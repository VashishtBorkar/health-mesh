.PHONY: setup migrate dev backend frontend test run sample import-personal run-personal dev-personal

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
	env -u HEALTHMESH_DATABASE_URL HEALTHMESH_PROFILE=personal $(MAKE) run

dev-personal:
	env -u HEALTHMESH_DATABASE_URL HEALTHMESH_PROFILE=personal $(MAKE) dev
