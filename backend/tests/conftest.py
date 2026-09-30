from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

# Keep application imports from touching the real platform data directory.
os.environ.setdefault("HEALTHMESH_DATABASE_URL", "sqlite://")

from healthmesh.metrics import METRIC_DEFINITIONS
from healthmesh.models import Base, DataSource, MetricDefinition


@pytest.fixture()
def session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as database:
        database.add(DataSource(key="healthmesh_csv", name="HealthMesh CSV", connector_type="file"))
        database.add_all(MetricDefinition(**definition) for definition in METRIC_DEFINITIONS.values())
        database.commit()
        yield database
    Base.metadata.drop_all(engine)
