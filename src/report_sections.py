"""
report_sections.py — markdown rendering for v1.7+ strategy gates.

Each function returns a list of markdown lines (or empty list if there's
nothing to show). Designed to be imported by report_generator.generate_markdown()
without modifying the existing rendering logic.
"""

from __future__ import annotations

from typing import Iterable


# ── Position aging ──────────────────────────────────────────────────────


def render_position_aging(holdings: Iterable[dict], holding_days_map: dict | None, settings: dict | None = None) -> list[str]:
    """Render the position aging table. Empty list when no actionable tiers."""
    from src.position_aging import annotate_holdings, aging_summary

    holding_days_map = holding_days_map or {}
    settings = settings or {}
    annotated = annotate_holdings(holdings or [], holding_days_map, settings.get("position_aging_tiers"))
    summary = aging_summary(annotated)
    counts = summary["counts"]
    if not (summary["mature_tickers"] or summary["aged_tickers"] or summary["stale_tickers"]):
        # No actionable aged/stale positions — emit a status line so the user
        # knows the gate ran without implying unknown durations are known fresh.
        if any(h.get("aging_tier") for h in annotated):
            unknown_note = ""
            if counts.get("unknown"):
                unknown_note = (
                    f" {counts['unknown']} position(s) have unknown entry dates because "
                    "they pre-date or are missing from the activities export."
                )
            return [
                "## Position Aging",
                "",
                f"_Known activity-derived ages are fresh/core only._ ({counts['fresh']} fresh, {counts['core']} core).{unknown_note}",
                "",
                "---",
                "",
            ]
        return []

    lines = [
        "## Position Aging",
        "",
        "Your strategy: 3-6 month sweet spot, 2-year hard cap. Aged positions need a fresh catalyst; stale positions are auto-trimmed.",
        "",
        "| Tier | Range | Count | Action |",
        "|---|---|---:|---|",
        f"| Fresh | 0-90 d | {counts['fresh']} | Normal evaluation |",
        f"| Core | 91-180 d | {counts['core']} | Sweet spot — hold/add on dips |",
        f"| Mature | 181-365 d | {counts['mature']} | Re-validate thesis; conviction -1 if no fresh catalyst |",
        f"| Aged | 366-730 d | {counts['aged']} | Trim candidate (needs fresh catalyst to keep) |",
        f"| Stale | >730 d | {counts['stale']} | **Auto-TRIM** (strategy rejects permanent holds) |",
        "",
    ]

    if summary["mature_tickers"]:
        lines.append("**Mature** (re-validate): " + ", ".join(summary["mature_tickers"]))
        lines.append("")
    if summary["aged_tickers"]:
        lines.append("**Aged** (trim candidates): " + ", ".join(summary["aged_tickers"]))
        lines.append("")
    if summary["stale_tickers"]:
        lines.append("**Stale** (forced exit): " + ", ".join(summary["stale_tickers"]))
        lines.append("")
    unknown_bounds = summary.get("unknown_with_lower_bound") or []
    if unknown_bounds:
        formatted = ", ".join(f"{item['ticker']} (≥{item['lower_bound_days']}d)" for item in unknown_bounds[:12])
        lines.append("**Unknown entry date** (held at least this long, entry pre-dates activities window): " + formatted)
        lines.append("")

    lines += ["---", ""]
    return lines


# ── Trailing stops ──────────────────────────────────────────────────────


def render_trailing_stops(trailing_alerts: list[dict] | None) -> list[str]:
    """Render trailing-stop status table."""
    if not trailing_alerts:
        return []
    breached = [a for a in trailing_alerts if a.get("breached")]
    active = [a for a in trailing_alerts if not a.get("breached")]
    lines = [
        "## Trailing Stops",
        "",
        "Stops auto-tighten as positions appreciate: +10% → breakeven, +20% → trail 8%, +40% → trail 12%.",
        "",
    ]

    if breached:
        lines += [
            "### ⚠️ Breached — auto-TRIM generated",
            "",
            "| Ticker | Avg Cost | Peak | Now | Stop | Peak Gain | Now Gain | Trail |",
            "|---|---:|---:|---:|---:|---:|---:|---|",
        ]
        for a in breached:
            lines.append(
                f"| **{a['ticker']}** | ${a['avg_cost']:.2f} | ${a.get('peak_price', 0):.2f} | "
                f"${a['current_price']:.2f} | ${a['stop_price']:.2f} | "
                f"{a['peak_gain_pct']:+.1f}% | {a['current_gain_pct']:+.1f}% | {a['trail_kind']} |"
            )
        lines.append("")

    if active:
        lines += [
            "### Active (informational — keep your stop here)",
            "",
            "| Ticker | Avg Cost | Peak | Now | Stop | Peak Gain | Now Gain | Trail |",
            "|---|---:|---:|---:|---:|---:|---:|---|",
        ]
        for a in active[:12]:
            lines.append(
                f"| {a['ticker']} | ${a['avg_cost']:.2f} | ${a.get('peak_price', 0):.2f} | "
                f"${a['current_price']:.2f} | ${a['stop_price']:.2f} | "
                f"{a['peak_gain_pct']:+.1f}% | {a['current_gain_pct']:+.1f}% | {a['trail_kind']} |"
            )
        lines.append("")

    lines += ["---", ""]
    return lines


# ── Sector rotation ─────────────────────────────────────────────────────


def render_sector_rotation(market_context: dict | None, previous_market_context: dict | None, settings: dict | None = None) -> list[str]:
    """Render sector rotation leadership table + rotation arrows."""
    if not market_context:
        return []
    from src.sector_rotation import classify

    settings = settings or {}
    universe = settings.get("sector_rotation_tickers")
    result = classify(market_context, previous_market_context=previous_market_context, sector_universe=universe)
    leaders = result["leaders"]
    laggards = result["laggards"]
    rotating_in = result["rotating_in"]
    rotating_out = result["rotating_out"]
    if not leaders and not laggards:
        return []

    lines = [
        "## Sector Rotation",
        "",
        "1-month relative strength of sector ETFs. Leaders persist for several weeks once they shift.",
        "",
    ]

    if leaders:
        leader_str = " | ".join(f"**{r['ticker']}** ({r['change_pct']:+.1f}%)" for r in leaders)
        lines.append(f"**Leaders:** {leader_str}")
        lines.append("")
    if laggards:
        laggard_str = " | ".join(f"{r['ticker']} ({r['change_pct']:+.1f}%)" for r in laggards)
        lines.append(f"**Laggards:** {laggard_str}")
        lines.append("")

    if rotating_in or rotating_out:
        lines += [
            "| Direction | Sectors | Trade Bias |",
            "|---|---|---|",
        ]
        if rotating_in:
            lines.append(f"| ⤴ Rotating IN | {', '.join(rotating_in)} | Add — leadership tends to persist |")
        if rotating_out:
            lines.append(f"| ⤵ Rotating OUT | {', '.join(rotating_out)} | Trim before underperformance compounds |")
        lines.append("")

    lines += ["---", ""]
    return lines


# ── Drawdown / VIX status banner ────────────────────────────────────────


def render_market_state_banner(drawdown_state: dict | None, market_context: dict | None, vix_multiplier_applied: float | None) -> list[str]:
    """Top-of-report banner showing active risk modifiers."""
    has_drawdown = drawdown_state and drawdown_state.get("triggered")
    macro = (market_context or {}).get("macro") if market_context else None
    vix = macro.get("vix") if isinstance(macro, dict) else None
    has_vix_adjustment = vix_multiplier_applied is not None and vix_multiplier_applied != 1.0
    if not (has_drawdown or has_vix_adjustment):
        return []

    lines = ["## Active Risk Modifiers", ""]

    if has_drawdown:
        dd = drawdown_state
        lines += [
            f"⚠️ **DRAWDOWN CIRCUIT BREAKER ACTIVE** — portfolio is "
            f"**{dd.get('drawdown_pct', 0):+.1f}%** from {dd.get('peak_label', '30d peak')} "
            f"(threshold {dd.get('threshold_pct', -6):.1f}%).",
            "",
            "Effect on this session:",
            "- All BUY recommendations downgraded to HOLD-watch.",
            "- All ADD invest amounts halved.",
            "- HOLD positions with conviction <7 forced to watch tier.",
            "",
        ]

    if has_vix_adjustment:
        vix_str = f"VIX = **{vix:.1f}** → " if isinstance(vix, (int, float)) else ""
        lines += [
            f"📉 **VIX-regime sizing**: {vix_str}all invest amounts × **{vix_multiplier_applied}**.",
            "",
        ]

    lines += ["---", ""]
    return lines


# ── Tranched plan rendering (per-recommendation insert) ─────────────────


def render_entry_or_exit_plan(rec: dict) -> list[str]:
    """Render a recommendation's entry_plan or exit_plan as a small table.

    Returns empty list when the rec has neither plan.
    """
    plan = rec.get("entry_plan") or rec.get("exit_plan")
    if not isinstance(plan, list) or not plan:
        return []

    is_entry = bool(rec.get("entry_plan"))
    label = "Entry Plan" if is_entry else "Exit Plan"
    auto_flag = rec.get("entry_plan_auto_generated") if is_entry else rec.get("exit_plan_auto_generated")
    suffix = "  _(auto-generated tranches; override by overriding entry_plan in the JSON)_" if auto_flag else ""

    lines = [
        f"**{label}** (3-step tranches){suffix}",
        "",
        "| Trigger | Fraction | Price % from now | Note |",
        "|---|---:|---:|---|",
    ]
    for tranche in plan:
        try:
            frac = float(tranche.get("fraction", 0)) * 100
            price_pct = float(tranche.get("price_pct", 0))
            lines.append(f"| {tranche.get('trigger', '?')} | {frac:.0f}% | {price_pct:+.1f}% | {tranche.get('note', '')} |")
        except (TypeError, ValueError):
            continue
    lines.append("")
    return lines
