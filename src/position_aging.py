"""
position_aging.py — classify each open position by holding-period tier.

The user's stated strategy is small weekly actions, 3–6 month sweet-spot holds,
and a hard 2–3 year cap. The aging tiers below operationalize that:

    fresh   (0–90 days)    Normal evaluation. Most BUY/ADD candidates land here.
    core    (91–180)       Sweet spot. Hold and add on dips when conviction high.
    mature  (181–365)      Re-validate thesis. Conviction loses 1 point if no
                           new catalyst since entry.
    aged    (366–730)      Trim candidate. Must have a fresh catalyst to keep.
    stale   (731+)         Hard exit recommendation regardless of P&L. The
                           strategy explicitly rejects permanent holds.

This module produces *deterministic* tags that flow into the Claude prompt and
into post-Claude quality gates. Claude can override `mature` and `aged` tags
with strong reasoning, but `stale` is enforced by the gate (no override).

The caller passes:
  - `holdings`: list of holding dicts from portfolio_loader
  - `holding_days_map`: output of activity_loader.holding_days_by_ticker()
"""

from __future__ import annotations

from collections.abc import Iterable

# Tier boundaries are configurable via settings.json -> position_aging_tiers.
DEFAULT_TIERS = {
    "fresh_max_days": 90,
    "core_max_days": 180,
    "mature_max_days": 365,
    "aged_max_days": 730,
    # > aged_max_days = stale (forced exit)
}

TIER_GUIDANCE = {
    "fresh": "Normal evaluation. Inside the 0-3 month entry window.",
    "core": "Sweet-spot hold (3-6 months). Add on dips when conviction is high.",
    "mature": "Re-validate the thesis. Drop conviction by 1 if no fresh catalyst.",
    "aged": "Trim candidate. Keep only with a verified new catalyst.",
    "stale": "Forced exit candidate (>2 years). The strategy rejects permanent holds.",
}


def classify_age(days_held: int | None, tiers: dict | None = None) -> str | None:
    """Return the position-aging tier for a single ticker.

    Returns None when days_held is unknown (e.g. activities CSV not provided
    or the buy fell outside the activities window).
    """
    if days_held is None:
        return None
    cfg = {**DEFAULT_TIERS, **(tiers or {})}
    if days_held <= cfg["fresh_max_days"]:
        return "fresh"
    if days_held <= cfg["core_max_days"]:
        return "core"
    if days_held <= cfg["mature_max_days"]:
        return "mature"
    if days_held <= cfg["aged_max_days"]:
        return "aged"
    return "stale"


def annotate_holdings(holdings: Iterable[dict], holding_days_map: dict, tiers: dict | None = None) -> list[dict]:
    """Return a copy of holdings enriched with `days_held` and `aging_tier`.

    Does not mutate the input holdings dicts.
    """
    out = []
    for holding in holdings or []:
        ticker = holding.get("ticker")
        info = holding_days_map.get(ticker, {}) if holding_days_map else {}
        days_held = info.get("days_held")
        copied = dict(holding)
        copied["days_held"] = days_held
        copied["lower_bound_days"] = info.get("lower_bound_days")
        copied["aging_tier"] = classify_age(days_held, tiers)
        copied["holding_duration_unknown"] = bool(info.get("duration_unknown"))
        out.append(copied)
    return out


def aging_summary(annotated: Iterable[dict]) -> dict:
    """Summarize counts per aging tier, useful in the prompt and quality gates.

    The ``unknown_with_lower_bound`` list captures holdings whose exact entry date
    is not in the activities window but where the activities CSV proves the
    position has been held *at least* that many days. We surface these to
    Claude so it can reason about long-untouched positions even when the buy
    pre-dates the available window.
    """
    counts = {"fresh": 0, "core": 0, "mature": 0, "aged": 0, "stale": 0, "unknown": 0}
    stale_tickers: list[str] = []
    aged_tickers: list[str] = []
    mature_tickers: list[str] = []
    unknown_with_lower_bound: list[dict] = []
    for holding in annotated or []:
        tier = holding.get("aging_tier")
        ticker = holding.get("ticker")
        if tier is None:
            counts["unknown"] += 1
            lower_bound = holding.get("lower_bound_days")
            if ticker and isinstance(lower_bound, (int, float)) and lower_bound > 0:
                unknown_with_lower_bound.append(
                    {
                        "ticker": ticker,
                        "lower_bound_days": int(lower_bound),
                    }
                )
            continue
        counts[tier] = counts.get(tier, 0) + 1
        if not ticker:
            continue
        if tier == "stale":
            stale_tickers.append(ticker)
        elif tier == "aged":
            aged_tickers.append(ticker)
        elif tier == "mature":
            mature_tickers.append(ticker)
    return {
        "counts": counts,
        "stale_tickers": sorted(stale_tickers),
        "aged_tickers": sorted(aged_tickers),
        "mature_tickers": sorted(mature_tickers),
        "unknown_with_lower_bound": sorted(
            unknown_with_lower_bound,
            key=lambda item: -item["lower_bound_days"],
        ),
    }


def format_aging_for_prompt(annotated: list[dict], summary: dict) -> str:
    """Render a compact, Claude-friendly summary of position ages.

    Emits content when there are positions whose age changes the action
    (mature, aged, or stale tickers), OR when there are holdings with an
    activities-window-derived lower bound on hold time. When everything is
    fresh/core with no lower-bound info, returns "".
    """
    counts = summary.get("counts") or {}
    stale = summary.get("stale_tickers") or []
    aged = summary.get("aged_tickers") or []
    mature = summary.get("mature_tickers") or []
    unknown_bounds = summary.get("unknown_with_lower_bound") or []

    if not (stale or aged or mature or unknown_bounds):
        return ""  # nothing worth telling Claude about

    lines = [
        "POSITION AGING (your strategy: 3-6 month sweet spot, 2-year hard cap):",
        f"  - fresh (0-90d): {counts.get('fresh', 0)}",
        f"  - core (91-180d): {counts.get('core', 0)}",
        f"  - mature (181-365d): {counts.get('mature', 0)}",
        f"  - aged (366-730d): {counts.get('aged', 0)}",
        f"  - stale (>730d): {counts.get('stale', 0)}",
    ]
    if mature:
        lines.append(f"  MATURE — re-validate thesis or drop conviction by 1: {', '.join(mature[:10])}")
    if aged:
        lines.append(f"  AGED — trim candidate, keep only with fresh catalyst: {', '.join(aged[:10])}")
    if stale:
        lines.append(f"  STALE — FORCE EXIT (over 2-year cap, strategy rejects permanent holds): {', '.join(stale[:10])}")
    if unknown_bounds:
        # Holdings whose entry date is older than the activities CSV window:
        # we know they have been held *at least* lower_bound_days. Useful when
        # the lower bound already exceeds the mature/aged thresholds.
        formatted = ", ".join(f"{item['ticker']} (≥{item['lower_bound_days']}d)" for item in unknown_bounds[:10])
        lines.append("  UNKNOWN ENTRY DATE — held at least this long (entry pre-dates activities window): " + formatted)
    return "\n".join(lines)
