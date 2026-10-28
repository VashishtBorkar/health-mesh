from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from statistics import fmean, median

import numpy as np

from .data import Window


@dataclass(frozen=True)
class Forecast:
    point: float | None
    lower: float | None = None
    upper: float | None = None


def persistence(window: Window, target: str) -> Forecast:
    observed = [row[target] for row in window.history if row[target] is not None]
    return Forecast(observed[-1] if observed else None)


def trailing_average(window: Window, target: str) -> Forecast:
    observed = [row[target] for row in window.history[-7:] if row[target] is not None]
    return Forecast(fmean(observed) if len(observed) >= 3 else None)


def trailing_median(window: Window, target: str) -> Forecast:
    observed = [row[target] for row in window.history[-7:] if row[target] is not None]
    return Forecast(float(median(observed)) if len(observed) >= 3 else None)


def summary_features(window: Window, keys: list[str]) -> np.ndarray:
    features = []
    for key in keys:
        values = [row[key] for row in window.history]
        positions = [i for i,value in enumerate(values) if value is not None]
        recent = [value for value in values[-7:] if value is not None]
        features.extend([
            values[positions[-1]] if positions else np.nan,
            fmean(recent) if recent else np.nan,
            1 - len(positions) / len(values),
            (len(values)-1-positions[-1]) / len(values) if positions else 1.0,
        ])
    return np.asarray(features, dtype=np.float64)


class RidgeForecaster:
    """Small regularized model of lagged summaries with training-only scaling.

    Each metric contributes latest observed value, seven-day observed mean,
    missing fraction, and age of its latest observation. Missing numeric summaries
    are filled with the training mean, with coverage/age preserving missingness.
    """

    def __init__(self, keys: list[str], alpha: float):
        self.keys, self.alpha = keys, alpha

    def fit(self, training: list[Window]) -> None:
        observed = [window for window in training if window.actual is not None]
        if len(observed) < 2:
            raise ValueError("Insufficient observed training targets")
        x = np.stack([summary_features(window, self.keys) for window in observed])
        self.means = np.array([float(np.mean(col[np.isfinite(col)])) if np.isfinite(col).any() else 0.0 for col in x.T])
        filled = np.where(np.isfinite(x), x, self.means)
        self.scales = np.std(filled, axis=0)
        self.scales[self.scales < 1e-8] = 1.0
        standardized = (filled-self.means) / self.scales
        y = np.asarray([window.actual for window in observed])
        self.intercept = float(y.mean())
        penalty = self.alpha * np.eye(standardized.shape[1])
        self.weights = np.linalg.solve(standardized.T @ standardized + penalty, standardized.T @ (y-self.intercept))
        self.training_examples = len(observed)

    def predict(self, window: Window) -> Forecast:
        raw = summary_features(window, self.keys)
        x = (np.where(np.isfinite(raw), raw, self.means)-self.means) / self.scales
        return Forecast(max(0.0, float(x @ self.weights + self.intercept)))

    def artifact(self) -> dict:
        return {"keys": self.keys, "alpha": self.alpha, "means": self.means.tolist(),
                "scales": self.scales.tolist(), "weights": self.weights.tolist(),
                "intercept": self.intercept, "trainingExamples": self.training_examples,
                "featuresPerMetric": ["latest_observed", "trailing_7_mean", "missing_fraction", "observation_age_fraction"]}


def chronos_input(window: Window, target: str, keys: list[str]) -> dict:
    # Only historical measurements enter the predictor. The target day's actual
    # value is deliberately not accessed here. NaN carries the native missing mask.
    data = {"target": np.asarray([row[target] if row[target] is not None else np.nan for row in window.history], dtype=np.float32)}
    covariates = {key: np.asarray([row[key] if row[key] is not None else np.nan for row in window.history], dtype=np.float32)
                  for key in keys if key != target}
    if covariates:
        data["past_covariates"] = covariates
    return data


class ChronosForecaster:
    def __init__(self, model_id: str, device: str, revision: str, seed: int):
        # Downloading weights is opt-in, and no personal data is sent to a service.
        import os
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        import torch
        from chronos import Chronos2Pipeline
        from huggingface_hub import hf_hub_download

        np.random.seed(seed)
        torch.manual_seed(seed)
        if device == "cpu":
            torch.set_num_threads(min(4, os.cpu_count() or 1))
        # Resolve the revision before loading weights: some Chronos configs do
        # not retain Hugging Face's _commit_hash attribute after construction.
        if Path(model_id).is_dir():
            raise ValueError("Use a Hugging Face model ID with a pinned revision for this reproducible experiment")
        config_path = Path(hf_hub_download(model_id, "config.json", revision=revision))
        resolved = config_path.parent.name
        if not re.fullmatch(r"[a-f0-9]{40}", resolved):
            raise ValueError("Could not resolve the model checkpoint commit from the Hub cache")
        self.pipeline = Chronos2Pipeline.from_pretrained(model_id, device_map=device, revision=resolved)
        self.model_id, self.device, self.revision = model_id, device, revision
        self.resolved_revision = resolved

    def predict(self, examples: list[Window], target: str, keys: list[str], context: int, horizon: int = 1) -> list[Forecast]:
        if not examples:
            return []
        # Trainer can return a pipeline whose LoRA dropout remains in training
        # mode. Inference mode disables gradients, but does not disable dropout.
        if hasattr(self.pipeline, 'model'):
            self.pipeline.model.eval()
        inputs = [chronos_input(window, target, keys) for window in examples]
        # Cross-window learning would allow later windows to influence earlier
        # forecasts in a batched backtest. Explicitly disable it.
        quantiles, _ = self.pipeline.predict_quantiles(
            inputs, prediction_length=horizon, quantile_levels=[0.1, 0.5, 0.9],
            context_length=context, batch_size=32, cross_learning=False,
        )
        forecasts = []
        for prediction in quantiles:
            daily = np.asarray(prediction[0].tolist(), dtype=float)
            if daily.shape != (horizon, 3) or not np.isfinite(daily).all() or not ((daily[:,0] <= daily[:,1]) & (daily[:,1] <= daily[:,2])).all():
                raise ValueError("Chronos returned invalid forecast quantiles")
            daily = np.maximum(0.0, daily)
            if horizon == 1:
                forecasts.append(Forecast(float(daily[0,1]), float(daily[0,0]), float(daily[0,2])))
            else:
                # Means of marginal quantiles are not quantiles of the mean.
                # Aggregate the point forecasts only; do not invent an interval.
                forecasts.append(Forecast(float(np.mean(daily[:,1]))))
        if len(forecasts) != len(examples):
            raise ValueError("Chronos forecast count does not match input windows")
        return forecasts

    def artifact(self) -> dict:
        return {"modelId": self.model_id, "requestedRevision": self.revision,
                "resolvedRevision": self.resolved_revision, "device": self.device,
                "crossLearning": False, "quantiles": [0.1, 0.5, 0.9],
                "pointForecast": "median (q50)", "weightsUpdated": False}
