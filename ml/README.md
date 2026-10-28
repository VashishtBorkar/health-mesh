# HRV forecasting experiment

This workspace studies next-day HRV and average HRV over the next three days from
daily Fitbit and Cronometer history. Training runs independently of the dashboard
and never changes the personal database. Predictions, adapters, and reports remain
private. The dashboard can display an explicitly exported final experiment report.

## Run locally

First complete `make import-personal`, then:

```bash
make setup-ml
make prepare-hrv
make baseline-hrv
make test-ml
```

To install the optional pretrained-model dependencies and compare Chronos-2:

```bash
make setup-chronos
make chronos-hrv
```

The first Chronos run downloads model weights. Prediction runs locally; personal
measurements are not sent to an inference service. The Make target puts the
weight cache under the ignored `health-info/model-cache/` directory. HRV experiments
and per-date results are saved under `health-info/modeling/hrv-v1/`.

With `uv`, setup uses the frozen `ml/uv.lock`. The pip fallback resolves the
declared ranges. Each result records installed package versions, the input SHA-256,
configuration, and resolved model revision. Keep the original input and lockfile
to reproduce an experiment.

## Research question and predeclared configuration

Can additional sleep, activity, and nutrition history improve next-day HRV
forecasts relative to HRV history alone?

`experiments/hrv_v1.json` declares:

- Target: daily nightly RMSSD, `hrv_ms`, in milliseconds.
- Timing: at the end of D, forecast the HRV assigned to D+1.
- Horizon: one calendar day.
- Context: 14 calendar days by default; seven days is a development comparison.
- Initial training: August 14 through September 23, 2026.
- Validation: September 24 through October 7.
- Final test: October 8 through October 21.
- Minimum coverage: three observed target values in a context window.
- Ridge regularization: alpha 10, fixed before validation.

The source snapshot is the canonical personal daily CSV. Gaps in the calendar are
inserted as missing rows. Explicit zeroes remain zero. Feature groups are:

| Group | Inputs |
| --- | --- |
| `history` | HRV |
| `fitbit` | HRV, sleep duration, sleep efficiency, steps, cardio load |
| `combined` | Fitbit inputs plus calories consumed, protein, total carbohydrates, fat |

Weight is excluded because coverage is inadequate. Workout duration is excluded
from the first experiment because missing exercise logs do not establish zero
activity. Raw sleep stages are excluded initially to keep the input set small.

## Baselines

- `training_mean` and `training_median`: constants fitted to observed target values
  in the training period only, including early days without a full context.
- `persistence`: latest observed HRV within the context window.
- `trailing_mean_7`: average of recorded HRV in the preceding seven calendar days,
  requiring at least three observations.
- `trailing_median_7`: median over that same window and coverage requirement.
- `ridge/history`, `ridge/fitbit`, `ridge/combined`: regularized regression using
  each metric's latest observed value, seven-day mean, missing fraction, and age
  of the latest observation. Numeric summaries missing entirely from a window
  are filled using the training-example mean. Coverage and age remain explicit
  features. Regression weights, means, and scales are fitted only on training
  examples. Predictions are bounded below by zero.

Missing target values are never imputed for training or scoring. Training examples
are overlapping windows, not independent participants or independent trials.

## Chronos

The default model is `amazon/chronos-2`, loaded through `Chronos2Pipeline`.
The initial runner performs pretrained inference only. No weights are updated.

Historical covariates are explicitly past-only. Missing values are passed as NaN
for Chronos's native missing-data handling. Forecast q50 is the point prediction;
q10–q90 forms a nominal 80% interval. The report measures interval coverage and
width rather than assuming that the interval is calibrated to personal health.

`cross_learning=False` is explicit: a later context window in an inference batch
must never provide information to an earlier forecast. Contexts always end on
the preceding date. Future target-day sleep, nutrition, and activity are absent
from predictor inputs. Forecasts are bounded below by zero.

Official references:

- [Chronos-2 model card](https://huggingface.co/amazon/chronos-2)
- [Pipeline and prediction API](https://github.com/amazon-science/chronos-forecasting/blob/main/src/chronos/chronos2/pipeline.py)

## University GPU execution

Copy the repository and private canonical CSV to your own university workspace.
No raw archive is needed for model execution. Keep personal inputs and generated
results out of Git there as well.

```bash
cd ml
uv sync --python 3.12 --extra dev --extra chronos --frozen
uv run --extra dev --extra chronos --frozen python -m healthmesh_ml.cli chronos \
  --data ../health-info/processed/healthmesh_personal_daily.csv \
  --device cuda
```

For local CPU inference, use `--device cpu` (the default). To pin a particular
checkpoint, pass `--revision <model-commit>`. Save the printed result directory.

## Evaluation and holdout protection

All normal runs evaluate validation only. MAE, RMSE, and prediction bias are
reported in milliseconds, on the intersection of observed dates where every
reported model has a prediction. Counts and excluded dates are explicit.
Chronos also receives interval coverage, mean width, and mean pinball loss.
No confidence intervals or significance claims are attached to this small study.

Each rolling forecast uses earlier observations, including earlier validation
or test days when they become history. Fitted parameters remain frozen. The
retrospective protocol assumes prior-day summaries were available by the end of
that day; provider release delays and historical revisions are not replayed.

Use validation to choose the model, features, and context length. A seven-day
comparison is explicit:

```bash
ml/.venv/bin/python -m healthmesh_ml.cli baselines --context-days 7
```

Only after model selection, save an immutable selection file and evaluate the
final test. These commands are intentionally not run by the standard Make targets:

```bash
ml/.venv/bin/python -m healthmesh_ml.cli select \
  --run-dir <validation-result-directory> \
  --model ridge/combined \
  --output health-info/modeling/hrv-v1/selection.json

ml/.venv/bin/python -m healthmesh_ml.cli evaluate-test \
  --selection health-info/modeling/hrv-v1/selection.json
```

The test command checks the dataset hash and selected validation manifests and
uses the saved configuration and model revision. It does not accept a context
override. This prevents accidental changes, not deliberate repeated test tuning.
Do not choose a different model after seeing the final test to present that result
as an untouched holdout.

## Result files

- `manifest.json`: configuration, source hash, dependency versions, model revision,
  development sample counts, and evaluation stage.
- `windows.jsonl`: exact historical contexts and observed masks for each forecast.
- `predictions.csv`: forecast date, actual value, point forecast, error, and optional quantiles.
- `metrics.json`: comparison metrics on paired dates.
- `ridge_artifacts.json`: regression coefficients and training-only preprocessing.
- `report.md`: readable validation or test report.

Each evaluation creates a new result directory. Preparation refuses to overwrite
a manifest for a different snapshot. Generated reports and weights stay ignored.

## Next experiments

The diagnostic and personalization experiments below are complete for the
current snapshot. Further adaptation requires a new evaluation period because
the final test has been consumed. Anomaly calibration and live forecast integration
remain future work. A separate sleep-duration experiment needs its own declared
configuration, target timing, and independent evaluation data.

## Raw HRV versus three-day HRV diagnostic

```bash
make diagnose-hrv           # five simple baselines and three ridge feature groups
make diagnose-hrv-chronos   # also run the three pretrained Chronos feature groups
```

These commands require the original Google Health archive as well as the canonical
CSV. The archive is checked read-only; neither command changes the database or
the input CSV. Results stay under ignored `health-info/modeling/hrv-diagnostic-v1/`.
The fixed plan is `experiments/hrv_diagnostic_v1.json`:

| Fold | Train through | Development evaluation |
| --- | --- | --- |
| 1 | September 16 | September 17–23 |
| 2 | September 23 | September 24–30 |
| 3 | September 30 | October 1–7 |

Each model gets seven calendar days of past context, with at least three recorded
HRV readings. Seven days, rather than fourteen, retains at least ten complete
three-day training targets in the earliest fold. Ridge alpha remains 10; there is
no parameter sweep. Regression and its preprocessing are refitted once at each
fold boundary. Earlier evaluation observations can enter later forecast contexts.

The two tasks predict either the next day's recorded HRV or the average over the
next three calendar days. All three future readings must exist for a three-day
label. Training and evaluation labels must end within their respective periods,
so the final two possible origins in each three-day evaluation fold are excluded.
Missing target values are never interpolated. Ridge learns the three-day average
directly. Chronos forecasts three raw daily values and averages their marginal
medians; this is a point forecast, not a distributional forecast of the average.
Daily marginal quantiles are not averaged into an interval for the mean.

The report compares each task against its own strongest simple baseline, shows
fold results and actual-versus-predicted plots, and records raw-export checks for
HRV and local-wake-date sleep aggregation. Large changes remain in the data.
Matching exports establishes ingestion consistency, not device accuracy.

This diagnostic was designed after viewing the initial validation results; it is
exploratory. Adjacent three-day labels overlap, and the small number of scored
origins does not support significance claims. Lower absolute error for a smoothed
target alone is not evidence of a better model. The descriptive screen (at least
5% lower pooled MAE and a majority of fold wins against each fold's strongest
simple baseline) is a development heuristic, not proof of generalization.

The diagnostic runner excludes October 8–21 rows from source
checks, feature generation, fitting, plotting, and scoring. It does not write a
model selection or run a final test. Tests verify that changing held-out values
cannot change any development prediction.

Combined ridge was the strongest three-day development candidate; neither ridge
nor pretrained Chronos improved next-day HRV over the best simple baseline.
The later final test described below did not confirm ridge's development advantage.

## Personal calibration and LoRA fine-tuning

```bash
make setup-finetune
make calibrate-hrv
make finetune-hrv                 # CPU is sufficient for this tiny experiment
make finetune-hrv ML_DEVICE=cuda  # university GPU, one visible GPU
```

The fixed plan is `experiments/hrv_personalization_v1.json`. It reuses the three
development folds and seven-day context, restricting Chronos to combined inputs
and the three-day HRV target. There is no parameter sweep. Each fold:

1. Computes pretrained forecasts of complete training targets and fits one
   additive correction: the median of actual minus predicted training values.
   The offset is frozen for the evaluation fold. Evaluation outcomes do not fit it.
2. Creates one ten-day sequence per complete training window: seven historical
   days plus three raw HRV target readings. All covariates in those last three days
   are NaN. `min_past=7` fixes Chronos's random split to the intended origin.
3. Restarts from the pinned original checkpoint and trains LoRA adapters for 30
   steps, learning rate 1e-5, rank 4, alpha 8, dropout 0.05, batch size 16, seed 42.
   Only the attention query/value adapters train: 294,912 parameters of roughly
   120 million. No development labels are passed as training or early-stopping data.
4. Scores raw, calibrated, and adapted Chronos alongside the unchanged baselines
   and ridge models on common dates.

Fine-tuning minimizes Chronos's daily quantile loss. The point forecast of the
three-day average remains the mean of three marginal medians; it is not trained
directly on the mean and has no claimed uncertainty interval for that aggregate.
Calibration is applied to pretrained forecasts only, keeping the comparison small.

Each run saves private adapters (with pinned base revision), hashes, training-only
calibration residuals, coefficients, contexts, metrics, and a plot under
`health-info/modeling/hrv-personalization-v1/`. Without PEFT the command fails
instead of silently using full-model fine-tuning. The implementation follows the
[official Chronos fit API](https://github.com/amazon-science/chronos-forecasting/blob/main/src/chronos/chronos2/pipeline.py).

On the current development snapshot (10 overlapping scored origins), MAE was
9.33 ms for combined ridge, 12.25 for the seven-day median, 21.39 for pretrained
Chronos, 23.83 for calibration, and 21.37 for LoRA. Adapting Chronos did not beat
the simple baseline. These are exploratory results from very little data.

For university execution, copy the private canonical CSV and Google archive to
their original ignored locations, then run the Make commands above. Install
CUDA-compatible PyTorch for the university's driver environment before running;
the checked-in lock records the package versions, not the university's CUDA driver.
GPU results may differ slightly from local CPU results. Do not repeatedly use the
consumed test period to select revised models.

## Frozen selection, final test, and dashboard

The separate explicit finalization command freezes the model with lowest pooled
development MAE before opening the October 8–21 labels:

```bash
ml/.venv/bin/python -m healthmesh_ml.finalize --run-dir <completed-personalization-run>
```

It requires a completed LoRA comparison and matching input hash, writes
`health-info/modeling/hrv-final-v1/selection.json` with exclusive creation, fits the
selected baseline/ridge model through October 7, and evaluates only that model and
the baseline fixed from development. It refuses repeat evaluation when the
selection receipt exists. Chronos winners are explicitly unsupported by this
first final-training runner, rather than silently substituted. After a failed
finalization, inspect the receipt and failure before attempting recovery.

**The current snapshot has already been finalized. October 8–21 is consumed.**
Combined ridge was selected on development data. Across 12 complete overlapping
held-out origins, ridge MAE was **7.77 ms**, versus **6.45 ms** for the seven-day
median baseline. Its development advantage did not generalize to this test.
The selected model remains ridge in the record; the baseline was not selected
retroactively. New claims of generalization need genuinely new held-out data.

A saved-adapter reload check caught active LoRA dropout immediately after
training. Predictions now explicitly call `eval()`. Re-evaluation of the saved
adapters corrected LoRA development MAE from 20.16 to 21.37 ms; it did not change
the winner. The original selection and final-test records remain immutable.
`personalization --finetune --adapters-from <original-run>` verifies matching
manifests and adapter hashes before re-evaluating development only.
`finalize --refresh-development --run-dir <verified-run>` attaches that verified
comparison to the dashboard without training, reading test measurements, or
rescoring the test. A separate verification record documents this correction.

`make run-personal` loads the saved `dashboard.json` into `/modeling`. The page
shows the development comparison, final metrics, and recorded-versus-predicted
test chart with explicit limitations. It does not run inference. The backend's
`GET /api/v1/modeling/report` exposes the report only with the personal profile
and explicit `HEALTHMESH_MODEL_REPORT` path; a default/sample installation has no
personal report. Dashboard date controls do not change the fixed study periods.
