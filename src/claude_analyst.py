"""
claude_analyst.py
Builds the structured prompt, calls the Claude API, parses and validates
the JSON response. Prompt caching is applied to the system prompt to
reduce costs on repeated runs.
"""

import json
import os
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import anthropic
import jsonschema
from dotenv import load_dotenv

from src.config import load_settings
from src.drift_tracker import compute_drift
from src.portfolio_analytics import build_hedge_suggestions
from src.report_quality import apply_quality_gates, evaluate as evaluate_report_quality

load_dotenv(Path(__file__).parent.parent / ".env")

# Pricing per 1M tokens (USD) — update when Anthropic changes rates
MODEL_PRICING = {
    "claude-sonnet-4-6": {"input": 3.00,  "output": 15.00, "cache_write": 3.75,  "cache_read": 0.30},
    "claude-opus-4-7":   {"input": 5.00,  "output": 25.00, "cache_write": 6.25,  "cache_read": 0.50},
    "claude-haiku-4-5":  {"input": 1.00,  "output": 5.00,  "cache_write": 1.25,  "cache_read": 0.10},
}


SYSTEM_PROMPT = """You are a disciplined, fee-aware portfolio advisor for a Canadian retail investor using Wealthsimple Premium with a USD account ($10/month plan). The investor prefers holding positions for 1 month to 3 years, with a sweet spot of 3–12 months. They invest $50–$700 per session and can buy fractional shares, so always express trade size as a dollar amount (invest_amount_usd), not share counts.

Your job: analyze the provided portfolio snapshot, market data, technical indicators, enrichment signals, news sentiment, and track record — then output a structured trading recommendation in valid JSON only.

RULES YOU MUST FOLLOW:
1. FEE DISCIPLINE: Every BUY or ADD must have net_expected_pct > fee_hurdle_pct. If it doesn't clear the hurdle, output HOLD instead.
2. CONVICTION: Score 1–10. Under 6 = HOLD only. Only conviction ≥6 gets BUY/SELL/TRIM/ADD.
3. THESIS CLARITY: 2-3 sentences explaining WHY + clear invalidation condition (what proves you wrong).
4. POSITION SIZING: No single position > 25% of total portfolio value.
5. RISK TOLERANCE: Aggressive — high-volatility names (PLTR, SMCI, small-cap AI) alongside megacaps are fine.
6. SESSION AWARENESS: morning = overnight catalysts, premarket, pre-open setup. afternoon = intraday action, EOD positioning, swing entries.
7. JSON ONLY: Return ONLY valid JSON. No preamble, no markdown fences.
8. NEGATIVE CASH / MARGIN: Negative cash_cad = margin — mention interest drag, bias toward SELL/TRIM, never add leveraged positions.
9. LIQUIDITY TIER: small-caps (PLTR/SMCI/ARM/IONQ/SHOP/etc) require conviction ≥8 and smaller sizing. Bid-ask drag is real.
10. SHARE CLASS DUPLICATES: Never recommend both GOOG and GOOGL simultaneously. Flag if portfolio holds both.
11. LEVERAGED ETF DECAY: SOXL, TQQQ, SQQQ, UPRO, UVXY, TMF, TZA, SPXL, LABU, LABD, TSLL, NVDL, SOXS, TMV, UDOW, SDOW — never hold >2 weeks. Always include decay warning if held.
12. INDICATOR SANITY: RSI>70 = bias against BUY/ADD. RSI<30 = mean-reversion candidate. Price < SMA(200) = not a long-term uptrend. MACD hist turning positive = bullish trigger.
13. SENTIMENT CHECK: Strongly negative news (<-0.3 avg) + wanting BUY = thesis must explain why market is wrong. Strong positive news + weak technicals = crowded-trade warning.
14. TRACK RECORD CALIBRATION: Use provided track record to calibrate conviction. If a conviction bucket has n>=3 and avg_return_pct<=0 or hit_rate<50%, cap similar new recommendations at one conviction point lower. If the action bucket has negative average return, lower confidence by 1 or use HOLD. Do not assign conviction 8-10 unless similar past action/ticker evidence was positive or today has a verified new catalyst.
15. EARNINGS ALERT: If enrichment data shows a ticker has earnings within 7 days, set earnings_alert=true and lead the thesis with "⚠️ EARNINGS [DATE] [BMO/AMC]". Earnings change the risk profile — do not ADD into earnings without explicitly stating why you expect a beat.
16. ETF SECTOR CLASSIFICATION: ARK ETFs (ARKF, ARKK, ARKQ, ARKG) = ~90% technology — count toward tech concentration. VGRO/XEQT/VEQT/VCNS = balanced multi-sector, count separately. SOXL = 3× semiconductors. TQQQ = 3× QQQ tech-heavy. Use these when calculating real sector concentration.
17. ENRICHMENT CITATION: When analyst_consensus is available, cite it in the thesis (e.g., "66 analysts: STRONG BUY"). When earnings_history shows 3+ consecutive beats, say "beat estimates X quarters in a row". When insider_activity shows net buying/selling of significance, mention it. Do not silently ignore enrichment data.
18. INVESTMENT SIZING (FRACTIONAL SHARES): For BUY/ADD, set invest_amount_usd based on the session budget (USD available, shown in PORTFOLIO): conviction 8–10 = up to 40% of budget, conviction 7 = 25%, conviction 6 = 15%. Cap at the position limit. Express as a dollar amount — the investor will buy fractional shares automatically through Wealthsimple.
19. HOLD TIERS — add hold_tier to every HOLD: "watch" (conviction ≤5: monitoring for deterioration/exit opportunity), "keep" (conviction 6–7: comfortable, no action needed), "add_on_dip" (conviction ≥8: would buy more if budget or price dipped).
20. TIME HORIZONS: Use exactly one of: "intraday" / "next session" / "1-3 trading days" / "1-2 weeks" / "1-3 months" / "3-6 months" / "6-12 months" / "12-36 months". Match to the actual thesis — a mean-reversion trade is 1-3 months, a fundamental growth story is 12-36 months. If the report is generated after the regular market close, do not use "intraday"; use "next session" or longer.
21. TARGET EXIT & PRICE RANGE: For every recommendation (including HOLDs), provide: target_exit_date (e.g., "Jul 2026"), price_target_low_pct (conservative % move over holding period), price_target_high_pct (optimistic % move). These must be consistent with time_horizon.
22. BUY SIGNALS: Actively look for BUY opportunities — not just in the existing portfolio. If a watchlist ticker or a ticker mentioned in news is setting up well (RSI recovering, catalyst, analyst upgrades), recommend BUY with invest_amount_usd. Don't only HOLD; find the best 1-2 buys per session if any exist.
23. PRIORITY ACTIONS: Output priority_actions — an ordered list of what to execute today. Only include BUY/SELL/TRIM/ADD. Order by urgency (intraday first, then short-term). HOLDs are never in this list.
24. QUOTE DISCIPLINE: Treat quote freshness as a hard input. Use current_price only with its quote timestamp, previous_close, source, and price_basis. If a ticker uses daily_history_close fallback or lacks a quote timestamp, say that data quality is degraded and avoid new BUY/ADD recommendations.
25. LARGE-MOVE CATALYST CHECK: For any ticker with an absolute 1-day move of 5% or more, explicitly cite the top available news/catalyst in the thesis. If no news catalyst is available, say "NO VERIFIED CATALYST FOUND" and make any trade conditional on manual catalyst verification.
26. TRADER CLARITY: Separate expected stock move from expected benefit of the action in wording. For SELL/TRIM, net_expected_pct means drawdown avoided or gain protected, not a positive expected stock return.
27. RISK CONTROLS: Every recommendation must include risk_controls with entry_zone_low_pct, entry_zone_high_pct, stop_loss_pct, and take_profit_pct. Use percentages relative to current price. For SELL/TRIM, stop_loss_pct means the adverse rebound or invalidation threshold.
28. CATALYST GATE: Every recommendation must include catalyst_verified, catalyst_source, and manual_review_required. BUY/ADD on >5% movers or near-earnings names requires catalyst_verified=true and a specific source; otherwise downgrade to HOLD and set manual_review_required=true.
29. DECISION TREE: Every thesis or risk_or_invalidation must contain compact "If X, do Y; if Z, do W" execution language.
30. RANGE LABELS: price_target_low_pct is the Bear Case and price_target_high_pct is the Bull Case. Keep the JSON field names unchanged for compatibility.
31. HEDGE SUGGESTIONS: If concentration, beta, or volatility risk is high, include hedge_suggestions. Trim/rebalance suggestions should come before inverse ETFs. Inverse ETF hedges are allowed only as small short-term hedges with risk notes and sizing caps.
32. COMPACT JSON: Return at most 12 recommendation rows. Include all priority/actionable trades, all holdings with material risk, and the strongest watchlist opportunities. Do not include every low-signal ticker as a recommendation; summarize the rest in watchlist_flags, sector_warnings, or warnings.

OUTPUT FORMAT (return exactly this structure):
{
  "session_summary": "1-2 sentence overview of market context and your overall read",
  "portfolio_health": {
    "total_value_usd_equivalent": <number>,
    "overall_pnl_pct": <number>,
    "concentration_risk": "low|medium|high",
    "cash_deployment": "string",
    "risk_dashboard": <object or null>
  },
  "hedge_suggestions": [
    {
      "type": "rebalance|inverse_etf|cash_buffer|other",
      "instrument": "string",
      "action": "string",
      "max_portfolio_pct": <number or null>,
      "rationale": "string",
      "risk_note": "string"
    }
  ],
  "priority_actions": [
    {
      "order": 1,
      "ticker": "string",
      "action": "BUY|SELL|TRIM|ADD",
      "invest_amount_usd": <number or null>,
      "shares": <number or null>,
      "rationale": "one-line reason"
    }
  ],
  "recommendations": [
    {
      "ticker": "string",
      "action": "BUY|SELL|HOLD|TRIM|ADD",
      "invest_amount_usd": <number or null>,
      "shares": <number or null>,
      "target_entry_or_exit": <number or null>,
      "conviction": <1-10>,
      "thesis": "string",
      "technical_basis": "string or null",
      "liquidity_tier": "megacap|midcap|smallcap",
      "expected_move_pct": <number>,
      "fee_hurdle_pct": <number>,
      "net_expected_pct": <number>,
      "risk_or_invalidation": "string",
      "time_horizon": "intraday|next session|1-3 trading days|1-2 weeks|1-3 months|3-6 months|6-12 months|12-36 months",
      "target_exit_date": "string or null (e.g. Jul 2026)",
      "price_target_low_pct": <number or null>,
      "price_target_high_pct": <number or null>,
      "risk_controls": {
        "entry_zone_low_pct": <number or null>,
        "entry_zone_high_pct": <number or null>,
        "stop_loss_pct": <number or null>,
        "take_profit_pct": <number or null>
      },
      "catalyst_verified": <true|false|null>,
      "catalyst_source": "string or null",
      "manual_review_required": <true|false|null>,
      "hold_tier": "watch|keep|add_on_dip|null",
      "earnings_alert": <true|false|null>
    }
  ],
  "watchlist_flags": [
    {
      "ticker": "string",
      "why_noteworthy": "string"
    }
  ],
  "sector_warnings": ["string"],
  "warnings": ["string"]
}"""


# ── JSON schema for Claude's response ────────────────────────────────────────
# additionalProperties=True so Claude can add fields without breaking us.
RECOMMENDATION_SCHEMA = {
    "type": "object",
    "required": ["session_summary", "portfolio_health", "recommendations", "warnings"],
    "properties": {
        "session_summary": {"type": "string"},
        "portfolio_health": {
            "type": "object",
            "properties": {
                "total_value_usd_equivalent": {"type": ["number", "null"]},
                "overall_pnl_pct": {"type": ["number", "null"]},
                "concentration_risk": {"type": ["string", "null"]},
                "cash_deployment": {"type": ["string", "null"]},
                "risk_dashboard": {"type": ["object", "null"]},
            },
            "additionalProperties": True,
        },
        "hedge_suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": ["string", "null"]},
                    "instrument": {"type": ["string", "null"]},
                    "action": {"type": ["string", "null"]},
                    "max_portfolio_pct": {"type": ["number", "null"]},
                    "rationale": {"type": ["string", "null"]},
                    "risk_note": {"type": ["string", "null"]},
                },
                "additionalProperties": True,
            },
        },
        "priority_actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "order": {"type": "number"},
                    "ticker": {"type": "string"},
                    "action": {"enum": ["BUY", "SELL", "TRIM", "ADD"]},
                    "invest_amount_usd": {"type": ["number", "null"]},
                    "shares": {"type": ["number", "null"]},
                    "rationale": {"type": "string"},
                },
                "additionalProperties": True,
            },
        },
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["ticker", "action", "conviction", "thesis",
                             "net_expected_pct", "fee_hurdle_pct", "time_horizon"],
                "properties": {
                    "ticker": {"type": "string"},
                    "action": {"enum": ["BUY", "SELL", "HOLD", "TRIM", "ADD"]},
                    "invest_amount_usd": {"type": ["number", "null"]},
                    "shares": {"type": ["number", "null"]},
                    "target_entry_or_exit": {"type": ["number", "null"]},
                    "conviction": {"type": "number", "minimum": 1, "maximum": 10},
                    "thesis": {"type": "string"},
                    "technical_basis": {"type": ["string", "null"]},
                    "liquidity_tier": {"type": ["string", "null"]},
                    "expected_move_pct": {"type": ["number", "null"]},
                    "fee_hurdle_pct": {"type": ["number", "null"]},
                    "net_expected_pct": {"type": "number"},
                    "risk_or_invalidation": {"type": ["string", "null"]},
                    "time_horizon": {"type": "string"},
                    "target_exit_date": {"type": ["string", "null"]},
                    "price_target_low_pct": {"type": ["number", "null"]},
                    "price_target_high_pct": {"type": ["number", "null"]},
                    "risk_controls": {
                        "type": ["object", "null"],
                        "properties": {
                            "entry_zone_low_pct": {"type": ["number", "null"]},
                            "entry_zone_high_pct": {"type": ["number", "null"]},
                            "stop_loss_pct": {"type": ["number", "null"]},
                            "take_profit_pct": {"type": ["number", "null"]},
                        },
                        "additionalProperties": True,
                    },
                    "catalyst_verified": {"type": ["boolean", "null"]},
                    "catalyst_source": {"type": ["string", "null"]},
                    "manual_review_required": {"type": ["boolean", "null"]},
                    "hold_tier": {"type": ["string", "null"]},
                    "earnings_alert": {"type": ["boolean", "null"]},
                },
                "additionalProperties": True,
            },
        },
        "watchlist_flags": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "why_noteworthy": {"type": "string"},
                },
                "additionalProperties": True,
            },
        },
        "sector_warnings": {"type": "array", "items": {"type": "string"}},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": True,
}


def normalize_recommendation(recommendation: dict) -> dict:
    """Normalize model output before it is logged or rendered."""
    for rec in recommendation.get("recommendations", []) or []:
        if rec.get("ticker"):
            rec["ticker"] = str(rec["ticker"]).upper()
        rec.setdefault("ticker", "UNKNOWN")
        if rec.get("action") not in {"BUY", "SELL", "HOLD", "TRIM", "ADD"}:
            rec["action"] = "HOLD"
        rec.setdefault("conviction", 5)
        rec.setdefault("thesis", "No thesis provided by model.")
        rec.setdefault("net_expected_pct", 0)
        rec.setdefault("fee_hurdle_pct", 0)
        rec.setdefault("time_horizon", "1-3 months")
        low = rec.get("price_target_low_pct")
        high = rec.get("price_target_high_pct")
        if low is not None and high is not None and low > high:
            rec["range_was_normalized"] = True
            rec["price_target_low_pct"], rec["price_target_high_pct"] = high, low
        controls = rec.get("risk_controls")
        if not isinstance(controls, dict):
            controls = {}
        rec["risk_controls"] = {
            "entry_zone_low_pct": controls.get("entry_zone_low_pct"),
            "entry_zone_high_pct": controls.get("entry_zone_high_pct"),
            "stop_loss_pct": controls.get("stop_loss_pct"),
            "take_profit_pct": controls.get("take_profit_pct"),
            **{k: v for k, v in controls.items() if k not in {
                "entry_zone_low_pct", "entry_zone_high_pct", "stop_loss_pct", "take_profit_pct",
            }},
        }
        rec.setdefault("catalyst_verified", False)
        rec.setdefault("catalyst_source", None)
        rec.setdefault("manual_review_required", False)
        if rec.get("action") == "HOLD" and not rec.get("hold_tier"):
            rec["hold_tier"] = "watch"
    recommendation.setdefault("hedge_suggestions", [])
    return recommendation


def _format_indicators_line(ind: dict) -> str:
    """Format technical indicators dict as a single readable line."""
    if not ind:
        return ""
    parts = []
    if ind.get("rsi_14") is not None:
        parts.append(f"RSI={ind['rsi_14']:.1f}")
    if ind.get("macd_hist") is not None:
        parts.append(f"MACD_hist={ind['macd_hist']:+.3f}")
    if ind.get("bb_pct") is not None:
        parts.append(f"BB%={ind['bb_pct']:.2f}")
    if ind.get("price_vs_sma50_pct") is not None:
        parts.append(f"px/SMA50={ind['price_vs_sma50_pct']:+.1f}%")
    if ind.get("price_vs_sma200_pct") is not None:
        parts.append(f"px/SMA200={ind['price_vs_sma200_pct']:+.1f}%")
    if ind.get("sma_50_above_200") is not None:
        parts.append(f"SMA50>SMA200={bool(ind['sma_50_above_200'])}")
    if ind.get("atr_pct_of_price") is not None:
        parts.append(f"ATR14={ind['atr_pct_of_price']:.1f}%")
    if ind.get("volatility_20d_pct") is not None:
        parts.append(f"20d_vol={ind['volatility_20d_pct']:.1f}%")
    if ind.get("volume_spike_ratio") is not None:
        parts.append(f"vol×{ind['volume_spike_ratio']:.2f}")
    return " | ".join(parts)


def _format_sentiment_line(aggregate: dict) -> str:
    if not aggregate or aggregate.get("article_count", 0) == 0:
        return ""
    return (
        f"sentiment avg={aggregate['avg_sentiment']:+.2f} "
        f"[{aggregate['bullish_count']}🟢 / {aggregate['neutral_count']}⚪ / "
        f"{aggregate['bearish_count']}🔴]"
    )


def _format_previous_session(previous_session: dict | None) -> list[str]:
    if not previous_session:
        return []
    lines = [
        "\n=== PREVIOUS SESSION RECOMMENDATIONS ===",
        f"Source log: {previous_session.get('_session_file', 'unknown')}",
    ]
    for rec in (previous_session.get("recommendations") or [])[:12]:
        lines.append(
            f"  {rec.get('ticker', '')}: {rec.get('action', '')} "
            f"conviction={rec.get('conviction', 'N/A')} "
            f"net={rec.get('net_expected_pct', 'N/A')}% "
            f"horizon={rec.get('time_horizon', 'N/A')}"
        )
    return lines


def _format_risk_dashboard(risk_dashboard: dict | None) -> list[str]:
    if not risk_dashboard:
        return []
    lines = ["\n=== PORTFOLIO RISK DASHBOARD ==="]
    if risk_dashboard.get("annualized_volatility_pct") is not None:
        lines.append(f"Annualized volatility estimate: {risk_dashboard['annualized_volatility_pct']:.1f}%")
    if risk_dashboard.get("max_drawdown_estimate_pct") is not None:
        lines.append(f"Max drawdown estimate from available history: {risk_dashboard['max_drawdown_estimate_pct']:.1f}%")
    if risk_dashboard.get("top3_concentration_pct") is not None:
        lines.append(f"Top-3 concentration: {risk_dashboard['top3_concentration_pct']:.1f}%")
    beta = risk_dashboard.get("beta") or {}
    if beta:
        lines.append("Beta estimates: " + ", ".join(f"{k}={v:.2f}" for k, v in beta.items()))
    pairs = risk_dashboard.get("correlated_pairs") or []
    if pairs:
        lines.append(
            "Highly correlated pairs: "
            + ", ".join(f"{p['pair']} ({p['correlation']:+.2f})" for p in pairs)
        )
    return lines


def _format_company_exposure(company_exposure: dict | None) -> list[str]:
    if not company_exposure:
        return []
    lines = ["\n=== COMPANY-LEVEL EXPOSURE ROLLUP ==="]
    for row in list(company_exposure.values())[:12]:
        tickers = ", ".join(row.get("tickers") or [])
        lines.append(
            f"  {row.get('company')}: {row.get('pct', 0):.1f}% "
            f"(${row.get('value_usd', 0):,.0f} USD equiv) via {tickers}"
        )
    return lines


def _format_market_context(market_context: dict | None) -> list[str]:
    if not market_context:
        return []
    lines = ["\n=== SECTOR / CROSS-ASSET CONTEXT ==="]
    for symbol, row in sorted(market_context.items()):
        if row.get("error"):
            lines.append(f"  {symbol}: ERROR - {row['error']}")
            continue
        lines.append(
            f"  {symbol}: ${row.get('current_price', 'N/A')} | "
            f"5d={row.get('change_pct_5d', 'N/A')}% | "
            f"1mo={row.get('change_pct_21d', row.get('change_pct_20d', 'N/A'))}% | "
            f"source={row.get('quote_source', 'N/A')}"
        )
    return lines


def _market_phase(now_dt: datetime) -> str:
    market_open = now_dt.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_dt.replace(hour=16, minute=0, second=0, microsecond=0)
    if now_dt < market_open:
        return "outside regular market hours — before next open"
    if now_dt >= market_close:
        return "after regular market close"
    return "regular session or pre-close"


def build_user_message(
    session_type: str,
    portfolio: dict,
    market_data: dict,
    news_by_ticker: dict,
    fee_snapshot: dict,
    settings: dict,
    recent_activities: list = None,
    sector_exposure: dict = None,
    backtest_summary: dict = None,
    price_alerts: list = None,
    drift: list = None,
    enriched: dict = None,
    previous_session: dict = None,
    risk_dashboard: dict = None,
    company_exposure: dict = None,
    market_context: dict = None,
    hedge_suggestions: list = None,
) -> str:
    """Construct the full user message with all context."""
    from src.news_fetcher import aggregate_sentiment

    now_dt = datetime.now()
    now = now_dt.strftime("%Y-%m-%d %H:%M")
    market_phase = _market_phase(now_dt)
    budget_cad = settings.get("budget_cad", 0)
    budget_usd = settings.get("budget_usd", 0)
    news_by_ticker = news_by_ticker or {}

    holdings = portfolio.get("holdings", [])
    cash_cad = portfolio.get("cash_cad", 0)
    exported_at = portfolio.get("exported_at", "")

    budget_lines = []
    if budget_usd:
        budget_lines.append(f"Available to invest (USD): ${budget_usd:,.2f}")
    if budget_cad:
        budget_lines.append(f"Available to invest (CAD): ${budget_cad:,.2f}")
    if not budget_lines:
        budget_lines.append("Available to invest: $0 (observation only — no new capital this session)")

    lines = [
        f"SESSION TYPE: {session_type.upper()}",
        f"TIMESTAMP: {now}",
        f"MARKET PHASE: {market_phase}",
        "",
        "=== PORTFOLIO ===",
        f"Portfolio snapshot: {exported_at}" if exported_at else "",
        f"Cash (CASH ETF): ${cash_cad:,.2f} CAD",
    ] + budget_lines + [
        f"Risk tolerance: {settings.get('risk_tolerance', 'aggressive')}",
        f"Account: {settings.get('account_type', 'wealthsimple_premium_usd')}",
        "",
    ]

    if holdings:
        usd_holdings = [h for h in holdings if not h.get("is_cdr") and h.get("market_currency") == "USD"]
        cad_holdings = [h for h in holdings if h.get("is_cdr") or h.get("market_currency") == "CAD"]

        if usd_holdings:
            lines.append("USD Holdings:")
            for h in usd_holdings:
                ticker = h.get("ticker", "")
                qty = h.get("quantity", 0)
                avg = h.get("avg_cost_market")
                price = h.get("market_price")
                pnl_pct = h.get("unrealized_pnl_pct")
                pnl = h.get("unrealized_pnl")
                mv = h.get("market_value")
                pnl_str = f" | P&L {pnl_pct:+.1f}% (${pnl:+.0f})" if pnl_pct is not None else ""
                avg_str = f"avg ${avg:.2f}" if avg else ""
                price_str = f"now ${price:.2f}" if price else ""
                mv_str = f"value ${mv:,.0f}" if mv else ""
                lines.append(
                    f"  {ticker:8s} {qty:8.4f} sh | {avg_str} | {price_str} | {mv_str}{pnl_str}"
                )

        if cad_holdings:
            lines.append("\nCAD/CDR Holdings:")
            for h in cad_holdings:
                ticker = h.get("ticker", "")
                name = h.get("name", "")
                qty = h.get("quantity", 0)
                avg = h.get("avg_cost_market")
                price = h.get("market_price")
                pnl_pct = h.get("unrealized_pnl_pct")
                pnl = h.get("unrealized_pnl")
                cdr_flag = " [CDR]" if h.get("is_cdr") and "CDR" in name else ""
                pnl_str = f" | P&L {pnl_pct:+.1f}% (${pnl:+.0f} CAD)" if pnl_pct is not None else ""
                avg_str = f"avg ${avg:.2f} CAD" if avg else ""
                price_str = f"now ${price:.2f} CAD" if price else ""
                lines.append(
                    f"  {ticker:8s}{cdr_flag:6s} {qty:8.4f} sh | {avg_str} | {price_str}{pnl_str}"
                )
    else:
        lines.append("No current holdings — all cash.")

    # ── Sector exposure (if provided) ──────────────────────────────────────
    if sector_exposure:
        lines.append("\n=== SECTOR EXPOSURE (% of portfolio value) ===")
        threshold = settings.get("sector_concentration_threshold_pct", 40)
        for sector, data in sector_exposure.items():
            flag = "  ⚠️ CONCENTRATED" if data["pct"] > threshold else ""
            tickers_str = ", ".join(data["tickers"][:6])
            lines.append(
                f"  {sector:22s} {data['pct']:5.1f}%  (${data['value_cad']:,.0f} CAD)  "
                f"[{tickers_str}]{flag}"
            )

    lines += _format_company_exposure(company_exposure)
    lines += _format_risk_dashboard(risk_dashboard)
    if hedge_suggestions:
        lines.append("\n=== DETERMINISTIC HEDGE / REBALANCE SUGGESTIONS ===")
        for suggestion in hedge_suggestions:
            lines.append(
                f"  {suggestion.get('instrument')}: {suggestion.get('action')} "
                f"cap={suggestion.get('max_portfolio_pct', 'N/A')}% - "
                f"{suggestion.get('rationale', '')} Risk: {suggestion.get('risk_note', '')}"
            )

    # ── Market data + indicators ──────────────────────────────────────────
    lines.append("\n=== MARKET DATA (price + technical indicators) ===")
    for ticker, d in market_data.items():
        if d.get("error"):
            lines.append(f"{ticker}: ERROR — {d['error']}")
            continue
        hist = d.get("history", [])
        recent = hist[-5:] if hist else []
        recent_closes = ", ".join(f"${r['close']:.2f}" for r in recent)

        change_1d = d.get("change_pct_1d")
        change_5d = d.get("change_pct_5d")
        change_1mo = d.get("change_pct_1mo")
        pct_high = d.get("pct_from_52w_high")

        # Build summary string safely
        parts = [f"{ticker}: ${d.get('current_price', 'N/A')} {d.get('currency', '')}"]
        if d.get("previous_close") is not None:
            parts.append(f"prev_close=${d['previous_close']:.2f}")
        if change_1d is not None:
            parts.append(f"1d={change_1d:+.1f}%")
        if d.get("pre_market_change_pct") is not None:
            parts.append(f"premarket={d['pre_market_change_pct']:+.1f}%")
        if d.get("post_market_change_pct") is not None:
            parts.append(f"afterhours={d['post_market_change_pct']:+.1f}%")
        if change_5d is not None:
            parts.append(f"5d={change_5d:+.1f}%")
        if change_1mo is not None:
            parts.append(f"1mo={change_1mo:+.1f}%")
        if pct_high is not None:
            parts.append(f"from 52w-high={pct_high:+.1f}%")
        if d.get("pe_ratio") is not None:
            parts.append(f"PE={d['pe_ratio']}")
        if d.get("forward_pe") is not None:
            parts.append(f"fwdPE={d['forward_pe']}")
        if d.get("price_to_sales") is not None:
            parts.append(f"P/S={d['price_to_sales']}")
        if d.get("enterprise_to_ebitda") is not None:
            parts.append(f"EV/EBITDA={d['enterprise_to_ebitda']}")
        if d.get("free_cashflow_yield_pct") is not None:
            parts.append(f"FCF_yield={d['free_cashflow_yield_pct']:+.1f}%")
        if d.get("gross_margin_pct") is not None:
            parts.append(f"gross_margin={d['gross_margin_pct']:.1f}%")
        if d.get("operating_margin_pct") is not None:
            parts.append(f"operating_margin={d['operating_margin_pct']:.1f}%")
        if d.get("ex_dividend_date"):
            parts.append(f"ex_dividend={d['ex_dividend_date'][:10]}")
        if d.get("sector"):
            parts.append(f"sector={d['sector']}")
        if d.get("quote_timestamp_utc"):
            parts.append(f"quote_time_utc={d['quote_timestamp_utc']}")
        if d.get("quote_source"):
            parts.append(f"source={d['quote_source']}")
        if d.get("price_basis"):
            parts.append(f"price_basis={d['price_basis']}")
        lines.append(" | ".join(parts))

        ind_line = _format_indicators_line(d.get("indicators") or {})
        if ind_line:
            lines.append(f"  INDICATORS: {ind_line}")
        options_move = d.get("options_implied_move")
        if options_move:
            lines.append(
                "  OPTIONS IMPLIED MOVE: "
                f"{options_move.get('implied_move_pct')}% by {options_move.get('expiry')} "
                f"(ATM {options_move.get('atm_strike')}, source={options_move.get('source')})"
            )
        lines.append(f"  Last 5 closes: {recent_closes}")

    lines += _format_market_context(market_context)

    # ── Mandatory catalyst check for large movers ─────────────────────────
    catalyst_threshold = settings.get("news_catalyst_move_threshold_pct", 5)
    large_movers = []
    for ticker, d in market_data.items():
        move = d.get("change_pct_1d")
        if move is not None and abs(move) >= catalyst_threshold:
            large_movers.append((ticker, move))
    if large_movers:
        lines.append(f"\n=== LARGE-MOVE CATALYST CHECK REQUIRED (>|{catalyst_threshold:.0f}%| 1D) ===")
        for ticker, move in sorted(large_movers, key=lambda x: -abs(x[1])):
            articles = news_by_ticker.get(ticker) or []
            top = next((a for a in articles if a.get("title")), None)
            if top:
                lines.append(
                    f"  {ticker}: {move:+.1f}% — top headline: "
                    f"{top.get('title')} ({top.get('publisher', 'source unknown')}, "
                    f"{top.get('published_at', 'time unknown')})"
                )
            else:
                lines.append(f"  {ticker}: {move:+.1f}% — NO VERIFIED CATALYST FOUND in news feed")

    # ── Price alerts from watchlist ────────────────────────────────────────
    if price_alerts:
        lines.append("\n=== WATCHLIST PRICE ALERTS ===")
        for a in price_alerts:
            lines.append(f"  {a['ticker']}: {a['message']}")

    if recent_activities:
        from src.activity_loader import format_activities_for_prompt
        lines.append("\n=== RECENT TRADE HISTORY (last 90 days) ===")
        lines.append(format_activities_for_prompt(recent_activities))

    lines += _format_previous_session(previous_session)

    # ── Track record (from backtester) ─────────────────────────────────────
    if backtest_summary and backtest_summary.get("n_samples", 0) > 0:
        lines.append("\n=== YOUR PAST TRACK RECORD (from recommendation logs) ===")
        lines.append(f"  Samples: {backtest_summary['n_samples']} recommendations evaluated")
        by_action = backtest_summary.get("avg_return_by_action", {})
        if by_action:
            lines.append("  Avg actual return by action:")
            for action, stats in by_action.items():
                lines.append(f"    {action:6s} n={stats['n']:3d} avg={stats['avg_return_pct']:+.2f}%  win_rate={stats['hit_rate']:.0%}")
        by_conv = backtest_summary.get("avg_return_by_conviction", {})
        if by_conv:
            lines.append("  Avg actual return by conviction score:")
            for conv in sorted(by_conv.keys()):
                stats = by_conv[conv]
                lines.append(f"    conviction={conv}  n={stats['n']:3d}  avg={stats['avg_return_pct']:+.2f}%  win_rate={stats['hit_rate']:.0%}")
        by_ticker = backtest_summary.get("avg_return_by_ticker", {})
        if by_ticker:
            lines.append("  Avg actual return by ticker:")
            for ticker, stats in list(by_ticker.items())[:10]:
                lines.append(f"    {ticker:8s} n={stats['n']:3d} avg={stats['avg_return_pct']:+.2f}% win_rate={stats['hit_rate']:.0%}")
        examples = backtest_summary.get("recent_realized_examples", [])
        if examples:
            lines.append("  Recent realized examples to calibrate today's recommendations:")
            for row in examples[:5]:
                lines.append(
                    f"    {row.get('session_date')} {row.get('ticker')} {row.get('action')} "
                    f"conv={row.get('conviction')} expected={row.get('expected_pct'):+.2f}% "
                    f"actual={row.get('actual_pct'):+.2f}% hit={row.get('hit')}"
                )
        lines.append("  ↳ Use this to calibrate conviction scores this session.")

    # ── Drift from previous session ────────────────────────────────────────
    if drift:
        lines.append("\n=== DRIFT SINCE LAST SESSION ===")
        for d in drift:
            lines.append(
                f"  {d['ticker']}: {d['drift_type']} — "
                f"was {d['was']['action']}/{d['was']['conviction']}, "
                f"now {d['now']['action']}/{d['now']['conviction']}"
            )

    lines.append("\n=== FEE SNAPSHOT (round-trip cost per $1000 notional) ===")
    fee_model = settings.get("fee_model", {})
    lines.append(
        "Fee assumptions: "
        f"account={settings.get('account_type', 'wealthsimple_premium_usd')}; "
        f"commission=${fee_model.get('commission', 0):.2f}; "
        f"fx_spread_in_hurdle={fee_model.get('fx_spread_pct', 0):.2f}%; "
        "USD-account trades assume USD cash is available; CAD→USD conversion is not included unless cash must be converted."
    )
    for ticker, fees in fee_snapshot.items():
        lines.append(
            f"{ticker}: hurdle={fees['hurdle_pct']:.3f}% | "
            f"bid-ask(one-way)={fees['bid_ask_pct_one_way']:.2f}% | "
            f"total=${fees['total_usd']:.3f}"
        )

    # ── News + sentiment ───────────────────────────────────────────────────
    lines.append("\n=== RECENT NEWS (last 7 days, with sentiment) ===")
    for ticker, articles in news_by_ticker.items():
        lines.append(f"\n{ticker}:")
        if not articles:
            lines.append("  No recent news.")
            continue
        agg = aggregate_sentiment(articles)
        sent_line = _format_sentiment_line(agg)
        if sent_line:
            lines.append(f"  [{sent_line}]")
        for a in articles[:4]:
            senti = f" ({a['sentiment']:+.2f})" if "sentiment" in a else ""
            lines.append(f"  [{a.get('published_at', '')}] {a.get('title', '')}{senti}")
            if a.get("summary"):
                lines.append(f"    {a['summary'][:200]}")

    # ── Enriched intelligence (Finnhub, Polygon, FRED, CoinGecko, etc.) ──────
    if enriched:
        from src.enriched_data import format_enrichment_for_prompt
        enrichment_block = format_enrichment_for_prompt(enriched)
        if enrichment_block:
            lines.append(enrichment_block)

    lines.append(
        f"\n\nNow provide your recommendation JSON. Remember: only recommend trading if "
        f"net_expected_pct > {settings.get('min_net_expected_return_pct', 0.5)}% and conviction >= 6. "
        f"Use the TECHNICAL INDICATORS, ANALYST CONSENSUS, OPTIONS FLOW, MACRO CONTEXT, "
        f"RISK DASHBOARD, COMPANY EXPOSURE, and TRACK RECORD above to calibrate. "
        f"Populate risk_controls, catalyst fields, hedge_suggestions, and decision-tree wording. "
        f"Keep recommendations compact: at most 12 rows, focused on actionable trades and material risks."
    )

    return "\n".join(lines)


def estimate_cost(usage, model: str) -> dict:
    """Estimate the USD cost of an API call from usage statistics."""
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["claude-sonnet-4-6"])
    M = 1_000_000

    input_cost    = (getattr(usage, "input_tokens", 0) / M) * pricing["input"]
    output_cost   = (getattr(usage, "output_tokens", 0) / M) * pricing["output"]
    cache_w_cost  = (getattr(usage, "cache_creation_input_tokens", 0) / M) * pricing["cache_write"]
    cache_r_cost  = (getattr(usage, "cache_read_input_tokens", 0) / M) * pricing["cache_read"]
    total_cost    = input_cost + output_cost + cache_w_cost + cache_r_cost

    return {
        "input_tokens":        getattr(usage, "input_tokens", 0),
        "output_tokens":       getattr(usage, "output_tokens", 0),
        "cache_write_tokens":  getattr(usage, "cache_creation_input_tokens", 0),
        "cache_read_tokens":   getattr(usage, "cache_read_input_tokens", 0),
        "total_tokens":        (getattr(usage, "input_tokens", 0)
                                + getattr(usage, "output_tokens", 0)),
        "cost_usd":            round(total_cost, 4),
        "cache_hit":           getattr(usage, "cache_read_input_tokens", 0) > 0,
    }


def _strip_json_fences(raw_text: str) -> str:
    raw_text = (raw_text or "").strip()
    if raw_text.startswith("```"):
        lines_raw = raw_text.split("\n")
        raw_text = "\n".join(lines_raw[1:-1] if lines_raw[-1].strip() == "```" else lines_raw[1:])
    return raw_text.strip()


def _parse_validate_recommendation(raw_text: str) -> dict:
    raw_text = _strip_json_fences(raw_text)
    try:
        recommendation = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Claude returned non-JSON response. Parse error: {e}\n\nRaw response:\n{raw_text[:500]}"
        )

    recommendation = normalize_recommendation(recommendation)

    try:
        jsonschema.validate(recommendation, RECOMMENDATION_SCHEMA)
    except jsonschema.ValidationError as e:
        path = " -> ".join(str(p) for p in e.absolute_path) or "<root>"
        raise ValueError(
            f"Claude response failed schema validation at {path}: {e.message}"
        )

    return recommendation


def _response_text(response) -> str:
    """Extract text blocks from an Anthropic response, ignoring thinking blocks."""
    texts = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text" and getattr(block, "text", None):
            texts.append(block.text)
        elif getattr(block, "text", None):
            texts.append(block.text)
    return "\n".join(texts)


def _cacheable_text_block(text: str) -> dict:
    """Attach an Anthropic ephemeral cache breakpoint to a repeated user block."""
    return {
        "type": "text",
        "text": text,
        "cache_control": {"type": "ephemeral", "ttl": "1h"},
    }


def _create_message(client, model: str, settings: dict, messages: list[dict]):
    """Call Anthropic with the cacheable system prompt."""
    max_tokens = settings.get("claude_max_tokens", 20000)
    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "system": [
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral", "ttl": "1h"},
            }
        ],
        "messages": messages,
    }
    if "opus" in model.lower() and settings.get("enable_opus_extended_thinking", True):
        budget = min(int(settings.get("opus_thinking_budget_tokens", 4096)), max_tokens - 1024)
        if budget >= 1024:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
    return client.messages.create(**kwargs)


def _combine_usage_stats(first: dict, second: dict | None) -> dict:
    """Aggregate cost/tokens across the two Claude passes."""
    if not second:
        out = deepcopy(first)
        out["passes"] = 1
        out["first_pass"] = first
        return out

    out = {
        "input_tokens": first.get("input_tokens", 0) + second.get("input_tokens", 0),
        "output_tokens": first.get("output_tokens", 0) + second.get("output_tokens", 0),
        "cache_write_tokens": first.get("cache_write_tokens", 0) + second.get("cache_write_tokens", 0),
        "cache_read_tokens": first.get("cache_read_tokens", 0) + second.get("cache_read_tokens", 0),
        "total_tokens": first.get("total_tokens", 0) + second.get("total_tokens", 0),
        "cost_usd": round(first.get("cost_usd", 0) + second.get("cost_usd", 0), 4),
        "cache_hit": bool(first.get("cache_hit") or second.get("cache_hit")),
        "passes": 2,
        "first_pass": first,
        "second_pass": second,
    }
    return out


def _build_review_message(
    first_recommendation: dict,
    quality_warnings: list[dict],
    drift: list[dict],
    previous_session: dict | None,
) -> str:
    previous_meta = {
        "source": (previous_session or {}).get("_session_file"),
        "recommendations": (previous_session or {}).get("recommendations", [])[:12],
    }
    return "\n".join([
        "SECOND PASS QUALITY REVIEW.",
        "Revise the recommendation JSON using the deterministic warnings and drift below.",
        "Return one complete valid JSON object only, using the same schema.",
        "Hard requirements:",
        "- Fix or explicitly surface every high/medium quality warning.",
        "- Downgrade BUY/ADD to HOLD when catalyst verification is missing.",
        "- Keep risk_controls, catalyst fields, hedge_suggestions, and decision-tree wording populated.",
        "- Preserve useful recommendations, but reduce unsupported drift versus the previous session.",
        "",
        "FIRST_PASS_JSON:",
        json.dumps(first_recommendation, indent=2, default=str),
        "",
        "QUALITY_WARNINGS_JSON:",
        json.dumps(quality_warnings, indent=2, default=str),
        "",
        "DRIFT_VS_PREVIOUS_JSON:",
        json.dumps(drift, indent=2, default=str),
        "",
        "PREVIOUS_SESSION_CONTEXT_JSON:",
        json.dumps(previous_meta, indent=2, default=str),
    ])


def call_claude(
    session_type: str,
    portfolio: dict,
    market_data: dict,
    news_by_ticker: dict,
    fee_snapshot: dict,
    recent_activities: list = None,
    settings_override: dict = None,
    sector_exposure: dict = None,
    backtest_summary: dict = None,
    price_alerts: list = None,
    drift: list = None,
    enriched: dict = None,
    previous_session: dict = None,
    risk_dashboard: dict = None,
    company_exposure: dict = None,
    market_context: dict = None,
    hedge_suggestions: list = None,
) -> tuple[dict, dict]:
    """
    Call Claude API and return (recommendation, usage_stats).
    Raises ValueError if response cannot be parsed or fails schema validation.
    settings_override: merged on top of settings.json (used by interactive mode).
    """
    settings = load_settings()
    if settings_override:
        settings.update(settings_override)
    model = settings.get("claude_model", "claude-sonnet-4-6")

    deterministic_hedges = hedge_suggestions
    if deterministic_hedges is None:
        deterministic_hedges = build_hedge_suggestions(risk_dashboard or {}, company_exposure or {}, settings)

    user_message = build_user_message(
        session_type, portfolio, market_data, news_by_ticker, fee_snapshot, settings,
        recent_activities=recent_activities,
        sector_exposure=sector_exposure,
        backtest_summary=backtest_summary,
        price_alerts=price_alerts,
        drift=drift,
        enriched=enriched,
        previous_session=previous_session,
        risk_dashboard=risk_dashboard,
        company_exposure=company_exposure,
        market_context=market_context,
        hedge_suggestions=deterministic_hedges,
    )

    client = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        timeout=settings.get("claude_timeout_seconds", 240),
    )

    # Pass 1: produce the initial recommendation JSON.
    first_response = _create_message(
        client,
        model,
        settings,
        [{"role": "user", "content": [_cacheable_text_block(user_message)]}],
    )
    first_recommendation = _parse_validate_recommendation(_response_text(first_response))
    first_usage = estimate_cost(first_response.usage, model)

    first_drift = compute_drift(
        first_recommendation,
        previous_session,
        conviction_delta_threshold=settings.get("drift_conviction_delta", 2),
    )
    first_warnings = evaluate_report_quality(
        first_recommendation,
        market_data,
        portfolio=portfolio,
        news_by_ticker=news_by_ticker,
        enriched=enriched,
        settings=settings,
    )

    # Pass 2: always-on critique/revision using deterministic warnings and drift.
    review_message = _build_review_message(
        first_recommendation,
        first_warnings,
        first_drift,
        previous_session,
    )
    second_response = _create_message(
        client,
        model,
        settings,
        [
            {"role": "user", "content": [_cacheable_text_block(user_message)]},
            {"role": "user", "content": review_message},
        ],
    )
    recommendation = _parse_validate_recommendation(_response_text(second_response))
    second_usage = estimate_cost(second_response.usage, model)

    final_drift = compute_drift(
        recommendation,
        previous_session,
        conviction_delta_threshold=settings.get("drift_conviction_delta", 2),
    )
    final_warnings = evaluate_report_quality(
        recommendation,
        market_data,
        portfolio=portfolio,
        news_by_ticker=news_by_ticker,
        enriched=enriched,
        settings=settings,
    )

    recommendation = apply_quality_gates(recommendation, final_warnings)
    recommendation["review_passes"] = 2
    recommendation["drift_vs_previous"] = final_drift
    recommendation["first_pass_quality_warnings"] = first_warnings
    recommendation["first_pass_drift_vs_previous"] = first_drift
    recommendation["quality_warnings"] = recommendation.get("quality_warnings") or final_warnings

    ph = recommendation.setdefault("portfolio_health", {})
    if risk_dashboard:
        ph["risk_dashboard"] = risk_dashboard
    if deterministic_hedges and not recommendation.get("hedge_suggestions"):
        recommendation["hedge_suggestions"] = deterministic_hedges

    usage_stats = _combine_usage_stats(first_usage, second_usage)
    recommendation["usage_summary"] = {
        "passes": usage_stats.get("passes"),
        "total_tokens": usage_stats.get("total_tokens"),
        "cost_usd": usage_stats.get("cost_usd"),
    }
    return recommendation, usage_stats
