from __future__ import annotations

import math
from statistics import fmean, median

from .data import Window
from .models import Forecast


def score(examples: list[Window], predictions: dict[str, list[Forecast]]) -> dict:
    if not predictions or any(len(values) != len(examples) for values in predictions.values()):
        raise ValueError("Each model must forecast the same examples")
    paired = [i for i,w in enumerate(examples) if w.actual is not None
              and all(forecasts[i].point is not None for forecasts in predictions.values())]
    observed = sum(w.actual is not None for w in examples)
    results = {}
    for model, forecasts in predictions.items():
        errors = [forecasts[i].point-examples[i].actual for i in paired]
        metrics = {"matchedCount": len(paired), "mae": fmean(abs(e) for e in errors) if errors else None,
                   "medianAbsoluteError": float(median(abs(e) for e in errors)) if errors else None,
                   "rmse": math.sqrt(fmean(e*e for e in errors)) if errors else None,
                   "bias": fmean(errors) if errors else None}
        probabilistic = [i for i in paired if forecasts[i].lower is not None and forecasts[i].upper is not None]
        if probabilistic:
            losses = []
            for i in probabilistic:
                for q,predicted in [(0.1,forecasts[i].lower),(0.5,forecasts[i].point),(0.9,forecasts[i].upper)]:
                    residual = examples[i].actual-predicted
                    losses.append(max(q*residual, (q-1)*residual))
            metrics.update(intervalNominalCoverage=0.8,
                           intervalObservedCoverage=fmean(float(forecasts[i].lower <= examples[i].actual <= forecasts[i].upper) for i in probabilistic),
                           intervalMeanWidth=fmean(forecasts[i].upper-forecasts[i].lower for i in probabilistic),
                           meanPinballLoss=fmean(losses))
        results[model] = metrics
    return {"forecastDays": len(examples), "observedTargetDays": observed, "pairedScoredDays": len(paired),
            "missingTargetDays": len(examples)-observed, "observedDaysExcludedForMissingForecast": observed-len(paired),
            "pairedDates": [examples[i].target_date.isoformat() for i in paired], "models": results}


def prediction_records(examples: list[Window], predictions: dict[str, list[Forecast]]) -> list[dict]:
    return [{"date": w.target_date.isoformat(), "contextStart": w.context_dates[0].isoformat(),
             "contextEnd": w.context_dates[-1].isoformat(), "model": model, "actual": w.actual,
             "prediction": predictions[model][i].point, "q10": predictions[model][i].lower,
             "q90": predictions[model][i].upper,
             "error": predictions[model][i].point-w.actual if w.actual is not None and predictions[model][i].point is not None else None}
            for i,w in enumerate(examples) for model in predictions]
