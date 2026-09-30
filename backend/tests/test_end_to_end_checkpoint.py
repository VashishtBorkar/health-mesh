from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from healthmesh.db import get_session
from healthmesh.main import app
from healthmesh.models import Observation


def test_sample_import_dashboard_reimport_and_invalid_file(session: Session) -> None:
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    sample_path = Path(__file__).resolve().parents[2] / "fixtures" / "healthmesh_daily_sample.csv"
    sample = sample_path.read_bytes()
    try:
        imported = client.post(
            "/api/v1/imports/csv",
            files={"file": (sample_path.name, sample, "text/csv")},
        )
        assert imported.status_code == 200
        assert imported.json()["rowsProcessed"] == 90
        assert imported.json()["valuesCreated"] > 0

        overview = client.get("/api/v1/analytics/overview").json()
        assert overview["hasData"] is True
        assert overview["dateRange"] == {"start": "2026-03-02", "end": "2026-03-31"}
        assert overview["summaries"]["sleep"]["count"] > 0

        compared = client.get(
            "/api/v1/analytics/compare",
            params={"x": "steps", "y": "weight_lb", "start": "2026-01-01", "end": "2026-03-31"},
        ).json()
        assert compared["matchedCount"] > 3
        assert compared["correlation"] is not None

        count_before = session.scalar(select(func.count(Observation.id)))
        duplicate = client.post(
            "/api/v1/imports/csv",
            files={"file": (sample_path.name, sample, "text/csv")},
        )
        assert duplicate.json()["status"] == "duplicate"
        assert session.scalar(select(func.count(Observation.id))) == count_before

        overlap = client.post(
            "/api/v1/imports/csv",
            files={"file": ("overlap.csv", b"date,steps,weight_lb\n2026-03-31,12345,\n", "text/csv")},
        )
        assert overlap.json()["valuesUpdated"] == 1
        assert overlap.json()["valuesCreated"] == 0

        count_before_invalid = session.scalar(select(func.count(Observation.id)))
        invalid = client.post(
            "/api/v1/imports/csv",
            files={"file": ("invalid.csv", b"date,steps\n2026-03-31,nope\n", "text/csv")},
        )
        assert invalid.status_code == 422
        assert session.scalar(select(func.count(Observation.id))) == count_before_invalid
    finally:
        app.dependency_overrides.clear()

