"""Deterministic recommendation explainability for reports and UIs."""

from __future__ import annotations

from typing import Any

from src.source_coverage import build_ticker_source_confidence

ACTIONABLE_ACTIONS = {"BUY", "ADD", "TRIM", "SELL"}


def build_explainability(
    recommendation: dict[str, Any] | None = None,
    *,
    market_data: dict[str, dict[str, Any]] | None = None,
    enriched: dict[str, Any] | None = None,
    news_by_ticker: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Return compact, deterministic reasons for every recommendation.

    This intentionally does not ask the LLM for more prose. It translates the
    existing recommendation, quality gates, source confidence, and market data
    into an audit-friendly view that can be shown before a user acts.
    """
    recommendation = recommendation or {}
    market_data = market_data or {}
    enriched = enriched or {}
    news_by_ticker = news_by_ticker or {}
    warnings = recommendation.get("quality_warnings") or []
    degradation = recommendation.get("source_degradation") or enriched.get("degradation") or []
    per_ticker = enriched.get("per_ticker") or {}
    warnings_by_ticker: dict[str, list[dict[str, Any]]] = {}
    for warning in warnings:
        ticker = str(warning.get("ticker") or "Portfolio").upper()
        warnings_by_ticker.setdefault(ticker, []).append(warning)

    rows = []
    for rec in recommendation.get("recommendations") or []:
        ticker = str(rec.get("ticker") or "").upper()
        ticker_market = market_data.get(ticker) or {}
        ticker_enriched = per_ticker.get(ticker) or {}
        ticker_warnings = warnings_by_ticker.get(ticker, [])
        source_confidence = rec.get("source_confidence") or build_ticker_source_confidence(
            recommendation=rec,
            market_data=ticker_market,
            enriched=ticker_enriched,
            news=news_by_ticker.get(ticker) or [],
            quality_warnings=ticker_warnings,
            degradation=degradation,
        )
        missing_data = _missing_data(source_confidence, ticker_warnings)
        bullish, bearish = _evidence_lists(rec, ticker_market, ticker_warnings, source_confidence)
        change_mind = _change_mind(rec, ticker_warnings, ticker_market)
        rows.append(
            {
                "ticker": ticker or "Portfolio",
                "action": str(rec.get("action") or rec.get("hold_tier") or "").upper() or "N/A",
                "readiness": source_confidence.get("overall_status") or rec.get("trade_readiness") or "REVIEW_FIRST",
                "readiness_reason": _readiness_reason(source_confidence, ticker_warnings),
                "bullish_evidence": bullish,
                "bearish_evidence": bearish,
                "missing_data": missing_data,
                "change_mind": change_mind,
                "warning_codes": [str(row.get("code") or "") for row in ticker_warnings if row.get("code")],
                "source_confidence": source_confidence,
            }
        )

    ready = sum(1 for row in rows if row.get("readiness") == "TRADE_READY")
    review = sum(1 for row in rows if row.get("readiness") == "REVIEW_FIRST")
    blocked = sum(1 for row in rows if row.get("readiness") == "BLOCKED")
    summary = f"{len(rows)} recommendation(s) explained: {ready} trade-ready, {review} review-first, {blocked} blocked."
    return {"summary": summary, "rows": rows}


def _evidence_lists(
    rec: dict[str, Any],
    market: dict[str, Any],
    warnings: list[dict[str, Any]],
    source_confidence: dict[str, Any],
) -> tuple[list[str], list[str]]:
    bullish: list[str] = []
    bearish: list[str] = []
    action = str(rec.get("action") or "").upper()
    conviction = rec.get("conviction")
    if conviction is not None:
        target = bullish if action in {"BUY", "ADD"} else bearish if action in {"TRIM", "SELL"} else bullish
        target.append(f"Conviction {conviction}/10")
    thesis = str(rec.get("thesis") or "").strip()
    if thesis:
        bullish.append(_shorten(thesis, 180))
    catalyst_source = rec.get("catalyst_source")
    if rec.get("catalyst_verified"):
        bullish.append(f"Verified catalyst/source: {catalyst_source or 'provided'}")
    elif catalyst_source:
        bearish.append(f"Catalyst source is unverified: {catalyst_source}")
    technical = str(rec.get("technical_basis") or "").strip()
    if technical:
        (bearish if action in {"TRIM", "SELL"} else bullish).append(_shorten(technical, 160))
    if market.get("change_pct_1d") is not None:
        move = _float(market.get("change_pct_1d"))
        if move is not None:
            label = f"1D move {move:+.2f}%"
            (bearish if move < -3 else bullish if move > 3 else bullish).append(label)
    if market.get("rsi_14") is not None:
        rsi = _float(market.get("rsi_14"))
        if rsi is not None:
            if rsi >= 70:
                bearish.append(f"RSI {rsi:.1f} is overbought")
            elif rsi <= 35:
                bullish.append(f"RSI {rsi:.1f} is oversold")
    if market.get("atr_pct") is not None:
        atr = _float(market.get("atr_pct"))
        if atr is not None and atr >= 5:
            bearish.append(f"High ATR risk: {atr:.1f}% of price")
    for warning in warnings[:3]:
        message = str(warning.get("message") or "").strip()
        if message:
            bearish.append(_shorten(message, 160))
    blockers = source_confidence.get("blockers") or []
    for blocker in blockers[:2]:
        bearish.append(_shorten(str(blocker), 160))
    return _dedupe(bullish)[:4], _dedupe(bearish)[:4]


def _missing_data(source_confidence: dict[str, Any], warnings: list[dict[str, Any]]) -> list[str]:
    missing = []
    for name, component in (source_confidence.get("components") or {}).items():
        status = component.get("status")
        if status in {"MISSING", "DEGRADED", "PARTIAL"}:
            missing.append(f"{name}: {status} ({component.get('action')})")
    for warning in warnings:
        code = str(warning.get("code") or "")
        if code.startswith("missing_") or code in {"market_data_error", "stale_or_unstamped_quote"}:
            missing.append(f"{code}: {warning.get('action_required') or warning.get('message')}")
    return _dedupe([_shorten(row, 160) for row in missing])[:5]


def _readiness_reason(source_confidence: dict[str, Any], warnings: list[dict[str, Any]]) -> str:
    blockers = source_confidence.get("blockers") or []
    review = source_confidence.get("review_reasons") or []
    if blockers:
        return _shorten(str(blockers[0]), 180)
    if review:
        return _shorten(str(review[0]), 180)
    if warnings:
        return _shorten(str(warnings[0].get("action_required") or warnings[0].get("message") or ""), 180)
    return "No deterministic source-confidence blocker detected."


def _change_mind(rec: dict[str, Any], warnings: list[dict[str, Any]], market: dict[str, Any]) -> str:
    invalidation = str(rec.get("risk_or_invalidation") or "").strip()
    if invalidation and invalidation.upper() != "N/A":
        return _shorten(invalidation, 220)
    controls = rec.get("risk_controls") or {}
    stop = controls.get("stop_loss_pct")
    take_profit = controls.get("take_profit_pct")
    if stop is not None:
        return f"Re-check if price breaches stop-loss control ({stop}%)."
    if take_profit is not None:
        return f"Re-check if price reaches take-profit control ({take_profit}%)."
    if warnings:
        return _shorten(str(warnings[0].get("action_required") or warnings[0].get("message") or ""), 220)
    quote_time = market.get("quote_timestamp_utc")
    if quote_time:
        return f"Re-check if broker quote materially differs from provider quote timestamped {quote_time}."
    return "Re-check broker quote, position size, catalyst, and fee/FX assumptions before execution."


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _shorten(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _dedupe(rows: list[str]) -> list[str]:
    seen = set()
    out = []
    for row in rows:
        key = row.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row.strip())
    return out


__all__ = ["build_explainability"]
