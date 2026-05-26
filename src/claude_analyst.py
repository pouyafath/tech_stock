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
# Pricing per 1M tokens. cache_write_5m is the 5-minute ephemeral write multiplier
# (1.25× input). cache_write_1h is the 1-hour ephemeral write multiplier (2× input)
# — this is what the code actually uses (ttl: "1h" set at lines 794 and 808).
# cache_read is 0.1× input.  See https://docs.anthropic.com/en/docs/prompt-caching
MODEL_PRICING = {
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00, "cache_write_5m": 3.75, "cache_write_1h": 6.00, "cache_read": 0.30},
    "claude-opus-4-7": {"input": 5.00, "output": 25.00, "cache_write_5m": 6.25, "cache_write_1h": 10.00, "cache_read": 0.50},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00, "cache_write_5m": 1.25, "cache_write_1h": 2.00, "cache_read": 0.10},
}

# Which cache TTL the analyst actually uses (must match the cache_control TTL passed to
# the Anthropic SDK below).  Bump to "5m" only if you also change the cache_control values.
_CACHE_TTL = "1h"


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
    Hard size caps: session_summary <= 600 characters; cash_deployment <= 450; each thesis <= 450; technical_basis <= 250; risk_or_invalidation <= 250; catalyst_source <= 160; each warning <= 240; watchlist_flags <= 8; warnings <= 12; sector_warnings <= 8. Do not repeat raw quote tables inside JSON strings.
33. POSITION AGING (3-6 month sweet spot, 2-year hard cap): Every existing holding has a `held [days] [tier]` tag in PORTFOLIO. Tiers and required actions:
    - fresh (0-90d) → normal evaluation; ADD freely if conviction ≥7
    - core (91-180d) → sweet spot; HOLD-keep or HOLD-add_on_dip with strong thesis
    - mature (181-365d) → re-validate the original thesis; if no fresh catalyst since entry, drop conviction by 1 and bias toward TRIM
    - aged (366-730d) → must have a fresh catalyst from enrichment data; otherwise TRIM
    - stale (>730d) → output TRIM (no permanent holds; the user explicitly capped holds at 2 years). The deterministic gate enforces this regardless of your output.
   Use the POSITION AGING summary block (when present) as a checklist.
34. VIX-REGIME SIZING: When MARKET DATA shows VIX, scale your invest_amount_usd values:
    - VIX < 15  → full size (1.00× of conviction-based amount)
    - 15 to 25  → 0.85× (mild caution)
    - 25 to 35  → 0.60× (elevated; only top 1-2 BUYs per session)
    - VIX > 35  → 0.40× (panic; require conviction 9+ for any new BUY, prefer TRIM/HEDGE)
   Mention the VIX level explicitly in the session_summary when above 20.
35. DRAWDOWN MODE: When the user message contains a "DRAWDOWN CIRCUIT BREAKER ACTIVE" line, follow these rules without exception:
    - No new BUY recommendations this session.
    - Existing ADD candidates: keep but halve invest_amount_usd.
    - Force HOLD-watch on every position with conviction <7 (monitor for further weakness or exit).
    - Bias toward defensive sector trims (XLY, XLK) and toward defensive HOLDs (XLP, XLU).
    - The deterministic gate enforces these rules; align your JSON output with them.
36. CATALYST WINDOWS: When the user message contains a "CATALYST WINDOWS" block, treat its tags as constraints, not suggestions:
    - LOCKDOWN (≤5 days before earnings) → no new BUY/ADD on that ticker; existing recommendations stay HOLD.
    - SETUP (T-30 to T-6 days) → entries OK if conviction ≥7 with cited catalyst.
    - DRIFT (T+1 to T+3) → high-conviction adds OK only if post-earnings move confirms thesis direction.
    - FOMC_TODAY / CPI_WEEK / NFP_DAY → reduce session-wide aggressiveness; consider trimming highest-beta names; defer non-urgent BUYs.
37. TRAILING STOPS: When the user message contains a "TRAILING STOPS" block, the deterministic trailing-stop logic has already calculated a tightened stop level. For BREACHED alerts, output TRIM (the deterministic gate enforces this). For active alerts, set risk_controls.stop_loss_pct so the absolute stop matches the listed stop_price; do not loosen the stop. The schedule is: +10% gain → breakeven; +20% gain → trail by 8% from peak; +40% gain → trail by 12% from peak.
38. SECTOR ROTATION: When the user message contains a "SECTOR ROTATION" block, use the leadership ranking to bias trade ideas:
    - "Rotating IN" sectors → favor adding leaders or BUY single names within those sectors (1-month leaders persist for several weeks).
    - "Rotating OUT" sectors → favor trimming holdings concentrated in those sectors before underperformance compounds.
    - Static "Leaders" → maintain or modestly add; static "Laggards" → only add on strong contrarian thesis.
39. TRANCHED PLANS: For every BUY/ADD include an `entry_plan` array; for every SELL/TRIM include an `exit_plan` array. Each entry is `{trigger, fraction, price_pct, note}`. Default split is 40% / 30% / 30% across (now / pullback to lower entry zone / confirmation above upper entry zone). This produces 3 small actions over 1-2 weeks instead of a single bet — fits the user's weekly-action cadence and lowers average entry by ~0.5-1% historically. If you omit these arrays, the system fills in a deterministic default using the entry_zone and stop_loss percentages.
40. THESIS DECAY: When the user message contains a "THESIS DECAY" block, treat it as the official quarterly review:
    - For "Due for review" tickers: explicitly state in your thesis whether the original thesis has materialized, partial, not_yet, or invalidated. The system will auto-classify your verdict from the action/conviction.
    - For "FORCED EXIT" tickers: output SELL. The deterministic gate enforces this — output anything else and the gate will overwrite. These positions have failed 4 consecutive quarterly reviews; the strategy is to free up capital for fresh ideas.

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


COMPACT_JSON_RETRY_MESSAGE = """The previous response was invalid JSON or was truncated.
Return one COMPLETE valid JSON object only, using the same schema, with these emergency caps:
- Max 8 recommendation rows and max 5 priority_actions.
- Max 5 watchlist_flags, max 6 warnings, max 4 hedge_suggestions.
- thesis <= 220 chars; technical_basis <= 140 chars; risk_or_invalidation <= 180 chars.
- Omit entry_plan/exit_plan arrays; deterministic defaults will be added later.
- Do not include raw quotes, raw news lists, markdown, or prose outside JSON."""


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
                "required": ["ticker", "action", "conviction", "thesis", "net_expected_pct", "fee_hurdle_pct", "time_horizon"],
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


def _default_entry_plan(rec: dict) -> list[dict]:
    """Build a deterministic 3-tranche entry plan when Claude omits one.

    Splits the position 40% / 30% / 30% across:
        - 40% now (immediate execution)
        - 30% if the price pulls back to the lower half of the entry zone
          (or -3% if no zone was provided)
        - 30% on confirmation (price clears the upper half of the entry zone
          or +2% if no zone was provided)

    Lowers the user's average entry by ~0.5-1% historically and produces 3
    weekly small actions instead of 1 big bet — fits the user's cadence.
    """
    controls = rec.get("risk_controls") or {}
    low = controls.get("entry_zone_low_pct")
    high = controls.get("entry_zone_high_pct")
    pullback_pct = (low / 2.0) if isinstance(low, (int, float)) else -3.0
    confirm_pct = (high / 2.0) if isinstance(high, (int, float)) else 2.0
    return [
        {"trigger": "now", "fraction": 0.4, "price_pct": 0, "note": "immediate"},
        {"trigger": "pullback", "fraction": 0.3, "price_pct": round(pullback_pct, 2), "note": "if price pulls back"},
        {"trigger": "confirmation", "fraction": 0.3, "price_pct": round(confirm_pct, 2), "note": "on upside confirmation"},
    ]


def _default_exit_plan(rec: dict) -> list[dict]:
    """Build a deterministic 3-tranche exit plan when Claude omits one.

    Trims:
        - 40% now (lock in some at current price)
        - 30% if price recovers to entry zone high
        - 30% if price falls to stop_loss (full exit)
    """
    controls = rec.get("risk_controls") or {}
    high = controls.get("entry_zone_high_pct")
    stop = controls.get("stop_loss_pct")
    recover_pct = (high / 2.0) if isinstance(high, (int, float)) else 2.0
    stop_pct = stop if isinstance(stop, (int, float)) else -7.0
    return [
        {"trigger": "now", "fraction": 0.4, "price_pct": 0, "note": "lock in at current"},
        {"trigger": "recovery", "fraction": 0.3, "price_pct": round(recover_pct, 2), "note": "if price bounces"},
        {"trigger": "stop_loss", "fraction": 0.3, "price_pct": round(stop_pct, 2), "note": "full exit at stop"},
    ]


_CANONICAL_HORIZONS = (
    "intraday",
    "next session",
    "1-3 trading days",
    "1-2 weeks",
    "1-3 months",
    "3-6 months",
    "6-12 months",
    "12-36 months",
)
_CANONICAL_HORIZON_SET = set(_CANONICAL_HORIZONS)

# Common Claude-drift variants → canonical horizon. Keys are lowercased and
# whitespace-collapsed; values must appear in _CANONICAL_HORIZONS.
_HORIZON_VARIANT_MAP = {
    # Intraday / next session
    "today": "intraday",
    "same session": "intraday",
    "open to close": "intraday",
    "tomorrow": "next session",
    "next open": "next session",
    "overnight": "next session",
    # Trading days
    "1 day": "1-3 trading days",
    "2 days": "1-3 trading days",
    "3 days": "1-3 trading days",
    "few days": "1-3 trading days",
    "1-3 days": "1-3 trading days",
    "1-3 sessions": "1-3 trading days",
    "few trading days": "1-3 trading days",
    # Weeks
    "1 week": "1-2 weeks",
    "2 weeks": "1-2 weeks",
    "1-2 wks": "1-2 weeks",
    "next 1-2 weeks": "1-2 weeks",
    "couple weeks": "1-2 weeks",
    # 1-3 months
    "1 month": "1-3 months",
    "2 months": "1-3 months",
    "3 months": "1-3 months",
    "1-3 mo": "1-3 months",
    "1 to 3 months": "1-3 months",
    "next quarter": "1-3 months",
    # 3-6 months
    "4 months": "3-6 months",
    "5 months": "3-6 months",
    "6 months": "3-6 months",
    "3-6 mo": "3-6 months",
    "two quarters": "3-6 months",
    # 6-12 months
    "7 months": "6-12 months",
    "9 months": "6-12 months",
    "12 months": "6-12 months",
    "1 year": "6-12 months",
    "6-12 mo": "6-12 months",
    "rest of year": "6-12 months",
    # 12-36 months
    "18 months": "12-36 months",
    "24 months": "12-36 months",
    "2 years": "12-36 months",
    "3 years": "12-36 months",
    "1-3 years": "12-36 months",
    "long term": "12-36 months",
    "long-term": "12-36 months",
    "multi-year": "12-36 months",
}


def _normalize_time_horizon(value) -> str:
    """Snap a free-form time horizon to one of the canonical strings.

    Falls back to the default "1-3 months" only when the input does not match
    any canonical or known variant. Keeps the canonical value untouched.
    """
    if not value:
        return "1-3 months"
    if value in _CANONICAL_HORIZON_SET:
        return value
    key = " ".join(str(value).lower().split())
    if key in _HORIZON_VARIANT_MAP:
        return _HORIZON_VARIANT_MAP[key]
    # Try a couple of broad heuristics for unanticipated formats (e.g. "10-12 mo")
    if "month" in key or " mo" in key.split()[-1] if key.split() else False:
        if any(num in key for num in ("12", "18", "24", "36")):
            return "12-36 months"
        if any(num in key for num in ("6", "7", "8", "9", "10", "11")):
            return "6-12 months"
        if any(num in key for num in ("4", "5")):
            return "3-6 months"
        return "1-3 months"
    if "year" in key:
        return "12-36 months"
    if "week" in key:
        return "1-2 weeks"
    if "day" in key:
        return "1-3 trading days"
    return "1-3 months"


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

        # Snap time_horizon variants to the canonical Rule 20 strings so the
        # backtester's HORIZON_DAYS lookup and downstream UI filters keep working.
        original_horizon = rec.get("time_horizon")
        normalized_horizon = _normalize_time_horizon(original_horizon)
        rec["time_horizon"] = normalized_horizon
        if original_horizon and original_horizon != normalized_horizon:
            rec["time_horizon_original"] = original_horizon
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
            **{
                k: v
                for k, v in controls.items()
                if k
                not in {
                    "entry_zone_low_pct",
                    "entry_zone_high_pct",
                    "stop_loss_pct",
                    "take_profit_pct",
                }
            },
        }
        rec.setdefault("catalyst_verified", False)
        rec.setdefault("catalyst_source", None)
        rec.setdefault("manual_review_required", False)
        if rec.get("action") == "HOLD" and not rec.get("hold_tier"):
            rec["hold_tier"] = "watch"

        # Tranched plans — backfill defaults when Claude omits them so the user
        # always sees a 3-step "now / pullback / confirmation" plan instead of
        # a single bet.  Claude can override by returning its own entry_plan /
        # exit_plan.
        action = rec.get("action")
        if action in {"BUY", "ADD"}:
            if not isinstance(rec.get("entry_plan"), list) or not rec.get("entry_plan"):
                rec["entry_plan"] = _default_entry_plan(rec)
                rec["entry_plan_auto_generated"] = True
        elif action in {"SELL", "TRIM"}:
            if not isinstance(rec.get("exit_plan"), list) or not rec.get("exit_plan"):
                rec["exit_plan"] = _default_exit_plan(rec)
                rec["exit_plan_auto_generated"] = True

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
        lines.append("Highly correlated pairs: " + ", ".join(f"{p['pair']} ({p['correlation']:+.2f})" for p in pairs))
    return lines


def _format_company_exposure(company_exposure: dict | None) -> list[str]:
    if not company_exposure:
        return []
    lines = ["\n=== COMPANY-LEVEL EXPOSURE ROLLUP ==="]
    for row in list(company_exposure.values())[:12]:
        tickers = ", ".join(row.get("tickers") or [])
        lines.append(f"  {row.get('company')}: {row.get('pct', 0):.1f}% (${row.get('value_usd', 0):,.0f} USD equiv) via {tickers}")
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
    holding_days_map: dict | None = None,
    drawdown_state: dict | None = None,
    thesis_due_for_review: list | None = None,
    thesis_forced_exits: list | None = None,
    decision_scorecard: dict | None = None,
) -> str:
    """Construct the full user message with all context."""
    from src.news_fetcher import aggregate_sentiment
    from src.position_aging import (
        annotate_holdings,
        aging_summary,
        format_aging_for_prompt,
    )

    now_dt = datetime.now()
    now = now_dt.strftime("%Y-%m-%d %H:%M")
    market_phase = _market_phase(now_dt)
    budget_cad = settings.get("budget_cad", 0)
    budget_usd = settings.get("budget_usd", 0)
    news_by_ticker = news_by_ticker or {}

    holdings = portfolio.get("holdings", [])
    aging_tiers = settings.get("position_aging_tiers") or None
    annotated_holdings = annotate_holdings(holdings, holding_days_map or {}, aging_tiers)
    holdings = annotated_holdings  # downstream rendering uses days_held + aging_tier
    cash_cad = portfolio.get("cash_cad", 0)
    exported_at = portfolio.get("exported_at", "")

    budget_lines = []
    if budget_usd:
        budget_lines.append(f"Available to invest (USD): ${budget_usd:,.2f}")
    if budget_cad:
        budget_lines.append(f"Available to invest (CAD): ${budget_cad:,.2f}")
    if not budget_lines:
        budget_lines.append("Available to invest: $0 (observation only — no new capital this session)")

    lines = (
        [
            f"SESSION TYPE: {session_type.upper()}",
            f"TIMESTAMP: {now}",
            f"MARKET PHASE: {market_phase}",
            "",
            "=== PORTFOLIO ===",
            f"Portfolio snapshot: {exported_at}" if exported_at else "",
            f"Cash (CASH ETF): ${cash_cad:,.2f} CAD",
        ]
        + budget_lines
        + [
            f"Risk tolerance: {settings.get('risk_tolerance', 'aggressive')}",
            f"Account: {settings.get('account_type', 'wealthsimple_premium_usd')}",
            "",
        ]
    )

    if holdings:
        usd_holdings = [h for h in holdings if not h.get("is_cdr") and h.get("market_currency") == "USD"]
        cad_holdings = [h for h in holdings if h.get("is_cdr") or h.get("market_currency") == "CAD"]

        def _age_label(h: dict) -> str:
            tier = h.get("aging_tier")
            days = h.get("days_held")
            if tier and days is not None:
                return f" | held {days}d [{tier}]"
            if h.get("holding_duration_unknown"):
                lower_bound = h.get("lower_bound_days")
                if lower_bound is not None:
                    return f" | held at least {lower_bound}d (entry pre-dates activity export)"
                return " | holding duration unknown (entry pre-dates activity export)"
            return ""

        def _fmt_pnl(pnl_pct, pnl_dollars, currency_suffix: str = "") -> str:
            """Build a P&L string that survives None values defensively.

            Cases:
              - both None       → ""
              - only pct known  → " | P&L +5.2%"
              - both known      → " | P&L +5.2% ($+1,234{ currency_suffix})"
              - only dollars    → " | P&L $+1,234{ currency_suffix}"
            """
            try:
                pct_part = f"{float(pnl_pct):+.1f}%" if pnl_pct is not None else None
            except (TypeError, ValueError):
                pct_part = None
            try:
                dollar_part = f"${float(pnl_dollars):+,.0f}{currency_suffix}" if pnl_dollars is not None else None
            except (TypeError, ValueError):
                dollar_part = None
            if pct_part and dollar_part:
                return f" | P&L {pct_part} ({dollar_part})"
            if pct_part:
                return f" | P&L {pct_part}"
            if dollar_part:
                return f" | P&L {dollar_part}"
            return ""

        def _fmt_qty(qty) -> str:
            try:
                return f"{float(qty):8.4f}"
            except (TypeError, ValueError):
                return "       ?"

        def _fmt_dollar(value, prefix: str = "$", precision: int = 2, suffix: str = "") -> str:
            try:
                return f"{prefix}{float(value):,.{precision}f}{suffix}"
            except (TypeError, ValueError):
                return ""

        if usd_holdings:
            lines.append("USD Holdings:")
            for h in usd_holdings:
                ticker = h.get("ticker", "")
                qty_str = _fmt_qty(h.get("quantity", 0))
                avg_str = _fmt_dollar(h.get("avg_cost_market"), prefix="avg $")
                price_str = _fmt_dollar(h.get("market_price"), prefix="now $")
                mv_str = _fmt_dollar(h.get("market_value"), prefix="value $", precision=0)
                pnl_str = _fmt_pnl(h.get("unrealized_pnl_pct"), h.get("unrealized_pnl"))
                lines.append(f"  {ticker:8s} {qty_str} sh | {avg_str} | {price_str} | {mv_str}{pnl_str}{_age_label(h)}")

        if cad_holdings:
            lines.append("\nCAD/CDR Holdings:")
            for h in cad_holdings:
                ticker = h.get("ticker", "")
                name = h.get("name", "")
                qty_str = _fmt_qty(h.get("quantity", 0))
                avg_str = _fmt_dollar(h.get("avg_cost_market"), prefix="avg $", suffix=" CAD")
                price_str = _fmt_dollar(h.get("market_price"), prefix="now $", suffix=" CAD")
                cdr_flag = " [CDR]" if h.get("is_cdr") and "CDR" in name else ""
                pnl_str = _fmt_pnl(h.get("unrealized_pnl_pct"), h.get("unrealized_pnl"), currency_suffix=" CAD")
                lines.append(f"  {ticker:8s}{cdr_flag:6s} {qty_str} sh | {avg_str} | {price_str}{pnl_str}{_age_label(h)}")
    else:
        lines.append("No current holdings — all cash.")

    # ── Sector exposure (if provided) ──────────────────────────────────────
    if sector_exposure:
        lines.append("\n=== SECTOR EXPOSURE (% of portfolio value) ===")
        threshold = settings.get("sector_concentration_threshold_pct", 40)
        for sector, data in sector_exposure.items():
            flag = "  ⚠️ CONCENTRATED" if data["pct"] > threshold else ""
            tickers_str = ", ".join(data["tickers"][:6])
            lines.append(f"  {sector:22s} {data['pct']:5.1f}%  (${data['value_cad']:,.0f} CAD)  [{tickers_str}]{flag}")

    lines += _format_company_exposure(company_exposure)
    lines += _format_risk_dashboard(risk_dashboard)

    # ── Position aging (drives weekly small actions on existing holdings) ─
    aging = aging_summary(annotated_holdings)
    aging_block = format_aging_for_prompt(annotated_holdings, aging)
    if aging_block:
        lines.append("")
        lines.append(aging_block)

    # ── Catalyst windows (earnings ±5d, FOMC, CPI, NFP) ─────────────────
    from src.catalyst_windows import annotate_tickers, macro_session_tags, format_for_prompt

    enriched_per_ticker = (enriched or {}).get("per_ticker") or {}
    macro_calendar = ((enriched or {}).get("macro_context") or {}).get("calendar")
    ticker_windows = annotate_tickers(enriched_per_ticker)
    session_tags = macro_session_tags(macro_calendar)
    catalyst_block = format_for_prompt(ticker_windows, session_tags)
    if catalyst_block:
        lines.append("")
        lines.append(catalyst_block)

    # ── Trailing stops (lock in gains as positions appreciate) ──────────
    from src.trailing_stops import evaluate as _eval_trailing_stops, format_for_prompt as _fmt_ts

    trailing = _eval_trailing_stops(holdings, market_data, holding_days_map, settings)
    trailing_block = _fmt_ts(trailing)
    if trailing_block:
        lines.append("")
        lines.append(trailing_block)

    # ── Sector rotation rhythm (1-month relative strength) ───────────────
    if market_context:
        from src.sector_rotation import classify as _classify_sectors, format_for_prompt as _fmt_sectors

        prev_context = (previous_session or {}).get("market_context_snapshot")
        sector_universe = settings.get("sector_rotation_tickers")
        rotation = _classify_sectors(
            market_context,
            previous_market_context=prev_context,
            sector_universe=sector_universe,
        )
        rotation_block = _fmt_sectors(rotation)
        if rotation_block:
            lines.append("")
            lines.append(rotation_block)

    # ── Thesis decay (90-day reviews + forced exits after 4 negative reviews)
    if thesis_due_for_review or thesis_forced_exits:
        from src.thesis_tracker import format_for_prompt as _fmt_thesis

        thesis_block = _fmt_thesis(thesis_due_for_review or [], thesis_forced_exits or [])
        if thesis_block:
            lines.append("")
            lines.append(thesis_block)

    # ── Drawdown circuit-breaker context (set by main.py / analytics) ────
    if drawdown_state and drawdown_state.get("triggered"):
        dd = drawdown_state
        lines.append("")
        lines.append(
            "DRAWDOWN CIRCUIT BREAKER ACTIVE — portfolio is "
            f"{dd.get('drawdown_pct', 0):+.1f}% from {dd.get('peak_label', '30d peak')}. "
            "Apply rules in §32-34 (no new ADD; halve all invest_amount_usd; "
            "force HOLD-watch on conviction <7)."
        )
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

        recent_days = settings.get("recent_activity_days", 90)
        recent_window = "full export" if recent_days is None else f"last {recent_days} days"
        lines.append(f"\n=== RECENT TRADE HISTORY ({recent_window}) ===")
        lines.append(format_activities_for_prompt(recent_activities, days=recent_days))

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
            lines.append("  Avg actual return by conviction score (v1.16: also Sharpe + max-DD):")
            for conv in sorted(by_conv.keys()):
                stats = by_conv[conv]
                line = f"    conviction={conv}  n={stats['n']:3d}  avg={stats['avg_return_pct']:+.2f}%  win_rate={stats['hit_rate']:.0%}"
                # Sharpe and max-DD only present when v1.16+ backtester ran —
                # gracefully skip on legacy summaries so prompt stays clean.
                if "sharpe" in stats:
                    line += f"  sharpe={stats['sharpe']:+.2f}  max_dd={stats['max_drawdown_pct']:+.2f}%"
                lines.append(line)
            sizing_mults = backtest_summary.get("sizing_multipliers_by_conviction") or {}
            if sizing_mults:
                lines.append(
                    "  ↳ Sizing multipliers (Sharpe-dampened): " + ", ".join(f"conv{k}={v:.2f}×" for k, v in sorted(sizing_mults.items()))
                )
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

    if decision_scorecard and (decision_scorecard.get("journal") or {}).get("recorded", 0) > 0:
        journal = decision_scorecard.get("journal") or {}
        overall = decision_scorecard.get("overall") or {}
        lines.append("\n=== YOUR DECISION JOURNAL TRACK RECORD ===")
        lines.append(
            f"  Recorded decisions: {journal.get('recorded', 0)} | "
            f"pending: {journal.get('pending', 0)} | "
            f"scored windows: {decision_scorecard.get('n_scored_windows', 0)}"
        )
        lines.append(
            f"  Model avg action return: {overall.get('model_avg_return_pct', 0):+.2f}% | "
            f"Your avg action return: {overall.get('user_avg_return_pct', 0):+.2f}% | "
            f"Discretion delta: {overall.get('avg_decision_delta_pct', 0):+.2f}%"
        )
        by_decision = decision_scorecard.get("by_user_decision") or {}
        if by_decision:
            lines.append("  By user decision:")
            for decision, stats in by_decision.items():
                lines.append(
                    f"    {decision:8s} n={stats['n']:3d} "
                    f"model={stats['model_avg_return_pct']:+.2f}% "
                    f"user={stats['user_avg_return_pct']:+.2f}% "
                    f"delta={stats['avg_decision_delta_pct']:+.2f}%"
                )
        # v1.16: per-horizon edge — the user's edge often varies sharply by
        # holding period. Surface it explicitly so Claude can bias the
        # time_horizon field toward where the user actually outperforms.
        by_horizon = decision_scorecard.get("by_horizon") or {}
        if by_horizon:
            edge_parts = []
            best_horizon: tuple[int, float] | None = None
            for horizon in sorted(int(h) for h in by_horizon.keys()):
                stats = by_horizon[horizon]
                user_avg = float(stats.get("user_avg_return_pct", 0.0))
                edge_parts.append(f"{horizon}d {user_avg:+.1f}%")
                # "Best" = highest user_avg, breaking ties toward shorter horizon.
                if best_horizon is None or user_avg > best_horizon[1] + 1e-9:
                    best_horizon = (horizon, user_avg)
            lines.append("  Your edge by horizon (user_avg_return): " + " | ".join(edge_parts))
            if best_horizon is not None and best_horizon[1] > 0:
                lines.append(
                    f"  ↳ Bias time_horizon toward ~{best_horizon[0]}d when conviction ≥ 7 "
                    f"(user's strongest window: {best_horizon[1]:+.1f}%)."
                )
        worst = decision_scorecard.get("worst_user_overrides") or []
        if worst:
            lines.append("  Overrides that hurt most:")
            for row in worst[:5]:
                lines.append(
                    f"    {row.get('session_date')} {row.get('ticker')} rec={row.get('recommended_action')} "
                    f"decision={row.get('user_decision')} horizon={row.get('horizon_days')}d "
                    f"delta={row.get('decision_delta_pct'):+.2f}%"
                )
        lines.append("  ↳ Use this to calibrate whether to push harder on recommendations the user tends to ignore incorrectly.")

    # ── Drift from previous session ────────────────────────────────────────
    if drift:
        lines.append("\n=== DRIFT SINCE LAST SESSION ===")
        # Render generic drift events first; thesis_text_drift gets its own
        # mini-section because it needs the similarity score and a steering
        # nudge for Claude.
        thesis_drift_events = [d for d in drift if d.get("drift_type") == "thesis_text_drift"]
        for d in drift:
            if d.get("drift_type") == "thesis_text_drift":
                continue
            was = d.get("was") or {}
            now = d.get("now") or {}
            lines.append(
                f"  {d['ticker']}: {d['drift_type']} — "
                f"was {was.get('action', '')}/{was.get('conviction', '')}, "
                f"now {now.get('action', '')}/{now.get('conviction', '')}"
            )
        if thesis_drift_events:
            lines.append("  Thesis-text drift (action steady, rationale rewritten — confirm or downgrade):")
            for d in thesis_drift_events[:3]:
                ticker = d.get("ticker", "?")
                similarity = d.get("similarity", 0.0)
                was_thesis = ((d.get("was") or {}).get("thesis") or "").strip()
                now_thesis = ((d.get("now") or {}).get("thesis") or "").strip()
                lines.append(f"    {ticker}: similarity={similarity:.2f}")
                if was_thesis:
                    lines.append(f"      was: {was_thesis[:220]}")
                if now_thesis:
                    lines.append(f"      now: {now_thesis[:220]}")

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
        prompt_article_cap = int(settings.get("news_prompt_max_articles", 2))
        for a in articles[:prompt_article_cap]:
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
    """Estimate the USD cost of an API call from usage statistics.

    Uses the 1-hour cache write rate by default since that is what
    `_CACHE_TTL` controls and the analyst sets on every Pass 1 call.
    """
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["claude-sonnet-4-6"])
    M = 1_000_000
    cache_write_rate = pricing.get(f"cache_write_{_CACHE_TTL}", pricing.get("cache_write_1h"))

    input_cost = (getattr(usage, "input_tokens", 0) / M) * pricing["input"]
    output_cost = (getattr(usage, "output_tokens", 0) / M) * pricing["output"]
    cache_w_cost = (getattr(usage, "cache_creation_input_tokens", 0) / M) * cache_write_rate
    cache_r_cost = (getattr(usage, "cache_read_input_tokens", 0) / M) * pricing["cache_read"]
    total_cost = input_cost + output_cost + cache_w_cost + cache_r_cost

    return {
        "input_tokens": getattr(usage, "input_tokens", 0),
        "output_tokens": getattr(usage, "output_tokens", 0),
        "cache_write_tokens": getattr(usage, "cache_creation_input_tokens", 0),
        "cache_read_tokens": getattr(usage, "cache_read_input_tokens", 0),
        "total_tokens": (getattr(usage, "input_tokens", 0) + getattr(usage, "output_tokens", 0)),
        "cost_usd": round(total_cost, 4),
        "cache_hit": getattr(usage, "cache_read_input_tokens", 0) > 0,
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
        raise ValueError(f"Claude returned non-JSON response. Parse error: {e}\n\nRaw response:\n{raw_text[:500]}")

    recommendation = normalize_recommendation(recommendation)

    try:
        jsonschema.validate(recommendation, RECOMMENDATION_SCHEMA)
    except jsonschema.ValidationError as e:
        path = " -> ".join(str(p) for p in e.absolute_path) or "<root>"
        raise ValueError(f"Claude response failed schema validation at {path}: {e.message}")

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


def _sum_usage_stats(stats: list[dict]) -> dict:
    if not stats:
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_write_tokens": 0,
            "cache_read_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0,
            "cache_hit": False,
        }
    return {
        "input_tokens": sum(s.get("input_tokens", 0) for s in stats),
        "output_tokens": sum(s.get("output_tokens", 0) for s in stats),
        "cache_write_tokens": sum(s.get("cache_write_tokens", 0) for s in stats),
        "cache_read_tokens": sum(s.get("cache_read_tokens", 0) for s in stats),
        "total_tokens": sum(s.get("total_tokens", 0) for s in stats),
        "cost_usd": round(sum(s.get("cost_usd", 0) for s in stats), 4),
        "cache_hit": any(s.get("cache_hit") for s in stats),
        "retries": sum(s.get("retries", 0) for s in stats),
    }


def _looks_retryable_json_error(exc: ValueError, response) -> bool:
    message = str(exc)
    return "Claude returned non-JSON response" in message or getattr(response, "stop_reason", None) == "max_tokens"


def _create_parse_message(client, model: str, settings: dict, messages: list[dict]) -> tuple[dict, dict]:
    """Call Claude and parse JSON, retrying once with emergency compact caps if needed."""
    response = _create_message(client, model, settings, messages)
    usage_parts = [estimate_cost(response.usage, model)]
    try:
        return _parse_validate_recommendation(_response_text(response)), _sum_usage_stats(usage_parts)
    except ValueError as exc:
        if not _looks_retryable_json_error(exc, response):
            raise
        retry_messages = messages + [{"role": "user", "content": COMPACT_JSON_RETRY_MESSAGE}]
        retry_response = _create_message(client, model, settings, retry_messages)
        retry_usage = estimate_cost(retry_response.usage, model)
        retry_usage["retries"] = 1
        usage_parts.append(retry_usage)
        return _parse_validate_recommendation(_response_text(retry_response)), _sum_usage_stats(usage_parts)


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
        "retries": first.get("retries", 0) + second.get("retries", 0),
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
    return "\n".join(
        [
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
        ]
    )


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
    holding_days_map: dict | None = None,
    drawdown_state: dict | None = None,
    thesis_due_for_review: list | None = None,
    thesis_forced_exits: list | None = None,
    decision_scorecard: dict | None = None,
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
        session_type,
        portfolio,
        market_data,
        news_by_ticker,
        fee_snapshot,
        settings,
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
        holding_days_map=holding_days_map,
        drawdown_state=drawdown_state,
        thesis_due_for_review=thesis_due_for_review,
        thesis_forced_exits=thesis_forced_exits,
        decision_scorecard=decision_scorecard,
    )

    client = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        timeout=settings.get("claude_timeout_seconds", 240),
    )

    # Pass 1: produce the initial recommendation JSON.
    first_recommendation, first_usage = _create_parse_message(
        client,
        model,
        settings,
        [{"role": "user", "content": [_cacheable_text_block(user_message)]}],
    )

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
    recommendation, second_usage = _create_parse_message(
        client,
        model,
        settings,
        [
            {"role": "user", "content": [_cacheable_text_block(user_message)]},
            {"role": "user", "content": review_message},
        ],
    )

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

    # Build the aging summary so the gate can enforce the 2-year cap.
    from src.position_aging import annotate_holdings, aging_summary

    annotated = annotate_holdings(
        portfolio.get("holdings", []),
        holding_days_map or {},
        settings.get("position_aging_tiers"),
    )
    aging = aging_summary(annotated)

    # Compute trailing-stop alerts for the gate.
    from src.trailing_stops import evaluate as _eval_trailing_stops

    trailing_alerts = _eval_trailing_stops(
        portfolio.get("holdings", []),
        market_data,
        holding_days_map or {},
        settings,
    )

    recommendation = apply_quality_gates(
        recommendation,
        final_warnings,
        drawdown_state=drawdown_state,
        market_context=market_context,
        settings=settings,
        aging_summary_data=aging,
        backtest_summary=backtest_summary,
        trailing_alerts=trailing_alerts,
        thesis_forced_exits=thesis_forced_exits,
    )
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
        "retries": usage_stats.get("retries", 0),
    }
    return recommendation, usage_stats
