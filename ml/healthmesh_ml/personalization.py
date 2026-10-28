"""Training-only HRV bias correction and a fixed Chronos LoRA experiment."""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import copy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import gc
import hashlib
import json
from pathlib import Path
from statistics import median

import numpy as np

from .cli import DEFAULT_CONFIG, DEFAULT_DATA, DEFAULT_OUTPUT, implementation_hash, package_versions, write_json
from .data import read_dataset, public_window
from .diagnostic import load_plan, period_windows, fold_predictions, summarize, write_csv
from .evaluation import score, prediction_records
from .models import ChronosForecaster, Forecast
from .source_audit import audit_sources


def load_experiment(path):
    experiment = json.loads(path.read_text())
    if experiment['horizonDays'] != 3 or experiment['featureGroup'] != 'combined':
        raise ValueError('This experiment fixes the three-day target and combined feature group')
    if experiment['calibration'] != 'training_median_residual':
        raise ValueError('Unsupported calibration method')
    settings = experiment['finetune']
    if (settings['mode'] != 'lora' or not 1 <= settings['rank'] <= 8
            or not 1 <= settings['numSteps'] <= 100 or not 1 <= settings['batchSize'] <= 64
            or not 0 < settings['learningRate'] <= 0.0001 or settings['alpha'] <= 0
            or not 0 <= settings['dropout'] < 1 or not settings['targetModules']):
        raise ValueError('Invalid small-experiment LoRA settings')
    return experiment, load_plan(path.parent / experiment['diagnosticPlan'])


def fit_offset(training, predictions):
    if len(training) != len(predictions):
        raise ValueError('Calibration predictions must match training windows')
    residuals = [w.actual - p.point for w, p in zip(training, predictions)
                 if w.actual is not None and p.point is not None]
    if len(residuals) < 3:
        raise ValueError('At least three training residuals are required')
    return {'method': 'training_median_residual', 'offsetMs': float(median(residuals)),
            'count': len(residuals), 'latestTrainingTargetEnd':
            (max(w.target_date for w in training) + timedelta(days=2)).isoformat()}


def apply_offset(predictions, calibration):
    # This is point-only calibration, not calibrated predictive uncertainty.
    return [Forecast(max(0.0, p.point + calibration['offsetMs']))
            if p.point is not None else Forecast(None) for p in predictions]


def tuning_inputs(dataset, training, plan):
    """Exactly one eligible seven-past/three-future split per input sequence.

    Chronos samples its split between min_past and length - prediction_length.
    Setting min_past=7 on a length-10 sequence fixes that split to seven.
    Only the target has future observations. Covariates are padded with NaN.
    """
    positions = {day: i for i, day in enumerate(dataset.dates)}
    result = []
    for window in training:
        if window.actual is None:
            continue
        index = positions[window.target_date]
        future = [r[plan['target']] for r in dataset.rows[index:index+3]]
        if len(future) != 3 or any(v is None for v in future):
            raise ValueError('Fine-tuning requires all three target readings')
        values = [r[plan['target']] for r in window.history] + future
        covariates = {key: np.asarray([r[key] for r in window.history] + [np.nan]*3, dtype=np.float32)
                      for key in plan['featureGroups']['combined'] if key != plan['target']}
        result.append({'target': np.asarray(values, dtype=np.float32), 'past_covariates': covariates})
    return result


def tune(base, inputs, experiment, plan, output):
    # Chronos otherwise silently falls back to full fine-tuning without PEFT.
    import peft  # noqa: F401
    import torch
    settings = experiment['finetune']
    np.random.seed(plan['seed'])
    torch.manual_seed(plan['seed'])
    pipeline = base.pipeline.fit(
        inputs=inputs, prediction_length=3, validation_inputs=None,
        finetune_mode='lora', lora_config={
            'r': settings['rank'], 'lora_alpha': settings['alpha'],
            'lora_dropout': settings['dropout'], 'target_modules': settings['targetModules'],
        },
        context_length=7, min_past=7, learning_rate=settings['learningRate'],
        num_steps=settings['numSteps'], batch_size=settings['batchSize'], output_dir=output,
        seed=plan['seed'], data_seed=plan['seed'], report_to='none',
        logging_steps=10, disable_tqdm=True, optim='adamw_torch',
        dataloader_pin_memory=False,
    )
    if not hasattr(pipeline.model, 'peft_config'):
        raise ValueError('Expected LoRA adapters; refusing full-model fine-tuning')
    trainable, total = pipeline.model.get_nb_trainable_parameters()
    tuned = copy(base)
    tuned.pipeline = pipeline
    checkpoint = output / 'finetuned-ckpt'
    # The upstream adapter defaults to an unpinned base model. Pin its reload
    # metadata as well as the experiment manifest, then save the adapter again.
    for adapter in pipeline.model.peft_config.values():
        adapter.revision = base.resolved_revision
    pipeline.save_pretrained(checkpoint)
    # Record hashes of the private adapter files; the base model revision is in manifest.
    hashes = {str(p.relative_to(checkpoint)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(checkpoint.rglob('*')) if p.is_file()}
    return tuned, {'trainableParameters': trainable, 'totalParameters': total,
                   'checkpoint': str(checkpoint.resolve()), 'checkpointSHA256': hashes,
                   'trainingWindows': len(inputs), 'settings': settings}


def report(directory, metrics, folds, audit, finetuned):
    lines = ['# Three-day HRV personalization experiment', '',
             'Exploratory development comparison. October 8–21 was not evaluated.', '',
             'Seven-day context; combined Fitbit/Cronometer inputs; three expanding-training folds.',
             'Calibration uses median residuals from pretrained forecasts of training windows only.',
             'LoRA, when enabled, restarts from the same pretrained checkpoint for every fold.', '',
             '| Model | MAE (ms) | RMSE (ms) | Improvement vs best simple | Folds won |',
             '| --- | ---: | ---: | ---: | ---: |']
    for name, m in sorted(metrics['models'].items(), key=lambda item: item[1]['mae']):
        lines.append(f"| {name} | {m['mae']:.2f} | {m['rmse']:.2f} | {m['improvementVsStrongestSimplePct']:+.1f}% | {m['foldWinsVsStrongestSimple']}/{m['scoredFolds']} |")
    lines += ['', f"Common scored origins: {metrics['pairedScoredDays']}. Strongest simple baseline: `{metrics['strongestSimpleBaseline']}`.", '',
              '| Fold | Complete training windows | Scored origins | Calibration offset (ms) | Ridge combined MAE | Calibrated Chronos MAE | LoRA MAE |',
              '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for fold in folds:
        values = fold['scores']['models']
        tuned = f"{values['chronos/lora']['mae']:.2f}" if finetuned else 'not run'
        lines.append(f"| {fold['fold']['name']} | {fold['trainingExamples']} | {fold['scores']['pairedScoredDays']} | {fold['calibration']['offsetMs']:+.2f} | {values['ridge/combined']['mae']:.2f} | {values['chronos/calibrated']['mae']:.2f} | {tuned} |")
    lines += ['', '![Forecasts](personalization.png)', '',
              f"Source checks: {audit['checkedHRV']} HRV readings and {audit['checkedSleepDays']} sleep totals; {len(audit['mismatches'])} mismatches.", '',
              'Three-day targets overlap and require three actual readings. No target interpolation or fabricated aggregate uncertainty interval is used.',
              'This repeats development evaluation after earlier results; it is not an independent confirmation. No model selection or final test is performed by this command.',
              'LoRA optimizes daily HRV quantile loss and averages daily marginal medians at inference. It does not directly optimize the three-day mean.',
              'Fixed steps, rank, and learning rate; no early stopping on development folds and no hyperparameter search.', '']
    (directory / 'report.md').write_text('\n'.join(lines))


def plot(directory, records, plan):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    fig, ax = plt.subplots(figsize=(12, 5), layout='constrained')
    observed = {r['date']: r['actual'] for r in records}
    dates = sorted(observed)
    x = [date.fromisoformat(d) for d in dates]
    ax.plot(x, [observed[d] if observed[d] is not None else np.nan for d in dates],
            color='#26372f', marker='o', label='Actual three-day mean', linewidth=2)
    models = [('trailing_median_7', '#888888', '--'), ('ridge/combined', '#8d2e2c', '-'),
              ('chronos/calibrated', '#356b89', '-'), ('chronos/lora', '#b78028', '-')]
    for model, color, style in models:
        series = {r['date']: r['prediction'] for r in records if r['model'] == model}
        if series:
            ax.plot(x, [series.get(d, np.nan) for d in dates], color=color, linestyle=style, label=model)
    for fold in plan['folds'][1:]:
        ax.axvline(date.fromisoformat(fold['start']), color='#cccccc', linewidth=.8)
    ax.set(title='Three-day HRV personalization — development only', ylabel='HRV (ms)', xlabel='First target date')
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
    ax.grid(axis='y', alpha=.2)
    ax.legend(loc='upper right', fontsize=9)
    fig.savefig(directory / 'personalization.png', dpi=150)
    plt.close(fig)


def run(args):
    experiment, plan = load_experiment(args.experiment)
    config = {**plan, 'horizonDays': 1, 'quantiles': [.1, .5, .9],
              'trainEnd': plan['folds'][0]['trainEnd'], 'validationEnd': plan['developmentEnd'],
              'testEnd': plan['holdoutStart']}
    full = read_dataset(args.data, config)
    limit = sum(day <= date.fromisoformat(plan['developmentEnd']) for day in full.dates)
    dataset = replace(full, dates=full.dates[:limit], rows=full.rows[:limit])
    audit = audit_sources(dataset, args.archive, date.fromisoformat(plan['developmentEnd']))
    if audit['mismatches']:
        raise ValueError('Source audit failed')
    if args.finetune:
        import peft  # noqa: F401
    directory = args.output_root / experiment['name'] / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory.mkdir(parents=True, exist_ok=False)
    base = ChronosForecaster(plan['modelId'], args.device, args.revision, plan['seed'])
    adapter_source = getattr(args, 'adapters_from', None)
    if adapter_source:
        if not args.finetune:
            raise ValueError('--adapters-from requires --finetune')
        source_manifest = json.loads((adapter_source / 'manifest.json').read_text())
        if (source_manifest['status'] != 'complete' or not source_manifest['fineTuningEnabled']
                or source_manifest['experiment'] != experiment or source_manifest['plan'] != plan
                or source_manifest['datasetSHA256'] != full.sha256
                or source_manifest['chronos']['resolvedRevision'] != base.resolved_revision):
            raise ValueError('Adapter source must match the completed experiment, plan, data, and base checkpoint')
    manifest = {'experiment': experiment, 'plan': plan, 'datasetSHA256': full.sha256,
                'implementationSHA256': implementation_hash(), 'environment': package_versions(),
                'chronos': base.artifact(), 'fineTuningEnabled': args.finetune, 'testEvaluated': False,
                'status': 'running', 'createdAt': datetime.now(timezone.utc).isoformat()}
    manifest['adapterSourceRun'] = str(adapter_source.resolve()) if adapter_source else None
    write_json(directory / 'manifest.json', manifest)
    records, contexts, fold_reports, all_examples = [], [], [], []
    all_predictions = defaultdict(list)
    for fold in plan['folds']:
        print(f"Running {fold['name']} (training through {fold['trainEnd']})", flush=True)
        train_end = date.fromisoformat(fold['trainEnd'])
        training = [w for w in period_windows(dataset, plan, dataset.dates[0], train_end, 3) if w.actual is not None]
        examples, predictions, artifacts = fold_predictions(dataset, plan, fold, 3)
        keys = plan['featureGroups']['combined']
        train_predictions = base.predict(training, plan['target'], keys, 7, horizon=3)
        raw = base.predict(examples, plan['target'], keys, 7, horizon=3)
        calibration = fit_offset(training, train_predictions)
        predictions['chronos/combined'] = raw
        predictions['chronos/calibrated'] = apply_offset(raw, calibration)
        write_csv(directory / f"{fold['name']}_calibration.csv", prediction_records(training, {'chronos/combined': train_predictions}))
        if args.finetune:
            if adapter_source:
                from chronos import Chronos2Pipeline
                fitted = json.loads((adapter_source / f"{fold['name']}_artifacts.json").read_text())['lora']
                checkpoint = Path(fitted['checkpoint'])
                for relative, expected in fitted['checkpointSHA256'].items():
                    if hashlib.sha256((checkpoint / relative).read_bytes()).hexdigest() != expected:
                        raise ValueError('Saved adapter checksum differs')
                tuned = copy(base)
                tuned.pipeline = Chronos2Pipeline.from_pretrained(checkpoint, device_map=args.device)
            else:
                tuned, fitted = tune(base, tuning_inputs(dataset, training, plan), experiment, plan, directory / fold['name'])
            predictions['chronos/lora'] = tuned.predict(examples, plan['target'], keys, 7, horizon=3)
            artifacts['lora'] = fitted
            del tuned
            gc.collect()
        result = score(examples, predictions)
        fold_reports.append({'fold': fold, 'trainingExamples': len(training), 'calibration': calibration, 'scores': result})
        write_json(directory / f"{fold['name']}_artifacts.json", {'calibration': calibration, **artifacts})
        records.extend({'fold': fold['name'], 'targetEnd': (date.fromisoformat(r['date'])+timedelta(days=2)).isoformat(), **r}
                       for r in prediction_records(examples, predictions))
        for stage, windows in [('training', training), ('development', examples)]:
            contexts.extend({'fold': fold['name'], 'stage': stage, **public_window(w, plan)} for w in windows)
        all_examples.extend(examples)
        for name, values in predictions.items():
            all_predictions[name].extend(values)
    metrics = summarize(all_examples, dict(all_predictions), [f['scores'] for f in fold_reports])
    write_json(directory / 'metrics.json', {'pooled': metrics, 'folds': fold_reports})
    write_json(directory / 'source_audit.json', audit)
    write_csv(directory / 'predictions.csv', records)
    with (directory / 'windows.jsonl').open('w') as handle:
        for context in contexts:
            handle.write(json.dumps(context, allow_nan=False)+'\n')
    plot(directory, records, plan)
    report(directory, metrics, fold_reports, audit, args.finetune)
    manifest['status'] = 'complete'
    write_json(directory / 'manifest.json', manifest)
    print(json.dumps({'outputDirectory': str(directory), 'testEvaluated': False,
                      'mae': {k: v['mae'] for k, v in metrics['models'].items()}}, indent=2))
    return directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', type=Path, default=DEFAULT_CONFIG.parent / 'hrv_personalization_v1.json')
    parser.add_argument('--data', type=Path, default=DEFAULT_DATA)
    parser.add_argument('--archive', type=Path, default=DEFAULT_DATA.parents[1] / 'google-health-info.zip')
    parser.add_argument('--output-root', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    parser.add_argument('--revision', default='29ec3766d36d6f73f0696f85560a422f50e8498c')
    parser.add_argument('--finetune', action='store_true')
    parser.add_argument('--adapters-from', type=Path, help='Re-evaluate matching saved adapters without retraining; validates manifest and file hashes')
    args = parser.parse_args()
    try:
        run(args)
    except (ValueError, ImportError, FileNotFoundError) as exc:
        parser.exit(2, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
