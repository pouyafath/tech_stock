"""User data-file defaults, workspace visibility, and pre-run checks.

This module keeps file-selection logic out of individual UIs.  The app can run
without saved defaults, but once a user confirms their Wealthsimple exports we
remember those paths in the writable workspace config folder.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.cost_tracker import check_budget
from src.csv_health import inspect_csv
from src.updater import check_for_update


@dataclass
class CheckRow:
    check: str
    status: str
    detail: str
    action: str = ""
    blocking: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PreRunChecklist:
    rows: list[CheckRow] = field(default_factory=list)

    @property
    def blocking_count(self) -> int:
        return sum(1 for row in self.rows if row.blocking)

    @property
    def warning_count(self) -> int:
        return sum(1 for row in self.rows if row.status == "WARN")

    @property
    def can_run(self) -> bool:
        return self.blocking_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "can_run": self.can_run,
            "blocking_count": self.blocking_count,
            "warning_count": self.warning_count,
            "next_action": next((row.action for row in self.rows if row.blocking and row.action), "Ready to run."),
            "rows": [row.to_dict() for row in self.rows],
        }


def data_file_settings_path() -> Path:
    from src import main

    return main.CONFIG_DIR / "data_files.json"


def load_data_file_defaults() -> dict[str, str]:
    path = data_file_settings_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {key: str(value) for key, value in payload.items() if key in {"holdings", "activities"} and value}


def save_data_file_defaults(
    holdings: str | Path | None = None,
    activities: str | Path | None = None,
    *,
    clear_missing: bool = False,
) -> Path:
    """Persist selected CSV paths for future UI sessions."""
    current = {} if clear_missing else load_data_file_defaults()
    for key, value in {"holdings": holdings, "activities": activities}.items():
        text = str(value).strip() if value else ""
        if text:
            current[key] = str(Path(text).expanduser())
        elif clear_missing and key in current:
            current.pop(key, None)
    path = data_file_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    return path


def selected_data_files() -> dict[str, Path | None]:
    """Return saved defaults if present, otherwise auto-detected current exports."""
    from src import main

    defaults = load_data_file_defaults()
    holdings = _existing_path(defaults.get("holdings")) or main.find_csv_by_date("holdings-report")
    activities = _existing_path(defaults.get("activities")) or main.find_csv_by_date("activities-export")
    return {"holdings": holdings, "activities": activities}


def csv_search_dirs() -> list[Path]:
    from src import main

    dirs = [
        main.UPLOAD_DIR,
        Path.home() / "Downloads",
        Path.home() / "Desktop",
        Path.home() / "Documents",
    ]
    return _dedupe_dirs(dirs)


def discover_csv_candidates(kind: str, limit: int = 20) -> list[Path]:
    prefix = "holdings-report" if kind == "holdings" else "activities-export"
    candidates: list[Path] = []
    patterns = [f"{prefix}-*.csv", f"{prefix}*.csv"]
    for directory in csv_search_dirs():
        if not directory.exists():
            continue
        for pattern in patterns:
            candidates.extend(directory.glob(pattern))
    unique = sorted({path.resolve() for path in candidates if path.exists()}, key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    return unique[:limit]


def data_files_view() -> dict[str, Any]:
    """Return paths and statuses for the Data Files / Workspace screen."""
    from src import main

    selected = selected_data_files()
    api_paths = main.api_key_search_paths()
    api_found = next((path for path in api_paths if path.exists()), None)
    locations = main.runtime_locations()

    rows = [
        _csv_resource_row("Holdings CSV", selected.get("holdings"), "holdings", required=True),
        _csv_resource_row("Activities CSV", selected.get("activities"), "activities", required=False),
        {
            "resource": "API keys",
            "status": "OK" if api_found else "WARN",
            "path": str(api_found or (api_paths[0] if api_paths else "")),
            "detail": "API key file found." if api_found else "No API_KEYS.txt or .env file found in search paths.",
            "action": "" if api_found else "Create API_KEYS.txt in the app workspace or use Settings > API Keys.",
            "openable": bool(api_found),
        },
        _folder_row("Reports folder", locations.get("reports")),
        _folder_row("Recommendation logs", locations.get("recommendation_logs")),
        _folder_row("Uploads folder", locations.get("uploads")),
        _folder_row("Workspace", locations.get("workspace")),
    ]
    return {
        "settings_path": data_file_settings_path(),
        "selected": selected,
        "rows": rows,
        "csv_candidates": {
            "holdings": [str(path) for path in discover_csv_candidates("holdings")],
            "activities": [str(path) for path in discover_csv_candidates("activities")],
        },
        "api_key_paths": [{"path": str(path), "exists": path.exists()} for path in api_paths],
        "locations": locations,
    }


def build_pre_run_checklist(
    *,
    holdings_csv: str | Path | None,
    activities_csv: str | Path | None = None,
    use_fallback_config: bool = False,
    dry_run: bool = False,
    allow_sample: bool = False,
    timeout: float = 4.0,
) -> dict[str, Any]:
    """Build a deterministic paid-run checklist shared by all UIs."""
    from src import main

    rows: list[CheckRow] = []
    main._load_api_keys_from_file()

    if dry_run:
        rows.append(CheckRow("Anthropic API key", "SKIP", "Dry run/demo mode does not call Claude."))
    elif os.environ.get("ANTHROPIC_API_KEY"):
        rows.append(CheckRow("Anthropic API key", "OK", "Required Claude key is configured."))
    else:
        rows.append(
            CheckRow(
                "Anthropic API key",
                "BLOCKED",
                "ANTHROPIC_API_KEY is missing.",
                "Add ANTHROPIC_API_KEY in API_KEYS.txt or .env before a paid run.",
                True,
            )
        )

    if use_fallback_config:
        portfolio_path = main.CONFIG_DIR / "portfolio.json"
        rows.append(
            CheckRow(
                "Holdings CSV",
                "WARN",
                f"Using fallback portfolio config: {portfolio_path}",
                "Prefer a fresh Wealthsimple holdings-report CSV for real analysis.",
            )
        )
    else:
        rows.append(_csv_check_row("Holdings CSV", holdings_csv, "holdings", required=True, allow_sample=allow_sample or dry_run))

    rows.append(_csv_check_row("Activities CSV", activities_csv, "activities", required=False, allow_sample=allow_sample or dry_run))

    try:
        budget = check_budget(expected_cost_usd=0.0)
        if dry_run:
            rows.append(CheckRow("Monthly budget", "SKIP", "Dry run/demo mode has no Claude spend."))
        elif budget.hard_block:
            rows.append(CheckRow("Monthly budget", "BLOCKED", budget.message, "Increase budget or set ALLOW_OVERAGE=1.", True))
        elif budget.soft_warn:
            rows.append(CheckRow("Monthly budget", "WARN", budget.message, "Review spend before running."))
        else:
            rows.append(CheckRow("Monthly budget", "OK", budget.message or "Budget check passed."))
    except Exception as exc:  # noqa: BLE001
        rows.append(CheckRow("Monthly budget", "WARN", f"Budget check failed: {exc}", "Review cost settings if this persists."))

    optional_missing = _optional_api_missing_count()
    rows.append(
        CheckRow(
            "Optional data APIs",
            "WARN" if optional_missing else "OK",
            f"{optional_missing} optional API key(s) missing." if optional_missing else "Configured optional APIs look available.",
            "Reports can run, but analyst/news/macro coverage may be reduced." if optional_missing else "",
        )
    )

    try:
        info = check_for_update(timeout=timeout, use_cache=True)
        rows.append(
            CheckRow(
                "App version",
                "WARN" if info.available else "OK",
                f"latest={info.latest_version or 'unknown'} current={info.current_version}",
                f"Update to {info.latest_version} after this run." if info.available else "",
            )
        )
    except Exception as exc:  # noqa: BLE001
        rows.append(CheckRow("App version", "WARN", f"Update check failed: {exc}", "Run Settings > Updates later."))

    checklist = PreRunChecklist(rows)
    return checklist.to_dict()


def format_pre_run_checklist(checklist: dict[str, Any]) -> str:
    lines = ["Pre-run checklist:"]
    for row in checklist.get("rows") or []:
        marker = "BLOCKED" if row.get("blocking") else row.get("status") or ""
        detail = row.get("detail") or ""
        action = row.get("action") or ""
        lines.append(f"- [{marker}] {row.get('check')}: {detail}" + (f" Action: {action}" if action else ""))
    return "\n".join(lines)


def _optional_api_missing_count() -> int:
    from src.preflight import API_FIELDS

    return sum(1 for field in API_FIELDS if not field.get("required") and not os.environ.get(field["env"]))


def _csv_check_row(
    label: str,
    path: str | Path | None,
    expected_kind: str,
    *,
    required: bool,
    allow_sample: bool,
) -> CheckRow:
    inspection = inspect_csv(path, expected_kind=expected_kind)
    if not path:
        if required:
            return CheckRow(label, "BLOCKED", "No file selected.", inspection.action, True)
        return CheckRow(
            label, "WARN", "No activities CSV selected.", "Optional, but recommended for holding-age and trade-history context."
        )
    if not inspection.exists:
        return CheckRow(label, "BLOCKED", f"File not found: {inspection.path}", inspection.action, True)
    if not inspection.readable:
        return CheckRow(label, "BLOCKED", f"File is not readable: {inspection.path}", inspection.action, True)
    if inspection.swapped:
        return CheckRow(label, "BLOCKED", "This file appears to be selected in the wrong field.", inspection.action, True)
    if inspection.is_sample and not allow_sample:
        return CheckRow(label, "BLOCKED", "Sample/demo CSV selected for a paid run.", inspection.action, True)
    if not inspection.ok_for_expected:
        return CheckRow(
            label, "BLOCKED" if required else "WARN", "; ".join(inspection.issues) or inspection.action, inspection.action, required
        )
    age_hours = _age_hours(Path(inspection.path))
    if age_hours is not None and age_hours > 72:
        return CheckRow(label, "WARN", f"{Path(inspection.path).name} is {age_hours:.1f} hours old.", "Export a fresh file before trading.")
    sample_suffix = " (sample/demo)" if inspection.is_sample else ""
    return CheckRow(label, "OK", f"{Path(inspection.path).name} detected as {inspection.kind}{sample_suffix}.")


def _csv_resource_row(label: str, path: Path | None, expected_kind: str, *, required: bool) -> dict[str, Any]:
    inspection = inspect_csv(path, expected_kind=expected_kind)
    if not path:
        status = "FAIL" if required else "WARN"
        detail = "No file selected or discovered."
    elif inspection.swapped or (required and not inspection.ok_for_expected):
        status = "FAIL"
        detail = "; ".join(inspection.issues) or inspection.action
    elif inspection.is_sample and required:
        status = "FAIL"
        detail = "Sample/demo file selected."
    elif not inspection.ok_for_expected:
        status = "WARN"
        detail = "; ".join(inspection.issues) or inspection.action
    else:
        status = "OK"
        detail = f"Detected {inspection.kind} with {inspection.confidence} confidence."
    age = _age_hours(path) if path else None
    if status == "OK" and age is not None and age > 72:
        status = "WARN"
        detail = f"File is {age:.1f} hours old."
    return {
        "resource": label,
        "status": status,
        "path": str(path or ""),
        "detail": detail,
        "action": inspection.action if status in {"FAIL", "WARN"} else "",
        "detected": inspection.kind,
        "age_hours": age,
        "openable": bool(path and path.exists()),
    }


def _folder_row(label: str, path: Path | None) -> dict[str, Any]:
    exists = bool(path and path.exists())
    count = 0
    if exists and path and path.is_dir():
        try:
            count = len(list(path.iterdir()))
        except OSError:
            count = 0
    return {
        "resource": label,
        "status": "OK" if exists else "WARN",
        "path": str(path or ""),
        "detail": f"{count} item(s)" if exists else "Folder does not exist yet.",
        "action": "" if exists else "It will be created automatically when needed.",
        "openable": exists,
    }


def _existing_path(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.exists() else None


def _age_hours(path: Path | None) -> float | None:
    if not path or not path.exists():
        return None
    return round((datetime.now().timestamp() - path.stat().st_mtime) / 3600, 2)


def _dedupe_dirs(paths: list[Path]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        expanded = path.expanduser()
        key = expanded.resolve() if expanded.exists() else expanded
        if key in seen:
            continue
        seen.add(key)
        deduped.append(expanded)
    return deduped
