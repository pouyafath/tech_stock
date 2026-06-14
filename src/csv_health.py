"""CSV schema inspection for Wealthsimple holdings and activities exports."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

HOLDINGS_REQUIRED_COLUMNS = {
    "symbol",
    "quantity",
    "market price",
    "market price currency",
    "book value (market)",
    "market value",
    "market unrealized returns",
}

ACTIVITIES_REQUIRED_COLUMNS = {
    "transaction_date",
    "activity_type",
    "symbol",
    "quantity",
    "unit_price",
    "net_cash_amount",
}

HOLDINGS_FILENAME_HINTS = ("holdings-report", "holdings")
ACTIVITIES_FILENAME_HINTS = ("activities-export", "activities")


@dataclass
class CsvInspection:
    path: str
    exists: bool
    readable: bool
    kind: str
    expected_kind: str | None = None
    filename_kind: str | None = None
    confidence: str = "none"
    columns: list[str] = field(default_factory=list)
    missing_holdings_columns: list[str] = field(default_factory=list)
    missing_activities_columns: list[str] = field(default_factory=list)
    row_count_hint: int = 0
    is_sample: bool = False
    swapped: bool = False
    ok_for_expected: bool = False
    issues: list[str] = field(default_factory=list)
    action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalise_column(column: str | None) -> str:
    return (column or "").strip().strip('"').lower()


def infer_filename_kind(path: str | Path) -> str | None:
    name = Path(path).name.lower()
    if any(hint in name for hint in HOLDINGS_FILENAME_HINTS):
        return "holdings"
    if any(hint in name for hint in ACTIVITIES_FILENAME_HINTS):
        return "activities"
    return None


def is_sample_csv(path: str | Path) -> bool:
    resolved = Path(path)
    parts = {part.lower() for part in resolved.parts}
    return "samples" in parts or "sample" in resolved.name.lower()


def inspect_csv(path: str | Path | None, expected_kind: str | None = None) -> CsvInspection:
    if path is None or not str(path).strip():
        return CsvInspection(
            path="",
            exists=False,
            readable=False,
            kind="missing",
            expected_kind=expected_kind,
            issues=["No CSV path provided."],
            action=_action_for_expected(expected_kind),
        )

    resolved = Path(path).expanduser()
    filename_kind = infer_filename_kind(resolved)
    if not resolved.exists():
        return CsvInspection(
            path=str(resolved),
            exists=False,
            readable=False,
            kind="missing",
            expected_kind=expected_kind,
            filename_kind=filename_kind,
            is_sample=is_sample_csv(resolved),
            issues=["CSV file does not exist."],
            action="Choose an existing CSV file.",
        )

    try:
        columns, row_count_hint = _read_columns(resolved)
    except OSError as exc:
        return CsvInspection(
            path=str(resolved),
            exists=True,
            readable=False,
            kind="unreadable",
            expected_kind=expected_kind,
            filename_kind=filename_kind,
            is_sample=is_sample_csv(resolved),
            issues=[f"Could not read CSV: {exc}"],
            action="Check file permissions or choose a different CSV.",
        )

    normalised = {normalise_column(column) for column in columns}
    missing_holdings = sorted(HOLDINGS_REQUIRED_COLUMNS - normalised)
    missing_activities = sorted(ACTIVITIES_REQUIRED_COLUMNS - normalised)
    holdings_score = len(HOLDINGS_REQUIRED_COLUMNS & normalised)
    activities_score = len(ACTIVITIES_REQUIRED_COLUMNS & normalised)

    kind = "unknown"
    confidence = "none"
    if not missing_holdings:
        kind = "holdings"
        confidence = "high"
    elif not missing_activities:
        kind = "activities"
        confidence = "high"
    elif holdings_score >= 4 and holdings_score > activities_score:
        kind = "holdings_partial"
        confidence = "medium"
    elif activities_score >= 4 and activities_score > holdings_score:
        kind = "activities_partial"
        confidence = "medium"
    elif filename_kind:
        kind = f"{filename_kind}_filename_only"
        confidence = "low"

    issues: list[str] = []
    if kind == "unknown":
        issues.append("CSV schema does not match a Wealthsimple holdings or activities export.")
    if expected_kind == "holdings" and kind.startswith("activities"):
        issues.append("This looks like an activities export selected as the Holdings CSV.")
    if expected_kind == "activities" and kind.startswith("holdings"):
        issues.append("This looks like a holdings report selected as the Activities CSV.")
    if expected_kind == "holdings" and kind.startswith("holdings") and missing_holdings:
        issues.append(f"Holdings CSV is missing required columns: {missing_holdings}.")
    if expected_kind == "activities" and kind.startswith("activities") and missing_activities:
        issues.append(f"Activities CSV is missing required columns: {missing_activities}.")

    sample = is_sample_csv(resolved)
    if sample:
        issues.append("This is a sample/demo CSV, not a real Wealthsimple export.")

    ok_for_expected = bool(
        expected_kind and kind == expected_kind and (not missing_holdings if expected_kind == "holdings" else not missing_activities)
    )
    swapped = bool(
        (expected_kind == "holdings" and kind.startswith("activities")) or (expected_kind == "activities" and kind.startswith("holdings"))
    )

    return CsvInspection(
        path=str(resolved),
        exists=True,
        readable=True,
        kind=kind,
        expected_kind=expected_kind,
        filename_kind=filename_kind,
        confidence=confidence,
        columns=columns,
        missing_holdings_columns=missing_holdings,
        missing_activities_columns=missing_activities,
        row_count_hint=row_count_hint,
        is_sample=sample,
        swapped=swapped,
        ok_for_expected=ok_for_expected,
        issues=issues,
        action=_action_for_issue(expected_kind, kind, sample, swapped),
    )


def validate_csv_pair(
    holdings_csv: str | Path | None,
    activities_csv: str | Path | None,
    *,
    allow_auto_swap: bool = True,
    allow_sample: bool = False,
) -> dict[str, Any]:
    """Validate selected CSV inputs before a report run.

    Returns resolved paths plus warnings. Raises ``ValueError`` for blocking
    input mistakes that would otherwise fail later with a parser traceback.
    """
    holdings = inspect_csv(holdings_csv, expected_kind="holdings") if holdings_csv else None
    activities = inspect_csv(activities_csv, expected_kind="activities") if activities_csv else None
    warnings: list[str] = []

    if allow_auto_swap and holdings and activities and holdings.kind.startswith("activities") and activities.kind.startswith("holdings"):
        warnings.append("Holdings and Activities CSV paths looked swapped; tech_stock corrected them automatically.")
        holdings, activities = inspect_csv(activities_csv, expected_kind="holdings"), inspect_csv(holdings_csv, expected_kind="activities")

    errors: list[str] = []
    for label, inspection in (("Holdings", holdings), ("Activities", activities)):
        if inspection is None:
            continue
        if not inspection.exists:
            errors.append(f"{label} CSV not found: {inspection.path}")
        elif not inspection.readable:
            errors.append(f"{label} CSV is not readable: {inspection.action}")
        elif inspection.swapped:
            errors.append(f"{label} CSV is in the wrong field. {inspection.action}")
        elif inspection.is_sample and not allow_sample:
            errors.append(f"{label} CSV is sample/demo data. {inspection.action}")
        elif inspection.expected_kind and not inspection.kind.startswith(inspection.expected_kind):
            errors.append(f"{label} CSV schema is not recognized. {inspection.action}")
        elif not inspection.ok_for_expected and inspection.expected_kind:
            errors.append(f"{label} CSV is incomplete. {' '.join(inspection.issues) or inspection.action}")

    if errors:
        raise ValueError(" ".join(errors))

    return {
        "holdings_csv": Path(holdings.path) if holdings else None,
        "activities_csv": Path(activities.path) if activities else None,
        "warnings": warnings,
        "holdings": holdings.to_dict() if holdings else None,
        "activities": activities.to_dict() if activities else None,
    }


def _read_columns(path: Path) -> tuple[list[str], int]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = [line for line in handle.read().splitlines() if line.strip() and not line.strip().strip('"').startswith("As of")]
    if not rows:
        return [], 0
    reader = csv.reader(rows)
    try:
        columns = [column.strip().strip('"') for column in next(reader)]
    except StopIteration:
        return [], 0
    row_count = sum(1 for _row in reader)
    return columns, row_count


def _action_for_expected(expected_kind: str | None) -> str:
    if expected_kind == "holdings":
        return "Choose a Wealthsimple holdings-report CSV in the Holdings field."
    if expected_kind == "activities":
        return "Choose a Wealthsimple activities-export CSV in the Activities field, or leave it blank."
    return "Choose a Wealthsimple CSV export."


def _action_for_issue(expected_kind: str | None, kind: str, sample: bool, swapped: bool) -> str:
    if sample:
        return "Use sample CSVs only in demo mode; choose your real Wealthsimple export for a paid run."
    if swapped and expected_kind == "holdings":
        return "Move this file to the Activities field and choose a holdings-report CSV for Holdings."
    if swapped and expected_kind == "activities":
        return "Move this file to the Holdings field and choose an activities-export CSV for Activities."
    if expected_kind == "holdings":
        return "Export a fresh Wealthsimple holdings-report CSV and select it as Holdings."
    if expected_kind == "activities":
        return "Export a fresh Wealthsimple activities-export CSV or leave Activities blank."
    if kind == "unknown":
        return "Export a fresh Wealthsimple CSV and try again."
    return ""
