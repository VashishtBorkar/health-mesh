"""Freeze a development winner and evaluate the reserved three-day HRV test once."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

from .cli import DEFAULT_DATA, DEFAULT_OUTPUT, implementation_hash, package_versions, write_json
from .data import read_dataset
from .diagnostic import fold_predictions
from .evaluation import prediction_records, score


def finalize(run_dir, data, output):
    manifest = json.loads((run_dir / 'manifest.json').read_text())
    development = json.loads((run_dir / 'metrics.json').read_text())
    if manifest['status'] != 'complete' or manifest['testEvaluated'] or not manifest['fineTuningEnabled']:
        raise ValueError('Select only from a completed development personalization comparison including LoRA')
    if hashlib.sha256(data.read_bytes()).hexdigest() != manifest['datasetSHA256']:
        raise ValueError('Dataset differs from the development snapshot')
    scores = development['pooled']['models']
    winner = min((k for k, m in scores.items() if m['mae'] is not None), key=lambda k: scores[k]['mae'])
    # This first release can finalize baseline/ridge winners. A Chronos winner
    # needs a separately implemented final-training path, never a silent fallback.
    if winner.startswith('chronos/'):
        raise ValueError('Chronos won development; implement its final-training path before opening the test')
    baseline = development['pooled']['strongestSimpleBaseline']
    output.mkdir(parents=True, exist_ok=True)
    selection = {'selectedModel': winner, 'baseline': baseline, 'rule': 'Lowest pooled development MAE; no test-based selection',
                 'developmentRun': str(run_dir.resolve()), 'developmentManifestSHA256': hashlib.sha256((run_dir / 'manifest.json').read_bytes()).hexdigest(),
                 'datasetSHA256': manifest['datasetSHA256'], 'plan': manifest['plan'],
                 'frozenAt': datetime.now(timezone.utc).isoformat(), 'implementationSHA256': implementation_hash()}
    # Exclusive creation protects against accidental repeat evaluations. Even a
    # failed evaluation leaves the frozen receipt and is not automatically retried.
    with (output / 'selection.json').open('x') as handle:
        json.dump(selection, handle, indent=2, allow_nan=False)
    write_json(output / 'status.json', {'status': 'started', 'testEvaluated': False})
    plan = manifest['plan']
    # The reserved dates are explicit, never inferred from extra appended data.
    test_start, test_end = date(2026, 10, 8), date(2026, 10, 21)
    if plan['developmentEnd'] != '2026-10-07' or plan['holdoutStart'] != test_start.isoformat():
        raise ValueError('Unexpected final holdout dates')
    config = {**plan, 'horizonDays': 1, 'quantiles': [.1, .5, .9],
              'trainEnd': plan['developmentEnd'], 'validationEnd': plan['developmentEnd'], 'testEnd': test_end.isoformat()}
    dataset = read_dataset(data, config)
    fold = {'name': 'final-test', 'trainEnd': plan['developmentEnd'], 'start': test_start.isoformat(), 'end': test_end.isoformat()}
    examples, predictions, artifacts = fold_predictions(dataset, plan, fold, 3)
    predictions = {k: predictions[k] for k in dict.fromkeys([winner, baseline])}
    result = score(examples, predictions)
    if not result['pairedScoredDays']:
        raise ValueError('No complete final-test targets')
    records = prediction_records(examples, predictions)
    write_json(output / 'test_results.json', {'selection': selection, 'scores': result, 'predictions': records,
                                             'environment': package_versions(), 'testEvaluated': True})
    write_json(output / 'training_artifacts.json', artifacts)
    names = list(predictions)
    points = [{'date': w.target_date.isoformat(), 'targetEnd': (w.target_date+timedelta(days=2)).isoformat(),
               'actual': w.actual, 'selected': predictions[winner][i].point,
               'baseline': predictions[baseline][i].point} for i, w in enumerate(examples)]
    dashboard = {
        'available': True, 'target': 'Average HRV over the next three calendar days', 'unit': 'ms',
        'selectedModel': winner, 'baseline': baseline, 'contextDays': 7,
        'developmentRange': {'start': plan['folds'][0]['start'], 'end': plan['developmentEnd']},
        'testRange': {'start': test_start.isoformat(), 'end': test_end.isoformat()},
        'frozenAt': selection['frozenAt'], 'developmentCount': development['pooled']['pairedScoredDays'],
        'developmentModels': [{'model': k, 'mae': v['mae'], 'rmse': v['rmse']} for k, v in scores.items()],
        'testCount': result['pairedScoredDays'],
        'testModels': [{'model': k, 'mae': result['models'][k]['mae'], 'rmse': result['models'][k]['rmse']} for k in names],
        'points': points,
        'limitations': ['Single-person exploratory study with very few observations.',
                         'Three-day targets overlap; forecast errors are not independent.',
                         'All three future readings are required for scoring; no target interpolation.',
                         'Historical backtest, not a live forecast or medical recommendation.',
                         'Earlier test observations enter later contexts; fitted parameters stay frozen.',
                         'Chronos adapters learn daily quantile forecasts; ridge predicts the three-day mean directly.'],
    }
    write_json(output / 'dashboard.json', dashboard)
    selected_mae = result['models'][winner]['mae']
    baseline_mae = result['models'][baseline]['mae']
    lines = ['# Frozen HRV final-test result', '', f'Selected using development only: `{winner}`.',
             f'Reference baseline fixed from development: `{baseline}`.', '',
             f'Test: October 8–21. Complete scored origins: {result["pairedScoredDays"]}.',
             f'Selected-model MAE: {selected_mae:.2f} ms. Baseline MAE: {baseline_mae:.2f} ms.', '',
             'This test is now consumed. Do not tune against it or describe a later revised model as independently tested.', '',
             *['- '+s for s in dashboard['limitations']], '']
    (output / 'report.md').write_text('\n'.join(lines))
    write_json(output / 'status.json', {'status': 'complete', 'testEvaluated': True})
    print(json.dumps({'outputDirectory': str(output), 'selectedModel': winner, 'scores': result}, indent=2))
    return output


def refresh_development(run_dir, output):
    """Attach a verified saved-adapter comparison without refitting or rescoring test."""
    selection = json.loads((output / 'selection.json').read_text())
    verified = json.loads((run_dir / 'manifest.json').read_text())
    if (verified['status'] != 'complete' or verified['testEvaluated']
            or verified['datasetSHA256'] != selection['datasetSHA256']
            or verified['adapterSourceRun'] != selection['developmentRun']
            or verified['plan'] != selection['plan']):
        raise ValueError('Verification must reuse the original development adapters, plan, and data')
    metrics = json.loads((run_dir / 'metrics.json').read_text())['pooled']
    note = 'Chronos adapter development predictions were verified from saved weights in evaluation mode. The original frozen selection and final-test scores are unchanged.'
    audit = {'verifiedDevelopmentRun': str(run_dir.resolve()),
             'reason': 'Explicit evaluation mode disables LoRA dropout during prediction.',
             'manifestSHA256': hashlib.sha256((run_dir / 'manifest.json').read_bytes()).hexdigest(),
             'testRescored': False, 'selectionChanged': False}
    # Read the dashboard export, never the test dataset or fitting pipeline.
    dashboard = json.loads((output / 'dashboard.json').read_text())
    dashboard['developmentModels'] = [{'model': k, 'mae': v['mae'], 'rmse': v['rmse']}
                                      for k, v in metrics['models'].items()]
    dashboard['developmentVerification'] = note
    write_json(output / 'development_verification.json', audit)
    write_json(output / 'dashboard.json', dashboard)
    print(json.dumps(audit, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--data', type=Path, default=DEFAULT_DATA)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT / 'hrv-final-v1')
    parser.add_argument('--refresh-development', action='store_true', help='Attach verified saved-adapter development results; never evaluate test')
    args = parser.parse_args()
    try:
        if args.refresh_development:
            refresh_development(args.run_dir, args.output)
        else:
            finalize(args.run_dir, args.data, args.output)
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        parser.exit(2, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
