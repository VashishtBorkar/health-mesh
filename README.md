# HealthMesh

HealthMesh is a local-first personal health data platform. Phase one imports a documented daily CSV into a local SQLite database and presents the data through the Vital Ledger dashboard. Sleep, recovery, activity, nutrition, and body measurements stay on the user's computer.

Coach, Insights, forecasting, and anomaly detection have reserved interfaces but are deliberately disabled in this phase. The application does not provide medical advice.

## What works

- Atomic CSV validation and import with row-level error messages
- Idempotent exact re-imports and non-empty updates for overlapping dates
- Local provenance, import history, and metric coverage
- Overview, Sleep, Recovery, Activity, Nutrition, Body, and Compare views
- Seven-calendar-day moving averages with honest gaps and sample counts
- Aligned scatterplots and Pearson associations with matched-date counts
- Empty-state template and synthetic 90-day sample downloads
- Disabled, truthful Coach and Insights capability contracts

## Requirements

- Python 3.12
- [`uv`](https://docs.astral.sh/uv/) recommended; `make setup` has a standard Python fallback
- Node.js 20 or newer and npm

## Start the application

```bash
make setup
make dev
```

Open `http://127.0.0.1:5173`. The Vite frontend and FastAPI backend run separately in development.

For a production-style local run, FastAPI serves the compiled frontend:

```bash
make run
```

Then open `http://127.0.0.1:8000`.

## First import

1. Open HealthMesh and choose **Import CSV**.
2. Download the empty template or use the bundled 90-day sample.
3. Preview the file, then import it.
4. Move through the domain pages or compare any two recorded numeric metrics.

The files are also available directly in [`fixtures/`](./fixtures). [`fixtures/README.md`](./fixtures/README.md) is the complete data dictionary.

## Local data

The database is created outside the repository in the operating system's application-data directory:

- macOS: `~/Library/Application Support/HealthMesh/healthmesh.db`
- Linux: the platform user-data directory, normally `~/.local/share/HealthMesh/healthmesh.db`
- Windows: the platform local application-data directory

For development or testing, set `HEALTHMESH_DATA_DIR` or `HEALTHMESH_DATABASE_URL`. Database files, uploads, logs, environment files, dependencies, and compiled assets are ignored by Git.

## Useful commands

```bash
make setup     # install Python and frontend dependencies
make dev       # run Vite and FastAPI with reload
make test      # run backend and frontend tests
make run       # build the frontend and serve everything on port 8000
make migrate   # apply the SQLite schema migrations
make sample    # regenerate the deterministic synthetic fixture
```

## Repository guide

- [`frontend/`](./frontend) — React, TypeScript, ECharts, and the Vital Ledger UI
- [`backend/`](./backend) — FastAPI, SQLAlchemy, Alembic, import validation, and analytics
- [`fixtures/`](./fixtures) — empty template, synthetic sample, and data dictionary
- [`project_context.md`](./project_context.md) — enduring project vision
- [`design_and_implementation_plan.md`](./design_and_implementation_plan.md) — implemented phase-one contracts and future extension points

## API

The versioned API is under `/api/v1`. Interactive documentation is available at `/docs` while the backend is running. The dashboard and any future Coach or anomaly tools consume the same backend analytics functions so metric definitions remain consistent.
