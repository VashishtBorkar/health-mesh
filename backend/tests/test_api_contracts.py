from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from healthmesh.db import get_session
from healthmesh.main import app


def test_disabled_intelligence_contracts(session: Session) -> None:
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        assert client.get("/api/v1/capabilities").json() == {
            "dataPlatform": True,
            "coach": False,
            "insights": False,
        }
        assert client.get("/api/v1/insights").json() == {"enabled": False, "items": []}
        response = client.post("/api/v1/coach/query", json={
            "message": "What changed?",
            "context": {
                "route": "/sleep",
                "startDate": "2026-01-01",
                "endDate": "2026-01-30",
                "metricKeys": ["sleep_duration_min"],
            },
        })
        assert response.status_code == 501
        assert response.json()["code"] == "feature_not_available"
    finally:
        app.dependency_overrides.clear()

