from __future__ import annotations

import csv
import io
import json
from argparse import Namespace
from dataclasses import replace
from datetime import date, timedelta
from zipfile import ZipFile

import numpy as np
import pytest

from healthmesh_ml.data import DailyDataset
from healthmesh_ml.diagnostic import fold_predictions, load_plan, period_windows, run_diagnostic, target_value
from healthmesh_ml.models import ChronosForecaster, Forecast
from healthmesh_ml.source_audit import audit_sources


@pytest.fixture
def diagnostic_data():
    dates=tuple(date(2026,1,1)+timedelta(days=i) for i in range(70))
    rows=tuple({'hrv_ms':float(i+30),'steps':float(i*100),'sleep_duration_min':60.0} for i in range(70))
    dataset=DailyDataset(dates,rows,'synthetic')
    plan={'name':'synthetic-diagnostic','target':'hrv_ms','contextDays':7,'minTargetObservations':3,
          'minimumTrainingExamples':10,'ridgeAlpha':10.0,'horizons':[1,3],
          'developmentEnd':'2026-03-03','holdoutStart':'2026-03-04',
          'folds':[{'name':f'fold-{i}','trainEnd':(date(2026,2,10)+timedelta(days=7*i)).isoformat(),
                    'start':(date(2026,2,11)+timedelta(days=7*i)).isoformat(),
                    'end':(date(2026,2,17)+timedelta(days=7*i)).isoformat()} for i in range(3)],
          'featureGroups':{'history':['hrv_ms'],'combined':['hrv_ms','steps','sleep_duration_min']},
          'modelId':'amazon/chronos-2','seed':42}
    return dataset,plan


def test_three_day_labels_stay_inside_their_period(diagnostic_data):
    dataset,plan=diagnostic_data
    train_end=date(2026,2,10)
    training=period_windows(dataset,plan,dataset.dates[0],train_end,3)
    assert training[-1].target_date==date(2026,2,8)
    assert all(w.target_date+timedelta(days=2)<=train_end for w in training)
    examples=period_windows(dataset,plan,date(2026,2,11),date(2026,2,17),3)
    assert len(examples)==5
    for w in examples:
        index=dataset.dates.index(w.target_date)
        assert w.actual==pytest.approx(sum(dataset.rows[index+i]['hrv_ms'] for i in range(3))/3)
        assert w.context_dates[-1]==w.target_date-timedelta(days=1)


def test_missing_three_day_targets_are_not_filled(diagnostic_data):
    dataset,plan=diagnostic_data
    rows=list(dataset.rows)
    rows[dataset.dates.index(date(2026,2,13))]={**rows[0],'hrv_ms':None}
    changed=replace(dataset,rows=tuple(rows))
    examples=period_windows(changed,plan,date(2026,2,11),date(2026,2,17),3)
    assert len(examples)==5
    assert [w.target_date for w in examples if w.actual is None]==[date(2026,2,11),date(2026,2,12),date(2026,2,13)]
    assert target_value(changed,len(changed.dates)-1,'hrv_ms',3,changed.dates[-1]) is None


def test_future_labels_do_not_enter_training_or_first_forecast(diagnostic_data):
    dataset,plan=diagnostic_data
    fold=plan['folds'][0]
    examples,predictions,artifacts=fold_predictions(dataset,plan,fold,3)
    rows=tuple({key:999999. for key in row} if day>=date.fromisoformat(fold['start']) else row
               for day,row in zip(dataset.dates,dataset.rows))
    altered=replace(dataset,rows=rows)
    changed_examples,changed_predictions,changed_artifacts=fold_predictions(altered,plan,fold,3)
    assert artifacts==changed_artifacts
    assert examples[0].actual!=changed_examples[0].actual
    for model in predictions:
        assert predictions[model][0]==changed_predictions[model][0]


def test_chronos_mean_does_not_claim_an_aggregate_interval(diagnostic_data):
    dataset,plan=diagnostic_data
    examples=period_windows(dataset,plan,date(2026,2,11),date(2026,2,17),3)
    class Pipeline:
        def predict_quantiles(self,inputs,**kwargs):
            assert kwargs['prediction_length']==3
            assert kwargs['cross_learning'] is False
            return [np.array([[[5.,10.,20.],[10.,20.,40.],[20.,30.,50.]]]) for _ in inputs],[]
    predictor=ChronosForecaster.__new__(ChronosForecaster)
    predictor.pipeline=Pipeline()
    results=predictor.predict(examples,'hrv_ms',plan['featureGroups']['combined'],7,horizon=3)
    assert results==[Forecast(20.0)]*5
    assert all(r.lower is None and r.upper is None for r in results)


def make_archive(path,dataset,cutoff):
    def text(rows):
        output=io.StringIO()
        writer=csv.DictWriter(output,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
        return output.getvalue()
    rows=[{'timestamp':day.isoformat()+'T00:00:00Z', 'average heart rate variability milliseconds':str(row['hrv_ms'])}
          for day,row in zip(dataset.dates,dataset.rows) if day<=cutoff]
    sleeps=[{'sleep_id':day.isoformat(),'algorithm_version':'sleep_session_v2',
             'sleep_start':day.isoformat()+'T10:00:00Z','sleep_end':day.isoformat()+'T11:00:00Z',
             'end_utc_offset':'-04:00','minutes_asleep':'60','sleep_last_updated':day.isoformat()+'T12:00:00Z'}
            for day in dataset.dates if day<=cutoff]
    with ZipFile(path,'w') as archive:
        archive.writestr('Takeout/Google Health/Physical Activity_GoogleData/Daily Heart Rate Variability/daily.csv',text(rows))
        archive.writestr('Takeout/Google Health/Health Fitness Data_GoogleData/UserSleeps_fixture.csv',text(sleeps))


def test_source_audit_detects_mismatch_and_excludes_holdout(tmp_path,diagnostic_data):
    dataset,plan=diagnostic_data
    cutoff=date.fromisoformat(plan['developmentEnd'])
    archive=tmp_path/'source.zip'
    make_archive(archive,dataset,cutoff)
    with pytest.raises(ValueError,match='development data only'):
        audit_sources(dataset,archive,cutoff)
    count=sum(d<=cutoff for d in dataset.dates)
    development=replace(dataset,dates=dataset.dates[:count],rows=dataset.rows[:count])
    audit=audit_sources(development,archive,cutoff)
    assert audit['allCheckedValuesMatch']
    assert audit['allRecoveryLabelsAtMidnightUTC']
    rows=list(development.rows); rows[0]={**rows[0],'hrv_ms':9999.}
    changed=audit_sources(replace(development,rows=tuple(rows)),archive,cutoff)
    assert not changed['allCheckedValuesMatch']
    assert changed['mismatches'][0]['metric']=='hrv_ms'


def test_invalid_fold_cannot_reach_holdout(tmp_path,diagnostic_data):
    _,plan=diagnostic_data
    path=tmp_path/'plan.json'
    plan['folds'][-1]['end']=plan['holdoutStart']
    path.write_text(json.dumps(plan))
    with pytest.raises(ValueError,match='before the holdout'):
        load_plan(path)


def test_diagnostic_outputs_plots_and_no_holdout_predictions(tmp_path,diagnostic_data,monkeypatch):
    monkeypatch.setenv('MPLCONFIGDIR',str(tmp_path/'mpl-cache'))
    dataset,plan=diagnostic_data
    path=tmp_path/'daily.csv';plan_path=tmp_path/'plan.json';archive=tmp_path/'source.zip'
    with path.open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=['date',*dataset.rows[0]])
        writer.writeheader()
        writer.writerows({'date':day.isoformat(),**row} for day,row in zip(dataset.dates,dataset.rows))
    plan_path.write_text(json.dumps(plan))
    make_archive(archive,dataset,date.fromisoformat(plan['developmentEnd']))
    args=Namespace(plan=plan_path,data=path,archive=archive,output_root=tmp_path/'results',chronos=False,device='cpu',revision='main')
    output=run_diagnostic(args)
    assert (output/'forecast_comparison.png').stat().st_size>1000
    assert (output/'source_jumps.png').stat().st_size>1000
    assert json.loads((output/'manifest.json').read_text())['testEvaluated'] is False
    with (output/'predictions.csv').open() as handle:
        predictions=list(csv.DictReader(handle))
    assert all(row['targetEnd']<=plan['developmentEnd'] for row in predictions)
    assert all(row['contextEnd']<row['date'] for row in predictions)
    three=[row for row in predictions if row['horizonDays']=='3']
    assert all((date.fromisoformat(row['targetEnd'])-date.fromisoformat(row['date'])).days==2 for row in three)
    # Changing every held-out measurement must leave all development forecasts unchanged.
    with path.open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=['date',*dataset.rows[0]])
        writer.writeheader()
        writer.writerows({'date':day.isoformat(),**(row if day<date.fromisoformat(plan['holdoutStart']) else {key:999999. for key in row})}
                         for day,row in zip(dataset.dates,dataset.rows))
    second=run_diagnostic(args)
    assert (output/'predictions.csv').read_text()==(second/'predictions.csv').read_text()
