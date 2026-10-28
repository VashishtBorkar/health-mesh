.PHONY: setup migrate dev backend frontend test run sample import-personal run-personal dev-personal setup-ml setup-chronos setup-finetune prepare-hrv baseline-hrv chronos-hrv diagnose-hrv diagnose-hrv-chronos calibrate-hrv finetune-hrv test-ml

ML_DEVICE ?= cpu

setup:
	@if command -v uv >/dev/null 2>&1; then \
		cd backend && UV_PROJECT_ENVIRONMENT=../.venv uv sync --python 3.12 --extra dev --frozen; \
	else \
		python3 -m venv .venv; \
		.venv/bin/python -m pip install -e './backend[dev]'; \
	fi
	cd frontend && npm install

migrate:
	cd backend && ../.venv/bin/alembic upgrade head

backend:
	cd backend && ../.venv/bin/uvicorn healthmesh.main:app --reload --host 127.0.0.1 --port 8000

frontend:
	cd frontend && npm run dev -- --host 127.0.0.1

dev:
	@trap 'kill 0' INT TERM EXIT; $(MAKE) backend & $(MAKE) frontend & wait

test:
	.venv/bin/pytest backend/tests
	cd frontend && npm test -- --run

run:
	cd frontend && npm run build
	cd backend && ../.venv/bin/uvicorn healthmesh.main:app --host 127.0.0.1 --port 8000

sample:
	python3 backend/scripts/generate_sample.py

# These inputs and generated outputs stay in the git-ignored health-info directory.
import-personal:
	.venv/bin/python -m healthmesh.personal_import --google-health health-info/google-health-info.zip --cronometer health-info/cronometer-info.csv --nutrition-days-complete

run-personal:
	env -u HEALTHMESH_DATABASE_URL HEALTHMESH_PROFILE=personal HEALTHMESH_MODEL_REPORT="$(CURDIR)/health-info/modeling/hrv-final-v1/dashboard.json" $(MAKE) run

dev-personal:
	env -u HEALTHMESH_DATABASE_URL HEALTHMESH_PROFILE=personal HEALTHMESH_MODEL_REPORT="$(CURDIR)/health-info/modeling/hrv-final-v1/dashboard.json" $(MAKE) dev

# The research environment is separate from the FastAPI environment.
setup-ml:
	@if command -v uv >/dev/null 2>&1; then \
		cd ml && uv sync --python 3.12 --extra dev --frozen; \
	else \
		.venv/bin/python -m venv ml/.venv; \
		ml/.venv/bin/python -m pip install -e './ml[dev]'; \
	fi

setup-chronos:
	@if command -v uv >/dev/null 2>&1; then \
		cd ml && uv sync --python 3.12 --extra dev --extra chronos --frozen; \
	else \
		.venv/bin/python -m venv ml/.venv; \
		ml/.venv/bin/python -m pip install -e './ml[dev,chronos]'; \
	fi

prepare-hrv:
	ml/.venv/bin/python -m healthmesh_ml.cli prepare

setup-finetune:
	@if command -v uv >/dev/null 2>&1; then \
		cd ml && uv sync --python 3.12 --extra dev --extra finetune --frozen; \
	else \
		.venv/bin/python -m venv ml/.venv; \
		ml/.venv/bin/python -m pip install -e './ml[dev,finetune]'; \
	fi

calibrate-hrv:
	HF_HOME="$(CURDIR)/health-info/model-cache" MPLCONFIGDIR="$(CURDIR)/health-info/modeling/.matplotlib" ml/.venv/bin/python -m healthmesh_ml.personalization --device $(ML_DEVICE)

finetune-hrv:
	HF_HOME="$(CURDIR)/health-info/model-cache" MPLCONFIGDIR="$(CURDIR)/health-info/modeling/.matplotlib" ml/.venv/bin/python -m healthmesh_ml.personalization --finetune --device $(ML_DEVICE)

baseline-hrv:
	ml/.venv/bin/python -m healthmesh_ml.cli baselines

chronos-hrv:
	HF_HOME="$(CURDIR)/health-info/model-cache" ml/.venv/bin/python -m healthmesh_ml.cli chronos

diagnose-hrv:
	MPLCONFIGDIR="$(CURDIR)/health-info/modeling/.matplotlib" ml/.venv/bin/python -m healthmesh_ml.diagnostic

diagnose-hrv-chronos:
	HF_HOME="$(CURDIR)/health-info/model-cache" MPLCONFIGDIR="$(CURDIR)/health-info/modeling/.matplotlib" ml/.venv/bin/python -m healthmesh_ml.diagnostic --chronos

test-ml:
	ml/.venv/bin/python -m pytest ml/tests
