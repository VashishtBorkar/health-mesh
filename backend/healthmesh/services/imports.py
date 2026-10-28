from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthmesh.connectors import ParsedCSV
from healthmesh.models import (
    DataSource,
    DayMetadata,
    ImportRecord,
    MetricDefinition,
    Observation,
    SourceRow,
)


NUTRITION_METRICS = {
    "calories_consumed_kcal",
    "protein_g",
    "carbohydrates_g",
    "fat_g",
    "fiber_g",
}


@dataclass(frozen=True)
class ImportResult:
    import_record: ImportRecord
    duplicate: bool = False

    def as_dict(self) -> dict[str, object]:
        record = self.import_record
        no_op = self.duplicate
        return {
            "importId": record.id,
            "status": "duplicate" if no_op else record.status,
            "filename": record.filename,
            "dateRange": {
                "start": record.start_date.isoformat() if record.start_date else None,
                "end": record.end_date.isoformat() if record.end_date else None,
            },
            "rowsProcessed": 0 if no_op else record.rows_processed,
            "valuesCreated": 0 if no_op else record.values_created,
            "valuesUpdated": 0 if no_op else record.values_updated,
            "valuesUnchanged": 0 if no_op else record.values_unchanged,
            "valuesIgnored": 0 if no_op else record.values_ignored,
            "warnings": (["Exact file hash was already imported; no data changed."] if no_op else record.warnings),
        }


def import_parsed_csv(session: Session, parsed: ParsedCSV, *, source_key: str = "healthmesh_csv") -> ImportResult:
    duplicate = session.scalar(select(ImportRecord).where(ImportRecord.sha256 == parsed.sha256))
    if duplicate:
        return ImportResult(duplicate, duplicate=True)

    source = session.scalar(select(DataSource).where(DataSource.key == source_key))
    if source is None:
        raise RuntimeError(f"Data source {source_key} is not configured")

    metrics = {
        metric.key: metric
        for metric in session.scalars(select(MetricDefinition).where(MetricDefinition.key.in_(parsed.metric_columns)))
    }
    record = ImportRecord(
        source_id=source.id,
        filename=parsed.filename,
        sha256=parsed.sha256,
        imported_columns=parsed.metric_columns,
        start_date=parsed.start_date,
        end_date=parsed.end_date,
        rows_processed=len(parsed.rows),
        warnings=parsed.warnings,
    )
    session.add(record)
    session.flush()

    created = updated = unchanged = ignored = 0
    for row in parsed.rows:
        session.add(SourceRow(
            import_id=record.id,
            row_number=row.row_number,
            observed_date=row.observed_date,
            checksum=row.checksum,
            raw_payload=row.raw_payload,
        ))
        ignored += row.ignored_values
        for key, value in row.values.items():
            metric = metrics[key]
            observation = session.scalar(select(Observation).where(
                Observation.source_id == source.id,
                Observation.observed_date == row.observed_date,
                Observation.metric_id == metric.id,
            ))
            if observation is None:
                session.add(Observation(
                    source_id=source.id,
                    observed_date=row.observed_date,
                    metric_id=metric.id,
                    value=value,
                    quality="observed",
                    latest_import_id=record.id,
                ))
                created += 1
            elif abs(observation.value - value) > 1e-9:
                observation.value = value
                observation.latest_import_id = record.id
                updated += 1
            else:
                unchanged += 1

        # A blank completeness flag still means "unknown" when nutrition was
        # recorded. Persisting that state lets the UI distinguish it from a day
        # that has no nutrition data at all.
        has_nutrition_data = bool(NUTRITION_METRICS.intersection(row.values))
        if row.nutrition_completeness is not None or has_nutrition_data:
            metadata = session.scalar(select(DayMetadata).where(
                DayMetadata.source_id == source.id,
                DayMetadata.observed_date == row.observed_date,
            ))
            if metadata is None:
                session.add(DayMetadata(
                    source_id=source.id,
                    observed_date=row.observed_date,
                    nutrition_completeness=row.nutrition_completeness,
                    latest_import_id=record.id,
                ))
            else:
                # Blank cells never erase prior information. An existing
                # complete/partial flag is updated only by an explicit value.
                if row.nutrition_completeness is not None:
                    metadata.nutrition_completeness = row.nutrition_completeness
                metadata.latest_import_id = record.id

    record.values_created = created
    record.values_updated = updated
    record.values_unchanged = unchanged
    record.values_ignored = ignored
    session.commit()
    session.refresh(record)
    return ImportResult(record)
