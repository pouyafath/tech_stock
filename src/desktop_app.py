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
    API_KEY_FIELDS,
    api_health_view,
    api_key_locations,
    api_key_inventory,
    app_data_locations,
    apply_available_update,
    buy_signal_view,
    check_update_available,
    current_app_version,
    default_run_settings,
    diagnostics_view,
    diagnostics_support_bundle,
    find_default_csvs,
    latest_log_summary,
    latest_report,
    learning_view,
    list_reports,
    preview_holdings_csv,
    read_editable_json,
    read_text_file,
    relative_to_root,
    report_locations,
    run_report_from_ui,
    delete_api_key,
    save_api_key,
    validate_json_text,
    write_editable_json,
)
from src.performance_history import portfolio_performance_summary

try:
    from src.ui_theme import PALETTE  # noqa: E402
except Exception:  # pragma: no cover — defensive fallback for early bundle init

    class _PaletteFallback:
        bg = "#0b0d14"
        surface = "#12141c"
        panel = "#171a26"
        card = "#1c1f2e"
        border = "#272b3c"
        border_strong = "#363b52"
        text = "#e6e9f2"
        text_strong = "#ffffff"
        muted = "#8a93a8"
        subtle = "#5b6478"
        accent = "#22c55e"
        accent_hover = "#16a34a"
        warn = "#f59e0b"
        danger = "#ef4444"
        info = "#38bdf8"
        neutral = "#94a3b8"

    PALETTE = _PaletteFallback()  # type: ignore[assignment]


IS_MACOS = sys.platform == "darwin"
MOD_KEY = "Command" if IS_MACOS else "Control"
MOD_LABEL = "⌘" if IS_MACOS else "Ctrl+"


def _platform_fonts() -> dict[str, tuple]:
    """Return a font ladder tuned per-platform.

    On macOS we use the system "SF Pro" stack (Apple's modern default). On
    Windows we use Segoe UI; elsewhere we fall back to TkDefaultFont. Each
    entry is ``(family, size, weight)``.
    """
    if IS_MACOS:
        family_display = "SF Pro Display"
        family_text = "SF Pro Text"
        mono = "SF Mono"
    elif sys.platform == "win32":
        family_display = "Segoe UI"
        family_text = "Segoe UI"
        mono = "Consolas"
    else:
        family_display = "TkDefaultFont"
        family_text = "TkDefaultFont"
        mono = "TkFixedFont"
    return {
        "title": (family_display, 28, "bold"),
        "heading": (family_display, 17, "bold"),
        "subheading": (family_text, 13, "bold"),
        "body": (family_text, 12, "normal"),
        "small": (family_text, 11, "normal"),
        "mono": (mono, 12, "normal"),
    }


SEARCH_MATCH_LIMIT = 500


def find_search_offsets(text: str, query: str, limit: int = SEARCH_MATCH_LIMIT) -> tuple[list[tuple[int, int]], bool]:
    """Return non-overlapping case-insensitive match offsets without using Tk's text search."""
    if not query:
        return [], False
    haystack = text.lower()
    needle = query.lower()
    matches: list[tuple[int, int]] = []
    start = 0
    truncated = False
    while True:
        index = haystack.find(needle, start)
        if index == -1:
            break
        end = index + len(query)
        matches.append((index, end))
        start = end
        if len(matches) >= limit:
            truncated = haystack.find(needle, start) != -1
            break
    return matches, truncated


class DesktopApp(tk.Tk):
    """Native desktop dashboard for users who do not want a browser UI."""

    def __init__(self) -> None:
        super().__init__()
        self.title("tech_stock")
        self.geometry("1200x840")
        self.minsize(980, 680)

        # Shared palette (Streamlit + Textual + Tkinter all read the same tokens)
        self.bg = PALETTE.bg
        self.surface = PALETTE.surface
        self.panel = PALETTE.panel
        self.text = PALETTE.text
        self.text_strong = PALETTE.text_strong
        self.muted = PALETTE.muted
        self.accent = PALETTE.accent
        self.accent_hover = PALETTE.accent_hover
        self.danger = PALETTE.danger
        self.warning = PALETTE.warn
        self.good = PALETTE.accent
        self.card = PALETTE.card
        self.border = PALETTE.border
        self.border_strong = PALETTE.border_strong
        self.table_bg = "#0f172a"
        self.configure(bg=self.bg)

        # Platform-aware font ladder
        self.fonts = _platform_fonts()

        self.progress_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.latest_report_path: Path | None = None  # lazily resolved after first paint
        self.latest_update_info: Any = None
        self.search_state: dict[str, dict[str, Any]] = {}
        self._warmed_tabs: set[str] = set()

        self._configure_style()
        self._build_menu()
        self._build_header()
        self._build_tabs()

        # Universal accelerators — the menu also binds these, but bind_all
        # ensures they work even before the menu is realised on macOS.
        self.bind_all(f"<{MOD_KEY}-f>", self.focus_active_search)
        self.bind_all(f"<{MOD_KEY}-r>", lambda _e: self._refresh_active_tab())
        self.bind_all(f"<{MOD_KEY}-comma>", lambda _e: self._jump_to_tab(self.editor_tab))
        self.bind_all(f"<{MOD_KEY}-n>", lambda _e: self._jump_to_tab(self.run_tab))
        self.bind_all(f"<{MOD_KEY}-l>", lambda _e: self.load_report(latest_report(), select_tab=True))

        # Drain the progress queue every 100ms — cheap, must run on the Tk loop.
        self.after(100, self._drain_progress_queue)

        # Defer ALL non-essential startup work to after the first paint.
        # The window now appears instantly; heavy I/O happens behind the scenes.
        self.after_idle(self._post_paint_warmup)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            # 'aqua' is macOS's native theme and respects system dark mode
            # better than 'clam'. Fall back if it isn't available.
            preferred = "aqua" if IS_MACOS and "aqua" in style.theme_names() else "clam"
            style.theme_use(preferred)
        except tk.TclError:
            pass
        fonts = self.fonts
        style.configure("TFrame", background=self.bg)
        style.configure("Panel.TFrame", background=self.panel)
        style.configure("TLabel", background=self.bg, foreground=self.text, font=fonts["body"])
        style.configure("Muted.TLabel", background=self.bg, foreground=self.muted, font=fonts["small"])
        style.configure("Title.TLabel", background=self.bg, foreground=self.accent, font=fonts["title"])
        style.configure("TButton", padding=(12, 7), font=fonts["body"])
        style.configure("Accent.TButton", padding=(14, 8), font=fonts["subheading"])
        style.configure("TNotebook", background=self.bg, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(18, 9), font=fonts["body"])
        style.map(
            "TNotebook.Tab",
            background=[("selected", self.surface)],
            foreground=[("selected", self.accent)],
        )
        style.configure(
            "Treeview",
            rowheight=28,
            background=self.table_bg,
            fieldbackground=self.table_bg,
            foreground=self.text,
            borderwidth=0,
            font=fonts["body"],
        )
        style.configure(
            "Treeview.Heading",
            background=self.surface,
            foreground=self.text_strong,
            font=fonts["subheading"],
            relief="flat",
        )
        style.map("Treeview.Heading", background=[("active", self.panel)])

    def _build_menu(self) -> None:
        """Build the native macOS menu bar (also works on Windows/Linux)."""
        menubar = tk.Menu(self)

        # — App menu (macOS automatically pulls this from the first menu) —
        if IS_MACOS:
            # The first 'apple' menu is auto-handled by Tk on macOS; we also
            # use the special "TK." prefix to inject items into the
            # application menu (About / Preferences / Quit grouping).
            app_menu = tk.Menu(menubar, name="apple", tearoff=0)
            app_menu.add_command(label="About tech_stock", command=self._show_about_dialog)
            menubar.add_cascade(menu=app_menu)
            # Wire up the system Preferences shortcut (⌘,)
            self.createcommand("tk::mac::ShowPreferences", lambda: self._jump_to_tab(self.editor_tab))
            self.createcommand("tk::mac::Quit", self.destroy)

        # — File menu —
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(
            label="New Report…",
            accelerator=f"{MOD_LABEL}N",
            command=lambda: self._jump_to_tab(self.run_tab),
        )
        file_menu.add_command(
            label="Open Latest Report",
            accelerator=f"{MOD_LABEL}L",
            command=lambda: self.load_report(latest_report(), select_tab=True),
        )
        file_menu.add_separator()
        file_menu.add_command(label="Reveal Workspace in Finder", command=self._reveal_workspace)
        file_menu.add_command(label="Reveal Latest Report", command=self._reveal_latest_report)
        if not IS_MACOS:
            file_menu.add_separator()
            file_menu.add_command(label="Quit", accelerator="Ctrl+Q", command=self.destroy)
            self.bind_all("<Control-q>", lambda _e: self.destroy())
        menubar.add_cascade(label="File", menu=file_menu)

        # — View menu —
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="Dashboard", command=lambda: self._jump_to_tab(self.dashboard_tab))
        view_menu.add_command(label="Buy Signals", command=lambda: self._jump_to_tab(self.buy_signals_tab))
        view_menu.add_command(label="Report Viewer", command=lambda: self._jump_to_tab(self.report_tab))
        view_menu.add_command(label="History", command=lambda: self._jump_to_tab(self.history_tab))
        view_menu.add_command(label="Config Editor", accelerator=f"{MOD_LABEL},", command=lambda: self._jump_to_tab(self.editor_tab))
        view_menu.add_separator()
        view_menu.add_command(
            label="Refresh Current Tab",
            accelerator=f"{MOD_LABEL}R",
            command=self._refresh_active_tab,
        )
        view_menu.add_command(
            label="Find in Report…",
            accelerator=f"{MOD_LABEL}F",
            command=self.focus_active_search,
        )
        menubar.add_cascade(label="View", menu=view_menu)

        # — Help menu —
        help_menu = tk.Menu(menubar, tearoff=0, name="help")
        help_menu.add_command(label="Check for Updates…", command=lambda: self.start_update_check(startup=False))
        help_menu.add_command(label="Open GitHub Repository", command=self._open_repo)
        help_menu.add_command(label="Report a Bug…", command=self._open_issues)
        if not IS_MACOS:
            help_menu.add_separator()
            help_menu.add_command(label="About tech_stock", command=self._show_about_dialog)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menubar)

    def _build_header(self) -> None:
        header = ttk.Frame(self)
        header.pack(fill="x", padx=22, pady=(18, 8))

        left = ttk.Frame(header)
        left.pack(side="left", anchor="w")
        ttk.Label(left, text="tech_stock", style="Title.TLabel").pack(side="left")
        ttk.Label(
            left,
            text=f"v{current_app_version()} · embedded desktop dashboard",
            style="Muted.TLabel",
        ).pack(side="left", padx=(14, 0), pady=(14, 0))

        # Status pill on the right shows API health summary once warmed up.
        self.header_status_var = tk.StringVar(value="● Warming up…")
        self.header_status_label = ttk.Label(
            header,
            textvariable=self.header_status_var,
            style="Muted.TLabel",
        )
        self.header_status_label.pack(side="right", padx=(0, 6), pady=(14, 0))

    def _build_tabs(self) -> None:
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=18, pady=(0, 18))

        self.dashboard_tab = ttk.Frame(self.tabs)
        self.buy_signals_tab = ttk.Frame(self.tabs)
        self.run_tab = ttk.Frame(self.tabs)
        self.report_tab = ttk.Frame(self.tabs)
        self.history_tab = ttk.Frame(self.tabs)
        self.performance_tab = ttk.Frame(self.tabs)
        self.learning_tab = ttk.Frame(self.tabs)
        self.diagnostics_tab = ttk.Frame(self.tabs)
        self.schedule_tab = ttk.Frame(self.tabs)
        self.editor_tab = ttk.Frame(self.tabs)
        self.health_tab = ttk.Frame(self.tabs)
        self.update_tab = ttk.Frame(self.tabs)

        self.tabs.add(self.dashboard_tab, text="Dashboard")
        self.tabs.add(self.buy_signals_tab, text="Buy Signals")
        self.tabs.add(self.run_tab, text="Run Report")
        self.tabs.add(self.report_tab, text="Report Viewer")
        self.tabs.add(self.history_tab, text="History")
        self.tabs.add(self.performance_tab, text="Performance")
        self.tabs.add(self.learning_tab, text="Learning")
        self.tabs.add(self.diagnostics_tab, text="Diagnostics")
        self.tabs.add(self.schedule_tab, text="Schedule")
        self.tabs.add(self.editor_tab, text="Config Editor")
        self.tabs.add(self.health_tab, text="API Checks")
        self.tabs.add(self.update_tab, text="Updates")

        self._build_dashboard_tab()
        self._build_buy_signals_tab()
        self._build_run_tab()
        self._build_report_tab()
        self._build_history_tab()
        self._build_performance_tab()
        self._build_learning_tab()
        self._build_diagnostics_tab()
        self._build_schedule_tab()
        self._build_editor_tab()
        self._build_health_tab()
        self._build_update_tab()

    # ── Lazy-warm-up & menu helpers ─────────────────────────────────────────
    def _post_paint_warmup(self) -> None:
        """Run after the first paint; load lightweight context, defer heavy work."""
        # 1. Cheap: read the latest report path from disk (~1ms)
        self.latest_report_path = latest_report()

        # 2. Cheap: paint dashboard from the most recent JSON log
        self.refresh_dashboard()
        self.refresh_history()
        self.load_report(self.latest_report_path, select_tab=False)
        self._update_header_status()

        # 3. Background: CSV detection toast (350 ms after paint)
        self.after(350, self.confirm_detected_csv_paths)

        # 4. Background: cached update check after 1.2 s
        if os.environ.get("TECH_STOCK_SKIP_UPDATE_CHECK") != "1":
            self.after(1200, lambda: self.start_update_check(startup=True))

        # 5. Buy-signal refresh is deferred until the tab is *actually opened*.
        self.tabs.bind("<<NotebookTabChanged>>", self._on_tab_changed, add="+")

    def _on_tab_changed(self, _event: object) -> None:
        """Warm up a tab the first time the user actually visits it.

        Saves 2-5 s of yfinance / API calls when the user just wants to read
        the latest report and never opens Buy Signals or API Checks.
        """
        try:
            selected = self.tabs.select()
            tab_text = self.tabs.tab(selected, "text")
        except tk.TclError:
            return
        if tab_text in self._warmed_tabs:
            return
        self._warmed_tabs.add(tab_text)
        if tab_text == "Buy Signals":
            self.start_buy_signal_refresh()
        elif tab_text == "API Checks":
            # Refresh the API key inventory; live connectivity probe stays manual.
            self.refresh_api_key_manager()
        elif tab_text == "Learning":
            self.refresh_learning_tab()
        elif tab_text == "Diagnostics":
            self.refresh_diagnostics_tab()
        elif tab_text == "Performance":
            self.refresh_performance_tab()
        elif tab_text == "Schedule":
            self.refresh_schedule_tab()

    def _refresh_active_tab(self) -> None:
        """⌘R handler — re-run the data-load for whichever tab is in front."""
        try:
            selected = self.tabs.select()
            tab_text = self.tabs.tab(selected, "text")
        except tk.TclError:
            return
        actions: dict[str, callable] = {
            "Dashboard": self.refresh_dashboard,
            "Buy Signals": self.start_buy_signal_refresh,
            "Report Viewer": lambda: self.load_report(latest_report(), select_tab=True),
            "History": self.refresh_history,
            "Performance": self.refresh_performance_tab,
            "Learning": self.refresh_learning_tab,
            "Diagnostics": self.refresh_diagnostics_tab,
            "Schedule": self.refresh_schedule_tab,
            "Config Editor": self.load_editor_file,
            "API Checks": self.start_connectivity_check,
            "Updates": lambda: self.start_update_check(startup=False),
        }
        handler = actions.get(tab_text)
        if handler is not None:
            handler()

    def _jump_to_tab(self, tab_frame: ttk.Frame) -> None:
        try:
            self.tabs.select(tab_frame)
        except tk.TclError:
            pass

    def _update_header_status(self) -> None:
        """Refresh the small status pill at the top-right of the window."""
        summary = latest_log_summary() or {}
        usage = summary.get("usage") or {}
        warnings = summary.get("quality_warnings") or []
        if not summary or summary.get("error"):
            self.header_status_var.set("● No data yet")
            return
        cost = usage.get("cost_usd")
        parts = []
        if cost is not None:
            parts.append(f"⚡ ${cost:.4f}")
        if warnings:
            critical = sum(1 for w in warnings if str(w.get("severity", "")).lower() in {"critical", "high"})
            if critical:
                parts.append(f"⛔ {critical}")
            else:
                parts.append(f"⚠️ {len(warnings)}")
        else:
            parts.append("✓ clean")
        self.header_status_var.set(" · ".join(parts) or "Ready.")

    def _show_about_dialog(self) -> None:
        from tkinter import messagebox

        messagebox.showinfo(
            f"About tech_stock {current_app_version()}",
            f"tech_stock v{current_app_version()}\n\n"
            "AI-powered portfolio advisor — built on Claude.\n\n"
            "Two-pass review · deterministic quality gates · full audit trail.\n\n"
            "https://github.com/pouyafath/tech_stock\n\n"
            "© 2026 tech_stock",
        )

    def _reveal_workspace(self) -> None:
        from src.ui_support import app_data_locations as _locs

        locations = _locs()
        root = locations.get("workspace") or Path.home()
        self._reveal_in_finder(Path(root))

    def _reveal_latest_report(self) -> None:
        report = latest_report()
        if report is None:
            from tkinter import messagebox

            messagebox.showinfo("No report yet", "Generate a report first from the Run Report tab.")
            return
        self._reveal_in_finder(report)

    def _reveal_in_finder(self, path: Path) -> None:
        import subprocess

        try:
            if IS_MACOS:
                subprocess.Popen(["open", "-R", str(path)] if path.is_file() else ["open", str(path)])
            elif sys.platform == "win32":
                if path.is_file():
                    subprocess.Popen(["explorer", "/select,", str(path)])
                else:
                    os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(path.parent if path.is_file() else path)])
        except Exception:
            pass

    def _open_repo(self) -> None:
        import webbrowser

        webbrowser.open("https://github.com/pouyafath/tech_stock")

    def _open_issues(self) -> None:
        import webbrowser

        webbrowser.open("https://github.com/pouyafath/tech_stock/issues/new")

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
            tk.Label(box, textvariable=var, bg=self.card, fg=self.text, font=("Helvetica", 20, "bold")).pack(anchor="w", pady=(4, 0))
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

    def _build_buy_signals_tab(self) -> None:
        top = ttk.Frame(self.buy_signals_tab)
        top.pack(fill="x", padx=16, pady=16)
        self.buy_signal_button = ttk.Button(top, text="Refresh Buy Signals", command=self.start_buy_signal_refresh)
        self.buy_signal_button.pack(side="left")
        self.buy_action_filter = tk.StringVar(value="All actions")
        self.buy_readiness_filter = tk.StringVar(value="All readiness")
        ttk.Combobox(
            top,
            textvariable=self.buy_action_filter,
            values=["All actions", "BUY/ADD", "add_on_dip"],
            state="readonly",
            width=13,
        ).pack(side="left", padx=(10, 0))
        ttk.Combobox(
            top,
            textvariable=self.buy_readiness_filter,
            values=["All readiness", "Trade Ready", "Review First", "Blocked"],
            state="readonly",
            width=15,
        ).pack(side="left", padx=(8, 0))
        self.buy_signal_status = tk.StringVar(value="Uses latest report plus refreshed source data.")
        ttk.Label(top, textvariable=self.buy_signal_status, style="Muted.TLabel").pack(side="left", padx=12)

        self.buy_signal_tabs = ttk.Notebook(self.buy_signals_tab)
        self.buy_signal_tabs.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        overview = ttk.Frame(self.buy_signal_tabs)
        consensus = ttk.Frame(self.buy_signal_tabs)
        catalysts = ttk.Frame(self.buy_signal_tabs)
        sources = ttk.Frame(self.buy_signal_tabs)
        self.buy_signal_tabs.add(overview, text="Overview")
        self.buy_signal_tabs.add(consensus, text="Consensus & Targets")
        self.buy_signal_tabs.add(catalysts, text="Catalysts & Risk")
        self.buy_signal_tabs.add(sources, text="Sources")

        self.buy_overview_tree = self._make_tree(
            overview,
            ["readiness", "ticker", "action", "conviction", "amount", "price", "consensus", "mean_upside", "catalyst", "warnings"],
            [120, 80, 90, 90, 120, 110, 140, 120, 260, 260],
        )
        self.buy_overview_tree.pack(fill="both", expand=True)

        self.buy_consensus_tree = self._make_tree(
            consensus,
            ["ticker", "readiness", "buy", "hold", "sell", "analysts", "low", "mean", "high", "mean_upside", "source"],
            [80, 120, 70, 70, 70, 90, 100, 100, 100, 120, 260],
        )
        self.buy_consensus_tree.pack(fill="both", expand=True)

        self.buy_catalyst_text = self._readonly_text(catalysts, height=24)
        self.buy_sources_text = self._readonly_text(sources, height=24)

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
        ttk.Button(toolbar, text="Refresh", command=lambda: self.load_report(self.latest_report_path, select_tab=True)).pack(
            side="left", padx=8
        )
        self.report_paths_button = ttk.Button(toolbar, text="Show Search Paths", command=self.toggle_report_paths)
        self.report_paths_button.pack(side="left", padx=8)
        self.report_path_label = ttk.Label(toolbar, text="", style="Muted.TLabel")
        self.report_path_label.pack(side="left", padx=12)
        self._build_search_controls(toolbar, "report", lambda: self.report_text)

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

        search_bar = ttk.Frame(right, style="Panel.TFrame")
        search_bar.pack(fill="x", pady=(0, 10))
        self._build_search_controls(search_bar, "history", lambda: self.history_text)
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

    # ── Learning tab ────────────────────────────────────────────────────────
    def _build_learning_tab(self) -> None:
        """Build the read-only "Learning Loop" tab.

        Mirrors the Streamlit tab: per-horizon edge metrics, sizing
        multipliers table, thesis-verdict heat-map list, and thesis-text
        drift alerts. Pure-render — data is fetched lazily by
        ``refresh_learning_tab`` only when the tab is opened.
        """
        toolbar = ttk.Frame(self.learning_tab)
        toolbar.pack(fill="x", padx=16, pady=(16, 8))
        ttk.Button(toolbar, text="Refresh learning view", command=self.refresh_learning_tab).pack(side="left")
        self.learning_status = tk.StringVar(value="Open this tab to load the learning view.")
        ttk.Label(toolbar, textvariable=self.learning_status, style="Muted.TLabel").pack(side="left", padx=14)

        # Three stacked panels: edge by horizon, sizing-by-conviction, theses.
        edge_panel = self._panel(self.learning_tab, "Your edge by horizon (user_avg_return %)")
        edge_panel.pack(fill="x", padx=16, pady=(0, 12))
        self.learning_edge_text = tk.Text(
            edge_panel,
            height=4,
            wrap="word",
            bg=self.table_bg,
            fg=self.text,
            insertbackground=self.text,
            relief="flat",
        )
        self.learning_edge_text.pack(fill="x")
        self.learning_edge_text.configure(state="disabled")

        sizing_panel = self._panel(self.learning_tab, "Sizing multipliers (Sharpe-dampened)")
        sizing_panel.pack(fill="x", padx=16, pady=(0, 12))
        self.learning_sizing_tree = self._make_tree(
            sizing_panel,
            ["conviction", "n", "avg_return_pct", "hit_rate", "sharpe", "max_drawdown_pct", "sizing_multiplier"],
            [90, 70, 120, 90, 80, 130, 140],
            height=6,
        )
        self.learning_sizing_tree.pack(fill="x")

        # v1.18: Calibration table — does conviction X actually win X*10%?
        calibration_panel = self._panel(self.learning_tab, "Calibration (stated vs realized)")
        calibration_panel.pack(fill="x", padx=16, pady=(0, 12))
        self.learning_calibration_tree = self._make_tree(
            calibration_panel,
            ["conviction", "n", "stated_pct", "realized_pct", "error_pp", "verdict"],
            [90, 70, 100, 110, 90, 160],
            height=5,
        )
        self.learning_calibration_tree.pack(fill="x")
        self.learning_walkforward_var = tk.StringVar(value="Walk-forward stability: not enough samples yet.")
        ttk.Label(
            calibration_panel,
            textvariable=self.learning_walkforward_var,
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(6, 0))

        # Use a paned window so the user can rebalance verdicts vs drift.
        body = ttk.PanedWindow(self.learning_tab, orient="horizontal")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        verdict_panel = self._panel(body, "Active thesis verdicts")
        body.add(verdict_panel, weight=3)
        self.learning_verdict_tree = self._make_tree(
            verdict_panel,
            ["ticker", "entry_date", "days_held", "original_action", "original_conviction", "current_verdict", "reviews"],
            [80, 110, 90, 130, 140, 150, 80],
            height=10,
        )
        self.learning_verdict_tree.pack(fill="both", expand=True)

        drift_panel = self._panel(body, "Thesis-text drift alerts")
        body.add(drift_panel, weight=2)
        self.learning_drift_text = tk.Text(
            drift_panel,
            wrap="word",
            bg=self.table_bg,
            fg=self.text,
            insertbackground=self.text,
            relief="flat",
            padx=8,
            pady=8,
        )
        self.learning_drift_text.pack(fill="both", expand=True)
        self.learning_drift_text.configure(state="disabled")

    def refresh_learning_tab(self) -> None:
        """Fetch a fresh learning_view and re-render every panel."""
        try:
            view = learning_view()
        except Exception as exc:  # noqa: BLE001
            self.learning_status.set(f"Failed to load learning view: {exc}")
            return

        error_count = len(view.get("errors") or [])
        self.learning_status.set(
            f"Loaded {len(view.get('thesis_verdicts') or [])} thesis · "
            f"{len(view.get('edge_by_horizon') or {})} horizons · "
            f"{len(view.get('sharpe_by_conviction') or {})} conviction buckets · "
            f"{len(view.get('thesis_text_drift_alerts') or [])} drift alert(s)" + (f" · {error_count} soft error(s)" if error_count else "")
        )

        # — Edge by horizon —
        edge = view.get("edge_by_horizon") or {}
        if edge:
            parts = []
            for horizon in sorted(int(h) for h in edge.keys()):
                stats = edge[horizon]
                parts.append(
                    f"{horizon}d  user={stats.get('user_avg_return_pct', 0):+.2f}%  "
                    f"model={stats.get('model_avg_return_pct', 0):+.2f}%  "
                    f"hit={stats.get('user_hit_rate', 0):.0%}  "
                    f"(n={stats.get('n', 0)})"
                )
            edge_text = "\n".join(parts)
        else:
            edge_text = "Not enough scored decisions yet. Record at least a few in the Journal tab and re-run."
        self.learning_edge_text.configure(state="normal")
        self.learning_edge_text.delete("1.0", "end")
        self.learning_edge_text.insert("1.0", edge_text)
        self.learning_edge_text.configure(state="disabled")

        # — Sizing-by-conviction —
        sharpe_rows = view.get("sharpe_by_conviction") or {}
        rows = []
        for conv in sorted(sharpe_rows.keys()):
            stats = sharpe_rows[conv]
            rows.append(
                [
                    str(conv),
                    str(stats.get("n", 0)),
                    f"{stats.get('avg_return_pct', 0):+.2f}%",
                    f"{stats.get('hit_rate', 0):.0%}",
                    f"{stats.get('sharpe', 0):+.2f}",
                    f"{stats.get('max_drawdown_pct', 0):+.2f}%",
                    f"{stats.get('sizing_multiplier', 1.0):.2f}×",
                ]
            )
        self._replace_tree_rows(self.learning_sizing_tree, rows)

        # — Calibration (v1.18) —
        calibration_rows = []
        for conv in sorted((view.get("calibration") or {}).keys()):
            bucket = view["calibration"][conv]
            calibration_rows.append(
                [
                    str(conv),
                    str(bucket.get("n", 0)),
                    f"{bucket.get('stated_pct', 0):.0f}%",
                    f"{bucket.get('realized_pct', 0):.1f}%",
                    f"{bucket.get('error_pp', 0):+.1f}",
                    "over-confident" if bucket.get("overconfident") else "well-calibrated",
                ]
            )
        self._replace_tree_rows(self.learning_calibration_tree, calibration_rows)

        # — Walk-forward stability summary line —
        walk = view.get("walk_forward") or []
        if len(walk) >= 2:
            recent_hr = walk[-1].get("hit_rate", 0.0)
            mean_hr = sum(w.get("hit_rate", 0.0) for w in walk) / len(walk)
            delta_pp = (recent_hr - mean_hr) * 100.0
            self.learning_walkforward_var.set(
                f"Walk-forward stability: {len(walk)} windows · latest hit-rate {recent_hr:.0%} vs mean {mean_hr:.0%} ({delta_pp:+.1f}pp)"
            )
        elif walk:
            self.learning_walkforward_var.set(f"Walk-forward stability: {len(walk)} window · not enough to trend yet.")
        else:
            self.learning_walkforward_var.set("Walk-forward stability: needs ≥ 60 matured recommendations.")

        # — Verdict tree —
        verdict_rows = []
        for v in view.get("thesis_verdicts") or []:
            verdict_rows.append(
                [
                    v.get("ticker") or "—",
                    v.get("entry_date") or "—",
                    str(v.get("days_held")) if v.get("days_held") is not None else "—",
                    v.get("original_action") or "—",
                    str(v.get("original_conviction")) if v.get("original_conviction") is not None else "—",
                    (v.get("current_verdict") or "·").replace("_", " "),
                    str(v.get("reviews_count") or 0),
                ]
            )
        self._replace_tree_rows(self.learning_verdict_tree, verdict_rows)

        # — Thesis-text drift alerts —
        alerts = view.get("thesis_text_drift_alerts") or []
        if not alerts:
            drift_msg = "No drift detected — all active theses kept a consistent rationale across the last two sessions."
        else:
            lines = [f"{len(alerts)} alert(s):", ""]
            for alert in alerts:
                lines.append(f"• {alert.get('ticker')}  (similarity {float(alert.get('similarity') or 0):.0%})")
                if alert.get("was_thesis"):
                    lines.append(f"    Was: {alert['was_thesis']}")
                if alert.get("now_thesis"):
                    lines.append(f"    Now: {alert['now_thesis']}")
                lines.append("")
            drift_msg = "\n".join(lines).rstrip()
        self.learning_drift_text.configure(state="normal")
        self.learning_drift_text.delete("1.0", "end")
        self.learning_drift_text.insert("1.0", drift_msg)
        self.learning_drift_text.configure(state="disabled")

    # ── Performance tab ─────────────────────────────────────────────────────
    def _build_performance_tab(self) -> None:
        """Portfolio time-series rebuilt from recommendation-log snapshots (v1.17).

        Matplotlib is intentionally excluded from the PyInstaller bundle, so
        we draw a minimal cumulative-value sparkline directly on a tk.Canvas.
        Numbers go into Treeviews; users who want full plots can use
        Streamlit (``./run.sh 2``).
        """
        toolbar = ttk.Frame(self.performance_tab)
        toolbar.pack(fill="x", padx=16, pady=(16, 8))
        ttk.Button(toolbar, text="Refresh", command=self.refresh_performance_tab).pack(side="left")
        self.performance_lookback_var = tk.StringVar(value="All time")
        ttk.Label(toolbar, text="Lookback", style="Muted.TLabel").pack(side="left", padx=(14, 4))
        lookback_box = ttk.Combobox(
            toolbar,
            textvariable=self.performance_lookback_var,
            values=["All time", "Last 30 days", "Last 90 days", "Last 365 days"],
            state="readonly",
            width=14,
        )
        lookback_box.pack(side="left", padx=(0, 8))
        lookback_box.bind("<<ComboboxSelected>>", lambda _e: self.refresh_performance_tab())
        self.performance_fetch_spy_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            toolbar,
            text="Compare vs SPY",
            variable=self.performance_fetch_spy_var,
            command=self.refresh_performance_tab,
        ).pack(side="left", padx=(0, 8))
        self.performance_status = tk.StringVar(value="Open this tab to load performance metrics.")
        ttk.Label(toolbar, textvariable=self.performance_status, style="Muted.TLabel").pack(side="left", padx=14)

        # Headline metrics row
        metrics_panel = self._panel(self.performance_tab, "Headline metrics")
        metrics_panel.pack(fill="x", padx=16, pady=(0, 12))
        self.performance_metric_vars: dict[str, tk.StringVar] = {}
        grid = ttk.Frame(metrics_panel, style="Panel.TFrame")
        grid.pack(fill="x")
        for i, label in enumerate(
            ["Cumulative return", "Annualized return", "Volatility", "Sharpe", "Max drawdown", "SPY return", "Beta", "Alpha (ann.)"]
        ):
            var = tk.StringVar(value="—")
            self.performance_metric_vars[label] = var
            cell = tk.Frame(grid, bg=self.card, padx=14, pady=10, highlightthickness=1, highlightbackground=self.border)
            cell.grid(row=i // 4, column=i % 4, sticky="ew", padx=4, pady=4)
            grid.columnconfigure(i % 4, weight=1, uniform="perf_metrics")
            tk.Label(cell, text=label.upper(), bg=self.card, fg=self.muted, font=self.fonts["small"]).pack(anchor="w")
            tk.Label(cell, textvariable=var, bg=self.card, fg=self.text_strong, font=self.fonts["heading"]).pack(anchor="w", pady=(4, 0))

        # Sparkline canvas — portfolio (and SPY) rebased to 100 at start.
        chart_panel = self._panel(self.performance_tab, "Portfolio value (rebased to 100 at start)")
        chart_panel.pack(fill="x", padx=16, pady=(0, 12))
        self.performance_canvas = tk.Canvas(
            chart_panel,
            height=160,
            bg=self.table_bg,
            highlightthickness=0,
            bd=0,
        )
        self.performance_canvas.pack(fill="x", expand=True)
        legend = ttk.Frame(chart_panel, style="Panel.TFrame")
        legend.pack(fill="x", pady=(6, 0))
        tk.Label(legend, text="● Portfolio", bg=self.panel, fg=self.accent, font=self.fonts["small"]).pack(side="left", padx=8)
        tk.Label(legend, text="● SPY", bg=self.panel, fg=PALETTE.info, font=self.fonts["small"]).pack(side="left", padx=8)

        # Sector waterfall + return distribution
        body = ttk.PanedWindow(self.performance_tab, orient="horizontal")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        sector_panel = self._panel(body, "Sector contribution (USD change)")
        body.add(sector_panel, weight=3)
        self.performance_sector_tree = self._make_tree(
            sector_panel,
            ["sector", "start_usd", "end_usd", "delta_usd"],
            [180, 110, 110, 110],
            height=8,
        )
        self.performance_sector_tree.pack(fill="both", expand=True)
        dist_panel = self._panel(body, "Return distribution")
        body.add(dist_panel, weight=2)
        self.performance_dist_tree = self._make_tree(
            dist_panel,
            ["return_bucket", "count"],
            [150, 80],
            height=8,
        )
        self.performance_dist_tree.pack(fill="both", expand=True)

    def refresh_performance_tab(self) -> None:
        """Recompute and re-render the Performance tab."""
        lookback_label = self.performance_lookback_var.get()
        lookback_days = {"Last 30 days": 30, "Last 90 days": 90, "Last 365 days": 365}.get(lookback_label)
        fetch_spy = bool(self.performance_fetch_spy_var.get())

        try:
            view = portfolio_performance_summary(lookback_days=lookback_days, fetch_spy=fetch_spy)
        except Exception as exc:  # noqa: BLE001
            self.performance_status.set(f"Failed to compute performance: {exc}")
            return

        if not view.get("ready"):
            self.performance_status.set(view.get("reason") or "Not enough snapshots yet.")
            for var in self.performance_metric_vars.values():
                var.set("—")
            self.performance_canvas.delete("all")
            self._replace_tree_rows(self.performance_sector_tree, [])
            self._replace_tree_rows(self.performance_dist_tree, [])
            return

        spy = view.get("spy") or {}
        self.performance_status.set(
            f"{view['n_snapshots']} sessions · {view['first_ts']} → {view['last_ts']} · "
            f"sessions/year ≈ {view['sessions_per_year']}" + (" · SPY benchmark loaded" if spy.get("available") else "")
        )

        def _pct(value, *, signed=True, digits=2) -> str:
            if value is None:
                return "—"
            fmt = f"{{:{'+' if signed else ''}.{digits}f}}%"
            return fmt.format(value)

        m = self.performance_metric_vars
        m["Cumulative return"].set(_pct(view["cumulative_return_pct"]))
        m["Annualized return"].set(_pct(view["annualized_return_pct"], digits=1))
        m["Volatility"].set(_pct(view["annualized_volatility_pct"], signed=False, digits=1))
        m["Sharpe"].set(f"{view['sharpe']:.2f}")
        m["Max drawdown"].set(_pct(view["max_drawdown_pct"], digits=1))
        m["SPY return"].set(_pct(spy.get("cumulative_return_pct")) if spy.get("available") else "—")
        m["Beta"].set(f"{spy.get('beta'):.2f}" if spy.get("beta") is not None else "—")
        m["Alpha (ann.)"].set(_pct(spy.get("alpha_annualized_pct")) if spy.get("available") else "—")

        # Sparkline
        self._draw_performance_sparkline(view)

        # Sector waterfall
        sector_rows = []
        for row in view.get("sector_waterfall") or []:
            sector_rows.append(
                [
                    row.get("sector"),
                    f"${row.get('start_usd', 0):,.0f}",
                    f"${row.get('end_usd', 0):,.0f}",
                    f"${row.get('delta_usd', 0):+,.0f}",
                ]
            )
        self._replace_tree_rows(self.performance_sector_tree, sector_rows)

        # Return distribution — keep buckets sorted for sensible visual reading
        def _sort_key(label: str) -> tuple:
            if label.startswith("≤"):
                return (-999.0,)
            if label.startswith("≥"):
                return (999.0,)
            try:
                return (float(label.split(" ")[0]),)
            except ValueError:
                return (0.0,)

        dist_rows = sorted((view.get("return_distribution") or {}).items(), key=lambda kv: _sort_key(kv[0]))
        self._replace_tree_rows(self.performance_dist_tree, [[bucket, str(count)] for bucket, count in dist_rows])

    def _draw_performance_sparkline(self, view: dict) -> None:
        canvas = self.performance_canvas
        canvas.delete("all")
        canvas.update_idletasks()
        width = max(canvas.winfo_width(), 600)
        height = max(canvas.winfo_height(), 120)
        padding_x = 18
        padding_y = 14
        usable_w = width - 2 * padding_x
        usable_h = height - 2 * padding_y

        portfolio_values = view.get("values_usd") or []
        if len(portfolio_values) < 2:
            return
        initial = portfolio_values[0]
        portfolio_indexed = [v / initial * 100.0 for v in portfolio_values]

        series_to_draw = [(portfolio_indexed, self.accent)]
        spy = view.get("spy") or {}
        if spy.get("available") and spy.get("values"):
            spy_initial = spy["values"][0]
            if spy_initial > 0:
                series_to_draw.append(([v / spy_initial * 100.0 for v in spy["values"]], PALETTE.info))

        # Shared y-range so both series stay comparable
        all_values = [v for series, _ in series_to_draw for v in series]
        ymin = min(all_values)
        ymax = max(all_values)
        if ymax == ymin:
            ymax = ymin + 1  # avoid div-by-zero on a flat line

        # 100-baseline reference line
        baseline_y = padding_y + usable_h * (1 - (100 - ymin) / (ymax - ymin))
        canvas.create_line(padding_x, baseline_y, width - padding_x, baseline_y, fill=self.border, dash=(2, 4))
        canvas.create_text(padding_x + 4, baseline_y - 8, anchor="w", text="100", fill=self.muted, font=self.fonts["small"])

        # Series
        for series, colour in series_to_draw:
            n = len(series)
            step = usable_w / (n - 1) if n > 1 else 0
            coords = []
            for i, value in enumerate(series):
                x = padding_x + i * step
                y = padding_y + usable_h * (1 - (value - ymin) / (ymax - ymin))
                coords.extend([x, y])
            canvas.create_line(*coords, fill=colour, width=2, smooth=True)

    # ── Schedule tab (v1.18) ────────────────────────────────────────────────
    def _build_schedule_tab(self) -> None:
        """Per-user scheduled-run installer (launchd / Task Scheduler / cron)."""
        toolbar = ttk.Frame(self.schedule_tab)
        toolbar.pack(fill="x", padx=16, pady=(16, 8))
        ttk.Button(toolbar, text="Refresh", command=self.refresh_schedule_tab).pack(side="left")
        ttk.Button(toolbar, text="Send test notification", command=self._send_test_notification).pack(side="left", padx=(8, 0))
        self.schedule_status = tk.StringVar(value="Open this tab to inspect or install the schedule.")
        ttk.Label(toolbar, textvariable=self.schedule_status, style="Muted.TLabel").pack(side="left", padx=14)

        current_panel = self._panel(self.schedule_tab, "Current schedule")
        current_panel.pack(fill="x", padx=16, pady=(0, 12))
        self.schedule_current_tree = self._make_tree(
            current_panel,
            ["hour", "minute", "session_type"],
            [80, 80, 140],
            height=4,
        )
        self.schedule_current_tree.pack(fill="x")
        self.schedule_path_var = tk.StringVar(value="Backend: — · file: —")
        ttk.Label(current_panel, textvariable=self.schedule_path_var, style="Muted.TLabel").pack(anchor="w", pady=(6, 0))
        button_row = ttk.Frame(current_panel)
        button_row.pack(fill="x", pady=(8, 0))
        ttk.Button(button_row, text="Uninstall schedule", command=self._uninstall_schedule_clicked).pack(side="left")

        # Slot pickers
        new_panel = self._panel(self.schedule_tab, "New schedule")
        new_panel.pack(fill="x", padx=16, pady=(0, 12))
        self.schedule_slots: list[dict] = []  # filled below; each {enabled, hour, minute, session}
        grid = ttk.Frame(new_panel)
        grid.pack(fill="x")
        for col, defaults in enumerate(
            [
                {"label": "Morning", "enabled": True, "hour": 7, "minute": 0, "session": "morning"},
                {"label": "Midday", "enabled": False, "hour": 11, "minute": 0, "session": "morning"},
                {"label": "Afternoon", "enabled": True, "hour": 14, "minute": 0, "session": "afternoon"},
            ]
        ):
            cell = ttk.Frame(grid, padding=8)
            cell.grid(row=0, column=col, sticky="ew", padx=4)
            grid.columnconfigure(col, weight=1, uniform="schedule_slots")
            enabled = tk.BooleanVar(value=defaults["enabled"])
            hour = tk.IntVar(value=defaults["hour"])
            minute = tk.IntVar(value=defaults["minute"])
            ttk.Checkbutton(cell, text=f"{defaults['label']} run", variable=enabled).pack(anchor="w")
            time_row = ttk.Frame(cell)
            time_row.pack(fill="x", pady=(6, 0))
            ttk.Label(time_row, text="Hour", style="Muted.TLabel").pack(side="left")
            ttk.Spinbox(time_row, from_=0, to=23, textvariable=hour, width=4).pack(side="left", padx=4)
            ttk.Label(time_row, text="Minute", style="Muted.TLabel").pack(side="left")
            ttk.Spinbox(time_row, from_=0, to=59, textvariable=minute, width=4).pack(side="left", padx=4)
            self.schedule_slots.append({"enabled": enabled, "hour": hour, "minute": minute, "session": defaults["session"]})

        action_row = ttk.Frame(new_panel)
        action_row.pack(fill="x", pady=(10, 0))
        ttk.Button(action_row, text="Install schedule", command=self._install_schedule_clicked).pack(side="left")
        ttk.Label(action_row, text="No sudo required.", style="Muted.TLabel").pack(side="left", padx=14)

        preview_panel = self._panel(self.schedule_tab, "Preview (artefact body)")
        preview_panel.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.schedule_preview_text = tk.Text(
            preview_panel,
            wrap="none",
            bg=self.table_bg,
            fg=self.text,
            insertbackground=self.text,
            relief="flat",
        )
        self.schedule_preview_text.pack(fill="both", expand=True)
        self.schedule_preview_text.configure(state="disabled")

    def _selected_schedule_times(self) -> list:
        from src.scheduling import ScheduleTime

        out = []
        for slot in self.schedule_slots:
            if not slot["enabled"].get():
                continue
            out.append(
                ScheduleTime(
                    hour=int(slot["hour"].get()),
                    minute=int(slot["minute"].get()),
                    session_type=slot["session"],
                )
            )
        return out

    def refresh_schedule_tab(self) -> None:
        from src.scheduling import current_schedule, preview_schedule

        try:
            current = current_schedule()
        except Exception as exc:  # noqa: BLE001
            self.schedule_status.set(f"Could not inspect: {exc}")
            return

        if current.installed:
            rows = [[f"{t.hour:02d}", f"{t.minute:02d}", t.session_type] for t in current.times]
            self._replace_tree_rows(self.schedule_current_tree, rows)
            self.schedule_path_var.set(f"Backend: {current.backend} · file: {current.path}")
            self.schedule_status.set(f"Schedule installed via {current.backend}.")
        else:
            self._replace_tree_rows(self.schedule_current_tree, [])
            self.schedule_path_var.set(f"Backend: {current.backend} · no schedule installed.")
            self.schedule_status.set("No schedule installed.")

        # Preview using the live picker values
        times = self._selected_schedule_times()
        if times:
            backend, body = preview_schedule(times)
            preview = f"# {backend} artefact preview\n\n{body}"
        else:
            preview = "Enable at least one slot to preview the schedule."
        self.schedule_preview_text.configure(state="normal")
        self.schedule_preview_text.delete("1.0", "end")
        self.schedule_preview_text.insert("1.0", preview)
        self.schedule_preview_text.configure(state="disabled")

    def _install_schedule_clicked(self) -> None:
        from src.scheduling import install_schedule

        times = self._selected_schedule_times()
        if not times:
            messagebox.showwarning("No slots selected", "Enable at least one slot before installing.")
            return
        result = install_schedule(times)
        if result.ok:
            messagebox.showinfo("Schedule installed", f"{result.message}\n\nBackend: {result.backend}\n{result.path}")
        else:
            messagebox.showerror("Install failed", result.message + (f"\n\n{result.error}" if result.error else ""))
        self.refresh_schedule_tab()

    def _uninstall_schedule_clicked(self) -> None:
        from src.scheduling import uninstall_schedule

        result = uninstall_schedule()
        if result.ok:
            messagebox.showinfo("Schedule removed", result.message)
        else:
            messagebox.showerror("Uninstall failed", result.message)
        self.refresh_schedule_tab()

    def _send_test_notification(self) -> None:
        from src.notifications import send

        result = send(
            "tech_stock test",
            "If you see this, native notifications are working.",
            channel="general",
        )
        if result.sent:
            self.schedule_status.set(f"Test notification sent via {result.backend}.")
        elif result.deduped:
            self.schedule_status.set("Dedup window suppressed — try again in a few seconds.")
        else:
            self.schedule_status.set(f"Notification failed: {result.error or 'no backend'}")

    # ── Diagnostics tab ─────────────────────────────────────────────────────
    def _build_diagnostics_tab(self) -> None:
        """Surface the structured-log Diagnostics view (v1.17).

        Mirrors the Streamlit tab: per-source health table, recent-error
        list, copyable support bundle. All data comes from
        ``user_workspace()/logs/diagnostics.jsonl`` via ui_support.
        """
        toolbar = ttk.Frame(self.diagnostics_tab)
        toolbar.pack(fill="x", padx=16, pady=(16, 8))
        ttk.Button(toolbar, text="Refresh", command=self.refresh_diagnostics_tab).pack(side="left")
        self.diagnostics_window_var = tk.StringVar(value="24")
        ttk.Label(toolbar, text="Window", style="Muted.TLabel").pack(side="left", padx=(14, 4))
        window_box = ttk.Combobox(
            toolbar,
            textvariable=self.diagnostics_window_var,
            values=["1", "6", "24", "72", "168"],
            state="readonly",
            width=5,
        )
        window_box.pack(side="left", padx=(0, 4))
        window_box.bind("<<ComboboxSelected>>", lambda _e: self.refresh_diagnostics_tab())
        ttk.Label(toolbar, text="hours", style="Muted.TLabel").pack(side="left")
        self.diagnostics_status = tk.StringVar(value="Open this tab to load the diagnostics view.")
        ttk.Label(toolbar, textvariable=self.diagnostics_status, style="Muted.TLabel").pack(side="left", padx=14)

        # Per-source table
        sources_panel = self._panel(self.diagnostics_tab, "Sources")
        sources_panel.pack(fill="x", padx=16, pady=(0, 12))
        self.diagnostics_sources_tree = self._make_tree(
            sources_panel,
            ["source", "health", "total", "errors", "success_rate", "last_error_code", "last_error_message"],
            [130, 100, 80, 80, 110, 160, 360],
            height=7,
        )
        self.diagnostics_sources_tree.pack(fill="x")

        # Recent errors table
        errors_panel = self._panel(self.diagnostics_tab, "Recent error events")
        errors_panel.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        self.diagnostics_errors_tree = self._make_tree(
            errors_panel,
            ["when", "source", "level", "code", "message"],
            [160, 120, 80, 140, 480],
            height=10,
        )
        self.diagnostics_errors_tree.pack(fill="both", expand=True)

        # Support bundle
        bundle_panel = self._panel(self.diagnostics_tab, "Support bundle (redacted)")
        bundle_panel.pack(fill="x", padx=16, pady=(0, 16))
        bundle_buttons = ttk.Frame(bundle_panel)
        bundle_buttons.pack(fill="x", pady=(0, 6))
        ttk.Button(bundle_buttons, text="Copy to clipboard", command=self._copy_diagnostics_bundle).pack(side="left")
        ttk.Button(bundle_buttons, text="Open log folder", command=self._open_diagnostics_log_folder).pack(side="left", padx=8)
        self.diagnostics_bundle_text = tk.Text(
            bundle_panel,
            height=8,
            wrap="none",
            bg=self.table_bg,
            fg=self.text,
            insertbackground=self.text,
            relief="flat",
        )
        self.diagnostics_bundle_text.pack(fill="x")
        self.diagnostics_bundle_text.configure(state="disabled")

    def refresh_diagnostics_tab(self) -> None:
        """Fetch a fresh diagnostics_view and re-render every panel."""
        try:
            hours = int(self.diagnostics_window_var.get() or "24")
        except ValueError:
            hours = 24
        try:
            view = diagnostics_view(hours=hours)
        except Exception as exc:  # noqa: BLE001
            self.diagnostics_status.set(f"Failed to load diagnostics: {exc}")
            return

        sources = view.get("sources") or {}
        ok = sum(1 for b in sources.values() if b.get("health") == "ok")
        degraded = sum(1 for b in sources.values() if b.get("health") == "degraded")
        down = sum(1 for b in sources.values() if b.get("health") == "down")
        self.diagnostics_status.set(
            f"{view.get('total_events', 0)} events in last {hours}h · "
            f"{len(sources)} source(s) · {ok} ok · {degraded} degraded · {down} down"
        )

        # — Sources table —
        source_rows = []
        for name in sorted(sources):
            bucket = sources[name]
            rate = bucket.get("success_rate")
            rate_str = "n/a" if rate is None else f"{rate:.0%}"
            last_error = bucket.get("last_error") or {}
            source_rows.append(
                [
                    name,
                    (bucket.get("health") or "idle").upper(),
                    str(bucket.get("total", 0)),
                    str(bucket.get("errors", 0)),
                    rate_str,
                    last_error.get("code") or "",
                    (last_error.get("message") or "")[:200],
                ]
            )
        self._replace_tree_rows(self.diagnostics_sources_tree, source_rows)

        # — Recent errors table —
        error_rows = []
        for event in view.get("recent_errors") or []:
            error_rows.append(
                [
                    event.get("ts") or "",
                    event.get("source") or "",
                    (event.get("level") or "").upper(),
                    event.get("code") or "",
                    (event.get("message") or "")[:300],
                ]
            )
        self._replace_tree_rows(self.diagnostics_errors_tree, error_rows)

        # — Support bundle —
        bundle = diagnostics_support_bundle(limit=200)
        self.diagnostics_bundle_text.configure(state="normal")
        self.diagnostics_bundle_text.delete("1.0", "end")
        self.diagnostics_bundle_text.insert("1.0", bundle or "(no events yet)")
        self.diagnostics_bundle_text.configure(state="disabled")
        # Stash the path for the "Open log folder" button
        self._diagnostics_log_path = Path(view.get("log_path") or "")

    def _copy_diagnostics_bundle(self) -> None:
        """Copy the redacted support bundle to the clipboard."""
        try:
            bundle = diagnostics_support_bundle(limit=500)
            self.clipboard_clear()
            self.clipboard_append(bundle)
            self.update_idletasks()
            self.diagnostics_status.set("Support bundle copied to clipboard.")
        except Exception as exc:  # noqa: BLE001
            self.diagnostics_status.set(f"Copy failed: {exc}")

    def _open_diagnostics_log_folder(self) -> None:
        log_path = getattr(self, "_diagnostics_log_path", None)
        if log_path and log_path.exists():
            self._reveal_in_finder(log_path)

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

        manager = self._panel(self.health_tab, "API Key Manager")
        manager.pack(fill="x", padx=16, pady=(0, 16))
        self.api_key_options = {f"{field['label']} ({field['env']})": field["env"] for field in API_KEY_FIELDS}
        self.api_key_choice = tk.StringVar(value=next(iter(self.api_key_options)))
        self.api_key_value = tk.StringVar()
        self.api_key_manager_status = tk.StringVar(value="")

        row = ttk.Frame(manager, style="Panel.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="Key", background=self.panel, foreground=self.muted).pack(side="left")
        key_combo = ttk.Combobox(
            row,
            textvariable=self.api_key_choice,
            values=list(self.api_key_options),
            state="readonly",
            width=34,
        )
        key_combo.pack(side="left", padx=(8, 12))
        key_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_api_key_manager())
        ttk.Label(row, text="New value", background=self.panel, foreground=self.muted).pack(side="left")
        ttk.Entry(row, textvariable=self.api_key_value, show="*", width=44).pack(side="left", padx=(8, 12))
        ttk.Button(row, text="Save / Update", command=self.save_selected_api_key).pack(side="left")
        ttk.Button(row, text="Delete", command=self.delete_selected_api_key).pack(side="left", padx=(8, 0))
        ttk.Label(manager, textvariable=self.api_key_manager_status, background=self.panel, foreground=self.muted).pack(
            anchor="w", pady=(8, 0)
        )

        self.api_key_tree = self._make_tree(
            manager,
            ["api", "configured", "masked_value", "source"],
            [170, 110, 180, 760],
            height=7,
        )
        self.api_key_tree.pack(fill="x", pady=(10, 0))
        self.refresh_api_key_manager()

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

    def _selected_api_env_name(self) -> str:
        return self.api_key_options.get(self.api_key_choice.get()) or API_KEY_FIELDS[0]["env"]

    def refresh_api_key_manager(self) -> None:
        rows = []
        selected_env = self._selected_api_env_name()
        selected_status = ""
        for row in api_key_inventory():
            source = row.get("source_path")
            source_text = str(source) if source else ""
            rows.append([row["label"], "YES" if row["configured"] else "NO", row.get("masked") or "", source_text])
            if row["env"] == selected_env:
                selected_status = (
                    f"Current {row['label']}: {row.get('masked') or 'not configured'}{' from ' + source_text if source_text else ''}"
                )
        self._replace_tree_rows(self.api_key_tree, rows)
        self.api_key_value.set("")
        self.api_key_manager_status.set(selected_status or "Select an API key to update.")
        if hasattr(self, "api_paths_text"):
            self.refresh_api_paths_text()

    def save_selected_api_key(self) -> None:
        env_name = self._selected_api_env_name()
        value = self.api_key_value.get().strip()
        if not value:
            messagebox.showerror("Missing API key", "Paste the full new API key value before saving.")
            return
        try:
            path = save_api_key(env_name, value)
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))
            return
        self.api_key_manager_status.set(f"Saved {env_name} to {path}")
        self.refresh_api_key_manager()

    def delete_selected_api_key(self) -> None:
        env_name = self._selected_api_env_name()
        if not messagebox.askyesno("Delete API key", f"Remove {env_name} from all discovered API key files?"):
            return
        try:
            touched = delete_api_key(env_name)
        except Exception as exc:
            messagebox.showerror("Delete failed", str(exc))
            return
        detail = ", ".join(str(path) for path in touched) if touched else "no files contained this key"
        self.api_key_manager_status.set(f"Deleted {env_name}: {detail}")
        self.refresh_api_key_manager()

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
        lines.extend(
            [
                "",
                "Data preservation:",
                "- Reports, CSV outputs, JSON logs, API keys, config, uploads, and decision journals are stored in the app workspace.",
                "- Updating replaces only the application files, not the workspace.",
            ]
        )
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

    def _build_search_controls(self, parent: tk.Widget, key: str, get_widget: Any) -> None:
        query = tk.StringVar()
        status = tk.StringVar(value="Search")
        state: dict[str, Any] = {
            "query": query,
            "status": status,
            "matches": [],
            "current": -1,
            "last_query": "",
            "truncated": False,
            "get_widget": get_widget,
        }
        self.search_state[key] = state

        frame = ttk.Frame(parent)
        frame.pack(side="right")
        ttk.Label(frame, text="Search", style="Muted.TLabel").pack(side="left", padx=(0, 6))
        entry = ttk.Entry(frame, textvariable=query, width=24)
        entry.pack(side="left")
        state["entry"] = entry
        ttk.Button(frame, text="Find", command=lambda: self._run_search(key, direction=1)).pack(side="left", padx=(6, 0))
        ttk.Button(frame, text="Previous", command=lambda: self._run_search(key, direction=-1)).pack(side="left", padx=(4, 0))
        ttk.Button(frame, text="Next", command=lambda: self._run_search(key, direction=1)).pack(side="left", padx=(4, 0))
        ttk.Button(frame, text="Clear", command=lambda: self._clear_search_highlights(key)).pack(side="left", padx=(4, 0))
        ttk.Label(frame, textvariable=status, style="Muted.TLabel").pack(side="left", padx=(8, 0))

        entry.bind("<Return>", lambda _event: self._entry_search(key, direction=1))
        entry.bind("<Shift-Return>", lambda _event: self._entry_search(key, direction=-1))
        query.trace_add("write", lambda *_args: self._mark_search_query_dirty(key))

    def _entry_search(self, key: str, *, direction: int) -> str:
        self._run_search(key, direction=direction)
        return "break"

    def focus_active_search(self, _event: object | None = None) -> str:
        selected = self.tabs.select()
        tab_text = self.tabs.tab(selected, "text") if selected else ""
        if tab_text == "History":
            key = "history"
        else:
            key = "report"
            if tab_text != "Report Viewer":
                self.tabs.select(self.report_tab)
        state = self.search_state.get(key)
        entry = state.get("entry") if state else None
        if entry:
            entry.focus_set()
            entry.selection_range(0, "end")
        return "break"

    def _search_text_widget(self, key: str) -> tk.Text | None:
        state = self.search_state.get(key)
        if not state:
            return None
        try:
            widget = state["get_widget"]()
        except (AttributeError, tk.TclError):
            return None
        return widget if isinstance(widget, tk.Text) else None

    def _refresh_search_after_text_change(self, key: str) -> None:
        state = self.search_state.get(key)
        if not state:
            return
        self._reset_search_state(key)
        if state["query"].get().strip():
            state["status"].set("Press Enter")
        else:
            state["status"].set("Search")

    def _mark_search_query_dirty(self, key: str) -> None:
        state = self.search_state.get(key)
        if not state:
            return
        self._reset_search_state(key)
        state["status"].set("Press Enter" if state["query"].get().strip() else "Search")

    def _reset_search_state(self, key: str) -> None:
        state = self.search_state.get(key)
        if not state:
            return
        widget = self._search_text_widget(key)
        if widget:
            widget.tag_remove("search_match", "1.0", "end")
            widget.tag_remove("search_current", "1.0", "end")
        state["matches"] = []
        state["current"] = -1
        state["last_query"] = ""
        state["truncated"] = False

    def _clear_search_highlights(self, key: str, *, clear_query: bool = True) -> None:
        state = self.search_state.get(key)
        if not state:
            return
        self._reset_search_state(key)
        if clear_query and state["query"].get():
            state["query"].set("")
        state["status"].set("Search")

    def _run_search(self, key: str, *, direction: int) -> None:
        state = self.search_state.get(key)
        if not state:
            return
        query = state["query"].get()
        if not query.strip():
            self._clear_search_highlights(key, clear_query=False)
            return
        if query != state.get("last_query") or not state.get("matches"):
            self._collect_search_matches(key, query)
        matches: list[tuple[str, str]] = state.get("matches", [])
        if not matches:
            state["status"].set("0 matches")
            return
        current = int(state.get("current", -1))
        if current == -1:
            current = len(matches) - 1 if direction < 0 else 0
        else:
            current = (current + direction) % len(matches)
        self._select_search_match(key, current)

    def _collect_search_matches(self, key: str, query: str) -> None:
        state = self.search_state.get(key)
        widget = self._search_text_widget(key)
        if not state or not widget:
            return
        widget.tag_remove("search_match", "1.0", "end")
        widget.tag_remove("search_current", "1.0", "end")
        text = widget.get("1.0", "end-1c")
        offsets, truncated = find_search_offsets(text, query)
        matches: list[tuple[str, str]] = []
        for start_offset, end_offset in offsets:
            index = f"1.0+{start_offset}c"
            end = f"1.0+{end_offset}c"
            matches.append((index, end))
            widget.tag_add("search_match", index, end)
        widget.tag_raise("search_match")
        widget.tag_raise("search_current")
        state["matches"] = matches
        state["current"] = -1
        state["last_query"] = query
        state["truncated"] = truncated
        suffix = "+" if truncated else ""
        state["status"].set(f"0/{len(matches)}{suffix}" if matches else "0 matches")

    def _select_search_match(self, key: str, match_index: int) -> None:
        state = self.search_state.get(key)
        widget = self._search_text_widget(key)
        if not state or not widget:
            return
        matches: list[tuple[str, str]] = state.get("matches", [])
        if not matches:
            return
        widget.tag_remove("search_current", "1.0", "end")
        start, end = matches[match_index]
        widget.tag_add("search_current", start, end)
        widget.tag_raise("search_current")
        widget.see(start)
        state["current"] = match_index
        suffix = "+" if state.get("truncated") else ""
        state["status"].set(f"{match_index + 1}/{len(matches)}{suffix}")

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
        widget.tag_configure(
            "table", font=mono_font, background="#e5e7eb", foreground="#111827", lmargin1=10, lmargin2=10, spacing1=1, spacing3=1
        )
        widget.tag_configure(
            "table_header", font=("Menlo", 12, "bold"), background="#d1d5db", foreground="#111827", lmargin1=10, lmargin2=10
        )
        widget.tag_configure("rule", foreground="#94a3b8", spacing1=6, spacing3=6)
        widget.tag_configure("search_match", background="#fde68a", foreground="#111827")
        widget.tag_configure("search_current", background="#fb923c", foreground="#111827")

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
        tree.tag_configure("TRADE READY", foreground=self.good)
        tree.tag_configure("REVIEW FIRST", foreground=self.warning)
        tree.tag_configure("BLOCKED", foreground=self.danger)
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
            f"{row.get('ticker')}: {row.get('quantity')} @ {row.get('market_price')} {row.get('currency')}" for row in rows[:12]
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
                f"The app found this Holdings CSV:\n\n{holdings}\n\nIs this the correct file?",
            )
            if not keep:
                self.browse_csv(self.holdings_var)

        activities = self.activities_var.get().strip()
        if activities:
            keep = messagebox.askyesno(
                "Confirm Activities CSV",
                f"The app found this Activities CSV:\n\n{activities}\n\nIs this the correct file?",
            )
            if not keep:
                replace = messagebox.askyesno(
                    "Activities CSV",
                    "Do you want to choose a different Activities CSV?\n\nChoose No to run without activities.",
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
                elif kind == "buy_signals_done":
                    self._buy_signals_done(payload)
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
        self.start_buy_signal_refresh()

    def start_buy_signal_refresh(self) -> None:
        if not hasattr(self, "buy_signal_button"):
            return
        self.buy_signal_button.configure(state="disabled")
        self.buy_signal_status.set("Refreshing buy signals from source data...")
        action_filter = self._buy_action_filter_value()
        readiness_filter = self._buy_readiness_filter_value()

        def worker() -> None:
            self.progress_queue.put(
                (
                    "buy_signals_done",
                    buy_signal_view(action_filter=action_filter, readiness_filter=readiness_filter),
                )
            )

        threading.Thread(target=worker, daemon=True).start()

    def _buy_action_filter_value(self) -> str:
        value = getattr(self, "buy_action_filter", tk.StringVar(value="All actions")).get()
        return {
            "BUY/ADD": "buy_add",
            "add_on_dip": "add_on_dip",
        }.get(value, "all")

    def _buy_readiness_filter_value(self) -> str:
        value = getattr(self, "buy_readiness_filter", tk.StringVar(value="All readiness")).get()
        return {
            "Trade Ready": "TRADE_READY",
            "Review First": "REVIEW_FIRST",
            "Blocked": "BLOCKED",
        }.get(value, "all")

    def _buy_signals_done(self, payload: dict[str, Any]) -> None:
        self.buy_signal_button.configure(state="normal")
        if payload.get("error"):
            self.buy_signal_status.set(payload["error"])
            self._replace_tree_rows(self.buy_overview_tree, [])
            self._replace_tree_rows(self.buy_consensus_tree, [])
            self._set_readonly_text(self.buy_catalyst_text, payload["error"])
            self._set_readonly_text(self.buy_sources_text, payload["error"])
            return
        candidates = payload.get("cards") or payload.get("candidates") or []
        counts = payload.get("counts") or {}
        self.buy_signal_status.set(
            f"{len(candidates)} shown / {counts.get('total', len(candidates))} total "
            f"({counts.get('TRADE_READY', 0)} ready, {counts.get('REVIEW_FIRST', 0)} review, {counts.get('BLOCKED', 0)} blocked) "
            f"from {payload.get('session_file', 'latest log')}"
        )
        overview_rows = []
        consensus_rows = []
        catalyst_lines = []
        source_lines = [
            f"Session log: {payload.get('session_file', '')}",
            f"Fetched at: {payload.get('fetched_at', '')}",
            "",
            "Active enrichment sources:",
            ", ".join(payload.get("sources_active") or ["none reported"]),
            "",
        ]
        for item in candidates:
            ticker = item.get("ticker") or ""
            targets = item.get("price_targets") or {}
            analyst = item.get("analyst_consensus") or {}
            readiness = item.get("readiness") or {}
            warnings = item.get("quality_warnings") or []
            amount = item.get("action_amount")
            amount_currency = item.get("action_amount_currency") or "USD"
            amount_text = f"{self._fmt_money(amount)} {amount_currency}" if amount else ""
            overview_rows.append(
                [
                    readiness.get("label") or "N/A",
                    ticker,
                    item.get("action") or item.get("hold_tier") or "",
                    item.get("conviction"),
                    amount_text,
                    self._fmt_price(item.get("current_price")),
                    analyst.get("consensus_label") or "N/A",
                    self._fmt_pct(targets.get("mean_upside_pct"), signed=True),
                    self._trim_text(item.get("catalyst_source") or "N/A", 80),
                    "; ".join(w.get("code", "") for w in warnings[:3]) or "none",
                ]
            )
            consensus_rows.append(
                [
                    ticker,
                    readiness.get("label") or "N/A",
                    analyst.get("buy", "N/A"),
                    analyst.get("hold", "N/A"),
                    analyst.get("sell", "N/A"),
                    targets.get("analyst_count") or analyst.get("total_analysts") or "N/A",
                    self._fmt_price(targets.get("low")),
                    self._fmt_price(targets.get("mean")),
                    self._fmt_price(targets.get("high")),
                    self._fmt_pct(targets.get("mean_upside_pct"), signed=True),
                    targets.get("source") or "N/A",
                ]
            )
            catalyst_lines.extend(self._format_buy_signal_detail(item))
            source_lines.append(f"{ticker}:")
            for note in item.get("source_notes") or []:
                source_lines.append(f"  - {note}")
        degradation = payload.get("degradation") or []
        if degradation:
            source_lines.extend(["", "Data coverage warnings:"])
            for row in degradation[:12]:
                ticker = f"{row.get('ticker')}: " if row.get("ticker") else ""
                source_lines.append(f"  - {ticker}{row.get('source')}.{row.get('operation')} unavailable ({row.get('error')})")

        self._replace_tree_rows(self.buy_overview_tree, overview_rows, tag_index=0)
        self._replace_tree_rows(self.buy_consensus_tree, consensus_rows)
        self._set_readonly_text(self.buy_catalyst_text, "\n".join(catalyst_lines) or "No buy signal candidates found.")
        self._set_readonly_text(self.buy_sources_text, "\n".join(source_lines))

    def _format_buy_signal_detail(self, item: dict[str, Any]) -> list[str]:
        ticker = item.get("ticker") or ""
        lines = [f"{ticker} — {item.get('action') or item.get('hold_tier') or ''} | conviction {item.get('conviction')}", "-" * 78]
        readiness = item.get("readiness") or {}
        if readiness:
            lines.append(f"Readiness: {readiness.get('label')} — {'; '.join(readiness.get('reasons') or [])}")
        catalyst = item.get("catalyst_source") or "No catalyst source recorded in latest report."
        lines.append(f"Catalyst: {catalyst}")
        lines.append(f"Verified: {item.get('catalyst_verified')} | Manual review: {item.get('manual_review_required')}")
        lines.append(
            f"Quote: {self._fmt_price(item.get('current_price'))} | {item.get('quote_source') or 'unavailable'} | {item.get('quote_timestamp_utc') or 'missing timestamp'}"
        )
        technical = item.get("technical") or {}
        lines.append(
            "Technical: "
            f"RSI {technical.get('rsi_14', 'N/A')} | "
            f"MACD hist {technical.get('macd_hist', 'N/A')} | "
            f"ATR {self._fmt_pct(technical.get('atr_pct_of_price'))} | "
            f"20d vol {self._fmt_pct(technical.get('volatility_20d_pct'))}"
        )
        insider = item.get("insider_activity") or {}
        if insider:
            lines.append(
                "Insider activity: "
                f"{insider.get('signal', 'N/A')} | buys {insider.get('buys', 'N/A')} / "
                f"sells {insider.get('sells', 'N/A')} | net {insider.get('net_shares', 'N/A')}"
            )
        earnings = item.get("upcoming_earnings") or {}
        if earnings.get("date"):
            lines.append(f"Next earnings: {earnings.get('date')} {earnings.get('hour') or ''} | EPS est {earnings.get('eps_estimate')}")
        rating_changes = item.get("latest_rating_changes") or []
        if rating_changes:
            lines.append("Recent rating changes:")
            for row in rating_changes[:4]:
                lines.append(
                    f"  - {str(row.get('date') or '')[:10]} {row.get('firm') or 'unknown firm'}: "
                    f"{row.get('from_grade') or 'N/A'} -> {row.get('to_grade') or 'N/A'} ({row.get('action') or 'rating change'})"
                )
        news = item.get("news") or []
        if news:
            summary = item.get("news_summary") or {}
            lines.append(
                f"Recent news sentiment: avg {summary.get('avg_sentiment', 0):+.2f}; "
                f"{summary.get('bullish_count', 0)} bullish / {summary.get('neutral_count', 0)} neutral / "
                f"{summary.get('bearish_count', 0)} bearish"
            )
            for article in news[:3]:
                lines.append(f"  - {article.get('published_at', '')} {article.get('title', '')} ({article.get('publisher', '')})")
        warnings = item.get("quality_warnings") or []
        if warnings:
            lines.append("Quality warnings:")
            for warning in warnings[:4]:
                lines.append(
                    f"  - {warning.get('severity', '').upper()} {warning.get('code')}: {warning.get('action_required') or warning.get('message')}"
                )
        lines.append(f"Risk/invalidation: {item.get('risk_or_invalidation') or 'N/A'}")
        lines.append("")
        return lines

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
                lines.append(
                    f"- {row.get('ticker')}: {row.get('drift_type')} ({was.get('action', 'new')} -> {now.get('action', 'dropped')})"
                )
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
                lines.append(
                    f"- {ticker}: {row.get('current_price', 'N/A')} | 5d {self._fmt_pct(row.get('change_pct_5d'), signed=True)} | 1mo {self._fmt_pct(row.get('change_pct_21d'), signed=True)}"
                )
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

    def _wrapped_dashboard_label(
        self, parent: tk.Widget, text: str, *, bg: str, fg: str, font: tuple[str, int, str] | tuple[str, int] = ("Helvetica", 11)
    ) -> tk.Label:
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
        # Keep the header status pill in lock-step with the dashboard.
        if hasattr(self, "header_status_var"):
            self._update_header_status()
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
        self._set_metric(
            "Portfolio", self._fmt_money(health.get("total_value_usd_equivalent") or risk.get("total_value_usd")), "USD equivalent"
        )
        self._set_metric("P&L", self._fmt_pct(health.get("overall_pnl_pct"), signed=True), "overall")
        self._set_metric("SPY Beta", str(beta.get("SPY", "N/A")), f"QQQ {beta.get('QQQ', 'N/A')} | SMH {beta.get('SMH', 'N/A')}")
        self._set_metric(
            "Annual Vol",
            f"{risk.get('annualized_volatility_pct', 0):.1f}%",
            f"max DD {self._fmt_pct(risk.get('max_drawdown_estimate_pct'), signed=True)}",
        )
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
            self._refresh_search_after_text_change("report")
            if select_tab:
                self.tabs.select(self.report_tab)
            return
        self.report_path_label.configure(text=relative_to_root(path))
        self._render_markdown(self.report_text, text)
        self._refresh_search_after_text_change("report")
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
        self._refresh_search_after_text_change("history")

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
        self.refresh_api_key_manager()
        self._replace_tree_rows(self.health_tree, [])

        def worker() -> None:
            self.progress_queue.put(("health_done", api_health_view()))

        threading.Thread(target=worker, daemon=True).start()

    def _connectivity_done(self, payload: Any) -> None:
        rows = payload.get("checks", []) if isinstance(payload, dict) else payload
        if isinstance(payload, dict):
            self.health_status.set(
                f"Connectivity check complete. {payload.get('ok_count', 0)} OK / {payload.get('fail_count', 0)} unavailable. "
                f"Storage: {payload.get('storage_mode', 'API_KEYS.txt / .env files')}"
            )
        else:
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
