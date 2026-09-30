"""Create the phase-one health data schema.

Revision ID: 0001
Revises: None
"""
from __future__ import annotations

from alembic import op
from sqlalchemy.orm import Session

from healthmesh.metrics import METRIC_DEFINITIONS
from healthmesh.models import Base, DataSource, MetricDefinition

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    session = Session(bind=bind)
    session.add(DataSource(key="healthmesh_csv", name="HealthMesh CSV", connector_type="file"))
    for metric in METRIC_DEFINITIONS.values():
        session.add(MetricDefinition(**metric))
    session.commit()


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())

