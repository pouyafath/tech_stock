"""Provider/source coverage summaries for reports and UIs."""

from __future__ import annotations

from typing import Any

ACTIONABLE_ACTIONS = {"BUY", "ADD", "TRIM", "SELL"}
BUY_ADD_ACTIONS = {"BUY", "ADD"}


def build_source_coverage(
    *,
    recommendation: dict[str, Any] | None = None,
    market_data: dict[str, dict[str, Any]] | None = None,
    enriched: dict[str, Any] | None = None,
    news_by_ticker: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Return deterministic source provenance rows.

    The model intentionally describes coverage rather than quality of an
    investment idea.  A provider can be optional and still useful; missing
    optional rows should surface as context, not hard blockers.
    """
    recommendation = recommendation or {}
    market_data = market_data or {}
    enriched = enriched or {}
    news_by_ticker = news_by_ticker or {}
    recs = recommendation.get("recommendations") or []
    degradation = enriched.get("degradation") or recommendation.get("source_degradation") or []
    degraded_sources = _degraded_source_names(degradation)

    rows = [
        _quote_row(market_data, degraded_sources),
        _recommendation_row(recs),
        _catalyst_row(recs, news_by_ticker, recommendation.get("quality_warnings") or [], degraded_sources),
        _analyst_row(market_data, enriched, degraded_sources),
        _fundamentals_row(market_data, enriched, degraded_sources),
        _options_row(market_data, degraded_sources),
        _macro_row(recommendation, enriched, degraded_sources),
        _insider_row(enriched, degraded_sources),
    ]
    required_missing = sum(1 for row in rows if row["required"] and row["status"] in {"MISSING", "DEGRADED"})
    degraded_count = sum(1 for row in rows if row["status"] == "DEGRADED")
    missing_optional = sum(1 for row in rows if not row["required"] and row["status"] == "MISSING")
    if required_missing:
        status = "BLOCKED"
        summary = "Required source coverage has gaps; verify data before acting."
    elif degraded_count:
        status = "REVIEW_FIRST"
        summary = "Core data is present, but at least one source reported degradation."
    elif missing_optional:
        status = "PARTIAL"
        summary = "Required sources are present; optional enrichment is incomplete."
    else:
        status = "OK"
        summary = "Required and optional source coverage are present."

    return {
        "status": status,
        "summary": summary,
        "rows": rows,
        "degradation_count": len(degradation),
        "required_missing_count": required_missing,
        "optional_missing_count": missing_optional,
        "degraded_count": degraded_count,
    }


def build_ticker_source_confidence(
    *,
    recommendation: dict[str, Any] | None = None,
    market_data: dict[str, Any] | None = None,
    enriched: dict[str, Any] | None = None,
    news: list[dict[str, Any]] | None = None,
    quality_warnings: list[dict[str, Any]] | None = None,
    degradation: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return per-ticker source confidence for Buy Signals and readiness.

    This is intentionally compact and deterministic.  It never invents analyst
    or catalyst numbers; it only reports whether a source family contributed
    evidence for this ticker.
    """
    recommendation = recommendation or {}
    market_data = market_data or {}
    enriched = enriched or {}
    news = news or []
    quality_warnings = quality_warnings or []
    degradation = degradation or []

    action = str(recommendation.get("action") or "").upper()
    degraded_sources = _degraded_source_names(degradation)
    warning_codes = {str(row.get("code") or "") for row in quality_warnings}

    quote = _ticker_quote_status(market_data, degraded_sources)
    catalyst = _ticker_catalyst_status(recommendation, news, warning_codes, degraded_sources)
    analyst = _ticker_analyst_status(market_data, enriched, degraded_sources)
    fundamentals = _ticker_fundamentals_status(market_data, enriched, degraded_sources)
    options = _ticker_options_status(market_data, degraded_sources)

    filters = []
    if quote["status"] != "OK":
        filters.append("quote_not_timestamped")
    if action in BUY_ADD_ACTIONS and catalyst["status"] in {"MISSING", "DEGRADED"}:
        filters.append("missing_catalyst")
    if analyst["status"] in {"MISSING", "DEGRADED"}:
        filters.append("missing_analyst")
    if any(row["status"] == "DEGRADED" for row in (quote, catalyst, analyst, fundamentals, options)):
        filters.append("source_degraded")

    blockers = []
    review = []
    if quote["status"] in {"MISSING", "DEGRADED"}:
        blockers.append(quote["action"])
    elif quote["status"] == "PARTIAL":
        review.append(quote["action"])
    if action in BUY_ADD_ACTIONS and catalyst["status"] in {"MISSING", "DEGRADED"}:
        blockers.append(catalyst["action"])
    elif catalyst["status"] == "PARTIAL":
        review.append(catalyst["action"])
    if analyst["status"] in {"MISSING", "DEGRADED", "PARTIAL"}:
        review.append(analyst["action"])
    for optional in (fundamentals, options):
        if optional["status"] in {"DEGRADED", "PARTIAL"}:
            review.append(optional["action"])

    if blockers:
        overall = "BLOCKED"
        label = "Blocked"
    elif review:
        overall = "REVIEW_FIRST"
        label = "Review First"
    else:
        overall = "TRADE_READY"
        label = "Trade Ready"

    return {
        "overall_status": overall,
        "label": label,
        "filters": sorted(set(filters)),
        "blockers": blockers,
        "review_reasons": review,
        "components": {
            "quote": quote,
            "catalyst": catalyst,
            "analyst": analyst,
            "fundamentals": fundamentals,
            "options": options,
        },
    }


def build_source_provenance(
    *,
    recommendation: dict[str, Any] | None = None,
    market_data: dict[str, dict[str, Any]] | None = None,
    enriched: dict[str, Any] | None = None,
    news_by_ticker: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Return per-ticker provider provenance rows.

    The output is intentionally factual: provider family, status, timestamp or
    field name, and what to verify. It does not infer analyst opinions or
    create source-backed claims that were not present in the run payload.
    """
    recommendation = recommendation or {}
    market_data = market_data or {}
    enriched = enriched or {}
    news_by_ticker = news_by_ticker or {}
    per_ticker = enriched.get("per_ticker") or {}
    degradation = enriched.get("degradation") or recommendation.get("source_degradation") or []
    warnings = recommendation.get("quality_warnings") or []
    warnings_by_ticker: dict[str, list[dict[str, Any]]] = {}
    for warning in warnings:
        ticker = str(warning.get("ticker") or "Portfolio").upper()
        warnings_by_ticker.setdefault(ticker, []).append(warning)

    rows: list[dict[str, Any]] = []
    tickers = {str(rec.get("ticker") or "").upper() for rec in recommendation.get("recommendations") or [] if rec.get("ticker")} | {
        str(ticker).upper() for ticker in market_data
    }

    rec_by_ticker = {str(rec.get("ticker") or "").upper(): rec for rec in recommendation.get("recommendations") or [] if rec.get("ticker")}
    for ticker in sorted(tickers):
        rec = rec_by_ticker.get(ticker) or {"ticker": ticker}
        ticker_market = market_data.get(ticker) or {}
        ticker_enriched = per_ticker.get(ticker) or {}
        confidence = build_ticker_source_confidence(
            recommendation=rec,
            market_data=ticker_market,
            enriched=ticker_enriched,
            news=news_by_ticker.get(ticker) or [],
            quality_warnings=warnings_by_ticker.get(ticker) or [],
            degradation=degradation,
        )
        rows.extend(_provenance_rows_for_ticker(ticker, rec, ticker_market, ticker_enriched, news_by_ticker.get(ticker) or [], confidence))

    status_counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "UNKNOWN")
        status_counts[status] = status_counts.get(status, 0) + 1
    problem_count = sum(status_counts.get(status, 0) for status in ("MISSING", "DEGRADED", "PARTIAL"))
    if not rows:
        status = "MISSING"
        summary = "No source provenance rows are available yet."
    elif status_counts.get("DEGRADED") or status_counts.get("MISSING"):
        status = "REVIEW_FIRST"
        summary = f"{problem_count} source provenance row(s) need review before acting."
    elif status_counts.get("PARTIAL"):
        status = "PARTIAL"
        summary = f"{status_counts['PARTIAL']} source provenance row(s) are partial."
    else:
        status = "OK"
        summary = "Ticker source provenance is available."

    return {
        "status": status,
        "summary": summary,
        "rows": rows,
        "status_counts": status_counts,
        "problem_count": problem_count,
    }


def _provenance_rows_for_ticker(
    ticker: str,
    rec: dict[str, Any],
    market: dict[str, Any],
    enriched: dict[str, Any],
    news: list[dict[str, Any]],
    confidence: dict[str, Any],
) -> list[dict[str, Any]]:
    components = confidence.get("components") or {}
    quote = components.get("quote") or {}
    catalyst = components.get("catalyst") or {}
    analyst = components.get("analyst") or {}
    fundamentals = components.get("fundamentals") or {}
    options = components.get("options") or {}
    latest_news = _latest_news(news)
    return [
        _provenance_row(
            ticker,
            "Quote",
            quote.get("status"),
            market.get("quote_source") or "yfinance",
            market.get("quote_timestamp_utc") or "",
            market.get("price_basis") or "regular_market_quote",
            quote.get("evidence") or "",
            quote.get("action") or "",
        ),
        _provenance_row(
            ticker,
            "Catalyst",
            catalyst.get("status"),
            rec.get("catalyst_source") or latest_news.get("source") or "news/provider feed",
            latest_news.get("published_at") or latest_news.get("datetime") or "",
            latest_news.get("title") or ("catalyst_source" if rec.get("catalyst_source") else ""),
            catalyst.get("evidence") or "",
            catalyst.get("action") or "",
        ),
        _provenance_row(
            ticker,
            "Analyst",
            analyst.get("status"),
            "Finnhub/yfinance",
            "",
            "analyst_consensus/price_targets",
            analyst.get("evidence") or "",
            analyst.get("action") or "",
        ),
        _provenance_row(
            ticker,
            "Fundamentals",
            fundamentals.get("status"),
            "yfinance/Finnhub",
            "",
            "valuation/profile",
            fundamentals.get("evidence") or "",
            fundamentals.get("action") or "",
        ),
        _provenance_row(
            ticker,
            "Options",
            options.get("status"),
            "yfinance options",
            "",
            "options_implied_move_pct",
            options.get("evidence") or "",
            options.get("action") or "",
        ),
    ]


def _provenance_row(
    ticker: str,
    source: str,
    status: Any,
    provider: Any,
    timestamp: Any,
    field: Any,
    evidence: Any,
    action: Any,
) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "source": source,
        "status": str(status or "MISSING"),
        "provider": str(provider or ""),
        "timestamp": str(timestamp or ""),
        "field": str(field or ""),
        "evidence": str(evidence or ""),
        "action": str(action or ""),
    }


def _latest_news(news: list[dict[str, Any]]) -> dict[str, Any]:
    if not news:
        return {}
    return max(news, key=lambda row: str(row.get("published_at") or row.get("datetime") or row.get("date") or ""))


def _quote_row(market_data: dict[str, dict[str, Any]], degraded_sources: set[str]) -> dict[str, Any]:
    total = len(market_data)
    errors = sum(1 for row in market_data.values() if row.get("error"))
    timestamped = sum(1 for row in market_data.values() if row.get("quote_timestamp_utc"))
    fallback = sum(1 for row in market_data.values() if row.get("price_basis") == "daily_history_close")
    if "yfinance" in degraded_sources:
        status = "DEGRADED"
    elif not total or errors == total:
        status = "MISSING"
    elif errors or fallback or timestamped < total:
        status = "PARTIAL"
    else:
        status = "OK"
    return _row(
        "Quotes",
        status,
        f"{timestamped}/{total} timestamped; {fallback} fallback close; {errors} errors",
        "Confirm live broker quotes before trading." if status != "OK" else "Use as research quote context.",
        required=True,
    )


def _recommendation_row(recs: list[dict[str, Any]]) -> dict[str, Any]:
    actionable = sum(1 for rec in recs if str(rec.get("action") or "").upper() in {"BUY", "ADD", "TRIM", "SELL"})
    status = "OK" if recs else "MISSING"
    return _row(
        "Claude recommendations",
        status,
        f"{len(recs)} recommendation(s); {actionable} actionable",
        "Generate a report before reviewing signals." if status == "MISSING" else "Review deterministic gates before acting.",
        required=True,
    )


def _catalyst_row(
    recs: list[dict[str, Any]],
    news_by_ticker: dict[str, list[dict[str, Any]]],
    warnings: list[dict[str, Any]],
    degraded_sources: set[str],
) -> dict[str, Any]:
    verified = sum(1 for rec in recs if rec.get("catalyst_verified"))
    manual = sum(1 for rec in recs if rec.get("manual_review_required"))
    cited = sum(1 for rec in recs if rec.get("catalyst_source"))
    news_count = sum(len(rows or []) for rows in news_by_ticker.values())
    missing_warning = sum(1 for warning in warnings if warning.get("code") == "missing_catalyst")
    relevant = [rec for rec in recs if str(rec.get("action") or "").upper() in {"BUY", "ADD", "TRIM", "SELL"}]
    if not relevant:
        status = "OK"
    elif "news" in degraded_sources or "yfinance_news" in degraded_sources:
        status = "DEGRADED"
    elif verified or cited or news_count:
        status = "PARTIAL" if manual or missing_warning else "OK"
    else:
        status = "MISSING"
    return _row(
        "News/catalyst",
        status,
        f"{verified} verified; {cited} cited; {manual} manual review; {news_count} news item(s)",
        "Verify catalyst manually for movers before buying/adding." if status != "OK" else "Catalyst coverage present.",
        required=True,
    )


def _analyst_row(market_data: dict[str, dict[str, Any]], enriched: dict[str, Any], degraded_sources: set[str]) -> dict[str, Any]:
    per_ticker = enriched.get("per_ticker") or {}
    consensus = sum(1 for row in per_ticker.values() if row.get("analyst_consensus"))
    targets = sum(1 for row in market_data.values() if row.get("analyst_target_mean") or row.get("number_of_analyst_opinions"))
    if "finnhub" in degraded_sources:
        status = "DEGRADED"
    elif consensus or targets:
        status = "OK"
    else:
        status = "MISSING"
    return _row(
        "Analyst consensus/targets",
        status,
        f"{consensus} consensus rows; {targets} target rows",
        "Treat analyst sentiment as unavailable for this run." if status == "MISSING" else "Use as one secondary input.",
        required=False,
    )


def _fundamentals_row(market_data: dict[str, dict[str, Any]], enriched: dict[str, Any], degraded_sources: set[str]) -> dict[str, Any]:
    per_ticker = enriched.get("per_ticker") or {}
    enriched_count = sum(1 for row in per_ticker.values() if row.get("fundamentals") or row.get("company_profile"))
    market_count = sum(1 for row in market_data.values() if row.get("forward_pe") or row.get("trailing_pe") or row.get("market_cap"))
    if "fundamentals" in degraded_sources:
        status = "DEGRADED"
    elif enriched_count or market_count:
        status = "OK"
    else:
        status = "MISSING"
    return _row(
        "Fundamentals",
        status,
        f"{enriched_count + market_count} ticker(s) with fundamentals/profile fields",
        "Avoid treating valuation comments as source-backed." if status == "MISSING" else "Valuation context available.",
        required=False,
    )


def _options_row(market_data: dict[str, dict[str, Any]], degraded_sources: set[str]) -> dict[str, Any]:
    count = sum(1 for row in market_data.values() if row.get("options_implied_move_pct") or row.get("earnings_implied_move_pct"))
    if "options" in degraded_sources:
        status = "DEGRADED"
    elif count:
        status = "OK"
    else:
        status = "MISSING"
    return _row(
        "Options implied move",
        status,
        f"{count} ticker(s) with implied-move data",
        "Use ATR/volatility as fallback; options context unavailable." if status == "MISSING" else "Options context available.",
        required=False,
    )


def _macro_row(recommendation: dict[str, Any], enriched: dict[str, Any], degraded_sources: set[str]) -> dict[str, Any]:
    macro = enriched.get("macro") or {}
    has_macro = bool(macro or recommendation.get("macro_regime") or recommendation.get("market_context_snapshot"))
    if "fred" in degraded_sources:
        status = "DEGRADED"
    elif has_macro:
        status = "OK"
    else:
        status = "MISSING"
    return _row(
        "Macro/regime",
        status,
        "macro context present" if has_macro else "no macro context found",
        "Review macro regime manually if sizing is sensitive." if status != "OK" else "Macro context available.",
        required=False,
    )


def _insider_row(enriched: dict[str, Any], degraded_sources: set[str]) -> dict[str, Any]:
    per_ticker = enriched.get("per_ticker") or {}
    count = sum(1 for row in per_ticker.values() if row.get("insider_activity"))
    if "finnhub" in degraded_sources:
        status = "DEGRADED"
    elif count:
        status = "OK"
    else:
        status = "MISSING"
    return _row(
        "Insider activity",
        status,
        f"{count} ticker(s) with insider activity",
        "Do not rely on insider-flow claims for this run." if status == "MISSING" else "Insider context available.",
        required=False,
    )


def _ticker_quote_status(market_data: dict[str, Any], degraded_sources: set[str]) -> dict[str, Any]:
    if "yfinance" in degraded_sources:
        status = "DEGRADED"
    elif market_data.get("error"):
        status = "MISSING"
    elif not market_data.get("current_price") and not market_data.get("quote_timestamp_utc"):
        status = "MISSING"
    elif market_data.get("price_basis") == "daily_history_close" or not market_data.get("quote_timestamp_utc"):
        status = "PARTIAL"
    else:
        status = "OK"
    return _component(
        status,
        f"{market_data.get('quote_source') or 'unavailable'}; {market_data.get('quote_timestamp_utc') or 'missing timestamp'}",
        "Confirm a live broker quote before trading." if status != "OK" else "Quote is timestamped.",
    )


def _ticker_catalyst_status(
    recommendation: dict[str, Any],
    news: list[dict[str, Any]],
    warning_codes: set[str],
    degraded_sources: set[str],
) -> dict[str, Any]:
    action = str(recommendation.get("action") or "").upper()
    if action not in ACTIONABLE_ACTIONS:
        return _component("OK", "No actionable trade catalyst required.", "No catalyst action needed.")
    has_news = any(str(row.get("title") or "").strip() for row in news)
    has_source = bool(recommendation.get("catalyst_source"))
    verified = bool(recommendation.get("catalyst_verified"))
    if "news" in degraded_sources or "yfinance_news" in degraded_sources:
        status = "DEGRADED"
    elif verified and (has_source or has_news):
        status = "OK"
    elif has_source or has_news:
        status = "PARTIAL"
    else:
        status = "MISSING"
    if "missing_catalyst_verification" in warning_codes:
        status = "MISSING"
    return _component(
        status,
        f"verified={verified}; source={recommendation.get('catalyst_source') or 'none'}; news={len(news)} item(s)",
        "Verify catalyst manually before buying/adding." if status != "OK" else "Catalyst/source present.",
    )


def _ticker_analyst_status(market_data: dict[str, Any], enriched: dict[str, Any], degraded_sources: set[str]) -> dict[str, Any]:
    analyst = enriched.get("analyst_consensus") or {}
    targets = bool(market_data.get("analyst_target_mean") or market_data.get("number_of_analyst_opinions"))
    if "finnhub" in degraded_sources:
        status = "DEGRADED"
    elif analyst or targets:
        status = "OK"
    else:
        status = "MISSING"
    return _component(
        status,
        f"consensus={'yes' if analyst else 'no'}; targets={'yes' if targets else 'no'}",
        "Do not treat analyst consensus/targets as sourced." if status != "OK" else "Analyst context present.",
    )


def _ticker_fundamentals_status(market_data: dict[str, Any], enriched: dict[str, Any], degraded_sources: set[str]) -> dict[str, Any]:
    present = bool(
        enriched.get("fundamentals")
        or enriched.get("company_profile")
        or market_data.get("forward_pe")
        or market_data.get("trailing_pe")
        or market_data.get("market_cap")
    )
    if "fundamentals" in degraded_sources:
        status = "DEGRADED"
    elif present:
        status = "OK"
    else:
        status = "MISSING"
    return _component(
        status,
        "fundamentals/profile present" if present else "no valuation/profile fields",
        "Treat valuation comments as unsourced." if status != "OK" else "Fundamental context present.",
    )


def _ticker_options_status(market_data: dict[str, Any], degraded_sources: set[str]) -> dict[str, Any]:
    present = bool(market_data.get("options_implied_move_pct") or market_data.get("earnings_implied_move_pct"))
    if "options" in degraded_sources:
        status = "DEGRADED"
    elif present:
        status = "OK"
    else:
        status = "MISSING"
    return _component(
        status,
        "implied move present" if present else "no options implied move",
        "Use ATR/volatility fallback; options context unavailable." if status != "OK" else "Options context present.",
    )


def _degraded_source_names(degradation: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for row in degradation:
        if not isinstance(row, dict):
            continue
        source = str(row.get("source") or row.get("provider") or "").strip().lower()
        operation = str(row.get("operation") or "").strip().lower()
        if source:
            names.add(source)
        if operation:
            names.add(operation)
    return names


def _row(source: str, status: str, evidence: str, action: str, *, required: bool) -> dict[str, Any]:
    return {
        "source": source,
        "status": status,
        "required": bool(required),
        "evidence": evidence,
        "action": action,
    }


def _component(status: str, evidence: str, action: str) -> dict[str, Any]:
    return {"status": status, "evidence": evidence, "action": action}
