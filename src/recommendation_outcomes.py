"""Deterministic recommendation outcome tracking.

This module scores every actionable recommendation in saved JSON logs over
fixed windows.  It is intentionally read-only: historical logs are not mutated,
and price data comes through the existing cached ``market_data.price_at`` path.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src._utils import parse_session_filename, safe_float
from src.market_data import price_at

ACTIONABLE_ACTIONS = {"BUY", "ADD", "SELL", "TRIM"}
DEFAULT_HORIZONS = (1, 5, 20)
DEFAULT_BENCHMARKS = ("SPY", "QQQ")
SEMICONDUCTOR_TICKERS = {"AMD", "AVGO", "INTC", "MU", "NVDA", "QCOM", "SMH", "SOXL", "TSM"}
LEVERAGED_QQQ_TICKERS = {"TQQQ", "SQQQ", "QLD", "QID"}
BLOCKING_WARNING_CODES = {
    "market_data_error",
    "stale_or_unstamped_quote",
    "missing_catalyst_verification",
    "buy_add_over_position_cap",
    "oversized_company_exposure",
}

_FILENAME_RE = re.compile(r"^(\d{8})_(\d{4})_(morning|afternoon)\.json$")


def stable_recommendation_id(session_file: str, ticker: str, action: str, ordinal: int = 1) -> str:
    """Return a stable, user-readable recommendation id.

    Example: ``20260616_morning_NVDA_ADD_001``.
    """
    match = _FILENAME_RE.match(Path(session_file).name)
    if match:
        date_part, _time_part, session_type = match.groups()
        prefix = f"{date_part}_{session_type}"
    else:
        prefix = Path(session_file).stem.replace(" ", "_")
    clean_ticker = re.sub(r"[^A-Z0-9._-]+", "", (ticker or "UNKNOWN").upper()) or "UNKNOWN"
    clean_action = re.sub(r"[^A-Z0-9._-]+", "", (action or "HOLD").upper()) or "HOLD"
    return f"{prefix}_{clean_ticker}_{clean_action}_{int(ordinal):03d}"


def load_recommendation_events(log_dir: str | Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    """Load actionable recommendations from JSON logs ordered oldest to newest."""
    root = Path(log_dir)
    if not root.exists():
        return []
    paths = sorted(root.glob("*.json"), key=lambda path: path.name)
    if limit is not None and limit > 0:
        paths = paths[-int(limit) :]

    events: list[dict[str, Any]] = []
    for path in paths:
        parsed = parse_session_filename(path.name)
        if not parsed:
            continue
        session_date, session_type = parsed
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        recs = payload.get("recommendations") or []
        per_key_count: dict[tuple[str, str], int] = defaultdict(int)
        for index, rec in enumerate(recs, start=1):
            if not isinstance(rec, dict):
                continue
            ticker = (rec.get("ticker") or "").upper()
            action = (rec.get("action") or "HOLD").upper()
            if not ticker or ticker == "CASH" or action not in ACTIONABLE_ACTIONS:
                continue
            key = (ticker, action)
            per_key_count[key] += 1
            rec_id = rec.get("recommendation_id") or stable_recommendation_id(path.name, ticker, action, per_key_count[key])
            event = {
                "id": rec_id,
                "session_file": path.name,
                "session_path": str(path),
                "session_date": session_date,
                "session_type": session_type,
                "ticker": ticker,
                "action": action,
                "conviction": _to_int(rec.get("conviction")),
                "time_horizon": rec.get("time_horizon") or "",
                "expected_pct": safe_float(rec.get("net_expected_pct")) or safe_float(rec.get("expected_move_pct")),
                "report_price": _first_price(
                    rec.get("current_price"),
                    rec.get("target_entry_or_exit"),
                    rec.get("market_price"),
                    rec.get("last_price"),
                ),
                "risk_controls": rec.get("risk_controls") or {},
                "catalyst_verified": bool(rec.get("catalyst_verified")),
                "catalyst_source": rec.get("catalyst_source") or "",
                "manual_review_required": bool(rec.get("manual_review_required")),
                "trade_readiness": _trade_readiness(rec, payload, ticker),
                "market_regime": _market_regime(payload),
                "source_coverage_status": _source_coverage_status(payload),
                "source_required_missing_count": _source_required_missing_count(payload),
                "source_bucket": _source_bucket(rec, payload),
                "quality_warning_count": _quality_warning_count(payload, ticker),
                "log_index": index,
                "usage_cost_usd": safe_float((payload.get("usage_summary") or payload.get("usage") or {}).get("cost_usd")),
            }
            events.append(event)
    return events


def evaluate_outcomes(
    log_dir: str | Path,
    *,
    as_of: datetime | None = None,
    horizons: tuple[int, ...] | list[int] = DEFAULT_HORIZONS,
    max_logs: int | None = 250,
    price_lookup: Callable[[str, str], float | None] = price_at,
) -> dict[str, Any]:
    """Evaluate fixed-window outcomes for actionable recommendations."""
    as_of = as_of or datetime.now()
    events = load_recommendation_events(log_dir, limit=max_logs)
    rows: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for event in events:
        try:
            start_dt = datetime.strptime(event["session_date"], "%Y-%m-%d")
        except (KeyError, ValueError):
            continue
        ticker = event.get("ticker")
        if not ticker:
            continue
        start_price = price_lookup(ticker, start_dt.strftime("%Y-%m-%d"))
        if not start_price or start_price <= 0:
            errors.append({"id": event.get("id"), "ticker": ticker, "error": "missing_start_price"})
            continue

        for horizon in sorted({int(h) for h in horizons if int(h) > 0}):
            end_dt = start_dt + timedelta(days=horizon)
            if end_dt > as_of:
                pending.append({**event, "horizon_days": horizon, "reason": "not_mature"})
                continue
            end_price = price_lookup(ticker, end_dt.strftime("%Y-%m-%d"))
            if not end_price or end_price <= 0:
                errors.append({"id": event.get("id"), "ticker": ticker, "horizon_days": horizon, "error": "missing_end_price"})
                continue

            stock_move = (end_price - start_price) / start_price * 100.0
            action_return = _action_return_pct(event.get("action"), stock_move)
            benchmark_symbol = benchmark_for_ticker(ticker)
            benchmark_move = _benchmark_return(benchmark_symbol, start_dt, end_dt, price_lookup)
            alpha = _alpha_vs_benchmark(event.get("action"), stock_move, benchmark_move)
            stop_hit, take_hit = _risk_control_hits(event.get("risk_controls") or {}, stock_move)

            rows.append(
                {
                    **event,
                    "horizon_days": horizon,
                    "start_date": start_dt.strftime("%Y-%m-%d"),
                    "end_date": end_dt.strftime("%Y-%m-%d"),
                    "start_price": round(float(start_price), 4),
                    "end_price": round(float(end_price), 4),
                    "stock_move_pct": round(stock_move, 2),
                    "action_return_pct": round(action_return, 2),
                    "benchmark": benchmark_symbol,
                    "benchmark_move_pct": round(benchmark_move, 2) if benchmark_move is not None else None,
                    "alpha_vs_benchmark_pct": round(alpha, 2) if alpha is not None else None,
                    "hit": action_return > 0,
                    "beat_benchmark": alpha is not None and alpha > 0,
                    "stop_loss_triggered": stop_hit,
                    "take_profit_triggered": take_hit,
                    "trigger_basis": "close_to_close",
                }
            )

    return {
        "events": events,
        "rows": rows,
        "pending": pending,
        "errors": errors,
        "summary": summarize_outcomes(rows, pending=pending, events=events, errors=errors),
    }


def summarize_outcomes(
    rows: list[dict[str, Any]],
    *,
    pending: list[dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
    errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build aggregate outcome statistics for dashboards and prompts."""
    pending = pending or []
    events = events or []
    errors = errors or []
    unique_logs = {event.get("session_file") for event in events if event.get("session_file")}
    unique_costs: dict[str, float] = {}
    for event in events:
        session = event.get("session_file")
        cost = safe_float(event.get("usage_cost_usd"))
        if session and cost is not None:
            unique_costs[session] = cost
    total_cost = round(sum(unique_costs.values()), 4)
    useful_rows = [row for row in rows if row.get("hit") or row.get("beat_benchmark")]

    buy_add = [row for row in rows if row.get("action") in {"BUY", "ADD"}]
    trim_sell = [row for row in rows if row.get("action") in {"TRIM", "SELL"}]
    saved_drawdown_rows = [
        row for row in trim_sell if safe_float(row.get("stock_move_pct")) is not None and float(row["stock_move_pct"]) < 0
    ]

    summary = {
        "scored_windows": len(rows),
        "scored_recommendations": len({row.get("id") for row in rows}),
        "total_recommendations": len(events),
        "pending_windows": len(pending),
        "error_count": len(errors),
        "log_count": len(unique_logs),
        "estimated_claude_cost_usd": total_cost,
        "cost_per_useful_window_usd": round(total_cost / len(useful_rows), 4) if useful_rows and total_cost else None,
        "overall": _bucket_stats(rows),
        "buy_add_success_rate": _hit_rate(buy_add),
        "trim_sell_saved_drawdown_avg_pct": _avg(
            [_action_return_pct(row.get("action"), row.get("stock_move_pct")) for row in saved_drawdown_rows]
        ),
        "trim_sell_saved_drawdown_count": len(saved_drawdown_rows),
        "by_action": _bucket_by(rows, "action"),
        "by_horizon": _bucket_by(rows, "horizon_days"),
        "by_ticker": _top_bucket_by(rows, "ticker", limit=12),
        "by_source_bucket": _bucket_by(rows, "source_bucket"),
        "by_trade_readiness": _bucket_by(rows, "trade_readiness"),
        "by_catalyst_verified": _bucket_by(rows, "catalyst_verified"),
        "by_manual_review_required": _bucket_by(rows, "manual_review_required"),
        "by_market_regime": _bucket_by(rows, "market_regime"),
        "by_source_coverage_status": _bucket_by(rows, "source_coverage_status"),
        "best_recommendations": sorted(rows, key=lambda row: safe_float(row.get("action_return_pct")) or 0.0, reverse=True)[:8],
        "worst_recommendations": sorted(rows, key=lambda row: safe_float(row.get("action_return_pct")) or 0.0)[:8],
        "best_alpha": sorted(
            [row for row in rows if row.get("alpha_vs_benchmark_pct") is not None],
            key=lambda row: safe_float(row.get("alpha_vs_benchmark_pct")) or 0.0,
            reverse=True,
        )[:8],
        "stop_loss_hits": sum(1 for row in rows if row.get("stop_loss_triggered")),
        "take_profit_hits": sum(1 for row in rows if row.get("take_profit_triggered")),
    }
    summary["lessons"] = build_outcome_lessons(summary)
    summary["prompt_summary"] = prompt_summary(summary)
    return summary


def build_outcomes_view(
    log_dir: str | Path,
    *,
    as_of: datetime | None = None,
    horizons: tuple[int, ...] | list[int] = DEFAULT_HORIZONS,
    max_logs: int | None = 250,
    price_lookup: Callable[[str, str], float | None] = price_at,
) -> dict[str, Any]:
    """Return a stable UI payload for recommendation outcome dashboards."""
    result = evaluate_outcomes(
        log_dir,
        as_of=as_of,
        horizons=horizons,
        max_logs=max_logs,
        price_lookup=price_lookup,
    )
    summary = result["summary"]
    return {
        "status": "READY" if summary.get("scored_windows") else "PENDING",
        "summary": summary,
        "rows": result["rows"],
        "pending": result["pending"],
        "errors": result["errors"],
        "metric_cards": [
            {"label": "Scored windows", "value": summary.get("scored_windows")},
            {"label": "Hit rate", "value": summary.get("overall", {}).get("hit_rate"), "kind": "pct_ratio"},
            {"label": "Avg action return", "value": summary.get("overall", {}).get("avg_action_return_pct"), "kind": "pct"},
            {"label": "Avg alpha", "value": summary.get("overall", {}).get("avg_alpha_vs_benchmark_pct"), "kind": "pct"},
            {"label": "BUY/ADD success", "value": summary.get("buy_add_success_rate"), "kind": "pct_ratio"},
            {"label": "Saved drawdown", "value": summary.get("trim_sell_saved_drawdown_avg_pct"), "kind": "pct"},
            {"label": "Claude cost", "value": summary.get("estimated_claude_cost_usd"), "kind": "money"},
            {"label": "Cost/useful", "value": summary.get("cost_per_useful_window_usd"), "kind": "money"},
        ],
        "recent_rows": sorted(result["rows"], key=lambda row: (row.get("session_date") or "", row.get("ticker") or ""), reverse=True)[:50],
        "lessons": summary.get("lessons") or [],
        "prompt_summary": summary.get("prompt_summary"),
    }


def build_outcome_lessons(summary: dict[str, Any], *, min_n: int = 2) -> list[dict[str, Any]]:
    """Return deterministic lessons from mature outcome buckets."""
    lessons: list[dict[str, Any]] = []
    lessons.extend(_bucket_lessons("Readiness", summary.get("by_trade_readiness") or {}, min_n=min_n))
    lessons.extend(_bucket_lessons("Source coverage", summary.get("by_source_coverage_status") or {}, min_n=min_n))
    lessons.extend(_bucket_lessons("Catalyst verified", summary.get("by_catalyst_verified") or {}, min_n=min_n))
    lessons.extend(_bucket_lessons("Action", summary.get("by_action") or {}, min_n=min_n))
    lessons.extend(_bucket_lessons("Market regime", summary.get("by_market_regime") or {}, min_n=min_n))
    return sorted(lessons, key=lambda row: (-abs(safe_float(row.get("edge_pct")) or 0.0), str(row.get("dimension"))))[:8]


def _bucket_lessons(label: str, buckets: dict[Any, dict[str, Any]], *, min_n: int) -> list[dict[str, Any]]:
    eligible = [(key, stats) for key, stats in buckets.items() if int(stats.get("n") or 0) >= min_n]
    if not eligible:
        return []
    lessons = []
    best_key, best_stats = max(eligible, key=lambda item: safe_float(item[1].get("avg_action_return_pct")) or 0.0)
    worst_key, worst_stats = min(eligible, key=lambda item: safe_float(item[1].get("avg_action_return_pct")) or 0.0)
    best_return = safe_float(best_stats.get("avg_action_return_pct")) or 0.0
    worst_return = safe_float(worst_stats.get("avg_action_return_pct")) or 0.0
    if best_return > 0:
        lessons.append(
            _lesson(
                label,
                best_key,
                "positive",
                best_stats,
                best_return,
                f"{label} bucket '{best_key}' has produced positive average action return.",
            )
        )
    if worst_return < 0:
        lessons.append(
            _lesson(
                label,
                worst_key,
                "negative",
                worst_stats,
                worst_return,
                f"{label} bucket '{worst_key}' has produced negative average action return.",
            )
        )
    return lessons


def _lesson(
    dimension: str,
    bucket: Any,
    direction: str,
    stats: dict[str, Any],
    edge_pct: float,
    message: str,
) -> dict[str, Any]:
    return {
        "dimension": dimension,
        "bucket": str(bucket),
        "direction": direction,
        "n": int(stats.get("n") or 0),
        "hit_rate": stats.get("hit_rate"),
        "avg_action_return_pct": stats.get("avg_action_return_pct"),
        "avg_alpha_vs_benchmark_pct": stats.get("avg_alpha_vs_benchmark_pct"),
        "edge_pct": round(float(edge_pct), 2),
        "message": message,
    }


def prompt_summary(summary: dict[str, Any]) -> str:
    """Compact sentence for Claude prompt calibration."""
    if not summary or not summary.get("scored_windows"):
        return "No matured fixed-window recommendation outcomes yet."
    overall = summary.get("overall") or {}
    parts = [
        f"{summary.get('scored_windows')} fixed-window outcomes",
        f"hit {overall.get('hit_rate', 0):.0%}",
        f"avg action {overall.get('avg_action_return_pct', 0):+.2f}%",
    ]
    alpha = overall.get("avg_alpha_vs_benchmark_pct")
    if alpha is not None:
        parts.append(f"avg alpha {alpha:+.2f}%")
    if summary.get("buy_add_success_rate") is not None:
        parts.append(f"BUY/ADD hit {summary['buy_add_success_rate']:.0%}")
    if summary.get("trim_sell_saved_drawdown_count"):
        parts.append(
            f"TRIM/SELL saved drawdown {summary.get('trim_sell_saved_drawdown_avg_pct', 0):+.2f}% "
            f"on {summary.get('trim_sell_saved_drawdown_count')} windows"
        )
    readiness = summary.get("by_trade_readiness") or {}
    if readiness:
        ready = readiness.get("TRADE_READY", {}).get("hit_rate")
        review = readiness.get("REVIEW_FIRST", {}).get("hit_rate")
        blocked = readiness.get("BLOCKED", {}).get("hit_rate")
        if ready is not None:
            parts.append(f"trade-ready hit {ready:.0%}")
        if review is not None:
            parts.append(f"review-first hit {review:.0%}")
        if blocked is not None:
            parts.append(f"blocked hit {blocked:.0%}")
    catalyst = summary.get("by_catalyst_verified") or {}
    if True in catalyst and catalyst[True].get("n"):
        parts.append(f"verified-catalyst hit {catalyst[True].get('hit_rate', 0):.0%}")
    source_coverage = summary.get("by_source_coverage_status") or {}
    for status in ("OK", "PARTIAL", "REVIEW_FIRST", "BLOCKED"):
        bucket = source_coverage.get(status)
        if bucket and bucket.get("n"):
            parts.append(f"source-{status.lower()} hit {bucket.get('hit_rate', 0):.0%}")
    return "; ".join(parts) + "."


def benchmark_for_ticker(ticker: str) -> str:
    symbol = (ticker or "").upper()
    if symbol in SEMICONDUCTOR_TICKERS:
        return "SMH"
    if symbol in LEVERAGED_QQQ_TICKERS:
        return "QQQ"
    return "QQQ" if symbol not in {"SPY", "VOO", "VFV.TO"} else "SPY"


def _benchmark_return(symbol: str, start_dt: datetime, end_dt: datetime, price_lookup: Callable[[str, str], float | None]) -> float | None:
    start = price_lookup(symbol, start_dt.strftime("%Y-%m-%d"))
    end = price_lookup(symbol, end_dt.strftime("%Y-%m-%d"))
    if not start or not end or start <= 0:
        return None
    return (end - start) / start * 100.0


def _alpha_vs_benchmark(action: str | None, stock_move_pct: float, benchmark_move_pct: float | None) -> float | None:
    if benchmark_move_pct is None:
        return None
    action = (action or "").upper()
    if action in {"SELL", "TRIM"}:
        return benchmark_move_pct - stock_move_pct
    return stock_move_pct - benchmark_move_pct


def _action_return_pct(action: str | None, stock_move_pct: float | None) -> float:
    move = safe_float(stock_move_pct) or 0.0
    if (action or "").upper() in {"SELL", "TRIM"}:
        return -move
    return move


def _risk_control_hits(risk_controls: dict[str, Any], stock_move_pct: float) -> tuple[bool, bool]:
    stop = safe_float(risk_controls.get("stop_loss_pct"))
    take = safe_float(risk_controls.get("take_profit_pct"))
    stop_hit = bool(stop is not None and stock_move_pct <= stop)
    take_hit = bool(take is not None and stock_move_pct >= take)
    return stop_hit, take_hit


def _bucket_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "n": 0,
            "avg_action_return_pct": 0.0,
            "avg_alpha_vs_benchmark_pct": None,
            "hit_rate": 0.0,
            "benchmark_win_rate": 0.0,
        }
    action_returns = [safe_float(row.get("action_return_pct")) or 0.0 for row in rows]
    alphas = [safe_float(row.get("alpha_vs_benchmark_pct")) for row in rows if safe_float(row.get("alpha_vs_benchmark_pct")) is not None]
    return {
        "n": len(rows),
        "avg_action_return_pct": _avg(action_returns),
        "avg_alpha_vs_benchmark_pct": _avg(alphas) if alphas else None,
        "hit_rate": _hit_rate(rows),
        "benchmark_win_rate": round(sum(1 for row in rows if row.get("beat_benchmark")) / len(rows), 3),
    }


def _bucket_by(rows: list[dict[str, Any]], key: str) -> dict[Any, dict[str, Any]]:
    out: dict[Any, dict[str, Any]] = {}
    for value in sorted({row.get(key) for row in rows if row.get(key) is not None}, key=lambda item: str(item)):
        out[value] = _bucket_stats([row for row in rows if row.get(key) == value])
    return out


def _top_bucket_by(rows: list[dict[str, Any]], key: str, *, limit: int) -> dict[Any, dict[str, Any]]:
    buckets = _bucket_by(rows, key)
    return dict(sorted(buckets.items(), key=lambda item: (-item[1].get("n", 0), str(item[0])))[:limit])


def _hit_rate(rows: list[dict[str, Any]]) -> float | None:
    if not rows:
        return None
    return round(sum(1 for row in rows if row.get("hit")) / len(rows), 3)


def _avg(values: list[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    return round(sum(clean) / len(clean), 2) if clean else None


def _to_int(value: Any) -> int | None:
    parsed = safe_float(value)
    return int(parsed) if parsed is not None else None


def _first_price(*values: Any) -> float | None:
    for value in values:
        parsed = safe_float(value)
        if parsed is not None and parsed > 0:
            return parsed
    return None


def _quality_warning_count(payload: dict[str, Any], ticker: str) -> int:
    warnings = payload.get("quality_warnings") or []
    return sum(1 for row in warnings if (row.get("ticker") or "").upper() == ticker)


def _quality_warnings_for_ticker(payload: dict[str, Any], ticker: str) -> list[dict[str, Any]]:
    warnings = payload.get("quality_warnings") or []
    return [row for row in warnings if (row.get("ticker") or "").upper() == ticker]


def _trade_readiness(rec: dict[str, Any], payload: dict[str, Any], ticker: str) -> str:
    explicit = str(rec.get("trade_readiness") or rec.get("readiness") or "").upper()
    if explicit in {"TRADE_READY", "REVIEW_FIRST", "BLOCKED"}:
        return explicit
    warnings = _quality_warnings_for_ticker(payload, ticker)
    warning_codes = {row.get("code") for row in warnings}
    if warning_codes & BLOCKING_WARNING_CODES:
        return "BLOCKED"
    if rec.get("manual_review_required"):
        return "REVIEW_FIRST"
    if warnings:
        return "REVIEW_FIRST"
    confidence_status = str((payload.get("data_confidence") or {}).get("status") or "").upper()
    if confidence_status == "BLOCKED":
        return "BLOCKED"
    if confidence_status == "REVIEW_FIRST":
        return "REVIEW_FIRST"
    return "TRADE_READY"


def _market_regime(payload: dict[str, Any]) -> str:
    macro = payload.get("macro_regime") or {}
    if isinstance(macro, dict):
        for key in ("regime", "label", "risk_regime", "summary"):
            value = macro.get(key)
            if value:
                return _clean_bucket(value)
    context = payload.get("market_context_snapshot") or {}
    if isinstance(context, dict):
        for key in ("regime", "risk_regime", "market_regime"):
            value = context.get(key)
            if value:
                return _clean_bucket(value)
        vix = safe_float(context.get("vix") or context.get("VIX") or context.get("vix_close"))
        if vix is not None:
            if vix >= 25:
                return "high_volatility"
            if vix >= 18:
                return "elevated_volatility"
            return "calm_volatility"
    drawdown = payload.get("drawdown_state") or {}
    if isinstance(drawdown, dict) and drawdown.get("risk_regime"):
        return _clean_bucket(drawdown.get("risk_regime"))
    return "unknown"


def _source_coverage_status(payload: dict[str, Any]) -> str:
    status = str((payload.get("source_coverage") or {}).get("status") or "").upper()
    return status or "UNKNOWN"


def _source_required_missing_count(payload: dict[str, Any]) -> int:
    value = safe_float((payload.get("source_coverage") or {}).get("required_missing_count"))
    return int(value or 0)


def _source_bucket(rec: dict[str, Any], payload: dict[str, Any]) -> str:
    if rec.get("manual_review_required"):
        return "manual_review"
    if rec.get("catalyst_verified"):
        return "verified_catalyst"
    if _quality_warning_count(payload, (rec.get("ticker") or "").upper()):
        return "quality_warning"
    return "thesis_only"


def _clean_bucket(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "unknown"
