"""Focused adapters for Google Health Takeout and Cronometer Daily Nutrition.

Only selected measurements are read. Archives are never extracted. Output is
validated by the same canonical CSV connector used by the dashboard.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from zipfile import ZipFile
from zoneinfo import ZoneInfo

from healthmesh.connectors.csv_connector import CSVConnector, ParsedCSV
from healthmesh.metrics import METRIC_DEFINITIONS

VERSION = "personal-exports-v1"
NUTRITION = {
    "Energy (kcal)": "calories_consumed_kcal", "Protein (g)": "protein_g",
    "Carbs (g)": "carbohydrates_g", "Fat (g)": "fat_g", "Fiber (g)": "fiber_g",
}


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Google Health event timestamps must include a timezone")
    return parsed


def offset(value: str) -> timezone:
    sign = -1 if value.startswith("-") else 1
    hours, minutes = map(int, value.lstrip("+-").split(":"))
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def number(value: str, context: str) -> float | None:
    if not value.strip() or value.strip().upper() in {"N/A", "NA"}:
        return None
    result = float(value.replace(",", ""))
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"Invalid nonnegative measurement in {context}")
    return result


@dataclass
class Record:
    data: dict[str, str]
    file: str
    row: int

    def reference(self) -> dict:
        return {"file": self.file, "row": self.row}


@dataclass
class PersonalDataset:
    parsed: ParsedCSV
    csv_content: str
    report: dict


def read_archive(archive: ZipFile, group: str | None = None, prefix: str | None = None):
    for info in sorted(archive.infolist(), key=lambda item: item.filename):
        path = PurePosixPath(info.filename)
        if path.suffix != ".csv":
            continue
        if group and path.parent.name != group:
            continue
        if prefix and not (path.parent.name == "Health Fitness Data_GoogleData" and path.name.startswith(prefix)):
            continue
        # Do not read unrelated account, location, conversations, or sensor files.
        with archive.open(info) as binary:
            for index, row in enumerate(csv.DictReader(io.TextIOWrapper(binary, encoding="utf-8-sig")), 2):
                if None in row:
                    raise ValueError(f"Malformed CSV row {index} in {info.filename}")
                yield Record({k: (v or "").strip() for k, v in row.items()}, info.filename, index)


def build_personal_dataset(
    google_health: Path, cronometer: Path, *, through: date | None = None,
    nutrition_days_complete: bool = False, fallback_timezone: str = "America/New_York",
) -> PersonalDataset:
    with cronometer.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"Date", "Completed", *NUTRITION}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Expected Cronometer Daily Nutrition CSV with daily totals (disable diary group rows)")
        nutrition_records = []
        seen = set()
        for index, row in enumerate(reader, 2):
            if None in row:
                raise ValueError(f"Malformed Cronometer row {index}")
            row = {key: (value or "").strip() for key, value in row.items()}
            day = date.fromisoformat(row["Date"])
            if day in seen:
                raise ValueError("Cronometer contains duplicate dates; export daily totals without diary groups")
            seen.add(day)
            nutrition_records.append(Record(row, cronometer.name, index))
    if not nutrition_records:
        raise ValueError("Cronometer export contains no dates")
    # The newest export date may be unfinished. Keep it out unless explicitly requested.
    cutoff = through or max(seen) - timedelta(days=1)
    start = min(seen)
    if cutoff < start:
        raise ValueError("Import cutoff precedes the first nutrition date")
    days = [start + timedelta(days=i) for i in range((cutoff - start).days + 1)]
    values: dict[date, dict[str, float]] = defaultdict(dict)
    refs: dict[date, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    completions: dict[date, str] = {}
    original_completion: dict[date, str] = {}
    audit = Counter()
    warnings = [
        "The newest export day is excluded by default; --through can override the cutoff.",
        "Daily recovery timestamps are date labels; timed activity uses session-derived UTC offsets.",
        "Timezone between explicit session offsets is inferred from the latest preceding anchor; review travel dates.",
    ]

    def put(day: date, key: str, value: float | None, record: Record, *, additive=False):
        if not start <= day <= cutoff or value is None:
            return
        if key in values[day] and not additive and abs(values[day][key] - value) > 1e-7:
            raise ValueError(f"Conflicting {key} observations on {day}")
        values[day][key] = values[day].get(key, 0) + value if additive else value
        refs[day][key].append(record.reference())

    for record in nutrition_records:
        day = date.fromisoformat(record.data["Date"])
        if not start <= day <= cutoff:
            continue
        populated = False
        for column, key in NUTRITION.items():
            value = number(record.data[column], f"Cronometer {column} row {record.row}")
            put(day, key, value, record)
            populated |= value is not None
        flag = record.data["Completed"].lower()
        if flag not in {"true", "false", ""}:
            raise ValueError(f"Invalid Cronometer completion flag on row {record.row}")
        original_completion[day] = flag
        if populated:
            completions[day] = "true" if nutrition_days_complete or flag == "true" else "false" if flag == "false" else ""
    if nutrition_days_complete:
        warnings.append("Populated nutrition days are marked complete by explicit user confirmation; original flags are preserved in provenance.")

    with ZipFile(google_health) as archive:
        sleeps = list(read_archive(archive, prefix="UserSleeps_"))
        exercises = list(read_archive(archive, prefix="UserExercises_"))
        anchors = []
        for record in sleeps + exercises:
            row = record.data
            for time_key, offset_key in [("sleep_start", "start_utc_offset"), ("sleep_end", "end_utc_offset"), ("exercise_start", "utc_offset"), ("exercise_end", "utc_offset")]:
                if row.get(time_key) and row.get(offset_key):
                    anchors.append((instant(row[time_key]), row[offset_key]))
        anchors.sort()
        anchor_times = [item[0] for item in anchors]
        fallback = ZoneInfo(fallback_timezone)

        def local_day(timestamp: str) -> date:
            time = instant(timestamp)
            index = bisect_right(anchor_times, time) - 1
            zone = offset(anchors[index][1]) if index >= 0 else fallback
            if index < 0:
                audit["timestamps_using_fallback_timezone"] += 1
            return time.astimezone(zone).date()

        for group, column, key in [
            ("Daily Heart Rate Variability", "average heart rate variability milliseconds", "hrv_ms"),
            ("Daily Resting Heart Rate", "beats per minute", "resting_heart_rate_bpm"),
            ("Daily Respiratory Rate", "breaths per minute", "respiratory_rate_bpm"),
        ]:
            for record in read_archive(archive, group=group):
                # These exports encode the provider's daily label at midnight UTC.
                day = date.fromisoformat(record.data["timestamp"][:10])
                put(day, key, number(record.data[column], group), record)

        for group, column, key, source_kind in [
            ("Steps", "steps", "steps", "fitbit"),
            ("Calories", "calories", "total_calories_burned_kcal", "app"),
            ("Active Energy Burned", "Kilocalories", "active_calories_kcal", "app"),
            ("Cardio Load", "total", "training_load", "fitbit"),
        ]:
            seen_times = {}
            for record in read_archive(archive, group=group):
                source = record.data.get("data source", "").lower()
                accepted = "fitbit" in source if source_kind == "fitbit" else source == "google health app"
                if not accepted:
                    audit[f"{group}: excluded other-source rows"] += 1
                    continue
                stamp = record.data["timestamp"]
                value = number(record.data[column], group)
                if stamp in seen_times:
                    if seen_times[stamp] != value:
                        raise ValueError(f"Conflicting duplicate timestamp in {group}")
                    audit[f"{group}: identical duplicate rows skipped"] += 1
                    continue
                seen_times[stamp] = value
                put(local_day(stamp), key, value, record, additive=True)

        # Prefer the newer algorithm, then the most recently updated record.
        # Retain disjoint naps, but never add overlapping alternative sessions.
        sleeps.sort(key=lambda r: ("v2" in r.data.get("algorithm_version", ""), r.data.get("sleep_last_updated", "")), reverse=True)
        selected = []
        for record in sleeps:
            a, b = instant(record.data["sleep_start"]), instant(record.data["sleep_end"])
            if b <= a:
                raise ValueError("Sleep session has a nonpositive duration")
            if any(a < end and b > begin for begin, end, _ in selected):
                audit["overlapping_sleep_sessions_skipped"] += 1
                continue
            selected.append((a, b, record))
        selected_ids = {r.data["sleep_id"] for _, _, r in selected}
        stage_values = defaultdict(lambda: defaultdict(float))
        stage_refs = defaultdict(list)
        stage_keys = {"DEEP": "deep_sleep_min", "REM": "rem_sleep_min", "LIGHT": "light_sleep_min"}
        seen_stages = set()
        for record in read_archive(archive, prefix="UserSleepStages_"):
            row = record.data
            if row["sleep_id"] not in selected_ids or row["sleep_stage_type"] not in stage_keys:
                continue
            identity = row["sleep_stage_id"]
            if identity in seen_stages:
                continue
            seen_stages.add(identity)
            minutes = (instant(row["sleep_stage_end"]) - instant(row["sleep_stage_start"])).total_seconds() / 60
            if minutes < 0:
                raise ValueError("Sleep stage has a negative duration")
            stage_values[row["sleep_id"]][stage_keys[row["sleep_stage_type"]]] += minutes
            stage_refs[row["sleep_id"]].append(record.reference())
        sleep_period = defaultdict(float)
        for _, _, record in selected:
            row = record.data
            day = instant(row["sleep_end"]).astimezone(offset(row["end_utc_offset"])).date()
            minutes = number(row["minutes_asleep"], "minutes_asleep")
            put(day, "sleep_duration_min", minutes, record, additive=True)
            if start <= day <= cutoff:
                sleep_period[day] += number(row["minutes_in_sleep_period"], "sleep period") or 0
            stages = stage_values[row["sleep_id"]]
            if minutes is not None and sum(stages.values()) > minutes + 0.001:
                audit["sleep_sessions_with_inconsistent_stages_omitted"] += 1
                continue
            for key, value in stages.items():
                put(day, key, value, record, additive=True)
                if start <= day <= cutoff:
                    refs[day][key].extend(stage_refs[row["sleep_id"]])
        for day, period in sleep_period.items():
            duration = values[day].get("sleep_duration_min")
            if period > 0 and duration is not None and duration <= period:
                values[day]["sleep_efficiency_pct"] = duration / period * 100
                refs[day]["sleep_efficiency_pct"] = refs[day]["sleep_duration_min"]

        # Exercise duration is the union of recorded session intervals, split at
        # local midnight. Missing exercise records do not prove a zero-workout day.
        intervals = []
        for record in exercises:
            row = record.data
            if row.get("deletion_reason", "") not in {"", "UNSPECIFIED"}:
                audit["deleted_exercises_skipped"] += 1
                continue
            begin, end = instant(row["exercise_start"]), instant(row["exercise_end"])
            if end <= begin:
                raise ValueError("Exercise has a nonpositive duration")
            zone = offset(row["utc_offset"])
            cursor = begin
            while cursor < end:
                local = cursor.astimezone(zone)
                boundary = datetime.combine(local.date() + timedelta(days=1), datetime.min.time(), tzinfo=zone)
                stop = min(end, boundary)
                intervals.append((local.date(), cursor, stop, record))
                cursor = stop
        by_day = defaultdict(list)
        for day, begin, end, record in intervals:
            if start <= day <= cutoff:
                by_day[day].append((begin, end, record))
        for day, entries in by_day.items():
            merged = []
            for begin, end, record in sorted(entries, key=lambda x: x[0]):
                refs[day]["workout_duration_min"].append(record.reference())
                if merged and begin <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
                else:
                    merged.append((begin, end))
            values[day]["workout_duration_min"] = sum((b-a).total_seconds()/60 for a,b in merged)

        for record in read_archive(archive, group="Weight"):
            grams = number(record.data["weight grams"], "weight")
            put(local_day(record.data["timestamp"]), "weight_lb", grams / 453.59237 if grams is not None else None, record)

    columns = [key for key in METRIC_DEFINITIONS if any(key in item for item in values.values())]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["date", *columns, "nutrition_complete"], lineterminator="\n")
    writer.writeheader()
    for day in days:
        writer.writerow({"date": day.isoformat(), **{k: round(v, 6) for k,v in values[day].items()}, "nutrition_complete": completions.get(day, "")})
    content = output.getvalue()
    parsed = CSVConnector().parse(content.encode(), "Fitbit and Cronometer daily history.csv")
    manifest = {
        "adapterVersion": VERSION, "googleHealthSHA256": digest(google_health),
        "cronometerSHA256": digest(cronometer), "startDate": start.isoformat(),
        "endDate": cutoff.isoformat(), "nutritionDaysConfirmedComplete": nutrition_days_complete,
        "fallbackTimezone": fallback_timezone,
    }
    rows = []
    for row in parsed.rows:
        raw = dict(row.raw_payload)
        raw["_source_references"] = json.dumps(refs[row.observed_date], sort_keys=True)
        raw["_original_cronometer_completed"] = original_completion.get(row.observed_date, "")
        raw["_import_policy"] = json.dumps(manifest, sort_keys=True)
        rows.append(replace(row, raw_payload=raw))
    identity = hashlib.sha256((json.dumps(manifest, sort_keys=True) + content).encode()).hexdigest()
    parsed = replace(parsed, rows=rows, sha256=identity, warnings=warnings)
    coverage = []
    for key in METRIC_DEFINITIONS:
        present = [day for day in days if key in values[day]]
        longest = current = 0
        for day in days:
            current = 0 if key in values[day] else current + 1
            longest = max(longest, current)
        coverage.append({"metric": key, "observedDays": len(present), "totalDays": len(days),
                         "missingDays": len(days)-len(present), "longestMissingRun": longest,
                         "firstDate": present[0].isoformat() if present else None,
                         "lastDate": present[-1].isoformat() if present else None})
    def joint(keys):
        return sum(all(key in values[day] for key in keys) for day in days)
    report = {**manifest, "calendarDays": len(days), "coverage": coverage, "auditCounts": dict(audit),
              "overlap": {"hrvAndNutritionDays": joint(["hrv_ms", *NUTRITION.values()]),
                          "restingHeartRateAndNutritionDays": joint(["resting_heart_rate_bpm", *NUTRITION.values()])},
              "warnings": warnings,
              "definitions": {"training_load": "Sum of Fitbit cardio-load total increments; provider-specific units.",
                              "sleep_efficiency_pct": "minutes_asleep / minutes_in_sleep_period, aggregated across selected sessions.",
                              "workout_duration_min": "Union of recorded exercise intervals; days without logs remain missing."}}
    return PersonalDataset(parsed, content, report)
