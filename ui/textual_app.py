from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, Markdown, RichLog, Select, Static, TabbedContent, TabPane, TextArea

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ui_support import (  # noqa: E402
    EDITABLE_JSON_FILES,
    api_health_view,
    app_self_test_view,
    apply_available_update,
    buy_signal_view,
    check_update_available,
    csv_choice_view,
    current_app_version,
    data_files_view,
    decision_journal_view,
    decision_scorecard_summary,
    default_run_settings,
    demo_smoke_view,
    discover_csv_files,
    export_support_bundle,
    find_default_csvs,
    latest_log_summary,
    latest_report,
    learning_view,
    list_reports,
    paid_run_readiness_view,
    pre_run_checklist_view,
    read_editable_json,
    read_text_file,
    relative_to_root,
    report_history_view,
    report_review_view,
    run_backtest_summary,
    run_report_from_ui,
    save_selected_data_files,
    setup_readiness_view,
    support_bundle_preview,
    validate_json_text,
    write_editable_json,
)

try:
    from src.ui_theme import action_meta, severity_meta  # noqa: E402
except Exception:  # pragma: no cover

    def action_meta(value):  # type: ignore[misc]
        return {"color": "white"}

    def severity_meta(value):  # type: ignore[misc]
        return {"color": "white"}


ANSI_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

# Columns whose cells should be colour-styled using the shared palette.
_ACTION_COLUMN_KEYS = {"action", "recommended_action", "actual_action"}
_SEVERITY_COLUMN_KEYS = {"severity"}
_READINESS_COLUMN_KEYS = {"readiness"}

_READINESS_COLOURS = {
    "trade_ready": "#22c55e",
    "trade ready": "#22c55e",
    "review_first": "#f59e0b",
    "review first": "#f59e0b",
    "blocked": "#ef4444",
}


def _coloured_action(value) -> Text:
    """Wrap an action value in a colour-styled rich.Text using the shared palette."""
    text = str(value or "").strip()
    if not text:
        return Text("")
    color = action_meta(text).get("color", "white")
    return Text(text.upper(), style=f"bold {color}")


def _coloured_severity(value) -> Text:
    text = str(value or "").strip()
    if not text:
        return Text("")
    color = severity_meta(text).get("color", "white")
    return Text(text.lower(), style=f"bold {color}")


def _coloured_readiness(value) -> Text:
    text = str(value or "").strip()
    if not text:
        return Text("")
    color = _READINESS_COLOURS.get(text.lower(), "white")
    return Text(text, style=f"bold {color}")


class UpdatePrompt(ModalScreen[bool]):
    """Small yes/no prompt shown when startup finds a newer release."""

    CSS = """
    UpdatePrompt {
        align: center middle;
        background: rgba(0, 0, 0, 0.55);
    }

    #update_prompt {
        width: 76;
        height: auto;
        padding: 2 4;
        border: thick $accent;
        background: $surface;
    }

    #update_prompt_title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    #update_prompt_body {
        margin-bottom: 1;
        color: $text;
    }

    #update_prompt_subtle {
        color: $text-muted;
        text-style: italic;
        margin-bottom: 1;
    }

    #update_prompt_buttons {
        margin-top: 1;
        align: center middle;
    }

    #confirm_update {
        margin-right: 2;
    }
    """

    def __init__(self, latest_version: str, current_version: str) -> None:
        super().__init__()
        self.latest_version = latest_version
        self.current_version = current_version

    def compose(self) -> ComposeResult:
        with Vertical(id="update_prompt"):
            yield Static(f"🆙  tech_stock v{self.latest_version} is available", id="update_prompt_title")
            yield Static(
                f"You are currently on v{self.current_version}. The update will replace the bundled app while keeping all of your data.",
                id="update_prompt_body",
            )
            yield Static(
                "Kept: reports · recommendation logs · uploaded CSVs · config files · API keys.",
                id="update_prompt_subtle",
            )
            with Horizontal(id="update_prompt_buttons"):
                yield Button("Update now", id="confirm_update", variant="primary")
                yield Button("Later", id="dismiss_update")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm_update")


class TechStockTUI(App):
    TITLE = "tech_stock"
    SUB_TITLE = "Portfolio report dashboard"
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh_current", "Refresh"),
        ("ctrl+r", "run_report", "Run"),
        ("ctrl+s", "save_editor", "Save"),
    ]

    CSS = """
    Screen {
        background: $surface;
    }

    TabbedContent {
        height: 1fr;
    }

    .form-row {
        height: auto;
        margin-bottom: 1;
    }

    .form-col {
        width: 1fr;
        padding-right: 2;
    }

    #console {
        height: 14;
        border: solid $primary;
        margin-top: 1;
    }

    #dashboard_log, #connectivity_log, #buy_signals_log, #backtest_log, #update_log {
        height: 1fr;
        border: solid $primary;
        padding: 1;
    }

    #today_markdown, #history_markdown {
        height: 1fr;
        border: solid $primary;
        padding: 1;
        overflow-y: scroll;
    }

    #editor_text {
        height: 1fr;
        border: solid $primary;
    }

    #status, #editor_status {
        height: 3;
        color: $text-muted;
    }
    """

    def compose(self) -> ComposeResult:
        defaults = find_default_csvs()
        run_defaults = default_run_settings()
        model_choice = run_defaults["model_choice"]
        history_options = self._history_options()
        holdings_options = self._csv_options("holdings-report", defaults["holdings"])
        activities_options = self._csv_options("activities-export", defaults["activities"])
        yield Header()
        with TabbedContent(initial="dashboard"):
            with TabPane("Dashboard", id="dashboard"):
                with Horizontal(classes="form-row"):
                    yield Button("Refresh dashboard", id="refresh_dashboard")
                    yield Button("Check connectivity", id="check_connectivity")
                yield RichLog(id="dashboard_log", wrap=True, highlight=True)
                yield RichLog(id="connectivity_log", wrap=True, highlight=True)
            with TabPane("Buy Signals", id="buy_signals"):
                with Horizontal(classes="form-row"):
                    yield Button("Refresh buy signals", id="refresh_buy_signals")
                    yield Select(
                        [("All actions", "all"), ("BUY/ADD", "buy_add"), ("add_on_dip", "add_on_dip")],
                        value="all",
                        id="buy_action_filter",
                    )
                    yield Select(
                        [
                            ("All readiness", "all"),
                            ("Trade Ready", "TRADE_READY"),
                            ("Review First", "REVIEW_FIRST"),
                            ("Blocked", "BLOCKED"),
                        ],
                        value="all",
                        id="buy_readiness_filter",
                    )
                yield RichLog(id="buy_signals_log", wrap=True, highlight=True)
            with TabPane("Run Report", id="run"):
                with Horizontal(classes="form-row"):
                    with Vertical(classes="form-col"):
                        yield Static("Session")
                        yield Select(
                            [("Morning", "morning"), ("Afternoon", "afternoon")],
                            value="morning",
                            id="session",
                        )
                    with Vertical(classes="form-col"):
                        yield Static("Model")
                        yield Select(
                            [("Sonnet 4.6", "sonnet"), ("Opus 4.7", "opus")],
                            value=model_choice,
                            id="model",
                        )
                with Horizontal(classes="form-row"):
                    with Vertical(classes="form-col"):
                        yield Static("USD budget")
                        yield Input(value=str(run_defaults["budget_usd"]), id="budget_usd")
                    with Vertical(classes="form-col"):
                        yield Static("CAD budget")
                        yield Input(value=str(run_defaults["budget_cad"]), id="budget_cad")
                yield Static("Discovered Holdings CSV")
                yield Select(holdings_options, value=holdings_options[0][1], id="holdings_select", allow_blank=False)
                yield Static("Holdings CSV path (blank uses config/portfolio.json)")
                yield Input(value=str(defaults["holdings"] or ""), id="holdings_path")
                yield Static("Discovered Activities CSV")
                yield Select(activities_options, value=activities_options[0][1], id="activities_select", allow_blank=False)
                yield Static("Activities CSV path (optional)")
                yield Input(value=str(defaults["activities"] or ""), id="activities_path")
                with Horizontal(classes="form-row"):
                    yield Button("Check setup", id="check_setup")
                    yield Button("Save file defaults", id="save_data_files")
                    yield Button("Run demo smoke", id="run_demo_smoke")
                    yield Button("Run report", id="run_report", variant="primary")
                yield Static("Ready.", id="status")
                yield RichLog(id="console", wrap=True, highlight=True)
            with TabPane("Data Files", id="data_files"):
                with Horizontal(classes="form-row"):
                    yield Button("Refresh data files", id="refresh_data_files")
                    yield Button("Save current run paths", id="save_data_files_from_tab")
                    yield Button("Run demo smoke", id="run_demo_smoke_files")
                    yield Button("Export support bundle", id="export_support_bundle")
                yield RichLog(id="data_files_log", wrap=True, highlight=True)
            with TabPane("Today's Report", id="today"):
                yield Button("Refresh report", id="refresh_today")
                yield Static("", id="today_path")
                yield Markdown("", id="today_markdown")
            with TabPane("Report Review", id="report_review"):
                yield Button("Refresh review", id="refresh_report_review")
                yield RichLog(id="report_review_log", wrap=True, highlight=True)
            with TabPane("History", id="history"):
                yield Button("Refresh history", id="refresh_history")
                yield Select(history_options, value=history_options[0][1], allow_blank=False, id="history_select")
                yield Button("Load selected report", id="load_history", disabled=history_options[0][1] == "__none__")
                yield Markdown("", id="history_markdown")
            with TabPane("Backtest", id="backtest"):
                yield Button("Refresh backtest", id="refresh_backtest")
                yield RichLog(id="backtest_log", wrap=True, highlight=True)
            with TabPane("Portfolio Editor", id="editor"):
                yield Select([(label, label) for label in EDITABLE_JSON_FILES], value="Settings", id="editor_file")
                yield Button("Load JSON", id="load_json")
                yield Button("Save JSON", id="save_json", variant="success")
                yield Static("", id="editor_status")
                yield TextArea("", language="json", id="editor_text")
            with TabPane("Updates", id="updates"):
                with Horizontal(classes="form-row"):
                    yield Button("Check for updates", id="check_updates")
                    yield Button("Update now", id="apply_update", variant="primary", disabled=True)
                yield RichLog(id="update_log", wrap=True, highlight=True)
        yield Footer()

    def on_mount(self) -> None:
        self.latest_update_info = None
        self._load_dashboard()
        self._show_buy_signals_placeholder()
        self._load_today_report()
        self._load_report_review()
        self._load_history_report()
        # Backtest is NOT loaded on mount — it fetches live price data from
        # yfinance for every past recommendation, which can take 20-30 s.
        # User triggers it explicitly with the "Refresh backtest" button.
        self._show_backtest_placeholder()
        self._load_editor_text()
        self._load_data_files()
        if os.environ.get("TECH_STOCK_SKIP_UPDATE_CHECK") != "1":
            self.run_worker(self._check_updates_async(startup=True), exclusive=False)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "run_report":
            await self._run_report()
        elif button_id == "check_setup":
            self._render_pre_run_checklist()
        elif button_id in {"save_data_files", "save_data_files_from_tab"}:
            self._save_data_file_defaults()
        elif button_id in {"run_demo_smoke", "run_demo_smoke_files"}:
            await self._run_demo_smoke()
        elif button_id == "refresh_data_files":
            self._load_data_files()
        elif button_id == "export_support_bundle":
            self._export_support_bundle()
        elif button_id == "refresh_dashboard":
            self._load_dashboard()
        elif button_id == "check_connectivity":
            await self._check_connectivity()
        elif button_id == "refresh_buy_signals":
            self.run_worker(self._load_buy_signals_async(), exclusive=True)
        elif button_id == "refresh_today":
            self._load_today_report()
            self._load_report_review()
        elif button_id == "refresh_report_review":
            self._load_report_review()
        elif button_id == "refresh_history":
            self._refresh_history_select()
            self._load_history_report()
        elif button_id == "load_history":
            self._load_history_report()
        elif button_id == "refresh_backtest":
            self.run_worker(self._load_backtest_async(), exclusive=True)
        elif button_id == "load_json":
            self._load_editor_text()
        elif button_id == "save_json":
            self._save_editor_text()
        elif button_id == "check_updates":
            self.run_worker(self._check_updates_async(startup=False), exclusive=True)
        elif button_id == "apply_update":
            self.run_worker(self._apply_update_async(), exclusive=True)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "editor_file":
            self._load_editor_text()
        elif event.select.id == "holdings_select" and isinstance(event.value, str) and event.value != "__none__":
            self.query_one("#holdings_path", Input).value = "" if event.value == "__fallback__" else event.value
        elif event.select.id == "activities_select" and isinstance(event.value, str) and event.value != "__none__":
            self.query_one("#activities_path", Input).value = "" if event.value == "__none__" else event.value

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == "editor_text":
            self._validate_editor_text()

    def action_refresh_current(self) -> None:
        active = self.query_one(TabbedContent).active
        if active == "dashboard":
            self._load_dashboard()
        elif active == "today":
            self._load_today_report()
        elif active == "history":
            self._refresh_history_select()
            self._load_history_report()
        elif active == "data_files":
            self._load_data_files()
        elif active == "backtest":
            self.run_worker(self._load_backtest_async(), exclusive=True)
        elif active == "editor":
            self._load_editor_text()
        elif active == "updates":
            self.run_worker(self._check_updates_async(startup=False), exclusive=True)

    def action_run_report(self) -> None:
        self.run_worker(self._run_report(), exclusive=True)

    def action_save_editor(self) -> None:
        self._save_editor_text()

    async def _run_report(self) -> None:
        status = self.query_one("#status", Static)
        console = self.query_one("#console", RichLog)
        checklist = self._render_pre_run_checklist()
        if not checklist.get("can_run"):
            status.update(f"Blocked: {checklist.get('next_action')}")
            return
        console.clear()
        status.update("Running report. This can take several minutes for a full two-pass Claude run.")

        def on_progress(line: str) -> None:
            self.call_from_thread(self._console_write, line)

        result = await asyncio.to_thread(
            run_report_from_ui,
            session_type=self.query_one("#session", Select).value,
            holdings_csv=self.query_one("#holdings_path", Input).value,
            activities_csv=self.query_one("#activities_path", Input).value,
            budget_usd=self._float_input("#budget_usd"),
            budget_cad=self._float_input("#budget_cad"),
            model_choice=self.query_one("#model", Select).value,
            on_progress=on_progress,
        )

        if not result.ok:
            status.update(f"Failed: {result.error}")
            return

        status.update(f"Done. Report: {relative_to_root(result.report_path)} | CSV: {relative_to_root(result.csv_path)}")
        self._load_dashboard()
        self._load_today_report(result.report_path)
        self._refresh_history_select()

    def _console_write(self, line: str) -> None:
        cleaned = ANSI_RE.sub("", line).strip()
        if cleaned:
            self.query_one("#console", RichLog).write(cleaned)

    def _float_input(self, selector: str) -> float:
        value = self.query_one(selector, Input).value.strip()
        if not value:
            return 0.0
        try:
            return max(float(value), 0.0)
        except ValueError:
            return 0.0

    def _current_run_paths(self) -> tuple[str, str]:
        return self.query_one("#holdings_path", Input).value, self.query_one("#activities_path", Input).value

    def _render_pre_run_checklist(self) -> dict:
        holdings, activities = self._current_run_paths()
        readiness = paid_run_readiness_view(
            holdings_csv=holdings,
            activities_csv=activities,
            use_fallback_config=not bool(holdings.strip()),
            model_choice=self.query_one("#model", Select).value,
            budget_usd=self._float_input("#budget_usd"),
            budget_cad=self._float_input("#budget_cad"),
        )
        checklist = pre_run_checklist_view(
            holdings_csv=holdings,
            activities_csv=activities,
            use_fallback_config=not bool(holdings.strip()),
        )
        console = self.query_one("#console", RichLog)
        console.clear()
        readiness_table = Table(title=f"Ready To Run — {readiness.get('status')}")
        readiness_table.add_column("Step")
        readiness_table.add_column("Status")
        readiness_table.add_column("Detail")
        readiness_table.add_column("Action")
        for row in readiness.get("steps") or []:
            status = row.get("status") or ""
            style = "bold #ef4444" if status == "BLOCKED" else "#f59e0b" if status == "WARN" else "#22c55e"
            readiness_table.add_row(row.get("step", ""), Text(status, style=style), row.get("detail", ""), row.get("action", ""))
        console.write(readiness_table)
        if readiness.get("summary"):
            console.write(Text(readiness.get("summary", ""), style="bold #f59e0b" if readiness.get("status") != "READY" else "#22c55e"))
        table = Table(title="Pre-run Checklist")
        table.add_column("Check")
        table.add_column("Status")
        table.add_column("Detail")
        table.add_column("Action")
        for row in checklist.get("rows") or []:
            style = "bold #ef4444" if row.get("blocking") else "#f59e0b" if row.get("status") == "WARN" else "#22c55e"
            table.add_row(row.get("check", ""), Text(row.get("status", ""), style=style), row.get("detail", ""), row.get("action", ""))
        console.write(table)
        self.query_one("#status", Static).update(readiness.get("next_action") or "Ready.")
        return checklist

    def _save_data_file_defaults(self) -> None:
        holdings, activities = self._current_run_paths()
        path = save_selected_data_files(holdings.strip() or None, activities.strip() or None)
        self.query_one("#status", Static).update(f"Saved file defaults: {relative_to_root(path)}")
        self._load_data_files()

    async def _run_demo_smoke(self) -> None:
        console = self.query_one("#console", RichLog)
        console.clear()
        result = await asyncio.to_thread(demo_smoke_view)
        table = Table(title="Demo Smoke Test")
        table.add_column("Check")
        table.add_column("Result")
        table.add_column("Detail")
        for row in result.get("checks") or []:
            table.add_row(
                row.get("name", ""),
                Text("OK" if row.get("ok") else "FAIL", style="#22c55e" if row.get("ok") else "bold #ef4444"),
                row.get("detail", ""),
            )
        console.write(table)
        self.query_one("#status", Static).update("Demo smoke passed." if result.get("ok") else "Demo smoke failed.")

    def _load_data_files(self) -> None:
        try:
            log = self.query_one("#data_files_log", RichLog)
        except Exception:
            return
        log.clear()
        setup = setup_readiness_view()
        setup_table = Table(title=f"Setup Readiness — {setup.get('status')}")
        setup_table.add_column("Check")
        setup_table.add_column("Status")
        setup_table.add_column("Detail")
        setup_table.add_column("Action")
        for row in setup.get("rows") or []:
            status = row.get("status") or ""
            style = "bold #ef4444" if status == "FAIL" else "#f59e0b" if status == "WARN" else "#22c55e"
            setup_table.add_row(row.get("check", ""), Text(status, style=style), row.get("detail", ""), row.get("action", ""))
        log.write(setup_table)
        if setup.get("next_action"):
            log.write(
                Text(f"Next action: {setup.get('next_action')}", style="bold #f59e0b" if setup.get("status") != "READY" else "#22c55e")
            )

        self_test = app_self_test_view()
        self_test_table = Table(title=f"App Self-Test — {self_test.get('status')}")
        self_test_table.add_column("Check")
        self_test_table.add_column("Status")
        self_test_table.add_column("Detail")
        self_test_table.add_column("Action")
        for row in self_test.get("rows") or []:
            status = row.get("status") or ""
            style = "bold #ef4444" if status == "FAIL" else "#f59e0b" if status == "WARN" else "#22c55e"
            self_test_table.add_row(row.get("check", ""), Text(status, style=style), row.get("detail", ""), row.get("action", ""))
        log.write(self_test_table)

        view = data_files_view()
        table = Table(title=f"Data Files / Workspace — defaults: {relative_to_root(view.get('settings_path'))}")
        table.add_column("Resource")
        table.add_column("Status")
        table.add_column("Path")
        table.add_column("Detail")
        for row in view.get("rows") or []:
            status = row.get("status") or ""
            style = "bold #ef4444" if status == "FAIL" else "#f59e0b" if status == "WARN" else "#22c55e"
            table.add_row(row.get("resource", ""), Text(status, style=style), row.get("path", ""), row.get("detail", ""))
        log.write(table)

        for kind in ("holdings", "activities"):
            candidates = Table(title=f"{kind.title()} CSV Candidates")
            candidates.add_column("Pick")
            candidates.add_column("Status")
            candidates.add_column("File")
            candidates.add_column("Age")
            candidates.add_column("Rows")
            candidates.add_column("Reason")
            for row in csv_choice_view(kind):
                status = row.get("status") or ""
                style = "bold #ef4444" if status == "BLOCKED" else "#f59e0b" if status in {"REVIEW", "DEMO_ONLY"} else "#22c55e"
                candidates.add_row(
                    "YES" if row.get("recommended") else "",
                    Text(status, style=style),
                    row.get("filename", ""),
                    str(row.get("age_hours") if row.get("age_hours") is not None else ""),
                    str(row.get("row_count_hint") or ""),
                    row.get("reason") or row.get("action") or "",
                )
            log.write(candidates)

        preview = support_bundle_preview(include_demo_smoke=False)
        bundle_table = Table(title="Support Bundle Preview")
        bundle_table.add_column("File")
        bundle_table.add_column("Privacy")
        bundle_table.add_column("Description")
        for row in preview.get("files") or []:
            bundle_table.add_row(row.get("path", ""), row.get("privacy", ""), row.get("description", ""))
        log.write(bundle_table)
        log.write(Text("Excluded: " + ", ".join(preview.get("excluded") or []), style="#94a3b8"))

    def _export_support_bundle(self) -> None:
        log = self.query_one("#data_files_log", RichLog)
        result = export_support_bundle(include_demo_smoke=False)
        log.write(result.get("summary") or result.get("error") or "Support bundle export finished.")

    def _csv_options(self, prefix: str, default: Path | None) -> list[tuple[str, str]]:
        options: list[tuple[str, str]] = []
        if prefix == "holdings-report":
            options.append(("Use fallback config/portfolio.json", "__fallback__"))
        else:
            options.append(("No activities CSV", "__none__"))
        for path in discover_csv_files(prefix):
            options.append((relative_to_root(path), str(path)))
        if default and str(default) not in {value for _, value in options}:
            options.insert(1, (relative_to_root(default), str(default)))
        return options

    def _history_options(self) -> list[tuple[str, str]]:
        rows = report_history_view(limit=50).get("rows") or []
        if not rows:
            return [("No reports found", "__none__")]
        options = []
        for row in rows:
            path = row.get("report_path")
            if not path:
                continue
            label = (
                f"{row.get('report')} | B/A {row.get('buy_add_count', 0)} | "
                f"T/S {row.get('trim_sell_count', 0)} | W {row.get('warning_count', 0)}"
            )
            options.append((label, str(path)))
        return options or [("No reports found", "__none__")]

    def _refresh_history_select(self) -> None:
        select = self.query_one("#history_select", Select)
        current = select.value if isinstance(select.value, str) else None
        options = self._history_options()
        values = {value for _, value in options}
        select.set_options(options)
        select.value = current if current in values else options[0][1]
        self.query_one("#load_history", Button).disabled = options[0][1] == "__none__"

    def _load_dashboard(self) -> None:
        log = self.query_one("#dashboard_log", RichLog)
        log.clear()
        summary = latest_log_summary()
        if not summary:
            log.write(Text("No recommendation JSON logs found yet.", style="dim italic"))
            log.write(Text("Run a report from the 'Run Report' tab to populate the dashboard.", style="dim"))
            return
        if summary.get("error"):
            log.write(Text(f"Failed to read latest log: {summary['error']}", style="bold #ef4444"))
            return

        log.write(Text(f"📂 Latest log: {summary.get('session_file', '')}", style="bold #22c55e"))
        risk = summary.get("risk_dashboard") or {}
        beta = risk.get("beta") or {}
        usage = summary.get("usage") or {}
        metrics = Table(title="Dashboard Metrics", title_style="bold #22c55e")
        metrics.add_column("Metric")
        metrics.add_column("Value", justify="right")
        total_value = risk.get("total_value_usd")
        if total_value is not None:
            metrics.add_row("Portfolio value", Text(f"${total_value:,.2f}", style="bold white"))
        metrics.add_row("Beta SPY", str(beta.get("SPY", "N/A")))
        metrics.add_row("Annualized volatility", f"{risk.get('annualized_volatility_pct', 0):.1f}%")
        drawdown = risk.get("max_drawdown_estimate_pct", 0)
        dd_style = "bold #ef4444" if drawdown < -10 else "bold #f59e0b" if drawdown < -5 else "white"
        metrics.add_row("Max drawdown estimate", Text(f"{drawdown:+.1f}%", style=dd_style))
        conc = risk.get("top3_concentration_pct", 0)
        conc_style = "bold #f59e0b" if conc > 40 else "white"
        metrics.add_row("Top-3 concentration", Text(f"{conc:.1f}%", style=conc_style))
        metrics.add_row("Claude cost", Text(f"${usage.get('cost_usd', 0):.4f}", style="bold #22c55e"))
        metrics.add_row("Tokens", f"{usage.get('total_tokens', 0):,}")
        log.write(metrics)

        self._write_rows_table(log, "Priority Actions", summary.get("priority_actions") or [], ["order", "ticker", "action", "rationale"])
        self._write_rows_table(
            log, "Quality Warnings", summary.get("quality_warnings") or [], ["severity", "code", "ticker", "message", "action_required"]
        )
        self._write_rows_table(
            log, "Hedge Suggestions", summary.get("hedge_suggestions") or [], ["type", "instrument", "action", "risk_note"]
        )
        self._write_rows_table(
            log, "Drift Vs Previous", self._flatten_drift(summary.get("drift") or []), ["ticker", "drift_type", "was", "now"]
        )
        journal = decision_journal_view().get("status") or {}
        journal_table = Table(title="Decision Journal")
        journal_table.add_column("Metric")
        journal_table.add_column("Value", justify="right")
        journal_table.add_row("Entries", str(journal.get("total", 0)))
        journal_table.add_row("Pending", str(journal.get("pending", 0)))
        journal_table.add_row("Recorded", str(journal.get("recorded", 0)))
        log.write(journal_table)

        # v1.16: per-horizon edge — one compact line so the Dashboard tab
        # surfaces the learning-loop signal without a dedicated tab.
        try:
            learning = learning_view()
            edge = learning.get("edge_by_horizon") or {}
        except Exception:  # noqa: BLE001 — never break the dashboard on a soft failure
            edge = {}
        if edge:
            edge_parts = [
                f"{int(h)}d {float(edge[h].get('user_avg_return_pct', 0.0)):+.1f}%" for h in sorted(edge.keys(), key=lambda x: int(x))
            ]
            log.write(Text("Your edge by horizon: " + " | ".join(edge_parts), style="bold #38bdf8"))

    async def _check_connectivity(self) -> None:
        log = self.query_one("#connectivity_log", RichLog)
        log.clear()
        log.write("Checking connectivity...")
        health = await asyncio.to_thread(api_health_view)
        log.clear()
        log.write(f"{health.get('ok_count', 0)} OK / {health.get('fail_count', 0)} unavailable | storage: {health.get('storage_mode')}")
        self._write_rows_table(log, "Connectivity", health.get("checks") or [], ["source", "ok", "latency_ms", "detail"])

    def _show_buy_signals_placeholder(self) -> None:
        log = self.query_one("#buy_signals_log", RichLog)
        log.clear()
        log.write(Text("🎯 Buy Signals", style="bold #22c55e"))
        log.write(Text("Press Refresh buy signals to load source-backed BUY/ADD and add-on-dip candidates.", style="dim"))
        log.write(Text("Filter by action or readiness using the dropdowns above.", style="dim italic"))

    async def _load_buy_signals_async(self) -> None:
        log = self.query_one("#buy_signals_log", RichLog)
        log.clear()
        log.write("Refreshing buy signals...")
        action_filter = self.query_one("#buy_action_filter", Select).value
        readiness_filter = self.query_one("#buy_readiness_filter", Select).value
        data = await asyncio.to_thread(
            buy_signal_view,
            action_filter=str(action_filter or "all"),
            readiness_filter=str(readiness_filter or "all"),
        )
        log.clear()
        if data.get("error"):
            log.write(data["error"])
            return
        counts = data.get("counts") or {}
        log.write(
            f"Latest log: {data.get('session_file')} | fetched {data.get('fetched_at')} | "
            f"{counts.get('TRADE_READY', 0)} ready / {counts.get('REVIEW_FIRST', 0)} review / {counts.get('BLOCKED', 0)} blocked"
        )
        self._write_rows_table(
            log,
            "Buy Signal Overview",
            data.get("overview_rows") or [],
            ["readiness", "ticker", "action", "conviction", "price", "consensus", "mean_upside_pct", "warnings"],
        )
        for item in data.get("cards") or []:
            readiness = item.get("readiness") or {}
            log.write(f"\n{item.get('ticker')} — {readiness.get('label')} — catalyst: {item.get('catalyst_source') or 'N/A'}")
            log.write(f"Readiness reasons: {'; '.join(readiness.get('reasons') or [])}")
            log.write(
                f"Quote: {item.get('current_price')} | {item.get('quote_source') or 'unavailable'} | {item.get('quote_timestamp_utc') or 'missing timestamp'}"
            )
            log.write(f"Risk/invalidation: {item.get('risk_or_invalidation') or 'N/A'}")
            for note in item.get("source_notes") or []:
                log.write(f"  source: {note}")

    def _write_rows_table(self, log: RichLog, title: str, rows: list[dict], columns: list[str]) -> None:
        if not rows:
            log.write(Text(f"{title}: none", style="dim italic"))
            return
        table = Table(title=title, title_style="bold #22c55e")
        for column in columns:
            table.add_column(column.replace("_", " ").title())
        for row in rows[:20]:
            cells = []
            for column in columns:
                value = row.get(column)
                if column in _ACTION_COLUMN_KEYS:
                    cells.append(_coloured_action(value))
                elif column in _SEVERITY_COLUMN_KEYS:
                    cells.append(_coloured_severity(value))
                elif column in _READINESS_COLUMN_KEYS:
                    cells.append(_coloured_readiness(value))
                else:
                    cells.append(self._format_cell(value))
            table.add_row(*cells)
        log.write(table)
        if len(rows) > 20:
            log.write(Text(f"… plus {len(rows) - 20} more rows", style="dim"))

    def _flatten_drift(self, drift: list[dict]) -> list[dict]:
        rows = []
        for item in drift:
            was = item.get("was") or {}
            now = item.get("now") or {}
            rows.append(
                {
                    "ticker": item.get("ticker"),
                    "drift_type": item.get("drift_type"),
                    "was": f"{was.get('action', '')} {was.get('conviction', '')}".strip() if isinstance(was, dict) else "",
                    "now": f"{now.get('action', '')} {now.get('conviction', '')}".strip() if isinstance(now, dict) else "",
                }
            )
        return rows

    def _format_cell(self, value) -> str:
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value)[:120]
        return str(value)[:160]

    def _load_today_report(self, preferred: Path | None = None) -> None:
        path = preferred or latest_report()
        self.query_one("#today_path", Static).update(relative_to_root(path) if path else "No report found.")
        self._update_markdown("#today_markdown", read_text_file(path) if path else "")

    def _load_report_review(self) -> None:
        try:
            log = self.query_one("#report_review_log", RichLog)
        except Exception:
            return
        log.clear()
        view = report_review_view()
        if not view.get("ok"):
            log.write(Text(view.get("error") or "No report review available.", style="bold #f59e0b"))
            return
        log.write(
            Text(
                f"Status: {view.get('status_label')} | Session: {view.get('session_file')} | Report: {relative_to_root(view.get('report_path'))}",
                style="bold #22c55e",
            )
        )
        self._write_rows_table(log, "Review Gates", view.get("metric_rows") or [], ["metric", "status", "value", "next_action"])
        if view.get("top_reasons"):
            log.write(Text("Top reasons:", style="bold #f59e0b"))
            for reason in view.get("top_reasons") or []:
                log.write(f"- {reason}")
        self._write_rows_table(
            log,
            "Recommendation Readiness",
            view.get("recommendation_rows") or [],
            ["readiness", "ticker", "action", "size", "conviction", "warnings", "risk_controls", "decision"],
        )
        self._write_rows_table(log, "Changed Since Previous Report", view.get("change_rows") or [], ["ticker", "change", "before", "after"])
        self._write_rows_table(
            log,
            "Decision Feedback Rows",
            view.get("decision_rows") or [],
            ["ticker", "recommended_action", "size", "conviction", "user_decision", "id"],
        )

    def _load_history_report(self) -> None:
        value = self.query_one("#history_select", Select).value
        path = Path(value) if isinstance(value, str) and value and value != "__none__" else latest_report()
        self._update_markdown("#history_markdown", read_text_file(path) if path else "")

    def _update_markdown(self, selector: str, text: str) -> None:
        widget = self.query_one(selector, Markdown)
        widget.update(text or "_No report content found._")

    async def _load_backtest_async(self) -> None:
        self._show_backtest_placeholder()
        summary = await asyncio.to_thread(run_backtest_summary)
        log = self.query_one("#backtest_log", RichLog)
        log.clear()
        overall = summary.get("overall") or {}
        metrics = Table(title=f"Backtest — {summary.get('n_samples', 0)} samples")
        metrics.add_column("Metric")
        metrics.add_column("Value", justify="right")
        metrics.add_row("Average return", f"{overall.get('avg_return_pct', 0):+.2f}%")
        metrics.add_row("Hit rate", f"{overall.get('hit_rate', 0):.0%}")
        log.write(metrics)
        self._write_bucket_table(log, "By Action", summary.get("avg_return_by_action") or {})
        self._write_bucket_table(log, "By Conviction", summary.get("avg_return_by_conviction") or {})
        self._write_bucket_table(log, "By Ticker", summary.get("avg_return_by_ticker") or {})
        self._write_rows_table(
            log,
            "Recent Realized Examples",
            summary.get("recent_realized_examples") or [],
            ["ticker", "session_date", "action", "conviction", "expected_pct", "actual_pct", "hit"],
        )
        scorecard = await asyncio.to_thread(decision_scorecard_summary)
        overall = scorecard.get("overall") or {}
        decision_table = Table(title=f"Decision Journal — {scorecard.get('n_scored_windows', 0)} scored windows")
        decision_table.add_column("Metric")
        decision_table.add_column("Value", justify="right")
        decision_table.add_row("Model avg", f"{overall.get('model_avg_return_pct', 0):+.2f}%")
        decision_table.add_row("Your avg", f"{overall.get('user_avg_return_pct', 0):+.2f}%")
        decision_table.add_row("Discretion delta", f"{overall.get('avg_decision_delta_pct', 0):+.2f}%")
        log.write(decision_table)
        self._write_rows_table(
            log,
            "Worst User Overrides",
            scorecard.get("worst_user_overrides") or [],
            ["ticker", "session_date", "recommended_action", "user_decision", "horizon_days", "decision_delta_pct"],
        )

    def _show_backtest_placeholder(self) -> None:
        log = self.query_one("#backtest_log", RichLog)
        log.clear()
        log.write(Text("📈 Backtest", style="bold #22c55e"))
        log.write(Text("Press 'Refresh backtest' to evaluate past recommendations.", style="dim"))
        log.write(Text("This fetches live price data via yfinance and may take 20–30 seconds.", style="dim italic"))

    async def _check_updates_async(self, *, startup: bool) -> None:
        log = self.query_one("#update_log", RichLog)
        if not startup:
            log.clear()
            log.write("Checking GitHub Releases...")
        info = await asyncio.to_thread(check_update_available)
        self.latest_update_info = info
        self.query_one("#apply_update", Button).disabled = not info.available
        if info.error:
            log.write(f"Update check failed: {info.error}")
            return
        if info.available:
            message = (
                f"Version {info.latest_version} is available. Current version: {info.current_version}.\n"
                "Reports, logs, uploaded CSVs, config files, and API key files are kept in the app workspace.\n"
                "Open the Updates tab and press 'Update now' to apply it."
            )
            log.write(message)
            if startup:
                self.notify(f"tech_stock v{info.latest_version} is available.")
                self.call_later(self._prompt_startup_update, info)
            return
        if not startup:
            log.write(f"Already up to date: v{info.current_version}")
        else:
            log.write(f"Current version: v{current_app_version()}")

    def _prompt_startup_update(self, info) -> None:
        latest = info.latest_version or "unknown"
        self.push_screen(UpdatePrompt(latest, info.current_version), self._handle_startup_update_choice)

    def _handle_startup_update_choice(self, should_update: bool | None) -> None:
        if should_update:
            self.run_worker(self._apply_update_async(), exclusive=True)

    async def _apply_update_async(self) -> None:
        log = self.query_one("#update_log", RichLog)
        info = self.latest_update_info
        if not info or not info.available:
            await self._check_updates_async(startup=False)
            return
        log.write(f"Updating to version {info.latest_version}...")
        result = await asyncio.to_thread(apply_available_update, info, restart=True)
        log.write(result.message)
        log.write(f"Update log: {result.log_path}")
        if result.downloaded_path:
            log.write(f"Downloaded file: {result.downloaded_path}")
        if result.ok and result.restart_started:
            log.write("Exiting so the updater can replace and reopen the app.")
            await asyncio.sleep(1)
            self.exit()

    def _write_bucket_table(self, log: RichLog, title: str, bucket: dict) -> None:
        rows = []
        for label, stats in bucket.items():
            rows.append(
                {
                    "bucket": label,
                    "n": stats.get("n", 0),
                    "avg_return_pct": f"{stats.get('avg_return_pct', 0):+.2f}%",
                    "hit_rate": f"{stats.get('hit_rate', 0):.0%}",
                }
            )
        self._write_rows_table(log, title, rows, ["bucket", "n", "avg_return_pct", "hit_rate"])

    def _load_editor_text(self) -> None:
        label = self.query_one("#editor_file", Select).value or "Settings"
        editor = self.query_one("#editor_text", TextArea)
        editor.load_text(read_editable_json(label))
        self._validate_editor_text(prefix=f"Loaded {label}. ")

    def _validate_editor_text(self, prefix: str = "") -> bool:
        editor = self.query_one("#editor_text", TextArea)
        ok, message = validate_json_text(editor.text)
        status = self.query_one("#editor_status", Static)
        status.update(f"{prefix}{message}")
        self.query_one("#save_json", Button).disabled = not ok
        return ok

    def _save_editor_text(self) -> None:
        if not self._validate_editor_text():
            return
        label = self.query_one("#editor_file", Select).value or "Settings"
        editor = self.query_one("#editor_text", TextArea)
        try:
            saved = write_editable_json(label, editor.text)
        except Exception as exc:
            self.query_one("#editor_status", Static).update(f"Save failed: {exc}")
            return
        self.query_one("#editor_status", Static).update(f"Saved {relative_to_root(saved)}")


if __name__ == "__main__":
    TechStockTUI().run()
