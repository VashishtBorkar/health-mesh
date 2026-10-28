from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path


@dataclass(frozen=True)
class DailyDataset:
    dates: tuple[date, ...]
    rows: tuple[dict[str, float | None], ...]
    sha256: str


@dataclass(frozen=True)
class Window:
    target_date: date
    context_dates: tuple[date, ...]
    history: tuple[dict[str, float | None], ...]
    actual: float | None


def load_config(path: Path) -> dict:
    config = json.loads(path.read_text())
    if config["horizonDays"] != 1:
        raise ValueError("This experiment supports next-day forecasting only")
    if not 1 <= config["minTargetObservations"] <= config["contextDays"]:
        raise ValueError("Invalid target observation requirement")
    if config["contextDays"] < 7 or config["minimumTrainingExamples"] < 2 or config["ridgeAlpha"] <= 0:
        raise ValueError("Context must be at least seven days and ridge regularization must be positive")
    if not date.fromisoformat(config["trainEnd"]) < date.fromisoformat(config["validationEnd"]) < date.fromisoformat(config["testEnd"]):
        raise ValueError("Train, validation, and test boundaries must be chronological")
    if config["quantiles"] != [0.1, 0.5, 0.9]:
        raise ValueError("The initial experiment uses q10, q50, q90")
    for keys in config["featureGroups"].values():
        if config["target"] not in keys or len(keys) != len(set(keys)):
            raise ValueError("Each feature group must contain the target once")
    return config


def read_dataset(path: Path, config: dict) -> DailyDataset:
    required = set().union(*config["featureGroups"].values())
    content = path.read_bytes()
    records = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not {"date", *required}.issubset(reader.fieldnames or []):
            raise ValueError("Dataset is missing required daily metric columns")
        for row in reader:
            if None in row:
                raise ValueError("Malformed daily dataset row")
            day = date.fromisoformat(row["date"])
            if day in records:
                raise ValueError("Dataset contains duplicate dates")
            metrics = {}
            for key in required:
                text = (row[key] or "").strip()
                value = float(text) if text else None
                if value is not None and (not math.isfinite(value) or value < 0):
                    raise ValueError(f"Invalid measurement for {key} on {day}")
                metrics[key] = value
            records[day] = metrics
    if not records:
        raise ValueError("Dataset is empty")
    dates = tuple(min(records) + timedelta(days=i) for i in range((max(records)-min(records)).days+1))
    if max(dates) < date.fromisoformat(config["testEnd"]):
        raise ValueError("Dataset does not reach the configured final test date")
    if (date.fromisoformat(config["trainEnd"]) - min(dates)).days < config["contextDays"]:
        raise ValueError("Insufficient initial training history")
    empty = {key: None for key in required}
    return DailyDataset(dates, tuple(records.get(day, dict(empty)) for day in dates), hashlib.sha256(content).hexdigest())


def windows(dataset: DailyDataset, config: dict, stage: str) -> list[Window]:
    if stage not in {"train", "validation", "test"}:
        raise ValueError("Unknown evaluation stage")
    train_end, val_end, test_end = (date.fromisoformat(config[k]) for k in ("trainEnd", "validationEnd", "testEnd"))
    width = config["contextDays"]
    result = []
    for index in range(width, len(dataset.dates)):
        day = dataset.dates[index]
        included = day <= train_end if stage == "train" else train_end < day <= val_end if stage == "validation" else val_end < day <= test_end
        if not included:
            continue
        history = dataset.rows[index-width:index]
        # Eligibility depends only on past target coverage, never current/future covariates.
        if sum(row[config["target"]] is not None for row in history) < config["minTargetObservations"]:
            continue
        result.append(Window(day, dataset.dates[index-width:index], history, dataset.rows[index][config["target"]]))
    return result


def public_window(window: Window, config: dict) -> dict:
    keys = sorted(set().union(*config["featureGroups"].values()))
    return {"targetDate": window.target_date.isoformat(), "contextDates": [day.isoformat() for day in window.context_dates],
            "history": {key: [row[key] for row in window.history] for key in keys},
            "observedMask": {key: [row[key] is not None for row in window.history] for key in keys},
            "actual": window.actual}


def dataset_manifest(dataset: DailyDataset, config: dict) -> dict:
    # No test target statistics or test windows are produced during development.
    stage_counts = {stage: {"windows": len(windows(dataset, config, stage)),
                            "observedTargets": sum(w.actual is not None for w in windows(dataset, config, stage))}
                    for stage in ("train", "validation")}
    return {"datasetSHA256": dataset.sha256, "calendarDays": len(dataset.dates),
            "firstDate": dataset.dates[0].isoformat(), "lastDate": dataset.dates[-1].isoformat(),
            "developmentCoverage": stage_counts, "testStatus": "held out; not evaluated",
            "predictionTiming": "At end of D, forecast HRV assigned to D+1 using observations through D.",
            "limitation": "Retrospective backtest assumes prior-day summaries were available; provider release delays are not replayed."}
