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
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from src.backtester import run_backtest
from src.main import (
    CONFIG_DIR,
    RECS_LOG_DIR,
    REPORTS_DIR,
    ROOT,
    UPLOAD_DIR,
    find_csv_by_date,
    _load_api_keys_from_file,
    run as run_cli_report,
)
from src.portfolio_loader import parse_holdings_csv

MODEL_OPTIONS = {
    "sonnet": ("claude-sonnet-4-6", "Sonnet 4.6"),
    "opus": ("claude-opus-4-7", "Opus 4.7"),
}

EDITABLE_JSON_FILES = {
    "Settings": CONFIG_DIR / "settings.json",
    "Watchlist": CONFIG_DIR / "watchlist.json",
    "Fallback Portfolio": CONFIG_DIR / "portfolio.json",
}


class TeeProgressIO(io.TextIOBase):
    """Capture CLI output while optionally streaming complete lines to a UI."""

    def __init__(self, capture: io.StringIO, on_progress: Callable[[str], None] | None = None):
        self.capture = capture
        self.on_progress = on_progress
        self._buffer = ""

    def writable(self) -> bool:
        return True

    def write(self, value: str) -> int:
        if not value:
            return 0
        self.capture.write(value)
        if self.on_progress:
            self._buffer += value
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                self._emit(line)
        return len(value)

    def flush(self) -> None:
        if self.on_progress and self._buffer.strip():
            self._emit(self._buffer)
            self._buffer = ""

    def _emit(self, line: str) -> None:
        cleaned = line.rstrip()
        if cleaned:
            self.on_progress(cleaned)


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


def discover_csv_files(pattern_prefix: str, limit: int = 20) -> list[Path]:
    candidates: list[Path] = []
    patterns = [f"{pattern_prefix}-*.csv", f"{pattern_prefix}*.csv"]
    search_dirs = [UPLOAD_DIR, Path.home() / "Downloads"]
    for directory in search_dirs:
        if not directory.exists():
            continue
        for pattern in patterns:
            candidates.extend(directory.glob(pattern))
    unique = sorted({p.resolve() for p in candidates if p.exists()}, key=lambda p: p.stat().st_mtime, reverse=True)
    return unique[:limit]


def preview_holdings_csv(path: str | Path | None, limit: int = 25) -> dict[str, Any]:
    resolved = normalize_optional_path(path)
    if not resolved or not resolved.exists():
        return {"ok": False, "error": "Holdings CSV not found."}
    try:
        portfolio = parse_holdings_csv(resolved)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    rows = []
    for holding in portfolio.get("holdings", [])[:limit]:
        rows.append({
            "ticker": holding.get("ticker"),
            "quantity": holding.get("quantity"),
            "market_price": holding.get("market_price"),
            "market_currency": holding.get("market_currency"),
            "value_usd": holding.get("market_value_usd"),
            "unrealized_pnl_pct": holding.get("unrealized_pnl_pct"),
        })
    return {
        "ok": True,
        "exported_at": portfolio.get("exported_at", ""),
        "position_count": len(portfolio.get("holdings", [])),
        "rows": rows,
    }


def run_report_from_ui(
    *,
    session_type: str,
    holdings_csv: str | Path | None = None,
    activities_csv: str | Path | None = None,
    budget_usd: float | None = None,
    budget_cad: float | None = None,
    model_choice: str | None = "sonnet",
    on_progress: Callable[[str], None] | None = None,
) -> UiRunResult:
    model_id, model_name = resolve_model(model_choice)
    console = io.StringIO()
    stream = TeeProgressIO(console, on_progress)
    try:
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
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
            stream.flush()
    except SystemExit as exc:
        stream.flush()
        return UiRunResult(
            ok=False,
            console=console.getvalue(),
            error=f"Program exited with code {exc.code}",
        )
    except Exception as exc:
        stream.flush()
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


def list_logs(limit: int = 25) -> list[Path]:
    if not RECS_LOG_DIR.exists():
        return []
    logs = sorted(RECS_LOG_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[:limit]


def latest_log_summary() -> dict[str, Any]:
    logs = list_logs(limit=1)
    if not logs:
        return {}
    path = logs[0]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"session_file": path.name, "error": str(exc)}

    portfolio_health = data.get("portfolio_health") or {}
    return {
        "session_file": path.name,
        "session_path": path,
        "risk_dashboard": data.get("risk_dashboard") or portfolio_health.get("risk_dashboard") or {},
        "quality_warnings": data.get("quality_warnings") or [],
        "hedge_suggestions": data.get("hedge_suggestions") or [],
        "drift": data.get("drift_vs_previous") or [],
        "priority_actions": data.get("priority_actions") or [],
        "usage": data.get("usage") or data.get("usage_summary") or {},
        "recommendations": data.get("recommendations") or [],
        "portfolio_health": portfolio_health,
    }


def read_text_file(path: str | Path | None) -> str:
    resolved = normalize_optional_path(path)
    if not resolved or not resolved.exists():
        return ""
    return resolved.read_text(encoding="utf-8")


def run_backtest_summary() -> dict[str, Any]:
    return run_backtest(RECS_LOG_DIR)


def validate_json_text(content: str) -> tuple[bool, str]:
    if not content.strip():
        return False, "JSON is empty."
    try:
        json.loads(content)
    except json.JSONDecodeError as exc:
        return False, f"Invalid JSON: line {exc.lineno}, column {exc.colno}: {exc.msg}"
    return True, "Valid JSON."


def read_editable_json(label: str) -> str:
    path = EDITABLE_JSON_FILES[label]
    return path.read_text(encoding="utf-8")


def write_editable_json(label: str, content: str) -> Path:
    path = EDITABLE_JSON_FILES[label]
    parsed = json.loads(content)
    path.write_text(json.dumps(parsed, indent=2) + "\n", encoding="utf-8")
    return path


def check_connectivity(timeout: float = 5.0) -> list[dict[str, Any]]:
    """Best-effort API/data-source health checks for the optional UIs."""
    _load_api_keys_from_file()
    checks: list[dict[str, Any]] = []

    def record(source: str, ok: bool, detail: str, started: float) -> None:
        checks.append({
            "source": source,
            "ok": ok,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "detail": detail,
        })

    try:
        import requests
        started = time.perf_counter()
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            record("Anthropic", False, "ANTHROPIC_API_KEY missing", started)
        else:
            response = requests.get(
                "https://api.anthropic.com/v1/models",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                timeout=timeout,
            )
            record("Anthropic", response.ok, f"HTTP {response.status_code}", started)
    except Exception as exc:
        record("Anthropic", False, str(exc), started if "started" in locals() else time.perf_counter())

    try:
        import yfinance as yf
        started = time.perf_counter()
        hist = yf.Ticker("SPY").history(period="1d")
        record("yfinance", not hist.empty, "SPY 1d history returned" if not hist.empty else "empty history", started)
    except Exception as exc:
        record("yfinance", False, str(exc), started if "started" in locals() else time.perf_counter())

    try:
        import requests
        started = time.perf_counter()
        key = os.environ.get("FINNHUB_API_KEY")
        if not key:
            record("Finnhub", False, "FINNHUB_API_KEY missing", started)
        else:
            response = requests.get("https://finnhub.io/api/v1/quote", params={"symbol": "AAPL", "token": key}, timeout=timeout)
            record("Finnhub", response.ok, f"HTTP {response.status_code}", started)
    except Exception as exc:
        record("Finnhub", False, str(exc), started if "started" in locals() else time.perf_counter())

    try:
        import requests
        started = time.perf_counter()
        key = os.environ.get("POLYGON_API_KEY")
        if not key:
            record("Polygon", False, "POLYGON_API_KEY missing", started)
        else:
            response = requests.get("https://api.polygon.io/v2/aggs/ticker/AAPL/prev", params={"apiKey": key}, timeout=timeout)
            record("Polygon", response.ok, f"HTTP {response.status_code}", started)
    except Exception as exc:
        record("Polygon", False, str(exc), started if "started" in locals() else time.perf_counter())

    return checks


def relative_to_root(path: Path | None) -> str:
    if not path:
        return ""
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path.resolve())
