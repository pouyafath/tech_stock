"""
Shared helpers for optional Streamlit and Textual interfaces.

UI entrypoints call the same ``ReportPipeline`` boundary and only handle input
collection, output capture, and report discovery.
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
from src.enriched_data import enrich
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
)
from src.market_data import get_market_data
from src.news_fetcher import aggregate_sentiment, get_news_for_tickers
from src.portfolio_loader import parse_holdings_csv
from src.preflight import build_preflight, run_demo_smoke_test
from src.report_pipeline import ReportPipeline
from src.updater import UpdateInfo, UpdateResult, apply_update, check_for_update
from src.version import APP_VERSION
from src.view_models import (
    build_api_health_view,
    build_buy_signals_view,
    build_dashboard_view,
    build_decision_journal_view,
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

DECISION_JOURNAL_PATH = DATA_DIR / "decision_journal.json"
THESIS_LOG_PATH = DATA_DIR / "thesis_log.json"
RECS_LOG_DIR = DATA_DIR / "recommendations_log"

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
        rows.append(
            {
                "ticker": holding.get("ticker"),
                "quantity": holding.get("quantity"),
                "market_price": holding.get("market_price"),
                "currency": holding.get("market_value_currency") or holding.get("market_currency"),
                "market_value": holding.get("market_value"),
                "unrealized_pnl_pct": holding.get("unrealized_pnl_pct"),
            }
        )
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
            artifacts = ReportPipeline().run(
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

    return UiRunResult(
        ok=True,
        console=console.getvalue(),
        report_path=artifacts.report_path,
        csv_path=artifacts.csv_path,
        log_path=artifacts.log_path,
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
    reports = sorted(reports, key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
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
        "source_degradation": data.get("source_degradation") or data.get("degradation") or [],
        "data_confidence": data.get("data_confidence") or {},
    }


def dashboard_view() -> dict[str, Any]:
    return build_dashboard_view(latest_log_summary())


BUY_SIGNAL_ACTIONS = {"BUY", "ADD"}
BUY_SIGNAL_HOLD_TIERS = {"add_on_dip"}


def is_buy_signal_candidate(recommendation: dict[str, Any]) -> bool:
    action = (recommendation.get("action") or "").upper()
    hold_tier = (recommendation.get("hold_tier") or "").lower()
    return action in BUY_SIGNAL_ACTIONS or hold_tier in BUY_SIGNAL_HOLD_TIERS


def target_upside_pct(target: float | int | None, current_price: float | int | None) -> float | None:
    try:
        if target is None or current_price is None or float(current_price) <= 0:
            return None
        return round((float(target) - float(current_price)) / float(current_price) * 100, 1)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _load_latest_log_payload() -> tuple[Path | None, dict[str, Any]]:
    logs = list_logs(limit=1)
    if not logs:
        return None, {}
    path = logs[0]
    try:
        return path, json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return path, {"error": str(exc)}


def _sort_buy_signal_recommendations(recommendations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(rec: dict[str, Any]) -> tuple[int, float, str]:
        action = (rec.get("action") or "").upper()
        action_rank = 0 if action in {"BUY", "ADD"} else 1
        try:
            conviction = float(rec.get("conviction") or 0)
        except (TypeError, ValueError):
            conviction = 0
        return (action_rank, -conviction, rec.get("ticker") or "")

    return sorted([rec for rec in recommendations if is_buy_signal_candidate(rec)], key=sort_key)


def buy_signal_insights(limit: int = 8) -> dict[str, Any]:
    """
    Build a data-backed buy-signal view from the latest recommendation log plus
    refreshed source data. No LLM is called here; the insight rows are
    deterministic summaries of source fields.
    """
    path, payload = _load_latest_log_payload()
    if not path:
        return {"session_file": "", "candidates": [], "error": "No recommendation JSON logs found."}
    if payload.get("error"):
        return {"session_file": path.name, "candidates": [], "error": payload["error"]}

    recs = _sort_buy_signal_recommendations(payload.get("recommendations") or [])[:limit]
    tickers = [rec.get("ticker") for rec in recs if rec.get("ticker")]
    market_data = get_market_data(tickers) if tickers else {}
    enriched = enrich(tickers) if tickers else {}
    news_by_ticker = get_news_for_tickers(tickers) if tickers else {}
    quality_by_ticker: dict[str, list[dict[str, Any]]] = {}
    for warning in payload.get("quality_warnings") or []:
        ticker = warning.get("ticker")
        if ticker:
            quality_by_ticker.setdefault(ticker, []).append(warning)

    candidates = []
    for rec in recs:
        ticker = rec.get("ticker")
        md = market_data.get(ticker) or {}
        per_ticker = ((enriched.get("per_ticker") or {}).get(ticker) or {}) if ticker else {}
        analyst = per_ticker.get("analyst_consensus") or {}
        price = md.get("current_price") or rec.get("target_entry_or_exit")
        price_targets = {
            "low": md.get("analyst_target_low"),
            "mean": md.get("analyst_target_mean"),
            "median": md.get("analyst_target_median"),
            "high": md.get("analyst_target_high"),
            "analyst_count": md.get("number_of_analyst_opinions") or analyst.get("total_analysts"),
            "source": md.get("analyst_target_source") if md.get("analyst_target_mean") else "",
        }
        price_targets["mean_upside_pct"] = target_upside_pct(price_targets["mean"], price)
        price_targets["high_upside_pct"] = target_upside_pct(price_targets["high"], price)
        price_targets["low_upside_pct"] = target_upside_pct(price_targets["low"], price)
        indicators = md.get("indicators") or {}
        news = news_by_ticker.get(ticker) or []
        source_notes = [
            f"Quote: {md.get('quote_source') or 'unavailable'}",
            "Analyst consensus: Finnhub /stock/recommendation" if analyst else "Analyst consensus: unavailable",
            "Analyst targets: Yahoo Finance via yfinance" if price_targets.get("mean") else "Analyst targets: unavailable",
            "Recent news: Yahoo Finance via yfinance",
            "Quality gates: deterministic report_quality checks",
        ]
        if per_ticker.get("insider_activity"):
            source_notes.append("Insider activity: Finnhub insider transactions")
        if per_ticker.get("upcoming_earnings"):
            source_notes.append("Earnings calendar: Finnhub")

        candidates.append(
            {
                "ticker": ticker,
                "action": rec.get("action"),
                "hold_tier": rec.get("hold_tier"),
                "conviction": rec.get("conviction"),
                "action_amount": rec.get("action_amount") or rec.get("invest_amount_usd"),
                "action_amount_currency": rec.get("action_amount_currency") or "USD",
                "current_price": price,
                "currency": md.get("currency") or "USD",
                "change_pct_1d": md.get("change_pct_1d"),
                "quote_source": md.get("quote_source"),
                "quote_timestamp_utc": md.get("quote_timestamp_utc"),
                "price_basis": md.get("price_basis"),
                "market_data_error": md.get("error"),
                "analyst_consensus": analyst,
                "price_targets": price_targets,
                "latest_rating_changes": (per_ticker.get("upgrade_downgrade") or [])[:4],
                "insider_activity": per_ticker.get("insider_activity") or {},
                "upcoming_earnings": per_ticker.get("upcoming_earnings") or {},
                "earnings_history": (per_ticker.get("earnings_history") or [])[:4],
                "technical": {
                    "rsi_14": indicators.get("rsi_14"),
                    "macd_hist": indicators.get("macd_hist"),
                    "atr_pct_of_price": indicators.get("atr_pct_of_price"),
                    "price_vs_sma50_pct": indicators.get("price_vs_sma50_pct"),
                    "price_vs_sma200_pct": indicators.get("price_vs_sma200_pct"),
                    "volatility_20d_pct": indicators.get("volatility_20d_pct"),
                    "volume_spike_ratio": indicators.get("volume_spike_ratio"),
                },
                "catalyst_verified": rec.get("catalyst_verified"),
                "catalyst_source": rec.get("catalyst_source"),
                "manual_review_required": rec.get("manual_review_required"),
                "quality_warnings": quality_by_ticker.get(ticker, []),
                "news": news[:3],
                "news_summary": aggregate_sentiment(news),
                "thesis": rec.get("thesis") or "",
                "risk_or_invalidation": rec.get("risk_or_invalidation") or "",
                "source_notes": source_notes,
            }
        )

    return {
        "session_file": path.name,
        "session_path": path,
        "session_summary": payload.get("session_summary") or "",
        "candidates": candidates,
        "sources_active": enriched.get("sources_active") or [],
        "degradation": enriched.get("degradation") or [],
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }


def buy_signal_view(
    limit: int = 8,
    *,
    action_filter: str = "all",
    readiness_filter: str = "all",
) -> dict[str, Any]:
    return build_buy_signals_view(
        buy_signal_insights(limit=limit),
        action_filter=action_filter,
        readiness_filter=readiness_filter,
    )


def demo_smoke_view() -> dict[str, Any]:
    """Run the no-spend demo smoke test for UI buttons."""
    return run_demo_smoke_test()


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


def decision_journal_view(limit: int = 200) -> dict[str, Any]:
    return build_decision_journal_view(decision_journal_snapshot(limit=limit))


def decision_scorecard_summary() -> dict[str, Any]:
    return run_decision_scorecard(DECISION_JOURNAL_PATH)


def diagnostics_view(*, hours: int = 24) -> dict[str, Any]:
    """Compact Diagnostics-tab payload.

    Thin wrapper over ``src.observability.source_summary`` plus a small
    health verdict per source.  Returns:
      {
        "window_hours": 24,
        "sources": {"finnhub": {total, errors, success_rate, last_error,
                                codes, health: "ok"|"degraded"|"down"}, ...},
        "recent_errors": [...],
        "total_events": int,
        "log_path": str,
        "rotated_path": str | None,
      }

    ``health`` is derived from ``success_rate``:
      * ≥ 0.95 → "ok"
      * 0.50–0.94 → "degraded"
      * < 0.50 → "down"
      * None (no traffic) → "idle"
    """
    from src.observability import source_summary

    summary = source_summary(hours=hours)
    for source, bucket in summary.get("sources", {}).items():
        rate = bucket.get("success_rate")
        if rate is None:
            bucket["health"] = "idle"
        elif rate >= 0.95:
            bucket["health"] = "ok"
        elif rate >= 0.50:
            bucket["health"] = "degraded"
        else:
            bucket["health"] = "down"
    try:
        summary["preflight"] = build_preflight(force_update=False, live_api_checks=False, include_demo_smoke=False, timeout=4.0)
    except Exception as exc:  # noqa: BLE001
        summary["preflight"] = {
            "summary_rows": [
                {
                    "check": "Preflight",
                    "status": "FAIL",
                    "detail": str(exc),
                }
            ]
        }
    return summary


def diagnostics_support_bundle(*, limit: int = 500) -> str:
    """Return a redacted JSON-lines tail suitable for copy-paste bug reports."""
    from src.observability import support_bundle

    return support_bundle(limit=limit)


def degradation_health(source: str, *, minutes: int = 60) -> str | None:
    """Return ``"degraded"`` if ``source`` had errors in the last N minutes.

    Used by inline pills in the Buy Signals / Dashboard tabs so the user
    sees *which* data source is misbehaving without opening Diagnostics.
    Returns ``None`` when the source is healthy or has no recent traffic.
    """
    from src.observability import source_summary

    hours = max(1, minutes // 60) if minutes >= 60 else 1
    snapshot = source_summary(hours=hours)
    bucket = snapshot.get("sources", {}).get(source)
    if not bucket:
        return None
    rate = bucket.get("success_rate")
    if rate is None:
        return None
    if rate < 0.5:
        return "down"
    if rate < 0.95:
        return "degraded"
    return None


def learning_view() -> dict[str, Any]:
    """Aggregated 'Learning' tab data used by every UI.

    Returns a stable shape:
      {
        "thesis_verdicts":     list of {ticker, entry_date, original_action,
                                       original_conviction, current_verdict,
                                       days_held, verdict_history (list[str])},
        "edge_by_horizon":     {1: {n, user_avg, model_avg, delta, user_hit,
                                    model_hit}, 5: {...}, 20: {...}, 60: {...}},
        "sharpe_by_conviction": {conv: {n, avg_return_pct, hit_rate, sharpe,
                                        max_drawdown_pct, sizing_multiplier}},
        "calibration":         {conv: {n, stated_pct, realized_pct, error_pp,
                                       overconfident}},  # v1.18
        "walk_forward":        [{window_start, window_end, n, hit_rate,
                                 avg_return_pct, sharpe, ...}],  # v1.18
        "thesis_text_drift_alerts": list of {ticker, similarity, was_thesis,
                                             now_thesis},
        "errors": list of soft error strings (never raises),
      }

    Lazy and read-only — never triggers a Claude run or yfinance fetch.
    Suitable to call on UI startup.
    """
    from src.drift_tracker import compute_drift, get_previous_session

    out: dict[str, Any] = {
        "thesis_verdicts": [],
        "edge_by_horizon": {},
        "sharpe_by_conviction": {},
        "calibration": {},  # v1.18
        "walk_forward": [],  # v1.18
        "thesis_text_drift_alerts": [],
        "errors": [],
    }

    # ── Thesis verdicts (from thesis_log.json) ────────────────────────────
    try:
        from datetime import date

        thesis_state = json.loads(THESIS_LOG_PATH.read_text(encoding="utf-8")) if THESIS_LOG_PATH.exists() else {}
        today = date.today()
        verdicts: list[dict[str, Any]] = []
        for key, entry in thesis_state.items():
            review_log = entry.get("review_log") or []
            history = [r.get("verdict") for r in review_log if r.get("verdict")]
            latest_verdict = history[-1] if history else None
            try:
                entry_date = entry.get("entry_date")
                days_held = (today - date.fromisoformat(entry_date)).days if entry_date else None
            except (TypeError, ValueError):
                days_held = None
            verdicts.append(
                {
                    "key": key,
                    "ticker": entry.get("ticker"),
                    "entry_date": entry.get("entry_date"),
                    "original_action": entry.get("original_action"),
                    "original_conviction": entry.get("original_conviction"),
                    "current_verdict": latest_verdict,
                    "verdict_history": history[-6:],  # last six dots
                    "days_held": days_held,
                    "reviews_count": len(history),
                }
            )
        # Order: most-recent-review-first, then oldest unreviewed positions.
        verdicts.sort(key=lambda v: (v.get("current_verdict") is None, -(v.get("reviews_count") or 0), -(v.get("days_held") or 0)))
        out["thesis_verdicts"] = verdicts
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"thesis_verdicts: {exc}")

    # ── Edge by horizon + per-conviction risk (from cached scorecard / backtest) ─
    try:
        scorecard = run_decision_scorecard(DECISION_JOURNAL_PATH) or {}
        out["edge_by_horizon"] = scorecard.get("by_horizon") or {}
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"edge_by_horizon: {exc}")

    try:
        from src.backtester import run_backtest

        recs_dir = ROOT / "data" / "recommendations_log"
        if recs_dir.exists() and any(recs_dir.glob("*.json")):
            backtest = run_backtest(recs_dir)
            by_conv = backtest.get("avg_return_by_conviction") or {}
            mults = backtest.get("sizing_multipliers_by_conviction") or {}
            enriched: dict[int, dict] = {}
            for conv, stats in by_conv.items():
                enriched[int(conv)] = {
                    "n": stats.get("n", 0),
                    "avg_return_pct": stats.get("avg_return_pct", 0.0),
                    "hit_rate": stats.get("hit_rate", 0.0),
                    "sharpe": stats.get("sharpe", 0.0),
                    "max_drawdown_pct": stats.get("max_drawdown_pct", 0.0),
                    "stdev_pct": stats.get("stdev_pct", 0.0),
                    "sizing_multiplier": mults.get(int(conv), 1.0),
                }
            out["sharpe_by_conviction"] = enriched
            # v1.18: surface reliability + walk-forward so the Learning tab
            # can show calibration scatter + stability bands.
            out["calibration"] = backtest.get("reliability") or {}
            out["walk_forward"] = backtest.get("walk_forward") or []
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"sharpe_by_conviction: {exc}")

    # ── Thesis-text drift alerts ──────────────────────────────────────────
    try:
        recs_dir = ROOT / "data" / "recommendations_log"
        latest_logs = list_logs(limit=1)
        if latest_logs:
            current = json.loads(latest_logs[0].read_text(encoding="utf-8"))
            current_session_file = latest_logs[0].name
            previous = get_previous_session(
                recs_dir,
                skip_newest=False,
                current_session_type=None,
                min_age_hours=0.0,
            )
            # If `get_previous_session` returned the same file we just loaded,
            # pull the one before it instead.  Drift against itself is empty
            # anyway, but skipping is cheaper.
            if previous and previous.get("source_filename") == current_session_file:
                previous = None
            if previous:
                drift_events = compute_drift(current, previous)
                alerts = []
                for event in drift_events:
                    if event.get("drift_type") != "thesis_text_drift":
                        continue
                    alerts.append(
                        {
                            "ticker": event.get("ticker"),
                            "similarity": event.get("similarity"),
                            "was_thesis": (event.get("was") or {}).get("thesis"),
                            "now_thesis": (event.get("now") or {}).get("thesis"),
                        }
                    )
                out["thesis_text_drift_alerts"] = alerts
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"thesis_text_drift_alerts: {exc}")

    return out


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
        rows.append(
            {
                **field,
                "configured": bool(value),
                "masked": mask_secret(value),
                "source_path": source,
            }
        )
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
        checks.append(
            {
                "source": source,
                "ok": ok,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "detail": detail,
            }
        )

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


def api_health_view(timeout: float = 12.0) -> dict[str, Any]:
    return build_api_health_view(check_connectivity(timeout=timeout), api_key_inventory())


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
        rows.append(
            {
                "path": resolved,
                "exists": resolved.exists(),
            }
        )
    return rows


def report_locations() -> list[dict[str, Any]]:
    """Return report search folders with existence/count flags for UIs."""
    rows = []
    for path in _ui_report_search_paths():
        exists = path.exists()
        rows.append(
            {
                "path": path,
                "exists": exists,
                "count": len(list(path.glob("*.md"))) if exists else 0,
            }
        )
    return rows


def app_data_locations() -> dict[str, Path]:
    """Return writable app data locations for UIs."""
    return runtime_locations()


def current_app_version() -> str:
    """Return the installed application version."""
    return APP_VERSION


def check_update_available(timeout: float = 6.0, *, force: bool = False) -> UpdateInfo:
    """Return the latest GitHub release update status.

    UI surfaces (Streamlit dashboard, Textual app, desktop tab) call this on
    every refresh. By default we serve the result from the local 6-hour disk
    cache so background reloads do not hammer the GitHub API. The user-facing
    "Check now" button should pass ``force=True`` to bypass the cache.
    """
    return check_for_update(timeout=timeout, use_cache=not force)


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
