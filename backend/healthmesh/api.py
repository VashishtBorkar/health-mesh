from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from healthmesh.connectors import CSVConnector, CSVValidationError
from healthmesh.db import get_session
from healthmesh.metrics import METRIC_DEFINITIONS
from healthmesh.models import ImportRecord, MetricDefinition, Observation
from healthmesh.schemas import CoachRequest
from healthmesh.services.analytics import compare_payload, date_range, nutrition_completeness, overview_payload, timeseries_payload
from healthmesh.services.imports import import_parsed_csv
from healthmesh.settings import fixtures_directory

router = APIRouter(prefix="/api/v1")


@router.get("/health")
def health(session: Session = Depends(get_session)) -> dict[str, object]:
    session.execute(select(1))
    return {"status": "ok", "database": "connected"}


@router.get("/capabilities")
def capabilities() -> dict[str, bool]:
    return {"dataPlatform": True, "coach": False, "insights": False}


@router.post("/imports/csv")
async def import_csv(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    content = await file.read()
    connector = CSVConnector()
    try:
        parsed = connector.parse(content, file.filename or "healthmesh.csv")
    except CSVValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "invalid_csv",
                "message": "The CSV could not be imported.",
                "errors": [issue.as_dict() for issue in exc.issues],
                "warnings": exc.warnings,
            },
        ) from exc
    return import_parsed_csv(session, parsed).as_dict()


@router.get("/imports")
def imports(session: Session = Depends(get_session)) -> dict[str, object]:
    records = session.scalars(select(ImportRecord).order_by(ImportRecord.created_at.desc())).all()
    return {
        "items": [
            {
                "id": record.id,
                "filename": record.filename,
                "sha256": record.sha256,
                "status": record.status,
                "columns": record.imported_columns,
                "dateRange": {
                    "start": record.start_date.isoformat() if record.start_date else None,
                    "end": record.end_date.isoformat() if record.end_date else None,
                },
                "rowsProcessed": record.rows_processed,
                "valuesCreated": record.values_created,
                "valuesUpdated": record.values_updated,
                "valuesUnchanged": record.values_unchanged,
                "valuesIgnored": record.values_ignored,
                "warnings": record.warnings,
                "createdAt": record.created_at.isoformat(),
            }
            for record in records
        ]
    }


@router.get("/metrics")
def metrics(session: Session = Depends(get_session)) -> dict[str, object]:
    definitions = session.scalars(select(MetricDefinition).order_by(MetricDefinition.domain, MetricDefinition.label)).all()
    coverage_rows = session.execute(
        select(
            MetricDefinition.key,
            func.count(Observation.id),
            func.min(Observation.observed_date),
            func.max(Observation.observed_date),
        )
        .outerjoin(Observation, Observation.metric_id == MetricDefinition.id)
        .group_by(MetricDefinition.id)
    )
    coverage = {
        key: {"count": count, "start": start.isoformat() if start else None, "end": end.isoformat() if end else None}
        for key, count, start, end in coverage_rows
    }
    overall_start, overall_end = session.execute(select(
        func.min(Observation.observed_date), func.max(Observation.observed_date)
    )).one()
    return {
        "dateRange": {
            "start": overall_start.isoformat() if overall_start else None,
            "end": overall_end.isoformat() if overall_end else None,
        },
        "items": [
            {
                "key": definition.key,
                "domain": definition.domain,
                "label": definition.label,
                "unit": definition.unit,
                "aggregation": definition.aggregation,
                "display": definition.display_config,
                "coverage": coverage[definition.key],
            }
            for definition in definitions
        ],
    }


@router.get("/analytics/overview")
def analytics_overview(
    start: date | None = None,
    end: date | None = None,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return overview_payload(session, start, end)


@router.get("/analytics/timeseries")
def analytics_timeseries(
    metrics: str = Query(..., min_length=1),
    start: date | None = None,
    end: date | None = None,
    rolling: int = Query(7, ge=1, le=30),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    keys = list(dict.fromkeys(key.strip() for key in metrics.split(",") if key.strip()))
    invalid = [key for key in keys if key not in METRIC_DEFINITIONS]
    if invalid:
        raise HTTPException(422, detail={"code": "unknown_metric", "metrics": invalid})
    return timeseries_payload(session, keys, start, end, rolling)


@router.get("/analytics/compare")
def analytics_compare(
    x: str,
    y: str,
    start: date | None = None,
    end: date | None = None,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    invalid = [key for key in [x, y] if key not in METRIC_DEFINITIONS]
    if invalid:
        raise HTTPException(422, detail={"code": "unknown_metric", "metrics": invalid})
    return compare_payload(session, x, y, start, end)


@router.get("/analytics/nutrition-completeness")
def analytics_nutrition_completeness(
    start: date | None = None,
    end: date | None = None,
    session: Session = Depends(get_session),
) -> dict[str, int]:
    resolved_start, resolved_end = date_range(session, start, end)
    if resolved_start is None or resolved_end is None:
        return {"complete": 0, "partial": 0, "unknown": 0}
    return nutrition_completeness(session, resolved_start, resolved_end)


@router.get("/insights")
def insights() -> dict[str, object]:
    return {"enabled": False, "items": []}


@router.post("/coach/query", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def coach_query(request: CoachRequest) -> dict[str, str]:
    del request
    return {
        "code": "feature_not_available",
        "message": "The local HealthMesh coach is planned for a later phase.",
    }


@router.get("/downloads/template")
def download_template() -> FileResponse:
    path = fixtures_directory() / "healthmesh_daily_template.csv"
    return FileResponse(path, filename=path.name, media_type="text/csv")


@router.get("/downloads/sample")
def download_sample() -> FileResponse:
    path = fixtures_directory() / "healthmesh_daily_sample.csv"
    return FileResponse(path, filename=path.name, media_type="text/csv")
