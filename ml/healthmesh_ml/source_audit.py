"""Read-only audit of development measurements against selected Takeout files."""
from __future__ import annotations

import csv
import hashlib
import io
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from .data import DailyDataset


def time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Source audit requires explicit UTC event timestamps")
    return result


def zone(value: str) -> timezone:
    sign = -1 if value.startswith("-") else 1
    hours, minutes = map(int,value.lstrip("+-").split(":"))
    return timezone(sign*timedelta(hours=hours,minutes=minutes))


def audit_sources(dataset: DailyDataset, archive_path: Path, cutoff: date, target="hrv_ms") -> dict:
    if any(day > cutoff for day in dataset.dates):
        raise ValueError("Source audit must receive development data only")
    raw_hrv = {}
    sleeps = []
    with ZipFile(archive_path) as archive:
        for info in archive.infolist():
            path = PurePosixPath(info.filename)
            is_hrv = path.parent.name == "Daily Heart Rate Variability"
            is_sleep = path.parent.name == "Health Fitness Data_GoogleData" and path.name.startswith("UserSleeps_")
            if path.suffix != ".csv" or not (is_hrv or is_sleep):
                continue
            with archive.open(info) as handle:
                reader = csv.DictReader(io.TextIOWrapper(handle,encoding="utf-8-sig"))
                for index,row in enumerate(reader,2):
                    if is_hrv:
                        day = date.fromisoformat(row["timestamp"][:10])
                        if day > cutoff:
                            continue
                        if day in raw_hrv:
                            raise ValueError(f"Duplicate source daily HRV label: {day}")
                        raw_hrv[day] = {"value":float(row["average heart rate variability milliseconds"]),
                                        "timestamp":row["timestamp"], "file":info.filename, "row":index}
                    else:
                        end = time(row["sleep_end"])
                        wake_date = end.astimezone(zone(row["end_utc_offset"])).date()
                        if wake_date <= cutoff:
                            sleeps.append(row)
    # Recompute the documented source selection and local wake-date aggregation.
    # App screenshots are not available, so this verifies export consistency only.
    sleeps.sort(key=lambda row:("v2" in row.get("algorithm_version",""),row.get("sleep_last_updated","")),reverse=True)
    intervals = []
    sleep_minutes = defaultdict(float)
    offsets = defaultdict(set)
    utc_wake_dates = defaultdict(set)
    skipped = 0
    for row in sleeps:
        begin,end = time(row["sleep_start"]),time(row["sleep_end"])
        if any(begin < b and end > a for a,b in intervals):
            skipped += 1
            continue
        intervals.append((begin,end))
        wake = end.astimezone(zone(row["end_utc_offset"])).date()
        sleep_minutes[wake] += float(row["minutes_asleep"])
        offsets[wake].add(row["end_utc_offset"])
        utc_wake_dates[wake].add(end.date().isoformat())
    checked_hrv = checked_sleep = 0
    mismatches = []
    canonical = dict(zip(dataset.dates,dataset.rows))
    records = []
    for day,row in canonical.items():
        if row[target] is not None:
            raw = raw_hrv.get(day)
            matched = raw is not None and abs(raw["value"]-row[target]) <= 1e-6
            checked_hrv += 1
            if not matched:
                mismatches.append({"date":day.isoformat(),"metric":target})
            records.append({"date":day.isoformat(),"canonicalHRV":row[target],
                            "sourceHRV":raw["value"] if raw else None,
                            "rawTimestamp":raw["timestamp"] if raw else None,"matches":matched,
                            "sourceFile":raw["file"] if raw else None,"sourceRow":raw["row"] if raw else None,
                            "sleepMinutes":row.get("sleep_duration_min"),
                            "sleepMinutesFromSelectedSources":sleep_minutes.get(day),
                            "sleepEndOffsets":sorted(offsets[day]),"sleepUTCWakeDates":sorted(utc_wake_dates[day])})
        sleep = row.get("sleep_duration_min")
        if sleep is not None:
            checked_sleep += 1
            if day not in sleep_minutes or abs(sleep_minutes[day]-sleep) > 1e-6:
                mismatches.append({"date":day.isoformat(),"metric":"sleep_duration_min"})
    jumps = []
    previous = None
    by_date = {entry["date"]:entry for entry in records}
    for day,row in canonical.items():
        if row[target] is None:
            continue
        if previous:
            prior_day,prior_value = previous
            jumps.append({"date":day.isoformat(),"previousDate":prior_day.isoformat(),
                          "calendarGapDays":(day-prior_day).days,"previousHRV":prior_value,
                          "actualHRV":row[target],"absoluteChange":abs(row[target]-prior_value),
                          "sourceMatches":by_date[day.isoformat()]["matches"],
                          "sourceTimestamp":by_date[day.isoformat()]["rawTimestamp"],
                          "sleepEndOffsets":by_date[day.isoformat()]["sleepEndOffsets"]})
        previous = day,row[target]
    jumps.sort(key=lambda entry:entry["absoluteChange"],reverse=True)
    with archive_path.open("rb") as handle:
        archive_hash = hashlib.file_digest(handle,"sha256").hexdigest()
    return {"cutoff":cutoff.isoformat(),"archiveSHA256":archive_hash,
            "checkedHRV":checked_hrv,"checkedSleepDays":checked_sleep,"mismatches":mismatches,
            "allCheckedValuesMatch":not mismatches,
            "allRecoveryLabelsAtMidnightUTC":all(entry["timestamp"].endswith("T00:00:00Z") for entry in raw_hrv.values()),
            "overlappingSleepAlternativesExcluded":skipped,
            "records":records,"largestJumps":jumps[:5],
            "interpretation":"Export values and recorded sleep offsets checked; device accuracy and source-app display have not been independently verified. No readings removed."}
