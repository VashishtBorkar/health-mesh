from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from dataclasses import dataclass
from datetime import date

from healthmesh.metrics import INTEGER_KEYS, METRIC_DEFINITIONS, PERCENTAGE_KEYS, SLEEP_STAGE_KEYS

MAX_FILE_SIZE = 10 * 1024 * 1024


@dataclass(frozen=True)
class ValidationIssue:
    row: int | None
    column: str | None
    code: str
    message: str

    def as_dict(self) -> dict[str, object]:
        return {"row": self.row, "column": self.column, "code": self.code, "message": self.message}


class CSVValidationError(Exception):
    def __init__(self, issues: list[ValidationIssue], warnings: list[str] | None = None):
        super().__init__("CSV validation failed")
        self.issues = issues
        self.warnings = warnings or []


@dataclass(frozen=True)
class ParsedRow:
    row_number: int
    observed_date: date
    values: dict[str, float]
    nutrition_completeness: str | None
    raw_payload: dict[str, str]
    checksum: str
    ignored_values: int


@dataclass(frozen=True)
class ParsedCSV:
    filename: str
    sha256: str
    metric_columns: list[str]
    rows: list[ParsedRow]
    warnings: list[str]

    @property
    def start_date(self) -> date:
        return min(row.observed_date for row in self.rows)

    @property
    def end_date(self) -> date:
        return max(row.observed_date for row in self.rows)


class CSVConnector:
    source_key = "healthmesh_csv"

    def parse(self, content: bytes, filename: str) -> ParsedCSV:
        if len(content) > MAX_FILE_SIZE:
            raise CSVValidationError([
                ValidationIssue(None, None, "file_too_large", "CSV files may not exceed 10 MB.")
            ])

        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise CSVValidationError([
                ValidationIssue(None, None, "invalid_encoding", "The CSV must use UTF-8 encoding.")
            ]) from exc

        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise CSVValidationError([
                ValidationIssue(1, None, "missing_header", "The CSV must contain a header row.")
            ])

        headers = [header.strip() if header else "" for header in reader.fieldnames]
        if len(headers) != len(set(headers)):
            raise CSVValidationError([
                ValidationIssue(1, None, "duplicate_header", "Column names must be unique.")
            ])
        reader.fieldnames = headers

        issues: list[ValidationIssue] = []
        warnings: list[str] = []
        if "date" not in headers:
            issues.append(ValidationIssue(1, "date", "missing_required_column", "A date column is required."))

        metric_columns = [header for header in headers if header in METRIC_DEFINITIONS]
        if not metric_columns:
            issues.append(ValidationIssue(1, None, "missing_metric_column", "Include at least one recognized metric column."))

        known = {"date", "nutrition_complete", *METRIC_DEFINITIONS.keys()}
        unknown = [header for header in headers if header and header not in known]
        if unknown:
            warnings.append(f"Ignored unknown columns: {', '.join(unknown)}")
        if issues:
            raise CSVValidationError(issues, warnings)

        parsed_rows: list[ParsedRow] = []
        seen_dates: set[date] = set()
        observed_values = 0

        for row_number, raw_row in enumerate(reader, start=2):
            normalized = {str(key).strip(): (value or "").strip() for key, value in raw_row.items() if key is not None}
            date_text = normalized.get("date", "")
            try:
                observed_date = date.fromisoformat(date_text)
            except ValueError:
                issues.append(ValidationIssue(row_number, "date", "invalid_date", "Use the date format YYYY-MM-DD."))
                continue

            if observed_date in seen_dates:
                issues.append(ValidationIssue(row_number, "date", "duplicate_date", f"{date_text} appears more than once in this file."))
                continue
            seen_dates.add(observed_date)

            values: dict[str, float] = {}
            ignored_values = 0
            for key in metric_columns:
                raw_value = normalized.get(key, "")
                if raw_value == "":
                    ignored_values += 1
                    continue
                try:
                    value = float(raw_value)
                except ValueError:
                    issues.append(ValidationIssue(row_number, key, "invalid_number", f"{key} must be numeric or blank."))
                    continue
                if not math.isfinite(value):
                    issues.append(ValidationIssue(row_number, key, "invalid_number", f"{key} must be a finite number or blank."))
                    continue
                if value < 0:
                    issues.append(ValidationIssue(row_number, key, "negative_value", f"{key} cannot be negative."))
                    continue
                if key in PERCENTAGE_KEYS and value > 100:
                    issues.append(ValidationIssue(row_number, key, "invalid_percentage", f"{key} must be between 0 and 100."))
                    continue
                if key in INTEGER_KEYS and not value.is_integer():
                    issues.append(ValidationIssue(row_number, key, "invalid_integer", f"{key} must be a whole number."))
                    continue
                values[key] = value
                observed_values += 1

            duration = values.get("sleep_duration_min")
            stage_total = sum(values.get(key, 0) for key in SLEEP_STAGE_KEYS)
            if duration is not None and stage_total > duration + 0.001:
                issues.append(ValidationIssue(
                    row_number,
                    "sleep_duration_min",
                    "sleep_stages_exceed_duration",
                    "Deep, REM, and light sleep cannot total more than sleep duration.",
                ))

            nutrition = normalized.get("nutrition_complete", "").lower()
            if nutrition not in {"", "true", "false"}:
                issues.append(ValidationIssue(
                    row_number,
                    "nutrition_complete",
                    "invalid_boolean",
                    "nutrition_complete must be true, false, or blank.",
                ))
                nutrition_value = None
            else:
                nutrition_value = {"true": "complete", "false": "partial", "": None}[nutrition]

            canonical_raw = {header: normalized.get(header, "") for header in headers}
            checksum = hashlib.sha256(json.dumps(canonical_raw, sort_keys=True).encode()).hexdigest()
            parsed_rows.append(ParsedRow(
                row_number=row_number,
                observed_date=observed_date,
                values=values,
                nutrition_completeness=nutrition_value,
                raw_payload=canonical_raw,
                checksum=checksum,
                ignored_values=ignored_values,
            ))

        if not parsed_rows and not issues:
            issues.append(ValidationIssue(None, None, "empty_file", "The CSV does not contain any data rows."))
        if observed_values == 0 and not issues:
            issues.append(ValidationIssue(None, None, "no_values", "The CSV does not contain any non-empty metric values."))
        if issues:
            raise CSVValidationError(issues, warnings)

        return ParsedCSV(
            filename=filename,
            sha256=hashlib.sha256(content).hexdigest(),
            metric_columns=metric_columns,
            rows=parsed_rows,
            warnings=warnings,
        )
