"""
sector_rotation.py — track 4-week relative strength of sector ETFs and surface
leadership shifts as actionable trades.

The user trades 3-6 month sweet-spot positions and wants weekly small actions.
Sector leadership tends to persist for several weeks once it shifts. By
ranking the sector ETFs (XLK, XLV, XLF, XLE, XLY, XLP, XLU, XLI) by 1-month
return weekly, you can:

  1. Increase weight in the new leader before the rotation is fully priced in.
  2. Trim the lagging former leader before its underperformance compounds.

This module produces deterministic tags from `get_context_moves()` output:

  * "leader"   — top quintile of 1-month returns
  * "laggard"  — bottom quintile of 1-month returns
  * "rotating_in"  — was middle/laggard last session, now in top half
  * "rotating_out" — was leader, now mid-pack or worse

The "rotating_*" tags require a previous session's snapshot for comparison;
without it, only static leader/laggard tags are emitted.
"""

from __future__ import annotations

from typing import Iterable

DEFAULT_QUINTILE_TOP = 0.4  # top 40% = leaders (handles small N: with 8 ETFs, 3 leaders)
DEFAULT_QUINTILE_BOT = 0.4  # bottom 40% = laggards


def _safe_float(value, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def rank_sectors(market_context: dict, lookback: str = "change_pct_21d") -> list[dict]:
    """Return sectors sorted by `lookback` change_pct, best first.

    market_context is the output of `get_context_moves()` keyed by ticker.
    Tickers with errors or missing data are filtered out.
    """
    rows = []
    for ticker, blob in (market_context or {}).items():
        if not isinstance(blob, dict) or blob.get("error"):
            continue
        change = _safe_float(blob.get(lookback))
        if change is None:
            continue
        rows.append({"ticker": ticker, "change_pct": round(change, 2)})
    rows.sort(key=lambda r: r["change_pct"], reverse=True)
    return rows


def classify(
    market_context: dict,
    previous_market_context: dict | None = None,
    sector_universe: Iterable[str] | None = None,
    lookback: str = "change_pct_21d",
    top_pct: float = DEFAULT_QUINTILE_TOP,
    bottom_pct: float = DEFAULT_QUINTILE_BOT,
) -> dict:
    """Classify sector ETFs into leaders/laggards/rotating tags.

    Returns:
        {
          "leaders":       [{ticker, change_pct}, ...],
          "laggards":      [{ticker, change_pct}, ...],
          "rotating_in":   [tickers that moved from bottom→top half],
          "rotating_out":  [tickers that moved from top→bottom half],
          "snapshot":      ranked list (also used to seed next session's compare),
        }
    """
    universe = set(sector_universe) if sector_universe else None
    full_rank = rank_sectors(market_context, lookback=lookback)
    if universe:
        full_rank = [r for r in full_rank if r["ticker"] in universe]
    if not full_rank:
        return {"leaders": [], "laggards": [], "rotating_in": [], "rotating_out": [], "snapshot": []}

    n = len(full_rank)
    n_top = max(1, int(round(n * top_pct)))
    n_bot = max(1, int(round(n * bottom_pct)))
    leaders = full_rank[:n_top]
    laggards = full_rank[-n_bot:]

    rotating_in: list[str] = []
    rotating_out: list[str] = []
    if previous_market_context:
        prev_rank = rank_sectors(previous_market_context, lookback=lookback)
        if universe:
            prev_rank = [r for r in prev_rank if r["ticker"] in universe]
        prev_n = len(prev_rank)
        if prev_n:
            half = prev_n // 2
            prev_top_half = {r["ticker"] for r in prev_rank[: max(1, half)]}
            prev_bot_half = {r["ticker"] for r in prev_rank[-max(1, half) :]}
            curr_n = n
            curr_half = curr_n // 2
            curr_top_half = {r["ticker"] for r in full_rank[: max(1, curr_half)]}
            curr_bot_half = {r["ticker"] for r in full_rank[-max(1, curr_half) :]}

            rotating_in = sorted((curr_top_half & prev_bot_half) - prev_top_half)
            rotating_out = sorted((curr_bot_half & prev_top_half) - prev_bot_half)

    return {
        "leaders": leaders,
        "laggards": laggards,
        "rotating_in": rotating_in,
        "rotating_out": rotating_out,
        "snapshot": full_rank,
    }


def format_for_prompt(classification: dict) -> str:
    """Render sector rotation tags for the Claude prompt.

    Empty if no sectors are ranked (e.g. context fetch failed).
    """
    leaders = classification.get("leaders") or []
    laggards = classification.get("laggards") or []
    rotating_in = classification.get("rotating_in") or []
    rotating_out = classification.get("rotating_out") or []
    if not leaders and not laggards:
        return ""

    lines = ["SECTOR ROTATION (1-month relative strength of sector ETFs):"]
    if leaders:
        leader_str = ", ".join(f"{r['ticker']} ({r['change_pct']:+.1f}%)" for r in leaders)
        lines.append(f"  Leaders:  {leader_str}")
    if laggards:
        laggard_str = ", ".join(f"{r['ticker']} ({r['change_pct']:+.1f}%)" for r in laggards)
        lines.append(f"  Laggards: {laggard_str}")
    if rotating_in:
        lines.append(f"  ⤴ Rotating IN  (gaining leadership): {', '.join(rotating_in)} — consider adding")
    if rotating_out:
        lines.append(f"  ⤵ Rotating OUT (losing leadership): {', '.join(rotating_out)} — consider trimming")
    return "\n".join(lines)
