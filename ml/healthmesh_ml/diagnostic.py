"""Fixed chronological diagnostic for raw HRV and the next-three-day mean."""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import fmean, median

from .cli import DEFAULT_CONFIG, DEFAULT_DATA, DEFAULT_OUTPUT, implementation_hash, package_versions, write_json
from .data import DailyDataset, Window, read_dataset, public_window
from .evaluation import prediction_records, score
from .models import ChronosForecaster, Forecast, RidgeForecaster, persistence, trailing_average, trailing_median
from .source_audit import audit_sources

SIMPLE = ("training_mean","training_median","persistence","trailing_mean_7","trailing_median_7")


def load_plan(path: Path) -> dict:
    plan = json.loads(path.read_text())
    if plan["target"] != "hrv_ms" or plan["contextDays"] != 7 or plan["horizons"] != [1,3]:
        raise ValueError("This diagnostic fixes HRV, seven-day context, and horizons one and three")
    if not 1 <= plan["minTargetObservations"] <= 7 or plan["minimumTrainingExamples"] < 2 or plan["ridgeAlpha"] <= 0:
        raise ValueError("Invalid coverage or ridge settings")
    cutoff,holdout = (date.fromisoformat(plan[key]) for key in ("developmentEnd","holdoutStart"))
    if cutoff >= holdout:
        raise ValueError("Development must end before the final holdout")
    previous_end = None
    names = set()
    for fold in plan["folds"]:
        train_end,start,end = (date.fromisoformat(fold[key]) for key in ("trainEnd","start","end"))
        if start != train_end+timedelta(days=1) or not start <= end <= cutoff or (previous_end and start <= previous_end):
            raise ValueError("Fold dates must be chronological, non-overlapping, and before the holdout")
        if fold["name"] in names:
            raise ValueError("Fold names must be unique")
        names.add(fold["name"])
        previous_end = end
    if not names:
        raise ValueError("At least one development fold is required")
    for keys in plan["featureGroups"].values():
        if plan["target"] not in keys or len(keys) != len(set(keys)):
            raise ValueError("Feature groups must contain the target once")
    return plan


def target_value(dataset: DailyDataset, index: int, target: str, horizon: int, period_end: date) -> float | None:
    end = index+horizon
    if end > len(dataset.dates) or dataset.dates[end-1] > period_end:
        return None
    future = [row[target] for row in dataset.rows[index:end]]
    return fmean(future) if all(value is not None for value in future) else None


def period_windows(dataset: DailyDataset, plan: dict, begin: date, end: date, horizon: int) -> list[Window]:
    result = []
    width = plan["contextDays"]
    for index in range(width,len(dataset.dates)):
        day = dataset.dates[index]
        # The entire label must belong to this period. In particular, training
        # labels cannot consume the first days of the next evaluation fold.
        if day < begin or day+timedelta(days=horizon-1) > end:
            continue
        if index+horizon > len(dataset.dates):
            continue
        history = dataset.rows[index-width:index]
        if sum(row[plan["target"]] is not None for row in history) < plan["minTargetObservations"]:
            continue
        actual = target_value(dataset,index,plan["target"],horizon,end)
        result.append(Window(day,dataset.dates[index-width:index],history,actual))
    return result


def fold_predictions(dataset, plan, fold, horizon, chronos=None):
    train_end,start,end = (date.fromisoformat(fold[k]) for k in ("trainEnd","start","end"))
    training = [w for w in period_windows(dataset,plan,dataset.dates[0],train_end,horizon) if w.actual is not None]
    if len(training) < plan["minimumTrainingExamples"]:
        raise ValueError(f"{fold['name']}, horizon {horizon}: only {len(training)} complete training targets")
    examples = period_windows(dataset,plan,start,end,horizon)
    values = [target_value(dataset,i,plan["target"],horizon,train_end) for i in range(len(dataset.dates)) if dataset.dates[i] <= train_end]
    values = [value for value in values if value is not None]
    predictions = {
        "training_mean":[Forecast(fmean(values)) for _ in examples],
        "training_median":[Forecast(float(median(values))) for _ in examples],
        "persistence":[persistence(w,plan["target"]) for w in examples],
        "trailing_mean_7":[trailing_average(w,plan["target"]) for w in examples],
        "trailing_median_7":[trailing_median(w,plan["target"]) for w in examples],
    }
    artifacts = {"trainingTargetCountForConstants":len(values),"trainingMean":fmean(values),
                 "trainingMedian":float(median(values)),"ridgeTrainingExamples":len(training),"ridge":{}}
    for group,keys in plan["featureGroups"].items():
        model = RidgeForecaster(keys,plan["ridgeAlpha"])
        model.fit(training)
        predictions[f"ridge/{group}"] = [model.predict(w) for w in examples]
        artifacts["ridge"][group] = model.artifact()
        if chronos:
            predictions[f"chronos/{group}"] = chronos.predict(examples,plan["target"],keys,plan["contextDays"],horizon=horizon)
    return examples,predictions,artifacts


def summarize(examples, predictions, fold_scores):
    result = score(examples,predictions)
    available = {name:m["mae"] for name,m in result["models"].items() if name in SIMPLE and m["mae"] is not None}
    best = min(available,key=available.get) if available else None
    reference = available.get(best) if best else None
    result["strongestSimpleBaseline"] = best
    result["exploratoryScreen"] = "At least 5% lower pooled MAE than strongest simple baseline and wins in a majority of scored folds; descriptive only, not statistical significance."
    for name,metrics in result["models"].items():
        metrics["improvementVsStrongestSimplePct"] = (100*(reference-metrics["mae"])/reference
                                                       if reference and metrics["mae"] is not None else None)
        wins = scored = 0
        for fold in fold_scores:
            simple = [m["mae"] for key,m in fold["models"].items() if key in SIMPLE and m["mae"] is not None]
            current = fold["models"].get(name,{}).get("mae")
            if simple and current is not None:
                scored += 1
                wins += current < min(simple)
        metrics["foldWinsVsStrongestSimple"] = wins
        metrics["scoredFolds"] = scored
        metrics["passesExploratoryScreen"] = bool(name not in SIMPLE and metrics["improvementVsStrongestSimplePct"] is not None
                                                  and metrics["improvementVsStrongestSimplePct"] >= 5 and wins > scored/2)
    return result


def write_csv(path: Path, rows: list[dict]):
    if not rows:
        return
    with path.open("w",newline="",encoding="utf-8") as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def diagnostic_report(directory, plan, aggregates, folds, audit):
    lines=["# HRV diagnostic comparison", "", f"Development data only, ending {plan['developmentEnd']}. Final holdout begins {plan['holdoutStart']} and was not evaluated.", "",
           "Fixed settings: seven-day historical context, ridge alpha 10, three expanding-training development folds. No fine-tuning or hyperparameter sweep.", "",
           "This is an exploratory analysis designed after the first validation results, not a new independent confirmatory evaluation.", ""]
    for horizon,result in aggregates.items():
        label="Next-day HRV" if horizon==1 else "Average HRV over the next three calendar days"
        lines += [f"## {label}", "", f"Common scored forecast origins: {result['pairedScoredDays']}. Strongest simple baseline: `{result['strongestSimpleBaseline']}`.", "",
                  "| Model | MAE (ms) | RMSE (ms) | Improvement vs strongest simple | Folds won |", "| --- | ---: | ---: | ---: | ---: |"]
        for name,m in sorted(result["models"].items(),key=lambda item:item[1]["mae"] if item[1]["mae"] is not None else float("inf")):
            if m["mae"] is None:
                continue
            improvement=m["improvementVsStrongestSimplePct"]
            relative=f"{improvement:+.1f}%" if improvement is not None else "unavailable"
            lines.append(f"| {name} | {m['mae']:.2f} | {m['rmse']:.2f} | {relative} | {m['foldWinsVsStrongestSimple']}/{m['scoredFolds']} |")
        lines += ["", "Positive improvement means lower error. Fold wins compare against the strongest simple baseline within each fold.", ""]
    lines += ["## Actual versus predicted", "", "![Forecast comparison](forecast_comparison.png)", "",
              "Points show recorded outcomes; lines connect adjacent forecast origins. Three-day outcomes are plotted at their first target date. Fold boundaries are marked.", "",
              "## Results by development fold", "", "| Horizon | Fold | Dates | Training examples | Scored origins | Best simple MAE | Combined ridge MAE | Combined Chronos MAE |",
              "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for item in folds:
        scores=item['scores']['models']
        simple=[m['mae'] for k,m in scores.items() if k in SIMPLE and m['mae'] is not None]
        def metric(key):
            value=scores.get(key,{}).get('mae')
            return f"{value:.2f}" if value is not None else "unavailable"
        simple_text=f"{min(simple):.2f}" if simple else "unavailable"
        lines.append(f"| {item['horizonDays']} | {item['fold']['name']} | {item['fold']['start']}–{item['fold']['end']} | {item['trainingExamples']} | {item['scores']['pairedScoredDays']} | {simple_text} | {metric('ridge/combined')} | {metric('chronos/combined')} |")
    lines += ["", "## Source and date checks", "", f"Matched original HRV readings: {audit['checkedHRV']}. Checked sleep-day totals: {audit['checkedSleepDays']}. Source mismatches: {len(audit['mismatches'])}.",
              "", audit['interpretation'], "", "![Development HRV and largest jumps](source_jumps.png)", "",
              "## Interpretation limits", "",
              "- Compare improvement against each target's own baselines. Lower raw MAE for a three-day mean does not by itself demonstrate better modeling.",
              "- Three-day targets require all three recorded readings. No target interpolation is used.",
              "- All three label dates remain inside their training or evaluation period. The last two forecast origins in each three-day fold are excluded at the boundary.",
              "- Adjacent three-day targets overlap and errors are correlated. Scored origins are not independent samples; no significance claim is made.",
              "- Regression fits and preprocessing use each fold's earlier training data only. Earlier evaluation days can later become observed history, but never training labels within that fold.",
              "- Chronos predicts three daily values and averages their marginal medians for the three-day target. Marginal quantiles are not averaged into a purported interval for the mean.",
              "- The source audit checks the export, not the app screen, clinical validity, or sensor accuracy. Unusual readings are retained.",
              "- Source-data publication delays are not replayed in this retrospective backtest.",
              "", "Full per-origin predictions, contexts, source audit, model artifacts, and fold metrics accompany this report.", ""]
    (directory/'report.md').write_text('\n'.join(lines),encoding='utf-8')


def run_diagnostic(args) -> Path:
    plan=load_plan(args.plan)
    base={**plan,"horizonDays":1,"quantiles":[.1,.5,.9],"trainEnd":plan['folds'][0]['trainEnd'],
          "validationEnd":plan['developmentEnd'],"testEnd":plan['holdoutStart']}
    full=read_dataset(args.data,base)
    cutoff=date.fromisoformat(plan['developmentEnd'])
    limit=sum(day<=cutoff for day in full.dates)
    dataset=replace(full,dates=full.dates[:limit],rows=full.rows[:limit])
    audit=audit_sources(dataset,args.archive,cutoff)
    if audit['mismatches']:
        raise ValueError("Source audit found inconsistent values; resolve these before comparing models")
    chronos=ChronosForecaster(plan['modelId'],args.device,args.revision,plan['seed']) if args.chronos else None
    all_records=[];contexts=[];artifacts={};fold_reports=[];aggregates={}
    for horizon in plan['horizons']:
        pooled_examples=[];pooled_predictions=defaultdict(list);scores=[]
        for fold in plan['folds']:
            examples,predictions,fitted=fold_predictions(dataset,plan,fold,horizon,chronos)
            result=score(examples,predictions)
            key=f"horizon{horizon}/{fold['name']}"
            artifacts[key]=fitted
            scores.append(result)
            fold_reports.append({'horizonDays':horizon,'fold':fold,'trainingExamples':fitted['ridgeTrainingExamples'],'scores':result})
            for record in prediction_records(examples,predictions):
                all_records.append({"horizonDays":horizon,"fold":fold['name'],"targetEnd":(date.fromisoformat(record['date'])+timedelta(days=horizon-1)).isoformat(),**record})
            for window in examples:
                contexts.append({'horizonDays':horizon,'fold':fold['name'],**public_window(window,base)})
            pooled_examples.extend(examples)
            for name,forecasts in predictions.items():
                pooled_predictions[name].extend(forecasts)
        aggregates[horizon]=summarize(pooled_examples,dict(pooled_predictions),scores)
    now=datetime.now(timezone.utc)
    directory=args.output_root/plan['name']/now.strftime('%Y%m%dT%H%M%S%fZ')
    directory.mkdir(parents=True,exist_ok=False)
    manifest={'createdAt':now.isoformat(),'plan':plan,'datasetSHA256':full.sha256,'implementationSHA256':implementation_hash(),
              'environment':package_versions(),'chronos':chronos.artifact() if chronos else None,
              'testEvaluated':False,'developmentEnd':plan['developmentEnd'],'holdoutStart':plan['holdoutStart'],
              'threeDayPointForecast':'Mean of three raw-HRV marginal medians for Chronos; direct three-day target for ridge.'}
    write_json(directory/'manifest.json',manifest)
    write_json(directory/'metrics.json',{'tasks':aggregates,'folds':fold_reports})
    write_json(directory/'source_audit.json',audit)
    write_json(directory/'ridge_artifacts.json',artifacts)
    write_csv(directory/'predictions.csv',all_records)
    write_csv(directory/'largest_jumps.csv',audit['largestJumps'])
    with (directory/'windows.jsonl').open('w',encoding='utf-8') as handle:
        for context in contexts:
            handle.write(json.dumps(context,allow_nan=False)+'\n')
    from .plots import plot_diagnostic
    plot_diagnostic(directory,plan,all_records,audit)
    diagnostic_report(directory,plan,aggregates,fold_reports,audit)
    print(json.dumps({'outputDirectory':str(directory),'sourceChecks':{'hrv':audit['checkedHRV'],'sleep':audit['checkedSleepDays'],'mismatches':len(audit['mismatches'])},
                      'tasks':{h:{'scoredOrigins':result['pairedScoredDays'],'strongestSimple':result['strongestSimpleBaseline'],
                                  'models':{name:{key:m[key] for key in ['mae','improvementVsStrongestSimplePct','foldWinsVsStrongestSimple','passesExploratoryScreen']} for name,m in result['models'].items()}}
                               for h,result in aggregates.items()},'testEvaluated':False},indent=2))
    return directory


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,default=DEFAULT_CONFIG.parent/'hrv_diagnostic_v1.json')
    parser.add_argument('--data',type=Path,default=DEFAULT_DATA)
    parser.add_argument('--archive',type=Path,default=DEFAULT_DATA.parents[1]/'google-health-info.zip')
    parser.add_argument('--output-root',type=Path,default=DEFAULT_OUTPUT)
    parser.add_argument('--chronos',action='store_true')
    parser.add_argument('--device',choices=['cpu','cuda'],default='cpu')
    parser.add_argument('--revision',default='main')
    args=parser.parse_args()
    try:
        run_diagnostic(args)
    except (ValueError,FileNotFoundError,ImportError) as exc:
        parser.exit(2,f'Error: {exc}\n')


if __name__=='__main__':
    main()
