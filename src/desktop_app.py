"""
Embedded desktop UI for tech_stock.

This is a native Tkinter application. It deliberately reuses src.ui_support
instead of duplicating portfolio/report logic, so the CLI, Streamlit, Textual,
and desktop app all run the same report pipeline.
"""

from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ui_support import (
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
    run_report_from_ui,
    validate_json_text,
    write_editable_json,
)


class DesktopApp(tk.Tk):
    """Native desktop dashboard for users who do not want a browser UI."""

    def __init__(self) -> None:
        super().__init__()
        self.title("tech_stock Desktop")
        self.geometry("1180x820")
        self.minsize(980, 680)

        self.bg = "#12121a"
        self.panel = "#1e1e2e"
        self.text = "#e5e7eb"
        self.muted = "#94a3b8"
        self.accent = "#22c55e"
        self.danger = "#ef4444"
        self.configure(bg=self.bg)

        self.progress_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.latest_report_path: Path | None = latest_report()

        self._configure_style()
        self._build_header()
        self._build_tabs()
        self.after(100, self._drain_progress_queue)
        self.refresh_dashboard()
        self.refresh_history()
        self.load_report(self.latest_report_path, select_tab=False)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=self.bg)
        style.configure("Panel.TFrame", background=self.panel)
        style.configure("TLabel", background=self.bg, foreground=self.text)
        style.configure("Muted.TLabel", background=self.bg, foreground=self.muted)
        style.configure("Title.TLabel", background=self.bg, foreground=self.accent, font=("Helvetica", 28, "bold"))
        style.configure("TButton", padding=(12, 7))
        style.configure("Accent.TButton", padding=(14, 8))
        style.configure("TNotebook", background=self.bg, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(16, 8))
        style.configure("Treeview", rowheight=25)

    def _build_header(self) -> None:
        header = ttk.Frame(self)
        header.pack(fill="x", padx=22, pady=(18, 8))
        ttk.Label(header, text="tech_stock", style="Title.TLabel").pack(side="left")
        ttk.Label(
            header,
            text="Embedded desktop dashboard - no browser required",
            style="Muted.TLabel",
        ).pack(side="left", padx=(18, 0), pady=(12, 0))

    def _build_tabs(self) -> None:
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=18, pady=(0, 18))

        self.dashboard_tab = ttk.Frame(self.tabs)
        self.run_tab = ttk.Frame(self.tabs)
        self.report_tab = ttk.Frame(self.tabs)
        self.history_tab = ttk.Frame(self.tabs)
        self.editor_tab = ttk.Frame(self.tabs)
        self.health_tab = ttk.Frame(self.tabs)

        self.tabs.add(self.dashboard_tab, text="Dashboard")
        self.tabs.add(self.run_tab, text="Run Report")
        self.tabs.add(self.report_tab, text="Report Viewer")
        self.tabs.add(self.history_tab, text="History")
        self.tabs.add(self.editor_tab, text="Config Editor")
        self.tabs.add(self.health_tab, text="API Checks")

        self._build_dashboard_tab()
        self._build_run_tab()
        self._build_report_tab()
        self._build_history_tab()
        self._build_editor_tab()
        self._build_health_tab()

    def _panel(self, parent: tk.Widget, title: str | None = None) -> ttk.Frame:
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=14)
        if title:
            ttk.Label(frame, text=title, font=("Helvetica", 14, "bold"), background=self.panel, foreground=self.text).pack(
                anchor="w", pady=(0, 8)
            )
        return frame

    def _build_dashboard_tab(self) -> None:
        top = ttk.Frame(self.dashboard_tab)
        top.pack(fill="x", padx=16, pady=16)
        ttk.Button(top, text="Refresh Dashboard", command=self.refresh_dashboard).pack(side="left")
        self.dashboard_caption = ttk.Label(top, text="", style="Muted.TLabel")
        self.dashboard_caption.pack(side="left", padx=12)

        metrics = ttk.Frame(self.dashboard_tab)
        metrics.pack(fill="x", padx=16)
        self.metric_vars: dict[str, tk.StringVar] = {}
        for label in ["SPY Beta", "Annual Vol", "Max DD Est.", "Top-3 Conc.", "Claude Cost"]:
            box = self._panel(metrics)
            box.pack(side="left", fill="x", expand=True, padx=(0, 10))
            ttk.Label(box, text=label, background=self.panel, foreground=self.muted).pack(anchor="w")
            var = tk.StringVar(value="N/A")
            self.metric_vars[label] = var
            ttk.Label(box, textvariable=var, background=self.panel, foreground=self.text, font=("Helvetica", 18, "bold")).pack(
                anchor="w", pady=(4, 0)
            )

        body = ttk.PanedWindow(self.dashboard_tab, orient="horizontal")
        body.pack(fill="both", expand=True, padx=16, pady=16)
        left = self._panel(body, "Priority Actions")
        right = self._panel(body, "Quality Warnings")
        body.add(left, weight=1)
        body.add(right, weight=1)

        self.priority_tree = self._make_tree(left, ["ticker", "action", "reason"], [90, 120, 430])
        self.warning_tree = self._make_tree(right, ["severity", "code", "ticker", "message"], [90, 170, 90, 430])

    def _build_run_tab(self) -> None:
        defaults = find_default_csvs()
        settings = default_run_settings()

        form = self._panel(self.run_tab, "Run Settings")
        form.pack(fill="x", padx=16, pady=16)

        self.session_var = tk.StringVar(value="morning")
        self.model_var = tk.StringVar(value=settings.get("model_choice", "sonnet"))
        self.budget_usd_var = tk.StringVar(value=str(settings.get("budget_usd", 0)))
        self.budget_cad_var = tk.StringVar(value=str(settings.get("budget_cad", 0)))
        self.holdings_var = tk.StringVar(value=str(defaults.get("holdings") or ""))
        self.activities_var = tk.StringVar(value=str(defaults.get("activities") or ""))

        grid = ttk.Frame(form, style="Panel.TFrame")
        grid.pack(fill="x")
        self._field_combo(grid, "Session", self.session_var, ["morning", "afternoon"], 0)
        self._field_combo(grid, "Model", self.model_var, ["sonnet", "opus"], 1)
        self._field_entry(grid, "USD budget", self.budget_usd_var, 2)
        self._field_entry(grid, "CAD budget", self.budget_cad_var, 3)

        files = ttk.Frame(form, style="Panel.TFrame")
        files.pack(fill="x", pady=(14, 0))
        self._path_row(files, "Holdings CSV", self.holdings_var, 0)
        self._path_row(files, "Activities CSV", self.activities_var, 1)

        actions = ttk.Frame(form, style="Panel.TFrame")
        actions.pack(fill="x", pady=(12, 0))
        self.run_button = ttk.Button(actions, text="Run Report", style="Accent.TButton", command=self.start_report_run)
        self.run_button.pack(side="left")
        ttk.Button(actions, text="Preview Holdings", command=self.preview_holdings).pack(side="left", padx=8)
        self.run_status = tk.StringVar(value="Ready.")
        ttk.Label(actions, textvariable=self.run_status, background=self.panel, foreground=self.muted).pack(side="left", padx=12)

        self.console_text = ScrolledText(self.run_tab, height=22, wrap="word", bg="#0f172a", fg="#e5e7eb", insertbackground="#e5e7eb")
        self.console_text.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    def _build_report_tab(self) -> None:
        toolbar = ttk.Frame(self.report_tab)
        toolbar.pack(fill="x", padx=16, pady=16)
        ttk.Button(toolbar, text="Load Latest", command=lambda: self.load_report(latest_report(), select_tab=True)).pack(side="left")
        ttk.Button(toolbar, text="Refresh", command=lambda: self.load_report(self.latest_report_path, select_tab=True)).pack(side="left", padx=8)
        self.report_path_label = ttk.Label(toolbar, text="", style="Muted.TLabel")
        self.report_path_label.pack(side="left", padx=12)

        self.report_text = ScrolledText(self.report_tab, wrap="word", bg="#0b1020", fg="#e5e7eb", insertbackground="#e5e7eb")
        self.report_text.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    def _build_history_tab(self) -> None:
        body = ttk.PanedWindow(self.history_tab, orient="horizontal")
        body.pack(fill="both", expand=True, padx=16, pady=16)

        left = self._panel(body, "Reports")
        right = self._panel(body, "Selected Report")
        body.add(left, weight=1)
        body.add(right, weight=3)

        ttk.Button(left, text="Refresh", command=self.refresh_history).pack(anchor="w", pady=(0, 8))
        self.history_list = tk.Listbox(left, bg="#0f172a", fg="#e5e7eb", activestyle="dotbox")
        self.history_list.pack(fill="both", expand=True)
        self.history_list.bind("<<ListboxSelect>>", self._history_selected)
        self.history_paths: list[Path] = []

        self.history_text = ScrolledText(right, wrap="word", bg="#0b1020", fg="#e5e7eb", insertbackground="#e5e7eb")
        self.history_text.pack(fill="both", expand=True)

    def _build_editor_tab(self) -> None:
        toolbar = ttk.Frame(self.editor_tab)
        toolbar.pack(fill="x", padx=16, pady=16)
        self.editor_file_var = tk.StringVar(value=next(iter(EDITABLE_JSON_FILES)))
        ttk.Label(toolbar, text="File").pack(side="left")
        selector = ttk.Combobox(toolbar, textvariable=self.editor_file_var, values=list(EDITABLE_JSON_FILES), state="readonly", width=24)
        selector.pack(side="left", padx=8)
        selector.bind("<<ComboboxSelected>>", lambda _event: self.load_editor_file())
        ttk.Button(toolbar, text="Validate", command=self.validate_editor_json).pack(side="left", padx=4)
        ttk.Button(toolbar, text="Save", command=self.save_editor_file).pack(side="left", padx=4)
        self.editor_status = tk.StringVar(value="")
        ttk.Label(toolbar, textvariable=self.editor_status, style="Muted.TLabel").pack(side="left", padx=12)

        self.editor_text = ScrolledText(self.editor_tab, wrap="none", bg="#0b1020", fg="#e5e7eb", insertbackground="#e5e7eb")
        self.editor_text.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.load_editor_file()

    def _build_health_tab(self) -> None:
        top = ttk.Frame(self.health_tab)
        top.pack(fill="x", padx=16, pady=16)
        ttk.Button(top, text="Check APIs", command=self.start_connectivity_check).pack(side="left")
        self.health_status = tk.StringVar(value="Ready.")
        ttk.Label(top, textvariable=self.health_status, style="Muted.TLabel").pack(side="left", padx=12)
        self.health_tree = self._make_tree(self.health_tab, ["source", "ok", "latency_ms", "detail"], [160, 80, 110, 700])
        self.health_tree.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    def _field_combo(self, parent: ttk.Frame, label: str, var: tk.StringVar, values: list[str], col: int) -> None:
        ttk.Label(parent, text=label, background=self.panel, foreground=self.muted).grid(row=0, column=col, sticky="w", padx=(0, 12))
        ttk.Combobox(parent, textvariable=var, values=values, state="readonly", width=16).grid(row=1, column=col, sticky="ew", padx=(0, 12))
        parent.columnconfigure(col, weight=1)

    def _field_entry(self, parent: ttk.Frame, label: str, var: tk.StringVar, col: int) -> None:
        ttk.Label(parent, text=label, background=self.panel, foreground=self.muted).grid(row=0, column=col, sticky="w", padx=(0, 12))
        ttk.Entry(parent, textvariable=var, width=16).grid(row=1, column=col, sticky="ew", padx=(0, 12))
        parent.columnconfigure(col, weight=1)

    def _path_row(self, parent: ttk.Frame, label: str, var: tk.StringVar, row: int) -> None:
        ttk.Label(parent, text=label, background=self.panel, foreground=self.muted, width=14).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", padx=8, pady=3)
        ttk.Button(parent, text="Browse", command=lambda: self.browse_csv(var)).grid(row=row, column=2, pady=3)
        parent.columnconfigure(1, weight=1)

    def _make_tree(self, parent: tk.Widget, columns: list[str], widths: list[int]) -> ttk.Treeview:
        tree = ttk.Treeview(parent, columns=columns, show="headings")
        for column, width in zip(columns, widths):
            tree.heading(column, text=column.replace("_", " ").title())
            tree.column(column, width=width, anchor="w")
        tree.pack(fill="both", expand=True)
        return tree

    def browse_csv(self, var: tk.StringVar) -> None:
        path = filedialog.askopenfilename(
            title="Choose CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            var.set(path)

    def preview_holdings(self) -> None:
        path = self.holdings_var.get().strip()
        if not path:
            messagebox.showwarning("No holdings CSV", "Choose a holdings CSV first.")
            return
        preview = preview_holdings_csv(path)
        if not preview.get("ok"):
            messagebox.showerror("Preview failed", preview.get("error", "Could not preview holdings."))
            return
        rows = preview.get("rows", [])
        sample = "\n".join(
            f"{row.get('ticker')}: {row.get('quantity')} @ {row.get('market_price')} {row.get('currency')}"
            for row in rows[:12]
        )
        messagebox.showinfo(
            "Holdings preview",
            f"{preview.get('position_count')} positions\n{preview.get('exported_at', '')}\n\n{sample}",
        )

    def start_report_run(self) -> None:
        try:
            budget_usd = float(self.budget_usd_var.get() or 0)
            budget_cad = float(self.budget_cad_var.get() or 0)
        except ValueError:
            messagebox.showerror("Invalid budget", "Budget fields must be numeric.")
            return

        self.run_button.configure(state="disabled")
        self.console_text.delete("1.0", "end")
        self.run_status.set("Running report...")
        self.tabs.select(self.run_tab)

        holdings = self.holdings_var.get().strip() or None
        activities = self.activities_var.get().strip() or None

        def worker() -> None:
            result = run_report_from_ui(
                session_type=self.session_var.get(),
                holdings_csv=holdings,
                activities_csv=activities,
                budget_usd=budget_usd,
                budget_cad=budget_cad,
                model_choice=self.model_var.get(),
                on_progress=lambda line: self.progress_queue.put(("line", line)),
            )
            self.progress_queue.put(("done", result))

        threading.Thread(target=worker, daemon=True).start()

    def _drain_progress_queue(self) -> None:
        try:
            while True:
                kind, payload = self.progress_queue.get_nowait()
                if kind == "line":
                    self.console_text.insert("end", str(payload) + "\n")
                    self.console_text.see("end")
                elif kind == "done":
                    self._report_run_done(payload)
                elif kind == "health_done":
                    self._connectivity_done(payload)
        except queue.Empty:
            pass
        self.after(100, self._drain_progress_queue)

    def _report_run_done(self, result: Any) -> None:
        self.run_button.configure(state="normal")
        if not result.ok:
            self.run_status.set("Report failed.")
            if result.console:
                self.console_text.insert("end", "\n" + result.console)
            messagebox.showerror("Report failed", result.error or "Unknown error.")
            return
        self.run_status.set("Report completed.")
        self.latest_report_path = result.report_path
        self.load_report(result.report_path, select_tab=True)
        self.refresh_dashboard()
        self.refresh_history()
        messagebox.showinfo(
            "Report completed",
            "Report generated successfully.\n\n"
            f"Markdown: {relative_to_root(result.report_path)}\n"
            f"CSV: {relative_to_root(result.csv_path)}\n"
            f"JSON: {relative_to_root(result.log_path)}",
        )

    def refresh_dashboard(self) -> None:
        summary = latest_log_summary()
        if not summary:
            self.dashboard_caption.configure(text="No recommendation JSON logs found yet.")
            return
        self.dashboard_caption.configure(text=str(summary.get("session_file", "")))
        risk = summary.get("risk_dashboard") or {}
        beta = risk.get("beta") or {}
        usage = summary.get("usage") or {}
        self.metric_vars["SPY Beta"].set(str(beta.get("SPY", "N/A")))
        self.metric_vars["Annual Vol"].set(f"{risk.get('annualized_volatility_pct', 0):.1f}%")
        self.metric_vars["Max DD Est."].set(f"{risk.get('max_drawdown_estimate_pct', 0):+.1f}%")
        self.metric_vars["Top-3 Conc."].set(f"{risk.get('top3_concentration_pct', 0):.1f}%")
        self.metric_vars["Claude Cost"].set(f"${usage.get('cost_usd', 0):.4f}")
        self._replace_tree_rows(
            self.priority_tree,
            [
                [row.get("ticker", ""), row.get("action", ""), row.get("reason", row.get("message", ""))]
                for row in summary.get("priority_actions", [])
            ],
        )
        self._replace_tree_rows(
            self.warning_tree,
            [
                [row.get("severity", ""), row.get("code", ""), row.get("ticker", ""), row.get("message", "")]
                for row in summary.get("quality_warnings", [])
            ],
        )

    def _replace_tree_rows(self, tree: ttk.Treeview, rows: list[list[Any]]) -> None:
        for item in tree.get_children():
            tree.delete(item)
        for row in rows:
            tree.insert("", "end", values=row)

    def load_report(self, path: Path | None, *, select_tab: bool = False) -> None:
        self.latest_report_path = path
        text = read_text_file(path)
        self.report_text.delete("1.0", "end")
        if not path or not text:
            self.report_path_label.configure(text="No report selected.")
            self.report_text.insert("1.0", "No report found yet.")
            if select_tab:
                self.tabs.select(self.report_tab)
            return
        self.report_path_label.configure(text=relative_to_root(path))
        self.report_text.insert("1.0", text)
        if select_tab:
            self.tabs.select(self.report_tab)

    def refresh_history(self) -> None:
        self.history_paths = list_reports(limit=100)
        self.history_list.delete(0, "end")
        for path in self.history_paths:
            self.history_list.insert("end", f"{path.name}  -  {relative_to_root(path.parent)}")

    def _history_selected(self, _event: object) -> None:
        selection = self.history_list.curselection()
        if not selection:
            return
        path = self.history_paths[selection[0]]
        self.history_text.delete("1.0", "end")
        self.history_text.insert("1.0", read_text_file(path) or "Could not read report.")

    def load_editor_file(self) -> None:
        label = self.editor_file_var.get()
        try:
            content = read_editable_json(label)
        except Exception as exc:
            content = ""
            self.editor_status.set(str(exc))
        self.editor_text.delete("1.0", "end")
        self.editor_text.insert("1.0", content)
        self.editor_status.set(relative_to_root(EDITABLE_JSON_FILES[label]))

    def validate_editor_json(self) -> bool:
        ok, message = validate_json_text(self.editor_text.get("1.0", "end"))
        self.editor_status.set(message)
        if not ok:
            messagebox.showerror("Invalid JSON", message)
        return ok

    def save_editor_file(self) -> None:
        if not self.validate_editor_json():
            return
        try:
            path = write_editable_json(self.editor_file_var.get(), self.editor_text.get("1.0", "end"))
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))
            return
        self.editor_status.set(f"Saved {relative_to_root(path)}")

    def start_connectivity_check(self) -> None:
        self.health_status.set("Checking APIs...")
        self._replace_tree_rows(self.health_tree, [])

        def worker() -> None:
            self.progress_queue.put(("health_done", check_connectivity()))

        threading.Thread(target=worker, daemon=True).start()

    def _connectivity_done(self, rows: list[dict[str, Any]]) -> None:
        self.health_status.set("Connectivity check complete.")
        self._replace_tree_rows(
            self.health_tree,
            [[row.get("source"), row.get("ok"), row.get("latency_ms"), row.get("detail")] for row in rows],
        )


def main() -> None:
    app = DesktopApp()
    app.mainloop()


if __name__ == "__main__":
    main()
