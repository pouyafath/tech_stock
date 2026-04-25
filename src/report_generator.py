"""
report_generator.py
Formats Claude's JSON recommendation into a readable markdown report.

Adds workflow-polish sections (Phase 5):
  - Sector Exposure
  - Tax-Loss Harvest Candidates
  - Watchlist Price Alerts
  - What Changed Since Last Session (drift)
  - Leveraged ETF Warnings
  - Track Record
"""

from datetime import datetime
from pathlib import Path


ACTION_EMOJI = {
    "BUY": "🟢",
    "ADD": "🟡",
    "HOLD": "⚪",
    "TRIM": "🟠",
    "SELL": "🔴",
}

CONVICTION_BAR = {
    range(1, 4): "▓░░░░░░░░░",
    range(4, 6): "▓▓▓▓░░░░░░",
    range(6, 8): "▓▓▓▓▓▓░░░░",
    range(8, 10): "▓▓▓▓▓▓▓▓░░",
    range(10, 11): "▓▓▓▓▓▓▓▓▓▓",
}

# Daily-reset 2x/3x leveraged ETFs — should not be held > ~14 days due to decay.
LEVERAGED_ETFS = {
    "SOXL", "SOXS", "TQQQ", "SQQQ", "UPRO", "UVXY", "TMF", "TZA", "SPXL",
    "LABU", "LABD", "TSLL", "NVDL", "TMV", "UDOW", "SDOW", "FAS", "FAZ",
    "TNA", "TZA", "YINN", "YANG",
}


def conviction_bar(score: int) -> str:
    if score is None:
        return "░░░░░░░░░░"
    for r, bar in CONVICTION_BAR.items():
        if score in r:
            return bar
    return "░░░░░░░░░░"


# ── Helpers for Phase 5 sections ──────────────────────────────────────────────

def tax_loss_candidates(holdings: list, threshold_pct: float = -15) -> list[dict]:
    """
    Find positions sitting on losses ≥ |threshold_pct| % — candidates for
    tax-loss harvesting.
    """
    out = []
    for h in holdings or []:
        if h.get("ticker") == "CASH":
            continue
        pnl_pct = h.get("unrealized_pnl_pct")
        if pnl_pct is None:
            continue
        if pnl_pct <= threshold_pct:
            out.append({
                "ticker": h.get("ticker", ""),
                "name": h.get("name", ""),
                "pnl_pct": pnl_pct,
                "pnl": h.get("unrealized_pnl"),
                "pnl_currency": h.get("unrealized_pnl_currency", ""),
                "market_value": h.get("market_value"),
                "market_value_currency": h.get("market_value_currency", ""),
            })
    return sorted(out, key=lambda x: x["pnl_pct"])


def leveraged_etf_warnings(
    holdings: list,
    activities: list,
    max_hold_days: int = 14,
) -> list[dict]:
    """
    Flag any leveraged ETF holding whose earliest unsold buy is older than
    max_hold_days. Falls back to "held — duration unknown" when activity
    data is missing.
    """
    if not holdings:
        return []

    # Build {ticker: earliest_buy_date} from activities (if provided)
    earliest_buy = {}
    for a in activities or []:
        ticker = a.get("ticker", "")
        if ticker not in LEVERAGED_ETFS:
            continue
        sub = (a.get("sub_type") or "").upper()
        if "BUY" not in sub:
            continue
        date_str = a.get("date")
        if not date_str:
            continue
        prev = earliest_buy.get(ticker)
        if prev is None or date_str < prev:
            earliest_buy[ticker] = date_str

    today = datetime.now().date()
    warnings = []
    for h in holdings:
        ticker = h.get("ticker", "")
        if ticker not in LEVERAGED_ETFS:
            continue
        if not h.get("quantity"):
            continue

        buy_date_str = earliest_buy.get(ticker)
        days_held = None
        if buy_date_str:
            try:
                buy_date = datetime.strptime(buy_date_str, "%Y-%m-%d").date()
                days_held = (today - buy_date).days
            except ValueError:
                days_held = None

        if days_held is None or days_held > max_hold_days:
            warnings.append({
                "ticker": ticker,
                "days_held": days_held,
                "max_hold_days": max_hold_days,
                "pnl_pct": h.get("unrealized_pnl_pct"),
                "market_value": h.get("market_value"),
            })
    return warnings


def watchlist_price_alerts(watchlist: dict, market_data: dict) -> list[dict]:
    """
    Build alerts when current price crosses watchlist target_entry_price
    (entry zone) or target_exit_price (exit zone).

    Supports both new schema (list of dicts with target prices) and old flat
    schema (skipped silently).
    """
    if not watchlist or not market_data:
        return []

    entries = watchlist.get("entries") or []
    if not isinstance(entries, list):
        return []

    alerts = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ticker = entry.get("ticker")
        if not ticker:
            continue
        md = market_data.get(ticker, {})
        if md.get("error"):
            continue
        price = md.get("current_price")
        if price is None:
            continue

        target_entry = entry.get("target_entry_price")
        target_exit = entry.get("target_exit_price")

        if target_entry is not None and price <= target_entry:
            alerts.append({
                "ticker": ticker,
                "kind": "entry",
                "price": price,
                "target": target_entry,
                "message": f"crossed below target entry ${target_entry:.2f} (now ${price:.2f})",
            })
        if target_exit is not None and price >= target_exit:
            alerts.append({
                "ticker": ticker,
                "kind": "exit",
                "price": price,
                "target": target_exit,
                "message": f"crossed above target exit ${target_exit:.2f} (now ${price:.2f})",
            })

    return alerts


# ── Markdown rendering ────────────────────────────────────────────────────────

def _render_sector_section(sector_exposure: dict, threshold_pct: float = 40) -> list[str]:
    if not sector_exposure:
        return []
    lines = ["## Sector Exposure", ""]
    lines.append("| Sector | % | Value (CAD) | Tickers | |")
    lines.append("|---|---:|---:|---|---|")
    for sector, data in sector_exposure.items():
        flag = " ⚠️" if data.get("pct", 0) > threshold_pct else ""
        tickers = ", ".join(data.get("tickers", [])[:8])
        lines.append(
            f"| {sector} | {data['pct']:.1f}% | ${data['value_cad']:,.0f} | {tickers} | {flag} |"
        )
    lines += ["", "---", ""]
    return lines


def _render_tax_loss_section(holdings: list, threshold_pct: float = -15) -> list[str]:
    candidates = tax_loss_candidates(holdings, threshold_pct)
    if not candidates:
        return []
    lines = [
        "## Tax-Loss Harvest Candidates",
        "",
        f"_Positions down {threshold_pct}% or worse — consider harvesting losses to offset gains._",
        "",
        "| Ticker | P&L % | P&L | Market Value |",
        "|---|---:|---:|---:|",
    ]
    for c in candidates:
        pnl = c["pnl"] or 0
        mv = c["market_value"] or 0
        cur = c.get("pnl_currency", "")
        lines.append(
            f"| **{c['ticker']}** | {c['pnl_pct']:+.1f}% | ${pnl:+,.0f} {cur} | ${mv:,.0f} |"
        )
    lines += ["", "---", ""]
    return lines


def _render_alerts_section(alerts: list) -> list[str]:
    if not alerts:
        return []
    lines = ["## Watchlist Price Alerts", ""]
    for a in alerts:
        emoji = "🟢" if a["kind"] == "entry" else "🔴"
        lines.append(f"- {emoji} **{a['ticker']}**: {a['message']}")
    lines += ["", "---", ""]
    return lines


def _render_drift_section(drift: list) -> list[str]:
    if not drift:
        return []
    lines = ["## What Changed Since Last Session", ""]

    by_type = {}
    for d in drift:
        by_type.setdefault(d["drift_type"], []).append(d)

    type_labels = {
        "action_flip":     "🔀 Action flips",
        "conviction_jump": "📈 Conviction jumps",
        "sign_flip":       "↕️ Net-expected sign flips",
        "new_ticker":      "✨ New tickers",
        "dropped_ticker":  "🗑 Dropped tickers",
    }

    for drift_type, label in type_labels.items():
        items = by_type.get(drift_type)
        if not items:
            continue
        lines.append(f"**{label}**")
        for d in items:
            was = d.get("was") or {}
            now = d.get("now") or {}
            was_str = f"{was.get('action', '–')}/{was.get('conviction', '–')}" if was else "—"
            now_str = f"{now.get('action', '–')}/{now.get('conviction', '–')}" if now else "—"
            lines.append(f"- **{d['ticker']}** — was `{was_str}` → now `{now_str}`")
        lines.append("")
    lines += ["---", ""]
    return lines


def _render_track_record_section(backtest_summary: dict) -> list[str]:
    if not backtest_summary or backtest_summary.get("n_samples", 0) == 0:
        return []
    lines = ["## Track Record", ""]
    lines.append(f"_Based on {backtest_summary['n_samples']} mature recommendations from prior sessions._")
    lines.append("")

    overall = backtest_summary.get("overall", {})
    if overall.get("n"):
        lines.append(
            f"**Overall:** n={overall['n']}, "
            f"avg actual return = **{overall['avg_return_pct']:+.2f}%**, "
            f"hit rate = **{overall['hit_rate']:.0%}**"
        )
        lines.append("")

    by_action = backtest_summary.get("avg_return_by_action", {})
    if by_action:
        lines += [
            "**By action:**",
            "",
            "| Action | n | Avg Return | Win Rate |",
            "|---|---:|---:|---:|",
        ]
        for action, stats in by_action.items():
            lines.append(
                f"| {action} | {stats['n']} | {stats['avg_return_pct']:+.2f}% | {stats['hit_rate']:.0%} |"
            )
        lines.append("")

    by_conv = backtest_summary.get("avg_return_by_conviction", {})
    if by_conv:
        lines += [
            "**By conviction:**",
            "",
            "| Conviction | n | Avg Return | Win Rate |",
            "|---|---:|---:|---:|",
        ]
        for conv in sorted(by_conv.keys()):
            stats = by_conv[conv]
            lines.append(
                f"| {conv} | {stats['n']} | {stats['avg_return_pct']:+.2f}% | {stats['hit_rate']:.0%} |"
            )
        lines.append("")

    lines += ["---", ""]
    return lines


def _render_leveraged_etf_section(warnings: list) -> list[str]:
    if not warnings:
        return []
    lines = [
        "## ⚠️ Leveraged ETF Decay Warning",
        "",
        "_Daily-reset 2x/3x ETFs significantly underperform the implied multiple over time due to volatility decay._",
        "",
    ]
    for w in warnings:
        held = f"{w['days_held']} days" if w.get("days_held") is not None else "duration unknown"
        pnl = w.get("pnl_pct")
        pnl_str = f" | P&L {pnl:+.1f}%" if pnl is not None else ""
        lines.append(
            f"- **{w['ticker']}** — held {held} (cap: {w['max_hold_days']} days){pnl_str}"
        )
    lines += ["", "---", ""]
    return lines


# ── Main entrypoint ───────────────────────────────────────────────────────────

def generate_markdown(
    session_type: str,
    recommendation: dict,
    market_data: dict,
    portfolio: dict = None,
    sector_exposure: dict = None,
    backtest_summary: dict = None,
    drift: list = None,
    price_alerts: list = None,
    recent_activities: list = None,
    settings: dict = None,
) -> str:
    """Generate the full markdown report from Claude's JSON output + extras."""
    settings = settings or {}
    portfolio = portfolio or {}
    holdings = portfolio.get("holdings", [])

    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H:%M")
    date_str = now.strftime("%Y-%m-%d")

    lines = [
        f"# Tech Stock Advisor — {session_type.capitalize()} Report",
        f"**Generated:** {timestamp}  |  **Session:** {session_type.upper()}",
        "",
        "---",
        "",
        "## Market Overview",
        "",
        recommendation.get("session_summary", "_No summary provided._"),
        "",
        "---",
        "",
        "## Portfolio Health",
        "",
    ]

    ph = recommendation.get("portfolio_health", {})
    if ph:
        lines += [
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total Value (USD equiv.) | ${ph.get('total_value_usd_equivalent', 0):,.0f} |",
            f"| Overall P&L | {ph.get('overall_pnl_pct', 0):+.1f}% |",
            f"| Concentration Risk | {ph.get('concentration_risk', 'N/A').upper()} |",
            f"| Cash Deployment | {ph.get('cash_deployment', 'N/A')} |",
        ]
    lines += ["", "---", ""]

    # ── New sections (Phase 4 + 5) ─────────────────────────────────────────
    threshold_pct = settings.get("sector_concentration_threshold_pct", 40)
    lines += _render_sector_section(sector_exposure or {}, threshold_pct)

    lines += _render_alerts_section(price_alerts or [])

    lines += _render_drift_section(drift or [])

    lines += _render_track_record_section(backtest_summary or {})

    tax_threshold = settings.get("tax_loss_threshold_pct", -15)
    lines += _render_tax_loss_section(holdings, tax_threshold)

    max_hold = settings.get("leveraged_etf_max_hold_days", 14)
    lev_warnings = leveraged_etf_warnings(holdings, recent_activities or [], max_hold)
    lines += _render_leveraged_etf_section(lev_warnings)

    # ── Recommendations ────────────────────────────────────────────────────
    lines += ["## Recommendations", ""]
    recs = recommendation.get("recommendations", [])
    if not recs:
        lines.append("_No recommendations this session._")
    else:
        for rec in recs:
            ticker = rec.get("ticker", "")
            action = rec.get("action", "HOLD")
            conviction = rec.get("conviction", 0)
            emoji = ACTION_EMOJI.get(action, "⚪")

            lines += [
                f"### {emoji} {ticker} — {action}",
                "",
                f"**Conviction:** {conviction}/10  {conviction_bar(conviction)}",
                "",
                f"**Thesis:** {rec.get('thesis', 'N/A')}",
                "",
            ]
            if rec.get("technical_basis"):
                lines += [f"**Technical basis:** {rec['technical_basis']}", ""]
            lines += [
                f"**Invalidation:** {rec.get('risk_or_invalidation', 'N/A')}",
                "",
            ]

            md = market_data.get(ticker, {})
            if md and not md.get("error"):
                lines += [
                    f"| | |",
                    f"|---|---|",
                    f"| Current Price | ${md.get('current_price', 'N/A')} {md.get('currency', '')} |",
                ]
                if md.get("change_pct_1d") is not None:
                    lines.append(f"| 1-Day Change | {md['change_pct_1d']:+.1f}% |")
                if md.get("pct_from_52w_high") is not None:
                    lines.append(f"| From 52w High | {md['pct_from_52w_high']:+.1f}% |")
                ind = md.get("indicators") or {}
                if ind.get("rsi_14") is not None:
                    lines.append(f"| RSI(14) | {ind['rsi_14']:.1f} |")
                if ind.get("macd_hist") is not None:
                    lines.append(f"| MACD hist | {ind['macd_hist']:+.3f} |")
                if ind.get("price_vs_sma200_pct") is not None:
                    lines.append(f"| vs SMA(200) | {ind['price_vs_sma200_pct']:+.1f}% |")
                if rec.get("liquidity_tier"):
                    lines.append(f"| Liquidity Tier | {rec['liquidity_tier']} |")
                if rec.get("target_entry_or_exit"):
                    lines.append(f"| Target Entry/Exit | ${rec['target_entry_or_exit']:.2f} |")
                if rec.get("shares"):
                    lines.append(f"| Suggested Shares | {rec['shares']} |")
                lines.append("")

            lines += [
                f"| Expected Move | Fee Hurdle | Net Expected | Time Horizon |",
                f"|---|---|---|---|",
                f"| {rec.get('expected_move_pct', 0):+.2f}% | "
                f"{rec.get('fee_hurdle_pct', 0):.3f}% | "
                f"**{rec.get('net_expected_pct', 0):+.2f}%** | "
                f"{rec.get('time_horizon', 'N/A')} |",
                "",
                "---",
                "",
            ]

    # ── Watchlist flags from Claude ────────────────────────────────────────
    flags = recommendation.get("watchlist_flags", [])
    if flags:
        lines += ["## Watchlist Flags", ""]
        for flag in flags:
            lines.append(f"- **{flag.get('ticker', '')}**: {flag.get('why_noteworthy', '')}")
        lines += ["", "---", ""]

    # ── Sector warnings from Claude ────────────────────────────────────────
    sector_warns = recommendation.get("sector_warnings", []) or []
    if sector_warns:
        lines += ["## Sector Warnings", ""]
        for w in sector_warns:
            lines.append(f"- {w}")
        lines += ["", "---", ""]

    # ── General warnings ──────────────────────────────────────────────────
    warnings = recommendation.get("warnings", [])
    if warnings:
        lines += ["## ⚠️ Warnings", ""]
        for w in warnings:
            lines.append(f"- {w}")
        lines += ["", "---", ""]

    lines += [
        "_Recommendations are advisory only. Execute trades manually in Wealthsimple._",
        f"_Report saved: {date_str}_",
    ]

    return "\n".join(lines)


def save_report(content: str, session_type: str, reports_dir: Path) -> Path:
    """Save the markdown report to the reports/ directory."""
    reports_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"{timestamp}_{session_type}.md"
    path = reports_dir / filename
    path.write_text(content, encoding="utf-8")
    return path
