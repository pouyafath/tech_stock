from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ui_support import (  # noqa: E402
    EDITABLE_JSON_FILES,
    check_connectivity,
    default_run_settings,
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
    save_uploaded_bytes,
    validate_json_text,
    write_editable_json,
)


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _clean_console_line(line: str) -> str:
    return ANSI_RE.sub("", line).strip()


def _stored_upload_path(uploaded, state_key: str) -> Path | None:
    if uploaded is None:
        return None
    data = uploaded.getvalue()
    fingerprint = (uploaded.name, len(data))
    if st.session_state.get(f"{state_key}_fingerprint") != fingerprint:
        path = save_uploaded_bytes(uploaded.name, data)
        st.session_state[f"{state_key}_fingerprint"] = fingerprint
        st.session_state[f"{state_key}_path"] = str(path)
    stored = st.session_state.get(f"{state_key}_path")
    return Path(stored) if stored else None


def _display_download(label: str, path: Path | None, mime: str) -> None:
    if not path or not path.exists():
        st.write(f"{label}: unavailable")
        return
    st.write(f"{label}: `{relative_to_root(path)}`")
    st.download_button(f"Download {label}", path.read_bytes(), file_name=path.name, mime=mime)


def _rows_from_bucket(bucket: dict, label: str) -> list[dict]:
    rows = []
    for key, stats in (bucket or {}).items():
        rows.append({
            label: key,
            "n": stats.get("n", 0),
            "avg_return_pct": stats.get("avg_return_pct", 0),
            "hit_rate": stats.get("hit_rate", 0),
        })
    return rows


def _render_backtest_table(title: str, rows: list[dict], index_col: str) -> None:
    with st.expander(title, expanded=bool(rows)):
        if not rows:
            st.caption("No evaluated rows yet.")
            return
        df = pd.DataFrame(rows)
        st.dataframe(df, hide_index=True, width="stretch")
        chart_df = df.set_index(index_col)
        if "avg_return_pct" in chart_df:
            st.bar_chart(chart_df["avg_return_pct"])


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


st.set_page_config(page_title="tech_stock", layout="wide")

st.title("tech_stock")

defaults = find_default_csvs()
run_defaults = default_run_settings()

with st.sidebar:
    st.header("Run Settings")
    session_type = st.selectbox("Session", ["morning", "afternoon"], index=0)
    model_index = 1 if run_defaults["model_choice"] == "opus" else 0
    model_choice = st.selectbox(
        "Claude model",
        ["sonnet", "opus"],
        index=model_index,
        format_func=lambda value: "Sonnet 4.6" if value == "sonnet" else "Opus 4.7",
    )
    budget_usd = st.number_input("USD budget", min_value=0.0, value=run_defaults["budget_usd"], step=50.0)
    budget_cad = st.number_input("CAD budget", min_value=0.0, value=run_defaults["budget_cad"], step=50.0)

tab_dashboard, tab_report, tab_run, tab_history, tab_backtest, tab_editor = st.tabs(
    ["Dashboard", "Today's Report", "Run Report", "History", "Backtest", "Portfolio Editor"]
)

with tab_dashboard:
    st.subheader("Latest Run Dashboard")
    if st.button("Refresh dashboard"):
        st.session_state["latest_log_summary"] = latest_log_summary()
    summary = st.session_state.get("latest_log_summary") or latest_log_summary()
    if not summary:
        st.info("No recommendation JSON logs found yet.")
    elif summary.get("error"):
        st.error(summary["error"])
    else:
        st.caption(summary.get("session_file", ""))
        risk = summary.get("risk_dashboard") or {}
        beta = risk.get("beta") or {}
        usage = summary.get("usage") or {}
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Portfolio beta SPY", beta.get("SPY", "N/A"))
        c2.metric("Annualized vol", f"{risk.get('annualized_volatility_pct', 0):.1f}%")
        c3.metric("Max DD est.", f"{risk.get('max_drawdown_estimate_pct', 0):+.1f}%")
        c4.metric("Top-3 concentration", f"{risk.get('top3_concentration_pct', 0):.1f}%")
        c5.metric("Claude cost", f"${usage.get('cost_usd', 0):.4f}")

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### Priority Actions")
            priority = summary.get("priority_actions") or []
            if priority:
                st.dataframe(pd.DataFrame(priority), hide_index=True, width="stretch")
            else:
                st.caption("No priority actions in latest log.")

            st.markdown("#### Quality Warnings")
            warnings = summary.get("quality_warnings") or []
            if warnings:
                warning_df = pd.DataFrame(warnings)
                counts = warning_df["severity"].value_counts().to_dict() if "severity" in warning_df else {}
                st.caption(" | ".join(f"{severity}: {count}" for severity, count in counts.items()))
                st.dataframe(warning_df, hide_index=True, width="stretch")
            else:
                st.success("No quality warnings in latest log.")

        with c2:
            st.markdown("#### Hedge Suggestions")
            hedge = summary.get("hedge_suggestions") or []
            if hedge:
                st.dataframe(pd.DataFrame(hedge), hide_index=True, width="stretch")
            else:
                st.caption("No hedge suggestions in latest log.")

            st.markdown("#### Drift Vs Previous")
            drift = summary.get("drift") or []
            if drift:
                st.dataframe(pd.DataFrame(drift), hide_index=True, width="stretch")
            else:
                st.caption("No drift entries in latest log.")

        with st.expander("Cost, Tokens, And Correlation Detail"):
            st.json({"usage": usage, "correlated_pairs": risk.get("correlated_pairs") or []})

    with st.expander("Connectivity Check"):
        if st.button("Check APIs and data sources"):
            with st.spinner("Checking connectivity..."):
                checks = check_connectivity()
            st.dataframe(pd.DataFrame(checks), hide_index=True, width="stretch")

with tab_run:
    st.subheader("Generate Report")
    holdings_mode = st.radio(
        "Holdings input",
        ["File path", "Upload CSV", "Fallback config"],
        index=0 if defaults["holdings"] else 1,
        horizontal=True,
    )

    holdings_path_text = ""
    holdings_upload = None
    if holdings_mode == "File path":
        holdings_path_text = st.text_input(
            "Holdings CSV path",
            value=str(defaults["holdings"]) if defaults["holdings"] else "",
        )
        if not holdings_path_text:
            st.caption("No holdings CSV found in the default locations.")
    elif holdings_mode == "Upload CSV":
        holdings_upload = st.file_uploader("Upload Holdings CSV", type=["csv"], key="holdings_upload")
    else:
        st.info("This run will use config/portfolio.json instead of a Wealthsimple Holdings CSV.")

    activities_mode = st.radio(
        "Activities input",
        ["No activities", "File path", "Upload CSV"],
        index=1 if defaults["activities"] else 0,
        horizontal=True,
    )
    activities_path_text = ""
    activities_upload = None
    if activities_mode == "File path":
        activities_path_text = st.text_input(
            "Activities CSV path",
            value=str(defaults["activities"]) if defaults["activities"] else "",
        )
        if not activities_path_text:
            st.caption("No activities CSV found in the default locations.")
    elif activities_mode == "Upload CSV":
        activities_upload = st.file_uploader("Upload Activities CSV", type=["csv"], key="activities_upload")

    preview_holdings_path, preview_activities_path = _resolve_run_inputs(
        holdings_mode,
        holdings_path_text,
        holdings_upload,
        activities_mode,
        activities_path_text,
        activities_upload,
    )
    if preview_holdings_path:
        with st.expander("Holdings Preview", expanded=True):
            preview = preview_holdings_csv(preview_holdings_path)
            if preview.get("ok"):
                st.caption(f"{preview['position_count']} positions | {preview.get('exported_at', '')}")
                st.dataframe(pd.DataFrame(preview["rows"]), hide_index=True, width="stretch")
            else:
                st.warning(preview.get("error", "Could not preview holdings."))

    if st.button("Run report", type="primary"):
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

        status = st.status("Running market data, enrichment, Claude review, and report rendering...", expanded=True)
        progress_box = st.empty()
        progress_lines: list[str] = []

        def on_progress(line: str) -> None:
            cleaned = _clean_console_line(line)
            if not cleaned:
                return
            progress_lines.append(cleaned)
            progress_box.code("\n".join(progress_lines[-40:]))

        result = run_report_from_ui(
            session_type=session_type,
            holdings_csv=holdings_path,
            activities_csv=activities_path,
            budget_usd=budget_usd,
            budget_cad=budget_cad,
            model_choice=model_choice,
            on_progress=on_progress,
        )

        st.text_area("Console output", result.console, height=260)
        if not result.ok:
            status.update(label="Report failed", state="error")
            st.error(result.error or "Report run failed.")
            st.stop()

        status.update(label="Report generated", state="complete")
        st.session_state["latest_report_path"] = str(result.report_path)
        st.session_state["latest_log_summary"] = latest_log_summary()
        st.success("Report generated.")
        col_report, col_csv, col_log = st.columns(3)
        with col_report:
            _display_download("Report", result.report_path, "text/markdown")
        with col_csv:
            _display_download("CSV", result.csv_path, "text/csv")
        with col_log:
            _display_download("JSON", result.log_path, "application/json")

with tab_report:
    selected_path = st.session_state.get("latest_report_path")
    report_path = Path(selected_path) if selected_path else latest_report()
    if not report_path:
        st.info("No markdown reports found yet.")
    else:
        st.caption(relative_to_root(report_path))
        st.markdown(read_text_file(report_path))

with tab_history:
    reports = list_reports(limit=200)
    if not reports:
        st.info("No report history found.")
    else:
        filter_col, search_col = st.columns([1, 3])
        session_filter = filter_col.selectbox("Session", ["all", "morning", "afternoon"])
        search = search_col.text_input("Search filename")
        filtered = [
            path for path in reports
            if (session_filter == "all" or session_filter in path.name)
            and (not search or search.lower() in path.name.lower())
        ]
        if not filtered:
            st.info("No reports match the selected filters.")
        else:
            labels = [relative_to_root(path) for path in filtered]
            compare = st.checkbox("Compare two reports")
            if compare and len(filtered) > 1:
                col_a, col_b = st.columns(2)
                with col_a:
                    sel_a = st.selectbox("Report A", labels, key="hist_a")
                    st.markdown(read_text_file(filtered[labels.index(sel_a)]))
                with col_b:
                    sel_b = st.selectbox("Report B", labels, index=min(1, len(labels) - 1), key="hist_b")
                    st.markdown(read_text_file(filtered[labels.index(sel_b)]))
            else:
                selected_label = st.selectbox("Report", labels)
                selected_report = filtered[labels.index(selected_label)]
                st.markdown(read_text_file(selected_report))

with tab_backtest:
    if st.button("Refresh backtest"):
        st.session_state["backtest_summary"] = run_backtest_summary()
    backtest = st.session_state.get("backtest_summary") or run_backtest_summary()
    col_samples, col_return, col_hit = st.columns(3)
    overall = backtest.get("overall") or {}
    col_samples.metric("Samples", backtest.get("n_samples", 0))
    col_return.metric("Average return", f"{overall.get('avg_return_pct', 0):+.2f}%")
    col_hit.metric("Hit rate", f"{overall.get('hit_rate', 0):.0%}")

    _render_backtest_table(
        "By Action",
        _rows_from_bucket(backtest.get("avg_return_by_action") or {}, "action"),
        "action",
    )
    _render_backtest_table(
        "By Conviction",
        _rows_from_bucket(backtest.get("avg_return_by_conviction") or {}, "conviction"),
        "conviction",
    )
    _render_backtest_table(
        "By Ticker",
        _rows_from_bucket(backtest.get("avg_return_by_ticker") or {}, "ticker"),
        "ticker",
    )

    with st.expander("Recent Realized Examples", expanded=True):
        examples = backtest.get("recent_realized_examples") or []
        if examples:
            st.dataframe(pd.DataFrame(examples), hide_index=True, width="stretch")
        else:
            st.caption("No realized examples yet.")

    with st.expander("Raw backtest JSON"):
        st.json(backtest)

with tab_editor:
    selected_label = st.selectbox("File", list(EDITABLE_JSON_FILES.keys()))
    state_key = f"editor_text_{selected_label}"
    if state_key not in st.session_state:
        st.session_state[state_key] = read_editable_json(selected_label)
    content = st.text_area("JSON", key=state_key, height=520)
    is_valid, validation_message = validate_json_text(content)
    if is_valid:
        st.success(validation_message)
        with st.expander("Parsed JSON preview"):
            st.json(json.loads(content))
    else:
        st.error(validation_message)
    if st.button("Save JSON", disabled=not is_valid):
        try:
            saved_path = write_editable_json(selected_label, content)
        except Exception as exc:
            st.error(str(exc))
        else:
            st.success(f"Saved {relative_to_root(saved_path)}")
