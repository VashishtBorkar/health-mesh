from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pytest
import csv
import hashlib
import json

from healthmesh_ml.data import DailyDataset, Window
from healthmesh_ml.models import Forecast
from healthmesh_ml.personalization import apply_offset, fit_offset, tuning_inputs
from healthmesh_ml.finalize import finalize, refresh_development


def example(day, actual):
    dates = tuple(day-timedelta(days=7-i) for i in range(7))
    return Window(day, dates, tuple({'hrv_ms': 60., 'steps': 1000.} for _ in dates), actual)


def test_calibration_is_median_training_residual_and_clips_zero():
    windows = [example(date(2026, 9, 1)+timedelta(days=i), v) for i, v in enumerate([40., 50., 600.])]
    fitted = fit_offset(windows, [Forecast(60.), Forecast(60.), Forecast(60.)])
    assert fitted['offsetMs'] == -10.
    assert fitted['latestTrainingTargetEnd'] == '2026-09-05'
    assert apply_offset([Forecast(50.), Forecast(5.), Forecast(None)], fitted) == [Forecast(40.), Forecast(0.), Forecast(None)]
    with pytest.raises(ValueError):
        fit_offset(windows[:2], [Forecast(1.), Forecast(1.)])


def test_tuning_inputs_mask_future_covariates_and_keep_daily_targets():
    dates = tuple(date(2026, 9, 1)+timedelta(days=i) for i in range(14))
    rows = tuple({'hrv_ms': 50.+i, 'steps': 1000.+i} for i in range(14))
    dataset = DailyDataset(dates, rows, 'synthetic')
    window = Window(dates[7], dates[:7], rows[:7], 58.)
    plan = {'target': 'hrv_ms', 'featureGroups': {'combined': ['hrv_ms', 'steps']}}
    values = tuning_inputs(dataset, [window], plan)[0]
    assert values['target'].tolist() == list(range(50, 60))
    assert values['past_covariates']['steps'][:7].tolist() == list(range(1000, 1007))
    assert np.isnan(values['past_covariates']['steps'][7:]).all()
    assert 'future_covariates' not in values
    # Changing later targets or target-day covariates cannot change fitting inputs.
    changed = tuple({**r, 'steps': 999999.} if i >= 7 else r for i, r in enumerate(rows))
    changed = changed[:10] + tuple({'hrv_ms': 999999., 'steps': 999999.} for _ in rows[10:])
    after = tuning_inputs(replace(dataset, rows=changed), [window], plan)[0]
    np.testing.assert_equal(values['target'], after['target'])
    np.testing.assert_equal(values['past_covariates']['steps'], after['past_covariates']['steps'])


def test_actual_chronos_dataset_has_only_intended_split():
    torch = pytest.importorskip('torch')
    pytest.importorskip('chronos')
    from chronos.chronos2.dataset import Chronos2Dataset, DatasetMode
    inputs = [{'target': np.arange(10, dtype=np.float32),
               'past_covariates': {'steps': np.array([1.]*7+[np.nan]*3, dtype=np.float32)}}]
    dataset = Chronos2Dataset(inputs, context_length=7, prediction_length=3,
                             batch_size=2, output_patch_size=16, min_past=7, mode=DatasetMode.TRAIN)
    for _ in range(3):
        context, target, covariates, n_targets = dataset._construct_slice(0)
        assert context.shape == (2, 7)
        assert n_targets == 1
        assert target[0, :3].tolist() == [7., 8., 9.]
        assert torch.isnan(target[1]).all()
        assert torch.isnan(covariates).all()


def test_finalization_freezes_before_scoring_and_refuses_repeat(tmp_path, monkeypatch):
    data = tmp_path / 'daily.csv'
    with data.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=['date', 'hrv_ms', 'steps'])
        writer.writeheader()
        for i in range(69):
            writer.writerow({'date': (date(2026,8,14)+timedelta(days=i)).isoformat(), 'hrv_ms': 50+i*.1, 'steps': 1000+i})
    plan = {'target': 'hrv_ms', 'contextDays': 7, 'minTargetObservations': 3, 'minimumTrainingExamples': 10,
            'ridgeAlpha': 10., 'developmentEnd': '2026-10-07', 'holdoutStart': '2026-10-08',
            'folds': [{'start': '2026-09-17'}], 'featureGroups': {'combined': ['hrv_ms', 'steps']}}
    run = tmp_path / 'development'
    run.mkdir()
    manifest = {'status': 'complete', 'testEvaluated': False, 'fineTuningEnabled': True, 'plan': plan,
                'datasetSHA256': hashlib.sha256(data.read_bytes()).hexdigest()}
    (run / 'manifest.json').write_text(json.dumps(manifest))
    (run / 'metrics.json').write_text(json.dumps({'pooled': {'models': {
        'ridge/combined': {'mae': 1., 'rmse': 2.}, 'trailing_median_7': {'mae': 3., 'rmse': 4.}},
        'strongestSimpleBaseline': 'trailing_median_7', 'pairedScoredDays': 10}}))
    output = tmp_path / 'final'
    import healthmesh_ml.finalize as module
    original = module.fold_predictions
    def guarded(*args):
        assert (output / 'selection.json').is_file()
        assert json.loads((output / 'selection.json').read_text())['selectedModel'] == 'ridge/combined'
        return original(*args)
    monkeypatch.setattr(module, 'fold_predictions', guarded)
    finalize(run, data, output)
    result = json.loads((output / 'test_results.json').read_text())
    assert result['testEvaluated'] is True
    assert all('2026-10-08' <= r['date'] <= '2026-10-19' for r in result['predictions'])
    dashboard = json.loads((output / 'dashboard.json').read_text())
    assert dashboard['selectedModel'] == 'ridge/combined'
    assert dashboard['testCount'] == 12
    before = (output / 'test_results.json').read_bytes()
    with pytest.raises(FileExistsError):
        finalize(run, data, output)
    assert (output / 'test_results.json').read_bytes() == before
    frozen = (output / 'selection.json').read_bytes()
    verified = tmp_path / 'verified'
    verified.mkdir()
    (verified / 'manifest.json').write_text(json.dumps({**manifest, 'adapterSourceRun': str(run.resolve())}))
    (verified / 'metrics.json').write_text((run / 'metrics.json').read_text())
    refresh_development(verified, output)
    assert (output / 'test_results.json').read_bytes() == before
    assert (output / 'selection.json').read_bytes() == frozen
    assert json.loads((output / 'dashboard.json').read_text())['developmentVerification']
