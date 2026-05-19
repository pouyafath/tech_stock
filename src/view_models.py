"""Shared UI view models for dashboard, signals, API health, and journals."""

from __future__ import annotations

from typing import Any

TRADE_READY = "TRADE_READY"
REVIEW_FIRST = "REVIEW_FIRST"
BLOCKED = "BLOCKED"

BLOCKING_WARNING_CODES = {
    "market_data_error",
    "stale_or_unstamped_quote",
    "missing_catalyst_verification",
    "buy_add_over_position_cap",
    "oversized_company_exposure",
}

BLOCKING_PRICE_BASIS = {"daily_history_close"}


def classify_trade_readiness(candidate: dict[str, Any]) -> dict[str, Any]:
    """Classify whether a signal is execution-ready from deterministic fields."""
    reasons: list[str] = []
    warnings = candidate.get("quality_warnings") or []
    warning_codes = {str(row.get("code") or "") for row in warnings}
    high_warnings = [row for row in warnings if str(row.get("severity") or "").lower() == "high"]

    if candidate.get("market_data_error"):
        reasons.append(f"Market data error: {candidate.get('market_data_error')}")
    if candidate.get("price_basis") in BLOCKING_PRICE_BASIS or not candidate.get("quote_timestamp_utc"):
        reasons.append("Quote is stale, close-only, or missing a provider timestamp.")
    for code in sorted(warning_codes & BLOCKING_WARNING_CODES):
        reasons.append(f"Blocking quality warning: {code}")
    for warning in high_warnings:
        code = warning.get("code")
        if code not in BLOCKING_WARNING_CODES:
            reasons.append(f"High-severity quality warning: {code}")

    if reasons:
        return {
            "status": BLOCKED,
            "label": "Blocked",
            "rank": 2,
            "reasons": reasons,
        }

    review_reasons: list[str] = []
    if candidate.get("manual_review_required"):
        review_reasons.append("Manual review required by the recommendation.")
    if warnings:
        review_reasons.append("Quality warnings are present.")
    if not (candidate.get("analyst_consensus") or {}).get("total_analysts"):
        review_reasons.append("Analyst consensus source is unavailable.")
    if not (candidate.get("price_targets") or {}).get("mean"):
        review_reasons.append("Analyst target source is unavailable.")
    if "unavailable" in " ".join(candidate.get("source_notes") or []).lower():
        review_reasons.append("One or more optional source notes are unavailable.")

    if review_reasons:
        return {
            "status": REVIEW_FIRST,
            "label": "Review First",
            "rank": 1,
            "reasons": review_reasons,
        }

    return {
        "status": TRADE_READY,
        "label": "Trade Ready",
        "rank": 0,
        "reasons": ["Fresh quote, required catalysts, and deterministic gates are clear."],
    }


def _candidate_action_group(candidate: dict[str, Any]) -> str:
    action = str(candidate.get("action") or "").upper()
    hold_tier = str(candidate.get("hold_tier") or "").lower()
    if action in {"BUY", "ADD"}:
        return "BUY_ADD"
    if hold_tier == "add_on_dip":
        return "ADD_ON_DIP"
    return "OTHER"


def _matches_filter(candidate: dict[str, Any], action_filter: str, readiness_filter: str) -> bool:
    action_group = candidate.get("action_group") or _candidate_action_group(candidate)
    readiness = (candidate.get("readiness") or {}).get("status")
    action_filter = (action_filter or "all").lower()
    readiness_filter = (readiness_filter or "all").upper()

    if action_filter == "buy_add" and action_group != "BUY_ADD":
        return False
    if action_filter == "add_on_dip" and action_group != "ADD_ON_DIP":
        return False
    if readiness_filter != "ALL" and readiness != readiness_filter:
        return False
    return True


def build_buy_signals_view(
    raw: dict[str, Any],
    *,
    action_filter: str = "all",
    readiness_filter: str = "all",
) -> dict[str, Any]:
    """Return a UI-ready buy-signal payload with readiness badges and filters."""
    if raw.get("error"):
        return {**raw, "cards": [], "overview_rows": [], "consensus_rows": [], "counts": {}}

    cards: list[dict[str, Any]] = []
    for candidate in raw.get("candidates") or []:
        enriched = dict(candidate)
        enriched["action_group"] = _candidate_action_group(enriched)
        enriched["readiness"] = classify_trade_readiness(enriched)
        cards.append(enriched)

    cards.sort(
        key=lambda item: ((item.get("readiness") or {}).get("rank", 9), -(float(item.get("conviction") or 0)), item.get("ticker") or "")
    )
    filtered = [item for item in cards if _matches_filter(item, action_filter, readiness_filter)]

    counts = {
        "total": len(cards),
        TRADE_READY: sum(1 for item in cards if (item.get("readiness") or {}).get("status") == TRADE_READY),
        REVIEW_FIRST: sum(1 for item in cards if (item.get("readiness") or {}).get("status") == REVIEW_FIRST),
        BLOCKED: sum(1 for item in cards if (item.get("readiness") or {}).get("status") == BLOCKED),
        "BUY_ADD": sum(1 for item in cards if item.get("action_group") == "BUY_ADD"),
        "ADD_ON_DIP": sum(1 for item in cards if item.get("action_group") == "ADD_ON_DIP"),
    }

    overview_rows = []
    consensus_rows = []
    for item in filtered:
        targets = item.get("price_targets") or {}
        analyst = item.get("analyst_consensus") or {}
        readiness = item.get("readiness") or {}
        warnings = item.get("quality_warnings") or []
        overview_rows.append(
            {
                "readiness": readiness.get("label"),
                "ticker": item.get("ticker"),
                "action": item.get("action") or item.get("hold_tier"),
                "conviction": item.get("conviction"),
                "amount": item.get("action_amount"),
                "price": item.get("current_price"),
                "quote_time": item.get("quote_timestamp_utc") or "missing",
                "quote_source": item.get("quote_source") or "unavailable",
                "consensus": analyst.get("consensus_label") or "N/A",
                "mean_upside_pct": targets.get("mean_upside_pct"),
                "catalyst": item.get("catalyst_source") or "N/A",
                "warnings": ", ".join(row.get("code", "") for row in warnings) or "none",
            }
        )
        consensus_rows.append(
            {
                "ticker": item.get("ticker"),
                "readiness": readiness.get("label"),
                "buy": analyst.get("buy", "N/A"),
                "hold": analyst.get("hold", "N/A"),
                "sell": analyst.get("sell", "N/A"),
                "analysts": targets.get("analyst_count") or analyst.get("total_analysts") or "N/A",
                "low": targets.get("low"),
                "mean": targets.get("mean"),
                "high": targets.get("high"),
                "mean_upside_pct": targets.get("mean_upside_pct"),
                "source": targets.get("source") or "N/A",
            }
        )

    return {
        **raw,
        "candidates": filtered,
        "all_candidates": cards,
        "cards": filtered,
        "overview_rows": overview_rows,
        "consensus_rows": consensus_rows,
        "counts": counts,
        "active_filters": {
            "action": action_filter,
            "readiness": readiness_filter,
        },
    }


def build_dashboard_view(summary: dict[str, Any]) -> dict[str, Any]:
    """Normalize the latest log summary into dashboard-friendly sections."""
    risk = summary.get("risk_dashboard") or {}
    health = summary.get("portfolio_health") or {}
    usage = summary.get("usage") or {}
    warnings = summary.get("quality_warnings") or []
    return {
        "session_file": summary.get("session_file"),
        "session_summary": summary.get("session_summary") or "",
        "metric_cards": [
            {"label": "Portfolio", "value": health.get("total_value_usd_equivalent")},
            {"label": "P&L", "value": health.get("overall_pnl_pct"), "kind": "pct"},
            {"label": "SPY Beta", "value": (risk.get("beta") or {}).get("SPY")},
            {"label": "Annual Vol", "value": risk.get("annualized_volatility_pct"), "kind": "pct"},
            {"label": "Top-3 Conc.", "value": risk.get("top3_concentration_pct"), "kind": "pct"},
            {"label": "Warnings", "value": len(warnings)},
            {"label": "Claude Cost", "value": usage.get("cost_usd"), "kind": "money"},
        ],
        "priority_actions": summary.get("priority_actions") or [],
        "quality_warnings": warnings,
        "hedge_suggestions": summary.get("hedge_suggestions") or [],
        "drift": summary.get("drift") or [],
        "market_context_snapshot": summary.get("market_context_snapshot") or {},
    }


def build_api_health_view(checks: list[dict[str, Any]], inventory: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    ok_count = sum(1 for row in checks if row.get("ok"))
    required_missing = [row for row in checks if not row.get("ok") and "ANTHROPIC_API_KEY missing" in str(row.get("detail") or "")]
    return {
        "checks": checks,
        "inventory": inventory or [],
        "ok_count": ok_count,
        "fail_count": len(checks) - ok_count,
        "required_missing": bool(required_missing),
        "storage_mode": "API_KEYS.txt / .env files",
    }


def build_decision_journal_view(snapshot: dict[str, Any]) -> dict[str, Any]:
    entries = snapshot.get("entries") or []
    status = snapshot.get("status") or {}
    return {
        "status": status,
        "entries": entries,
        "pending_count": status.get("pending", 0),
        "recorded_count": status.get("recorded", 0),
        "path": snapshot.get("path"),
    }
