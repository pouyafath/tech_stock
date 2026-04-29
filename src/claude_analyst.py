"""
claude_analyst.py
Builds the structured prompt, calls the Claude API, parses and validates
the JSON response. Prompt caching is applied to the system prompt to
reduce costs on repeated runs.
"""

import json
import os
from datetime import datetime
from pathlib import Path

import anthropic
import jsonschema
from dotenv import load_dotenv

from src.config import load_settings

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
14. TRACK RECORD CALIBRATION: Use provided track record to calibrate conviction. If past conviction-9 averaged +2.8% but conviction-7 averaged +0.3%, reflect that in scoring.
15. EARNINGS ALERT: If enrichment data shows a ticker has earnings within 7 days, set earnings_alert=true and lead the thesis with "⚠️ EARNINGS [DATE] [BMO/AMC]". Earnings change the risk profile — do not ADD into earnings without explicitly stating why you expect a beat.
16. ETF SECTOR CLASSIFICATION: ARK ETFs (ARKF, ARKK, ARKQ, ARKG) = ~90% technology — count toward tech concentration. VGRO/XEQT/VEQT/VCNS = balanced multi-sector, count separately. SOXL = 3× semiconductors. TQQQ = 3× QQQ tech-heavy. Use these when calculating real sector concentration.
17. ENRICHMENT CITATION: When analyst_consensus is available, cite it in the thesis (e.g., "66 analysts: STRONG BUY"). When earnings_history shows 3+ consecutive beats, say "beat estimates X quarters in a row". When insider_activity shows net buying/selling of significance, mention it. Do not silently ignore enrichment data.
18. INVESTMENT SIZING (FRACTIONAL SHARES): For BUY/ADD, set invest_amount_usd based on the session budget (USD available, shown in PORTFOLIO): conviction 8–10 = up to 40% of budget, conviction 7 = 25%, conviction 6 = 15%. Cap at the position limit. Express as a dollar amount — the investor will buy fractional shares automatically through Wealthsimple.
19. HOLD TIERS — add hold_tier to every HOLD: "watch" (conviction ≤5: monitoring for deterioration/exit opportunity), "keep" (conviction 6–7: comfortable, no action needed), "add_on_dip" (conviction ≥8: would buy more if budget or price dipped).
20. TIME HORIZONS: Use exactly one of: "intraday" / "1-2 weeks" / "1-3 months" / "3-6 months" / "6-12 months" / "12-36 months". Match to the actual thesis — a mean-reversion trade is 1-3 months, a fundamental growth story is 12-36 months.
21. TARGET EXIT & PRICE RANGE: For every recommendation (including HOLDs), provide: target_exit_date (e.g., "Jul 2026"), price_target_low_pct (conservative % move over holding period), price_target_high_pct (optimistic % move). These must be consistent with time_horizon.
22. BUY SIGNALS: Actively look for BUY opportunities — not just in the existing portfolio. If a watchlist ticker or a ticker mentioned in news is setting up well (RSI recovering, catalyst, analyst upgrades), recommend BUY with invest_amount_usd. Don't only HOLD; find the best 1-2 buys per session if any exist.
23. PRIORITY ACTIONS: Output priority_actions — an ordered list of what to execute today. Only include BUY/SELL/TRIM/ADD. Order by urgency (intraday first, then short-term). HOLDs are never in this list.

OUTPUT FORMAT (return exactly this structure):
{
  "session_summary": "1-2 sentence overview of market context and your overall read",
  "portfolio_health": {
    "total_value_usd_equivalent": <number>,
    "overall_pnl_pct": <number>,
    "concentration_risk": "low|medium|high",
    "cash_deployment": "string"
  },
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
      "time_horizon": "intraday|1-2 weeks|1-3 months|3-6 months|6-12 months|12-36 months",
      "target_exit_date": "string or null (e.g. Jul 2026)",
      "price_target_low_pct": <number or null>,
      "price_target_high_pct": <number or null>,
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
            },
            "additionalProperties": True,
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
        low = rec.get("price_target_low_pct")
        high = rec.get("price_target_high_pct")
        if low is not None and high is not None and low > high:
            rec["price_target_low_pct"], rec["price_target_high_pct"] = high, low
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
) -> str:
    """Construct the full user message with all context."""
    from src.news_fetcher import aggregate_sentiment

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    budget_cad = settings.get("budget_cad", 0)
    budget_usd = settings.get("budget_usd", 0)

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
        if change_1d is not None:
            parts.append(f"1d={change_1d:+.1f}%")
        if change_5d is not None:
            parts.append(f"5d={change_5d:+.1f}%")
        if change_1mo is not None:
            parts.append(f"1mo={change_1mo:+.1f}%")
        if pct_high is not None:
            parts.append(f"from 52w-high={pct_high:+.1f}%")
        if d.get("pe_ratio") is not None:
            parts.append(f"PE={d['pe_ratio']}")
        if d.get("sector"):
            parts.append(f"sector={d['sector']}")
        lines.append(" | ".join(parts))

        ind_line = _format_indicators_line(d.get("indicators") or {})
        if ind_line:
            lines.append(f"  INDICATORS: {ind_line}")
        lines.append(f"  Last 5 closes: {recent_closes}")

    # ── Price alerts from watchlist ────────────────────────────────────────
    if price_alerts:
        lines.append("\n=== WATCHLIST PRICE ALERTS ===")
        for a in price_alerts:
            lines.append(f"  {a['ticker']}: {a['message']}")

    if recent_activities:
        from src.activity_loader import format_activities_for_prompt
        lines.append("\n=== RECENT TRADE HISTORY (last 90 days) ===")
        lines.append(format_activities_for_prompt(recent_activities))

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
        f"and TRACK RECORD above to calibrate."
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

    user_message = build_user_message(
        session_type, portfolio, market_data, news_by_ticker, fee_snapshot, settings,
        recent_activities=recent_activities,
        sector_exposure=sector_exposure,
        backtest_summary=backtest_summary,
        price_alerts=price_alerts,
        drift=drift,
        enriched=enriched,
    )

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    # Cache the system prompt with 1h TTL — saves ~90% on repeated runs within an hour.
    response = client.messages.create(
        model=model,
        max_tokens=settings.get("claude_max_tokens", 20000),
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral", "ttl": "1h"},
            }
        ],
        messages=[{"role": "user", "content": user_message}],
    )

    raw_text = response.content[0].text.strip()

    # Strip markdown fences if Claude added them despite instructions
    if raw_text.startswith("```"):
        lines_raw = raw_text.split("\n")
        raw_text = "\n".join(lines_raw[1:-1] if lines_raw[-1].strip() == "```" else lines_raw[1:])

    try:
        recommendation = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Claude returned non-JSON response. Parse error: {e}\n\nRaw response:\n{raw_text[:500]}"
        )

    # ── Schema validation ────────────────────────────────────────────────
    try:
        jsonschema.validate(recommendation, RECOMMENDATION_SCHEMA)
    except jsonschema.ValidationError as e:
        path = " → ".join(str(p) for p in e.absolute_path) or "<root>"
        raise ValueError(
            f"Claude response failed schema validation at {path}: {e.message}"
        )

    recommendation = normalize_recommendation(recommendation)

    usage_stats = estimate_cost(response.usage, model)
    return recommendation, usage_stats
