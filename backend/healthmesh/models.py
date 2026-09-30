from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    connector_type: Mapped[str] = mapped_column(String(40))


class ImportRecord(Base):
    __tablename__ = "imports"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="completed")
    imported_columns: Mapped[list[str]] = mapped_column(JSON, default=list)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    rows_processed: Mapped[int] = mapped_column(Integer, default=0)
    values_created: Mapped[int] = mapped_column(Integer, default=0)
    values_updated: Mapped[int] = mapped_column(Integer, default=0)
    values_unchanged: Mapped[int] = mapped_column(Integer, default=0)
    values_ignored: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    source: Mapped[DataSource] = relationship()


class SourceRow(Base):
    __tablename__ = "source_rows"
    __table_args__ = (UniqueConstraint("import_id", "row_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    import_id: Mapped[int] = mapped_column(ForeignKey("imports.id", ondelete="CASCADE"), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    observed_date: Mapped[date] = mapped_column(Date, index=True)
    checksum: Mapped[str] = mapped_column(String(64))
    raw_payload: Mapped[dict[str, str]] = mapped_column(JSON)


class MetricDefinition(Base):
    __tablename__ = "metric_definitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    domain: Mapped[str] = mapped_column(String(40), index=True)
    label: Mapped[str] = mapped_column(String(160))
    unit: Mapped[str] = mapped_column(String(40))
    value_type: Mapped[str] = mapped_column(String(30), default="number")
    aggregation: Mapped[str] = mapped_column(String(30), default="mean")
    display_config: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (UniqueConstraint("source_id", "observed_date", "metric_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    observed_date: Mapped[date] = mapped_column(Date, index=True)
    metric_id: Mapped[int] = mapped_column(ForeignKey("metric_definitions.id"), index=True)
    value: Mapped[float] = mapped_column(Float)
    quality: Mapped[str] = mapped_column(String(30), default="observed")
    latest_import_id: Mapped[int] = mapped_column(ForeignKey("imports.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    metric: Mapped[MetricDefinition] = relationship()


class DayMetadata(Base):
    __tablename__ = "day_metadata"
    __table_args__ = (UniqueConstraint("source_id", "observed_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), index=True)
    observed_date: Mapped[date] = mapped_column(Date, index=True)
    nutrition_completeness: Mapped[str | None] = mapped_column(String(20), nullable=True)
    latest_import_id: Mapped[int] = mapped_column(ForeignKey("imports.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

