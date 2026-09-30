from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from healthmesh.connectors import CSVConnector
from healthmesh.services.analytics import compare_payload, overview_payload, timeseries_payload
from healthmesh.services.imports import import_parsed_csv


def import_rows(session: Session, text: str) -> None:
    parsed = CSVConnector().parse(text.encode(), "analytics.csv")
    import_parsed_csv(session, parsed)


def test_averages_rolling_energy_balance_and_gaps(session: Session) -> None:
    import_rows(session, """date,sleep_duration_min,calories_consumed_kcal,total_calories_burned_kcal
2026-01-01,420,2000,2200
2026-01-02,,2100,2250
2026-01-03,450,,2300
2026-01-04,480,2400,2350
2026-01-05,510,2500,
2026-01-06,540,2600,2450
2026-01-07,570,2700,2500
""")
    overview = overview_payload(session, date(2026, 1, 1), date(2026, 1, 7))
    assert overview["summaries"]["sleep"] == {"value": 495.0, "count": 6, "change": None}

    payload = timeseries_payload(session, ["sleep_duration_min"], date(2026, 1, 1), date(2026, 1, 7))
    points = payload["series"][0]["points"]
    assert points[1]["value"] is None
    assert points[2]["rollingAverage"] is None
    assert points[3]["rollingAverage"] == 450

    intake = timeseries_payload(
        session,
        ["calories_consumed_kcal", "total_calories_burned_kcal"],
        date(2026, 1, 1),
        date(2026, 1, 7),
    )["series"]
    consumed = {p["date"]: p["value"] for p in intake[0]["points"]}
    burned = {p["date"]: p["value"] for p in intake[1]["points"]}
    balances = {
        day: consumed[day] - burned[day]
        for day in consumed
        if consumed[day] is not None and burned[day] is not None
    }
    assert balances == {
        "2026-01-01": -200,
        "2026-01-02": -150,
        "2026-01-04": 50,
        "2026-01-06": 150,
        "2026-01-07": 200,
    }


def test_compare_alignment_and_minimum_sample(session: Session) -> None:
    import_rows(session, """date,steps,weight_lb
2026-01-01,1000,170
2026-01-02,2000,
2026-01-03,3000,168
2026-01-04,,167
2026-01-05,5000,166
""")
    result = compare_payload(session, "steps", "weight_lb", date(2026, 1, 1), date(2026, 1, 5))
    assert result["matchedCount"] == 3
    assert [pair["date"] for pair in result["pairs"]] == ["2026-01-01", "2026-01-03", "2026-01-05"]
    assert result["correlation"] == -1.0

    short = compare_payload(session, "steps", "weight_lb", date(2026, 1, 1), date(2026, 1, 3))
    assert short["matchedCount"] == 2
    assert short["correlation"] is None

