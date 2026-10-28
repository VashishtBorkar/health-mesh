from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import platform
from datetime import date
from statistics import fmean, median
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .data import dataset_manifest, load_config, public_window, read_dataset, windows
from .evaluation import prediction_records, score
from .models import ChronosForecaster, Forecast, RidgeForecaster, persistence, trailing_average, trailing_median

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "experiments/hrv_v1.json"
DEFAULT_DATA = ROOT.parent / "health-info/processed/healthmesh_personal_daily.csv"
DEFAULT_OUTPUT = ROOT.parent / "health-info/modeling"


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def implementation_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def package_versions() -> dict:
    versions = {"python": platform.python_version(), "healthmesh-ml": __version__}
    for name in ("numpy", "matplotlib", "chronos-forecasting", "torch", "transformers", "huggingface-hub", "peft", "accelerate"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    return versions


def baseline_predictions(dataset, config, examples):
    training = [w for w in windows(dataset, config, "train") if w.actual is not None]
    if len(training) < config["minimumTrainingExamples"]:
        raise ValueError(f"Only {len(training)} observed training examples; at least {config['minimumTrainingExamples']} required")
    predictions = {
        "persistence": [persistence(w, config["target"]) for w in examples],
        "trailing_mean_7": [trailing_average(w, config["target"]) for w in examples],
        "trailing_median_7": [trailing_median(w, config["target"]) for w in examples],
    }
    target_values = [row[config["target"]] for day,row in zip(dataset.dates,dataset.rows)
                     if day <= date.fromisoformat(config["trainEnd"]) and row[config["target"]] is not None]
    predictions["training_mean"] = [Forecast(fmean(target_values)) for _ in examples]
    predictions["training_median"] = [Forecast(float(median(target_values))) for _ in examples]
    artifacts = {"constant_baselines": {"observedTrainingDays":len(target_values),
                                       "mean":fmean(target_values), "median":float(median(target_values))}}
    for group, keys in config["featureGroups"].items():
        model = RidgeForecaster(keys, config["ridgeAlpha"])
        model.fit(training)
        name = f"ridge/{group}"
        predictions[name] = [model.predict(w) for w in examples]
        artifacts[name] = model.artifact()
    return predictions, artifacts


def save_report(directory: Path, manifest: dict, results: dict, records: list[dict]) -> None:
    write_json(directory / "manifest.json", manifest)
    write_json(directory / "metrics.json", results)
    with (directory / "predictions.csv").open("w", newline="", encoding="utf-8") as handle:
        if records:
            writer = csv.DictWriter(handle, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
    lines = [f"# {manifest['config']['target']} {manifest['stage']} results", "",
             f"Context: {manifest['config']['contextDays']} calendar days. Horizon: one day. Units: {manifest['config']['unit']}.", "",
             f"Forecast days: {results['forecastDays']}. Recorded targets: {results['observedTargetDays']}. Common scored dates: {results['pairedScoredDays']}.", "",
             "| Model | MAE | RMSE | Bias (prediction − actual) | Count |", "| --- | ---: | ---: | ---: | ---: |"]
    ranked = sorted(results["models"].items(), key=lambda item: item[1]["mae"] if item[1]["mae"] is not None else float("inf"))
    for name, metrics in ranked:
        fmt = lambda key: f"{metrics[key]:.3f}" if metrics[key] is not None else "unavailable"
        lines.append(f"| {name} | {fmt('mae')} | {fmt('rmse')} | {fmt('bias')} | {metrics['matchedCount']} |")
    probabilistic = [(name,m) for name,m in ranked if "intervalObservedCoverage" in m]
    if probabilistic:
        lines += ["", "## Forecast interval checks", "", "Nominal interval coverage: 80%. Coverage is measured, not assumed.", "",
                  "| Model | Observed coverage | Mean width | Mean pinball loss |", "| --- | ---: | ---: | ---: |"]
        for name,m in probabilistic:
            lines.append(f"| {name} | {m['intervalObservedCoverage']:.1%} | {m['intervalMeanWidth']:.3f} | {m['meanPinballLoss']:.3f} |")
    lines += ["", "## Interpretation", "",
              "All models use the same scored dates. Missing targets are not filled or scored.",
              "Ridge weights, imputation means, and scaling use training-period examples only.",
              "Models are frozen during rolling evaluation; earlier observed evaluation days become later historical context.",
              "This is a retrospective single-person study with a small evaluation period.",
              "Summary availability is assumed at the end of the preceding day; provider publication delays are not replayed.",
              "No anomalies, fatigue scores, or causal explanations are inferred by this report."]
    if manifest["stage"] == "validation":
        lines += ["", "The final test period remains unevaluated. Choose a model on validation data and save an explicit selection before testing."]
    (directory / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args, config, dataset, stage="validation", selection=None) -> Path:
    examples = windows(dataset, config, stage)
    if not examples:
        raise ValueError("No eligible forecast windows in this period")
    predictions, artifacts = baseline_predictions(dataset, config, examples)
    chronos_metadata = None
    wants_chronos = args.command == "chronos" or (selection and selection["selectedModel"].startswith("chronos/"))
    if wants_chronos:
        try:
            model = ChronosForecaster(config["modelId"], args.device, args.revision, config["seed"])
        except ImportError as exc:
            raise ValueError("Chronos dependencies are missing. Run make setup-chronos, or install ml[chronos] on university compute.") from exc
        groups = config["featureGroups"]
        if selection:
            group = selection["selectedModel"].split("/",1)[1]
            groups = {group: groups[group]}
            expected_revision = selection.get("chronos", {}).get("resolvedRevision")
            if expected_revision and model.resolved_revision != expected_revision:
                raise ValueError("Model revision differs from the selected validation run")
        for group, keys in groups.items():
            predictions[f"chronos/{group}"] = model.predict(examples, config["target"], keys, config["contextDays"])
        chronos_metadata = model.artifact()
    if selection:
        keep = {selection["selectedModel"], "persistence", "trailing_mean_7", "trailing_median_7", "training_mean", "training_median"}
        predictions = {name:values for name,values in predictions.items() if name in keep}
    results = score(examples, predictions)
    if not results["pairedScoredDays"]:
        raise ValueError("No common observed target dates available for scoring")
    created = datetime.now(timezone.utc)
    identifier = created.strftime("%Y%m%dT%H%M%S%fZ")
    directory = args.output_root / config["name"] / stage / f"{args.command}-context{config['contextDays']}-{identifier}"
    directory.mkdir(parents=True, exist_ok=False)
    manifest = {**dataset_manifest(dataset, config), "runnerVersion": __version__, "stage": stage,
                "implementationSHA256": implementation_hash(),
                "createdAt": created.isoformat(), "config": config, "environment": package_versions(),
                "inputPath": str(args.data.resolve()), "chronos": chronos_metadata,
                "testStatus": "evaluated after explicit selection" if stage == "test" else "held out; not evaluated",
                "selection": selection,
                "experiment": "Forecast HRV assigned to D+1 from measurements through D."}
    write_json(directory / "ridge_artifacts.json", artifacts)
    # Keep per-date contexts/masks to audit cutoff and missingness. Private output only.
    with (directory / "windows.jsonl").open("w", encoding="utf-8") as handle:
        for window in examples:
            handle.write(json.dumps(public_window(window, config), allow_nan=False) + "\n")
    save_report(directory, manifest, results, prediction_records(examples,predictions))
    print(json.dumps({"outputDirectory":str(directory), "stage":stage, "scoredDays":results["pairedScoredDays"],
                      "models": results["models"], "testEvaluated":stage=="test"}, indent=2))
    return directory


def select_model(args) -> None:
    manifest_path = args.run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    metrics_path = args.run_dir / "metrics.json"
    metrics = json.loads(metrics_path.read_text())
    if manifest["stage"] != "validation":
        raise ValueError("Select a model using validation results only")
    if args.model not in metrics["models"] or metrics["models"][args.model]["mae"] is None:
        raise ValueError("Selected model has no scored validation results")
    selection = {"selectedModel":args.model, "config":manifest["config"],
                 "implementationSHA256":manifest["implementationSHA256"],
                 "datasetSHA256":manifest["datasetSHA256"], "validationManifestSHA256":file_hash(manifest_path),
                 "validationMetricsSHA256":file_hash(metrics_path), "validationDirectory":str(args.run_dir.resolve()),
                 "chronos":manifest["chronos"], "environment":manifest["environment"],
                 "selectedAt":datetime.now(timezone.utc).isoformat()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(selection, indent=2, allow_nan=False) + "\n")
    print(f"Saved selection to {args.output}. Final test has not been evaluated.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily HRV forecasting experiments; validation is the default.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "baselines", "chronos", "evaluate-test"):
        command = commands.add_parser(name)
        command.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
        command.add_argument("--data", type=Path, default=DEFAULT_DATA)
        command.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
        command.add_argument("--context-days", type=int, choices=[7,14])
        command.add_argument("--device", choices=["cpu","cuda"], default="cpu")
        command.add_argument("--revision", default="main")
        if name == "evaluate-test":
            command.add_argument("--selection", type=Path, required=True)
    select = commands.add_parser("select")
    select.add_argument("--run-dir", type=Path, required=True)
    select.add_argument("--model", required=True)
    select.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "select":
            select_model(args)
            return
        config = load_config(args.config)
        if args.context_days is not None:
            config["contextDays"] = args.context_days
        selection = None
        if args.command == "evaluate-test":
            if args.context_days is not None:
                raise ValueError("Final test must use the saved configuration, without context overrides")
            selection = json.loads(args.selection.read_text())
            if selection["implementationSHA256"] != implementation_hash():
                raise ValueError("Forecasting implementation changed since model selection; rerun validation")
            config = selection["config"]
            source = Path(selection["validationDirectory"])
            if file_hash(source / "manifest.json") != selection["validationManifestSHA256"] or file_hash(source / "metrics.json") != selection["validationMetricsSHA256"]:
                raise ValueError("Selected validation results have changed")
            original = json.loads((source / "manifest.json").read_text())
            original_metrics = json.loads((source / "metrics.json").read_text())
            if original["stage"] != "validation" or config != original["config"] or selection["datasetSHA256"] != original["datasetSHA256"] or selection["selectedModel"] not in original_metrics["models"]:
                raise ValueError("Selection does not match its validation configuration")
            if selection["selectedModel"].startswith("chronos/"):
                args.revision = selection["chronos"].get("resolvedRevision") or selection["chronos"]["requestedRevision"]
        dataset = read_dataset(args.data, config)
        if selection and selection["datasetSHA256"] != dataset.sha256:
            raise ValueError("Dataset differs from the selected validation snapshot")
        if args.command == "prepare":
            manifest = {**dataset_manifest(dataset, config), "config":config}
            destination = args.output_root / config["name"] / f"dataset-context{config['contextDays']}"
            destination.mkdir(parents=True, exist_ok=True)
            path = destination / "manifest.json"
            if path.exists() and json.loads(path.read_text()) != manifest:
                raise ValueError("Prepared manifest differs; use another output root for a new experiment snapshot")
            write_json(path,manifest)
            print(json.dumps(manifest,indent=2))
        else:
            run(args, config, dataset, "test" if selection else "validation", selection)
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        parser.exit(2, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
