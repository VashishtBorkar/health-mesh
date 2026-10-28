from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from zipfile import ZipFile

import pytest
from sqlalchemy import func, select

from healthmesh.connectors.personal_exports import build_personal_dataset
from healthmesh.models import DayMetadata, Observation, SourceRow
from healthmesh.services.imports import import_parsed_csv


def text_csv(rows: list[dict]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


@pytest.fixture
def exports(tmp_path):
    archive = tmp_path / "google.zip"
    nutrition = tmp_path / "nutrition.csv"
    def sleep(identifier, version, start, end, asleep):
        return {"sleep_id": identifier, "algorithm_version": version,
                "sleep_start": start, "sleep_end": end, "start_utc_offset": "-07:00",
                "end_utc_offset": "-07:00", "minutes_asleep": str(asleep),
                "minutes_in_sleep_period": "480" if asleep > 60 else "30", "sleep_last_updated": end}
    with ZipFile(archive, "w") as z:
        root = "Takeout/Google Health/"
        def add(group, name, rows):
            z.writestr(root + group + "/" + name, text_csv(rows))
        add("Health Fitness Data_GoogleData", "UserSleeps_fixture.csv", [
            sleep("old", "sleep_session_v1", "2026-08-14T04:00:00Z", "2026-08-14T12:00:00Z", 400),
            sleep("new", "sleep_session_v2", "2026-08-14T04:15:00Z", "2026-08-14T12:00:00Z", 420),
            sleep("nap", "sleep_session_v2", "2026-08-14T20:00:00Z", "2026-08-14T20:30:00Z", 20),
        ])
        add("Health Fitness Data_GoogleData", "UserSleepStages_fixture.csv", [
            {"sleep_id": "new", "sleep_stage_id": "deep", "sleep_stage_type": "DEEP", "sleep_stage_start": "2026-08-14T05:00:00Z", "sleep_stage_end": "2026-08-14T06:00:00Z"},
            {"sleep_id": "old", "sleep_stage_id": "olddeep", "sleep_stage_type": "DEEP", "sleep_stage_start": "2026-08-14T05:00:00Z", "sleep_stage_end": "2026-08-14T06:00:00Z"},
        ])
        add("Health Fitness Data_GoogleData", "UserExercises_fixture.csv", [
            {"exercise_start": "2026-08-15T06:30:00Z", "exercise_end": "2026-08-15T07:30:00Z", "utc_offset": "-07:00", "deletion_reason": "UNSPECIFIED"},
            {"exercise_start": "2026-08-15T06:45:00Z", "exercise_end": "2026-08-15T07:15:00Z", "utc_offset": "-07:00", "deletion_reason": "UNSPECIFIED"},
        ])
        add("Steps", "steps.csv", [
            {"timestamp": "2026-08-15T01:00:00Z", "steps": "100", "data source": "Fitbit Air"},
            {"timestamp": "2026-08-15T02:00:00Z", "steps": "200", "data source": "Fitbit Air"},
            {"timestamp": "2026-08-15T01:00:00Z", "steps": "999", "data source": "Phone Health Kit"},
        ])
        add("Calories", "calories.csv", [{"timestamp": "2026-08-15T01:00:00Z", "calories": "1500", "data source": "Google Health App"}])
        add("Daily Heart Rate Variability", "daily.csv", [{"timestamp": "2026-08-14T00:00:00Z", "average heart rate variability milliseconds": "55"}])
        add("Daily Resting Heart Rate", "daily.csv", [{"timestamp": "2026-08-14T00:00:00Z", "beats per minute": "60"}])
        add("Weight", "weight.csv", [{"timestamp": "2026-08-14T15:00:00Z", "weight grams": "45359.237", "data source": "Google Health App"}])
        z.writestr(root + "User Security Data/secret.csv", "this,is,not,a,measurement\n")
    nutrition.write_text(text_csv([
        {"Date": "2026-08-14", "Energy (kcal)": "2000", "Protein (g)": "100", "Carbs (g)": "250", "Fat (g)": "60", "Fiber (g)": "0", "Completed": "false"},
        {"Date": "2026-08-15", "Energy (kcal)": "", "Protein (g)": "", "Carbs (g)": "", "Fat (g)": "", "Fiber (g)": "", "Completed": "false"},
        {"Date": "2026-08-16", "Energy (kcal)": "1000", "Protein (g)": "50", "Carbs (g)": "125", "Fat (g)": "30", "Fiber (g)": "5", "Completed": "false"},
    ]), encoding="utf-8")
    return archive, nutrition


def test_local_days_sleep_dedup_and_source_selection(exports):
    dataset = build_personal_dataset(*exports, nutrition_days_complete=True)
    rows = {row.observed_date: row for row in dataset.parsed.rows}
    first = rows[date(2026, 8, 14)]
    assert first.values["sleep_duration_min"] == 440  # v2 plus disjoint nap
    assert first.values["deep_sleep_min"] == 60  # v1 stages excluded
    assert first.values["sleep_efficiency_pct"] == pytest.approx(440 / 510 * 100, abs=1e-6)
    assert first.values["steps"] == 300  # local evening, Fitbit only
    assert first.values["total_calories_burned_kcal"] == 1500
    assert first.values["calories_consumed_kcal"] == 2000
    assert first.values["weight_lb"] == 100
    assert first.values["hrv_ms"] == 55  # midnight UTC is a daily label
    assert dataset.report["auditCounts"]["overlapping_sleep_sessions_skipped"] == 1
    assert date(2026, 8, 16) not in rows  # potentially unfinished export day


def test_exercise_union_split_at_local_midnight(exports):
    dataset = build_personal_dataset(*exports)
    rows = {row.observed_date: row for row in dataset.parsed.rows}
    assert rows[date(2026, 8, 14)].values["workout_duration_min"] == 30
    assert rows[date(2026, 8, 15)].values["workout_duration_min"] == 30


def test_nutrition_confirmation_missing_zero_and_provenance(exports):
    dataset = build_personal_dataset(*exports, nutrition_days_complete=True)
    first, second = dataset.parsed.rows
    assert first.nutrition_completeness == "complete"
    assert first.values["fiber_g"] == 0
    assert second.nutrition_completeness is None
    assert "calories_consumed_kcal" not in second.values
    assert first.raw_payload["_original_cronometer_completed"] == "false"
    refs = json.loads(first.raw_payload["_source_references"])
    assert refs["calories_consumed_kcal"][0] == {"file": "nutrition.csv", "row": 2}
    assert build_personal_dataset(*exports).parsed.rows[0].nutrition_completeness == "partial"


def test_atomic_persistence_idempotency_and_source_rows(exports, session):
    dataset = build_personal_dataset(*exports, nutrition_days_complete=True)
    first = import_parsed_csv(session, dataset.parsed)
    count = session.scalar(select(func.count(Observation.id)))
    assert first.as_dict()["valuesCreated"] == count
    assert import_parsed_csv(session, dataset.parsed).duplicate
    assert session.scalar(select(func.count(Observation.id))) == count
    raw = session.scalar(select(SourceRow).where(SourceRow.row_number == 2))
    assert "_source_references" in raw.raw_payload
    assert session.scalar(select(DayMetadata)).nutrition_completeness == "complete"


def test_duplicate_nutrition_dates_rejected(exports):
    archive, nutrition = exports
    lines = nutrition.read_text().splitlines()
    nutrition.write_text("\n".join([*lines, lines[1]]) + "\n")
    with pytest.raises(ValueError, match="duplicate dates"):
        build_personal_dataset(archive, nutrition)


def test_invalid_source_values_reject_conversion(exports):
    archive, nutrition = exports
    nutrition.write_text(nutrition.read_text().replace("2000", "nan"))
    with pytest.raises(ValueError, match="Invalid nonnegative"):
        build_personal_dataset(archive, nutrition)


def test_cutoff_and_changed_content_change_import_identity(exports):
    original = build_personal_dataset(*exports)
    repeated = build_personal_dataset(*exports)
    assert original.parsed.sha256 == repeated.parsed.sha256
    extended = build_personal_dataset(*exports, through=date(2026, 8, 16))
    assert len(extended.parsed.rows) == 3
    assert extended.parsed.sha256 != original.parsed.sha256
    coverage = {item["metric"]: item for item in original.report["coverage"]}
    assert coverage["calories_consumed_kcal"]["observedDays"] == 1
    assert coverage["calories_consumed_kcal"]["missingDays"] == 1
    assert coverage["body_fat_pct"]["observedDays"] == 0


def test_personal_cli_creates_isolated_database_and_reimports(exports, tmp_path):
    archive, nutrition = exports
    destination = tmp_path / "personal.db"
    output = tmp_path / "processed"
    command = [sys.executable, "-m", "healthmesh.personal_import", "--google-health", str(archive),
               "--cronometer", str(nutrition), "--database", str(destination),
               "--output-dir", str(output), "--nutrition-days-complete"]
    # A pre-existing override must not redirect this explicit destination.
    env = {**os.environ, "HEALTHMESH_DATABASE_URL": "sqlite:///should-not-exist.db"}
    first = subprocess.run(command, check=True, capture_output=True, text=True, env=env)
    assert json.loads(first.stdout)["status"] == "completed"
    assert destination.exists()
    assert (output / "coverage_report.md").exists()
    report = json.loads((output / "coverage_report.json").read_text())
    assert report["verifiedObservationCount"] > 0
    second = subprocess.run(command, check=True, capture_output=True, text=True, env=env)
    assert json.loads(second.stdout)["status"] == "duplicate"
    preview = subprocess.run([*command, "--preview"], check=True, capture_output=True, text=True, env=env)
    assert json.loads(preview.stdout)["calendarDays"] == 2


def test_personal_database_profile_is_separate(monkeypatch, tmp_path):
    from healthmesh.db import database_url
    monkeypatch.delenv("HEALTHMESH_DATABASE_URL", raising=False)
    monkeypatch.setenv("HEALTHMESH_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("HEALTHMESH_PROFILE", raising=False)
    assert database_url().endswith("/healthmesh.db")
    monkeypatch.setenv("HEALTHMESH_PROFILE", "personal")
    assert database_url().endswith("/healthmesh-personal.db")
