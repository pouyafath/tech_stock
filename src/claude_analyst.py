"""
claude_analyst.py
Builds the structured prompt, calls the Claude API, and parses the JSON response.
"""

import json
import os
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

SETTINGS_PATH = Path(__file__).parent.parent / "config" / "settings.json"


def load_settings() -> dict:
    with open(SETTINGS_PATH) as f:
        return json.load(f)


SYSTEM_PROMPT = """You are a disciplined, fee-aware portfolio advisor for a Canadian retail investor using Wealthsimple Premium with a USD account.

Your job is to analyze the provided portfolio snapshot, market data, and recent news, then output a structured trading recommendation in valid JSON only.

RULES YOU MUST FOLLOW:
1. FEE DISCIPLINE: Every BUY or ADD recommendation must have net_expected_pct > fee_hurdle_pct. If it doesn't clear the hurdle, output HOLD instead.
2. CONVICTION: Score 1–10. Under 6 = don't recommend trading (output HOLD). Only high-conviction calls get BUY/SELL/TRIM/ADD.
3. THESIS CLARITY: Provide a 2-3 sentence thesis explaining WHY, and a clear invalidation condition (what would prove you wrong).
4. POSITION SIZING: No single position should exceed 25% of total portfolio value.
5. RISK TOLERANCE: Aggressive — it's OK to recommend high-volatility names (PLTR, SMCI, small-cap AI) alongside megacaps.
6. SESSION AWARENESS: If session_type is "morning", focus on overnight catalysts, premarket moves, and pre-open setup. If "afternoon", focus on intraday action, EOD positioning, and swing trade entries.
7. JSON ONLY: Return ONLY valid JSON. No preamble, no explanation outside JSON, no markdown fences.

OUTPUT FORMAT (return exactly this structure):
{
  "session_summary": "1-2 sentence overview of today's market context and your overall read",
  "portfolio_health": {
    "total_value_usd_equivalent": <number>,
    "overall_pnl_pct": <number>,
    "concentration_risk": "low|medium|high",
    "cash_deployment": "string describing how aggressively cash should be deployed"
  },
  "recommendations": [
    {
      "ticker": "string",
      "action": "BUY|SELL|HOLD|TRIM|ADD",
      "shares": <number or null>,
      "target_entry_or_exit": <number or null>,
      "conviction": <1-10>,
      "thesis": "string",
      "expected_move_pct": <number>,
      "fee_hurdle_pct": <number>,
      "net_expected_pct": <number>,
      "risk_or_invalidation": "string",
      "time_horizon": "intraday|1-2 weeks|1-3 months"
    }
  ],
  "watchlist_flags": [
    {
      "ticker": "string",
      "why_noteworthy": "string"
    }
  ],
  "warnings": ["string"]
}"""


def build_user_message(
    session_type: str,
    portfolio: dict,
    market_data: dict,
    news_by_ticker: dict,
    fee_snapshot: dict,
    settings: dict,
    recent_activities: list = None,
) -> str:
    """Construct the full user message with all context."""
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

    portfolio_lines = [
        f"SESSION TYPE: {session_type.upper()}",
        f"TIMESTAMP: {now}",
        f"",
        f"=== PORTFOLIO ===",
        f"Portfolio snapshot: {exported_at}" if exported_at else "",
        f"Cash (CASH ETF): ${cash_cad:,.2f} CAD",
    ] + budget_lines + [
        f"Risk tolerance: {settings.get('risk_tolerance', 'aggressive')}",
        f"Account: {settings.get('account_type', 'wealthsimple_premium_usd')}",
        f"",
    ]

    if holdings:
        # Group: USD holdings first, then CAD/CDR
        usd_holdings = [h for h in holdings if not h.get("is_cdr") and h.get("market_currency") == "USD"]
        cad_holdings = [h for h in holdings if h.get("is_cdr") or h.get("market_currency") == "CAD"]

        if usd_holdings:
            portfolio_lines.append("USD Holdings:")
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
                portfolio_lines.append(
                    f"  {ticker:8s} {qty:8.4f} sh | {avg_str} | {price_str} | {mv_str}{pnl_str}"
                )

        if cad_holdings:
            portfolio_lines.append("\nCAD/CDR Holdings:")
            for h in cad_holdings:
                ticker = h.get("ticker", "")
                name = h.get("name", "")
                qty = h.get("quantity", 0)
                avg = h.get("avg_cost_market")
                price = h.get("market_price")
                pnl_pct = h.get("unrealized_pnl_pct")
                pnl = h.get("unrealized_pnl")
                mv = h.get("market_value")
                cdr_flag = " [CDR]" if h.get("is_cdr") and "CDR" in name else ""
                pnl_str = f" | P&L {pnl_pct:+.1f}% (${pnl:+.0f} CAD)" if pnl_pct is not None else ""
                avg_str = f"avg ${avg:.2f} CAD" if avg else ""
                price_str = f"now ${price:.2f} CAD" if price else ""
                portfolio_lines.append(
                    f"  {ticker:8s}{cdr_flag:6s} {qty:8.4f} sh | {avg_str} | {price_str}{pnl_str}"
                )
    else:
        portfolio_lines.append("No current holdings — all cash.")

    # Market data section
    portfolio_lines.append("\n=== MARKET DATA ===")
    for ticker, d in market_data.items():
        if d.get("error"):
            portfolio_lines.append(f"{ticker}: ERROR — {d['error']}")
            continue
        hist = d.get("history", [])
        recent = hist[-5:] if hist else []
        recent_closes = ", ".join(f"${r['close']:.2f}" for r in recent)
        portfolio_lines.append(
            f"{ticker}: ${d.get('current_price', 'N/A')} {d.get('currency', '')} | "
            f"1d={d.get('change_pct_1d', 'N/A'):+.1f}% | "
            f"5d={d.get('change_pct_5d', 'N/A'):+.1f}% | "
            f"1mo={d.get('change_pct_1mo', 'N/A'):+.1f}% | "
            f"from 52w-high={d.get('pct_from_52w_high', 'N/A'):+.1f}% | "
            f"PE={d.get('pe_ratio', 'N/A')} | "
            f"Last 5 closes: {recent_closes}"
        )

    # Recent trade activity section
    if recent_activities:
        from src.activity_loader import format_activities_for_prompt
        portfolio_lines.append("\n=== RECENT TRADE HISTORY (last 90 days) ===")
        portfolio_lines.append(format_activities_for_prompt(recent_activities))

    # Fee snapshot section
    portfolio_lines.append("\n=== FEE SNAPSHOT (round-trip cost per $1000 notional) ===")
    for ticker, fees in fee_snapshot.items():
        portfolio_lines.append(
            f"{ticker}: hurdle={fees['hurdle_pct']:.3f}% | "
            f"bid-ask(one-way)={fees['bid_ask_pct_one_way']:.2f}% | "
            f"total=${fees['total_usd']:.3f}"
        )

    # News section
    portfolio_lines.append("\n=== RECENT NEWS (last 7 days) ===")
    for ticker, articles in news_by_ticker.items():
        portfolio_lines.append(f"\n{ticker}:")
        if not articles:
            portfolio_lines.append("  No recent news.")
        else:
            for a in articles[:4]:
                portfolio_lines.append(f"  [{a.get('published_at', '')}] {a.get('title', '')}")
                if a.get("summary"):
                    portfolio_lines.append(f"    {a['summary'][:200]}")

    portfolio_lines.append(
        f"\n\nNow provide your recommendation JSON. Remember: only recommend trading if "
        f"net_expected_pct > {settings.get('min_net_expected_return_pct', 0.5)}% and conviction >= 6."
    )

    return "\n".join(portfolio_lines)


def call_claude(
    session_type: str,
    portfolio: dict,
    market_data: dict,
    news_by_ticker: dict,
    fee_snapshot: dict,
    recent_activities: list = None,
    settings_override: dict = None,
) -> dict:
    """
    Call Claude API and return the parsed JSON recommendation.
    Raises ValueError if response cannot be parsed as valid JSON.
    settings_override: merged on top of settings.json (used by interactive mode).
    """
    settings = load_settings()
    if settings_override:
        settings.update(settings_override)
    model = settings.get("claude_model", "claude-sonnet-4-6")

    user_message = build_user_message(
        session_type, portfolio, market_data, news_by_ticker, fee_snapshot, settings,
        recent_activities=recent_activities,
    )

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    response = client.messages.create(
        model=model,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw_text = response.content[0].text.strip()

    # Strip markdown fences if Claude added them despite instructions
    if raw_text.startswith("```"):
        lines = raw_text.split("\n")
        raw_text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Claude returned non-JSON response. Parse error: {e}\n\nRaw response:\n{raw_text[:500]}"
        )
