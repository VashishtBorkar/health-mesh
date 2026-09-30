# HealthMesh Design and Implementation Plan

## Status and scope

Phase one is implemented. Its purpose is to establish a dependable local data foundation and a useful dashboard before adding provider automation or machine learning.

The current application:

- is single-user, daily-granularity, and local-only;
- accepts the canonical HealthMesh daily CSV;
- stores normalized observations and source provenance in SQLite;
- renders the Vital Ledger dashboard in a local browser;
- treats missing values, explicit zeroes, and nutrition completeness distinctly; and
- exposes disabled Coach and Insights contracts without generating fake results.

Raw Fitbit and Cronometer parsing, OAuth, cloud services, authentication, automatic sync, desktop packaging, LLM inference, forecasting, and anomaly detection are outside phase one.

## Architecture

```text
HealthMesh daily CSV
        |
        v
CSV connector: decode -> validate full file -> normalize rows
        |
        v
Atomic import service -> provenance + normalized SQLite records
        |
        +----------------------+
        |                      |
        v                      v
Shared analytics service   Import history / coverage
        |
        v
Versioned FastAPI endpoints
        |
        v
React + ECharts Vital Ledger dashboard
```

The analytics service is independent of the HTTP and chart layers. Future Coach tools, anomaly detection, and forecasting should call this same service rather than reimplementing metric definitions.

### Technology

| Layer | Implementation |
| --- | --- |
| Frontend | React, TypeScript, Vite, React Router |
| Charts | Apache ECharts |
| Backend | Python 3.12 and FastAPI |
| Data | SQLite, SQLAlchemy, Alembic |
| Tooling | `uv`, npm, Make |
| Local production | Compiled frontend served by FastAPI on `127.0.0.1` |

The platform application-data directory contains the database outside the repository. `HEALTHMESH_DATA_DIR` and `HEALTHMESH_DATABASE_URL` provide explicit development overrides.

## Canonical CSV contract

Files are UTF-8, comma-delimited, and contain one row per local calendar date. `date` is required and uses `YYYY-MM-DD`. At least one recognized metric column must be present; any subset is valid.

```text
date
sleep_duration_min
sleep_efficiency_pct
deep_sleep_min
rem_sleep_min
light_sleep_min
hrv_ms
resting_heart_rate_bpm
respiratory_rate_bpm
steps
active_calories_kcal
total_calories_burned_kcal
workout_duration_min
training_load
calories_consumed_kcal
protein_g
carbohydrates_g
fat_g
fiber_g
nutrition_complete
weight_lb
body_fat_pct
```

Validation rules:

- Blank metric cells are missing and never become zero.
- Explicit zeroes are retained.
- `nutrition_complete` accepts `true`, `false`, or blank.
- Percentages are between 0 and 100.
- Counts, durations, energy, nutrients, weight, and physiological values are nonnegative.
- Steps are whole numbers.
- Recorded sleep stages cannot total more than sleep duration.
- Duplicate dates within a file are rejected.
- Unknown columns are ignored and returned as warnings.
- Files over 10 MB are rejected.
- The complete file is validated before any database write.

[`fixtures/healthmesh_daily_template.csv`](./fixtures/healthmesh_daily_template.csv) is the empty template. [`fixtures/healthmesh_daily_sample.csv`](./fixtures/healthmesh_daily_sample.csv) is a deterministic, synthetic 90-day history. [`fixtures/README.md`](./fixtures/README.md) defines every field and unit.

## Import and reconciliation behavior

The CSV connector returns normalized rows to a connector-neutral import service. This is the extension point for future Fitbit and Cronometer connectors.

Each import follows this sequence:

1. Enforce the size and encoding requirements.
2. Validate headers and every row in memory.
3. Compute file and row SHA-256 checksums.
4. Detect an exact prior file hash and return a no-op.
5. Create the import and raw source-row provenance records.
6. Insert new source/date/metric observations.
7. Update only non-empty overlapping values that changed.
8. Preserve existing values when a later cell is blank.
9. Commit the whole import atomically.

The response reports processed rows, created values, updated values, unchanged values, ignored blanks, warnings, and date coverage. An invalid file leaves all existing data unchanged.

## Database contract

| Table | Purpose |
| --- | --- |
| `data_sources` | Stable source key, display name, and connector type |
| `imports` | File hash, columns, range, outcome counts, warnings, and timestamp |
| `source_rows` | Original row number, local date, checksum, and raw JSON provenance |
| `metric_definitions` | Metric domain, label, unit, type, aggregation, and chart configuration |
| `observations` | Unique source/date/metric numeric values and latest import |
| `day_metadata` | Date-level quality metadata, currently nutrition completeness |

The first migration creates the schema and seeds the HealthMesh CSV source and all metric definitions. The unique source/date/metric constraint prevents duplicate normalized values.

## API contract

All application endpoints are versioned below `/api/v1`.

| Endpoint | Behavior |
| --- | --- |
| `GET /health` | Service and database status |
| `POST /imports/csv` | Multipart, validated, atomic CSV import |
| `GET /imports` | Import provenance and result summaries |
| `GET /metrics` | Definitions and observed coverage |
| `GET /analytics/overview` | Period summaries, coverage, and latest import |
| `GET /analytics/timeseries` | Gap-preserving series and optional rolling average |
| `GET /analytics/compare` | Aligned pairs, coverage, matched count, and association |
| `GET /analytics/nutrition-completeness` | Complete, partial, and unknown nutrition-day counts |
| `GET /capabilities` | `dataPlatform: true`, `coach: false`, `insights: false` |
| `GET /insights` | `{ enabled: false, items: [] }` |
| `POST /coach/query` | Validates the future request and returns structured HTTP 501 |
| `GET /downloads/template` | Empty canonical template |
| `GET /downloads/sample` | Synthetic 90-day sample |

The reserved Coach request carries `message` plus route, date range, and metric-key context. The reserved Insight shape carries identity, type, severity, status, date range, title, summary, and metric evidence.

## Analytics rules

- Date presets end on the latest imported date, never the computer's current date.
- Seven-day averages use calendar windows, skip missing observations, and require at least three values.
- Period averages include observed values only and return their sample count.
- Missing dates remain null so charts render gaps.
- Energy balance exists only when both recorded intake and total expenditure exist on that date.
- Compare aligns exact local dates and always reports its matched sample count.
- Pearson correlation is hidden for fewer than three pairs or a constant series.
- Correlation is presented as an exploratory association, not causation.
- CSV nutrition is described as recorded intake unless completeness is explicitly true.

## Vital Ledger interface

The visual system uses locally bundled Newsreader and IBM Plex Sans Condensed fonts, a paper-toned ruled surface, oxblood primary accents, sage data accents, and a compact circular navigation rail. It supports keyboard focus, reduced motion, chart descriptions, light/dark color schemes, and a compact layout below 800 pixels.

Shared controls include Import CSV and 30-day, 90-day, all-data, and custom ranges. The range persists while navigating.

### Routes and chart organization

- `/` — four summaries; weight; energy balance; sleep and HRV; data coverage; latest source; reserved intelligence space
- `/sleep` — duration and rolling average; stage composition; efficiency
- `/recovery` — HRV, resting heart rate, respiratory rate, and sleep-versus-HRV scatterplot
- `/activity` — steps, active calories, workout duration, training load, and workout-day count
- `/nutrition` — intake versus expenditure, macro composition, protein/fiber, and completeness
- `/body` — weight, seven-day trend, body fat, latest value, and period change
- `/compare` — two unit-preserving time series, matched scatterplot, coverage, sample count, and Pearson association
- `/data` — template/sample actions and local import register
- `/insights` — disabled future anomaly interface
- `/coach` — disabled future local-LLM interface

Every chart has a planned Coach affordance whose URL carries the active route, date range, and metric keys. The future model can therefore receive explicit UI context without coupling inference to chart code.

## Empty and import states

A fresh database contains metric definitions but no demonstration observations. The Overview presents a three-step guide with sample and template downloads.

Before upload, the browser shows the file name, recognized fields, total columns, size, and first five rows. The backend remains authoritative. On success, the interface reports result counts, warnings, and coverage, refreshes all queries, and selects the imported date range. Validation errors identify row, column, and reason.

## Verification

Backend tests cover parsing, missing versus zero, all validation boundaries, transaction safety, file idempotency, overlap updates, provenance, rolling averages, energy balance, aligned comparison, sample thresholds, and disabled intelligence contracts.

Frontend tests cover the guided empty state, fixture actions, every route, CSV preview and submission, and truthful Coach/Insights states. The production TypeScript/Vite build is also part of verification.

The end-to-end checkpoint posts the bundled 90-day sample through the HTTP API, confirms the latest-date 30-day Overview, verifies Compare pairing, re-imports the same file, updates an overlap, and proves an invalid upload preserves the existing observation count.

## Future phases

1. Add provider-specific connector adapters for Fitbit/Google Health and Cronometer while retaining the canonical import service.
2. Add scheduling, provider authorization, source priorities, correction windows, and clear sync status.
3. Add a local LLM runtime that can call read-only analytics tools and cite dates, units, counts, and coverage.
4. Build a versioned daily feature pipeline with missingness masks and chronological data splits.
5. Establish naive and classical baselines before training the temporal Transformer.
6. Derive explainable personalized anomalies from evaluated forecast errors.
7. Consider Tauri packaging, backup/restore, and database encryption as distribution requirements become clearer.

HealthMesh remains a personal analytics and research tool, not a diagnostic system or substitute for qualified medical care.
