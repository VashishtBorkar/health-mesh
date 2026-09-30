from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from healthmesh.connectors import CSVConnector, CSVValidationError
from healthmesh.models import DayMetadata, ImportRecord, Observation, SourceRow
from healthmesh.services.imports import import_parsed_csv


def parse(text: str, filename: str = "health.csv"):
    return CSVConnector().parse(text.encode(), filename)


def test_parses_complete_and_subset_files() -> None:
    complete = """date,sleep_duration_min,sleep_efficiency_pct,deep_sleep_min,rem_sleep_min,light_sleep_min,hrv_ms,resting_heart_rate_bpm,respiratory_rate_bpm,steps,active_calories_kcal,total_calories_burned_kcal,workout_duration_min,training_load,calories_consumed_kcal,protein_g,carbohydrates_g,fat_g,fiber_g,nutrition_complete,weight_lb,body_fat_pct
2026-01-01,450,92,80,100,260,54,58,14.2,0,0,2200,0,0,2100,125,240,70,28,true,168.4,18.2
"""
    parsed = parse(complete)
    assert len(parsed.metric_columns) == 20
    assert parsed.rows[0].values["steps"] == 0
    assert parsed.rows[0].nutrition_completeness == "complete"

    subset = parse("date,weight_lb,notes\n2026-01-01,168.4,baseline\n")
    assert subset.metric_columns == ["weight_lb"]
    assert subset.rows[0].values == {"weight_lb": 168.4}
    assert subset.warnings == ["Ignored unknown columns: notes"]


def test_blank_is_missing_but_explicit_zero_is_preserved() -> None:
    parsed = parse("date,steps,active_calories_kcal\n2026-01-01,0,\n")
    assert parsed.rows[0].values == {"steps": 0.0}
    assert parsed.rows[0].ignored_values == 1


def test_rejects_invalid_files() -> None:
    invalid_files = [
        "date,steps\nnot-a-date,10\n",
        "date,steps\n2026-01-01,ten\n",
        "date,hrv_ms\n2026-01-01,nan\n",
        "date,hrv_ms\n2026-01-01,inf\n",
        "date,body_fat_pct\n2026-01-01,101\n",
        "date,steps\n2026-01-01,-1\n",
        "date,steps\n2026-01-01,1\n2026-01-01,2\n",
        "date,sleep_duration_min,deep_sleep_min,rem_sleep_min,light_sleep_min\n2026-01-01,400,100,100,250\n",
        "date,weight_lb,nutrition_complete\n2026-01-01,170,maybe\n",
    ]
    for content in invalid_files:
        try:
            parse(content)
        except CSVValidationError:
            continue
        raise AssertionError(f"Expected validation failure for {content!r}")


def test_rejects_oversized_file() -> None:
    content = b"date,steps\n" + b"x" * (10 * 1024 * 1024)
    try:
        CSVConnector().parse(content, "large.csv")
    except CSVValidationError as exc:
        assert exc.issues[0].code == "file_too_large"
    else:
        raise AssertionError("Expected an oversized file to be rejected")


def test_invalid_file_does_not_mutate_database(session: Session) -> None:
    try:
        parse("date,weight_lb\n2026-01-01,not-a-number\n")
    except CSVValidationError:
        pass
    assert session.scalar(select(func.count(ImportRecord.id))) == 0
    assert session.scalar(select(func.count(Observation.id))) == 0


def test_reimport_overlap_and_provenance(session: Session) -> None:
    first = import_parsed_csv(
        session,
        parse("date,steps,weight_lb,calories_consumed_kcal,nutrition_complete\n2026-01-01,1000,170,2000,true\n2026-01-02,0,169,0,\n", "first.csv"),
    )
    assert first.as_dict()["valuesCreated"] == 6
    assert session.scalar(select(func.count(SourceRow.id))) == 2

    duplicate = import_parsed_csv(
        session,
        parse("date,steps,weight_lb,calories_consumed_kcal,nutrition_complete\n2026-01-01,1000,170,2000,true\n2026-01-02,0,169,0,\n", "first.csv"),
    )
    assert duplicate.duplicate is True
    assert duplicate.as_dict()["valuesCreated"] == 0
    assert duplicate.as_dict()["rowsProcessed"] == 0
    assert session.scalar(select(func.count(ImportRecord.id))) == 1

    overlap = import_parsed_csv(
        session,
        parse("date,steps,weight_lb\n2026-01-01,1200,\n2026-01-02,0,168.5\n", "overlap.csv"),
    ).as_dict()
    assert overlap["valuesUpdated"] == 2
    assert overlap["valuesUnchanged"] == 1
    assert session.scalar(select(func.count(Observation.id))) == 6

    observations = list(session.scalars(select(Observation).order_by(Observation.observed_date, Observation.metric_id)))
    assert any(item.observed_date.isoformat() == "2026-01-01" and item.value == 170 for item in observations)
    metadata = list(session.scalars(select(DayMetadata).order_by(DayMetadata.observed_date)))
    assert metadata[0].nutrition_completeness == "complete"
    assert metadata[1].nutrition_completeness is None
