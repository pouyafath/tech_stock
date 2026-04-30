from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

from rich.table import Table
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, RichLog, Select, Static, TabbedContent, TabPane, TextArea

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ui_support import (  # noqa: E402
    EDITABLE_JSON_FILES,
    check_connectivity,
    default_run_settings,
    discover_csv_files,
    find_default_csvs,
    latest_log_summary,
    latest_report,
    list_reports,
    read_editable_json,
    read_text_file,
    relative_to_root,
    run_backtest_summary,
    run_report_from_ui,
    validate_json_text,
    write_editable_json,
)


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


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

    #dashboard_log, #connectivity_log, #today_markdown, #history_markdown, #backtest_log {
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
                yield Button("Run report", id="run_report", variant="primary")
                yield Static("Ready.", id="status")
                yield RichLog(id="console", wrap=True, highlight=True)
            with TabPane("Today's Report", id="today"):
                yield Button("Refresh report", id="refresh_today")
                yield Static("", id="today_path")
                yield RichLog(id="today_markdown", wrap=True, highlight=True)
            with TabPane("History", id="history"):
                yield Button("Refresh history", id="refresh_history")
                yield Select(history_options, value=history_options[0][1], allow_blank=False, id="history_select")
                yield Button("Load selected report", id="load_history", disabled=history_options[0][1] == "__none__")
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
        self._load_dashboard()
        self._load_today_report()
        self._load_history_report()
        self._load_backtest()
        self._load_editor_text()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "run_report":
            await self._run_report()
        elif button_id == "refresh_dashboard":
            self._load_dashboard()
        elif button_id == "check_connectivity":
            await self._check_connectivity()
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
        elif active == "backtest":
            self._load_backtest()
        elif active == "editor":
            self._load_editor_text()

    def action_run_report(self) -> None:
        self.run_worker(self._run_report(), exclusive=True)

    def action_save_editor(self) -> None:
        self._save_editor_text()

    async def _run_report(self) -> None:
        status = self.query_one("#status", Static)
        console = self.query_one("#console", RichLog)
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

        status.update(
            "Done. "
            f"Report: {relative_to_root(result.report_path)} | "
            f"CSV: {relative_to_root(result.csv_path)}"
        )
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
        reports = list_reports(limit=50)
        if not reports:
            return [("No reports found", "__none__")]
        return [(relative_to_root(path), str(path)) for path in reports]

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
            log.write("No recommendation JSON logs found yet.")
            return
        if summary.get("error"):
            log.write(f"Failed to read latest log: {summary['error']}")
            return

        log.write(f"Latest log: {summary.get('session_file', '')}")
        risk = summary.get("risk_dashboard") or {}
        beta = risk.get("beta") or {}
        usage = summary.get("usage") or {}
        metrics = Table(title="Dashboard Metrics")
        metrics.add_column("Metric")
        metrics.add_column("Value", justify="right")
        metrics.add_row("Beta SPY", str(beta.get("SPY", "N/A")))
        metrics.add_row("Annualized volatility", f"{risk.get('annualized_volatility_pct', 0):.1f}%")
        metrics.add_row("Max drawdown estimate", f"{risk.get('max_drawdown_estimate_pct', 0):+.1f}%")
        metrics.add_row("Top-3 concentration", f"{risk.get('top3_concentration_pct', 0):.1f}%")
        metrics.add_row("Claude cost", f"${usage.get('cost_usd', 0):.4f}")
        metrics.add_row("Tokens", f"{usage.get('total_tokens', 0):,}")
        log.write(metrics)

        self._write_rows_table(log, "Priority Actions", summary.get("priority_actions") or [], ["order", "ticker", "action", "rationale"])
        self._write_rows_table(log, "Quality Warnings", summary.get("quality_warnings") or [], ["severity", "code", "ticker", "message", "action_required"])
        self._write_rows_table(log, "Hedge Suggestions", summary.get("hedge_suggestions") or [], ["type", "instrument", "action", "risk_note"])
        self._write_rows_table(log, "Drift Vs Previous", self._flatten_drift(summary.get("drift") or []), ["ticker", "drift_type", "was", "now"])

    async def _check_connectivity(self) -> None:
        log = self.query_one("#connectivity_log", RichLog)
        log.clear()
        log.write("Checking connectivity...")
        checks = await asyncio.to_thread(check_connectivity)
        log.clear()
        self._write_rows_table(log, "Connectivity", checks, ["source", "ok", "latency_ms", "detail"])

    def _write_rows_table(self, log: RichLog, title: str, rows: list[dict], columns: list[str]) -> None:
        if not rows:
            log.write(f"{title}: none")
            return
        table = Table(title=title)
        for column in columns:
            table.add_column(column.replace("_", " ").title())
        for row in rows[:20]:
            table.add_row(*[self._format_cell(row.get(column)) for column in columns])
        log.write(table)

    def _flatten_drift(self, drift: list[dict]) -> list[dict]:
        rows = []
        for item in drift:
            was = item.get("was") or {}
            now = item.get("now") or {}
            rows.append({
                "ticker": item.get("ticker"),
                "drift_type": item.get("drift_type"),
                "was": f"{was.get('action', '')} {was.get('conviction', '')}".strip() if isinstance(was, dict) else "",
                "now": f"{now.get('action', '')} {now.get('conviction', '')}".strip() if isinstance(now, dict) else "",
            })
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

    def _write_bucket_table(self, log: RichLog, title: str, bucket: dict) -> None:
        rows = []
        for label, stats in bucket.items():
            rows.append({
                "bucket": label,
                "n": stats.get("n", 0),
                "avg_return_pct": f"{stats.get('avg_return_pct', 0):+.2f}%",
                "hit_rate": f"{stats.get('hit_rate', 0):.0%}",
            })
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
