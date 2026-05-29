"""Shared data-confidence summaries for reports and UIs."""

from __future__ import annotations

from typing import Any

BLOCKING_CONFIDENCE_CODES = {
    "market_data_error",
    "stale_or_unstamped_quote",
    "missing_catalyst_verification",
    "buy_add_over_position_cap",
    "oversized_company_exposure",
}


def _severity_counts(warnings: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"high": 0, "medium": 0, "low": 0}
    for warning in warnings:
        severity = str(warning.get("severity") or "").lower()
        if severity in counts:
            counts[severity] += 1
    return counts


def build_data_confidence(
    *,
    recommendations: list[dict[str, Any]] | None = None,
    market_data: dict[str, dict[str, Any]] | None = None,
    quality_warnings: list[dict[str, Any]] | None = None,
    enriched: dict[str, Any] | None = None,
    readiness_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Return a compact trust summary from deterministic pipeline fields."""
    recommendations = recommendations or []
    market_data = market_data or {}
    quality_warnings = quality_warnings or []
    enriched = enriched or {}
    degradation = enriched.get("degradation") or []
    sources_active = enriched.get("sources_active") or []
    severity_counts = _severity_counts(quality_warnings)

    quote_total = len(market_data)
    quote_errors = sum(1 for row in market_data.values() if row.get("error"))
    timestamped_quotes = sum(1 for row in market_data.values() if row.get("quote_timestamp_utc"))
    fallback_quotes = sum(1 for row in market_data.values() if row.get("price_basis") == "daily_history_close")
    unstamped_quotes = max(0, quote_total - timestamped_quotes - quote_errors)
    stale_warning_count = sum(1 for warning in quality_warnings if warning.get("code") == "stale_or_unstamped_quote")
    blocking_warning_count = sum(1 for warning in quality_warnings if warning.get("code") in BLOCKING_CONFIDENCE_CODES)

    catalyst_relevant = [
        rec
        for rec in recommendations
        if str(rec.get("action") or "").upper() in {"BUY", "ADD", "TRIM", "SELL"}
        and (rec.get("catalyst_verified") is not None or rec.get("catalyst_source") or rec.get("manual_review_required") is not None)
    ]
    catalyst_verified = sum(1 for rec in catalyst_relevant if rec.get("catalyst_verified"))
    manual_review_required = sum(1 for rec in recommendations if rec.get("manual_review_required"))

    blockers: list[str] = []
    caution: list[str] = []
    if quote_errors:
        blockers.append(f"{quote_errors} quote error(s)")
    if stale_warning_count:
        blockers.append(f"{stale_warning_count} stale quote warning(s)")
    if blocking_warning_count:
        blockers.append(f"{blocking_warning_count} blocking quality warning(s)")
    if readiness_counts and readiness_counts.get("BLOCKED", 0):
        blockers.append(f"{readiness_counts.get('BLOCKED', 0)} blocked buy signal(s)")
    if fallback_quotes:
        caution.append(f"{fallback_quotes} fallback close quote(s)")
    if unstamped_quotes:
        caution.append(f"{unstamped_quotes} unstamped quote(s)")
    if degradation:
        caution.append(f"{len(degradation)} source degradation record(s)")
    if manual_review_required:
        caution.append(f"{manual_review_required} manual-review recommendation(s)")
    if severity_counts["medium"] or severity_counts["low"]:
        caution.append(f"{severity_counts['medium'] + severity_counts['low']} non-blocking warning(s)")

    if blockers:
        label = "LOW"
        status = "blocked"
        summary = "Trade execution needs manual verification before acting."
    elif caution:
        label = "MEDIUM"
        status = "review_first"
        summary = "Usable for research, but review source gaps before placing orders."
    else:
        label = "HIGH"
        status = "trade_ready"
        summary = "No deterministic data-confidence blockers detected."

    quote_freshness = "fresh_timestamped" if quote_total and timestamped_quotes == quote_total else "mixed_or_missing"
    if quote_errors:
        quote_freshness = "errors_present"
    elif fallback_quotes:
        quote_freshness = "fallback_close_present"

    return {
        "label": label,
        "status": status,
        "summary": summary,
        "reasons": blockers or caution or ["Deterministic data checks are clear."],
        "quote_freshness": quote_freshness,
        "quote_total": quote_total,
        "timestamped_quotes": timestamped_quotes,
        "fallback_quotes": fallback_quotes,
        "unstamped_quotes": unstamped_quotes,
        "quote_errors": quote_errors,
        "source_coverage": {
            "active_sources": sources_active,
            "active_count": len(sources_active),
            "degradation_count": len(degradation),
        },
        "catalyst_coverage": {
            "relevant_count": len(catalyst_relevant),
            "verified_count": catalyst_verified,
            "manual_review_required": manual_review_required,
        },
        "warning_count": len(quality_warnings),
        "warning_severity_counts": severity_counts,
        "readiness_counts": readiness_counts or {},
    }
