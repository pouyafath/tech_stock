"""Streamlit web UI — production-grade dashboard for tech_stock.

Sections
--------
* Sidebar  : run settings, live API/update status, workspace info
* Header   : hero banner with latest-run context
* Tabs     : Dashboard · Buy Signals · Today's Report · Run · History ·
             Backtest · Decision Journal · Portfolio Editor

All visual primitives (badges, cards, metric tiles, empty states) are
delegated to ``src.ui_theme`` so the Tkinter desktop and Textual TUI can
share the same colour language.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ui_support import (  # noqa: E402
    EDITABLE_JSON_FILES,
    API_KEY_FIELDS,
    api_health_view,
    api_key_inventory,
    apply_available_update,
    buy_signal_view,
    check_update_available,
    current_app_version,
    default_run_settings,
    decision_journal_view,
    decision_scorecard_summary,
    find_default_csvs,
    latest_log_summary,
    latest_report,
    list_reports,
    preview_holdings_csv,
    read_editable_json,
    read_text_file,
    relative_to_root,
    run_backtest_summary,
    run_report_from_ui,
    delete_api_key,
    save_api_key,
    save_decision_from_ui,
    save_uploaded_bytes,
    validate_json_text,
    write_editable_json,
)
from src.ui_theme import (  # noqa: E402
    PALETTE,
    STREAMLIT_CSS,
    action_badge,
    action_card,
    conviction_bar,
    empty_state,
    hero,
    readiness_badge,
    severity_badge,
    status_dot,
    warning_row,
)


# ── Constants & helpers ─────────────────────────────────────────────────────

ANSI_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
MAX_CONSOLE_LINES = 60


def _clean_console_line(line: str) -> str:
    return ANSI_RE.sub("", line).strip()


def _stored_upload_path(uploaded, state_key: str) -> Path | None:
    if uploaded is None:
        return None
    data = uploaded.getvalue()
    fingerprint = (uploaded.name, hashlib.md5(data).hexdigest())
    if st.session_state.get(f"{state_key}_fingerprint") != fingerprint:
        path = save_uploaded_bytes(uploaded.name, data)
        st.session_state[f"{state_key}_fingerprint"] = fingerprint
        st.session_state[f"{state_key}_path"] = str(path)
    stored = st.session_state.get(f"{state_key}_path")
    return Path(stored) if stored else None


def _display_download(label: str, path: Path | None, mime: str) -> None:
    if not path or not path.exists():
        st.caption(f"{label}: unavailable")
        return
    st.caption(f"{label} — `{relative_to_root(path)}`")
    st.download_button(
        f"⬇ {label}",
        path.read_bytes(),
        file_name=path.name,
        mime=mime,
        width="stretch",
    )


def _html(snippet: str) -> None:
    """Render trusted HTML produced by ``ui_theme`` helpers."""
    st.markdown(snippet, unsafe_allow_html=True)


def _format_currency(value, currency: str = "USD") -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "—"
    if currency == "USD":
        prefix = "$"
    elif currency == "CAD":
        prefix = "C$"
    else:
        prefix = ""
    if abs(amount) >= 1_000_000:
        return f"{prefix}{amount / 1_000_000:.2f}M"
    if abs(amount) >= 1_000:
        return f"{prefix}{amount / 1_000:.1f}K"
    return f"{prefix}{amount:,.2f}"


def _format_pct(value, *, signed: bool = False, digits: int = 1) -> str:
    try:
        pct = float(value)
    except (TypeError, ValueError):
        return "—"
    fmt = f"{{:{'+' if signed else ''}.{digits}f}}%"
    return fmt.format(pct)


def _rows_from_bucket(bucket: dict, label: str) -> list[dict]:
    rows = []
    for key, stats in (bucket or {}).items():
        rows.append(
            {
                label: key,
                "n": stats.get("n", 0),
                "avg_return_pct": stats.get("avg_return_pct", 0),
                "hit_rate": stats.get("hit_rate", 0),
            }
        )
    return rows


def _render_backtest_table(title: str, rows: list[dict], index_col: str) -> None:
    with st.expander(title, expanded=bool(rows)):
        if not rows:
            _html(empty_state("No data yet", "Run a backtest to see this bucket."))
            return
        df = pd.DataFrame(rows)
        st.dataframe(df, hide_index=True, width="stretch")
        chart_df = df.set_index(index_col)
        if "avg_return_pct" in chart_df:
            st.bar_chart(chart_df["avg_return_pct"], color=PALETTE.accent)


def _resolve_run_inputs(
    holdings_mode: str,
    holdings_path_text: str,
    holdings_upload,
    activities_mode: str,
    activities_path_text: str,
    activities_upload,
) -> tuple[Path | None, Path | None]:
    holdings_path = None
    activities_path = None
    if holdings_mode == "Upload CSV":
        holdings_path = _stored_upload_path(holdings_upload, "holdings_upload")
    elif holdings_mode == "File path" and holdings_path_text.strip():
        holdings_path = Path(holdings_path_text).expanduser()
    if activities_mode == "Upload CSV":
        activities_path = _stored_upload_path(activities_upload, "activities_upload")
    elif activities_mode == "File path" and activities_path_text.strip():
        activities_path = Path(activities_path_text).expanduser()
    return holdings_path, activities_path


def _format_session_label(session_file: str) -> str:
    """Pretty-print a session log filename like ``20260513_1345_afternoon``."""
    if not session_file:
        return ""
    stem = Path(session_file).stem
    match = re.match(r"(\d{8})_(\d{4})_(\w+)", stem)
    if not match:
        return stem
    raw_date, raw_time, session = match.groups()
    try:
        dt = datetime.strptime(f"{raw_date} {raw_time}", "%Y%m%d %H%M")
    except ValueError:
        return stem
    return f"{dt.strftime('%a %d %b %Y · %H:%M')} · {session.title()}"


# ── Page setup ─────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="tech_stock — Portfolio Advisor",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get Help": "https://github.com/pouyafath/tech_stock",
        "Report a bug": "https://github.com/pouyafath/tech_stock/issues",
        "About": (
            "**tech_stock** — AI-powered portfolio advisor built on Claude.\n\n"
            "Runs a deterministic enrichment pipeline → two-pass Claude review → "
            "quality-gated recommendations with full audit trail."
        ),
    },
)
_html(STREAMLIT_CSS)


# ── Session-state warm boot ────────────────────────────────────────────────

if "boot_summary" not in st.session_state:
    st.session_state["boot_summary"] = latest_log_summary()
if "boot_health_cache" not in st.session_state:
    st.session_state["boot_health_cache"] = None  # populated on first request
if "toasts" not in st.session_state:
    st.session_state["toasts"] = []


def _toast(message: str, *, icon: str = "✅") -> None:
    """Queue a toast notification (Streamlit shows them on next rerun)."""
    st.session_state["toasts"].append((message, icon))


def _flush_toasts() -> None:
    for message, icon in st.session_state.pop("toasts", []):
        st.toast(message, icon=icon)


# ── Sidebar ─────────────────────────────────────────────────────────────────

defaults = find_default_csvs()
run_defaults = default_run_settings()

with st.sidebar:
    st.markdown(
        f"""
        <div style='padding: 8px 0 16px 0;'>
            <div style='display:flex; align-items:center; gap:10px;'>
                <div style='font-size:1.8rem;'>📈</div>
                <div>
                    <div style='font-size:1.2rem; font-weight:700; color:{PALETTE.text_strong};'>tech_stock</div>
                    <div style='color:{PALETTE.muted}; font-size:0.78rem;'>v{current_app_version()}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("## Run Settings")
    session_type = st.selectbox(
        "Session",
        ["morning", "afternoon"],
        index=0,
        help="Morning (~07:00) uses a pre-open lens; afternoon (~14:00) is a mid-day check-in.",
    )
    model_index = 1 if run_defaults["model_choice"] == "opus" else 0
    model_choice = st.selectbox(
        "Claude model",
        ["sonnet", "opus"],
        index=model_index,
        format_func=lambda value: "Sonnet 4.6 (fast, ~$0.22)" if value == "sonnet" else "Opus 4.7 (deep, ~$0.45)",
        help="Sonnet is ~90% as accurate at ~50% of the cost. Use Opus for complex portfolios or when conviction scores feel inconsistent.",
    )
    col_usd, col_cad = st.columns(2)
    with col_usd:
        budget_usd = st.number_input("USD budget", min_value=0.0, value=run_defaults["budget_usd"], step=50.0)
    with col_cad:
        budget_cad = st.number_input("CAD budget", min_value=0.0, value=run_defaults["budget_cad"], step=50.0)

    st.markdown("## Status")
    if "startup_update_checked" not in st.session_state and os.environ.get("TECH_STOCK_SKIP_UPDATE_CHECK") != "1":
        st.session_state["startup_update_checked"] = True
        st.session_state["update_info"] = check_update_available(timeout=4.0)

    update_info = st.session_state.get("update_info")
    if update_info and update_info.available:
        st.warning(f"🆙 v{update_info.latest_version} available")
        if st.button("Update now", type="primary", width="stretch"):
            with st.spinner("Downloading and applying update..."):
                result = apply_available_update(update_info, restart=True)
            if not result.ok:
                st.error(result.message)
            else:
                st.success(result.message)
                if result.restart_started:
                    time.sleep(1)
                    os._exit(0)
    elif update_info and update_info.error:
        st.caption(f"Update check failed: {update_info.error}")
    elif update_info:
        st.caption(f"✓ Up to date · v{update_info.current_version}")

    health_summary = st.session_state.get("boot_health_cache")
    if health_summary:
        ok = health_summary.get("ok_count", 0)
        fail = health_summary.get("fail_count", 0)
        dot_color = PALETTE.accent if fail == 0 else (PALETTE.warn if fail < ok else PALETTE.danger)
        _html(
            f"<div style='margin-top:6px;color:{PALETTE.muted};font-size:0.85rem;'>"
            f"<span class='ts-status-dot' style='background:{dot_color};'></span>"
            f"APIs: <strong style='color:{PALETTE.text};'>{ok}</strong> ok · "
            f"<strong style='color:{PALETTE.text};'>{fail}</strong> down"
            "</div>"
        )
    if st.button("Refresh status", width="stretch"):
        with st.spinner("Pinging APIs..."):
            st.session_state["boot_health_cache"] = api_health_view()
            st.session_state["boot_summary"] = latest_log_summary()
        _toast("Status refreshed", icon="🔄")
        st.rerun()

    st.markdown("## Workspace")
    st.caption(f"📁 `{relative_to_root(ROOT)}/`")
    if defaults.get("holdings"):
        st.caption(f"📊 Holdings: `{defaults['holdings'].name}`")
    if defaults.get("activities"):
        st.caption(f"📜 Activities: `{defaults['activities'].name}`")

    st.markdown("---")
    st.caption("Built on Claude · Anthropic")


# ── Header hero ─────────────────────────────────────────────────────────────

summary = st.session_state.get("boot_summary") or {}
session_label = _format_session_label(summary.get("session_file", "")) if summary else ""
risk = (summary or {}).get("risk_dashboard") or {}
total_value = risk.get("total_value_usd")
beta = (risk.get("beta") or {}).get("SPY")
warning_count = len(summary.get("quality_warnings") or []) if summary else 0
usage = (summary or {}).get("usage") or {}
cost = usage.get("cost_usd")

meta_parts = []
if session_label:
    meta_parts.append(f"📅 {session_label}")
if total_value is not None:
    meta_parts.append(f"💼 {_format_currency(total_value)}")
if beta is not None:
    meta_parts.append(f"β {beta:.2f}")
if cost is not None:
    meta_parts.append(f"⚡ ${cost:.4f}")
if warning_count:
    meta_parts.append(f"⚠️ {warning_count} warning{'s' if warning_count != 1 else ''}")

_html(
    hero(
        "AI Portfolio Advisor",
        "Two-pass Claude review with deterministic quality gates and full audit trail.",
        meta_parts,
    )
)


# ── Tabs ────────────────────────────────────────────────────────────────────

tab_dashboard, tab_buy, tab_report, tab_run, tab_history, tab_backtest, tab_journal, tab_editor = st.tabs(
    [
        "📊 Dashboard",
        "🎯 Buy Signals",
        "📝 Today's Report",
        "▶️ Run Report",
        "📚 History",
        "📈 Backtest",
        "📓 Journal",
        "⚙️ Editor",
    ]
)


# ─── Dashboard ─────────────────────────────────────────────────────────────


def _render_dashboard() -> None:
    col_refresh, col_meta = st.columns([1, 4])
    with col_refresh:
        if st.button("🔄 Refresh", width="stretch", key="dashboard_refresh"):
            with st.spinner("Reloading latest log..."):
                st.session_state["boot_summary"] = latest_log_summary()
            _toast("Dashboard refreshed")
    with col_meta:
        st.caption(
            f"Loaded from `{summary.get('session_file', '—')}` ({_format_session_label(summary.get('session_file', ''))})"
            if summary
            else "No logs found yet."
        )

    if not summary:
        _html(
            empty_state(
                "No recommendations logged yet",
                "Generate your first report from the Run Report tab and the dashboard will populate automatically.",
            )
        )
        return
    if summary.get("error"):
        st.error(summary["error"])
        return

    risk = summary.get("risk_dashboard") or {}
    beta = risk.get("beta") or {}
    usage = summary.get("usage") or {}

    # Hero metric strip
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric(
        "Portfolio value",
        _format_currency(risk.get("total_value_usd")),
        help="Sum of all USD-equivalent holdings reported in the latest run.",
    )
    col2.metric(
        "β vs SPY",
        f"{beta.get('SPY', 0):.2f}" if beta.get("SPY") is not None else "—",
        help="Portfolio beta against SPY (S&P 500). >1 = more volatile than the market.",
    )
    col3.metric(
        "Ann. volatility",
        _format_pct(risk.get("annualized_volatility_pct"), digits=1),
        help="Annualised standard deviation of daily returns (from holdings' 1y prices).",
    )
    col4.metric(
        "Max drawdown",
        _format_pct(risk.get("max_drawdown_estimate_pct"), signed=True, digits=1),
        help="Worst peak-to-trough decline estimated from 1y price history.",
    )
    col5.metric(
        "Top-3 concentration",
        _format_pct(risk.get("top3_concentration_pct"), digits=1),
        help="Weight of the three largest positions. >40% is a concentration flag.",
    )

    st.markdown("### Priority Actions")
    priority = summary.get("priority_actions") or []
    if not priority:
        _html(empty_state("No priority actions queued", "The latest report did not flag anything urgent."))
    else:
        for item in priority[:8]:
            _html(
                action_card(
                    item.get("ticker", ""),
                    item.get("action"),
                    item.get("rationale", ""),
                )
            )

    col_left, col_right = st.columns(2)
    with col_left:
        st.markdown("### Quality Gates")
        warnings = summary.get("quality_warnings") or []
        if not warnings:
            _html(empty_state("All gates clear ✓", "No quality warnings raised in the latest log."))
        else:
            severities = [w.get("severity", "info") for w in warnings]
            chip_counts = " · ".join(
                f"{severity_badge(s)} {severities.count(s)}"
                for s in sorted(
                    set(severities),
                    key=lambda x: (
                        ["critical", "high", "medium", "low", "info"].index(x) if x in ["critical", "high", "medium", "low", "info"] else 5
                    ),
                )
            )
            _html(f"<div style='margin-bottom:8px'>{chip_counts}</div>")
            for warning in warnings[:10]:
                _html(
                    warning_row(
                        warning.get("severity"),
                        warning.get("ticker"),
                        warning.get("message", ""),
                    )
                )
            if len(warnings) > 10:
                st.caption(f"… and {len(warnings) - 10} more")

    with col_right:
        st.markdown("### Hedge Suggestions")
        hedge = summary.get("hedge_suggestions") or []
        if not hedge:
            _html(empty_state("No hedges suggested", "Portfolio risk is within normal parameters."))
        else:
            for item in hedge[:5]:
                with st.container(border=True):
                    type_label = (item.get("type") or "hedge").replace("_", " ").title()
                    instrument = item.get("instrument", "")
                    st.markdown(f"**{instrument}** · {type_label}")
                    st.caption(item.get("action") or "—")
                    if item.get("rationale"):
                        st.caption(f"_{item.get('rationale')}_")

    col_drift, col_cost = st.columns([3, 2])
    with col_drift:
        st.markdown("### Drift vs Previous")
        drift = summary.get("drift") or []
        if not drift:
            _html(empty_state("No drift recorded", "Either this is the first run or nothing has changed."))
        else:
            rows = []
            for item in drift:
                was = item.get("was") or {}
                now = item.get("now") or {}
                rows.append(
                    {
                        "Ticker": item.get("ticker"),
                        "Type": (item.get("drift_type") or "").replace("_", " "),
                        "Was": f"{was.get('action', '')} {was.get('conviction', '')}".strip(),
                        "Now": f"{now.get('action', '')} {now.get('conviction', '')}".strip(),
                    }
                )
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    with col_cost:
        st.markdown("### Run Cost")
        if usage:
            _html(
                f"<div class='ts-metric'>"
                f"<div class='ts-metric-label'>Total cost</div>"
                f"<div class='ts-metric-value' style='color:{PALETTE.accent};'>${usage.get('cost_usd', 0):.4f}</div>"
                f"<div class='ts-metric-hint'>{usage.get('total_tokens', 0):,} tokens · "
                f"{usage.get('input_tokens', 0):,} in / {usage.get('output_tokens', 0):,} out</div>"
                "</div>"
            )
        else:
            _html(empty_state("No usage telemetry", "Run a report to see token/cost stats."))

    with st.expander("🔌 Connectivity Check (live)"):
        if st.button("Ping all APIs", key="connectivity_check"):
            with st.spinner("Checking connectivity..."):
                health = api_health_view()
                st.session_state["boot_health_cache"] = health
            _toast("Connectivity check complete", icon="🛰️")
        health = st.session_state.get("boot_health_cache")
        if health:
            ok = health.get("ok_count", 0)
            fail = health.get("fail_count", 0)
            st.caption(f"**{ok}** OK · **{fail}** unavailable · storage: `{health.get('storage_mode')}`")
            checks_df = pd.DataFrame(health.get("checks") or [])
            if not checks_df.empty:
                st.dataframe(checks_df, hide_index=True, width="stretch")

    with st.expander("🔑 API Key Manager"):
        inventory = api_key_inventory()
        if inventory:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "API": row["label"],
                            "Configured": "✓" if row["configured"] else "—",
                            "Masked value": row["masked"],
                            "Source": str(row["source_path"] or ""),
                        }
                        for row in inventory
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        labels = [f"{field['label']} ({field['env']})" for field in API_KEY_FIELDS]
        selected_label = st.selectbox("API key", labels, key="api_key_select")
        selected_env = next(field["env"] for field in API_KEY_FIELDS if selected_label.endswith(f"({field['env']})"))
        new_value = st.text_input("New API key value", type="password", key="api_key_new_value")
        c_save, c_delete = st.columns(2)
        with c_save:
            if st.button("💾 Save", width="stretch", key="api_save"):
                if not new_value.strip():
                    st.error("Paste the full API key value before saving.")
                else:
                    path = save_api_key(selected_env, new_value)
                    _toast(f"Saved {selected_env}", icon="🔐")
                    st.success(f"Saved → {path}")
        with c_delete:
            if st.button("🗑 Delete", width="stretch", key="api_delete"):
                touched = delete_api_key(selected_env)
                _toast(f"Deleted {selected_env}", icon="🗑️")
                st.warning(f"Deleted {selected_env} ({len(touched)} file(s) changed)")


with tab_dashboard:
    _render_dashboard()


# ─── Buy Signals ───────────────────────────────────────────────────────────


def _render_buy_signals() -> None:
    st.caption("Source-backed snapshots from the latest log plus refreshed yfinance, Finnhub, and quality-gate data.")
    col_a, col_b, col_c = st.columns([2, 2, 1])
    with col_a:
        action_filter_label = st.selectbox(
            "Action filter",
            ["All actions", "BUY/ADD", "add_on_dip"],
            key="buy_action_filter",
        )
    with col_b:
        readiness_filter_label = st.selectbox(
            "Readiness filter",
            ["All readiness", "Trade Ready", "Review First", "Blocked"],
            key="buy_readiness_filter",
        )
    with col_c:
        st.markdown("&nbsp;")  # spacing
        refresh = st.button("🔄 Refresh", type="primary", width="stretch", key="buy_refresh")

    action_filter = {"BUY/ADD": "buy_add", "add_on_dip": "add_on_dip"}.get(action_filter_label, "all")
    readiness_filter = {
        "Trade Ready": "TRADE_READY",
        "Review First": "REVIEW_FIRST",
        "Blocked": "BLOCKED",
    }.get(readiness_filter_label, "all")

    if refresh:
        with st.spinner("Re-pulling source data and quality gates..."):
            st.session_state["buy_signal_insights"] = buy_signal_view(action_filter=action_filter, readiness_filter=readiness_filter)
        _toast("Buy signals refreshed", icon="🎯")

    buy_data = st.session_state.get("buy_signal_insights")
    if not buy_data:
        _html(
            empty_state(
                "No buy signals loaded",
                "Click Refresh to pull live data for BUY / ADD / add-on-dip candidates.",
            )
        )
        return
    if buy_data.get("error"):
        st.error(buy_data["error"])
        return

    counts = buy_data.get("counts") or {}
    col_ready, col_review, col_blocked, col_total = st.columns(4)
    col_ready.metric("✅ Trade Ready", counts.get("TRADE_READY", 0))
    col_review.metric("⚠️ Review First", counts.get("REVIEW_FIRST", 0))
    col_blocked.metric("🛑 Blocked", counts.get("BLOCKED", 0))
    col_total.metric("Total", counts.get("total", len(buy_data.get("cards") or [])))

    st.caption(f"Source: `{buy_data.get('session_file')}` · fetched {buy_data.get('fetched_at') or '—'}")

    candidates = buy_data.get("cards") or buy_data.get("candidates") or []
    if not candidates:
        _html(empty_state("No candidates match filters", "Try relaxing the action or readiness filter."))
        return

    sub_overview, sub_consensus, sub_catalysts, sub_sources = st.tabs(["Overview", "Consensus & Targets", "Catalysts & Risk", "Sources"])

    with sub_overview:
        if buy_data.get("overview_rows"):
            st.dataframe(pd.DataFrame(buy_data["overview_rows"]), hide_index=True, width="stretch")
        for item in candidates:
            readiness = item.get("readiness") or {}
            with st.container(border=True):
                head_col1, head_col2 = st.columns([3, 2])
                with head_col1:
                    _html(
                        f"<div style='display:flex;align-items:center;gap:10px;'>"
                        f"<span style='font-size:1.15rem;font-weight:700;letter-spacing:0.05em;color:{PALETTE.text_strong};'>"
                        f"{item.get('ticker', '')}</span>"
                        f"{action_badge(item.get('action') or item.get('hold_tier'))}"
                        f"{readiness_badge(readiness.get('code') or readiness.get('label'))}"
                        f"{conviction_bar(item.get('conviction'))}"
                        "</div>"
                    )
                with head_col2:
                    price = item.get("current_price")
                    qsrc = item.get("quote_source") or "—"
                    st.caption(f"💵 {price} · {qsrc}")
                if item.get("thesis"):
                    st.write(item["thesis"])
                if readiness.get("reasons"):
                    st.caption("· ".join(readiness["reasons"]))

    with sub_consensus:
        if buy_data.get("consensus_rows"):
            st.dataframe(pd.DataFrame(buy_data["consensus_rows"]), hide_index=True, width="stretch")
        else:
            _html(empty_state("No analyst consensus data", "Finnhub/Polygon may not have coverage for these tickers."))

    with sub_catalysts:
        for item in candidates:
            with st.expander(f"{item.get('ticker')} — {item.get('action') or item.get('hold_tier')}"):
                readiness = item.get("readiness") or {}
                st.markdown(f"**Readiness:** {readiness.get('label')}")
                if readiness.get("reasons"):
                    st.caption("· ".join(readiness["reasons"]))
                st.markdown(
                    f"**Quote:** {item.get('current_price')} · "
                    f"{item.get('quote_source') or 'unavailable'} · "
                    f"`{item.get('quote_timestamp_utc') or 'missing'}`"
                )
                st.markdown(f"**Catalyst:** {item.get('catalyst_source') or '—'}")
                st.caption(f"Verified: {item.get('catalyst_verified')} · Manual review: {item.get('manual_review_required')}")
                st.markdown(f"**Risk / invalidation:** {item.get('risk_or_invalidation') or '—'}")
                news = item.get("news") or []
                if news:
                    st.markdown("**Recent news**")
                    for article in news[:5]:
                        st.markdown(f"- `{article.get('published_at', '')}` — {article.get('title', '')} ({article.get('publisher', '')})")

    with sub_sources:
        sources_active = buy_data.get("sources_active") or []
        if sources_active:
            chips = " ".join(
                f"<span class='ts-badge' style='color:{PALETTE.info};background:{PALETTE.info_bg};border:1px solid {PALETTE.info}55;'>{src}</span>"
                for src in sources_active
            )
            _html(f"<div style='margin-bottom:12px'><strong>Active sources:</strong> {chips}</div>")
        for item in candidates:
            with st.expander(f"{item.get('ticker')} — provenance"):
                for note in item.get("source_notes") or []:
                    st.write(f"- {note}")
        degradation = buy_data.get("degradation") or []
        if degradation:
            st.warning("Some source calls degraded.")
            st.dataframe(pd.DataFrame(degradation), hide_index=True, width="stretch")


with tab_buy:
    _render_buy_signals()


# ─── Today's Report ────────────────────────────────────────────────────────

with tab_report:
    selected_path = st.session_state.get("latest_report_path")
    report_path = Path(selected_path) if selected_path else latest_report()
    if not report_path:
        _html(
            empty_state(
                "No reports generated yet",
                "Open the Run Report tab and click Run to generate your first report.",
            )
        )
    else:
        col_path, col_dl = st.columns([4, 1])
        with col_path:
            st.caption(f"📝 `{relative_to_root(report_path)}`")
        with col_dl:
            st.download_button(
                "⬇ Download",
                report_path.read_bytes(),
                file_name=report_path.name,
                mime="text/markdown",
                width="stretch",
            )
        with st.container(border=True):
            st.markdown(read_text_file(report_path))


# ─── Run Report ────────────────────────────────────────────────────────────


def _render_run_tab() -> None:
    st.subheader("Generate a new report")
    st.caption("Two-pass Claude review · deterministic pipeline · full audit trail")

    with st.container(border=True):
        st.markdown("**Step 1 — Holdings source**")
        holdings_mode = st.radio(
            "Holdings input",
            ["File path", "Upload CSV", "Fallback config"],
            index=0 if defaults["holdings"] else 1,
            horizontal=True,
            key="run_holdings_mode",
            label_visibility="collapsed",
        )
        holdings_path_text = ""
        holdings_upload = None
        if holdings_mode == "File path":
            holdings_path_text = st.text_input(
                "Holdings CSV path",
                value=str(defaults["holdings"]) if defaults["holdings"] else "",
                help="Absolute or relative path. The CSV should be a Wealthsimple holdings export.",
            )
            if not holdings_path_text:
                st.caption("⚠️ No holdings CSV found in the default locations.")
        elif holdings_mode == "Upload CSV":
            holdings_upload = st.file_uploader("Upload Holdings CSV", type=["csv"], key="holdings_upload")
        else:
            st.info("This run will use `config/portfolio.json` instead of a Wealthsimple CSV.")

    with st.container(border=True):
        st.markdown("**Step 2 — Activities (optional but recommended)**")
        activities_mode = st.radio(
            "Activities input",
            ["No activities", "File path", "Upload CSV"],
            index=1 if defaults["activities"] else 0,
            horizontal=True,
            key="run_activities_mode",
            label_visibility="collapsed",
        )
        activities_path_text = ""
        activities_upload = None
        if activities_mode == "File path":
            activities_path_text = st.text_input(
                "Activities CSV path",
                value=str(defaults["activities"]) if defaults["activities"] else "",
                help="Helps the model see entry dates, fees, and recent trades for age/cost-basis context.",
            )
            if not activities_path_text:
                st.caption("⚠️ No activities CSV found in the default locations.")
        elif activities_mode == "Upload CSV":
            activities_upload = st.file_uploader("Upload Activities CSV", type=["csv"], key="activities_upload")

    preview_holdings_path, _ = _resolve_run_inputs(
        holdings_mode,
        holdings_path_text,
        holdings_upload,
        activities_mode,
        activities_path_text,
        activities_upload,
    )
    if preview_holdings_path:
        with st.expander("👀 Holdings preview", expanded=True):
            preview = preview_holdings_csv(preview_holdings_path)
            if preview.get("ok"):
                st.caption(f"**{preview['position_count']}** positions · exported {preview.get('exported_at', '—')}")
                st.dataframe(pd.DataFrame(preview["rows"]), hide_index=True, width="stretch")
            else:
                st.warning(preview.get("error", "Could not preview holdings."))

    st.markdown("**Step 3 — Run**")
    estimate = "~$0.22" if model_choice == "sonnet" else "~$0.45"
    st.caption(f"Selected model: **{model_choice.title()}** · estimated cost {estimate}")

    if st.button("▶ Run report", type="primary", width="stretch", key="run_report_btn"):
        holdings_path, activities_path = _resolve_run_inputs(
            holdings_mode,
            holdings_path_text,
            holdings_upload,
            activities_mode,
            activities_path_text,
            activities_upload,
        )

        if holdings_mode != "Fallback config" and holdings_path is None:
            st.error("Select a holdings CSV, upload one, or choose fallback config mode.")
            st.stop()

        for label, path in [("Holdings", holdings_path), ("Activities", activities_path)]:
            if path is not None and not path.exists():
                st.error(f"{label} CSV not found: {path}")
                st.stop()

        status = st.status(
            "Running pipeline — market data → enrichment → Claude review → render",
            expanded=True,
        )
        progress_box = st.empty()
        progress_lines: list[str] = []

        def on_progress(line: str) -> None:
            cleaned = _clean_console_line(line)
            if not cleaned:
                return
            progress_lines.append(cleaned)
            progress_box.code("\n".join(progress_lines[-MAX_CONSOLE_LINES:]))

        result = run_report_from_ui(
            session_type=session_type,
            holdings_csv=holdings_path,
            activities_csv=activities_path,
            budget_usd=budget_usd,
            budget_cad=budget_cad,
            model_choice=model_choice,
            on_progress=on_progress,
        )

        with st.expander("📜 Full console output", expanded=False):
            st.text_area("Console", result.console, height=260, label_visibility="collapsed")

        if not result.ok:
            status.update(label="Report failed", state="error")
            st.error(result.error or "Report run failed.")
            return

        status.update(label="Report generated ✓", state="complete")
        st.session_state["latest_report_path"] = str(result.report_path)
        st.session_state["boot_summary"] = latest_log_summary()
        _toast("Report generated", icon="🎉")
        st.success("Report generated. Switch to the Today's Report tab to view it.")

        col_report, col_csv, col_log = st.columns(3)
        with col_report:
            _display_download("Report (Markdown)", result.report_path, "text/markdown")
        with col_csv:
            _display_download("Recommendations CSV", result.csv_path, "text/csv")
        with col_log:
            _display_download("JSON Log", result.log_path, "application/json")


with tab_run:
    _render_run_tab()


# ─── History ───────────────────────────────────────────────────────────────

with tab_history:
    reports = list_reports(limit=200)
    if not reports:
        _html(empty_state("No reports in history", "Past reports will appear here after your first run."))
    else:
        col_filter, col_search = st.columns([1, 3])
        session_filter = col_filter.selectbox("Session", ["all", "morning", "afternoon"], key="hist_session")
        search = col_search.text_input("🔎 Search filename", key="hist_search")
        filtered = [
            path
            for path in reports
            if (session_filter == "all" or session_filter in path.name) and (not search or search.lower() in path.name.lower())
        ]
        if not filtered:
            _html(empty_state("No reports match filters", "Try clearing the search or changing the session filter."))
        else:
            labels = [relative_to_root(path) for path in filtered]
            compare = st.checkbox("🔀 Compare two reports side-by-side", key="hist_compare")
            if compare and len(filtered) > 1:
                col_a, col_b = st.columns(2)
                with col_a:
                    sel_a = st.selectbox("Report A", labels, key="hist_a")
                    with st.container(border=True, height=600):
                        st.markdown(read_text_file(filtered[labels.index(sel_a)]))
                with col_b:
                    sel_b = st.selectbox("Report B", labels, index=min(1, len(labels) - 1), key="hist_b")
                    with st.container(border=True, height=600):
                        st.markdown(read_text_file(filtered[labels.index(sel_b)]))
            else:
                selected_label = st.selectbox("Report", labels, key="hist_selected")
                selected_report = filtered[labels.index(selected_label)]
                with st.container(border=True):
                    st.markdown(read_text_file(selected_report))


# ─── Backtest ──────────────────────────────────────────────────────────────

with tab_backtest:
    st.caption("Evaluates past recommendations against actual price moves via yfinance. First run typically takes 10–30 seconds.")
    if st.button("▶ Run backtest", type="primary", key="run_backtest"):
        with st.spinner("Fetching historical prices and evaluating recommendations..."):
            st.session_state["backtest_summary"] = run_backtest_summary()
        _toast("Backtest complete", icon="📈")

    backtest = st.session_state.get("backtest_summary")
    if backtest is None:
        _html(empty_state("No backtest data yet", "Click Run Backtest above to score your past recommendations."))
    else:
        overall = backtest.get("overall") or {}
        col_samples, col_return, col_hit = st.columns(3)
        col_samples.metric("Samples", backtest.get("n_samples", 0))
        col_return.metric("Average return", _format_pct(overall.get("avg_return_pct"), signed=True, digits=2))
        col_hit.metric("Hit rate", f"{overall.get('hit_rate', 0):.0%}")

        _render_backtest_table(
            "📊 By Action",
            _rows_from_bucket(backtest.get("avg_return_by_action") or {}, "action"),
            "action",
        )
        _render_backtest_table(
            "🎯 By Conviction",
            _rows_from_bucket(backtest.get("avg_return_by_conviction") or {}, "conviction"),
            "conviction",
        )
        _render_backtest_table(
            "🏷 By Ticker",
            _rows_from_bucket(backtest.get("avg_return_by_ticker") or {}, "ticker"),
            "ticker",
        )

        with st.expander("📋 Recent realized examples", expanded=True):
            examples = backtest.get("recent_realized_examples") or []
            if examples:
                st.dataframe(pd.DataFrame(examples), hide_index=True, width="stretch")
            else:
                st.caption("No realized examples yet.")
        with st.expander("🔬 Raw JSON"):
            st.json(backtest)


# ─── Journal ───────────────────────────────────────────────────────────────


def _render_journal() -> None:
    if st.button("🔄 Refresh journal", key="journal_refresh"):
        st.session_state["decision_journal_snapshot"] = decision_journal_view()
        _toast("Journal refreshed")

    journal_snapshot = st.session_state.get("decision_journal_snapshot") or decision_journal_view()
    status = journal_snapshot.get("status") or {}
    entries = journal_snapshot.get("entries") or []

    col_total, col_pending, col_recorded = st.columns(3)
    col_total.metric("Entries", status.get("total", 0))
    col_pending.metric("Pending", status.get("pending", 0), delta=None)
    col_recorded.metric("Recorded", status.get("recorded", 0))

    if not entries:
        _html(
            empty_state(
                "No journal entries yet",
                "Generate a report — actionable recommendations are auto-seeded into the journal.",
            )
        )
    else:
        display_cols = [
            "id",
            "session_date",
            "ticker",
            "recommended_action",
            "conviction",
            "recommended_shares",
            "recommended_amount",
            "user_decision",
            "actual_action",
            "actual_shares",
            "actual_price",
            "reason",
        ]
        df = pd.DataFrame(entries)
        keep_cols = [col for col in display_cols if col in df.columns]
        if keep_cols:
            st.dataframe(df[keep_cols], hide_index=True, width="stretch")

    with st.expander("✏️ Record or update a decision", expanded=bool(entries)):
        if not entries:
            st.caption("Generate a report first to seed journal entries.")
        else:
            labels = [f"{row.get('session_date')} {row.get('ticker')} {row.get('recommended_action')} | {row.get('id')}" for row in entries]
            selected = st.selectbox("Decision row", labels, key="journal_row")
            row = entries[labels.index(selected)]
            decision_options = ["accepted", "ignored", "modified", "delayed", "watch", "executed", "pending"]
            current_decision = row.get("user_decision") or "pending"
            action_options = ["", "BUY", "ADD", "HOLD", "TRIM", "SELL", "NONE"]
            current_action = row.get("actual_action") or ""
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                user_decision = st.selectbox(
                    "Your decision",
                    decision_options,
                    index=decision_options.index(current_decision)
                    if current_decision in decision_options
                    else decision_options.index("pending"),
                )
                actual_action = st.selectbox(
                    "Actual action",
                    action_options,
                    index=action_options.index(current_action) if current_action in action_options else 0,
                )
            with col_b:
                actual_shares = st.text_input(
                    "Actual shares", value="" if row.get("actual_shares") is None else str(row.get("actual_shares"))
                )
                actual_price = st.text_input(
                    "Execution price", value="" if row.get("actual_price") is None else str(row.get("actual_price"))
                )
                actual_currency = st.selectbox("Currency", ["USD", "CAD"], index=0 if row.get("actual_currency", "USD") == "USD" else 1)
            with col_c:
                decision_date = st.text_input("Decision date", value=row.get("decision_date") or date.today().isoformat())
                execution_date = st.text_input("Execution date", value=row.get("execution_date") or decision_date)
                reason = st.text_input("Reason", value=row.get("reason") or "")
            notes = st.text_area("Notes", value=row.get("notes") or "", height=120)
            if st.button("💾 Save decision", type="primary", key="journal_save"):
                try:
                    save_decision_from_ui(
                        row["id"],
                        user_decision=user_decision,
                        actual_action=actual_action or None,
                        actual_shares=actual_shares or None,
                        actual_price=actual_price or None,
                        actual_currency=actual_currency,
                        decision_date=decision_date or None,
                        execution_date=execution_date or None,
                        reason=reason,
                        notes=notes,
                    )
                except Exception as exc:
                    st.error(str(exc))
                else:
                    st.session_state["decision_journal_snapshot"] = decision_journal_view()
                    _toast("Decision saved", icon="💾")
                    st.success("Decision saved.")

    st.markdown("### Outcome Scorecard")
    st.caption("Scores recorded decisions over 1 / 5 / 20 / 60-day windows using yfinance.")
    if st.button("▶ Run scorecard", key="scorecard_run"):
        with st.spinner("Fetching historical prices..."):
            st.session_state["decision_scorecard"] = decision_scorecard_summary()
        _toast("Scorecard updated", icon="🎯")

    scorecard = st.session_state.get("decision_scorecard")
    if scorecard:
        overall = scorecard.get("overall") or {}
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Scored windows", scorecard.get("n_scored_windows", 0))
        col2.metric("Model avg", _format_pct(overall.get("model_avg_return_pct"), signed=True, digits=2))
        col3.metric("Your avg", _format_pct(overall.get("user_avg_return_pct"), signed=True, digits=2))
        col4.metric("Discretion delta", _format_pct(overall.get("avg_decision_delta_pct"), signed=True, digits=2))
        if scorecard.get("by_user_decision"):
            st.dataframe(
                pd.DataFrame([{"decision": decision, **stats} for decision, stats in scorecard["by_user_decision"].items()]),
                hide_index=True,
                width="stretch",
            )
        with st.expander("⚠️ Worst overrides"):
            rows = scorecard.get("worst_user_overrides") or []
            if rows:
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            else:
                st.caption("No scored overrides yet.")
        with st.expander("🔬 Raw JSON"):
            st.json(scorecard)


with tab_journal:
    _render_journal()


# ─── Editor ────────────────────────────────────────────────────────────────

with tab_editor:
    st.caption("Edit settings, watchlist, and fallback portfolio. JSON is validated live; save is disabled while invalid.")
    selected_label = st.selectbox("File", list(EDITABLE_JSON_FILES.keys()), key="editor_file")
    state_key = f"editor_text_{selected_label}"
    if state_key not in st.session_state:
        st.session_state[state_key] = read_editable_json(selected_label)
    content = st.text_area("JSON", key=state_key, height=540, label_visibility="collapsed")
    is_valid, validation_message = validate_json_text(content)
    if is_valid:
        st.success(f"✓ {validation_message}")
        with st.expander("🔬 Parsed JSON preview"):
            st.json(json.loads(content))
    else:
        st.error(f"✗ {validation_message}")
    if st.button("💾 Save JSON", type="primary", disabled=not is_valid, key="editor_save"):
        try:
            saved_path = write_editable_json(selected_label, content)
        except Exception as exc:
            st.error(str(exc))
        else:
            _toast(f"Saved {selected_label}", icon="💾")
            st.success(f"Saved → `{relative_to_root(saved_path)}`")


# ── Toasts flush at end (Streamlit shows them on next rerun) ──────────────

_flush_toasts()
