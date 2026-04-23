"""
report_generator.py
Formats Claude's JSON recommendation into a readable markdown report.
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


def conviction_bar(score: int) -> str:
    for r, bar in CONVICTION_BAR.items():
        if score in r:
            return bar
    return "░░░░░░░░░░"


def generate_markdown(
    session_type: str,
    recommendation: dict,
    market_data: dict,
) -> str:
    """Generate the full markdown report from Claude's JSON output."""
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

    lines += ["", "---", "", "## Recommendations", ""]

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
                f"**Invalidation:** {rec.get('risk_or_invalidation', 'N/A')}",
                "",
            ]

            # Price info from market data
            md = market_data.get(ticker, {})
            if md and not md.get("error"):
                lines += [
                    f"| | |",
                    f"|---|---|",
                    f"| Current Price | ${md.get('current_price', 'N/A')} {md.get('currency', '')} |",
                    f"| 1-Day Change | {md.get('change_pct_1d', 'N/A'):+.1f}% |",
                    f"| From 52w High | {md.get('pct_from_52w_high', 'N/A'):+.1f}% |",
                ]
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

    # Watchlist flags
    flags = recommendation.get("watchlist_flags", [])
    if flags:
        lines += ["## Watchlist Flags", ""]
        for flag in flags:
            lines.append(f"- **{flag.get('ticker', '')}**: {flag.get('why_noteworthy', '')}")
        lines += ["", "---", ""]

    # Warnings
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
