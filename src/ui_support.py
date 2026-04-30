"""
Shared helpers for optional Streamlit and Textual interfaces.

The CLI remains the canonical execution path. UI entrypoints call the same
src.main.run() function and only handle input collection, output capture, and
report discovery.
"""

from __future__ import annotations

import contextlib
import io
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.backtester import run_backtest
from src.main import (
    CONFIG_DIR,
    RECS_LOG_DIR,
    REPORTS_DIR,
    ROOT,
    UPLOAD_DIR,
    find_csv_by_date,
    run as run_cli_report,
)

MODEL_OPTIONS = {
    "sonnet": ("claude-sonnet-4-6", "Sonnet 4.6"),
    "opus": ("claude-opus-4-7", "Opus 4.7"),
}

EDITABLE_JSON_FILES = {
    "Settings": CONFIG_DIR / "settings.json",
    "Watchlist": CONFIG_DIR / "watchlist.json",
    "Fallback Portfolio": CONFIG_DIR / "portfolio.json",
}


@dataclass
class UiRunResult:
    ok: bool
    console: str
    report_path: Path | None = None
    csv_path: Path | None = None
    log_path: Path | None = None
    error: str | None = None


def resolve_model(model_choice: str | None) -> tuple[str | None, str | None]:
    if not model_choice:
        return None, None
    return MODEL_OPTIONS.get(model_choice.lower(), (None, None))


def normalize_optional_path(path_value: str | Path | None) -> Path | None:
    if path_value is None:
        return None
    path_text = str(path_value).strip()
    if not path_text:
        return None
    return Path(path_text).expanduser()


def find_default_csvs() -> dict[str, Path | None]:
    return {
        "holdings": find_csv_by_date("holdings-report"),
        "activities": find_csv_by_date("activities-export"),
    }


def default_run_settings() -> dict[str, Any]:
    try:
        settings = json.loads((CONFIG_DIR / "settings.json").read_text(encoding="utf-8"))
    except Exception:
        settings = {}
    model = settings.get("claude_model", "")
    model_choice = "opus" if "opus" in model else "sonnet"
    return {
        "budget_usd": float(settings.get("budget_usd", 0) or 0),
        "budget_cad": float(settings.get("budget_cad", 0) or 0),
        "model_choice": model_choice,
    }


def save_uploaded_bytes(name: str, data: bytes) -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = Path(name).name
    if not safe_name.lower().endswith(".csv"):
        safe_name = f"{safe_name}.csv"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = UPLOAD_DIR / f"ui_{timestamp}_{safe_name}"
    dest.write_bytes(data)
    return dest


def run_report_from_ui(
    *,
    session_type: str,
    holdings_csv: str | Path | None = None,
    activities_csv: str | Path | None = None,
    budget_usd: float | None = None,
    budget_cad: float | None = None,
    model_choice: str | None = "sonnet",
) -> UiRunResult:
    model_id, model_name = resolve_model(model_choice)
    console = io.StringIO()
    try:
        with contextlib.redirect_stdout(console), contextlib.redirect_stderr(console):
            artifacts = run_cli_report(
                session_type=session_type,
                holdings_csv=normalize_optional_path(holdings_csv),
                activities_csv=normalize_optional_path(activities_csv),
                budget_usd=budget_usd,
                budget_cad=budget_cad,
                model_id=model_id,
                model_name=model_name,
                open_report=False,
            )
    except SystemExit as exc:
        return UiRunResult(
            ok=False,
            console=console.getvalue(),
            error=f"Program exited with code {exc.code}",
        )
    except Exception as exc:
        return UiRunResult(ok=False, console=console.getvalue(), error=str(exc))

    artifacts = artifacts or {}
    return UiRunResult(
        ok=True,
        console=console.getvalue(),
        report_path=artifacts.get("report_path"),
        csv_path=artifacts.get("csv_path"),
        log_path=artifacts.get("log_path"),
    )


def list_reports(limit: int = 25) -> list[Path]:
    if not REPORTS_DIR.exists():
        return []
    reports = sorted(REPORTS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return reports[:limit]


def latest_report() -> Path | None:
    reports = list_reports(limit=1)
    return reports[0] if reports else None


def read_text_file(path: str | Path | None) -> str:
    resolved = normalize_optional_path(path)
    if not resolved or not resolved.exists():
        return ""
    return resolved.read_text(encoding="utf-8")


def run_backtest_summary() -> dict[str, Any]:
    return run_backtest(RECS_LOG_DIR)


def read_editable_json(label: str) -> str:
    path = EDITABLE_JSON_FILES[label]
    return path.read_text(encoding="utf-8")


def write_editable_json(label: str, content: str) -> Path:
    path = EDITABLE_JSON_FILES[label]
    parsed = json.loads(content)
    path.write_text(json.dumps(parsed, indent=2) + "\n", encoding="utf-8")
    return path


def relative_to_root(path: Path | None) -> str:
    if not path:
        return ""
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path.resolve())
