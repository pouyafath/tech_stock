from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ui_support import (  # noqa: E402
    EDITABLE_JSON_FILES,
    default_run_settings,
    find_default_csvs,
    latest_report,
    list_reports,
    read_editable_json,
    read_text_file,
    relative_to_root,
    run_backtest_summary,
    run_report_from_ui,
    save_uploaded_bytes,
    write_editable_json,
)


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
    use_fallback_portfolio = st.checkbox("Use config/portfolio.json when no holdings CSV is selected")

tab_report, tab_run, tab_history, tab_backtest, tab_editor = st.tabs(
    ["Today's Report", "Run Report", "History", "Backtest", "Portfolio Editor"]
)

with tab_run:
    st.subheader("Generate Report")
    holdings_path_text = st.text_input(
        "Holdings CSV path",
        value=str(defaults["holdings"]) if defaults["holdings"] else "",
    )
    holdings_upload = st.file_uploader("Or upload Holdings CSV", type=["csv"], key="holdings_upload")

    activities_path_text = st.text_input(
        "Activities CSV path",
        value=str(defaults["activities"]) if defaults["activities"] else "",
    )
    activities_upload = st.file_uploader("Or upload Activities CSV", type=["csv"], key="activities_upload")

    if st.button("Run report", type="primary"):
        holdings_path = None
        activities_path = None

        if holdings_upload is not None:
            holdings_path = save_uploaded_bytes(holdings_upload.name, holdings_upload.getvalue())
        elif holdings_path_text.strip():
            holdings_path = Path(holdings_path_text).expanduser()
        elif not use_fallback_portfolio:
            st.error("Select a holdings CSV, upload one, or enable fallback portfolio mode.")
            st.stop()

        if activities_upload is not None:
            activities_path = save_uploaded_bytes(activities_upload.name, activities_upload.getvalue())
        elif activities_path_text.strip():
            activities_path = Path(activities_path_text).expanduser()

        for label, path in [("Holdings", holdings_path), ("Activities", activities_path)]:
            if path is not None and not path.exists():
                st.error(f"{label} CSV not found: {path}")
                st.stop()

        with st.spinner("Running market data, enrichment, Claude review, and report rendering..."):
            result = run_report_from_ui(
                session_type=session_type,
                holdings_csv=holdings_path,
                activities_csv=activities_path,
                budget_usd=budget_usd,
                budget_cad=budget_cad,
                model_choice=model_choice,
            )

        st.text_area("Console output", result.console, height=260)
        if not result.ok:
            st.error(result.error or "Report run failed.")
            st.stop()

        st.session_state["latest_report_path"] = str(result.report_path)
        st.success("Report generated.")
        col_report, col_csv, col_log = st.columns(3)
        col_report.write(f"Report: `{relative_to_root(result.report_path)}`")
        col_csv.write(f"CSV: `{relative_to_root(result.csv_path)}`")
        col_log.write(f"JSON: `{relative_to_root(result.log_path)}`")

with tab_report:
    selected_path = st.session_state.get("latest_report_path")
    report_path = Path(selected_path) if selected_path else latest_report()
    if not report_path:
        st.info("No markdown reports found yet.")
    else:
        st.caption(relative_to_root(report_path))
        st.markdown(read_text_file(report_path))

with tab_history:
    reports = list_reports(limit=50)
    if not reports:
        st.info("No report history found.")
    else:
        report_labels = [relative_to_root(path) for path in reports]
        selected_label = st.selectbox("Report", report_labels)
        selected_report = reports[report_labels.index(selected_label)]
        st.markdown(read_text_file(selected_report))

with tab_backtest:
    if st.button("Refresh backtest"):
        st.session_state["backtest_summary"] = run_backtest_summary()
    summary = st.session_state.get("backtest_summary") or run_backtest_summary()
    col_samples, col_return, col_hit = st.columns(3)
    overall = summary.get("overall") or {}
    col_samples.metric("Samples", summary.get("n_samples", 0))
    col_return.metric("Average return", f"{overall.get('avg_return_pct', 0):+.2f}%")
    col_hit.metric("Hit rate", f"{overall.get('hit_rate', 0):.0%}")
    st.json(summary)

with tab_editor:
    selected_label = st.selectbox("File", list(EDITABLE_JSON_FILES.keys()))
    state_key = f"editor_text_{selected_label}"
    if state_key not in st.session_state:
        st.session_state[state_key] = read_editable_json(selected_label)
    content = st.text_area("JSON", key=state_key, height=520)
    if st.button("Save JSON"):
        try:
            saved_path = write_editable_json(selected_label, content)
        except Exception as exc:
            st.error(str(exc))
        else:
            st.success(f"Saved {relative_to_root(saved_path)}")
