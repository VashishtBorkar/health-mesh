from __future__ import annotations

import csv
import json
import subprocess
import sys
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from healthmesh_ml.cli import baseline_predictions
from healthmesh_ml.data import DailyDataset, Window, load_config, read_dataset, windows
from healthmesh_ml.evaluation import score
from healthmesh_ml.models import ChronosForecaster, Forecast, RidgeForecaster, chronos_input, summary_features


@pytest.fixture
def experiment(tmp_path):
    config = {
        "name":"synthetic-hrv", "target":"hrv_ms", "unit":"ms", "horizonDays":1,
        "contextDays":14, "minTargetObservations":3, "minimumTrainingExamples":10,
        "ridgeAlpha":10.0, "trainEnd":"2026-01-25", "validationEnd":"2026-02-04", "testEnd":"2026-02-14",
        "featureGroups":{"history":["hrv_ms"], "fitbit":["hrv_ms","steps"], "combined":["hrv_ms","steps","protein_g"]},
        "modelId":"amazon/chronos-2", "quantiles":[0.1,0.5,0.9], "seed":42,
    }
    config_path = tmp_path / "experiment.json"
    config_path.write_text(json.dumps(config))
    data = tmp_path / "daily.csv"
    with data.open("w",newline="") as handle:
        writer = csv.DictWriter(handle,fieldnames=["date","hrv_ms","steps","protein_g"])
        writer.writeheader()
        for i in range(45):
            writer.writerow({"date":(date(2026,1,1)+timedelta(days=i)).isoformat(),
                             "hrv_ms":"" if i in {5,30} else 50+i*.2+(i%3),
                             "steps":i*100, "protein_g":"" if i in {1,26} else 100+i})
    return config_path,data,tmp_path / "results"


def test_windows_preserve_calendar_cutoff_missing_and_zero(experiment):
    config_path,path,_ = experiment
    config = load_config(config_path)
    dataset = read_dataset(path,config)
    assert dataset.rows[0]["steps"] == 0
    assert dataset.rows[5]["hrv_ms"] is None
    training,validation = windows(dataset,config,"train"),windows(dataset,config,"validation")
    assert all(w.target_date <= date(2026,1,25) for w in training)
    assert validation[0].target_date == date(2026,1,26)
    for window in training+validation:
        assert len(window.context_dates) == 14
        assert window.context_dates[-1] == window.target_date-timedelta(days=1)
        assert window.target_date not in window.context_dates
    assert len(validation) == 10
    assert sum(w.actual is None for w in validation) == 1


def test_missing_calendar_dates_are_not_compressed(experiment):
    config_path,path,_ = experiment
    lines=path.read_text().splitlines()
    path.write_text("\n".join([*lines[:4],*lines[5:]])+"\n")
    dataset = read_dataset(path,load_config(config_path))
    assert len(dataset.dates)==45
    assert all(v is None for v in dataset.rows[3].values())


def test_duplicate_and_invalid_values_rejected(experiment):
    config_path,path,_=experiment
    original=path.read_text()
    path.write_text(original+original.splitlines()[1]+"\n")
    with pytest.raises(ValueError,match="duplicate"):
        read_dataset(path,load_config(config_path))
    path.write_text(original.replace("50.0", "nan",1))
    with pytest.raises(ValueError,match="Invalid measurement"):
        read_dataset(path,load_config(config_path))


def test_ridge_and_earlier_forecasts_do_not_use_future_measurements(experiment):
    config_path,path,_=experiment
    config=load_config(config_path)
    original=read_dataset(path,config)
    examples=windows(original,config,"validation")
    before,artifacts=baseline_predictions(original,config,examples)
    changed_rows=tuple({key:(999999.0 if value is not None else None) for key,value in row.items()}
                       if day>=examples[0].target_date else dict(row)
                       for day,row in zip(original.dates,original.rows))
    changed=replace(original,rows=changed_rows)
    after,changed_artifacts=baseline_predictions(changed,config,windows(changed,config,"validation"))
    assert artifacts==changed_artifacts
    for model in before:
        assert before[model][0]==after[model][0]


def test_training_only_imputation_for_all_missing_feature(experiment):
    config_path,path,_=experiment
    config=load_config(config_path)
    dataset=read_dataset(path,config)
    training=windows(dataset,config,"train")
    training=[replace(w,history=tuple({**row,"protein_g":None} for row in w.history)) for w in training]
    model=RidgeForecaster(["hrv_ms","protein_g"],10)
    model.fit(training)
    assert np.isfinite(model.weights).all()
    assert model.means[4]==0
    assert np.isfinite(model.predict(windows(dataset,config,"validation")[0]).point)


def test_chronos_receives_only_past_values_and_disables_cross_window_learning(experiment):
    config_path,path,_=experiment
    config=load_config(config_path)
    examples=windows(read_dataset(path,config),config,"validation")[:2]
    inputs=chronos_input(examples[0],"hrv_ms",["hrv_ms","protein_g"])
    assert set(inputs)=={"target","past_covariates"}
    assert inputs["target"].shape==(14,)
    assert inputs["past_covariates"]["protein_g"].shape==(14,)
    assert np.array_equal(inputs["target"],chronos_input(replace(examples[0],actual=999999),"hrv_ms",["hrv_ms","protein_g"])["target"],equal_nan=True)
    class Pipeline:
        class Model:
            evaluated = False
            def eval(self):
                self.evaluated = True
        model = Model()
        def predict_quantiles(self, received, **kwargs):
            assert self.model.evaluated
            assert kwargs["cross_learning"] is False
            assert kwargs["prediction_length"]==1
            assert kwargs["context_length"]==14
            assert all("future_covariates" not in item for item in received)
            return [np.array([[[40.,50.,60.]]]) for _ in received],[]
    predictor=ChronosForecaster.__new__(ChronosForecaster)
    predictor.pipeline=Pipeline()
    assert predictor.predict(examples,"hrv_ms",["hrv_ms","protein_g"],14)==[Forecast(50,40,60)]*2


def test_paired_scoring_and_interval_metrics():
    dates=(date(2026,1,1),)
    examples=[Window(date(2026,1,2),dates,({"hrv_ms":1.},),actual) for actual in [10.,20.,None]]
    predictions={"a":[Forecast(12,8,15),Forecast(18,15,25),Forecast(30,25,35)],
                 "b":[Forecast(10),Forecast(None),Forecast(1)]}
    results=score(examples,predictions)
    assert results["pairedScoredDays"]==1
    assert results["observedTargetDays"]==2
    assert results["models"]["a"]["mae"]==2
    assert results["models"]["a"]["intervalObservedCoverage"]==1
    assert results["models"]["a"]["intervalMeanWidth"]==7


def test_cli_validation_selection_and_guarded_test(experiment):
    config,path,output=experiment
    def invoke(command,*args,check=True):
        return subprocess.run([sys.executable,"-m","healthmesh_ml.cli",command,*args],capture_output=True,text=True,check=check)
    common=["--config",str(config),"--data",str(path),"--output-root",str(output)]
    prepared=invoke("prepare",*common)
    assert json.loads(prepared.stdout)["testStatus"]=="held out; not evaluated"
    baseline=invoke("baselines",*common)
    result=json.loads(baseline.stdout)
    assert result["testEvaluated"] is False
    run_dir=Path(result["outputDirectory"])
    assert (run_dir/"report.md").exists()
    records=list(csv.DictReader((run_dir/"predictions.csv").open()))
    assert all(r["date"]<="2026-02-04" and r["contextEnd"]<r["date"] for r in records)
    assert invoke("evaluate-test",*common,check=False).returncode!=0
    selection=output/"selection.json"
    invoke("select","--run-dir",str(run_dir),"--model","ridge/history","--output",str(selection))
    assert invoke("select","--run-dir",str(run_dir),"--model","ridge/history","--output",str(selection),check=False).returncode!=0
    tested=invoke("evaluate-test",*common,"--selection",str(selection))
    assert json.loads(tested.stdout)["stage"]=="test"
    path.write_text(path.read_text()+"\n")
    rejected=invoke("evaluate-test",*common,"--selection",str(selection),check=False)
    assert rejected.returncode!=0 and "Dataset differs" in rejected.stderr
