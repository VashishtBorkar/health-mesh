from __future__ import annotations

import math
from collections import defaultdict, deque
from datetime import date, timedelta
from statistics import fmean

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from healthmesh.models import DayMetadata, ImportRecord, MetricDefinition, Observation


def date_range(session: Session, start: date | None, end: date | None) -> tuple[date | None, date | None]:
    observed_min, observed_max = session.execute(select(
        func.min(Observation.observed_date), func.max(Observation.observed_date)
    )).one()
    if observed_max is None:
        return None, None
    resolved_end = min(end, observed_max) if end else observed_max
    resolved_start = start or max(observed_min, resolved_end - timedelta(days=29))
    return resolved_start, resolved_end


def all_dates(start: date, end: date) -> list[date]:
    count = (end - start).days + 1
    return [start + timedelta(days=offset) for offset in range(count)]


def observation_map(
    session: Session,
    metric_keys: list[str],
    start: date,
    end: date,
) -> tuple[dict[str, dict[date, float]], dict[str, MetricDefinition]]:
    metrics = {
        metric.key: metric
        for metric in session.scalars(select(MetricDefinition).where(MetricDefinition.key.in_(metric_keys)))
    }
    values: dict[str, dict[date, float]] = defaultdict(dict)
    rows = session.execute(
        select(Observation.observed_date, Observation.value, MetricDefinition.key)
        .join(MetricDefinition, Observation.metric_id == MetricDefinition.id)
        .where(
            MetricDefinition.key.in_(metric_keys),
            Observation.observed_date >= start,
            Observation.observed_date <= end,
        )
        .order_by(Observation.observed_date)
    )
    for observed_date, value, key in rows:
        values[key][observed_date] = value
    return values, metrics


def rolling_values(dates: list[date], values: dict[date, float], window_days: int = 7) -> list[float | None]:
    window: deque[tuple[date, float]] = deque()
    output: list[float | None] = []
    for current in dates:
        if current in values:
            window.append((current, values[current]))
        cutoff = current - timedelta(days=window_days - 1)
        while window and window[0][0] < cutoff:
            window.popleft()
        output.append(round(fmean(value for _, value in window), 4) if len(window) >= 3 else None)
    return output


def timeseries_payload(
    session: Session,
    metric_keys: list[str],
    start: date | None,
    end: date | None,
    rolling: int = 7,
) -> dict[str, object]:
    start, end = date_range(session, start, end)
    if start is None or end is None:
        return {"dateRange": {"start": None, "end": None}, "series": []}
    dates = all_dates(start, end)
    values, definitions = observation_map(session, metric_keys, start, end)
    series = []
    for key in metric_keys:
        definition = definitions.get(key)
        if definition is None:
            continue
        metric_values = values.get(key, {})
        rolling_points = rolling_values(dates, metric_values, rolling)
        points = [
            {
                "date": current.isoformat(),
                "value": metric_values.get(current),
                "rollingAverage": rolling_points[index],
            }
            for index, current in enumerate(dates)
        ]
        series.append({
            "key": key,
            "label": definition.label,
            "unit": definition.unit,
            "domain": definition.domain,
            "observedCount": len(metric_values),
            "coverage": round(len(metric_values) / len(dates), 4),
            "points": points,
        })
    return {"dateRange": {"start": start.isoformat(), "end": end.isoformat()}, "series": series}


def _values_for_period(session: Session, key: str, start: date, end: date) -> list[tuple[date, float]]:
    return list(session.execute(
        select(Observation.observed_date, Observation.value)
        .join(MetricDefinition, Observation.metric_id == MetricDefinition.id)
        .where(
            MetricDefinition.key == key,
            Observation.observed_date >= start,
            Observation.observed_date <= end,
        )
        .order_by(Observation.observed_date)
    ))


def summary_metric(session: Session, key: str, start: date, end: date, mode: str = "average") -> dict[str, object]:
    current = _values_for_period(session, key, start, end)
    duration = (end - start).days + 1
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=duration - 1)
    previous = _values_for_period(session, key, previous_start, previous_end)
    if not current:
        return {"value": None, "count": 0, "change": None}
    if mode == "latest":
        value = current[-1][1]
        change = value - current[0][1] if len(current) > 1 else None
    else:
        value = fmean(value for _, value in current)
        previous_value = fmean(value for _, value in previous) if previous else None
        change = value - previous_value if previous_value is not None else None
    return {
        "value": round(value, 3),
        "count": len(current),
        "change": round(change, 3) if change is not None else None,
    }


def overview_payload(session: Session, start: date | None, end: date | None) -> dict[str, object]:
    start, end = date_range(session, start, end)
    if start is None or end is None:
        return {"dateRange": {"start": None, "end": None}, "hasData": False, "summaries": {}, "coverage": [], "latestImport": None}
    keys = [
        "sleep_duration_min", "steps", "calories_consumed_kcal", "weight_lb",
        "hrv_ms", "resting_heart_rate_bpm", "total_calories_burned_kcal",
    ]
    _, definitions = observation_map(session, keys, start, end)
    summaries = {
        "sleep": summary_metric(session, "sleep_duration_min", start, end),
        "steps": summary_metric(session, "steps", start, end),
        "calories": summary_metric(session, "calories_consumed_kcal", start, end),
        "weight": summary_metric(session, "weight_lb", start, end, "latest"),
    }
    span = (end - start).days + 1
    coverage = []
    for key, definition in definitions.items():
        count = len(_values_for_period(session, key, start, end))
        coverage.append({"key": key, "label": definition.label, "count": count, "days": span, "ratio": round(count / span, 4)})
    latest_import = session.scalar(select(ImportRecord).order_by(ImportRecord.created_at.desc()).limit(1))
    return {
        "dateRange": {"start": start.isoformat(), "end": end.isoformat()},
        "hasData": True,
        "summaries": summaries,
        "coverage": sorted(coverage, key=lambda item: item["label"]),
        "latestImport": {
            "id": latest_import.id,
            "filename": latest_import.filename,
            "createdAt": latest_import.created_at.isoformat(),
        } if latest_import else None,
    }


def pearson(pairs: list[tuple[float, float]]) -> float | None:
    if len(pairs) < 3:
        return None
    xs = [pair[0] for pair in pairs]
    ys = [pair[1] for pair in pairs]
    mean_x, mean_y = fmean(xs), fmean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    denom_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    denom_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if denom_x == 0 or denom_y == 0:
        return None
    return round(numerator / (denom_x * denom_y), 4)


def compare_payload(session: Session, x: str, y: str, start: date | None, end: date | None) -> dict[str, object]:
    start, end = date_range(session, start, end)
    if start is None or end is None:
        return {"dateRange": {"start": None, "end": None}, "xSeries": None, "ySeries": None, "pairs": [], "matchedCount": 0, "correlation": None}
    payload = timeseries_payload(session, [x, y], start, end)
    by_key = {series["key"]: series for series in payload["series"]}
    x_series, y_series = by_key.get(x), by_key.get(y)
    if x_series is None or y_series is None:
        return {
            "dateRange": payload["dateRange"],
            "xSeries": x_series,
            "ySeries": y_series,
            "pairs": [],
            "matchedCount": 0,
            "correlation": None,
        }
    x_values = {point["date"]: point["value"] for point in x_series["points"] if point["value"] is not None}
    y_values = {point["date"]: point["value"] for point in y_series["points"] if point["value"] is not None}
    dates = sorted(set(x_values) & set(y_values))
    pairs = [{"date": day, "x": x_values[day], "y": y_values[day]} for day in dates]
    numeric_pairs = [(pair["x"], pair["y"]) for pair in pairs]
    return {
        "dateRange": payload["dateRange"],
        "xSeries": x_series,
        "ySeries": y_series,
        "pairs": pairs,
        "matchedCount": len(pairs),
        "correlation": pearson(numeric_pairs),
    }


def nutrition_completeness(session: Session, start: date, end: date) -> dict[str, int]:
    values = list(session.scalars(select(DayMetadata.nutrition_completeness).where(
        DayMetadata.observed_date >= start,
        DayMetadata.observed_date <= end,
    )))
    return {
        "complete": sum(value == "complete" for value in values),
        "partial": sum(value == "partial" for value in values),
        "unknown": sum(value is None for value in values),
    }
