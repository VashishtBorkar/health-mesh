"""Repeatable local import of the class project's two personal exports."""
from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

from healthmesh.connectors.personal_exports import build_personal_dataset


def write_outputs(directory: Path, dataset, database: str | None = None, result: dict | None = None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    report = {**dataset.report, "database": database, "importResult": result}
    (directory / "healthmesh_personal_daily.csv").write_text(dataset.csv_content, encoding="utf-8")
    (directory / "coverage_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = ["# Personal data coverage", "", f"Period: {report['startDate']} through {report['endDate']} ({report['calendarDays']} calendar days).", "",
             "| Metric | Observed days | Missing days | Longest missing run |", "| --- | ---: | ---: | ---: |"]
    for item in report["coverage"]:
        lines.append(f"| {item['metric']} | {item['observedDays']} | {item['missingDays']} | {item['longestMissingRun']} |")
    lines += ["", "## Modeling overlap", "", *[f"- {key}: {value}" for key,value in report["overlap"].items()],
              "", "## Import decisions", "", *[f"- {key}: {value}" for key,value in report["auditCounts"].items()],
              "", "## Definitions", "", *[f"- {key}: {value}" for key,value in report["definitions"].items()],
              "", "## Notes", "", *[f"- {warning}" for warning in report["warnings"]],
              "", "Original exports and this report are personal data. Keep the entire output directory ignored by Git.", ""]
    (directory / "coverage_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--google-health", type=Path, required=True)
    parser.add_argument("--cronometer", type=Path, required=True)
    parser.add_argument("--through", type=date.fromisoformat, help="Last included date; default is day before newest Cronometer date")
    parser.add_argument("--nutrition-days-complete", action="store_true", help="User confirms populated nutrition days represent full days")
    parser.add_argument("--fallback-timezone", default="America/New_York")
    parser.add_argument("--output-dir", type=Path, default=Path("health-info/processed"))
    parser.add_argument("--database", type=Path, help="Optional separate SQLite file; otherwise the platform personal database")
    parser.add_argument("--preview", action="store_true", help="Validate and report coverage without database or output writes")
    args = parser.parse_args()
    dataset = build_personal_dataset(args.google_health, args.cronometer, through=args.through,
                                    nutrition_days_complete=args.nutrition_days_complete,
                                    fallback_timezone=args.fallback_timezone)
    if args.preview:
        print(json.dumps(dataset.report, indent=2))
        return
    # Configure before importing application modules that construct the DB engine.
    os.environ["HEALTHMESH_PROFILE"] = "personal"
    if args.database:
        database_path = args.database.resolve()
        database_path.parent.mkdir(parents=True, exist_ok=True)
        os.environ["HEALTHMESH_DATABASE_URL"] = f"sqlite:///{database_path}"
    else:
        os.environ.pop("HEALTHMESH_DATABASE_URL", None)
    from sqlalchemy import select
    from healthmesh.db import SessionLocal, database_url
    from healthmesh.main import run_migrations
    from healthmesh.models import DataSource, ImportRecord, Observation
    from healthmesh.services.imports import import_parsed_csv

    run_migrations()
    with SessionLocal() as session:
        # Never mingle the demonstration or canonical-CSV source with these exports.
        other_source = session.scalar(select(ImportRecord.id).join(DataSource).where(DataSource.key != "personal_exports").limit(1))
        if other_source is not None:
            raise ValueError("Destination already contains other imports; choose a separate personal database")
        source = session.scalar(select(DataSource).where(DataSource.key == "personal_exports"))
        if source is None:
            source = DataSource(key="personal_exports", name="Fitbit and Cronometer", connector_type="file")
            session.add(source)
            session.flush()
        result = import_parsed_csv(session, dataset.parsed, source_key="personal_exports").as_dict()
        # Reconcile every imported value against the independently parsed daily ledger.
        stored = {(item.observed_date, item.metric.key): item.value for item in session.scalars(select(Observation).where(Observation.source_id == source.id))}
        expected = {(row.observed_date,key): value for row in dataset.parsed.rows for key,value in row.values.items()}
        mismatches = [key for key,value in expected.items() if key not in stored or abs(stored[key]-value) > 1e-6]
        if mismatches:
            raise RuntimeError(f"Database reconciliation failed for {len(mismatches)} observations")
        dataset.report["verifiedObservationCount"] = len(expected)
    write_outputs(args.output_dir, dataset, database_url(), result)
    print(json.dumps({"database": database_url(), "dateRange": result["dateRange"],
                      "status": result["status"], "verifiedObservations": len(expected),
                      "outputDirectory": str(args.output_dir), "overlap": dataset.report["overlap"]}, indent=2))


if __name__ == "__main__":
    main()
