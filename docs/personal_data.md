# Fitbit and Cronometer personal history

This class-project workflow reads a Google Health Takeout ZIP and a Cronometer
**Daily Nutrition** CSV. It imports the measurements into a separate SQLite
database, retaining the canonical CSV import service and existing dashboard.
It does not require provider APIs or account credentials.

## Import and open the personal dashboard

Place the two exports under the git-ignored `health-info/` directory as:

```text
health-info/google-health-info.zip
health-info/cronometer-info.csv
```

Export Cronometer daily totals with diary group rows disabled.

```bash
make import-personal
make run-personal
```

Open http://127.0.0.1:8000. The header says **personal history**. Stop an existing
server on that port first. `make dev-personal` is the equivalent development
workflow (frontend on port 5173).

The personal database is `healthmesh-personal.db` inside the platform HealthMesh
application-data directory. The usual `make run` still opens `healthmesh.db`.
Neither command deletes or modifies the other profile's data.

`make import-personal` includes `--nutrition-days-complete` because this project's
user confirmed that populated Cronometer entries represent full days even though
they never press the diary-complete button. A blank nutrition day stays missing.
The original flag is retained in raw provenance. Omit that option for an export
where full-day logging has not been confirmed.

The newest Cronometer date is excluded by default because the export may have
been created during that day. To choose an explicit inclusive cutoff:

```bash
.venv/bin/python -m healthmesh.personal_import \
  --google-health health-info/google-health-info.zip \
  --cronometer health-info/cronometer-info.csv \
  --nutrition-days-complete \
  --through YYYY-MM-DD
```

Use `--preview` to validate and print coverage without writing files or opening a
database. `--database /absolute/path/to/separate.db` selects a different destination
for testing. A destination containing other imports is rejected to prevent mixing
synthetic and personal histories. Re-running the same input and conversion policy
is a no-op. Corrections update non-empty observations without duplicating them.
An earlier cutoff does not delete data from a prior, longer import; use a new
database if an isolated shorter snapshot is needed.

## Outputs

Generated files remain under `health-info/processed/`, ignored by Git:

- `healthmesh_personal_daily.csv`: normalized daily values, with missing cells blank.
- `coverage_report.md`: observed days, missing days, missing runs, overlap, and decisions.
- `coverage_report.json`: the same report plus export hashes, import result, and conversion version.

The database's `source_rows` retain per-metric source file names and original CSV
row numbers, original Cronometer completion flags, and the input hashes/policy.
Keep the original exports to follow these references back to their source.
The archive is read in place, never extracted. Account, location, conversation,
and unrelated sensor files are not imported.

## Conversion rules

- Daily HRV is nightly RMSSD in milliseconds. Recovery timestamps at midnight UTC
  are treated as provider date labels, rather than shifted into the preceding day.
- Sleep is assigned to its local wake date using the session's explicit end offset.
  Overlapping alternative sessions prefer algorithm v2, then latest update.
  Disjoint naps are included. Stage durations use only retained session IDs.
- Sleep efficiency is total recorded minutes asleep divided by total recorded
  minutes in the sleep period. Inconsistent stage totals are omitted and counted.
- Timed activity uses the latest preceding explicit offset from sleep/exercise
  records. Before the first anchor, the fallback is `America/New_York` (configurable).
  Offset transitions between sessions are inferred. Review travel dates against
  the source app before relying on those dates for modeling.
- Steps use Fitbit device records only. Energy uses Google Health App records.
  Phone Health Kit activity is excluded so the sources are not added together.
- Steps, total calories, active energy, and cardio-load increments are summed by
  local day. Active energy is never added to total energy expenditure.
- Training load is the provider-specific total cardio-load increment, not a
  generic fitness score. Its definition is included in the coverage report.
- Workout duration is the union of exercise intervals, split at local midnight.
  Deleted records are excluded. No workout record leaves a missing value, not an
  assumed zero. This is elapsed session duration, including any pauses.
- Weight is converted from grams to pounds. Conflicting same-day readings are
  rejected for review rather than silently choosing a value.
- Cronometer owns intake and nutrients. `Carbs (g)` maps to total carbohydrates;
  net carbs are not substituted. Google Health's synced nutrition is excluded.
- Explicit zeroes remain zero. Nothing is interpolated or imputed for this import.

## Verification and next phase

The converter validates the full canonical CSV before the database is opened.
After importing, every generated observation is reconciled against its stored
value. Automated synthetic tests cover source selection, sleep overlap, local
midnight, exercise interval unions, grams-to-pounds conversion, completion
provenance, invalid input, cutoffs, and repeat imports.

The report identifies candidate forecasting targets and overlapping nutrition.
It is not a train/test split or a trained model. Next, create versioned modeling
datasets with historical input masks and chronological evaluation periods.
