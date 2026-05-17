"""
Embedded desktop UI for tech_stock.

This is a native Tkinter application. It deliberately reuses src.ui_support
instead of duplicating portfolio/report logic, so the CLI, Streamlit, Textual,
and desktop app all run the same report pipeline.
"""

from __future__ import annotations

import queue
import os
import re
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont
from tkinter.scrolledtext import ScrolledText
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ui_support import (
    EDITABLE_JSON_FILES,
    api_key_locations,
    app_data_locations,
    apply_available_update,
    check_connectivity,
    check_update_available,
    current_app_version,
    default_run_settings,
    find_default_csvs,
    latest_log_summary,
    latest_report,
    list_reports,
    preview_holdings_csv,
    read_editable_json,
    read_text_file,
    relative_to_root,
    report_locations,
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
        self.warning = "#f59e0b"
        self.good = "#22c55e"
        self.card = "#171827"
        self.table_bg = "#0f172a"
        self.configure(bg=self.bg)

        self.progress_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.latest_report_path: Path | None = latest_report()
        self.latest_update_info: Any = None

        self._configure_style()
        self._build_header()
        self._build_tabs()
        self.after(100, self._drain_progress_queue)
        self.refresh_dashboard()
        self.refresh_history()
        self.load_report(self.latest_report_path, select_tab=False)
        self.after(350, self.confirm_detected_csv_paths)
        if os.environ.get("TECH_STOCK_SKIP_UPDATE_CHECK") != "1":
            self.after(1200, lambda: self.start_update_check(startup=True))

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
        style.configure(
            "Treeview",
            rowheight=27,
            background="#0f172a",
            fieldbackground="#0f172a",
            foreground=self.text,
            borderwidth=0,
        )
        style.configure("Treeview.Heading", background="#242436", foreground=self.text, font=("Helvetica", 11, "bold"))

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
        self.update_tab = ttk.Frame(self.tabs)

        self.tabs.add(self.dashboard_tab, text="Dashboard")
        self.tabs.add(self.run_tab, text="Run Report")
        self.tabs.add(self.report_tab, text="Report Viewer")
        self.tabs.add(self.history_tab, text="History")
        self.tabs.add(self.editor_tab, text="Config Editor")
        self.tabs.add(self.health_tab, text="API Checks")
        self.tabs.add(self.update_tab, text="Updates")

        self._build_dashboard_tab()
        self._build_run_tab()
        self._build_report_tab()
        self._build_history_tab()
        self._build_editor_tab()
        self._build_health_tab()
        self._build_update_tab()

    def _panel(self, parent: tk.Widget, title: str | None = None) -> ttk.Frame:
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=14)
        if title:
            ttk.Label(frame, text=title, font=("Helvetica", 14, "bold"), background=self.panel, foreground=self.text).pack(
                anchor="w", pady=(0, 8)
            )
        return frame

    def _dashboard_panel(self, parent: tk.Widget, title: str) -> tuple[tk.Frame, tk.Frame]:
        panel = tk.Frame(parent, bg=self.panel, highlightthickness=1, highlightbackground="#2b2d42")
        header = tk.Frame(panel, bg=self.panel)
        header.pack(fill="x", padx=14, pady=(12, 6))
        tk.Label(header, text=title, bg=self.panel, fg=self.text, font=("Helvetica", 14, "bold")).pack(anchor="w")
        body = tk.Frame(panel, bg=self.panel)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        return panel, body

    def _scrollable_frame(self, parent: tk.Widget) -> ttk.Frame:
        outer = ttk.Frame(parent)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, bg=self.bg, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        content = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        content.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
        return content

    def _build_dashboard_tab(self) -> None:
        content = self._scrollable_frame(self.dashboard_tab)

        top = tk.Frame(content, bg=self.bg)
        top.pack(fill="x", padx=16, pady=(14, 10))
        ttk.Button(top, text="Refresh Dashboard", command=self.refresh_dashboard).pack(side="left")
        self.dashboard_caption = ttk.Label(top, text="", style="Muted.TLabel")
        self.dashboard_caption.pack(side="left", padx=12)

        signal = tk.Frame(content, bg="#171827", highlightthickness=1, highlightbackground="#303044")
        signal.pack(fill="x", padx=16, pady=(0, 12))
        self.signal_accent = tk.Frame(signal, bg=self.accent, width=5)
        self.signal_accent.pack(side="left", fill="y")
        signal_body = tk.Frame(signal, bg="#171827", padx=16, pady=14)
        signal_body.pack(side="left", fill="both", expand=True)
        self.signal_kicker = tk.StringVar(value="ACTION PULSE")
        self.signal_title = tk.StringVar(value="No report loaded")
        self.signal_body = tk.StringVar(value="Run a report to populate action signals.")
        self.signal_meta = tk.StringVar(value="")
        tk.Label(
            signal_body,
            textvariable=self.signal_kicker,
            bg="#171827",
            fg=self.muted,
            font=("Helvetica", 10, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            signal_body,
            textvariable=self.signal_title,
            background="#171827",
            foreground=self.accent,
            font=("Helvetica", 20, "bold"),
        ).pack(anchor="w", pady=(3, 0))
        ttk.Label(
            signal_body,
            textvariable=self.signal_body,
            background="#171827",
            foreground=self.text,
            wraplength=1040,
            justify="left",
        ).pack(anchor="w", fill="x", pady=(8, 0))
        ttk.Label(
            signal_body,
            textvariable=self.signal_meta,
            background="#171827",
            foreground=self.muted,
        ).pack(anchor="w", pady=(10, 0))

        metrics = tk.Frame(content, bg=self.bg)
        metrics.pack(fill="x", padx=16)
        self.metric_vars: dict[str, tk.StringVar] = {}
        self.metric_hint_vars: dict[str, tk.StringVar] = {}
        metric_labels = ["Portfolio", "P&L", "SPY Beta", "Annual Vol", "Top-3 Conc.", "Warnings", "Claude Cost"]
        for col in range(4):
            metrics.columnconfigure(col, weight=1, uniform="metrics")
        for index, label in enumerate(metric_labels):
            row = index // 4
            col = index % 4
            box = tk.Frame(metrics, bg=self.card, highlightthickness=1, highlightbackground="#2b2d42", padx=14, pady=12)
            box.grid(row=row, column=col, sticky="ew", padx=(0 if col == 0 else 8, 0), pady=(0, 8))
            tk.Label(box, text=label.upper(), bg=self.card, fg=self.muted, font=("Helvetica", 10, "bold")).pack(anchor="w")
            var = tk.StringVar(value="N/A")
            hint = tk.StringVar(value="")
            self.metric_vars[label] = var
            self.metric_hint_vars[label] = hint
            tk.Label(box, textvariable=var, bg=self.card, fg=self.text, font=("Helvetica", 20, "bold")).pack(
                anchor="w", pady=(4, 0)
            )
            tk.Label(box, textvariable=hint, bg=self.card, fg=self.muted, font=("Helvetica", 10)).pack(anchor="w", pady=(4, 0))

        action_panel, self.action_cards = self._dashboard_panel(content, "Action Queue")
        action_panel.pack(fill="x", padx=16, pady=(16, 10))

        middle = ttk.Frame(content)
        middle.pack(fill="both", expand=True, padx=16, pady=(0, 10))
        left, self.warning_cards = self._dashboard_panel(middle, "Quality Gates")
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        right, risk_body = self._dashboard_panel(middle, "Risk & Exposure")
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.risk_text = self._readonly_text(risk_body, height=11)

        lower = ttk.Frame(content)
        lower.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        trailing_panel, self.stop_cards = self._dashboard_panel(lower, "Stops & Breaches")
        trailing_panel.pack(side="left", fill="both", expand=True, padx=(0, 8))
        drift_panel, signal_text_body = self._dashboard_panel(lower, "Drift, Hedges & Market Signals")
        drift_panel.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.signal_text = self._readonly_text(signal_text_body, height=11)

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

        locations = self._panel(self.run_tab, "File Locations")
        locations.pack(fill="x", padx=16, pady=(0, 16))
        self.locations_text = tk.Text(locations, height=6, wrap="word", bg="#0f172a", fg="#e5e7eb")
        self.locations_text.pack(fill="x")
        self.locations_text.insert("1.0", self._locations_summary())
        self.locations_text.configure(state="disabled")

        self.console_text = ScrolledText(self.run_tab, height=22, wrap="word", bg="#0f172a", fg="#e5e7eb", insertbackground="#e5e7eb")
        self.console_text.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    def _build_report_tab(self) -> None:
        toolbar = ttk.Frame(self.report_tab)
        toolbar.pack(fill="x", padx=16, pady=16)
        ttk.Button(toolbar, text="Load Latest", command=lambda: self.load_report(latest_report(), select_tab=True)).pack(side="left")
        ttk.Button(toolbar, text="Refresh", command=lambda: self.load_report(self.latest_report_path, select_tab=True)).pack(side="left", padx=8)
        self.report_paths_button = ttk.Button(toolbar, text="Show Search Paths", command=self.toggle_report_paths)
        self.report_paths_button.pack(side="left", padx=8)
        self.report_path_label = ttk.Label(toolbar, text="", style="Muted.TLabel")
        self.report_path_label.pack(side="left", padx=12)

        self.report_paths_panel = self._panel(self.report_tab, "Report Search Paths")
        self.report_paths_visible = False
        self.report_paths_text = tk.Text(self.report_paths_panel, height=5, wrap="none", bg="#0f172a", fg="#e5e7eb")
        self.report_paths_text.pack(fill="x")
        self.refresh_report_paths_text()

        self.report_text = ScrolledText(
            self.report_tab,
            wrap="word",
            bg="#f8fafc",
            fg="#111827",
            insertbackground="#111827",
            relief="flat",
            padx=18,
            pady=16,
        )
        self.report_text.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self._configure_markdown_tags(self.report_text)

    def _build_history_tab(self) -> None:
        body = ttk.PanedWindow(self.history_tab, orient="horizontal")
        body.pack(fill="both", expand=True, padx=16, pady=16)

        left = self._panel(body, "Reports")
        right = self._panel(body, "Selected Report")
        body.add(left, weight=1)
        body.add(right, weight=3)

        ttk.Button(left, text="Refresh", command=self.refresh_history).pack(anchor="w", pady=(0, 8))
        paths_panel = self._panel(left, "History Search Paths")
        paths_panel.pack(fill="x", pady=(0, 8))
        self.history_paths_text = tk.Text(paths_panel, height=8, wrap="none", bg="#0f172a", fg="#e5e7eb")
        self.history_paths_text.pack(fill="x")
        self.history_list = tk.Listbox(left, bg="#0f172a", fg="#e5e7eb", activestyle="dotbox")
        self.history_list.pack(fill="both", expand=True)
        self.history_list.bind("<<ListboxSelect>>", self._history_selected)
        self.history_paths: list[Path] = []
        self.refresh_report_paths_text()

        self.history_text = ScrolledText(
            right,
            wrap="word",
            bg="#f8fafc",
            fg="#111827",
            insertbackground="#111827",
            relief="flat",
            padx=18,
            pady=16,
        )
        self.history_text.pack(fill="both", expand=True)
        self._configure_markdown_tags(self.history_text)

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

        paths_panel = self._panel(self.health_tab, "API Key Search Paths")
        paths_panel.pack(fill="x", padx=16, pady=(0, 16))
        self.api_paths_text = tk.Text(paths_panel, height=8, wrap="none", bg="#0f172a", fg="#e5e7eb")
        self.api_paths_text.pack(fill="x")
        self.refresh_api_paths_text()

        self.health_tree = self._make_tree(self.health_tab, ["source", "ok", "latency_ms", "detail"], [160, 80, 110, 700])
        self.health_tree.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    def _build_update_tab(self) -> None:
        top = ttk.Frame(self.update_tab)
        top.pack(fill="x", padx=16, pady=16)
        self.update_check_button = ttk.Button(top, text="Check For Updates", command=lambda: self.start_update_check(startup=False))
        self.update_check_button.pack(side="left")
        self.update_apply_button = ttk.Button(top, text="Update Now", command=self.start_update_apply)
        self.update_apply_button.pack(side="left", padx=8)
        self.update_apply_button.configure(state="disabled")
        self.update_status = tk.StringVar(value=f"Current version: {current_app_version()}")
        ttk.Label(top, textvariable=self.update_status, style="Muted.TLabel").pack(side="left", padx=12)

        body = self._panel(self.update_tab, "Update Details")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.update_text = tk.Text(body, height=18, wrap="word", bg="#0f172a", fg="#e5e7eb", padx=10, pady=8)
        self.update_text.pack(fill="both", expand=True)
        self._set_update_text(
            "Updates are checked from GitHub Releases.\n\n"
            "Your reports, recommendation logs, uploaded CSVs, config files, and API key files stay in the app workspace "
            "and are not deleted by app updates."
        )

    def _locations_summary(self) -> str:
        locations = app_data_locations()
        lines = ["App data folders:"]
        for label, path in locations.items():
            lines.append(f"- {label}: {path}")
        lines.append("")
        lines.append("CSV search order: temporary_upload first, then ~/Downloads, then today's exact filename under your home folder.")
        lines.append("You can also use Browse to select any holdings/activities CSV manually.")
        return "\n".join(lines)

    def refresh_api_paths_text(self) -> None:
        lines = ["The app checks these files for API keys, in order:"]
        for row in api_key_locations():
            marker = "FOUND" if row["exists"] else "missing"
            lines.append(f"- [{marker}] {row['path']}")
        self.api_paths_text.configure(state="normal")
        self.api_paths_text.delete("1.0", "end")
        self.api_paths_text.insert("1.0", "\n".join(lines))
        self.api_paths_text.configure(state="disabled")

    def refresh_report_paths_text(self) -> None:
        lines = ["The app checks these folders for markdown reports, in order:"]
        for row in report_locations():
            marker = f"FOUND {row['count']}" if row["exists"] else "missing"
            lines.append(f"- [{marker}] {row['path']}")
        text = "\n".join(lines)
        for widget_name in ("report_paths_text", "history_paths_text"):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.insert("1.0", text)
            widget.configure(state="disabled")

    def _set_update_text(self, value: str) -> None:
        self.update_text.configure(state="normal")
        self.update_text.delete("1.0", "end")
        self.update_text.insert("1.0", value)
        self.update_text.configure(state="disabled")

    def _format_update_info(self, info: Any) -> str:
        lines = [
            f"Current version: {info.current_version}",
            f"Latest version: {info.latest_version or 'unknown'}",
            f"Release page: {info.release_url}",
        ]
        if info.asset_name:
            lines.append(f"Platform asset: {info.asset_name}")
        lines.extend([
            "",
            "Data preservation:",
            "- Reports, CSV outputs, JSON logs, API keys, config, uploads, and decision journals are stored in the app workspace.",
            "- Updating replaces only the application files, not the workspace.",
        ])
        if info.body:
            lines.extend(["", "Release notes:", self._trim_text(info.body, 1800)])
        if info.error:
            lines.extend(["", f"Error: {info.error}"])
        return "\n".join(lines)

    def toggle_report_paths(self) -> None:
        if self.report_paths_visible:
            self.report_paths_panel.pack_forget()
            self.report_paths_button.configure(text="Show Search Paths")
            self.report_paths_visible = False
            return
        self.report_paths_panel.pack(fill="x", padx=16, pady=(0, 16), before=self.report_text)
        self.report_paths_button.configure(text="Hide Search Paths")
        self.report_paths_visible = True

    def _configure_markdown_tags(self, widget: tk.Text) -> None:
        base_font = tkfont.Font(family="Helvetica", size=13)
        mono_font = tkfont.Font(family="Menlo", size=12)
        widget.configure(font=base_font)
        widget.tag_configure("h1", font=("Helvetica", 24, "bold"), foreground="#0f172a", spacing1=8, spacing3=10)
        widget.tag_configure("h2", font=("Helvetica", 18, "bold"), foreground="#166534", spacing1=16, spacing3=8)
        widget.tag_configure("h3", font=("Helvetica", 15, "bold"), foreground="#1f2937", spacing1=12, spacing3=6)
        widget.tag_configure("body", font=base_font, foreground="#111827", spacing1=2, spacing3=8)
        widget.tag_configure("bold", font=("Helvetica", 13, "bold"), foreground="#111827")
        widget.tag_configure("bullet", lmargin1=20, lmargin2=38, spacing3=4)
        widget.tag_configure("table", font=mono_font, background="#e5e7eb", foreground="#111827", lmargin1=10, lmargin2=10, spacing1=1, spacing3=1)
        widget.tag_configure("table_header", font=("Menlo", 12, "bold"), background="#d1d5db", foreground="#111827", lmargin1=10, lmargin2=10)
        widget.tag_configure("rule", foreground="#94a3b8", spacing1=6, spacing3=6)

    def _insert_inline_markdown(self, widget: tk.Text, text: str, base_tag: str = "body") -> None:
        parts = re.split(r"(\*\*[^*]+\*\*)", text)
        for part in parts:
            if not part:
                continue
            if part.startswith("**") and part.endswith("**"):
                widget.insert("end", part[2:-2], (base_tag, "bold"))
            else:
                widget.insert("end", part, base_tag)

    def _parse_markdown_table(self, lines: list[str], start: int) -> tuple[list[list[str]], int]:
        rows: list[list[str]] = []
        index = start
        while index < len(lines) and lines[index].lstrip().startswith("|"):
            cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
            if cells and not all(re.fullmatch(r":?-{2,}:?", cell or "") for cell in cells):
                rows.append(cells)
            index += 1
        return rows, index

    def _insert_table(self, widget: tk.Text, rows: list[list[str]]) -> None:
        if not rows:
            return
        width = max(len(row) for row in rows)
        padded = [row + [""] * (width - len(row)) for row in rows]
        col_widths = [min(34, max(len(row[col]) for row in padded)) for col in range(width)]
        for row_index, row in enumerate(padded):
            rendered = "  ".join(cell[: col_widths[col]].ljust(col_widths[col]) for col, cell in enumerate(row))
            widget.insert("end", rendered + "\n", "table_header" if row_index == 0 else "table")
        widget.insert("end", "\n", "body")

    def _render_markdown(self, widget: tk.Text, markdown: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        lines = markdown.splitlines()
        index = 0
        while index < len(lines):
            line = lines[index].rstrip()
            stripped = line.strip()
            if not stripped:
                widget.insert("end", "\n", "body")
                index += 1
                continue
            if stripped.startswith("|"):
                rows, index = self._parse_markdown_table(lines, index)
                self._insert_table(widget, rows)
                continue
            if re.fullmatch(r"-{3,}", stripped):
                widget.insert("end", "─" * 80 + "\n", "rule")
                index += 1
                continue
            heading = re.match(r"^(#{1,3})\s+(.*)$", stripped)
            if heading:
                tag = {1: "h1", 2: "h2", 3: "h3"}[len(heading.group(1))]
                self._insert_inline_markdown(widget, heading.group(2), tag)
                widget.insert("end", "\n", tag)
                index += 1
                continue
            if stripped.startswith(("- ", "* ")):
                widget.insert("end", "• ", "bullet")
                self._insert_inline_markdown(widget, stripped[2:], "bullet")
                widget.insert("end", "\n", "bullet")
                index += 1
                continue
            numbered = re.match(r"^(\d+)\.\s+(.*)$", stripped)
            if numbered:
                widget.insert("end", f"{numbered.group(1)}. ", "bullet")
                self._insert_inline_markdown(widget, numbered.group(2), "bullet")
                widget.insert("end", "\n", "bullet")
                index += 1
                continue
            self._insert_inline_markdown(widget, stripped, "body")
            widget.insert("end", "\n", "body")
            index += 1
        widget.configure(state="disabled")

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

    def _readonly_text(self, parent: tk.Widget, *, height: int = 8) -> tk.Text:
        widget = tk.Text(
            parent,
            height=height,
            wrap="word",
            bg=self.table_bg,
            fg=self.text,
            insertbackground=self.text,
            relief="flat",
            padx=10,
            pady=8,
        )
        widget.pack(fill="both", expand=True)
        widget.configure(state="disabled")
        return widget

    def _set_readonly_text(self, widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _make_tree(self, parent: tk.Widget, columns: list[str], widths: list[int], *, height: int | None = None) -> ttk.Treeview:
        options: dict[str, Any] = {"columns": columns, "show": "headings"}
        if height is not None:
            options["height"] = height
        tree = ttk.Treeview(parent, **options)
        for column, width in zip(columns, widths):
            tree.heading(column, text=column.replace("_", " ").title())
            tree.column(column, width=width, anchor="w")
        tree.tag_configure("BUY", foreground=self.good)
        tree.tag_configure("ADD", foreground=self.good)
        tree.tag_configure("SELL", foreground=self.danger)
        tree.tag_configure("TRIM", foreground=self.warning)
        tree.tag_configure("HIGH", foreground=self.danger)
        tree.tag_configure("MEDIUM", foreground=self.warning)
        tree.tag_configure("LOW", foreground=self.muted)
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

    def confirm_detected_csv_paths(self) -> None:
        if os.environ.get("TECH_STOCK_SKIP_PATH_CONFIRM") == "1":
            return
        holdings = self.holdings_var.get().strip()
        if holdings:
            keep = messagebox.askyesno(
                "Confirm Holdings CSV",
                "The app found this Holdings CSV:\n\n"
                f"{holdings}\n\n"
                "Is this the correct file?",
            )
            if not keep:
                self.browse_csv(self.holdings_var)

        activities = self.activities_var.get().strip()
        if activities:
            keep = messagebox.askyesno(
                "Confirm Activities CSV",
                "The app found this Activities CSV:\n\n"
                f"{activities}\n\n"
                "Is this the correct file?",
            )
            if not keep:
                replace = messagebox.askyesno(
                    "Activities CSV",
                    "Do you want to choose a different Activities CSV?\n\n"
                    "Choose No to run without activities.",
                )
                if replace:
                    self.browse_csv(self.activities_var)
                else:
                    self.activities_var.set("")

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
                elif kind == "update_check_done":
                    self._update_check_done(payload)
                elif kind == "update_apply_done":
                    self._update_apply_done(payload)
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

    def _fmt_money(self, value: Any) -> str:
        try:
            return f"${float(value):,.0f}"
        except (TypeError, ValueError):
            return "N/A"

    def _fmt_price(self, value: Any) -> str:
        try:
            return f"${float(value):,.2f}"
        except (TypeError, ValueError):
            return "N/A"

    def _fmt_pct(self, value: Any, *, signed: bool = False) -> str:
        try:
            prefix = "+" if signed else ""
            return f"{float(value):{prefix}.1f}%"
        except (TypeError, ValueError):
            return "N/A"

    def _trim_text(self, value: Any, limit: int = 120) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        return text if len(text) <= limit else text[: limit - 1].rstrip() + "..."

    def _dashboard_signal(self, summary: dict[str, Any]) -> tuple[str, str]:
        actions = summary.get("priority_actions") or []
        warnings = summary.get("quality_warnings") or []
        breaches = summary.get("trailing_stop_breaches") or []
        high_or_medium = [row for row in warnings if str(row.get("severity", "")).lower() in {"high", "medium"}]
        first_action = actions[0] if actions else {}
        if first_action:
            title = f"Next action: {first_action.get('action', '')} {first_action.get('ticker', '')}".strip()
            body = first_action.get("rationale") or first_action.get("reason") or summary.get("session_summary") or ""
        elif high_or_medium:
            first_warning = high_or_medium[0]
            title = f"Review required: {first_warning.get('code', 'quality warning')}"
            body = first_warning.get("message") or first_warning.get("action_required") or ""
        elif breaches:
            first_breach = breaches[0]
            title = f"Stop breach: {first_breach.get('ticker', '')}"
            body = f"Current {first_breach.get('current_price', 'N/A')} vs stop {first_breach.get('stop_price', 'N/A')}."
        else:
            title = "No urgent action flagged"
            body = summary.get("session_summary") or "Latest report did not produce priority actions."
        return title, self._trim_text(body, 260)

    def _risk_summary_text(self, summary: dict[str, Any]) -> str:
        health = summary.get("portfolio_health") or {}
        risk = summary.get("risk_dashboard") or {}
        beta = risk.get("beta") or {}
        pairs = risk.get("correlated_pairs") or []
        sector_warnings = summary.get("sector_warnings") or []
        lines = [
            f"Portfolio value: {self._fmt_money(health.get('total_value_usd_equivalent') or risk.get('total_value_usd'))}",
            f"Overall P&L: {self._fmt_pct(health.get('overall_pnl_pct'), signed=True)}",
            f"Concentration risk: {str(health.get('concentration_risk') or 'N/A').upper()}",
            f"Beta: SPY {beta.get('SPY', 'N/A')} | QQQ {beta.get('QQQ', 'N/A')} | SMH {beta.get('SMH', 'N/A')}",
            f"Volatility / drawdown: {self._fmt_pct(risk.get('annualized_volatility_pct'))} annual vol, {self._fmt_pct(risk.get('max_drawdown_estimate_pct'), signed=True)} max-DD estimate",
            f"Top-3 concentration: {self._fmt_pct(risk.get('top3_concentration_pct'))}",
        ]
        if pairs:
            lines.append("")
            lines.append("Highly correlated pairs:")
            for pair in pairs[:4]:
                lines.append(f"- {pair.get('pair')}: {pair.get('correlation')}")
        if sector_warnings:
            lines.append("")
            lines.append("Sector signals:")
            for warning in sector_warnings[:4]:
                lines.append(f"- {self._trim_text(warning, 120)}")
        return "\n".join(lines)

    def _signals_summary_text(self, summary: dict[str, Any]) -> str:
        lines: list[str] = []
        drift = summary.get("drift") or []
        hedges = summary.get("hedge_suggestions") or []
        market = summary.get("market_context_snapshot") or {}
        watchlist = summary.get("watchlist_flags") or []
        if drift:
            lines.append("Changes since previous run:")
            for row in drift[:5]:
                now = row.get("now") or {}
                was = row.get("was") or {}
                lines.append(f"- {row.get('ticker')}: {row.get('drift_type')} ({was.get('action', 'new')} -> {now.get('action', 'dropped')})")
        if hedges:
            lines.append("")
            lines.append("Hedge / rebalance ideas:")
            for row in hedges[:4]:
                lines.append(f"- {row.get('instrument')}: {self._trim_text(row.get('action') or row.get('rationale'), 130)}")
        if market:
            ranked = sorted(
                market.items(),
                key=lambda item: abs(float((item[1] or {}).get("change_pct_21d") or 0)),
                reverse=True,
            )
            lines.append("")
            lines.append("Market context leaders:")
            for ticker, row in ranked[:5]:
                lines.append(f"- {ticker}: {row.get('current_price', 'N/A')} | 5d {self._fmt_pct(row.get('change_pct_5d'), signed=True)} | 1mo {self._fmt_pct(row.get('change_pct_21d'), signed=True)}")
        if watchlist:
            lines.append("")
            lines.append("Watchlist signals:")
            for row in watchlist[:3]:
                lines.append(f"- {row.get('ticker')}: {self._trim_text(row.get('why_noteworthy'), 125)}")
        return "\n".join(lines) or "No drift, hedge, market, or watchlist signals available yet."

    def _dashboard_tone(self, key: Any) -> tuple[str, str]:
        value = str(key or "").upper()
        if value in {"BUY", "ADD"}:
            return self.good, "#10231a"
        if value in {"SELL", "HIGH"}:
            return self.danger, "#2a1618"
        if value in {"TRIM", "MEDIUM"}:
            return self.warning, "#261f12"
        if value in {"WATCH", "LOW"}:
            return self.muted, "#151827"
        return self.accent, "#171827"

    def _set_metric(self, label: str, value: str, hint: str = "") -> None:
        if label in self.metric_vars:
            self.metric_vars[label].set(value)
        if label in self.metric_hint_vars:
            self.metric_hint_vars[label].set(hint)

    def _clear_dashboard_section(self, frame: tk.Frame) -> None:
        for child in frame.winfo_children():
            child.destroy()

    def _empty_dashboard_section(self, frame: tk.Frame, message: str) -> None:
        self._clear_dashboard_section(frame)
        tk.Label(
            frame,
            text=message,
            bg=self.panel,
            fg=self.muted,
            justify="left",
            anchor="w",
            padx=8,
            pady=8,
        ).pack(fill="x")

    def _dashboard_tag(self, parent: tk.Widget, text: Any, *, color: str) -> None:
        tk.Label(
            parent,
            text=str(text or ""),
            bg=color,
            fg="#0a0a10",
            font=("Helvetica", 10, "bold"),
            padx=8,
            pady=2,
        ).pack(side="left", padx=(0, 6))

    def _wrapped_dashboard_label(self, parent: tk.Widget, text: str, *, bg: str, fg: str, font: tuple[str, int, str] | tuple[str, int] = ("Helvetica", 11)) -> tk.Label:
        label = tk.Label(parent, text=text, bg=bg, fg=fg, font=font, justify="left", anchor="w", wraplength=900)
        label.pack(fill="x", pady=(6, 0))
        parent.bind("<Configure>", lambda event, widget=label: widget.configure(wraplength=max(event.width - 20, 260)))
        return label

    def _render_action_cards(self, rows: list[dict[str, Any]]) -> None:
        self._clear_dashboard_section(self.action_cards)
        if not rows:
            self._empty_dashboard_section(self.action_cards, "No priority actions in the latest report.")
            return
        for row in rows[:8]:
            action = row.get("action") or ""
            accent, bg = self._dashboard_tone(action)
            card = tk.Frame(self.action_cards, bg=bg, highlightthickness=1, highlightbackground="#303044")
            card.pack(fill="x", pady=(0, 8))
            tk.Frame(card, bg=accent, width=5).pack(side="left", fill="y")
            body = tk.Frame(card, bg=bg, padx=12, pady=10)
            body.pack(side="left", fill="both", expand=True)

            header = tk.Frame(body, bg=bg)
            header.pack(fill="x")
            self._dashboard_tag(header, f"#{row.get('order', '')}", color=accent)
            self._dashboard_tag(header, action, color=accent)
            tk.Label(
                header,
                text=str(row.get("ticker") or ""),
                bg=bg,
                fg=self.text,
                font=("Helvetica", 13, "bold"),
            ).pack(side="left", padx=(2, 10))
            size = row.get("action_size_label") or row.get("shares") or row.get("invest_amount_usd") or ""
            if size:
                tk.Label(header, text=str(size), bg=bg, fg=self.muted, font=("Helvetica", 11)).pack(side="left")

            reason = row.get("rationale") or row.get("reason") or row.get("message") or ""
            self._wrapped_dashboard_label(body, self._trim_text(reason, 360), bg=bg, fg=self.text)
        if len(rows) > 8:
            tk.Label(
                self.action_cards,
                text=f"{len(rows) - 8} more actions are in the full report.",
                bg=self.panel,
                fg=self.muted,
            ).pack(anchor="w", pady=(0, 4))

    def _render_warning_cards(self, rows: list[dict[str, Any]]) -> None:
        self._clear_dashboard_section(self.warning_cards)
        if not rows:
            self._empty_dashboard_section(self.warning_cards, "No quality warnings in the latest report.")
            return
        for row in rows[:7]:
            severity = str(row.get("severity") or "LOW").upper()
            accent, bg = self._dashboard_tone(severity)
            card = tk.Frame(self.warning_cards, bg=bg, highlightthickness=1, highlightbackground="#303044")
            card.pack(fill="x", pady=(0, 8))
            body = tk.Frame(card, bg=bg, padx=10, pady=8)
            body.pack(fill="both", expand=True)
            header = tk.Frame(body, bg=bg)
            header.pack(fill="x")
            self._dashboard_tag(header, severity, color=accent)
            if row.get("ticker"):
                self._dashboard_tag(header, row.get("ticker"), color="#64748b")
            tk.Label(
                header,
                text=str(row.get("code") or ""),
                bg=bg,
                fg=self.text,
                font=("Helvetica", 11, "bold"),
            ).pack(side="left", padx=(2, 0))
            message = row.get("action_required") or row.get("message") or ""
            self._wrapped_dashboard_label(body, self._trim_text(message, 240), bg=bg, fg=self.text, font=("Helvetica", 10))
        if len(rows) > 7:
            tk.Label(
                self.warning_cards,
                text=f"{len(rows) - 7} more warnings are in the report.",
                bg=self.panel,
                fg=self.muted,
            ).pack(anchor="w", pady=(0, 4))

    def _render_stop_cards(self, rows: list[dict[str, Any]]) -> None:
        self._clear_dashboard_section(self.stop_cards)
        if not rows:
            self._empty_dashboard_section(self.stop_cards, "No trailing-stop breaches in the latest report.")
            return
        for row in rows[:5]:
            action = row.get("recommended_action") or "REVIEW"
            accent, bg = self._dashboard_tone(action)
            card = tk.Frame(self.stop_cards, bg=bg, highlightthickness=1, highlightbackground="#303044")
            card.pack(fill="x", pady=(0, 8))
            body = tk.Frame(card, bg=bg, padx=10, pady=8)
            body.pack(fill="both", expand=True)
            header = tk.Frame(body, bg=bg)
            header.pack(fill="x")
            self._dashboard_tag(header, row.get("ticker") or "", color=accent)
            self._dashboard_tag(header, action, color=accent)
            metrics = (
                f"Now {self._fmt_price(row.get('current_price'))} | "
                f"Stop {self._fmt_price(row.get('stop_price'))} | "
                f"Gain {self._fmt_pct(row.get('current_gain_pct'), signed=True)}"
            )
            tk.Label(header, text=metrics, bg=bg, fg=self.text, font=("Helvetica", 10, "bold")).pack(side="left")
            note = row.get("rationale") or row.get("message") or ""
            if note:
                self._wrapped_dashboard_label(body, self._trim_text(note, 220), bg=bg, fg=self.muted, font=("Helvetica", 10))

    def refresh_dashboard(self) -> None:
        summary = latest_log_summary()
        if not summary:
            self.dashboard_caption.configure(text="No recommendation JSON logs found yet.")
            self.signal_accent.configure(bg=self.muted)
            self.signal_kicker.set("ACTION PULSE")
            self.signal_title.set("No report loaded")
            self.signal_body.set("Run a report to populate action signals.")
            self.signal_meta.set("")
            for label in self.metric_vars:
                self._set_metric(label, "N/A")
            self._empty_dashboard_section(self.action_cards, "Run a report to populate priority actions.")
            self._empty_dashboard_section(self.warning_cards, "Run a report to populate quality gates.")
            self._empty_dashboard_section(self.stop_cards, "Run a report to populate stop breaches.")
            self._set_readonly_text(self.risk_text, "No risk dashboard available yet.")
            self._set_readonly_text(self.signal_text, "No drift or market signals available yet.")
            return
        self.dashboard_caption.configure(text=str(summary.get("session_file", "")))
        title, body = self._dashboard_signal(summary)
        self.signal_title.set(title)
        self.signal_body.set(body)

        risk = summary.get("risk_dashboard") or {}
        health = summary.get("portfolio_health") or {}
        beta = risk.get("beta") or {}
        usage = summary.get("usage") or {}
        warnings = summary.get("quality_warnings") or []
        medium_plus = sum(1 for row in warnings if str(row.get("severity", "")).lower() in {"high", "medium"})
        actions = summary.get("priority_actions", []) or []
        breaches = summary.get("trailing_stop_breaches", []) or []
        first_action = actions[0] if actions else {}
        signal_color, _signal_bg = self._dashboard_tone(first_action.get("action") if first_action else ("HIGH" if medium_plus else "LOW"))
        self.signal_accent.configure(bg=signal_color)
        self.signal_kicker.set("NEXT TRADER ACTION" if actions else "ACTION PULSE")
        self.signal_meta.set(f"{len(actions)} priority actions | {medium_plus} high/medium quality gates | {len(breaches)} stop breaches")

        concentration = str(health.get("concentration_risk") or "unknown").upper()
        self._set_metric("Portfolio", self._fmt_money(health.get("total_value_usd_equivalent") or risk.get("total_value_usd")), "USD equivalent")
        self._set_metric("P&L", self._fmt_pct(health.get("overall_pnl_pct"), signed=True), "overall")
        self._set_metric("SPY Beta", str(beta.get("SPY", "N/A")), f"QQQ {beta.get('QQQ', 'N/A')} | SMH {beta.get('SMH', 'N/A')}")
        self._set_metric("Annual Vol", f"{risk.get('annualized_volatility_pct', 0):.1f}%", f"max DD {self._fmt_pct(risk.get('max_drawdown_estimate_pct'), signed=True)}")
        self._set_metric("Top-3 Conc.", f"{risk.get('top3_concentration_pct', 0):.1f}%", f"risk {concentration}")
        self._set_metric("Warnings", str(medium_plus), f"{len(warnings)} total gates")
        self._set_metric("Claude Cost", f"${usage.get('cost_usd', 0):.4f}", f"{int(usage.get('total_tokens', 0) or 0):,} tokens")
        self._render_action_cards(actions)
        self._render_warning_cards(warnings)
        self._render_stop_cards(breaches)
        self._set_readonly_text(self.risk_text, self._risk_summary_text(summary))
        self._set_readonly_text(self.signal_text, self._signals_summary_text(summary))

    def _replace_tree_rows(self, tree: ttk.Treeview, rows: list[list[Any]], *, tag_index: int | None = None) -> None:
        for item in tree.get_children():
            tree.delete(item)
        for row in rows:
            tags = ()
            if tag_index is not None and tag_index < len(row):
                tags = (str(row[tag_index]).upper(),)
            tree.insert("", "end", values=row, tags=tags)

    def load_report(self, path: Path | None, *, select_tab: bool = False) -> None:
        self.refresh_report_paths_text()
        self.latest_report_path = path
        text = read_text_file(path)
        if not path or not text:
            self.report_path_label.configure(text="No report selected.")
            self._render_markdown(self.report_text, "## No report found yet\n\nRun a report or choose one from History.")
            if select_tab:
                self.tabs.select(self.report_tab)
            return
        self.report_path_label.configure(text=relative_to_root(path))
        self._render_markdown(self.report_text, text)
        if select_tab:
            self.tabs.select(self.report_tab)

    def refresh_history(self) -> None:
        self.refresh_report_paths_text()
        self.history_paths = list_reports(limit=100)
        self.history_list.delete(0, "end")
        for path in self.history_paths:
            self.history_list.insert("end", f"{path.name}  -  {relative_to_root(path.parent)}")

    def _history_selected(self, _event: object) -> None:
        selection = self.history_list.curselection()
        if not selection:
            return
        path = self.history_paths[selection[0]]
        self._render_markdown(self.history_text, read_text_file(path) or "## Could not read report")

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
        self.refresh_api_paths_text()
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

    def start_update_check(self, *, startup: bool = False) -> None:
        self.update_check_button.configure(state="disabled")
        self.update_status.set("Checking GitHub Releases...")
        if not startup:
            self.tabs.select(self.update_tab)

        def worker() -> None:
            info = check_update_available()
            self.progress_queue.put(("update_check_done", {"info": info, "startup": startup}))

        threading.Thread(target=worker, daemon=True).start()

    def _update_check_done(self, payload: dict[str, Any]) -> None:
        info = payload["info"]
        startup = bool(payload.get("startup"))
        self.latest_update_info = info
        self.update_check_button.configure(state="normal")
        self.update_apply_button.configure(state="normal" if info.available else "disabled")
        self._set_update_text(self._format_update_info(info))

        if info.error:
            self.update_status.set("Update check failed.")
            if not startup:
                messagebox.showwarning("Update check failed", str(info.error))
            return

        if not info.available:
            self.update_status.set(f"Up to date: v{info.current_version}")
            if not startup:
                messagebox.showinfo("No update available", f"tech_stock v{info.current_version} is up to date.")
            return

        self.update_status.set(f"Version {info.latest_version} is available.")
        should_update = messagebox.askyesno(
            "Update available",
            f"Version {info.latest_version} is available.\n\n"
            f"You are currently on version {info.current_version}.\n\n"
            "Do you want to update now?\n\n"
            "Your reports, logs, uploaded CSVs, config files, and API key files will be kept.",
        )
        if should_update:
            self.start_update_apply()

    def start_update_apply(self) -> None:
        info = self.latest_update_info
        if not info or not getattr(info, "available", False):
            self.start_update_check(startup=False)
            return
        self.update_check_button.configure(state="disabled")
        self.update_apply_button.configure(state="disabled")
        self.update_status.set(f"Updating to version {info.latest_version}...")
        self.tabs.select(self.update_tab)

        def worker() -> None:
            result = apply_available_update(info, restart=True)
            self.progress_queue.put(("update_apply_done", result))

        threading.Thread(target=worker, daemon=True).start()

    def _update_apply_done(self, result: Any) -> None:
        self.update_check_button.configure(state="normal")
        self.update_apply_button.configure(state="normal" if self.latest_update_info and self.latest_update_info.available else "disabled")
        self.update_status.set("Update ready." if result.ok else "Update failed.")
        details = f"{result.message}\n\nUpdate log:\n{result.log_path}"
        if result.downloaded_path:
            details += f"\n\nDownloaded file:\n{result.downloaded_path}"
        self._set_update_text(details)
        if not result.ok:
            messagebox.showerror("Update failed", details)
            return
        messagebox.showinfo("Update started", details)
        if result.restart_started:
            self.after(800, self.destroy)


def main() -> None:
    app = DesktopApp()
    app.mainloop()


if __name__ == "__main__":
    main()
