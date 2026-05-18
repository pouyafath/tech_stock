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
from src.decision_journal import (
    journal_status,
    load_journal,
    record_decision,
    run_scorecard as run_decision_scorecard,
)
from src.main import (
    CONFIG_DIR,
    DATA_DIR,
    RECS_LOG_DIR,
    REPORTS_DIR,
    ROOT,
    UPLOAD_DIR,
    api_key_search_paths,
    find_csv_by_date,
    _load_api_keys_from_file,
    report_search_paths,
    runtime_locations,
    run as run_cli_report,
)
from src.portfolio_loader import parse_holdings_csv
from src.updater import UpdateInfo, UpdateResult, apply_update, check_for_update
from src.version import APP_VERSION

MODEL_OPTIONS = {
    "sonnet": ("claude-sonnet-4-6", "Sonnet 4.6"),
    "opus": ("claude-opus-4-7", "Opus 4.7"),
}

EDITABLE_JSON_FILES = {
    "Settings": CONFIG_DIR / "settings.json",
    "Watchlist": CONFIG_DIR / "watchlist.json",
    "Fallback Portfolio": CONFIG_DIR / "portfolio.json",
}

DECISION_JOURNAL_PATH = DATA_DIR / "decision_journal.json"

API_KEY_FIELDS = [
    {
        "env": "ANTHROPIC_API_KEY",
        "label": "Anthropic",
        "required": True,
        "help": "Required for Claude recommendations.",
    },
    {
        "env": "FINNHUB_API_KEY",
        "label": "Finnhub",
        "required": False,
        "help": "Analyst consensus, upgrades/downgrades, earnings, insider activity, sentiment.",
    },
    {
        "env": "POLYGON_API_KEY",
        "label": "Polygon",
        "required": False,
        "help": "Previous-session OHLCV/VWAP and optional current snapshots.",
    },
    {
        "env": "TWELVE_DATA_API_KEY",
        "label": "Twelve Data",
        "required": False,
        "help": "Real-time quote redundancy and earnings dates.",
    },
    {
        "env": "FRED_API_KEY",
        "label": "FRED",
        "required": False,
        "help": "Macro indicators and USD/CAD FX.",
    },
    {
        "env": "COINGECKO_API_KEY",
        "label": "CoinGecko",
        "required": False,
        "help": "Crypto/risk sentiment. Key is optional for the public endpoint.",
    },
    {
        "env": "ALPHA_VANTAGE_API_KEY",
        "label": "Alpha Vantage",
        "required": False,
        "help": "Optional news sentiment and earnings estimates.",
    },
]


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
            "currency": holding.get("market_value_currency") or holding.get("market_currency"),
            "market_value": holding.get("market_value"),
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


def _ui_report_search_paths() -> list[Path]:
    paths = report_search_paths()
    report_dir = REPORTS_DIR.expanduser()
    report_key = report_dir.resolve() if report_dir.exists() else report_dir
    path_keys = {path.resolve() if path.exists() else path for path in paths}
    if report_key not in path_keys:
        return [report_dir]
    return paths


def list_reports(limit: int = 25) -> list[Path]:
    reports: list[Path] = []
    seen: set[Path] = set()
    for directory in _ui_report_search_paths():
        if not directory.exists():
            continue
        for path in directory.glob("*.md"):
            key = path.resolve()
            if key in seen:
                continue
            seen.add(key)
            reports.append(path)
    reports = sorted(reports, key=lambda p: p.stat().st_mtime, reverse=True)
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
        "session_summary": data.get("session_summary") or "",
        "risk_dashboard": data.get("risk_dashboard") or portfolio_health.get("risk_dashboard") or {},
        "quality_warnings": data.get("quality_warnings") or [],
        "hedge_suggestions": data.get("hedge_suggestions") or [],
        "drift": data.get("drift_vs_previous") or [],
        "priority_actions": data.get("priority_actions") or [],
        "trailing_stop_breaches": data.get("trailing_stop_breaches") or [],
        "watchlist_flags": data.get("watchlist_flags") or [],
        "sector_warnings": data.get("sector_warnings") or [],
        "warnings": data.get("warnings") or [],
        "market_context_snapshot": data.get("market_context_snapshot") or {},
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


def decision_journal_snapshot(limit: int = 200) -> dict[str, Any]:
    journal = load_journal(DECISION_JOURNAL_PATH)
    status = journal_status(journal)
    entries = sorted(
        journal.get("decisions", []) or [],
        key=lambda row: (row.get("session_date") or "", row.get("ticker") or ""),
        reverse=True,
    )[:limit]
    return {
        "path": DECISION_JOURNAL_PATH,
        "status": status,
        "entries": entries,
    }


def decision_scorecard_summary() -> dict[str, Any]:
    return run_decision_scorecard(DECISION_JOURNAL_PATH)


def save_decision_from_ui(
    row_id: str,
    *,
    user_decision: str,
    actual_action: str | None = None,
    actual_shares: float | str | None = None,
    actual_price: float | str | None = None,
    actual_currency: str = "USD",
    decision_date: str | None = None,
    execution_date: str | None = None,
    reason: str = "",
    notes: str = "",
) -> dict[str, Any]:
    return record_decision(
        DECISION_JOURNAL_PATH,
        row_id,
        user_decision=user_decision,
        actual_action=actual_action,
        actual_shares=actual_shares,
        actual_price=actual_price,
        actual_currency=actual_currency,
        decision_date=decision_date,
        execution_date=execution_date,
        reason=reason,
        notes=notes,
    )


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


def _read_env_style_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith("=") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                values[key] = value
    except Exception:
        return values
    return values


def _write_env_style_file(path: Path, updates: dict[str, str | None]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    rendered: list[str] = []
    seen: set[str] = set()
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("=") or "=" not in line:
            rendered.append(raw_line)
            continue
        key, _value = line.split("=", 1)
        key = key.strip()
        if key in updates:
            value = (updates[key] or "").strip()
            if value and key not in seen:
                rendered.append(f"{key}={value}")
            seen.add(key)
            continue
        rendered.append(raw_line)
    for key, value in updates.items():
        value = (value or "").strip()
        if key not in seen and value:
            rendered.append(f"{key}={value}")
    path.write_text("\n".join(rendered).rstrip() + "\n", encoding="utf-8")
    return path


def _preferred_api_key_file() -> Path:
    for path in api_key_search_paths():
        if path.name == "API_KEYS.txt" and path.exists():
            return path
    return Path.home() / "Documents" / "tech_stock" / "API_KEYS.txt"


def mask_secret(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def api_key_inventory() -> list[dict[str, Any]]:
    """Return configured API-key fields with masked values and discovered source files."""
    _load_api_keys_from_file()
    file_values = [(path, _read_env_style_file(path)) for path in api_key_search_paths() if path.exists()]
    rows: list[dict[str, Any]] = []
    for field in API_KEY_FIELDS:
        env_name = field["env"]
        source = None
        value = os.environ.get(env_name) or ""
        for path, values in file_values:
            if env_name in values and values[env_name]:
                source = path
                value = values[env_name]
                break
        rows.append({
            **field,
            "configured": bool(value),
            "masked": mask_secret(value),
            "source_path": source,
        })
    return rows


def save_api_key(env_name: str, value: str) -> Path:
    valid = {field["env"] for field in API_KEY_FIELDS}
    if env_name not in valid:
        raise ValueError(f"Unsupported API key: {env_name}")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("API key value is empty.")
    path = _preferred_api_key_file()
    _write_env_style_file(path, {env_name: cleaned})
    os.environ[env_name] = cleaned
    return path


def delete_api_key(env_name: str) -> list[Path]:
    valid = {field["env"] for field in API_KEY_FIELDS}
    if env_name not in valid:
        raise ValueError(f"Unsupported API key: {env_name}")
    touched: list[Path] = []
    for path in api_key_search_paths():
        if not path.exists():
            continue
        values = _read_env_style_file(path)
        if env_name in values:
            _write_env_style_file(path, {env_name: None})
            touched.append(path)
    os.environ.pop(env_name, None)
    return touched


def check_connectivity(timeout: float = 12.0) -> list[dict[str, Any]]:
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

    def record_missing(source: str, env_name: str, started: float, *, optional: bool = True) -> None:
        suffix = " missing (optional)" if optional else " missing"
        record(source, False, f"{env_name}{suffix}", started)

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
            record_missing("Finnhub", "FINNHUB_API_KEY", started)
        else:
            response = requests.get("https://finnhub.io/api/v1/quote", params={"symbol": "AAPL", "token": key}, timeout=timeout)
            ok = response.ok and bool((response.json() if response.text else {}).get("c"))
            record("Finnhub", ok, f"HTTP {response.status_code}", started)
    except Exception as exc:
        record("Finnhub", False, str(exc), started if "started" in locals() else time.perf_counter())

    try:
        import requests
        started = time.perf_counter()
        key = os.environ.get("POLYGON_API_KEY")
        if not key:
            record_missing("Polygon", "POLYGON_API_KEY", started)
        else:
            response = requests.get("https://api.polygon.io/v2/aggs/ticker/AAPL/prev", params={"apiKey": key}, timeout=timeout)
            payload = response.json() if response.text else {}
            ok = response.ok and bool(payload.get("results"))
            record("Polygon", ok, f"HTTP {response.status_code}", started)
    except Exception as exc:
        record("Polygon", False, str(exc), started if "started" in locals() else time.perf_counter())

    try:
        import requests
        started = time.perf_counter()
        key = os.environ.get("TWELVE_DATA_API_KEY")
        if not key:
            record_missing("Twelve Data", "TWELVE_DATA_API_KEY", started)
        else:
            response = requests.get("https://api.twelvedata.com/quote", params={"symbol": "AAPL", "apikey": key}, timeout=timeout)
            payload = response.json() if response.text else {}
            ok = response.ok and payload.get("status") != "error" and bool(payload.get("close") or payload.get("price"))
            detail = f"HTTP {response.status_code}"
            if isinstance(payload, dict) and payload.get("message"):
                detail = f"{detail}: {payload.get('message')}"
            record("Twelve Data", ok, detail, started)
    except Exception as exc:
        record("Twelve Data", False, str(exc), started if "started" in locals() else time.perf_counter())

    try:
        import requests
        started = time.perf_counter()
        key = os.environ.get("FRED_API_KEY")
        if not key:
            record_missing("FRED", "FRED_API_KEY", started)
        else:
            response = requests.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={"series_id": "DFF", "api_key": key, "file_type": "json", "sort_order": "desc", "limit": 1},
                timeout=timeout,
            )
            payload = response.json() if response.text else {}
            ok = response.ok and bool(payload.get("observations"))
            record("FRED", ok, f"HTTP {response.status_code}", started)
    except Exception as exc:
        record("FRED", False, str(exc), started if "started" in locals() else time.perf_counter())

    try:
        import requests
        started = time.perf_counter()
        key = os.environ.get("COINGECKO_API_KEY")
        headers = {}
        if key:
            header_name = "x-cg-pro-api-key" if not key.startswith("CG-") else "x-cg-demo-api-key"
            headers[header_name] = key
        response = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin", "vs_currencies": "usd"},
            headers=headers,
            timeout=timeout,
        )
        payload = response.json() if response.text else {}
        ok = response.ok and bool((payload.get("bitcoin") or {}).get("usd"))
        detail = f"HTTP {response.status_code}" + ("" if key else " (public endpoint, no key)")
        record("CoinGecko", ok, detail, started)
    except Exception as exc:
        record("CoinGecko", False, str(exc), started if "started" in locals() else time.perf_counter())

    try:
        import requests
        started = time.perf_counter()
        key = os.environ.get("ALPHA_VANTAGE_API_KEY")
        if not key:
            record_missing("Alpha Vantage", "ALPHA_VANTAGE_API_KEY", started)
        else:
            response = requests.get(
                "https://www.alphavantage.co/query",
                params={"function": "GLOBAL_QUOTE", "symbol": "AAPL", "apikey": key},
                timeout=timeout,
            )
            payload = response.json() if response.text else {}
            ok = response.ok and bool(payload.get("Global Quote"))
            detail = f"HTTP {response.status_code}"
            if isinstance(payload, dict) and (payload.get("Note") or payload.get("Information")):
                detail = f"{detail}: {payload.get('Note') or payload.get('Information')}"
            record("Alpha Vantage", ok, detail, started)
    except Exception as exc:
        record("Alpha Vantage", False, str(exc), started if "started" in locals() else time.perf_counter())

    return checks


def api_key_locations() -> list[dict[str, Any]]:
    """Return API key search paths with existence flags for UIs."""
    rows = []
    seen: set[Path] = set()
    for path in api_key_search_paths():
        resolved = path.expanduser()
        key = resolved.resolve() if resolved.exists() else resolved
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "path": resolved,
            "exists": resolved.exists(),
        })
    return rows


def report_locations() -> list[dict[str, Any]]:
    """Return report search folders with existence/count flags for UIs."""
    rows = []
    for path in _ui_report_search_paths():
        exists = path.exists()
        rows.append({
            "path": path,
            "exists": exists,
            "count": len(list(path.glob("*.md"))) if exists else 0,
        })
    return rows


def app_data_locations() -> dict[str, Path]:
    """Return writable app data locations for UIs."""
    return runtime_locations()


def current_app_version() -> str:
    """Return the installed application version."""
    return APP_VERSION


def check_update_available(timeout: float = 6.0) -> UpdateInfo:
    """Return latest GitHub release update status."""
    return check_for_update(timeout=timeout)


def apply_available_update(info: UpdateInfo, *, restart: bool = True) -> UpdateResult:
    """Download/apply the selected update while preserving app data folders."""
    return apply_update(info, restart=restart)


def relative_to_root(path: Path | None) -> str:
    if not path:
        return ""
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path.resolve())
