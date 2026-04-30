from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, RichLog, Select, Static, TabbedContent, TabPane, TextArea

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
    write_editable_json,
)


class TechStockTUI(App):
    TITLE = "tech_stock"
    SUB_TITLE = "Portfolio report dashboard"
    BINDINGS = [("q", "quit", "Quit"), ("r", "refresh_reports", "Refresh")]

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

    #today_markdown, #history_markdown {
        height: 1fr;
        border: solid $primary;
        padding: 1;
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
        yield Header()
        with TabbedContent(initial="run"):
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
                yield Static("Holdings CSV path")
                yield Input(value=str(defaults["holdings"] or ""), id="holdings_path")
                yield Static("Activities CSV path")
                yield Input(value=str(defaults["activities"] or ""), id="activities_path")
                yield Button("Run report", id="run_report", variant="primary")
                yield Static("Ready.", id="status")
                yield RichLog(id="console", wrap=True, highlight=True)
            with TabPane("Today's Report", id="today"):
                yield Button("Refresh report", id="refresh_today")
                yield Static("", id="today_path")
                yield RichLog(id="today_markdown", wrap=True, highlight=True)
            with TabPane("History", id="history"):
                history_options = self._history_options()
                yield Button("Refresh history", id="refresh_history")
                yield Select(history_options, value=history_options[0][1], allow_blank=False, id="history_select")
                yield Button("Load selected report", id="load_history")
                yield RichLog(id="history_markdown", wrap=True, highlight=True)
            with TabPane("Backtest", id="backtest"):
                yield Button("Refresh backtest", id="refresh_backtest")
                yield RichLog(id="backtest_log", wrap=True, highlight=True)
            with TabPane("Portfolio Editor", id="editor"):
                yield Select([(label, label) for label in EDITABLE_JSON_FILES], value="Settings", id="editor_file")
                yield Button("Load JSON", id="load_json")
                yield Button("Save JSON", id="save_json", variant="success")
                yield Static("", id="editor_status")
                yield TextArea("", language="json", id="editor_text")
        yield Footer()

    def on_mount(self) -> None:
        self._load_today_report()
        self._load_history_report()
        self._load_backtest()
        self._load_editor_text()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "run_report":
            await self._run_report()
        elif button_id == "refresh_today":
            self._load_today_report()
        elif button_id == "refresh_history":
            self._refresh_history_select()
            self._load_history_report()
        elif button_id == "load_history":
            self._load_history_report()
        elif button_id == "refresh_backtest":
            self._load_backtest()
        elif button_id == "load_json":
            self._load_editor_text()
        elif button_id == "save_json":
            self._save_editor_text()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "editor_file":
            self._load_editor_text()

    def action_refresh_reports(self) -> None:
        self._load_today_report()
        self._refresh_history_select()
        self._load_history_report()

    async def _run_report(self) -> None:
        status = self.query_one("#status", Static)
        console = self.query_one("#console", RichLog)
        console.clear()
        status.update("Running report. This can take several minutes for a full two-pass Claude run.")

        result = await asyncio.to_thread(
            run_report_from_ui,
            session_type=self.query_one("#session", Select).value,
            holdings_csv=self.query_one("#holdings_path", Input).value,
            activities_csv=self.query_one("#activities_path", Input).value,
            budget_usd=self._float_input("#budget_usd"),
            budget_cad=self._float_input("#budget_cad"),
            model_choice=self.query_one("#model", Select).value,
        )

        if result.console:
            console.write(result.console)
        if not result.ok:
            status.update(f"Failed: {result.error}")
            return

        status.update(
            "Done. "
            f"Report: {relative_to_root(result.report_path)} | "
            f"CSV: {relative_to_root(result.csv_path)}"
        )
        self._load_today_report(result.report_path)
        self._refresh_history_select()

    def _float_input(self, selector: str) -> float:
        value = self.query_one(selector, Input).value.strip()
        if not value:
            return 0.0
        try:
            return max(float(value), 0.0)
        except ValueError:
            return 0.0

    def _history_options(self) -> list[tuple[str, str]]:
        reports = list_reports(limit=50)
        if not reports:
            return [("No reports found", "__none__")]
        return [(relative_to_root(path), str(path)) for path in reports]

    def _refresh_history_select(self) -> None:
        select = self.query_one("#history_select", Select)
        options = self._history_options()
        select.set_options(options)
        select.value = options[0][1]

    def _load_today_report(self, preferred: Path | None = None) -> None:
        path = preferred or latest_report()
        self.query_one("#today_path", Static).update(relative_to_root(path) if path else "No report found.")
        self._replace_log_text("#today_markdown", read_text_file(path) if path else "")

    def _load_history_report(self) -> None:
        value = self.query_one("#history_select", Select).value
        path = Path(value) if isinstance(value, str) and value and value != "__none__" else latest_report()
        self._replace_log_text("#history_markdown", read_text_file(path) if path else "")

    def _replace_log_text(self, selector: str, text: str) -> None:
        log = self.query_one(selector, RichLog)
        log.clear()
        if text:
            log.write(text)

    def _load_backtest(self) -> None:
        log = self.query_one("#backtest_log", RichLog)
        log.clear()
        summary = run_backtest_summary()
        overall = summary.get("overall") or {}
        log.write(f"Samples: {summary.get('n_samples', 0)}")
        log.write(f"Average return: {overall.get('avg_return_pct', 0):+.2f}%")
        log.write(f"Hit rate: {overall.get('hit_rate', 0):.0%}")
        log.write(summary)

    def _load_editor_text(self) -> None:
        label = self.query_one("#editor_file", Select).value or "Settings"
        editor = self.query_one("#editor_text", TextArea)
        editor.load_text(read_editable_json(label))
        self.query_one("#editor_status", Static).update(f"Loaded {label}.")

    def _save_editor_text(self) -> None:
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
