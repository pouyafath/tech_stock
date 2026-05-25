"""
trailing_stops.py — deterministic trailing-stop levels for open positions.

The user's existing `risk_controls.stop_loss_pct` is static — set once at entry
and never tightened. This module ratchets the stop upward as a position appreciates,
locking in gains automatically.

Schedule (configurable via settings.json["trailing_stop_schedule"]):

    Current gain   Trail behaviour
    ────────────   ─────────────────────────────────────────────────
    < +10%         No change — original stop_loss_pct still applies
    +10% to +20%   Raise stop to breakeven (lock in entry; never lose)
    +20% to +40%   Trail by 8% from session peak
    > +40%         Trail by 12% from session peak (let winners breathe)

Output is a list of `TrailingStopAlert` dicts ready for the prompt and for
auto-generated TRIM recommendations when the stop is breached.

Inputs the caller must provide:
    holdings:     list[dict]  — output of portfolio_loader.parse_holdings_csv
    market_data:  dict[ticker, dict] — must include `history` and `current_price`
    holding_days: dict[ticker, dict] — output of activity_loader.holding_days_by_ticker

Peak-price calculation uses the higher of:
    - The holding's `avg_cost_market` × (1 + observed_max_gain_pct/100), where
      observed_max_gain_pct is derived from history since `earliest_open_buy`,
    - or the simple max(close) over the available history window.

This is approximate: it doesn't see intraday highs, and history may not reach
back to the entry date. But it's deterministic, free, and good enough to flag
"this position was up 30% last week and is now back to +12%, tighten the stop."
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

DEFAULT_SCHEDULE = [
    # (gain_threshold_pct, behaviour, value)
    (10.0, "breakeven", 0.0),
    (20.0, "trail_pct", 8.0),
    (40.0, "trail_pct", 12.0),
]


def _peak_close_since(history: list[dict], since_date: str | None) -> float | None:
    """Highest close in `history` on or after `since_date` (ISO yyyy-mm-dd)."""
    if not history:
        return None
    if since_date:
        rows = [r for r in history if (r.get("date") or "") >= since_date and r.get("close")]
    else:
        rows = [r for r in history if r.get("close")]
    if not rows:
        return None
    return max(float(r["close"]) for r in rows)


def compute_trailing_stop(
    avg_cost: float | None,
    current_price: float | None,
    peak_price: float | None,
    schedule: list[tuple] | None = None,
) -> dict | None:
    """Return {stop_price, gain_pct_at_peak, trail_kind} or None if N/A.

    `trail_kind` is one of: "none" | "breakeven" | "trail_pct".
    """
    if avg_cost is None or avg_cost <= 0 or current_price is None:
        return None
    peak = peak_price if (peak_price and peak_price > 0) else current_price
    gain_at_peak_pct = (peak / avg_cost - 1.0) * 100.0
    schedule = schedule or DEFAULT_SCHEDULE
    selected = None
    for threshold_pct, kind, value in schedule:
        if gain_at_peak_pct >= threshold_pct:
            selected = (kind, value)
    if selected is None:
        return {"stop_price": None, "gain_pct_at_peak": gain_at_peak_pct, "trail_kind": "none"}

    kind, value = selected
    if kind == "breakeven":
        stop = avg_cost
    else:  # "trail_pct"
        stop = peak * (1.0 - value / 100.0)
    return {
        "stop_price": round(stop, 2),
        "gain_pct_at_peak": round(gain_at_peak_pct, 2),
        "trail_kind": kind,
    }


def evaluate(
    holdings: Iterable[dict],
    market_data: dict,
    holding_days_map: dict | None = None,
    settings: dict | None = None,
) -> list[dict]:
    """Compute trailing-stop status per holding.

    Returns a list of dicts. Only holdings where the trailing stop is *active*
    (i.e. current gain ≥ first schedule threshold) are included. When the
    stop is breached (current_price ≤ stop_price), the dict has
    `breached: True` and `recommended_action: "TRIM"`.
    """
    settings = settings or {}
    schedule = settings.get("trailing_stop_schedule") or DEFAULT_SCHEDULE
    holding_days_map = holding_days_map or {}
    out: list[dict] = []

    for holding in holdings or []:
        ticker = holding.get("ticker")
        if not ticker or ticker == "CASH":
            continue
        avg_cost = holding.get("avg_cost_market")
        data = (market_data or {}).get(ticker) or {}
        current_price = data.get("current_price")
        history = data.get("history") or []

        days_info = holding_days_map.get(ticker) or {}
        earliest_open = days_info.get("earliest_open_buy")  # ISO yyyy-mm-dd or None
        peak = _peak_close_since(history, earliest_open)

        result = compute_trailing_stop(avg_cost, current_price, peak, schedule=schedule)
        if not result or result.get("trail_kind") == "none":
            continue

        stop_price = result["stop_price"]
        gain_pct_now = (current_price / avg_cost - 1.0) * 100.0 if avg_cost else 0.0
        breached = current_price is not None and stop_price is not None and current_price <= stop_price

        out.append(
            {
                "ticker": ticker,
                "trail_kind": result["trail_kind"],
                "avg_cost": round(float(avg_cost), 2),
                "current_price": round(float(current_price), 2),
                "peak_price": round(float(peak), 2) if peak else None,
                "stop_price": stop_price,
                "current_gain_pct": round(gain_pct_now, 2),
                "peak_gain_pct": result["gain_pct_at_peak"],
                "breached": bool(breached),
                "recommended_action": "TRIM" if breached else "HOLD",
            }
        )

    # Sort breached first, then by largest peak gain
    out.sort(key=lambda r: (not r["breached"], -(r["peak_gain_pct"] or 0)))
    return out


def format_for_prompt(alerts: list[dict]) -> str:
    """Render a Claude-friendly trailing-stop block.

    Empty when there's nothing actionable.
    """
    if not alerts:
        return ""
    lines = ["TRAILING STOPS (auto-tightened as positions appreciate):"]
    breached = [a for a in alerts if a["breached"]]
    if breached:
        lines.append("  ⚠ BREACHED — these stops have been triggered, generate TRIM:")
        for a in breached:
            lines.append(
                f"    - {a['ticker']}: peak ${a['peak_price']:.2f} (+{a['peak_gain_pct']:.0f}%), "
                f"now ${a['current_price']:.2f} (+{a['current_gain_pct']:.0f}%), "
                f"stop ${a['stop_price']:.2f} ({a['trail_kind']})"
            )

    active = [a for a in alerts if not a["breached"]]
    if active:
        lines.append("  Active (informational — keep your stop here, do not loosen):")
        for a in active[:8]:
            lines.append(
                f"    - {a['ticker']}: stop ${a['stop_price']:.2f} ({a['trail_kind']}), "
                f"peak +{a['peak_gain_pct']:.0f}%, now +{a['current_gain_pct']:.0f}%"
            )
    return "\n".join(lines)
