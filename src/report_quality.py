"""
report_quality.py
Deterministic quality checks and safety gates for generated recommendations.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime

from src.backtester import HORIZON_DAYS
from src.portfolio_analytics import aggregate_company_exposure, aggregate_positions, company_key


@dataclass
class QualityWarning:
    severity: str
    code: str
    ticker: str | None
    message: str
    action_required: str

    def to_dict(self) -> dict:
        return asdict(self)


def _warn(severity: str, code: str, ticker: str | None, message: str, action: str) -> QualityWarning:
    return QualityWarning(severity, code, ticker, message, action)


def _news_has_catalyst(news_by_ticker: dict, ticker: str) -> bool:
    for article in (news_by_ticker or {}).get(ticker) or []:
        title = (article.get("title") or "").strip().lower()
        if title and not title.startswith("error fetching news"):
            return True
    return False


def _enrichment_for(enriched: dict, ticker: str) -> dict:
    return ((enriched or {}).get("per_ticker") or {}).get(ticker) or {}


def _parse_iso_date(value: str | None):
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _days_until_earnings(enrich: dict) -> int | None:
    earnings = (enrich or {}).get("upcoming_earnings") or (enrich or {}).get("td_earnings") or {}
    if isinstance(earnings, list):
        earnings = earnings[0] if earnings else {}
    date_value = earnings.get("date") or earnings.get("earnings_date")
    earnings_date = _parse_iso_date(date_value)
    if not earnings_date:
        return None
    return (earnings_date - datetime.now().date()).days


def _has_decision_tree(rec: dict) -> bool:
    text = " ".join([
        str(rec.get("thesis") or ""),
        str(rec.get("risk_or_invalidation") or ""),
    ]).lower()
    if not text:
        return False
    action_words = r"(then|do|buy|add|hold|keep|trim|sell|reduce|exit|wait)"
    condition_then_action = re.search(rf"\bif\b[^.;]*\b{action_words}\b", text)
    action_then_condition = re.search(rf"\b{action_words}\b[^.;]*\bif\b", text)
    paired_conditions = re.search(
        rf"(\bif\b[^.;]*\b{action_words}\b|\b{action_words}\b[^.;]*\bif\b)"
        rf".*[.;]\s*"
        rf"(\bif\b[^.;]*\b{action_words}\b|\b{action_words}\b[^.;]*\bif\b)",
        text,
    )
    if paired_conditions:
        return True
    return bool(condition_then_action or action_then_condition)


def evaluate(
    recommendation: dict,
    market_data: dict,
    portfolio: dict = None,
    news_by_ticker: dict = None,
    enriched: dict = None,
    settings: dict = None,
) -> list[dict]:
    """Return structured warnings for report/recommendation quality issues."""
    portfolio = portfolio or {}
    settings = settings or {}
    warnings: list[QualityWarning] = []
    recs = recommendation.get("recommendations", []) or []
    threshold = settings.get("news_catalyst_move_threshold_pct", 5)

    positions, _ = aggregate_positions(
        portfolio.get("holdings", []),
        settings.get("cad_per_usd_assumption", 1.37),
    )
    company_exposure, _ = aggregate_company_exposure(
        portfolio.get("holdings", []),
        settings.get("cad_per_usd_assumption", 1.37),
    )
    max_position_pct = settings.get("max_position_pct", 25)

    for ticker, data in (market_data or {}).items():
        if data.get("error"):
            warnings.append(_warn(
                "high", "market_data_error", ticker,
                f"Market data error: {data.get('error')}",
                "Verify quote manually before using any recommendation for this ticker.",
            ))
            continue
        if data.get("price_basis") == "daily_history_close" or not data.get("quote_timestamp_utc"):
            warnings.append(_warn(
                "medium", "stale_or_unstamped_quote", ticker,
                "Quote is based on daily close fallback or lacks a provider timestamp.",
                "Do not execute from this report until a live/delayed quote is confirmed.",
            ))

    for holding in portfolio.get("holdings", []) or []:
        ticker = holding.get("ticker")
        data = (market_data or {}).get(ticker) or {}
        if not ticker or not data or data.get("error"):
            continue
        holding_price = holding.get("market_price")
        quote = data.get("current_price")
        if not holding_price or not quote:
            continue
        if holding.get("market_currency") != data.get("currency"):
            continue
        delta = abs((quote - holding_price) / holding_price * 100)
        if delta > settings.get("quote_reconciliation_threshold_pct", 1.5):
            warnings.append(_warn(
                "medium", "quote_source_mismatch", ticker,
                f"Wealthsimple CSV price ${holding_price:.2f} differs from yfinance quote ${quote:.2f} by {delta:.1f}%.",
                "Check whether the holdings CSV or quote feed is stale before trading.",
            ))

    for company, row in company_exposure.items():
        if row.get("pct", 0) > max_position_pct:
            warnings.append(_warn(
                "high", "oversized_company_exposure", company,
                f"{company} economic exposure is {row['pct']:.1f}% of holdings ex-cash, above the {max_position_pct}% cap.",
                "Prefer TRIM/HOLD over BUY/ADD until exposure is back under the cap.",
            ))

    for rec in recs:
        ticker = rec.get("ticker")
        action = (rec.get("action") or "").upper()
        md = (market_data or {}).get(ticker) or {}
        move = md.get("change_pct_1d")
        risk_controls = rec.get("risk_controls") or {}

        low = rec.get("price_target_low_pct")
        high = rec.get("price_target_high_pct")
        if rec.get("range_was_normalized") or (low is not None and high is not None and low > high):
            warnings.append(_warn(
                "medium", "reversed_price_range", ticker,
                "Bear/bull price range is reversed.",
                "Normalize before rendering and verify the thesis direction.",
            ))

        horizon = (rec.get("time_horizon") or "").lower()
        if horizon and horizon not in HORIZON_DAYS:
            warnings.append(_warn(
                "medium", "invalid_time_horizon", ticker,
                f"Unsupported time horizon: {rec.get('time_horizon')}",
                "Use one of the configured horizon strings.",
            ))
        max_abs_range = max(
            [abs(v) for v in (low, high) if isinstance(v, (int, float))],
            default=0,
        )
        if horizon in {"intraday", "next session"} and max_abs_range > 15:
            warnings.append(_warn(
                "low", "horizon_range_mismatch", ticker,
                "Near-term horizon has an unusually wide bear/bull move range.",
                "Confirm the move is catalyst-driven, not a stale range.",
            ))

        if not _has_decision_tree(rec):
            warnings.append(_warn(
                "medium", "missing_decision_tree", ticker,
                'Recommendation lacks compact "If X, do Y; if Z, do W" execution language.',
                "Add decision-tree wording to the thesis or invalidation before execution.",
            ))

        if action in {"BUY", "ADD"}:
            if risk_controls.get("entry_zone_low_pct") is None or risk_controls.get("entry_zone_high_pct") is None:
                warnings.append(_warn(
                    "medium", "missing_entry_zone", ticker,
                    "BUY/ADD recommendation lacks an entry-zone range.",
                    "Add entry_zone_low_pct and entry_zone_high_pct before execution.",
                ))
        if action in {"SELL", "TRIM"}:
            if risk_controls.get("stop_loss_pct") is None:
                warnings.append(_warn(
                    "medium", "missing_stop_loss", ticker,
                    "SELL/TRIM recommendation lacks a stop/invalidation percentage.",
                    "Add stop_loss_pct to make the risk control explicit.",
                ))

        enrich = _enrichment_for(enriched or {}, ticker)
        days_to_earnings = _days_until_earnings(enrich)
        near_earnings = days_to_earnings is not None and 0 <= days_to_earnings <= 7
        large_move = move is not None and abs(move) >= threshold
        catalyst_required = action in {"BUY", "ADD"} and (
            large_move or rec.get("earnings_alert") or near_earnings
        )
        if catalyst_required:
            verified = bool(rec.get("catalyst_verified"))
            has_source = bool(rec.get("catalyst_source")) or _news_has_catalyst(news_by_ticker or {}, ticker)
            if not verified or not has_source:
                warnings.append(_warn(
                    "high", "missing_catalyst_verification", ticker,
                    "BUY/ADD requires verified catalyst because this ticker has a large move or near-term earnings.",
                    "Downgrade to HOLD or mark manual_review_required until catalyst is verified.",
                ))

        thesis = (rec.get("thesis") or "").lower()
        if enrich.get("analyst_consensus") and "analyst" not in thesis:
            warnings.append(_warn(
                "low", "missing_analyst_citation", ticker,
                "Analyst consensus is available but the thesis does not cite it.",
                "Cite analyst consensus or explicitly state why it is ignored.",
            ))
        if enrich.get("insider_activity") and "insider" not in thesis:
            warnings.append(_warn(
                "low", "missing_insider_citation", ticker,
                "Insider activity is available but the thesis does not cite it.",
                "Cite insider activity or explicitly state why it is ignored.",
            ))

        position = positions.get(ticker)
        if action in {"BUY", "ADD"} and position and position.get("pct", 0) >= max_position_pct:
            warnings.append(_warn(
                "high", "buy_add_over_position_cap", ticker,
                f"{ticker} is already {position['pct']:.1f}% of holdings ex-cash.",
                "Do not BUY/ADD above the configured position cap.",
            ))

    return [warning.to_dict() for warning in warnings]


def vix_size_multiplier(vix: float | None, settings: dict | None = None) -> float:
    """Map VIX level to a position-size multiplier.

    Defaults intentionally cautious:
        VIX < 15 → 1.0×    (calm, full size)
        15-25    → 0.85×   (normal)
        25-35    → 0.6×    (elevated — half-size new BUYs)
        > 35     → 0.4×    (panic — only the highest-conviction trades)

    Override via settings.json["vix_size_thresholds"] = {"low":15,"med":25,"high":35,
                                                          "low_mult":1.0,"med_mult":0.85,...}
    """
    if vix is None:
        return 1.0
    cfg = (settings or {}).get("vix_size_thresholds") or {}
    low      = float(cfg.get("low", 15))
    med      = float(cfg.get("med", 25))
    high     = float(cfg.get("high", 35))
    low_m    = float(cfg.get("low_mult", 1.0))
    med_m    = float(cfg.get("med_mult", 0.85))
    high_m   = float(cfg.get("high_mult", 0.6))
    panic_m  = float(cfg.get("panic_mult", 0.4))
    if vix < low:
        return low_m
    if vix < med:
        return med_m
    if vix < high:
        return high_m
    return panic_m


def apply_quality_gates(
    recommendation: dict,
    warnings: list[dict],
    drawdown_state: dict | None = None,
    market_context: dict | None = None,
    settings: dict | None = None,
    aging_summary_data: dict | None = None,
    backtest_summary: dict | None = None,
    trailing_alerts: list[dict] | None = None,
) -> dict:
    """Apply hard safety gates after model output.

    Layers, in order:
      1. Catalyst gate — downgrade BUY/ADD lacking verified catalyst to HOLD-watch.
      2. Stale-position gate — force EXIT recommendations on positions >2y old
         that aren't already SELL/TRIM.
      3. VIX-regime sizing — scale invest_amount_usd by VIX-derived multiplier.
      4. Drawdown circuit breaker — if portfolio is N% from peak: halve sizes,
         force HOLD-watch on conviction <7, drop ADD/BUY recommendations.
    """
    out = deepcopy(recommendation)
    settings = settings or {}

    # ── 1. Catalyst gate (existing behaviour) ──────────────────────────────
    blocked = {
        warning.get("ticker")
        for warning in warnings or []
        if warning.get("code") == "missing_catalyst_verification"
    }
    for rec in out.get("recommendations", []) or []:
        ticker = rec.get("ticker")
        if ticker not in blocked:
            continue
        if rec.get("action") in {"BUY", "ADD"}:
            rec["action"] = "HOLD"
            rec["hold_tier"] = "watch"
            try:
                rec["conviction"] = min(float(rec.get("conviction", 5)), 5)
                if rec["conviction"].is_integer():
                    rec["conviction"] = int(rec["conviction"])
            except (TypeError, ValueError, AttributeError):
                rec["conviction"] = 5
            rec["invest_amount_usd"] = None
            rec["manual_review_required"] = True
            rec["catalyst_verified"] = False
            rec["catalyst_source"] = rec.get("catalyst_source") or "manual_required"
            rec["thesis"] = (
                "Manual catalyst verification required before trading. "
                + (rec.get("thesis") or "")
            ).strip()

    # ── 2. Stale-position gate (>2y holds: force exit candidate) ────────────
    stale_tickers = set((aging_summary_data or {}).get("stale_tickers") or [])
    if stale_tickers:
        existing_tickers = {(r.get("ticker") or "") for r in out.get("recommendations", [])}
        for rec in out.get("recommendations", []) or []:
            if rec.get("ticker") in stale_tickers and rec.get("action") not in {"SELL", "TRIM"}:
                rec["action"] = "TRIM"
                rec["thesis"] = (
                    "POSITION OVER 2-YEAR CAP — forced trim per strategy rule (no permanent holds). "
                    + (rec.get("thesis") or "")
                ).strip()
                rec["manual_review_required"] = True
        # Make sure stale tickers without an explicit recommendation surface as TRIM.
        for ticker in stale_tickers - existing_tickers:
            out.setdefault("recommendations", []).append({
                "ticker": ticker,
                "action": "TRIM",
                "conviction": 7,
                "thesis": "POSITION OVER 2-YEAR CAP — strategy rule forces trim or exit.",
                "manual_review_required": True,
                "auto_generated": True,
            })

    # ── 2.5. Trailing-stop breaches (auto-TRIM positions where stop hit) ────
    breached_alerts = [a for a in (trailing_alerts or []) if a.get("breached")]
    if breached_alerts:
        existing_tickers = {(r.get("ticker") or "") for r in out.get("recommendations", [])}
        breached_tickers = {a["ticker"] for a in breached_alerts}
        # Modify in-place if already in recs
        for rec in out.get("recommendations", []) or []:
            if rec.get("ticker") in breached_tickers and rec.get("action") not in {"SELL", "TRIM"}:
                rec["action"] = "TRIM"
                alert = next(a for a in breached_alerts if a["ticker"] == rec["ticker"])
                rec["thesis"] = (
                    f"TRAILING STOP BREACHED at ${alert['stop_price']:.2f} "
                    f"(peak +{alert['peak_gain_pct']:.0f}% → now +{alert['current_gain_pct']:.0f}%). "
                    + (rec.get("thesis") or "")
                ).strip()
                rec["manual_review_required"] = True
                rsc = rec.setdefault("risk_controls", {})
                rsc["stop_loss_pct"] = round(
                    (alert["stop_price"] / alert["current_price"] - 1.0) * 100.0, 2
                )
        # Append for breached tickers Claude didn't surface
        for alert in breached_alerts:
            if alert["ticker"] not in existing_tickers:
                out.setdefault("recommendations", []).append({
                    "ticker": alert["ticker"],
                    "action": "TRIM",
                    "conviction": 8,
                    "thesis": (
                        f"TRAILING STOP BREACHED at ${alert['stop_price']:.2f} "
                        f"(peak +{alert['peak_gain_pct']:.0f}% → now "
                        f"+{alert['current_gain_pct']:.0f}%). Strategy rule: lock in "
                        f"gains when {alert['trail_kind']} trail is hit."
                    ),
                    "manual_review_required": True,
                    "auto_generated": True,
                    "risk_controls": {
                        "stop_loss_pct": round(
                            (alert["stop_price"] / alert["current_price"] - 1.0) * 100.0, 2
                        ),
                    },
                })
        out["trailing_stop_breaches"] = breached_alerts

    # ── 3. VIX-regime sizing ─────────────────────────────────────────────────
    vix = None
    macro = (market_context or {}).get("macro") if market_context else None
    if isinstance(macro, dict):
        vix = macro.get("vix")
    elif isinstance(market_context, dict):
        vix = market_context.get("vix")
    vix_mult = vix_size_multiplier(vix, settings)
    if vix_mult != 1.0:
        for rec in out.get("recommendations", []) or []:
            amount = rec.get("invest_amount_usd")
            if amount is None:
                continue
            try:
                rec["invest_amount_usd"] = round(float(amount) * vix_mult, 0) or None
            except (TypeError, ValueError):
                pass
        out.setdefault("session_summary", "")
        out["vix_size_multiplier"] = vix_mult

    # ── 3.5. Conviction-stratified sizing (uses actual hit rates from backtester)
    conv_multipliers = {}
    if backtest_summary:
        conv_multipliers = backtest_summary.get("sizing_multipliers_by_conviction") or {}
    if conv_multipliers:
        for rec in out.get("recommendations", []) or []:
            amount = rec.get("invest_amount_usd")
            if amount is None:
                continue
            try:
                conv = int(float(rec.get("conviction", 0)))
            except (TypeError, ValueError):
                continue
            mult = conv_multipliers.get(conv) or conv_multipliers.get(str(conv))
            if mult is None:
                continue
            try:
                rec["invest_amount_usd"] = round(float(amount) * float(mult), 0) or None
                rec["sizing_multiplier_applied"] = round(float(mult), 3)
            except (TypeError, ValueError):
                pass

    # ── 4. Drawdown circuit breaker ─────────────────────────────────────────
    if drawdown_state and drawdown_state.get("triggered"):
        for rec in out.get("recommendations", []) or []:
            action = (rec.get("action") or "").upper()
            conviction = rec.get("conviction")
            if action in {"BUY", "ADD"}:
                # Halve and downgrade ADDs; cancel BUYs entirely.
                if action == "ADD":
                    amount = rec.get("invest_amount_usd")
                    if amount is not None:
                        try:
                            rec["invest_amount_usd"] = round(float(amount) * 0.5, 0) or None
                        except (TypeError, ValueError):
                            pass
                else:  # BUY
                    rec["action"] = "HOLD"
                    rec["hold_tier"] = "watch"
                    rec["invest_amount_usd"] = None
                rec["thesis"] = (
                    f"DRAWDOWN MODE ({drawdown_state.get('drawdown_pct', 0):+.1f}%): "
                    + (rec.get("thesis") or "")
                ).strip()
            # Force HOLD-watch on weak-conviction holds during drawdown.
            try:
                if action == "HOLD" and conviction is not None and float(conviction) < 7:
                    rec["hold_tier"] = "watch"
            except (TypeError, ValueError):
                pass
        out["drawdown_state"] = drawdown_state

    out["priority_actions"] = [
        action for action in out.get("priority_actions", []) or []
        if action.get("ticker") not in blocked
    ]
    out["quality_warnings"] = warnings or []
    return out
