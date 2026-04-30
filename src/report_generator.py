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

from src.constants import LEVERAGED_ETFS

ACTION_EMOJI = {
    "BUY":  "🟢",
    "ADD":  "🟡",
    "HOLD": "⚪",
    "TRIM": "🟠",
    "SELL": "🔴",
}

HOLD_TIER_LABEL = {
    "watch":       "⚠️ HOLD-WATCH",
    "keep":        "✅ HOLD-KEEP",
    "add_on_dip":  "💡 HOLD (add on dip)",
}

CONVICTION_BAR = {
    range(1, 4): "▓░░░░░░░░░",
    range(4, 6): "▓▓▓▓░░░░░░",
    range(6, 8): "▓▓▓▓▓▓░░░░",
    range(8, 10): "▓▓▓▓▓▓▓▓░░",
    range(10, 11): "▓▓▓▓▓▓▓▓▓▓",
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
        tickers = ", ".join(data.get("tickers", []))
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


def _table_cell(value) -> str:
    """Make arbitrary text safe for a markdown table cell."""
    if value is None:
        return ""
    return str(value).replace("\n", " ").replace("|", "\\|").strip()


def _render_fee_assumptions_section(settings: dict) -> list[str]:
    fee_model = settings.get("fee_model") or {}
    account_type = settings.get("account_type", "wealthsimple_premium_usd")
    lines = [
        "## Fee & FX Assumptions",
        "",
        "| Item | Assumption |",
        "|---|---|",
        f"| Account type | `{account_type}` |",
        f"| Commission | ${fee_model.get('commission', 0):.2f} per trade |",
        f"| FX spread in trade hurdle | {fee_model.get('fx_spread_pct', 0):.2f}% |",
        f"| Bid/ask tiers | megacap {fee_model.get('bid_ask_megacap_pct', 0):.2f}%, midcap {fee_model.get('bid_ask_midcap_pct', 0):.2f}%, smallcap {fee_model.get('bid_ask_smallcap_pct', 0):.2f}% one-way |",
        f"| US regulatory fee estimate | ${fee_model.get('regulatory_per_us_trade_usd', 0):.2f} per US trade |",
        "| FX note | USD-account trades assume USD cash is already available; CAD-to-USD conversion costs are not included unless cash must be converted before execution. |",
        "",
        "---",
        "",
    ]
    return lines


def _render_data_quality_section(market_data: dict) -> list[str]:
    if not market_data:
        return []

    rows = []
    fallback_count = 0
    error_count = 0
    for ticker, data in sorted(market_data.items()):
        if data.get("error"):
            error_count += 1
            rows.append((ticker, "ERROR", "", "", "", data.get("error", "")))
            continue
        if data.get("price_basis") == "daily_history_close":
            fallback_count += 1
        rows.append((
            ticker,
            f"${data.get('current_price', 'N/A')} {data.get('currency', '')}",
            f"${data.get('previous_close'):,.2f}" if data.get("previous_close") else "N/A",
            f"{data.get('change_pct_1d'):+.2f}%" if data.get("change_pct_1d") is not None else "N/A",
            data.get("quote_timestamp_utc") or "N/A",
            data.get("quote_source") or "N/A",
        ))

    lines = [
        "## Quote & Data Quality",
        "",
        f"_Market data source: yfinance. Provider quotes may be delayed. Fallback daily-close quotes: {fallback_count}; ticker errors: {error_count}._",
        "",
        "| Ticker | Quote | Previous Close | 1D Move | Quote Time (UTC) | Source |",
        "|---|---:|---:|---:|---|---|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_table_cell(v) for v in row) + " |")
    lines += ["", "---", ""]
    return lines


def _render_catalyst_section(market_data: dict, news_by_ticker: dict, threshold_pct: float) -> list[str]:
    if not market_data:
        return []

    movers = []
    for ticker, data in market_data.items():
        move = data.get("change_pct_1d")
        if move is None or abs(move) < threshold_pct:
            continue
        articles = (news_by_ticker or {}).get(ticker) or []
        usable = [
            a for a in articles
            if a.get("title") and not a.get("title", "").lower().startswith("error fetching news")
        ]
        if usable:
            top = usable[0]
            headline = top.get("title", "")
            if top.get("link"):
                headline = f"[{headline}]({top['link']})"
            catalyst = f"{headline} ({top.get('publisher', 'source unknown')}, {top.get('published_at', 'time unknown')})"
        else:
            catalyst = "No fresh headline found by the news layer; manually verify catalyst before trading."
        movers.append((ticker, move, catalyst))

    if not movers:
        return []

    lines = [
        f"## Large-Move Catalyst Check (>|{threshold_pct:.0f}%|)",
        "",
        "| Ticker | 1D Move | Catalyst / Top Headline |",
        "|---|---:|---|",
    ]
    for ticker, move, catalyst in sorted(movers, key=lambda x: -abs(x[1])):
        lines.append(f"| **{ticker}** | {move:+.2f}% | {_table_cell(catalyst)} |")
    lines += ["", "---", ""]
    return lines


def _render_priority_actions_section(priority_actions: list, recommendations: list = None) -> list[str]:
    """Render the trader-facing ordered action plan at the top of the report."""
    if not priority_actions:
        return []
    rec_by_ticker = {r.get("ticker"): r for r in recommendations or []}
    lines = [
        "## 🎯 Trader Action Plan — Review Before Trading",
        "",
        "| # | Ticker | Action | Amount | Reason | Condition |",
        "|---|---|---|---:|---|---|",
    ]
    for pa in sorted(priority_actions, key=lambda x: x.get("order", 99)):
        ticker = pa.get("ticker", "")
        action = pa.get("action", "")
        emoji  = ACTION_EMOJI.get(action, "⚪")
        amount = pa.get("invest_amount_usd")
        shares = pa.get("shares")
        if amount:
            size_str = f"${amount:,.0f} USD"
        elif shares:
            size_str = f"{shares} sh"
        else:
            size_str = "—"
        rationale = pa.get("rationale", "")
        rec = rec_by_ticker.get(ticker) or {}
        condition = rec.get("risk_or_invalidation") or "Confirm live quote, spread, and catalyst before execution."
        lines.append(
            f"| {pa.get('order', '–')} | **{ticker}** | {emoji} {action} | {size_str} | {_table_cell(rationale)} | {_table_cell(condition)} |"
        )
    lines += ["", "---", ""]
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
    news_by_ticker: dict = None,
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

    # ── Priority actions (do-this-today list) ─────────────────────────────
    lines += _render_priority_actions_section(
        recommendation.get("priority_actions") or [],
        recommendation.get("recommendations") or [],
    )

    # ── Data quality and cost assumptions ─────────────────────────────────
    lines += _render_data_quality_section(market_data or {})
    lines += _render_fee_assumptions_section(settings)

    catalyst_threshold = settings.get("news_catalyst_move_threshold_pct", 5)
    lines += _render_catalyst_section(market_data or {}, news_by_ticker or {}, catalyst_threshold)

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
            ticker     = rec.get("ticker", "")
            action     = rec.get("action", "HOLD")
            conviction = rec.get("conviction", 0)
            emoji      = ACTION_EMOJI.get(action, "⚪")
            hold_tier  = rec.get("hold_tier")
            earnings   = rec.get("earnings_alert")

            # Build header line — HOLD gets sub-label, earnings get badge
            action_label = action
            if action == "HOLD" and hold_tier:
                action_label = HOLD_TIER_LABEL.get(hold_tier, action)

            header = f"### {emoji} {ticker} — {action_label}"
            if earnings:
                header += "   ⚠️ _EARNINGS THIS WEEK_"
            lines += [header, ""]

            lines += [f"**Conviction:** {conviction}/10  {conviction_bar(conviction)}", ""]

            lines += [f"**Thesis:** {rec.get('thesis', 'N/A')}", ""]

            if rec.get("technical_basis"):
                lines += [f"**Technical basis:** {rec['technical_basis']}", ""]

            lines += [f"**Invalidation:** {rec.get('risk_or_invalidation', 'N/A')}", ""]

            md = market_data.get(ticker, {})
            if md and not md.get("error"):
                lines += ["| | |", "|---|---|",
                          f"| Current Price | ${md.get('current_price', 'N/A')} {md.get('currency', '')} |"]
                if md.get("change_pct_1d") is not None:
                    lines.append(f"| 1-Day Change | {md['change_pct_1d']:+.1f}% |")
                if md.get("previous_close") is not None:
                    lines.append(f"| Previous Close | ${md['previous_close']:.2f} {md.get('currency', '')} |")
                if md.get("day_low") is not None and md.get("day_high") is not None:
                    lines.append(f"| Day Range | ${md['day_low']:.2f} – ${md['day_high']:.2f} |")
                if md.get("quote_timestamp_utc"):
                    lines.append(f"| Quote Time | {md['quote_timestamp_utc']} |")
                if md.get("quote_source"):
                    lines.append(f"| Quote Source | {md['quote_source']} |")
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
                # Invest amount for buys; shares for sells/trims
                if rec.get("invest_amount_usd") and action in ("BUY", "ADD"):
                    lines.append(f"| **Invest** | **${rec['invest_amount_usd']:,.0f} USD** (fractional ok) |")
                elif rec.get("shares"):
                    lines.append(f"| Suggested Shares | {rec['shares']} |")
                lines.append("")

            # Bottom table: expected move + exit plan
            target_exit = rec.get("target_exit_date", "")
            lo = rec.get("price_target_low_pct")
            hi = rec.get("price_target_high_pct")
            range_str = (
                f"{lo:+.0f}% / {hi:+.0f}%"
                if lo is not None and hi is not None
                else "N/A"
            )
            exit_str = target_exit if target_exit else "—"
            expected_header = "Expected Stock Move / Risk" if action in ("SELL", "TRIM") else "Expected Stock Move"
            net_header = "Expected Action Benefit" if action in ("SELL", "TRIM") else "Net After Fees"

            lines += [
                f"| {expected_header} | Fee Hurdle | {net_header} | Time Horizon | Exit Target | Price Range |",
                "|---|---|---|---|---|---|",
                f"| {rec.get('expected_move_pct', 0):+.2f}% | "
                f"{rec.get('fee_hurdle_pct', 0):.3f}% | "
                f"**{rec.get('net_expected_pct', 0):+.2f}%** | "
                f"{rec.get('time_horizon', 'N/A')} | "
                f"{exit_str} | "
                f"{range_str} |",
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
