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

from src.performance_history import portfolio_performance_summary  # noqa: E402
from src.ui_support import (  # noqa: E402
    API_KEY_FIELDS,
    EDITABLE_JSON_FILES,
    api_health_view,
    api_key_inventory,
    apply_available_update,
    buy_signal_view,
    check_update_available,
    current_app_version,
    decision_journal_view,
    decision_scorecard_summary,
    default_run_settings,
    degradation_health,
    delete_api_key,
    diagnostics_support_bundle,
    diagnostics_view,
    find_default_csvs,
    latest_log_summary,
    latest_report,
    learning_view,
    list_reports,
    preview_holdings_csv,
    read_editable_json,
    read_text_file,
    relative_to_root,
    run_backtest_summary,
    run_report_from_ui,
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
    health_badge,
    hero,
    readiness_badge,
    severity_badge,
    status_dot,
    verdict_badge,
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


# ── First-run wizard (v1.19) ───────────────────────────────────────────────


def _render_first_run_wizard() -> bool:
    """Render the inline wizard if onboarding is incomplete. Returns True when
    the wizard short-circuited the rest of the page (so the caller knows not
    to render the tabs)."""
    from src.onboarding import (
        advance as _advance,
    )
    from src.onboarding import (
        current_state as _onboarding_state,
    )
    from src.onboarding import (
        is_demo_mode_active as _demo_active,
    )
    from src.onboarding import (
        needs_onboarding as _needs,
    )
    from src.onboarding import (
        reset_onboarding as _reset,
    )
    from src.onboarding import (
        stage_guidance as _guidance,
    )

    if not _needs() or _demo_active():
        return False

    state = _onboarding_state()
    guide = _guidance(state.stage)

    with st.container(border=True):
        _html(
            f"<div style='display:flex;align-items:center;gap:14px;'>"
            f"<div style='font-size:2rem'>🚀</div>"
            f"<div><div style='font-size:1.3rem;font-weight:700;color:{PALETTE.text_strong}'>{guide.title}</div>"
            f"<div style='color:{PALETTE.muted};font-size:0.85rem'>Step {len(state.completed) + 1} of {6}</div></div>"
            "</div>"
        )
        st.write(guide.body)
        if guide.external_url:
            st.markdown(f"🔗 [{guide.external_url}]({guide.external_url})")
        if guide.helper_text:
            st.caption(guide.helper_text)

        # Stage-specific input widgets
        if state.stage == "api_key":
            api_value = st.text_input(
                "Paste your Anthropic API key",
                type="password",
                key="onboarding_api_key_value",
                placeholder="sk-ant-…",
            )
            if api_value and api_value.startswith("sk-"):
                save_api_key("ANTHROPIC_API_KEY", api_value)
                st.success("✓ Key saved to your config/.env file.")
        elif state.stage == "budgets":
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                monthly = st.number_input(
                    "Claude monthly cap (USD)",
                    min_value=1.0,
                    value=10.0,
                    step=1.0,
                    key="onboarding_monthly_usd",
                    help="We pause runs when you hit this. Override available anytime.",
                )
            with col_b:
                usd_budget = st.number_input(
                    "USD position budget per rec",
                    min_value=0.0,
                    value=500.0,
                    step=50.0,
                    key="onboarding_usd_budget",
                )
            with col_c:
                cad_budget = st.number_input(
                    "CAD position budget per rec",
                    min_value=0.0,
                    value=500.0,
                    step=50.0,
                    key="onboarding_cad_budget",
                )
            # Persist on every keystroke; cheap.
            try:
                from src.config import load_settings

                settings = load_settings()
                settings["monthly_budget_usd"] = float(monthly)
                settings["budget_usd"] = float(usd_budget)
                settings["budget_cad"] = float(cad_budget)
                (ROOT / "config" / "settings.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")
            except Exception:
                pass

        col_primary, col_secondary = st.columns([2, 2])
        with col_primary:
            if st.button(f"➡ {guide.primary_action}", type="primary", width="stretch", key=f"onb_primary_{state.stage}"):
                _advance(current=state.stage)
                st.rerun()
        with col_secondary:
            if guide.secondary_action:
                if st.button(guide.secondary_action, width="stretch", key=f"onb_secondary_{state.stage}"):
                    # 'Try demo' is the welcome-stage secondary action — short-
                    # circuit to demo mode rather than walking the wizard.  We
                    # inline st.toast here because the ``_toast`` queue helper
                    # is defined later in the file, after the wizard call.
                    if state.stage == "welcome":
                        os.environ["TECH_STOCK_DEMO_MODE"] = "1"
                        st.toast("Demo mode on — using bundled sample data.", icon="🎬")
                    _advance(current=state.stage, skip_demo=True)
                    st.rerun()

        # Tiny escape hatch: power users / re-installs can skip the wizard.
        with st.expander("Skip the wizard for now"):
            st.caption(
                "You can complete onboarding later. We'll keep checking until all stages are stamped. Or click here to mark setup done now."
            )
            if st.button("Mark setup complete (skip remaining steps)", key="onb_force_done"):
                # Walk through every remaining stage in one shot.
                while _onboarding_state().stage != "done":
                    _advance()
                st.rerun()
            if st.button("Reset wizard state (debug)", key="onb_reset"):
                _reset()
                st.rerun()
    return True


if _render_first_run_wizard():
    # Wizard rendered — stop here so the rest of the page doesn't draw.
    st.stop()


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
    if st.button("Force refresh updates", width="stretch", key="sidebar_force_update_refresh"):
        with st.spinner("Checking published GitHub Releases..."):
            st.session_state["update_info"] = check_update_available(timeout=6.0, force=True)
        st.rerun()

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

(
    tab_dashboard,
    tab_buy,
    tab_report,
    tab_run,
    tab_history,
    tab_performance,
    tab_backtest,
    tab_journal,
    tab_learning,
    tab_diagnostics,
    tab_schedule,
    tab_editor,
) = st.tabs(
    [
        "📊 Dashboard",
        "🎯 Buy Signals",
        "📝 Today's Report",
        "▶️ Run Report",
        "📚 History",
        "💹 Performance",
        "📈 Backtest",
        "📓 Journal",
        "🧠 Learning",
        "🩺 Diagnostics",
        "⏰ Schedule",
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
    data_confidence = summary.get("data_confidence") or {}

    # Hero metric strip
    col1, col2, col3, col4, col5, col6 = st.columns(6)
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
        "Data confidence",
        data_confidence.get("label") or "—",
        help=data_confidence.get("summary") or "Deterministic quote/source/catalyst confidence.",
    )
    col4.metric(
        "Ann. volatility",
        _format_pct(risk.get("annualized_volatility_pct"), digits=1),
        help="Annualised standard deviation of daily returns (from holdings' 1y prices).",
    )
    col5.metric(
        "Max drawdown",
        _format_pct(risk.get("max_drawdown_estimate_pct"), signed=True, digits=1),
        help="Worst peak-to-trough decline estimated from 1y price history.",
    )
    col6.metric(
        "Top-3 concentration",
        _format_pct(risk.get("top3_concentration_pct"), digits=1),
        help="Weight of the three largest positions. >40% is a concentration flag.",
    )

    if data_confidence:
        reasons = data_confidence.get("reasons") or []
        st.caption(
            f"Data Confidence: **{data_confidence.get('label')}** · "
            f"{data_confidence.get('timestamped_quotes', 0)}/{data_confidence.get('quote_total', 0)} timestamped quotes · "
            f"{data_confidence.get('warning_count', 0)} quality warnings" + (f" · {'; '.join(reasons[:2])}" if reasons else "")
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
    confidence = buy_data.get("data_confidence") or {}
    col_ready, col_review, col_blocked, col_total = st.columns(4)
    col_ready.metric("✅ Trade Ready", counts.get("TRADE_READY", 0))
    col_review.metric("⚠️ Review First", counts.get("REVIEW_FIRST", 0))
    col_blocked.metric("🛑 Blocked", counts.get("BLOCKED", 0))
    col_total.metric("Total", counts.get("total", len(buy_data.get("cards") or [])))

    st.caption(
        f"Source: `{buy_data.get('session_file')}` · fetched {buy_data.get('fetched_at') or '—'} · "
        f"Data Confidence: **{confidence.get('label', 'N/A')}**"
    )

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

    st.checkbox(
        "Dry run — validate data without calling Claude",
        key="dry_run_mode",
        value=False,
        help="Loads CSV, parses portfolio, fetches market data — but stops before the Claude API call.",
    )

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

        is_dry_run = st.session_state.get("dry_run_mode", False)

        status = st.status(
            "Dry-run validation — market data only (Claude skipped)"
            if is_dry_run
            else "Running pipeline — market data → enrichment → Claude review → render",
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
            dry_run=is_dry_run,
        )

        with st.expander("📜 Full console output", expanded=False):
            st.text_area("Console", result.console, height=260, label_visibility="collapsed")

        if not result.ok:
            status.update(label="Run failed", state="error")
            st.error(f"Run failed: {result.error or 'Unknown error'}")
            with st.expander("Error details", expanded=True):
                dry_data = result.dry_run_data or {}
                if dry_data.get("error"):
                    st.markdown(f"**Error:** {dry_data['error']}")
                console_text = result.console or ""
                if console_text:
                    tail_lines = console_text.splitlines()[-20:]
                    st.code("\n".join(tail_lines), language=None)
                if st.button("Retry", key="run_retry_btn"):
                    st.rerun()
            return

        if result.dry_run:
            status.update(label="Dry run complete ✓", state="complete")
            dry_data = result.dry_run_data or {}
            tickers = dry_data.get("tickers") or []
            total_value = dry_data.get("total_value_usd", 0)
            position_count = dry_data.get("position_count", 0)
            market_data_fetched = dry_data.get("market_data_fetched", 0)
            st.success(
                f"Dry run passed — portfolio loaded successfully.\n\n"
                f"**{position_count}** positions · **{len(tickers)}** tickers · "
                f"**${total_value:,.0f}** total value (USD equiv.) · "
                f"**{market_data_fetched}** market data records fetched.\n\n"
                f"Tickers: {', '.join(tickers[:20]) or '—'}" + (" …" if len(tickers) > 20 else "")
            )
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


# ─── Performance ──────────────────────────────────────────────────────────


def _render_performance() -> None:
    st.subheader("Portfolio Performance")
    st.caption(
        "Time-series rebuilt from your recommendation-log snapshots. Each session "
        "becomes one data point; SPY benchmark is fetched from yfinance (cached 4h)."
    )

    col_lookback, col_spy, col_refresh = st.columns([2, 2, 1])
    with col_lookback:
        lookback_label = st.selectbox(
            "Lookback",
            options=["All time", "Last 30 days", "Last 90 days", "Last 365 days"],
            index=0,
            key="perf_lookback",
        )
    with col_spy:
        fetch_spy = st.checkbox(
            "Compare vs SPY",
            value=True,
            help="Uncheck to skip the yfinance call (~1-2 s on cold cache).",
            key="perf_fetch_spy",
        )
    with col_refresh:
        st.markdown("&nbsp;")
        if st.button("🔄 Refresh", width="stretch", key="perf_refresh"):
            for key in list(st.session_state):
                if key.startswith("perf_view_cache_"):
                    del st.session_state[key]
            _toast("Performance recomputed", icon="💹")

    lookback_days = {"Last 30 days": 30, "Last 90 days": 90, "Last 365 days": 365}.get(lookback_label)
    cache_key = f"perf_view_cache_{lookback_label}_{fetch_spy}"
    if cache_key not in st.session_state:
        with st.spinner("Computing performance…"):
            st.session_state[cache_key] = portfolio_performance_summary(
                lookback_days=lookback_days,
                fetch_spy=fetch_spy,
            )
    view = st.session_state[cache_key]

    if not view.get("ready"):
        _html(empty_state("Performance not ready", view.get("reason") or "Need at least 2 recommendation logs."))
        return

    # ── Headline metrics ──────────────────────────────────────────────────
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric(
        "Cumulative return",
        _format_pct(view["cumulative_return_pct"], signed=True, digits=2),
        help=f"Over {view['n_snapshots']} sessions · {view['first_ts']} → {view['last_ts']}",
    )
    col2.metric(
        "Annualized return",
        _format_pct(view["annualized_return_pct"], signed=True, digits=1),
        help="Mean session return × sessions/year (your cadence)",
    )
    col3.metric(
        "Volatility (ann.)",
        _format_pct(view["annualized_volatility_pct"], digits=1),
        help="Standard deviation of session returns × √sessions_per_year",
    )
    col4.metric(
        "Sharpe",
        f"{view['sharpe']:.2f}",
        help="Annualized return / annualized volatility (rf=0)",
    )
    col5.metric(
        "Max drawdown",
        _format_pct(view["max_drawdown_pct"], signed=True, digits=1),
        help="Worst peak-to-trough on the cumulative value series",
    )

    spy = view.get("spy") or {}
    if spy.get("available"):
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("SPY cumulative", _format_pct(spy.get("cumulative_return_pct"), signed=True, digits=2))
        col_b.metric("Beta vs SPY", f"{spy.get('beta'):.2f}" if spy.get("beta") is not None else "—")
        col_c.metric(
            "Alpha (ann.)",
            _format_pct(spy.get("alpha_annualized_pct"), signed=True, digits=2),
            help="Intercept of session-return regression vs SPY × sessions/year",
        )

    # ── Cumulative-value line chart ───────────────────────────────────────
    st.markdown("### Portfolio value over time")
    iso_dates = view["iso_dates"]
    values = view["values_usd"]
    initial = values[0]

    # Rebased values (start = 100) so portfolio + SPY share a scale.
    portfolio_indexed = [v / initial * 100.0 for v in values]
    chart_rows = [{"date": d, "Portfolio": p} for d, p in zip(iso_dates, portfolio_indexed)]
    if spy.get("available") and spy.get("values"):
        spy_vals = spy["values"]
        spy_initial = spy_vals[0]
        for row, sv in zip(chart_rows, spy_vals):
            row["SPY"] = sv / spy_initial * 100.0
    chart_df = pd.DataFrame(chart_rows).set_index("date")
    st.line_chart(chart_df, color=[PALETTE.accent, PALETTE.info])

    # ── Rolling Sharpe + drawdown ─────────────────────────────────────────
    st.markdown("### Rolling metrics")
    col_l, col_r = st.columns(2)
    with col_l:
        st.caption(f"Rolling {view['rolling_window_sessions']}-session Sharpe")
        # rolling_sharpe is aligned with session_returns (length = n_snapshots - 1)
        rolling = view["rolling_sharpe"]
        rolling_dates = iso_dates[1 : 1 + len(rolling)]
        rolling_df = pd.DataFrame([{"date": d, "Sharpe": r} for d, r in zip(rolling_dates, rolling) if r is not None])
        if not rolling_df.empty:
            st.line_chart(rolling_df.set_index("date"), color=PALETTE.warn)
        else:
            _html(empty_state("Not enough sessions yet", "Rolling Sharpe needs ~30 sessions to warm up."))
    with col_r:
        st.caption("Drawdown from running peak")
        dd_df = pd.DataFrame({"date": iso_dates, "Drawdown %": view["rolling_drawdown_pct"]}).set_index("date")
        st.area_chart(dd_df, color=PALETTE.danger)

    # ── Sector contribution waterfall ─────────────────────────────────────
    st.markdown("### Sector contribution (USD change first → last)")
    sector_rows = view.get("sector_waterfall") or []
    if not sector_rows:
        _html(empty_state("No sector data", "Recommendation logs didn't carry sector tags for this window."))
    else:
        df = pd.DataFrame(sector_rows)
        st.bar_chart(df.set_index("sector")["delta_usd"], color=PALETTE.accent)
        with st.expander("Detail"):
            st.dataframe(df, hide_index=True, width="stretch")

    # ── Return distribution ───────────────────────────────────────────────
    st.markdown("### Session return distribution")
    dist = view.get("return_distribution") or {}
    if dist:
        # Sort buckets numerically — keep ≤-5%, … neutral … , ≥+5% extremes at edges.
        def _bucket_sort_key(label: str) -> tuple:
            if label.startswith("≤"):
                return (-999.0,)
            if label.startswith("≥"):
                return (999.0,)
            try:
                lower = float(label.split(" ")[0])
                return (lower,)
            except ValueError:
                return (0.0,)

        ordered = sorted(dist.items(), key=lambda kv: _bucket_sort_key(kv[0]))
        dist_df = pd.DataFrame([{"return_bucket": k, "count": v} for k, v in ordered])
        st.bar_chart(dist_df.set_index("return_bucket"), color=PALETTE.info)


with tab_performance:
    _render_performance()

    with st.expander("Paper Trading", expanded=False):
        try:
            from src.main import DATA_DIR as _DATA_DIR
            from src.paper_trading import _load_state as _load_paper_state

            _paper_path = _DATA_DIR / "paper_portfolio.json"
            paper = _load_paper_state(_paper_path)
        except Exception as _paper_exc:
            paper = None
            st.caption(f"Paper trading data unavailable: {_paper_exc}")

        if paper and paper.get("value_history"):
            from src.paper_trading import mark_to_market as _mtm

            _current_value = _mtm(paper, {})
            _starting = float(paper.get("starting_cash_usd") or 0)
            _total_pnl = _current_value - _starting
            _trade_log = paper.get("trade_log") or []

            col1, col2, col3 = st.columns(3)
            col1.metric("Current Value", f"${_current_value:,.0f}")
            col2.metric("P&L", f"${_total_pnl:,.0f}")
            col3.metric("Trades", str(len(_trade_log)))

            vh = paper["value_history"]
            if vh:
                df_vh = pd.DataFrame(vh)
                if "date" in df_vh.columns:
                    st.line_chart(df_vh.set_index("date")["value_usd"] if "value_usd" in df_vh.columns else df_vh.set_index("date"))
                else:
                    st.line_chart(df_vh)
        else:
            st.info("No paper trading data yet. Enable paper trading in Settings to start tracking simulated trades.")


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

        # Equity curve from recent realized examples
        examples = backtest.get("recent_realized_examples") or []
        if examples:
            with st.expander("📈 Equity Curve", expanded=True):
                try:
                    eq_df = pd.DataFrame(examples)
                    if "session_date" in eq_df.columns and "actual_pct" in eq_df.columns:
                        eq_df = eq_df.dropna(subset=["session_date", "actual_pct"])
                        eq_df["session_date"] = pd.to_datetime(eq_df["session_date"])
                        daily = eq_df.groupby("session_date")["actual_pct"].mean().sort_index()
                        cumulative = (1 + daily / 100).cumprod() * 100
                        st.line_chart(cumulative, x_label="Date", y_label="Portfolio Index (start=100)")
                    else:
                        st.info("Equity curve requires session_date and actual_pct columns.")
                except Exception:
                    st.info("Could not build equity curve from available data.")
        else:
            st.info("Run a backtest first to see the equity curve.")

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

    # ── Filters ───────────────────────────────────────────────────────────────
    if entries:
        from datetime import date as _date
        from datetime import timedelta as _timedelta

        _entries_df = pd.DataFrame(entries)
        _all_tickers = sorted(_entries_df["ticker"].dropna().unique().tolist()) if "ticker" in _entries_df.columns else []
        _today = _date.today()
        _30_days_ago = _today - _timedelta(days=30)

        _fcol1, _fcol2, _fcol3 = st.columns(3)
        with _fcol1:
            _sel_tickers = st.multiselect("Filter by ticker", _all_tickers, key="journal_ticker_filter")
        with _fcol2:
            _date_range = st.date_input("Date range", value=(_30_days_ago, _today), key="journal_date_range")
        with _fcol3:
            _outcome = st.selectbox("Outcome filter", ["All", "Win", "Loss", "Open"], key="journal_outcome")

        # Apply ticker filter
        if _sel_tickers:
            entries = [e for e in entries if e.get("ticker") in _sel_tickers]

        # Apply date filter
        if isinstance(_date_range, (list, tuple)) and len(_date_range) == 2:
            _start, _end = _date_range

            def _in_range(e):
                sd = e.get("session_date")
                if not sd:
                    return True
                try:
                    _d = _date.fromisoformat(str(sd)[:10])
                    return _start <= _d <= _end
                except Exception:
                    return True

            entries = [e for e in entries if _in_range(e)]

        # Apply outcome filter
        _WIN_DECISIONS = {"accepted", "executed"}
        _LOSS_DECISIONS = {"ignored"}
        _OPEN_DECISIONS = {"pending"}
        if _outcome == "Win":
            entries = [e for e in entries if e.get("user_decision") in _WIN_DECISIONS]
        elif _outcome == "Loss":
            entries = [e for e in entries if e.get("user_decision") in _LOSS_DECISIONS]
        elif _outcome == "Open":
            entries = [e for e in entries if e.get("user_decision") in _OPEN_DECISIONS]

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
            st.download_button("📥 Export to CSV", df[keep_cols].to_csv(index=False), "journal.csv", "text/csv")

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


# ─── Learning ──────────────────────────────────────────────────────────────


def _render_learning() -> None:
    st.subheader("Learning Loop")
    st.caption(
        "What the app has learned about your portfolio so far — thesis verdicts, "
        "per-horizon edge, risk-adjusted sizing, and any 'moving goalposts' on "
        "active rationales. Feeds back into the Claude prompt on the next run."
    )
    if st.button("🔄 Refresh", key="learning_refresh"):
        st.session_state["learning_view_cache"] = learning_view()
        _toast("Learning view refreshed", icon="🧠")
    view = st.session_state.get("learning_view_cache") or learning_view()
    st.session_state["learning_view_cache"] = view

    if view.get("errors"):
        with st.expander("⚠️ Soft errors loading data", expanded=False):
            for err in view["errors"]:
                st.caption(f"• {err}")

    # ── Per-horizon edge strip ────────────────────────────────────────────
    st.markdown("### Your edge by horizon")
    edge = view.get("edge_by_horizon") or {}
    if not edge:
        _html(
            empty_state(
                "Not enough scored decisions yet",
                "Record at least a few decisions in the Journal tab and re-run — "
                "this becomes the strongest signal Claude has about which "
                "time-horizon you actually outperform on.",
            )
        )
    else:
        horizons = sorted(int(h) for h in edge.keys())
        cols = st.columns(len(horizons))
        for col, horizon in zip(cols, horizons):
            stats = edge[horizon]
            user_avg = float(stats.get("user_avg_return_pct", 0.0))
            model_avg = float(stats.get("model_avg_return_pct", 0.0))
            delta_color = PALETTE.accent if user_avg > model_avg else PALETTE.danger
            col.metric(
                f"{horizon}d",
                _format_pct(user_avg, signed=True, digits=2),
                delta=_format_pct(user_avg - model_avg, signed=True, digits=2),
                help=f"User avg over {stats.get('n', 0)} scored windows · Model avg {model_avg:+.2f}%",
            )
            _html(f"<div style='font-size:0.78rem;color:{delta_color};margin-top:-12px'>hit rate {stats.get('user_hit_rate', 0):.0%}</div>")
        edge_df = pd.DataFrame(
            [
                {
                    "horizon_days": h,
                    "user_avg_return_pct": edge[h].get("user_avg_return_pct", 0.0),
                    "model_avg_return_pct": edge[h].get("model_avg_return_pct", 0.0),
                }
                for h in horizons
            ]
        )
        st.bar_chart(edge_df.set_index("horizon_days"), color=[PALETTE.accent, PALETTE.muted])

    # ── Sharpe-by-conviction table ────────────────────────────────────────
    st.markdown("### Sizing multipliers (Sharpe-dampened)")
    sharpe = view.get("sharpe_by_conviction") or {}
    if not sharpe:
        _html(
            empty_state(
                "No backtest samples yet",
                "Generate a few reports and let some recommendations mature — the "
                "sizing engine then learns the Sharpe + max-DD per conviction bucket.",
            )
        )
    else:
        rows = [
            {
                "conviction": conv,
                "n": stats.get("n", 0),
                "avg_return_pct": stats.get("avg_return_pct", 0.0),
                "hit_rate": f"{stats.get('hit_rate', 0):.0%}",
                "sharpe": stats.get("sharpe", 0.0),
                "max_drawdown_pct": stats.get("max_drawdown_pct", 0.0),
                "sizing_multiplier": f"{stats.get('sizing_multiplier', 1.0):.2f}×",
            }
            for conv, stats in sorted(sharpe.items())
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    # ── Calibration & stability (v1.18) ───────────────────────────────────
    st.markdown("### Calibration & stability")
    st.caption(
        "Does conviction X actually win X×10% of the time? The scatter "
        "compares stated probability (conviction × 10) to the realized hit "
        "rate per bucket; the diagonal is perfect calibration. The line "
        "chart below shows hit-rate stability across rolling windows."
    )
    calibration = view.get("calibration") or {}
    if not calibration:
        _html(
            empty_state(
                "Not enough mature recommendations yet",
                "Each conviction bucket needs ≥ 3 matured samples before calibration is meaningful.",
            )
        )
    else:
        # Scatter + reference diagonal — use a small Altair spec so we can
        # add the 45° line that the bar chart can't.
        cal_rows = [
            {
                "conviction": conv,
                "stated_pct": bucket.get("stated_pct"),
                "realized_pct": bucket.get("realized_pct"),
                "error_pp": bucket.get("error_pp"),
                "n": bucket.get("n"),
                "overconfident": bucket.get("overconfident"),
            }
            for conv, bucket in sorted(calibration.items())
        ]
        try:
            import altair as alt

            cal_df = pd.DataFrame(cal_rows)
            # Diagonal reference (stated == realized)
            diagonal = pd.DataFrame({"stated_pct": [0, 100], "realized_pct": [0, 100]})
            chart = (
                alt.Chart(cal_df)
                .mark_circle(size=160)
                .encode(
                    x=alt.X("stated_pct:Q", scale=alt.Scale(domain=[40, 100]), title="Stated probability (conv × 10)"),
                    y=alt.Y("realized_pct:Q", scale=alt.Scale(domain=[0, 100]), title="Realized hit rate %"),
                    color=alt.condition(
                        alt.datum.overconfident,
                        alt.value(PALETTE.danger),
                        alt.value(PALETTE.accent),
                    ),
                    tooltip=["conviction", "stated_pct", "realized_pct", "error_pp", "n"],
                )
            )
            diag = (
                alt.Chart(diagonal)
                .mark_line(strokeDash=[4, 4], color=PALETTE.muted, opacity=0.6)
                .encode(x="stated_pct:Q", y="realized_pct:Q")
            )
            st.altair_chart(diag + chart, use_container_width=True)
        except Exception:
            # Altair shouldn't fail, but if it does fall back to a table.
            st.dataframe(pd.DataFrame(cal_rows), hide_index=True, width="stretch")

        # Detail table
        with st.expander("Per-bucket detail"):
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "conviction": conv,
                            "n": bucket.get("n"),
                            "stated %": f"{bucket.get('stated_pct'):.0f}",
                            "realized %": f"{bucket.get('realized_pct'):.1f}",
                            "error_pp": f"{bucket.get('error_pp'):+.1f}",
                            "avg actual %": f"{bucket.get('avg_actual_pct'):+.2f}",
                            "verdict": "over-confident" if bucket.get("overconfident") else "well-calibrated / under",
                        }
                        for conv, bucket in sorted(calibration.items())
                    ]
                ),
                hide_index=True,
                width="stretch",
            )

    # Walk-forward stability line chart
    walk = view.get("walk_forward") or []
    if walk:
        st.caption(f"**Walk-forward stability** — {len(walk)} rolling windows · hit-rate over time")
        wf_df = pd.DataFrame(
            [{"window_end": w["window_end"], "hit_rate %": w["hit_rate"] * 100.0, "sharpe": w["sharpe"]} for w in walk]
        ).set_index("window_end")
        st.line_chart(wf_df[["hit_rate %"]], color=PALETTE.accent)
        if len(walk) >= 2:
            recent = walk[-1]["hit_rate"]
            mean_hr = sum(w["hit_rate"] for w in walk) / len(walk)
            delta_pp = (recent - mean_hr) * 100.0
            tone = PALETTE.danger if delta_pp <= -10 else PALETTE.accent if delta_pp >= 10 else PALETTE.muted
            _html(
                f"<div style='color:{PALETTE.muted};font-size:0.85rem;'>"
                f"Latest window: <strong style='color:{tone};'>{recent:.0%}</strong> "
                f"vs all-window mean {mean_hr:.0%} ({delta_pp:+.1f}pp)</div>"
            )
    elif calibration:
        st.caption("Walk-forward stability needs ≥ 60 matured recommendations — accumulating.")

    # ── Thesis verdict heat-map ───────────────────────────────────────────
    st.markdown("### Active thesis verdicts")
    verdicts = view.get("thesis_verdicts") or []
    if not verdicts:
        _html(
            empty_state(
                "No active theses tracked",
                "Theses are recorded when a new position is added. Open the latest "
                "report → Run Report once you have a new BUY/ADD to start tracking.",
            )
        )
    else:
        for verdict in verdicts[:20]:
            ticker = verdict.get("ticker") or "—"
            current_verdict = verdict.get("current_verdict")
            entry_date = verdict.get("entry_date") or "?"
            days_held = verdict.get("days_held")
            original_action = verdict.get("original_action") or "—"
            original_conv = verdict.get("original_conviction")
            history = verdict.get("verdict_history") or []
            history_dots = "".join(
                f"<span title='{h}' style='color:{PALETTE.muted};font-size:0.85rem;'>·</span>"
                if h is None
                else f"<span title='{h}' style='color:{(VERDICT_COLOR_LOOKUP.get(h) or PALETTE.muted)};font-size:1.1rem;'>●</span>"
                for h in history
            )
            with st.container(border=True):
                head_col, body_col = st.columns([2, 5])
                with head_col:
                    _html(
                        f"<div style='font-size:1.05rem;font-weight:700;color:{PALETTE.text_strong};letter-spacing:0.04em;'>"
                        f"{ticker}</div>"
                        f"<div style='color:{PALETTE.muted};font-size:0.82rem;margin-top:2px;'>"
                        f"entered {entry_date}"
                        f"{f' · {days_held}d held' if days_held is not None else ''}</div>"
                    )
                with body_col:
                    _html(
                        f"<div style='display:flex;align-items:center;gap:10px;flex-wrap:wrap;'>"
                        f"{verdict_badge(current_verdict)}"
                        f"<span style='color:{PALETTE.muted};font-size:0.85rem;'>"
                        f"original: {original_action} · conv {original_conv if original_conv is not None else '—'}"
                        f"</span>"
                        f"<span style='margin-left:auto;'>{history_dots}</span>"
                        f"</div>"
                    )

    # ── Thesis-text drift alerts ──────────────────────────────────────────
    st.markdown("### Thesis-text drift alerts")
    alerts = view.get("thesis_text_drift_alerts") or []
    if not alerts:
        _html(empty_state("No drift detected", "All active theses kept a consistent rationale across the last two sessions."))
    else:
        st.caption(
            f"{len(alerts)} ticker(s) had the same action but a substantially "
            "rewritten thesis since last session. Confirm the new rationale or "
            "downgrade — moving goalposts often precede reversals."
        )
        for alert in alerts:
            with st.container(border=True):
                ticker = alert.get("ticker", "—")
                sim = alert.get("similarity", 0.0)
                _html(
                    f"<div style='display:flex;gap:10px;align-items:center;'>"
                    f"<span style='font-weight:700;color:{PALETTE.text_strong};'>{ticker}</span>"
                    f"<span class='ts-badge' style='color:{PALETTE.warn};background:{PALETTE.warn_bg};"
                    f"border:1px solid {PALETTE.warn}55;'>similarity {sim:.0%}</span>"
                    f"</div>"
                )
                st.caption(f"**Was:** {alert.get('was_thesis') or '—'}")
                st.caption(f"**Now:** {alert.get('now_thesis') or '—'}")


# Map verdict → palette colour for the history dots above.
VERDICT_COLOR_LOOKUP = {
    "materialized": PALETTE.accent,
    "partial": PALETTE.warn,
    "not_yet": PALETTE.neutral,
    "invalidated": PALETTE.danger,
}


with tab_learning:
    _render_learning()


# ─── Diagnostics ───────────────────────────────────────────────────────────


def _render_diagnostics() -> None:
    # Data quality degradation check
    deg_issue = degradation_health("streamlit_app")
    if deg_issue:
        st.warning(f"⚠️ Data quality degradation detected: {deg_issue}")

    st.subheader("Diagnostics")
    st.caption(
        "Per-source API health, recent errors, and a redacted support bundle. "
        "Powered by `src/observability.py` — every API client now logs degradations "
        "to `logs/diagnostics.jsonl` instead of swallowing them silently."
    )

    col_window, col_refresh = st.columns([3, 1])
    with col_window:
        window = st.selectbox(
            "Time window",
            options=[1, 6, 24, 72, 168],
            format_func=lambda h: f"Last {h}h" if h < 24 else f"Last {h // 24}d",
            index=2,
            key="diag_window_hours",
        )
    with col_refresh:
        st.markdown("&nbsp;")  # vertical alignment with the selectbox
        if st.button("🔄 Refresh", width="stretch", key="diag_refresh"):
            st.session_state.pop("diag_view_cache", None)
            _toast("Diagnostics refreshed", icon="🩺")

    cache_key = f"diag_view_cache_{window}"
    if cache_key not in st.session_state:
        st.session_state[cache_key] = diagnostics_view(hours=int(window))
    view = st.session_state[cache_key]

    preflight = view.get("preflight") or {}
    rows = preflight.get("summary_rows") or []
    st.markdown("### Preflight")
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        _html(empty_state("Preflight unavailable", "Refresh diagnostics to rebuild the doctor payload."))

    csv_health = view.get("csv_health") or preflight.get("csv_freshness") or {}
    if csv_health:
        st.markdown("### CSV Health")
        csv_rows = []
        for kind in ("holdings", "activities"):
            item = csv_health.get(kind) or {}
            csv_rows.append(
                {
                    "type": kind.title(),
                    "status": item.get("status") or "",
                    "detected": item.get("schema_kind") or "missing",
                    "path": item.get("latest_path") or "not found",
                    "age_hours": item.get("age_hours"),
                    "action": item.get("action") or "",
                }
            )
        st.dataframe(pd.DataFrame(csv_rows), hide_index=True, width="stretch")

    sources = view.get("sources") or {}
    if not sources:
        _html(
            empty_state(
                "No events logged yet",
                "Generate a report (or run any enrichment) to populate the diagnostics log.",
            )
        )
    else:
        col_total, col_ok, col_degr, col_down = st.columns(4)
        col_total.metric("Sources tracked", len(sources))
        ok = sum(1 for b in sources.values() if b.get("health") == "ok")
        degr = sum(1 for b in sources.values() if b.get("health") == "degraded")
        down = sum(1 for b in sources.values() if b.get("health") == "down")
        col_ok.metric("OK", ok)
        col_degr.metric("Degraded", degr)
        col_down.metric("Down", down)

        st.markdown("### Sources")
        for source_name, bucket in sorted(sources.items()):
            health = bucket.get("health") or "idle"
            rate = bucket.get("success_rate")
            rate_str = "n/a" if rate is None else f"{rate:.0%}"
            with st.container(border=True):
                head_col, body_col = st.columns([3, 5])
                with head_col:
                    _html(
                        f"<div style='display:flex;align-items:center;gap:10px;'>"
                        f"<span style='font-weight:700;color:{PALETTE.text_strong};letter-spacing:0.03em;'>"
                        f"{source_name}</span>"
                        f"{health_badge(health)}"
                        f"<span style='color:{PALETTE.muted};font-size:0.85rem;'>success {rate_str}</span>"
                        "</div>"
                    )
                with body_col:
                    counts = " · ".join(
                        f"<span style='color:{PALETTE.muted};font-size:0.82rem;'>{code}: {n}</span>"
                        for code, n in sorted(bucket.get("codes", {}).items())
                    )
                    _html(
                        f"<div style='display:flex;justify-content:flex-end;gap:14px;flex-wrap:wrap;'>"
                        f"<span style='color:{PALETTE.muted};font-size:0.85rem;'>"
                        f"events {bucket.get('total', 0)} · errors {bucket.get('errors', 0)}"
                        f"</span>{counts}</div>"
                    )
                last_error = bucket.get("last_error")
                if last_error:
                    st.caption(f"**Last error** · `{last_error.get('ts')}` · `{last_error.get('code')}` — {last_error.get('message')}")

    st.markdown("### Recent error events")
    recent_errors = view.get("recent_errors") or []
    if not recent_errors:
        _html(empty_state("No recent errors", "Either everything's healthy or there's no recent traffic."))
    else:
        df_rows = [
            {
                "when": e.get("ts"),
                "source": e.get("source"),
                "level": e.get("level"),
                "code": e.get("code"),
                "message": e.get("message"),
            }
            for e in recent_errors
        ]
        st.dataframe(pd.DataFrame(df_rows), hide_index=True, width="stretch")

    st.markdown("### Support bundle")
    st.caption("Last 500 events, fully redacted (API keys / tokens / emails are scrubbed). Paste this into a bug report — safe to share.")
    bundle = diagnostics_support_bundle(limit=500)
    if bundle:
        st.code(bundle, language="json")
        st.download_button(
            "⬇ Download bundle",
            bundle.encode("utf-8"),
            file_name="tech_stock_diagnostics.jsonl",
            mime="application/jsonl",
            width="stretch",
        )
    else:
        st.caption("Bundle is empty (no events yet).")

    with st.expander("ℹ️ Log file locations"):
        st.write(f"Active log: `{view.get('log_path')}`")
        rotated = view.get("rotated_path")
        if rotated:
            st.write(f"Rotated log: `{rotated}`")

    # ── v1.19: Spend sub-section ──────────────────────────────────────────
    st.markdown("### 💰 Spend (Anthropic API)")
    from src.cost_tracker import check_budget as _check_budget
    from src.cost_tracker import clear_cost_log as _clear_cost
    from src.cost_tracker import spend_summary as _spend

    spend = _spend(lookback_days=30)
    budget = _check_budget(expected_cost_usd=0.0)

    col_total, col_mtd, col_proj, col_runs = st.columns(4)
    col_total.metric("Total all-time", _format_currency(spend.total_usd))
    col_mtd.metric("Month-to-date", _format_currency(spend.month_to_date_usd))
    col_proj.metric("Projected monthly", _format_currency(spend.projected_monthly_usd))
    col_runs.metric("Runs (30d)", spend.last_30d_runs)

    if budget.budget_usd > 0:
        used_pct = (spend.month_to_date_usd / budget.budget_usd) * 100.0
        tone = PALETTE.danger if used_pct >= 100 else PALETTE.warn if used_pct >= 80 else PALETTE.accent
        _html(
            f"<div style='margin:6px 0 14px 0;color:{PALETTE.muted};font-size:0.9rem;'>"
            f"<strong style='color:{tone};'>{used_pct:.0f}%</strong> of "
            f"<strong>${budget.budget_usd:.2f}</strong> monthly cap used. {budget.message}"
            "</div>"
        )
    else:
        st.caption(
            "No monthly budget cap set. Add a `monthly_budget_usd` field to "
            "`config/settings.json` (or use the wizard) to enable soft warnings + "
            "hard blocks."
        )

    if spend.daily_series:
        df_spend = pd.DataFrame(spend.daily_series).set_index("date")
        st.line_chart(df_spend["cost_usd"], color=PALETTE.accent)
    else:
        _html(empty_state("No runs logged yet", "Spend appears here after your first report run."))

    # ── v1.19: Privacy card ───────────────────────────────────────────────
    st.markdown("### 🔒 Privacy")
    with st.container(border=True):
        _html(
            f"<div style='color:{PALETTE.text};font-size:0.92rem;line-height:1.5;'>"
            "<strong>What gets sent to Anthropic:</strong> ticker symbols, your "
            "thesis text, recent activity summary, and configured prompt "
            "structure. No PII, no account numbers, no personal financial data "
            "beyond the symbols you hold.<br><br>"
            "<strong>What stays local:</strong> the raw Wealthsimple CSV, all "
            "recommendation logs, the decision journal, API keys, and the "
            "diagnostics log. Everything lives in your workspace folder.<br><br>"
            "<strong>What gets sent to yfinance / Finnhub / Polygon / Alpha "
            "Vantage / FRED / CoinGecko:</strong> only ticker symbols.<br>"
            "</div>"
        )
        col_export, col_delete = st.columns(2)
        with col_export:
            st.caption("Export everything to a zip — secrets (API keys, .env, uploads) are scrubbed automatically.")
            if st.button("📦 Export workspace…", key="privacy_export_button", width="stretch"):
                from src.workspace_export import export_summary_text, export_workspace

                result = export_workspace()
                if result.ok:
                    _toast("Workspace exported", icon="📦")
                    st.success(export_summary_text(result))
                    try:
                        st.download_button(
                            "⬇ Download zip",
                            result.output_path.read_bytes(),
                            file_name=result.output_path.name,
                            mime="application/zip",
                            width="stretch",
                            key="privacy_export_dl",
                        )
                    except OSError as exc:
                        st.warning(f"Zip written but couldn't read for download: {exc}")
                else:
                    st.error(export_summary_text(result))
        with col_delete:
            confirm = st.checkbox(
                "I understand this deletes my reports, logs, cost history, and journal entries.",
                key="privacy_delete_confirm",
            )
            if st.button(
                "🗑 Delete all local data",
                disabled=not confirm,
                key="privacy_delete_button",
            ):
                deleted = []
                for relpath in [
                    "data/recommendations_log",
                    "data/reports",
                    "data/decision_journal.json",
                    "data/thesis_log.json",
                    "cache",
                ]:
                    target = ROOT / relpath
                    if not target.exists():
                        continue
                    try:
                        if target.is_dir():
                            import shutil as _sh

                            _sh.rmtree(target)
                        else:
                            target.unlink()
                        deleted.append(relpath)
                    except OSError:
                        pass
                _clear_cost()
                deleted.append("cost_log.jsonl")
                _toast("Local data deleted", icon="🗑")
                st.success(f"Deleted: {', '.join(deleted) or 'nothing to delete'}")


with tab_diagnostics:
    _render_diagnostics()


# ─── Schedule (v1.18) ──────────────────────────────────────────────────────


def _render_schedule() -> None:
    from datetime import time as _time

    from src.notifications import send as _send_notify
    from src.scheduling import (
        ScheduleTime,
        current_schedule,
        install_schedule,
        preview_schedule,
        uninstall_schedule,
    )

    st.subheader("Scheduled runs")
    st.caption(
        "Install a per-user OS schedule so tech_stock runs itself at the times "
        "you pick. macOS uses launchd; Windows uses Task Scheduler; Linux uses "
        "your crontab. No sudo required."
    )

    st.markdown("### Current schedule")
    current = current_schedule()
    if current.installed:
        rows = [{"hour": f"{t.hour:02d}", "minute": f"{t.minute:02d}", "session_type": t.session_type} for t in current.times]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption(f"Backend: `{current.backend}` · file: `{current.path}`")
        if st.button("🗑 Uninstall schedule", key="schedule_uninstall"):
            result = uninstall_schedule()
            if result.ok:
                _toast("Schedule uninstalled", icon="⏰")
                st.success(result.message)
            else:
                st.error(result.message)
            st.rerun()
    else:
        _html(empty_state("No schedule installed", "Pick times below and click Install to start."))

    st.markdown("### New schedule")
    col_morn, col_noon, col_aft = st.columns(3)
    with col_morn:
        enable_morning = st.checkbox("Morning run", value=True, key="sched_morn_en")
        morn_time = st.time_input("Time", value=_time(7, 0), key="sched_morn_t")
    with col_noon:
        enable_midday = st.checkbox("Midday run", value=False, key="sched_mid_en")
        mid_time = st.time_input("Time", value=_time(11, 0), key="sched_mid_t")
    with col_aft:
        enable_afternoon = st.checkbox("Afternoon run", value=True, key="sched_aft_en")
        aft_time = st.time_input("Time", value=_time(14, 0), key="sched_aft_t")

    times: list[ScheduleTime] = []
    if enable_morning:
        times.append(ScheduleTime(hour=morn_time.hour, minute=morn_time.minute, session_type="morning"))
    if enable_midday:
        times.append(ScheduleTime(hour=mid_time.hour, minute=mid_time.minute, session_type="morning"))
    if enable_afternoon:
        times.append(ScheduleTime(hour=aft_time.hour, minute=aft_time.minute, session_type="afternoon"))

    if times:
        backend, body = preview_schedule(times)
        with st.expander(f"Preview ({backend} artefact)"):
            st.code(body, language="xml" if "xml" in backend or backend == "launchd" else "bash")
    else:
        st.caption("Enable at least one slot to preview the schedule.")

    col_install, col_test = st.columns(2)
    with col_install:
        if st.button("✓ Install schedule", type="primary", width="stretch", disabled=not times, key="schedule_install"):
            result = install_schedule(times)
            if result.ok:
                _toast("Schedule installed", icon="⏰")
                st.success(f"{result.message} (backend: {result.backend})")
            else:
                st.error(result.message or "Install failed.")
                if result.error:
                    st.caption(f"Detail: {result.error}")
            st.rerun()
    with col_test:
        if st.button("🔔 Send test notification", width="stretch", key="schedule_test_notify"):
            res = _send_notify(
                "tech_stock test",
                "If you see this, native notifications are working.",
                channel="general",
            )
            if res.sent:
                st.success(f"Sent via {res.backend}.")
            elif res.deduped:
                st.info("Suppressed by dedup window; try again in a few seconds.")
            else:
                st.warning(f"Send failed: {res.error or 'no backend available'}")

    st.markdown("### Notification channels")
    st.caption(
        "Channels are controlled by `config/settings.json` → `notifications.channels`. "
        "Edit them on the Editor tab. Defaults: report_complete, trailing_stop_breach, "
        "thesis_force_exit, high_priority_action are all ON."
    )


with tab_schedule:
    _render_schedule()


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
