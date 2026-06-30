"""
Embedded desktop UI for tech_stock.

This is a native Tkinter application. It deliberately reuses src.ui_support
instead of duplicating portfolio/report logic, so the CLI, Streamlit, Textual,
and desktop app all run the same report pipeline.
"""

from __future__ import annotations

import logging
import os
import queue
import re
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont
from tkinter.scrolledtext import ScrolledText
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.performance_history import portfolio_performance_summary
from src.ui_support import (
    API_KEY_FIELDS,
    EDITABLE_JSON_FILES,
    api_health_view,
    api_key_inventory,
    api_key_locations,
    app_data_locations,
    app_self_test_view,
    apply_available_update,
    buy_signal_view,
    check_update_available,
    csv_choice_view,
    current_app_version,
    data_files_view,
    default_run_settings,
    delete_api_key,
    demo_smoke_view,
    diagnostics_support_bundle,
    diagnostics_view,
    export_support_bundle,
    find_default_csvs,
    latest_log_summary,
    latest_report,
    learning_view,
    list_reports,
    outcomes_view,
    paid_run_readiness_view,
    pre_run_checklist_view,
    preview_holdings_csv,
    read_editable_json,
    read_text_file,
    relative_to_root,
    report_history_view,
    report_locations,
    report_review_view,
    run_report_from_ui,
    save_api_key,
    save_decision_from_ui,
    save_execution_checklist_from_ui,
    save_selected_data_files,
    setup_readiness_view,
    source_provenance_view,
    support_bundle_preview,
    validate_json_text,
    write_editable_json,
)

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


class _Tooltip:
    """Hover tooltip for any Tkinter widget."""

    _DELAY_MS = 400

    def __init__(self, widget: tk.Widget, text: str, *, bg: str = "", fg: str = "", outline: str = "") -> None:
        self.widget = widget
        self.text = text
        self.bg = bg or "#1c1f2e"
        self.fg = fg or "#e6e9f2"
        self.outline = outline or "#272b3c"
        self._tip_window: tk.Toplevel | None = None
        self._after_id: str | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._cancel, add="+")
        widget.bind("<Button>", self._cancel, add="+")

    def _schedule(self, _event: object) -> None:
        self._cancel()
        self._after_id = self.widget.after(self._DELAY_MS, self._show)

    def _cancel(self, _event: object = None) -> None:
        if self._after_id:
            self.widget.after_cancel(self._after_id)
            self._after_id = None
        self._hide()

    def _show(self) -> None:
        if self._tip_window:
            return
        x = self.widget.winfo_rootx() + 10
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        screen_w = self.widget.winfo_screenwidth()
        screen_h = self.widget.winfo_screenheight()
        tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        try:
            tw.wm_attributes("-topmost", True)
        except tk.TclError:
            pass
        tw.configure(bg=self.outline)
        label = tk.Label(
            tw,
            text=self.text,
            bg=self.bg,
            fg=self.fg,
            font=("TkDefaultFont", 11),
            wraplength=320,
            justify="left",
            padx=10,
            pady=6,
        )
        label.pack(padx=1, pady=1)
        tw.update_idletasks()
        tip_w = tw.winfo_width()
        tip_h = tw.winfo_height()
        if x + tip_w > screen_w:
            x = screen_w - tip_w - 4
        if y + tip_h > screen_h:
            y = self.widget.winfo_rooty() - tip_h - 4
        tw.wm_geometry(f"+{x}+{y}")
        self._tip_window = tw

    def _hide(self) -> None:
        if self._tip_window:
            self._tip_window.destroy()
            self._tip_window = None


class _OnboardingWizard(tk.Toplevel):
    """Native 6-stage setup wizard using the onboarding state machine."""

    _STAGES = ("welcome", "api_key", "budgets", "csv_walkthrough", "first_run", "done")

    def __init__(self, parent: DesktopApp) -> None:
        super().__init__(parent)
        self.app = parent
        self.title("Setup — tech_stock")
        self.geometry("680x520")
        self.resizable(False, False)
        self.configure(bg=PALETTE.bg)
        self.transient(parent)
        self.grab_set()

        self._api_key_var = tk.StringVar()
        # New installs get a sensible monthly Claude spend cap; existing users
        # keep whatever they already saved (this only seeds the onboarding field).
        self._budget_claude_var = tk.StringVar(value="25")
        self._budget_usd_var = tk.StringVar(value="0")
        self._budget_cad_var = tk.StringVar(value="3000")
        self._csv_path_var = tk.StringVar()

        try:
            defaults = find_default_csvs()
            if defaults.get("holdings"):
                self._csv_path_var.set(str(defaults["holdings"]))
        except Exception:
            pass

        try:
            from src.onboarding import current_state

            state = current_state()
            self._current = state.stage if state.stage in self._STAGES else "welcome"
        except Exception:
            self._current = "welcome"

        self._content = tk.Frame(self, bg=PALETTE.bg)
        self._content.pack(fill="both", expand=True, padx=30, pady=20)
        self._render()

    def _render(self) -> None:
        for w in self._content.winfo_children():
            w.destroy()

        # Progress dots
        dot_frame = tk.Frame(self._content, bg=PALETTE.bg)
        dot_frame.pack(fill="x", pady=(0, 20))
        labels = ["Welcome", "API Key", "Budget", "CSV", "First Run", "Done"]
        for i, (stage, label) in enumerate(zip(self._STAGES, labels)):
            idx = self._STAGES.index(self._current)
            if self._STAGES.index(stage) < idx:
                color = PALETTE.accent
            elif stage == self._current:
                color = PALETTE.text_strong
            else:
                color = PALETTE.border
            tk.Label(dot_frame, text=f"● {label}", bg=PALETTE.bg, fg=color, font=("TkDefaultFont", 10)).pack(side="left", padx=(0, 14))

        try:
            from src.onboarding import stage_guidance

            guidance = stage_guidance(self._current)
        except Exception:
            self.destroy()
            return

        # Title
        tk.Label(
            self._content,
            text=guidance.title,
            bg=PALETTE.bg,
            fg=PALETTE.text_strong,
            font=("TkDefaultFont", 20, "bold"),
            anchor="w",
        ).pack(fill="x", pady=(0, 10))

        # Body
        tk.Label(
            self._content,
            text=guidance.body,
            bg=PALETTE.bg,
            fg=PALETTE.text,
            font=("TkDefaultFont", 12),
            wraplength=600,
            justify="left",
            anchor="nw",
        ).pack(fill="x", pady=(0, 14))

        # Stage-specific inputs
        self._render_inputs()

        # Helper text
        if guidance.helper_text:
            tk.Label(
                self._content,
                text=guidance.helper_text,
                bg=PALETTE.bg,
                fg=PALETTE.muted,
                font=("TkDefaultFont", 10),
                wraplength=600,
                justify="left",
            ).pack(fill="x", pady=(8, 0))

        # Buttons
        btn_frame = tk.Frame(self._content, bg=PALETTE.bg)
        btn_frame.pack(fill="x", side="bottom", pady=(16, 0))

        if guidance.external_url:
            link = tk.Label(
                btn_frame,
                text="Open in browser →",
                bg=PALETTE.bg,
                fg=PALETTE.info,
                font=("TkDefaultFont", 11, "underline"),
                cursor="hand2",
            )
            link.pack(side="left")
            link.bind("<Button-1>", lambda _e, url=guidance.external_url: self._open_url(url))

        if guidance.secondary_action:
            tk.Button(
                btn_frame,
                text=guidance.secondary_action,
                bg=PALETTE.card,
                fg=PALETTE.text,
                font=("TkDefaultFont", 12),
                relief="flat",
                padx=16,
                pady=8,
                command=self._secondary,
            ).pack(side="right", padx=(8, 0))

        tk.Button(
            btn_frame,
            text=guidance.primary_action,
            bg=PALETTE.accent,
            fg=PALETTE.bg,
            font=("TkDefaultFont", 12, "bold"),
            relief="flat",
            padx=20,
            pady=8,
            command=self._primary,
        ).pack(side="right")

    def _render_inputs(self) -> None:
        if self._current == "api_key":
            frame = tk.Frame(self._content, bg=PALETTE.bg)
            frame.pack(fill="x", pady=(4, 0))
            tk.Label(frame, text="API Key:", bg=PALETTE.bg, fg=PALETTE.muted, font=("TkDefaultFont", 11)).pack(side="left")
            entry = tk.Entry(
                frame,
                textvariable=self._api_key_var,
                show="*",
                bg=PALETTE.card,
                fg=PALETTE.text,
                insertbackground=PALETTE.text,
                font=("TkDefaultFont", 12),
                width=44,
                relief="flat",
            )
            entry.pack(side="left", padx=(8, 0), ipady=4)
            entry.focus_set()

        elif self._current == "budgets":
            frame = tk.Frame(self._content, bg=PALETTE.bg)
            frame.pack(fill="x", pady=(4, 0))
            for label, var in [
                ("Monthly Claude budget (USD)", self._budget_claude_var),
                ("Trade budget (USD)", self._budget_usd_var),
                ("Trade budget (CAD)", self._budget_cad_var),
            ]:
                row = tk.Frame(frame, bg=PALETTE.bg)
                row.pack(fill="x", pady=3)
                tk.Label(row, text=label, bg=PALETTE.bg, fg=PALETTE.muted, font=("TkDefaultFont", 11), width=28, anchor="w").pack(
                    side="left"
                )
                tk.Entry(
                    row,
                    textvariable=var,
                    bg=PALETTE.card,
                    fg=PALETTE.text,
                    insertbackground=PALETTE.text,
                    font=("TkDefaultFont", 12),
                    width=12,
                    relief="flat",
                ).pack(side="left", padx=(8, 0), ipady=3)

        elif self._current == "csv_walkthrough":
            frame = tk.Frame(self._content, bg=PALETTE.bg)
            frame.pack(fill="x", pady=(4, 0))
            tk.Label(frame, text="Holdings CSV:", bg=PALETTE.bg, fg=PALETTE.muted, font=("TkDefaultFont", 11)).pack(side="left")
            tk.Entry(
                frame,
                textvariable=self._csv_path_var,
                bg=PALETTE.card,
                fg=PALETTE.text,
                insertbackground=PALETTE.text,
                font=("TkDefaultFont", 11),
                width=36,
                relief="flat",
            ).pack(side="left", padx=(8, 0), ipady=3)
            tk.Button(
                frame,
                text="Browse...",
                bg=PALETTE.card,
                fg=PALETTE.text,
                font=("TkDefaultFont", 11),
                relief="flat",
                padx=10,
                command=self._browse_csv,
            ).pack(side="left", padx=(8, 0))

    def _browse_csv(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose Holdings CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            self._csv_path_var.set(path)

    def _open_url(self, url: str) -> None:
        import webbrowser

        webbrowser.open(url)

    def _advance(self, *, skip_demo: bool = False) -> None:
        try:
            from src.onboarding import advance

            state = advance(current=self._current, skip_demo=skip_demo)
            self._current = state.stage
        except Exception:
            idx = self._STAGES.index(self._current)
            self._current = self._STAGES[min(idx + 1, len(self._STAGES) - 1)]
        if self._current == "done":
            self._finish()
        else:
            self._render()

    def _primary(self) -> None:
        if self._current == "api_key":
            key = self._api_key_var.get().strip()
            if key:
                try:
                    save_api_key("ANTHROPIC_API_KEY", key)
                except Exception:
                    logger.debug("Failed to save API key", exc_info=True)
            self._advance()
        elif self._current == "budgets":
            try:
                import json

                settings_path = ROOT / "config" / "settings.json"
                settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
                # Persist all three fields the wizard collects. Previously only
                # budget_cad was saved, silently dropping the Claude spend cap
                # (monthly_budget_usd) and the USD trade budget the analyst reads.
                for key, var, fallback in (
                    ("monthly_budget_usd", self._budget_claude_var, 25),
                    ("budget_usd", self._budget_usd_var, 0),
                    ("budget_cad", self._budget_cad_var, 3000),
                ):
                    try:
                        settings[key] = float(var.get() or fallback)
                    except ValueError:
                        settings[key] = float(fallback)
                settings_path.parent.mkdir(parents=True, exist_ok=True)
                settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
            except Exception:
                logger.debug("Failed to save budget settings", exc_info=True)
            self._advance()
        elif self._current == "csv_walkthrough":
            csv_path = self._csv_path_var.get().strip()
            if csv_path and hasattr(self.app, "holdings_var"):
                self.app.holdings_var.set(csv_path)
            self._advance()
        elif self._current == "first_run":
            self._advance()
            if hasattr(self.app, "start_report_run"):
                self.app.start_report_run()
        else:
            self._advance()

    def _secondary(self) -> None:
        if self._current == "welcome":
            self._advance(skip_demo=False)
        else:
            self._advance(skip_demo=True)

    def _finish(self) -> None:
        self.grab_release()
        self.destroy()
        try:
            self.app.tabs.select(self.app.dashboard_tab)
        except tk.TclError:
            pass


class DesktopApp(tk.Tk):
    """Native desktop dashboard for users who do not want a browser UI."""

    def __init__(self) -> None:
        super().__init__()
        self.title("tech_stock")
        self.geometry("1280x880")
        self.minsize(1024, 720)
        self._set_window_icon()
        self._restore_window_size()

        # Shared palette (Streamlit + Textual + Tkinter all read the same tokens)
        self.bg = PALETTE.bg
        self.surface = PALETTE.surface
        self.panel = PALETTE.panel
        self.text = PALETTE.text
        self.text_strong = PALETTE.text_strong
        self.muted = PALETTE.muted
        self.subtle = PALETTE.subtle
        self.accent = PALETTE.accent
        self.accent_hover = PALETTE.accent_hover
        self.danger = PALETTE.danger
        self.warning = PALETTE.warn
        self.info = PALETTE.info
        self.good = PALETTE.accent
        self.card = PALETTE.card
        self.border = PALETTE.border
        self.border_strong = PALETTE.border_strong
        self.table_bg = self.surface
        self.configure(bg=self.bg)

        # Platform-aware font ladder
        self.fonts = _platform_fonts()

        self.progress_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.latest_report_path: Path | None = None  # lazily resolved after first paint
        self.latest_update_info: Any = None
        self.search_state: dict[str, dict[str, Any]] = {}
        self._warmed_tabs: set[str] = set()
        self._async_generation: dict[str, int] = {}
        self._refresh_buttons: dict[str, Any] = {}
        self._report_elapsed_id: str | None = None
        self._report_start_time: float | None = None
        self._drain_id: str | None = None
        self._closing = False

        self._configure_style()
        self._build_menu()
        self._build_header()
        self._build_tabs()
        self._build_status_bar()

        # Universal accelerators
        self.bind_all(f"<{MOD_KEY}-f>", self.focus_active_search)
        self.bind_all(f"<{MOD_KEY}-r>", lambda _e: self._refresh_active_tab())
        self.bind_all(f"<{MOD_KEY}-comma>", lambda _e: self._jump_to_settings())
        self.bind_all(f"<{MOD_KEY}-n>", lambda _e: self._jump_to_tab(self.reports_tab, sub=self.run_subtab))
        self.bind_all(f"<{MOD_KEY}-l>", lambda _e: self.load_report(latest_report(), select_tab=True))

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._drain_id = self.after(100, self._drain_progress_queue)
        self.after_idle(self._post_paint_warmup)
        self.after(800, self._maybe_show_onboarding)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        fonts = self.fonts
        style.configure("TFrame", background=self.bg)
        style.configure("Panel.TFrame", background=self.panel)
        style.configure("Card.TFrame", background=self.card)
        style.configure(
            "TLabel",
            background=self.bg,
            foreground=self.text,
            font=fonts["body"],
        )
        style.configure(
            "Muted.TLabel",
            background=self.bg,
            foreground=self.muted,
            font=fonts["small"],
        )
        style.configure(
            "Title.TLabel",
            background=self.bg,
            foreground=self.text_strong,
            font=fonts["title"],
        )
        style.configure(
            "Subtitle.TLabel",
            background=self.bg,
            foreground=self.muted,
            font=fonts["small"],
        )
        style.configure(
            "TButton",
            padding=(14, 7),
            font=fonts["body"],
            background=self.card,
            foreground=self.text,
            borderwidth=1,
            relief="flat",
        )
        style.map(
            "TButton",
            background=[("active", self.border_strong), ("pressed", self.border)],
            foreground=[("active", self.accent)],
        )
        style.configure(
            "Accent.TButton",
            padding=(18, 9),
            font=fonts["subheading"],
            background=self.accent,
            foreground=self.bg,
        )
        style.map(
            "Accent.TButton",
            background=[("active", self.accent_hover)],
        )
        style.configure(
            "TNotebook",
            background=self.bg,
            borderwidth=0,
            tabmargins=[0, 0, 0, 0],
        )
        style.configure(
            "TNotebook.Tab",
            padding=(16, 8),
            font=fonts["body"],
            background=self.panel,
            foreground=self.muted,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", self.surface)],
            foreground=[("selected", self.accent)],
        )
        style.configure(
            "Treeview",
            rowheight=30,
            background=self.surface,
            fieldbackground=self.surface,
            foreground=self.text,
            borderwidth=0,
            font=fonts["body"],
        )
        style.configure(
            "Treeview.Heading",
            background=self.panel,
            foreground=self.muted,
            font=fonts["small"],
            relief="flat",
            padding=(8, 6),
        )
        style.map(
            "Treeview",
            background=[("selected", self.border_strong)],
            foreground=[("selected", self.text_strong)],
        )
        style.map("Treeview.Heading", background=[("active", self.card)])
        style.configure(
            "TCombobox",
            fieldbackground=self.card,
            background=self.card,
            foreground=self.text,
            arrowcolor=self.muted,
            borderwidth=1,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", self.card)],
            foreground=[("readonly", self.text)],
        )
        style.configure(
            "TEntry",
            fieldbackground=self.card,
            foreground=self.text,
            insertcolor=self.text,
            borderwidth=1,
        )
        style.configure(
            "TCheckbutton",
            background=self.bg,
            foreground=self.text,
            font=fonts["body"],
        )
        style.configure(
            "TSpinbox",
            fieldbackground=self.card,
            foreground=self.text,
            arrowcolor=self.muted,
        )
        style.configure(
            "Vertical.TScrollbar",
            background=self.panel,
            troughcolor=self.bg,
            borderwidth=0,
            arrowcolor=self.muted,
        )
        style.configure(
            "Sub.TNotebook",
            background=self.bg,
            borderwidth=0,
        )
        style.configure(
            "Sub.TNotebook.Tab",
            padding=(10, 5),
            font=fonts["small"],
            background=self.panel,
            foreground=self.muted,
        )
        style.map(
            "Sub.TNotebook.Tab",
            background=[("selected", self.surface)],
            foreground=[("selected", self.accent)],
        )
        style.configure(
            "Status.TLabel",
            background=self.panel,
            foreground=self.muted,
            font=fonts["small"],
        )
        style.configure(
            "TPanedwindow",
            background=self.bg,
        )
        style.configure(
            "Sash",
            sashthickness=6,
            background=self.border,
        )

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
            self.createcommand("tk::mac::ShowPreferences", self._jump_to_settings)
            self.createcommand("tk::mac::Quit", self._on_close)

        # — File menu —
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(
            label="New Report…",
            accelerator=f"{MOD_LABEL}N",
            command=lambda: self._jump_to_tab(self.reports_tab, sub=self.run_subtab),
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
            file_menu.add_command(label="Quit", accelerator="Ctrl+Q", command=self._on_close)
            self.bind_all("<Control-q>", lambda _e: self._on_close())
        menubar.add_cascade(label="File", menu=file_menu)

        # — View menu —
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="Home", command=lambda: self._jump_to_tab(self.dashboard_tab))
        view_menu.add_command(label="Signals", command=lambda: self._jump_to_tab(self.buy_signals_tab))
        view_menu.add_command(label="Reports", command=lambda: self._jump_to_tab(self.reports_tab))
        view_menu.add_command(label="Performance", command=lambda: self._jump_to_tab(self.performance_tab))
        view_menu.add_command(label="Outcomes", command=lambda: self._jump_to_tab(self.outcomes_tab))
        view_menu.add_command(label="Settings", accelerator=f"{MOD_LABEL},", command=self._jump_to_settings)
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
        header = tk.Frame(self, bg=self.bg)
        header.pack(fill="x", padx=24, pady=(20, 6))

        left = tk.Frame(header, bg=self.bg)
        left.pack(side="left", anchor="w")
        tk.Label(
            left,
            text="tech_stock",
            bg=self.bg,
            fg=self.text_strong,
            font=self.fonts["title"],
        ).pack(side="left")
        tk.Label(
            left,
            text=f"v{current_app_version()}",
            bg=self.bg,
            fg=self.accent,
            font=self.fonts["small"],
        ).pack(side="left", padx=(12, 0), pady=(12, 0))

        right = tk.Frame(header, bg=self.bg)
        right.pack(side="right", anchor="e")
        self.header_status_var = tk.StringVar(value="Loading...")
        self.header_status_label = tk.Label(
            right,
            textvariable=self.header_status_var,
            bg=self.bg,
            fg=self.muted,
            font=self.fonts["small"],
        )
        self.header_status_label.pack(side="right", pady=(12, 0))
        self._tip(self.header_status_label, "Shows session cost, warning count, and data quality from the latest report")

        separator = tk.Frame(self, bg=self.border, height=1)
        separator.pack(fill="x", padx=24, pady=(8, 0))

    def _build_tabs(self) -> None:
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=20, pady=(10, 0))

        self.dashboard_tab = ttk.Frame(self.tabs)
        self.buy_signals_tab = ttk.Frame(self.tabs)
        self.reports_tab = ttk.Frame(self.tabs)
        self.performance_tab = ttk.Frame(self.tabs)
        self.outcomes_tab = ttk.Frame(self.tabs)
        self.learning_tab = ttk.Frame(self.tabs)
        self.diagnostics_tab = ttk.Frame(self.tabs)
        self.settings_tab = ttk.Frame(self.tabs)

        self.tabs.add(self.dashboard_tab, text=" Home ")
        self.tabs.add(self.buy_signals_tab, text=" Signals ")
        self.tabs.add(self.reports_tab, text=" Reports ")
        self.tabs.add(self.performance_tab, text=" Performance ")
        self.tabs.add(self.outcomes_tab, text=" Outcomes ")
        self.tabs.add(self.learning_tab, text=" Learning ")
        self.tabs.add(self.diagnostics_tab, text=" Diagnostics ")
        self.tabs.add(self.settings_tab, text=" Settings ")

        # Reports sub-notebook: Run / Latest / History
        self.reports_sub = ttk.Notebook(self.reports_tab, style="Sub.TNotebook")
        self.reports_sub.pack(fill="both", expand=True, padx=4, pady=4)
        self.run_subtab = ttk.Frame(self.reports_sub)
        self.report_subtab = ttk.Frame(self.reports_sub)
        self.history_subtab = ttk.Frame(self.reports_sub)
        self.reports_sub.add(self.run_subtab, text=" Run ")
        self.reports_sub.add(self.report_subtab, text=" Latest ")
        self.reports_sub.add(self.history_subtab, text=" History ")

        # Settings sub-notebook: Preferences / API Keys / Schedule / Advanced Editor / Updates
        self.settings_sub = ttk.Notebook(self.settings_tab, style="Sub.TNotebook")
        self.settings_sub.pack(fill="both", expand=True, padx=4, pady=4)
        self.prefs_subtab = ttk.Frame(self.settings_sub)
        self.data_files_subtab = ttk.Frame(self.settings_sub)
        self.health_subtab = ttk.Frame(self.settings_sub)
        self.schedule_subtab = ttk.Frame(self.settings_sub)
        self.editor_subtab = ttk.Frame(self.settings_sub)
        self.update_subtab = ttk.Frame(self.settings_sub)
        self.settings_sub.add(self.prefs_subtab, text=" Preferences ")
        self.settings_sub.add(self.data_files_subtab, text=" Data Files ")
        self.settings_sub.add(self.health_subtab, text=" API Keys ")
        self.settings_sub.add(self.schedule_subtab, text=" Schedule ")
        self.settings_sub.add(self.editor_subtab, text=" Advanced Editor ")
        self.settings_sub.add(self.update_subtab, text=" Updates ")

        # Alias old tab references for internal methods
        self.run_tab = self.run_subtab
        self.report_tab = self.report_subtab
        self.history_tab = self.history_subtab
        self.editor_tab = self.editor_subtab
        self.data_files_tab = self.data_files_subtab
        self.health_tab = self.health_subtab
        self.schedule_tab = self.schedule_subtab
        self.update_tab = self.update_subtab

        self._build_dashboard_tab()
        self._build_buy_signals_tab()
        self._build_run_tab()
        self._build_report_tab()
        self._build_history_tab()
        self._build_performance_tab()
        self._build_outcomes_tab()
        self._build_learning_tab()
        self._build_diagnostics_tab()
        self._build_preferences_tab()
        self._build_data_files_tab()
        self._build_schedule_tab()
        self._build_editor_tab()
        self._build_health_tab()
        self._build_update_tab()

    # ── Lazy-warm-up & menu helpers ─────────────────────────────────────────
    def _post_paint_warmup(self) -> None:
        """Run after the first paint; load lightweight context, defer heavy work."""
        self._set_status("Loading your latest data...")
        self.latest_report_path = latest_report()

        self.refresh_dashboard()
        self.refresh_history()
        self.load_report(self.latest_report_path, select_tab=False)
        self._update_header_status()
        self._update_status_bar()

        self.after(350, self.confirm_detected_csv_paths)

        if os.environ.get("TECH_STOCK_SKIP_UPDATE_CHECK") != "1":
            self.after(1200, lambda: self.start_update_check(startup=True))

        self.tabs.bind("<<NotebookTabChanged>>", self._on_tab_changed, add="+")
        self.settings_sub.bind("<<NotebookTabChanged>>", self._on_settings_sub_changed, add="+")

        # Welcome-back message for returning users
        try:
            from src.onboarding import needs_onboarding

            if not needs_onboarding():
                self._set_status("Welcome back!", tone="success")
                self.after(3000, lambda: self._set_status(f"Ready — press {MOD_LABEL}N to generate a report."))
            else:
                self._set_status(f"Ready — press {MOD_LABEL}N to generate a report.")
        except Exception:
            self._set_status(f"Ready — press {MOD_LABEL}N to generate a report.")

    def _tab_name(self) -> str:
        """Return the active primary tab name, stripped of padding spaces."""
        try:
            selected = self.tabs.select()
            return self.tabs.tab(selected, "text").strip()
        except tk.TclError:
            return ""

    def _sub_tab_name(self, notebook: ttk.Notebook) -> str:
        """Return the active sub-tab name for a nested notebook."""
        try:
            selected = notebook.select()
            return notebook.tab(selected, "text").strip()
        except tk.TclError:
            return ""

    def _on_tab_changed(self, _event: object) -> None:
        """Warm up a tab the first time the user actually visits it."""
        tab_text = self._tab_name()
        if not tab_text or tab_text in self._warmed_tabs:
            return
        self._warmed_tabs.add(tab_text)
        if tab_text == "Signals":
            self.start_buy_signal_refresh()
        elif tab_text == "Settings":
            self.refresh_api_key_manager()
        elif tab_text == "Learning":
            self.refresh_learning_tab()
        elif tab_text == "Diagnostics":
            self.refresh_diagnostics_tab()
        elif tab_text == "Performance":
            self.refresh_performance_tab()
        elif tab_text == "Outcomes":
            self.refresh_outcomes_tab()

    def _on_settings_sub_changed(self, _event: object) -> None:
        sub = self._sub_tab_name(self.settings_sub)
        key = f"settings:{sub}"
        if key in self._warmed_tabs:
            return
        self._warmed_tabs.add(key)
        if sub == "Schedule":
            self.refresh_schedule_tab()
        elif sub == "Data Files":
            self.refresh_data_files_tab()

    def _refresh_active_tab(self) -> None:
        """⌘R handler — re-run the data-load for whichever tab is in front."""
        tab_text = self._tab_name()
        if not tab_text:
            return
        if tab_text == "Reports":
            sub = self._sub_tab_name(self.reports_sub)
            sub_actions: dict[str, callable] = {
                "Latest": lambda: self.load_report(latest_report(), select_tab=True),
                "History": self.refresh_history,
            }
            handler = sub_actions.get(sub)
            if handler:
                handler()
            return
        if tab_text == "Settings":
            sub = self._sub_tab_name(self.settings_sub)
            sub_actions = {
                "Schedule": self.refresh_schedule_tab,
                "Data Files": self.refresh_data_files_tab,
                "Advanced Editor": self.load_editor_file,
                "API Keys": self.start_connectivity_check,
                "Updates": lambda: self.start_update_check(startup=False),
            }
            handler = sub_actions.get(sub)
            if handler:
                handler()
            return
        actions: dict[str, callable] = {
            "Home": self.refresh_dashboard,
            "Signals": self.start_buy_signal_refresh,
            "Performance": self.refresh_performance_tab,
            "Outcomes": self.refresh_outcomes_tab,
            "Learning": self.refresh_learning_tab,
            "Diagnostics": self.refresh_diagnostics_tab,
        }
        handler = actions.get(tab_text)
        if handler is not None:
            handler()

    def _jump_to_tab(self, tab_frame: ttk.Frame, *, sub: ttk.Frame | None = None) -> None:
        try:
            if tab_frame in (self.run_subtab, self.report_subtab, self.history_subtab):
                self.tabs.select(self.reports_tab)
                self.reports_sub.select(tab_frame)
            elif tab_frame in (
                self.prefs_subtab,
                self.data_files_subtab,
                self.health_subtab,
                self.schedule_subtab,
                self.editor_subtab,
                self.update_subtab,
            ):
                self.tabs.select(self.settings_tab)
                self.settings_sub.select(tab_frame)
            else:
                self.tabs.select(tab_frame)
                if sub is not None:
                    if tab_frame is self.reports_tab:
                        self.reports_sub.select(sub)
                    elif tab_frame is self.settings_tab:
                        self.settings_sub.select(sub)
        except tk.TclError:
            pass

    def _jump_to_settings(self) -> None:
        self._jump_to_tab(self.settings_tab, sub=self.prefs_subtab)

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

    def _build_status_bar(self) -> None:
        bar = tk.Frame(self, bg=self.panel, height=26)
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)

        self._status_dot = tk.Label(bar, text="●", bg=self.panel, fg=self.accent, font=("TkDefaultFont", 9))
        self._status_dot.pack(side="left", padx=(12, 4))
        self._status_msg = tk.StringVar(value="Loading...")
        tk.Label(bar, textvariable=self._status_msg, bg=self.panel, fg=self.muted, font=self.fonts["small"]).pack(side="left")

        sep1 = tk.Label(bar, text="|", bg=self.panel, fg=self.border, font=self.fonts["small"])
        sep1.pack(side="left", padx=10)
        self._status_report = tk.StringVar(value="")
        tk.Label(bar, textvariable=self._status_report, bg=self.panel, fg=self.muted, font=self.fonts["small"]).pack(side="left")

        sep2 = tk.Label(bar, text="|", bg=self.panel, fg=self.border, font=self.fonts["small"])
        sep2.pack(side="left", padx=10)
        self._status_cost = tk.StringVar(value="")
        tk.Label(bar, textvariable=self._status_cost, bg=self.panel, fg=self.muted, font=self.fonts["small"]).pack(side="left")

        version_label = tk.Label(
            bar,
            text=f"v{current_app_version()}",
            bg=self.panel,
            fg=self.subtle,
            font=self.fonts["small"],
        )
        version_label.pack(side="right", padx=12)

    def _set_status(self, message: str, *, tone: str = "neutral") -> None:
        colors = {
            "success": self.accent,
            "warning": self.warning,
            "error": self.danger,
            "neutral": self.muted,
        }
        self._status_msg.set(message)
        self._status_dot.configure(fg=colors.get(tone, self.muted))

    def _update_status_bar(self) -> None:
        report = self.latest_report_path
        if report and report.exists():
            import time

            mtime = report.stat().st_mtime
            age = time.time() - mtime
            if age < 86400:
                from datetime import datetime

                ts = datetime.fromtimestamp(mtime).strftime("%I:%M %p").lstrip("0")
                self._status_report.set(f"Last report: Today {ts}")
            else:
                from datetime import datetime

                ts = datetime.fromtimestamp(mtime).strftime("%b %d, %I:%M %p").lstrip("0")
                self._status_report.set(f"Last report: {ts}")
        else:
            self._status_report.set("No reports yet")

        summary = latest_log_summary() or {}
        usage = summary.get("usage") or {}
        cost = usage.get("cost_usd")
        if cost is not None:
            self._status_cost.set(f"Session: ${cost:.2f}")
        else:
            self._status_cost.set("")

    def _tip(self, widget: tk.Widget, text: str) -> _Tooltip:
        return _Tooltip(widget, text, bg=self.card, fg=self.text, outline=self.border)

    def _maybe_show_onboarding(self) -> None:
        """Show the native onboarding wizard on first launch."""
        try:
            from src.onboarding import needs_onboarding

            if not needs_onboarding():
                return
        except Exception:
            return
        self.after(200, lambda: _OnboardingWizard(self))

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

            messagebox.showinfo("No report yet", "Generate a report first from the Reports > Run tab.")
            return
        self._reveal_in_finder(report)

    def _set_window_icon(self) -> None:
        """Use the packaged app icon for the title bar / taskbar / dock when
        running from source (PyInstaller builds already set this via the
        bundle's .icns/.ico, but a plain `python src/desktop_app.py` run
        otherwise shows Tk's generic feather icon)."""
        icon_path = Path(__file__).resolve().parents[2] / "assets" / "icon.png"
        if not icon_path.exists():
            return
        try:
            self._icon_image = tk.PhotoImage(file=str(icon_path))
            self.iconphoto(True, self._icon_image)
        except Exception:
            logger.debug("Failed to set window icon from %s", icon_path, exc_info=True)

    @staticmethod
    def _sanitize_window_size(
        size: str | None,
        screen_w: int,
        screen_h: int,
        *,
        min_w: int = 1024,
        min_h: int = 720,
    ) -> str | None:
        """Validate a saved ``"WIDTHxHEIGHT"`` string and clamp it onto the
        current screen.

        Restoring only the *size* (never the position) sidesteps the classic
        multi-monitor bug where a window saved on a now-disconnected display
        reopens off-screen and becomes unreachable. Returns ``None`` for an
        unparseable value so the caller keeps the default geometry.
        """
        if not size:
            return None
        match = re.match(r"^\s*(\d+)x(\d+)", str(size))
        if not match:
            return None
        width = max(min_w, min(int(match.group(1)), max(min_w, screen_w)))
        height = max(min_h, min(int(match.group(2)), max(min_h, screen_h)))
        return f"{width}x{height}"

    @property
    def _window_state_path(self) -> Path:
        return ROOT / "config" / "window_state.json"

    def _restore_window_size(self) -> None:
        """Reopen at the size the user last left the window."""
        import json

        try:
            path = self._window_state_path
            if not path.exists():
                return
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.debug("Could not read saved window size", exc_info=True)
            return
        size = self._sanitize_window_size(data.get("size"), self.winfo_screenwidth(), self.winfo_screenheight())
        if not size:
            return
        try:
            self.geometry(size)
        except tk.TclError:
            logger.debug("Could not apply saved window size %r", size, exc_info=True)

    def _save_window_size(self) -> None:
        """Persist the current window size so the next launch matches it."""
        import json

        try:
            width = self.winfo_width()
            height = self.winfo_height()
            if width <= 1 or height <= 1:  # window never realized — nothing useful to save
                return
            path = self._window_state_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"size": f"{width}x{height}"}, indent=2) + "\n", encoding="utf-8")
        except Exception:
            logger.debug("Could not persist window size", exc_info=True)

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
            logger.debug("Failed to reveal %s in file manager", path, exc_info=True)
            self._set_status(f"Couldn't open file manager — file is at {path}", tone="error")

    def _open_repo(self) -> None:
        import webbrowser

        webbrowser.open("https://github.com/pouyafath/tech_stock")

    def _open_issues(self) -> None:
        import webbrowser

        webbrowser.open("https://github.com/pouyafath/tech_stock/issues/new")

    def _panel(self, parent: tk.Widget, title: str | None = None) -> ttk.Frame:
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=16)
        if title:
            tk.Label(
                frame,
                text=title.upper(),
                bg=self.panel,
                fg=self.muted,
                font=self.fonts["small"],
                anchor="w",
            ).pack(fill="x", pady=(0, 10))
            tk.Frame(frame, bg=self.border, height=1).pack(fill="x", pady=(0, 10))
        return frame

    def _dashboard_panel(self, parent: tk.Widget, title: str) -> tuple[tk.Frame, tk.Frame]:
        panel = tk.Frame(parent, bg=self.panel, highlightthickness=1, highlightbackground=self.border)
        header = tk.Frame(panel, bg=self.panel)
        header.pack(fill="x", padx=16, pady=(14, 4))
        tk.Label(
            header,
            text=title.upper(),
            bg=self.panel,
            fg=self.muted,
            font=self.fonts["small"],
        ).pack(anchor="w")
        tk.Frame(panel, bg=self.border, height=1).pack(fill="x", padx=16, pady=(6, 0))
        body = tk.Frame(panel, bg=self.panel)
        body.pack(fill="both", expand=True, padx=16, pady=(10, 16))
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
        self._bind_mousewheel(canvas, content)
        return content

    @staticmethod
    def _wheel_scroll_steps(delta: int, num: int | None) -> int:
        """Translate a wheel event into a signed number of scroll units.

        Tk reports wheel input three different ways: Linux fires
        ``<Button-4>``/``<Button-5>`` (no delta), Windows sends ``delta`` in
        multiples of 120, and macOS sends small ``±1``/``±2`` deltas. Positive
        delta means "scroll up", which is a *negative* unit count for Tk.
        """
        if num == 4:
            return -1
        if num == 5:
            return 1
        if not delta:
            return 0
        if abs(delta) >= 120:  # Windows — multiples of 120
            return int(-delta / 120)
        return -1 if delta > 0 else 1  # macOS — small deltas

    def _bind_mousewheel(self, canvas: tk.Canvas, content: tk.Widget) -> None:
        """Let the mouse wheel / trackpad scroll ``canvas`` while the pointer
        is over it.

        The binding is activated on ``<Enter>`` and torn down on ``<Leave>`` so
        only the hovered scroll region reacts — several scrollable panes and
        Treeviews coexist in this window and must not fight over the wheel. The
        ``NotifyInferior`` guard keeps the binding alive when the pointer merely
        crosses onto a child widget inside the scroll region.
        """

        def _on_wheel(event: tk.Event) -> str:
            first, last = canvas.yview()
            if first <= 0.0 and last >= 1.0:
                return ""  # nothing to scroll — let the event propagate
            steps = self._wheel_scroll_steps(getattr(event, "delta", 0), getattr(event, "num", None))
            if steps:
                canvas.yview_scroll(steps, "units")
            return "break"

        def _activate(_event: tk.Event) -> None:
            # Bind without "+" so the most-recently-entered scroll region owns
            # the wheel and stale closures from other panes can't fire.
            canvas.bind_all("<MouseWheel>", _on_wheel)
            canvas.bind_all("<Button-4>", _on_wheel)
            canvas.bind_all("<Button-5>", _on_wheel)

        def _deactivate(event: tk.Event) -> None:
            if getattr(event, "detail", "") == "NotifyInferior":
                return  # moved onto a child, still inside the scroll region
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        for widget in (canvas, content):
            widget.bind("<Enter>", _activate, add="+")
            widget.bind("<Leave>", _deactivate, add="+")

    def _build_dashboard_tab(self) -> None:
        content = self._scrollable_frame(self.dashboard_tab)

        top = tk.Frame(content, bg=self.bg)
        top.pack(fill="x", padx=16, pady=(14, 10))
        refresh_btn = ttk.Button(top, text="Refresh", command=self.refresh_dashboard)
        refresh_btn.pack(side="left")
        self._tip(refresh_btn, "Reload dashboard data from the latest report")
        self.dashboard_caption = ttk.Label(top, text="", style="Muted.TLabel")
        self.dashboard_caption.pack(side="left", padx=12)

        signal = tk.Frame(content, bg=self.card, highlightthickness=1, highlightbackground=self.border)
        signal.pack(fill="x", padx=16, pady=(0, 14))
        self.signal_accent = tk.Frame(signal, bg=self.accent, width=4)
        self.signal_accent.pack(side="left", fill="y")
        signal_body = tk.Frame(signal, bg=self.card, padx=18, pady=16)
        signal_body.pack(side="left", fill="both", expand=True)
        self.signal_kicker = tk.StringVar(value="ACTION PULSE")
        self.signal_title = tk.StringVar(value="Welcome to tech_stock")
        self.signal_body = tk.StringVar(value="Generate your first report to see your portfolio analysis here.")
        self.signal_meta = tk.StringVar(value="")
        tk.Label(
            signal_body,
            textvariable=self.signal_kicker,
            bg=self.card,
            fg=self.subtle,
            font=self.fonts["small"],
        ).pack(anchor="w")
        tk.Label(
            signal_body,
            textvariable=self.signal_title,
            bg=self.card,
            fg=self.accent,
            font=self.fonts["heading"],
        ).pack(anchor="w", pady=(6, 0))
        tk.Label(
            signal_body,
            textvariable=self.signal_body,
            bg=self.card,
            fg=self.text,
            font=self.fonts["body"],
            wraplength=1080,
            justify="left",
        ).pack(anchor="w", fill="x", pady=(8, 0))
        tk.Label(
            signal_body,
            textvariable=self.signal_meta,
            bg=self.card,
            fg=self.muted,
            font=self.fonts["small"],
        ).pack(anchor="w", pady=(10, 0))

        metrics = tk.Frame(content, bg=self.bg)
        metrics.pack(fill="x", padx=16)
        self.metric_vars: dict[str, tk.StringVar] = {}
        self.metric_hint_vars: dict[str, tk.StringVar] = {}
        metric_labels = ["Portfolio", "P&L", "Data Conf.", "SPY Beta", "Annual Vol", "Top-3 Conc.", "Warnings", "Claude Cost"]
        metric_tips = {
            "Portfolio": "Total market value of all your holdings.",
            "P&L": "Unrealized profit or loss across your portfolio.",
            "Data Conf.": "How fresh and complete the market data is.",
            "SPY Beta": "Portfolio volatility vs S&P 500. >1 = more volatile than the market.",
            "Annual Vol": "Estimated annualized portfolio volatility (20-day rolling).",
            "Top-3 Conc.": "Weight of your three largest positions. High concentration = higher risk.",
            "Warnings": "Number of quality-gate alerts from the latest report.",
            "Claude Cost": "How much this report cost in Claude API usage (USD).",
        }
        for col in range(4):
            metrics.columnconfigure(col, weight=1, uniform="metrics")
        for index, label in enumerate(metric_labels):
            row = index // 4
            col = index % 4
            box = tk.Frame(
                metrics,
                bg=self.card,
                highlightthickness=1,
                highlightbackground=self.border,
                padx=16,
                pady=14,
            )
            box.grid(row=row, column=col, sticky="ew", padx=(0 if col == 0 else 6, 0), pady=(0, 6))
            tk.Label(
                box,
                text=label.upper(),
                bg=self.card,
                fg=self.subtle,
                font=self.fonts["small"],
            ).pack(anchor="w")
            var = tk.StringVar(value="—")
            hint = tk.StringVar(value="")
            self.metric_vars[label] = var
            self.metric_hint_vars[label] = hint
            tk.Label(
                box,
                textvariable=var,
                bg=self.card,
                fg=self.text_strong,
                font=self.fonts["heading"],
            ).pack(anchor="w", pady=(6, 0))
            tk.Label(
                box,
                textvariable=hint,
                bg=self.card,
                fg=self.muted,
                font=self.fonts["small"],
            ).pack(anchor="w", pady=(4, 0))
            if label in metric_tips:
                self._tip(box, metric_tips[label])

        action_panel, self.action_cards = self._dashboard_panel(content, "Recommended Actions")
        action_panel.pack(fill="x", padx=16, pady=(16, 10))

        middle = ttk.Frame(content)
        middle.pack(fill="both", expand=True, padx=16, pady=(0, 10))
        left, self.warning_cards = self._dashboard_panel(middle, "Risk Alerts")
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        right, risk_body = self._dashboard_panel(middle, "Portfolio Risk Summary")
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.risk_text = self._readonly_text(risk_body, height=11)

        lower = ttk.Frame(content)
        lower.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        trailing_panel, self.stop_cards = self._dashboard_panel(lower, "Price Alerts")
        trailing_panel.pack(side="left", fill="both", expand=True, padx=(0, 8))
        drift_panel, signal_text_body = self._dashboard_panel(lower, "Market Overview")
        drift_panel.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.signal_text = self._readonly_text(signal_text_body, height=11)

    def _build_buy_signals_tab(self) -> None:
        top = ttk.Frame(self.buy_signals_tab)
        top.pack(fill="x", padx=16, pady=16)
        self.buy_signal_button = ttk.Button(top, text="Check for Opportunities", command=self.start_buy_signal_refresh)
        self.buy_signal_button.pack(side="left")
        self._tip(self.buy_signal_button, "Refresh buy and add signals from the latest report and live market data")
        self.buy_action_filter = tk.StringVar(value="All actions")
        self.buy_readiness_filter = tk.StringVar(value="All readiness")
        self.buy_source_filter = tk.StringVar(value="All sources")
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
        ttk.Combobox(
            top,
            textvariable=self.buy_source_filter,
            values=["All sources", "Missing catalyst", "Missing analyst", "Quote not timestamped", "Source degraded"],
            state="readonly",
            width=20,
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
            [
                "readiness",
                "ticker",
                "action",
                "conviction",
                "amount",
                "price",
                "source_conf",
                "quote",
                "catalyst",
                "analyst",
                "why",
                "change_mind",
                "warnings",
            ],
            [120, 80, 90, 90, 120, 110, 120, 90, 90, 90, 360, 360, 240],
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
        self.run_button = ttk.Button(actions, text="Generate Report", style="Accent.TButton", command=self.start_report_run)
        self.run_button.pack(side="left")
        self._tip(self.run_button, "Run AI-powered portfolio analysis (~$0.22 with Sonnet, ~90 seconds)")
        preview_btn = ttk.Button(actions, text="Preview My Holdings", command=self.preview_holdings)
        preview_btn.pack(side="left", padx=8)
        self._tip(preview_btn, "Show a preview of positions from your holdings CSV")
        checklist_btn = ttk.Button(actions, text="Check Setup", command=self.refresh_run_preflight)
        checklist_btn.pack(side="left", padx=8)
        self._tip(checklist_btn, "Validate API keys, CSV files, budget, and update status before spending on Claude")
        demo_btn = ttk.Button(actions, text="Run Demo Smoke Test", command=self.run_demo_smoke_check)
        demo_btn.pack(side="left", padx=8)
        self._tip(demo_btn, "Validate bundled sample data and UI view models without Anthropic spend")
        self.run_status = tk.StringVar(value=f"Ready — press {MOD_LABEL}N to get started.")
        ttk.Label(actions, textvariable=self.run_status, background=self.panel, foreground=self.muted).pack(side="left", padx=12)

        readiness = self._panel(self.run_tab, "Ready To Run")
        readiness.pack(fill="x", padx=16, pady=(0, 16))
        self.run_readiness_summary = tk.StringVar(value="Click Check Setup to verify paid-run readiness.")
        ttk.Label(readiness, textvariable=self.run_readiness_summary, style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
        self.run_readiness_tree = self._make_tree(
            readiness,
            ["step", "status", "detail", "action"],
            [150, 90, 520, 440],
            height=5,
        )
        self.run_readiness_tree.pack(fill="x")

        preflight = self._panel(self.run_tab, "Pre-run Checklist")
        preflight.pack(fill="x", padx=16, pady=(0, 16))
        self.run_preflight_tree = self._make_tree(
            preflight,
            ["check", "status", "detail", "action"],
            [150, 90, 520, 440],
            height=7,
        )
        self.run_preflight_tree.pack(fill="x")

        # Progress bar (hidden until report runs)
        self._report_progress_frame = tk.Frame(form, bg=self.panel)
        self._report_progress_frame.pack(fill="x", pady=(10, 0))
        self._report_progress = ttk.Progressbar(self._report_progress_frame, mode="indeterminate", length=400)
        self._report_progress.pack(side="left")
        self._report_elapsed_var = tk.StringVar(value="")
        tk.Label(
            self._report_progress_frame,
            textvariable=self._report_elapsed_var,
            bg=self.panel,
            fg=self.muted,
            font=self.fonts["small"],
        ).pack(side="left", padx=10)
        self._report_progress_frame.pack_forget()

        locations = self._panel(self.run_tab, "File Locations")
        locations.pack(fill="x", padx=16, pady=(0, 16))
        self.locations_text = tk.Text(
            locations,
            height=6,
            wrap="word",
            bg=self.surface,
            fg=self.text,
            font=self.fonts["small"],
            relief="flat",
            padx=10,
            pady=8,
        )
        self.locations_text.pack(fill="x")
        self.locations_text.insert("1.0", self._locations_summary())
        self.locations_text.configure(state="disabled")

        self.console_text = ScrolledText(
            self.run_tab,
            height=22,
            wrap="word",
            bg=self.surface,
            fg=self.text,
            font=self.fonts["mono"],
            insertbackground=self.text,
            relief="flat",
            padx=12,
            pady=10,
        )
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
        self.report_paths_text = tk.Text(
            self.report_paths_panel,
            height=5,
            wrap="none",
            bg=self.surface,
            fg=self.text,
            font=self.fonts["small"],
            relief="flat",
            padx=8,
            pady=6,
        )
        self.report_paths_text.pack(fill="x")
        self.refresh_report_paths_text()

        review_panel = self._panel(self.report_tab, "Report Review")
        review_panel.pack(fill="x", padx=16, pady=(0, 12))
        self.report_review_status = tk.StringVar(value="Load a report to review quality gates and decision feedback.")
        ttk.Label(review_panel, textvariable=self.report_review_status, style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
        self.report_review_tree = self._make_tree(
            review_panel,
            ["metric", "status", "value", "next_action"],
            [190, 120, 160, 720],
            height=6,
        )
        self.report_review_tree.pack(fill="x")

        checklist_panel = ttk.Frame(review_panel, style="Panel.TFrame")
        checklist_panel.pack(fill="x", pady=(10, 0))
        ttk.Label(checklist_panel, text="Execution checklist", style="Subheading.TLabel").pack(anchor="w", pady=(0, 6))
        self.report_review_checklist_tree = self._make_tree(
            checklist_panel,
            ["ticker", "check", "required", "status", "detail"],
            [90, 190, 90, 100, 720],
            height=5,
        )
        self.report_review_checklist_tree.pack(fill="x")

        decision_bar = ttk.Frame(review_panel, style="Panel.TFrame")
        decision_bar.pack(fill="x", pady=(8, 0))
        ttk.Label(decision_bar, text="Decision", style="Muted.TLabel").pack(side="left")
        self.report_review_decision_var = tk.StringVar(value="")
        self.report_review_decision_box = ttk.Combobox(
            decision_bar,
            textvariable=self.report_review_decision_var,
            values=[],
            state="readonly",
            width=48,
        )
        self.report_review_decision_box.pack(side="left", padx=8)
        self.report_review_choice_var = tk.StringVar(value="accepted")
        self.report_review_choice_box = ttk.Combobox(
            decision_bar,
            textvariable=self.report_review_choice_var,
            values=["accepted", "ignored", "modified", "delayed", "watch", "executed"],
            state="readonly",
            width=12,
        )
        self.report_review_choice_box.pack(side="left", padx=(0, 8))
        ttk.Button(decision_bar, text="Save Feedback", command=self._save_report_review_decision).pack(side="left")
        ttk.Button(decision_bar, text="Mark Checklist Reviewed", command=self._save_report_review_checklist).pack(side="left", padx=(8, 0))

        self.report_text = ScrolledText(
            self.report_tab,
            wrap="word",
            bg=self.panel,
            fg=self.text,
            insertbackground=self.text,
            relief="flat",
            padx=20,
            pady=18,
            font=self.fonts["body"],
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
        self.history_paths_text = tk.Text(
            paths_panel,
            height=8,
            wrap="none",
            bg=self.surface,
            fg=self.text,
            font=self.fonts["small"],
            relief="flat",
            padx=8,
            pady=6,
        )
        self.history_paths_text.pack(fill="x")
        self.history_list = tk.Listbox(
            left,
            bg=self.surface,
            fg=self.text,
            selectbackground=self.border,
            selectforeground=self.text_strong,
            font=self.fonts["small"],
            activestyle="none",
            relief="flat",
        )
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
            bg=self.panel,
            fg=self.text,
            insertbackground=self.text,
            relief="flat",
            padx=20,
            pady=18,
            font=self.fonts["body"],
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
        _learning_refresh = ttk.Button(toolbar, text="Refresh learning view", command=self.refresh_learning_tab)
        _learning_refresh.pack(side="left")
        self._refresh_buttons["learning"] = _learning_refresh
        self.learning_status = tk.StringVar(value="Open this tab to load the learning view.")
        ttk.Label(toolbar, textvariable=self.learning_status, style="Muted.TLabel").pack(side="left", padx=14)

        # Three stacked panels: edge by horizon, sizing-by-conviction, theses.
        edge_panel = self._panel(self.learning_tab, "Your edge by horizon (user_avg_return %)")
        edge_panel.pack(fill="x", padx=16, pady=(0, 12))
        self.learning_edge_text = tk.Text(
            edge_panel,
            height=4,
            wrap="word",
            bg=self.surface,
            fg=self.text,
            font=self.fonts["mono"],
            insertbackground=self.text,
            relief="flat",
            padx=10,
            pady=8,
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
            bg=self.surface,
            fg=self.text,
            font=self.fonts["body"],
            insertbackground=self.text,
            relief="flat",
            padx=10,
            pady=8,
        )
        self.learning_drift_text.pack(fill="both", expand=True)
        self.learning_drift_text.configure(state="disabled")

    def refresh_learning_tab(self) -> None:
        """Fetch a fresh learning_view off the UI thread and re-render."""
        self.learning_status.set("Loading learning metrics…")
        on_success, on_error = self._guarded_callbacks(
            "learning",
            self._render_learning_view,
            lambda exc: self.learning_status.set(f"Failed to load learning view: {exc}"),
        )
        self._run_in_background(learning_view, on_success, on_error=on_error)

    def _render_learning_view(self, view: dict) -> None:
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
        _perf_refresh = ttk.Button(toolbar, text="Refresh", command=self.refresh_performance_tab)
        _perf_refresh.pack(side="left")
        self._refresh_buttons["performance"] = _perf_refresh
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
        perf_tooltips = {
            "Sharpe": "Return per unit of total volatility. Higher is better; >1 is good.",
            "Sortino": "Like Sharpe but penalizes only downside volatility. Higher is better.",
            "Calmar": "Annualized return divided by max drawdown. Higher means better return for the pain endured.",
            "VaR 95%": "Value at Risk: the per-session loss you'd expect to exceed only 5% of the time.",
            "CVaR 95%": "Expected loss on the worst 5% of sessions (the average of the tail beyond VaR).",
            "Max drawdown": "Largest peak-to-trough drop in portfolio value over the period.",
            "Beta": "Sensitivity to the S&P 500. >1 = moves more than the market.",
            "Volatility": "Annualized standard deviation of session returns.",
        }
        for i, label in enumerate(
            [
                "Cumulative return",
                "Annualized return",
                "Volatility",
                "Sharpe",
                "Sortino",
                "Calmar",
                "VaR 95%",
                "CVaR 95%",
                "Max drawdown",
                "SPY return",
                "Beta",
                "Alpha (ann.)",
            ]
        ):
            var = tk.StringVar(value="—")
            self.performance_metric_vars[label] = var
            cell = tk.Frame(grid, bg=self.card, padx=16, pady=12, highlightthickness=1, highlightbackground=self.border)
            cell.grid(row=i // 4, column=i % 4, sticky="ew", padx=4, pady=4)
            grid.columnconfigure(i % 4, weight=1, uniform="perf_metrics")
            name_label = tk.Label(
                cell,
                text=label.upper(),
                bg=self.card,
                fg=self.subtle,
                font=self.fonts["small"],
            )
            name_label.pack(anchor="w")
            tk.Label(
                cell,
                textvariable=var,
                bg=self.card,
                fg=self.text_strong,
                font=self.fonts["heading"],
            ).pack(anchor="w", pady=(6, 0))
            if label in perf_tooltips:
                self._tip(cell, perf_tooltips[label])
                self._tip(name_label, perf_tooltips[label])

        # Sparkline canvas — portfolio (and SPY) rebased to 100 at start.
        chart_panel = self._panel(self.performance_tab, "Portfolio value (rebased to 100 at start)")
        chart_panel.pack(fill="x", padx=16, pady=(0, 12))
        self.performance_canvas = tk.Canvas(
            chart_panel,
            height=180,
            bg=self.surface,
            highlightthickness=0,
            bd=0,
        )
        self.performance_canvas.pack(fill="x", expand=True)
        legend = tk.Frame(chart_panel, bg=self.panel)
        legend.pack(fill="x", pady=(8, 0))
        tk.Label(legend, text="● Portfolio", bg=self.panel, fg=self.accent, font=self.fonts["small"]).pack(side="left", padx=8)
        tk.Label(legend, text="● SPY", bg=self.panel, fg=self.info, font=self.fonts["small"]).pack(side="left", padx=8)

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
        """Recompute and re-render the Performance tab without freezing the UI.

        ``portfolio_performance_summary`` rebuilds the time series and (when
        enabled) fetches SPY over the network, so it runs off the Tk thread.
        """
        lookback_label = self.performance_lookback_var.get()
        lookback_days = {"Last 30 days": 30, "Last 90 days": 90, "Last 365 days": 365}.get(lookback_label)
        fetch_spy = bool(self.performance_fetch_spy_var.get())
        self.performance_status.set("Computing performance metrics…")
        on_success, on_error = self._guarded_callbacks(
            "performance",
            self._render_performance_view,
            lambda exc: self.performance_status.set(f"Failed to compute performance: {exc}"),
        )
        self._run_in_background(
            lambda: portfolio_performance_summary(lookback_days=lookback_days, fetch_spy=fetch_spy),
            on_success,
            on_error=on_error,
        )

    def _render_performance_view(self, view: dict) -> None:
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
        m["Sortino"].set(f"{view['sortino']:.2f}" if view.get("sortino") is not None else "—")
        m["Calmar"].set(f"{view['calmar']:.2f}" if view.get("calmar") is not None else "—")
        m["VaR 95%"].set(_pct(view.get("var_95_pct"), digits=2) if view.get("var_95_pct") is not None else "—")
        m["CVaR 95%"].set(_pct(view.get("cvar_95_pct"), digits=2) if view.get("cvar_95_pct") is not None else "—")
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

    # ── Outcomes tab ────────────────────────────────────────────────────────
    def _build_outcomes_tab(self) -> None:
        toolbar = ttk.Frame(self.outcomes_tab)
        toolbar.pack(fill="x", padx=16, pady=(16, 8))
        _outcomes_refresh = ttk.Button(toolbar, text="Refresh", command=self.refresh_outcomes_tab)
        _outcomes_refresh.pack(side="left")
        self._refresh_buttons["outcomes"] = _outcomes_refresh
        self.outcomes_status = tk.StringVar(value="Open this tab to score recommendation outcomes.")
        ttk.Label(toolbar, textvariable=self.outcomes_status, style="Muted.TLabel").pack(side="left", padx=14)

        metrics_panel = self._panel(self.outcomes_tab, "Outcome metrics")
        metrics_panel.pack(fill="x", padx=16, pady=(0, 12))
        self.outcomes_metric_vars: dict[str, tk.StringVar] = {}
        grid = ttk.Frame(metrics_panel, style="Panel.TFrame")
        grid.pack(fill="x")
        labels = [
            "Scored windows",
            "Hit rate",
            "Avg action",
            "Avg alpha",
            "BUY/ADD success",
            "Saved drawdown",
            "Claude cost",
            "Cost/useful",
        ]
        for i, label in enumerate(labels):
            var = tk.StringVar(value="—")
            self.outcomes_metric_vars[label] = var
            cell = tk.Frame(grid, bg=self.card, padx=16, pady=12, highlightthickness=1, highlightbackground=self.border)
            cell.grid(row=i // 4, column=i % 4, sticky="ew", padx=4, pady=4)
            grid.columnconfigure(i % 4, weight=1, uniform="outcome_metrics")
            tk.Label(cell, text=label.upper(), bg=self.card, fg=self.subtle, font=self.fonts["small"]).pack(anchor="w")
            tk.Label(cell, textvariable=var, bg=self.card, fg=self.text_strong, font=self.fonts["heading"]).pack(anchor="w", pady=(6, 0))

        self.outcomes_summary_text = self._readonly_text(self.outcomes_tab, height=4)
        self.outcomes_summary_text.pack(fill="x", padx=16, pady=(0, 12))

        lessons_panel = self._panel(self.outcomes_tab, "Outcome lessons")
        lessons_panel.pack(fill="x", padx=16, pady=(0, 12))
        self.outcomes_lessons_tree = self._make_tree(
            lessons_panel,
            ["dimension", "bucket", "direction", "n", "hit_rate", "avg_action", "message"],
            [150, 150, 100, 60, 90, 110, 620],
            height=5,
        )
        self.outcomes_lessons_tree.pack(fill="x")

        body = ttk.PanedWindow(self.outcomes_tab, orient="vertical")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        top = ttk.Frame(body)
        bottom = ttk.Frame(body)
        body.add(top, weight=1)
        body.add(bottom, weight=2)

        action_panel = self._panel(top, "By action")
        action_panel.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self.outcomes_action_tree = self._make_tree(
            action_panel,
            ["bucket", "n", "avg_action", "avg_alpha", "hit_rate", "benchmark_win"],
            [100, 60, 120, 120, 100, 120],
            height=7,
        )

        horizon_panel = self._panel(top, "By horizon")
        horizon_panel.pack(side="left", fill="both", expand=True, padx=(6, 0))
        self.outcomes_horizon_tree = self._make_tree(
            horizon_panel,
            ["bucket", "n", "avg_action", "avg_alpha", "hit_rate", "benchmark_win"],
            [100, 60, 120, 120, 100, 120],
            height=7,
        )

        best_panel = self._panel(bottom, "Best recommendations")
        best_panel.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self.outcomes_best_tree = self._make_tree(
            best_panel,
            ["ticker", "action", "horizon", "return", "alpha", "benchmark", "id"],
            [80, 80, 80, 90, 90, 90, 280],
            height=9,
        )

        worst_panel = self._panel(bottom, "Worst recommendations")
        worst_panel.pack(side="left", fill="both", expand=True, padx=(6, 0))
        self.outcomes_worst_tree = self._make_tree(
            worst_panel,
            ["ticker", "action", "horizon", "return", "alpha", "benchmark", "id"],
            [80, 80, 80, 90, 90, 90, 280],
            height=9,
        )

    def refresh_outcomes_tab(self) -> None:
        """Score recommendation outcomes off the UI thread, then render."""
        self.outcomes_status.set("Scoring recommendation outcomes…")
        on_success, on_error = self._guarded_callbacks(
            "outcomes",
            self._render_outcomes_view,
            lambda exc: self.outcomes_status.set(f"Failed to score outcomes: {exc}"),
        )
        self._run_in_background(outcomes_view, on_success, on_error=on_error)

    def _render_outcomes_view(self, view: dict) -> None:
        summary = view.get("summary") or {}
        overall = summary.get("overall") or {}
        self.outcomes_status.set(
            f"{summary.get('scored_windows', 0)} scored windows · "
            f"{summary.get('pending_windows', 0)} pending · "
            f"{summary.get('error_count', 0)} pricing issue(s)"
        )

        def _pct(value, *, ratio: bool = False) -> str:
            if value is None:
                return "—"
            try:
                amount = float(value)
            except (TypeError, ValueError):
                return "—"
            return f"{amount:.0%}" if ratio else f"{amount:+.2f}%"

        def _money(value) -> str:
            try:
                return f"${float(value):.4f}"
            except (TypeError, ValueError):
                return "—"

        m = self.outcomes_metric_vars
        m["Scored windows"].set(str(summary.get("scored_windows", 0)))
        m["Hit rate"].set(_pct(overall.get("hit_rate"), ratio=True))
        m["Avg action"].set(_pct(overall.get("avg_action_return_pct")))
        m["Avg alpha"].set(_pct(overall.get("avg_alpha_vs_benchmark_pct")))
        m["BUY/ADD success"].set(_pct(summary.get("buy_add_success_rate"), ratio=True))
        m["Saved drawdown"].set(_pct(summary.get("trim_sell_saved_drawdown_avg_pct")))
        m["Claude cost"].set(_money(summary.get("estimated_claude_cost_usd")))
        m["Cost/useful"].set(_money(summary.get("cost_per_useful_window_usd")))

        self._set_readonly_text(
            self.outcomes_summary_text,
            view.get("prompt_summary")
            or summary.get("prompt_summary")
            or "No matured fixed-window recommendation outcomes yet. Refresh after enough trading days pass.",
        )

        self._replace_tree_rows(self.outcomes_action_tree, self._outcome_bucket_rows(summary.get("by_action") or {}))
        self._replace_tree_rows(self.outcomes_horizon_tree, self._outcome_bucket_rows(summary.get("by_horizon") or {}))
        lessons = []
        for row in view.get("lessons") or summary.get("lessons") or []:
            lessons.append(
                [
                    row.get("dimension") or "",
                    row.get("bucket") or "",
                    row.get("direction") or "",
                    row.get("n") or 0,
                    _pct(row.get("hit_rate"), ratio=True),
                    _pct(row.get("avg_action_return_pct")),
                    row.get("message") or "",
                ]
            )
        self._replace_tree_rows(self.outcomes_lessons_tree, lessons, tag_index=2)
        self._replace_tree_rows(self.outcomes_best_tree, self._outcome_example_rows(summary.get("best_recommendations") or []), tag_index=1)
        self._replace_tree_rows(
            self.outcomes_worst_tree,
            self._outcome_example_rows(summary.get("worst_recommendations") or []),
            tag_index=1,
        )

    def _outcome_bucket_rows(self, bucket: dict[str, Any]) -> list[list[Any]]:
        rows = []
        for label, stats in bucket.items():
            alpha = stats.get("avg_alpha_vs_benchmark_pct")
            rows.append(
                [
                    label,
                    stats.get("n", 0),
                    f"{stats.get('avg_action_return_pct', 0):+.2f}%",
                    f"{alpha:+.2f}%" if alpha is not None else "—",
                    f"{stats.get('hit_rate', 0):.0%}",
                    f"{stats.get('benchmark_win_rate', 0):.0%}",
                ]
            )
        return rows

    def _outcome_example_rows(self, rows: list[dict[str, Any]]) -> list[list[Any]]:
        out = []
        for row in rows[:20]:
            alpha = row.get("alpha_vs_benchmark_pct")
            out.append(
                [
                    row.get("ticker"),
                    row.get("action"),
                    row.get("horizon_days"),
                    f"{row.get('action_return_pct', 0):+.2f}%",
                    f"{alpha:+.2f}%" if alpha is not None else "—",
                    row.get("benchmark"),
                    row.get("id"),
                ]
            )
        return out

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
                series_to_draw.append(([v / spy_initial * 100.0 for v in spy["values"]], self.info))

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

    # ── Preferences tab (v1.23) ──────────────────────────────────────────────
    def _build_preferences_tab(self) -> None:
        """Form-based settings for common options."""
        import json

        settings_path = ROOT / "config" / "settings.json"
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            settings = {}

        content = self._scrollable_frame(self.prefs_subtab)

        # Account section
        acct = self._panel(content, "Account")
        acct.pack(fill="x", padx=16, pady=(16, 10))
        grid = ttk.Frame(acct, style="Panel.TFrame")
        grid.pack(fill="x")
        self._pref_budget_cad = tk.StringVar(value=str(settings.get("budget_cad", 3000)))
        self._pref_risk = tk.StringVar(value=settings.get("risk_tolerance", "aggressive"))
        self._pref_account = tk.StringVar(value=settings.get("account_type", "wealthsimple_premium_usd"))

        for col, (label, var, widget_type, options) in enumerate(
            [
                ("Investment budget (CAD)", self._pref_budget_cad, "entry", None),
                ("Risk tolerance", self._pref_risk, "combo", ["conservative", "moderate", "aggressive"]),
                ("Account type", self._pref_account, "combo", ["wealthsimple_premium_usd", "other"]),
            ]
        ):
            ttk.Label(grid, text=label, background=self.panel, foreground=self.muted).grid(row=0, column=col, sticky="w", padx=(0, 14))
            if widget_type == "combo":
                w = ttk.Combobox(grid, textvariable=var, values=options, state="readonly", width=24)
            else:
                w = ttk.Entry(grid, textvariable=var, width=16)
            w.grid(row=1, column=col, sticky="ew", padx=(0, 14))
            grid.columnconfigure(col, weight=1)

        # AI Model section
        model = self._panel(content, "AI Model")
        model.pack(fill="x", padx=16, pady=(0, 10))
        mgrid = ttk.Frame(model, style="Panel.TFrame")
        mgrid.pack(fill="x")
        current_model = settings.get("claude_model", "claude-sonnet-4-6")
        model_display = "Opus (deeper, ~$1.80/report)" if "opus" in current_model else "Sonnet (faster, ~$0.22/report)"
        self._pref_model = tk.StringVar(value=model_display)
        self._pref_two_pass = tk.BooleanVar(value=settings.get("enable_two_pass_review", True))

        ttk.Label(mgrid, text="AI model", background=self.panel, foreground=self.muted).grid(row=0, column=0, sticky="w", padx=(0, 14))
        model_combo = ttk.Combobox(
            mgrid,
            textvariable=self._pref_model,
            values=["Sonnet (faster, ~$0.22/report)", "Opus (deeper, ~$1.80/report)"],
            state="readonly",
            width=30,
        )
        model_combo.grid(row=1, column=0, sticky="ew", padx=(0, 14))
        self._tip(model_combo, "Sonnet is fast and cost-effective. Opus gives deeper analysis for complex portfolios.")
        mgrid.columnconfigure(0, weight=1)

        two_pass = ttk.Checkbutton(mgrid, text="Two-pass review (higher quality)", variable=self._pref_two_pass)
        two_pass.grid(row=1, column=1, sticky="w", padx=(0, 14))
        self._tip(two_pass, "First pass generates recommendations, second pass critiques them against quality gates.")
        mgrid.columnconfigure(1, weight=1)

        # Risk Controls section
        risk = self._panel(content, "Risk Controls")
        risk.pack(fill="x", padx=16, pady=(0, 10))
        rgrid = ttk.Frame(risk, style="Panel.TFrame")
        rgrid.pack(fill="x")
        self._pref_max_pos = tk.StringVar(value=str(settings.get("max_position_pct", 25)))
        self._pref_min_return = tk.StringVar(value=str(settings.get("min_net_expected_return_pct", 0.5)))

        for col, (label, var, tip) in enumerate(
            [
                ("Max position size (%)", self._pref_max_pos, "Largest any single stock can be as a percentage of your portfolio."),
                (
                    "Min expected return (%)",
                    self._pref_min_return,
                    "The trade must beat this return threshold after fees to be recommended.",
                ),
            ]
        ):
            ttk.Label(rgrid, text=label, background=self.panel, foreground=self.muted).grid(row=0, column=col, sticky="w", padx=(0, 14))
            w = ttk.Entry(rgrid, textvariable=var, width=10)
            w.grid(row=1, column=col, sticky="w", padx=(0, 14))
            self._tip(w, tip)
            rgrid.columnconfigure(col, weight=1)

        # Features section
        features = self._panel(content, "Features")
        features.pack(fill="x", padx=16, pady=(0, 10))
        self._pref_journal = tk.BooleanVar(value=settings.get("enable_decision_journal", True))
        self._pref_sentiment = tk.BooleanVar(value=settings.get("enable_sentiment", True))
        self._pref_enrichment = tk.BooleanVar(value=settings.get("enable_enrichment", True))

        for var, label, tip in [
            (self._pref_journal, "Track decision outcomes", "Record what happened after each recommendation to improve future accuracy."),
            (self._pref_sentiment, "Analyze news sentiment", "Score news headlines to detect market mood shifts per stock."),
            (
                self._pref_enrichment,
                "Use enrichment APIs (Finnhub, Polygon, etc.)",
                "Fetch analyst ratings, earnings calendars, and options data from third-party APIs.",
            ),
        ]:
            cb = ttk.Checkbutton(features, text=label, variable=var)
            cb.pack(anchor="w", pady=2)
            self._tip(cb, tip)

        # Save / Reset buttons
        btn_frame = ttk.Frame(content)
        btn_frame.pack(fill="x", padx=16, pady=(10, 20))
        save_btn = ttk.Button(btn_frame, text="Save Preferences", style="Accent.TButton", command=self._save_preferences)
        save_btn.pack(side="left")
        self._tip(save_btn, "Save your preferences to config/settings.json")
        self._pref_status = tk.StringVar(value="")
        ttk.Label(btn_frame, textvariable=self._pref_status, style="Muted.TLabel").pack(side="left", padx=14)

    def _save_preferences(self) -> None:
        import json

        settings_path = ROOT / "config" / "settings.json"
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
        except Exception:
            settings = {}

        # Collect numeric-field parse errors so we can refuse to silently keep
        # a stale value while telling the user "saved".
        invalid: list[str] = []

        def _num(raw: str, fallback: float, label: str) -> float:
            try:
                return float(str(raw).strip() or fallback)
            except ValueError:
                invalid.append(label)
                return fallback

        budget_cad = _num(self._pref_budget_cad.get(), 3000, "Investment budget (CAD)")
        max_pos = _num(self._pref_max_pos.get(), 25, "Max position %")
        min_return = _num(self._pref_min_return.get(), 0.5, "Min net expected return %")

        if invalid:
            joined = ", ".join(invalid)
            self._pref_status.set(f"Not saved — these must be numbers: {joined}")
            self._set_status(f"Preferences not saved — invalid: {joined}", tone="error")
            return

        settings["budget_cad"] = budget_cad
        settings["max_position_pct"] = max_pos
        settings["min_net_expected_return_pct"] = min_return
        settings["risk_tolerance"] = self._pref_risk.get()
        settings["account_type"] = self._pref_account.get()

        model_choice = self._pref_model.get()
        if "Opus" in model_choice:
            settings["claude_model"] = "claude-opus-4-7"
        else:
            settings["claude_model"] = "claude-sonnet-4-6"
        settings["enable_two_pass_review"] = self._pref_two_pass.get()

        settings["enable_decision_journal"] = self._pref_journal.get()
        settings["enable_sentiment"] = self._pref_sentiment.get()
        settings["enable_enrichment"] = self._pref_enrichment.get()

        try:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
            self._pref_status.set("Preferences saved.")
            self._set_status("Preferences saved.", tone="success")
        except Exception as exc:
            self._pref_status.set(f"Save failed: {exc}")
            self._set_status("Failed to save preferences.", tone="error")

    # ── Data Files tab ──────────────────────────────────────────────────────
    def _build_data_files_tab(self) -> None:
        toolbar = ttk.Frame(self.data_files_tab)
        toolbar.pack(fill="x", padx=16, pady=16)
        ttk.Button(toolbar, text="Refresh", command=self.refresh_data_files_tab).pack(side="left")
        ttk.Button(toolbar, text="Save Current Run Paths", command=self.save_current_data_file_paths).pack(side="left", padx=8)
        ttk.Button(toolbar, text="Export Support Bundle", command=self.export_support_bundle_from_desktop).pack(side="left", padx=8)
        ttk.Button(toolbar, text="Open Workspace", command=lambda: self._open_data_location("Workspace")).pack(side="left", padx=8)
        ttk.Button(toolbar, text="Open Reports", command=lambda: self._open_data_location("Reports folder")).pack(side="left", padx=8)
        ttk.Button(toolbar, text="Open Logs", command=lambda: self._open_data_location("Recommendation logs")).pack(side="left", padx=8)
        ttk.Button(toolbar, text="Open Uploads", command=lambda: self._open_data_location("Uploads folder")).pack(side="left", padx=8)
        self.data_files_status = tk.StringVar(value="Open this tab to inspect workspace files.")
        ttk.Label(toolbar, textvariable=self.data_files_status, style="Muted.TLabel").pack(side="left", padx=12)

        readiness = self._panel(self.data_files_tab, "Setup Readiness")
        readiness.pack(fill="x", padx=16, pady=(0, 12))
        self.setup_readiness_tree = self._make_tree(
            readiness,
            ["check", "status", "detail", "action"],
            [170, 90, 600, 360],
            height=8,
        )
        self.setup_readiness_tree.pack(fill="x")

        recovery = self._panel(self.data_files_tab, "Fix Setup")
        recovery.pack(fill="x", padx=16, pady=(0, 12))
        self.setup_recovery_tree = self._make_tree(
            recovery,
            ["step", "status", "title", "detail", "action"],
            [70, 100, 210, 560, 360],
            height=5,
        )
        self.setup_recovery_tree.pack(fill="x")

        files = self._panel(self.data_files_tab, "Data Files / Workspace")
        files.pack(fill="x", padx=16, pady=(0, 12))
        self.data_files_tree = self._make_tree(
            files,
            ["resource", "status", "path", "detail", "action"],
            [170, 90, 430, 330, 360],
            height=7,
        )
        self.data_files_tree.pack(fill="x")

        candidates = self._panel(self.data_files_tab, "CSV Candidates To Confirm")
        candidates.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.csv_candidate_tree = self._make_tree(
            candidates,
            ["kind", "recommended", "status", "filename", "age_hours", "rows", "path", "action"],
            [90, 110, 100, 240, 90, 70, 430, 320],
            height=8,
        )
        self.csv_candidate_tree.pack(fill="both", expand=True)
        self._data_file_locations: dict[str, Path] = {}
        self.refresh_data_files_tab()

    def refresh_data_files_tab(self) -> None:
        try:
            view = data_files_view()
        except Exception as exc:  # noqa: BLE001
            self.data_files_status.set(f"Failed to load data files: {exc}")
            return
        try:
            setup = setup_readiness_view()
            readiness_rows = [
                [
                    row.get("check") or "",
                    row.get("status") or "",
                    row.get("detail") or "",
                    row.get("action") or "",
                ]
                for row in setup.get("rows") or []
            ]
            self._replace_tree_rows(self.setup_readiness_tree, readiness_rows)
            recovery_rows = [
                [
                    str(row.get("step") or ""),
                    row.get("status") or "",
                    row.get("title") or "",
                    row.get("detail") or "",
                    row.get("action") or "",
                ]
                for row in setup.get("recovery_steps") or []
            ]
            self._replace_tree_rows(self.setup_recovery_tree, recovery_rows, tag_index=1)
        except Exception as exc:  # noqa: BLE001
            self._replace_tree_rows(self.setup_readiness_tree, [["Setup", "FAIL", str(exc), "Open Diagnostics."]])
            self._replace_tree_rows(self.setup_recovery_tree, [["", "FAIL", "Setup recovery failed", str(exc), "Open Diagnostics."]])

        candidate_rows = []
        try:
            for kind in ("holdings", "activities"):
                for row in csv_choice_view(kind):
                    candidate_rows.append(
                        [
                            kind.title(),
                            "YES" if row.get("recommended") else "",
                            row.get("status") or "",
                            row.get("filename") or "",
                            str(row.get("age_hours") if row.get("age_hours") is not None else ""),
                            str(row.get("row_count_hint") or ""),
                            row.get("path") or "",
                            row.get("action") or row.get("reason") or "",
                        ]
                    )
        except Exception as exc:  # noqa: BLE001
            candidate_rows = [["", "", "FAIL", "", "", "", "", str(exc)]]
        self._replace_tree_rows(self.csv_candidate_tree, candidate_rows)

        rows = []
        self._data_file_locations = {}
        for row in view.get("rows") or []:
            rows.append(
                [
                    row.get("resource") or "",
                    row.get("status") or "",
                    row.get("path") or "",
                    row.get("detail") or "",
                    row.get("action") or "",
                ]
            )
            if row.get("path"):
                self._data_file_locations[row.get("resource") or ""] = Path(row["path"])
        self._replace_tree_rows(self.data_files_tree, rows)
        fail = sum(1 for row in view.get("rows") or [] if row.get("status") == "FAIL")
        warn = sum(1 for row in view.get("rows") or [] if row.get("status") == "WARN")
        setup_status = ""
        try:
            setup_status = f" Setup: {setup.get('status')}."
        except Exception:
            pass
        self.data_files_status.set(f"{fail} blocking issue(s), {warn} warning(s).{setup_status}")

    def save_current_data_file_paths(self) -> None:
        try:
            path = save_selected_data_files(
                self.holdings_var.get().strip() or None,
                self.activities_var.get().strip() or None,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Could not save paths", str(exc))
            return
        self.data_files_status.set(f"Saved defaults to {relative_to_root(path)}.")
        self.refresh_data_files_tab()

    def _open_data_location(self, label: str) -> None:
        path = getattr(self, "_data_file_locations", {}).get(label)
        if not path:
            self.refresh_data_files_tab()
            path = getattr(self, "_data_file_locations", {}).get(label)
        if not path:
            return
        self._reveal_in_finder(path)

    def export_support_bundle_from_desktop(self) -> None:
        try:
            payload = export_support_bundle(include_demo_smoke=False)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Support bundle failed", str(exc))
            return
        summary = payload.get("summary") or ""
        self.data_files_status.set(summary)
        output_path = payload.get("output_path")
        if payload.get("ok") and output_path:
            self._reveal_in_finder(Path(output_path))
        else:
            messagebox.showerror("Support bundle failed", summary or payload.get("error") or "Unknown error")

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
            bg=self.surface,
            fg=self.text,
            font=self.fonts["mono"],
            insertbackground=self.text,
            relief="flat",
            padx=10,
            pady=8,
        )
        self.schedule_preview_text.pack(fill="both", expand=True)
        self.schedule_preview_text.configure(state="disabled")

    @staticmethod
    def _coerce_time_field(value: str, *, lo: int, hi: int) -> int | None:
        """Parse a Spinbox hour/minute value, returning None if it is not a
        whole number in [lo, hi].  ttk.Spinbox lets the user type free text,
        so a bare int() here used to crash Install/Preview with a ValueError."""
        try:
            parsed = int(str(value).strip())
        except (ValueError, TypeError):
            return None
        return parsed if lo <= parsed <= hi else None

    def _selected_schedule_times(self) -> list:
        from src.scheduling import ScheduleTime

        out = []
        for slot in self.schedule_slots:
            if not slot["enabled"].get():
                continue
            hour = self._coerce_time_field(slot["hour"].get(), lo=0, hi=23)
            minute = self._coerce_time_field(slot["minute"].get(), lo=0, hi=59)
            if hour is None or minute is None:
                # Skip a slot with an out-of-range / non-numeric entry rather
                # than crashing the whole Install/Preview action.
                continue
            out.append(
                ScheduleTime(
                    hour=hour,
                    minute=minute,
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
        # install_schedule shells out to launchctl/schtasks — run it off the UI thread.
        self.schedule_status.set("Installing schedule…")
        self._run_in_background(
            lambda: install_schedule(times),
            self._schedule_install_done,
            on_error=lambda exc: messagebox.showerror("Install failed", str(exc)),
        )

    def _schedule_install_done(self, result) -> None:
        if result.ok:
            messagebox.showinfo("Schedule installed", f"{result.message}\n\nBackend: {result.backend}\n{result.path}")
        else:
            messagebox.showerror("Install failed", result.message + (f"\n\n{result.error}" if result.error else ""))
        self.refresh_schedule_tab()

    def _uninstall_schedule_clicked(self) -> None:
        from src.scheduling import uninstall_schedule

        self.schedule_status.set("Removing schedule…")
        self._run_in_background(
            uninstall_schedule,
            self._schedule_uninstall_done,
            on_error=lambda exc: messagebox.showerror("Uninstall failed", str(exc)),
        )

    def _schedule_uninstall_done(self, result) -> None:
        if result.ok:
            messagebox.showinfo("Schedule removed", result.message)
        else:
            messagebox.showerror("Uninstall failed", result.message)
        self.refresh_schedule_tab()

    def _send_test_notification(self) -> None:
        from src.notifications import send

        # The notification backend can shell out to osascript/notify-send.
        self.schedule_status.set("Sending test notification…")
        self._run_in_background(
            lambda: send(
                "tech_stock test",
                "If you see this, native notifications are working.",
                channel="general",
            ),
            self._test_notification_done,
            on_error=lambda exc: self.schedule_status.set(f"Notification failed: {exc}"),
        )

    def _test_notification_done(self, result) -> None:
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
        _diag_refresh = ttk.Button(toolbar, text="Refresh", command=self.refresh_diagnostics_tab)
        _diag_refresh.pack(side="left")
        self._refresh_buttons["diagnostics"] = _diag_refresh
        ttk.Button(toolbar, text="Run App Self-Test", command=self.refresh_app_self_test).pack(side="left", padx=(8, 0))
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

        # Preflight table
        preflight_panel = self._panel(self.diagnostics_tab, "Preflight")
        preflight_panel.pack(fill="x", padx=16, pady=(0, 12))
        self.diagnostics_preflight_tree = self._make_tree(
            preflight_panel,
            ["check", "status", "detail"],
            [170, 90, 760],
            height=7,
        )
        self.diagnostics_preflight_tree.pack(fill="x")

        self_test_panel = self._panel(self.diagnostics_tab, "App Self-Test")
        self_test_panel.pack(fill="x", padx=16, pady=(0, 12))
        self.diagnostics_self_test_tree = self._make_tree(
            self_test_panel,
            ["check", "status", "detail", "action"],
            [160, 90, 520, 420],
            height=5,
        )
        self.diagnostics_self_test_tree.pack(fill="x", pady=(0, 8))
        self.diagnostics_self_test_text = tk.Text(
            self_test_panel,
            height=5,
            wrap="word",
            bg=self.surface,
            fg=self.text,
            font=self.fonts["mono"],
            insertbackground=self.text,
            relief="flat",
            padx=10,
            pady=8,
        )
        self.diagnostics_self_test_text.pack(fill="x")
        self.diagnostics_self_test_text.configure(state="disabled")

        csv_panel = self._panel(self.diagnostics_tab, "CSV Health")
        csv_panel.pack(fill="x", padx=16, pady=(0, 12))
        self.diagnostics_csv_tree = self._make_tree(
            csv_panel,
            ["type", "status", "detected", "age_hours", "path", "action"],
            [100, 90, 140, 90, 420, 360],
            height=2,
        )
        self.diagnostics_csv_tree.pack(fill="x")

        coverage_panel = self._panel(self.diagnostics_tab, "Source Coverage")
        coverage_panel.pack(fill="x", padx=16, pady=(0, 12))
        self.diagnostics_source_coverage_tree = self._make_tree(
            coverage_panel,
            ["source", "status", "evidence", "action"],
            [170, 100, 460, 500],
            height=8,
        )
        self.diagnostics_source_coverage_tree.pack(fill="x")

        provenance_panel = self._panel(self.diagnostics_tab, "Source Provenance")
        provenance_panel.pack(fill="x", padx=16, pady=(0, 12))
        provenance_filter_bar = ttk.Frame(provenance_panel, style="Panel.TFrame")
        provenance_filter_bar.pack(fill="x", pady=(0, 8))
        self.provenance_status_filter_var = tk.StringVar(value="problem")
        self.provenance_source_filter_var = tk.StringVar(value="all")
        self.provenance_ticker_filter_var = tk.StringVar(value="")
        ttk.Label(provenance_filter_bar, text="Status", style="Muted.TLabel").pack(side="left")
        ttk.Combobox(
            provenance_filter_bar,
            textvariable=self.provenance_status_filter_var,
            values=["all", "problem", "OK", "PARTIAL", "MISSING", "DEGRADED"],
            state="readonly",
            width=10,
        ).pack(side="left", padx=(4, 12))
        ttk.Label(provenance_filter_bar, text="Source", style="Muted.TLabel").pack(side="left")
        ttk.Entry(provenance_filter_bar, textvariable=self.provenance_source_filter_var, width=16).pack(side="left", padx=(4, 12))
        ttk.Label(provenance_filter_bar, text="Ticker", style="Muted.TLabel").pack(side="left")
        ttk.Entry(provenance_filter_bar, textvariable=self.provenance_ticker_filter_var, width=12).pack(side="left", padx=(4, 12))
        ttk.Button(provenance_filter_bar, text="Apply", command=self.refresh_diagnostics_tab).pack(side="left")
        self.diagnostics_source_provenance_tree = self._make_tree(
            provenance_panel,
            ["ticker", "source", "status", "provider", "timestamp_field", "action"],
            [90, 120, 90, 180, 260, 420],
            height=8,
        )
        self.diagnostics_source_provenance_tree.pack(fill="x")

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
        ttk.Button(bundle_buttons, text="Export support zip", command=self.export_support_bundle_from_desktop).pack(side="left", padx=8)
        ttk.Button(bundle_buttons, text="Open log folder", command=self._open_diagnostics_log_folder).pack(side="left", padx=8)
        self.diagnostics_support_preview_tree = self._make_tree(
            bundle_panel,
            ["item", "included", "detail"],
            [240, 90, 820],
            height=6,
        )
        self.diagnostics_support_preview_tree.pack(fill="x", pady=(0, 8))
        self.diagnostics_bundle_text = tk.Text(
            bundle_panel,
            height=8,
            wrap="none",
            bg=self.surface,
            fg=self.text,
            font=self.fonts["mono"],
            insertbackground=self.text,
            relief="flat",
            padx=10,
            pady=8,
        )
        self.diagnostics_bundle_text.pack(fill="x")
        self.diagnostics_bundle_text.configure(state="disabled")

    def refresh_app_self_test(self) -> None:
        """Run the shared no-spend app self-test and render it in Diagnostics."""
        if not hasattr(self, "diagnostics_self_test_tree"):
            return
        try:
            view = app_self_test_view()
        except Exception as exc:  # noqa: BLE001
            self._replace_tree_rows(
                self.diagnostics_self_test_tree,
                [["App self-test", "FAIL", str(exc), "Open Diagnostics or run doctor from the terminal."]],
            )
            self._set_readonly_text(self.diagnostics_self_test_text, f"App self-test failed: {exc}")
            return
        rows = [
            [
                row.get("check") or "",
                row.get("status") or "",
                row.get("detail") or "",
                row.get("action") or "",
            ]
            for row in view.get("rows") or []
        ]
        self._replace_tree_rows(self.diagnostics_self_test_tree, rows, tag_index=1)
        self._set_readonly_text(self.diagnostics_self_test_text, view.get("support_summary") or "")
        self.diagnostics_status.set(f"App self-test: {view.get('status')} · {view.get('next_action') or ''}")

    def refresh_diagnostics_tab(self) -> None:
        """Collect diagnostics + the support-bundle preview off the UI thread.

        ``diagnostics_view`` aggregates the event log and ``support_bundle_*``
        scan disk, so all three slow calls run on a worker thread and the panels
        render together once they return.
        """
        try:
            hours = int(self.diagnostics_window_var.get() or "24")
        except ValueError:
            hours = 24
        self.diagnostics_status.set("Collecting diagnostics…")

        def _work() -> dict:
            return {
                "hours": hours,
                "view": diagnostics_view(hours=hours),
                "preview": support_bundle_preview(include_demo_smoke=False),
                "bundle": diagnostics_support_bundle(limit=200),
            }

        on_success, on_error = self._guarded_callbacks(
            "diagnostics",
            self._render_diagnostics_view,
            lambda exc: self.diagnostics_status.set(f"Failed to load diagnostics: {exc}"),
        )
        self._run_in_background(_work, on_success, on_error=on_error)

    def _render_diagnostics_view(self, payload: dict) -> None:
        hours = payload["hours"]
        view = payload["view"]
        sources = view.get("sources") or {}
        ok = sum(1 for b in sources.values() if b.get("health") == "ok")
        degraded = sum(1 for b in sources.values() if b.get("health") == "degraded")
        down = sum(1 for b in sources.values() if b.get("health") == "down")
        self.diagnostics_status.set(
            f"{view.get('total_events', 0)} events in last {hours}h · "
            f"{len(sources)} source(s) · {ok} ok · {degraded} degraded · {down} down"
        )

        preflight_rows = []
        for row in (view.get("preflight") or {}).get("summary_rows") or []:
            preflight_rows.append([row.get("check") or "", row.get("status") or "", row.get("detail") or ""])
        self._replace_tree_rows(self.diagnostics_preflight_tree, preflight_rows)

        csv_rows = []
        csv_health = view.get("csv_health") or (view.get("preflight") or {}).get("csv_freshness") or {}
        for kind in ("holdings", "activities"):
            item = csv_health.get(kind) or {}
            csv_rows.append(
                [
                    kind.title(),
                    item.get("status") or "",
                    item.get("schema_kind") or "missing",
                    str(item.get("age_hours") if item.get("age_hours") is not None else ""),
                    str(item.get("latest_path") or "not found"),
                    item.get("action") or "",
                ]
            )
        self._replace_tree_rows(self.diagnostics_csv_tree, csv_rows)

        coverage_rows = []
        for row in (view.get("source_coverage") or {}).get("rows") or []:
            coverage_rows.append(
                [
                    row.get("source") or "",
                    row.get("status") or "",
                    row.get("evidence") or "",
                    row.get("action") or "",
                ]
            )
        self._replace_tree_rows(self.diagnostics_source_coverage_tree, coverage_rows, tag_index=1)

        provenance = source_provenance_view(
            status_filter=self.provenance_status_filter_var.get() or "all",
            source_filter=self.provenance_source_filter_var.get() or "all",
            ticker_filter=self.provenance_ticker_filter_var.get() or "",
        )
        provenance_rows = []
        for row in provenance.get("rows") or []:
            provenance_rows.append(
                [
                    row.get("ticker") or "",
                    row.get("source") or "",
                    row.get("status") or "",
                    row.get("provider") or "",
                    row.get("timestamp") or row.get("field") or "",
                    row.get("action") or "",
                ]
            )
        self._replace_tree_rows(self.diagnostics_source_provenance_tree, provenance_rows[:40], tag_index=2)

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

        # — Support bundle (preview + redacted text both fetched off-thread) —
        preview = payload["preview"]
        preview_rows = []
        for item in preview.get("files") or []:
            preview_rows.append([item.get("path") or "", "YES", item.get("description") or ""])
        excluded = ", ".join(str(item) for item in preview.get("excluded") or [])
        if excluded:
            preview_rows.append(["Excluded", "NO", excluded])
        self._replace_tree_rows(self.diagnostics_support_preview_tree, preview_rows)
        bundle = payload["bundle"]
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
        else:
            self.diagnostics_status.set("No log folder yet — run a report first.")

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

        self.editor_text = ScrolledText(
            self.editor_tab,
            wrap="none",
            bg=self.surface,
            fg=self.text,
            font=self.fonts["mono"],
            insertbackground=self.text,
            relief="flat",
            padx=12,
            pady=10,
        )
        self.editor_text.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.load_editor_file()

    def _build_health_tab(self) -> None:
        top = ttk.Frame(self.health_tab)
        top.pack(fill="x", padx=16, pady=16)
        check_btn = ttk.Button(top, text="Test Connections", command=self.start_connectivity_check)
        check_btn.pack(side="left")
        self._tip(check_btn, "Verify all API keys are working and data sources are reachable")
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
        self.api_paths_text = tk.Text(
            paths_panel,
            height=8,
            wrap="none",
            bg=self.surface,
            fg=self.text,
            font=self.fonts["small"],
            relief="flat",
            padx=8,
            pady=6,
        )
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
        self.update_text = tk.Text(
            body,
            height=18,
            wrap="word",
            bg=self.surface,
            fg=self.text,
            font=self.fonts["body"],
            insertbackground=self.text,
            relief="flat",
            padx=12,
            pady=10,
        )
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
        # api_key_inventory scans every discovered key file/keyring — off-thread.
        selected_env = self._selected_api_env_name()
        self.api_key_manager_status.set("Loading API keys…")
        on_success, on_error = self._guarded_callbacks(
            "api_keys",
            lambda inventory: self._render_api_key_manager(inventory, selected_env),
            lambda exc: self.api_key_manager_status.set(f"Failed to load API keys: {exc}"),
        )
        self._run_in_background(api_key_inventory, on_success, on_error=on_error)

    def _render_api_key_manager(self, inventory, selected_env: str) -> None:
        rows = []
        selected_status = ""
        for row in inventory:
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
        self._set_status(f"{env_name} saved", tone="success")
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
        cache_source = "cache" if getattr(info, "from_cache", False) else "live GitHub Releases"
        lines = [
            f"Current version: {info.current_version}",
            f"Latest version: {info.latest_version or 'unknown'}",
            f"Release page: {info.release_url}",
            f"Result source: {cache_source}",
        ]
        if getattr(info, "cache_path", None):
            lines.append(f"Update cache: {info.cache_path} (age {info.cache_age_seconds or 0}s)")
        if info.asset_name:
            lines.append(f"Platform asset: {info.asset_name}")
        lines.append(f"Platform asset available: {bool(getattr(info, 'asset_available', False))}")
        lines.append(f"Checksums available: {bool(getattr(info, 'checksum_available', False))}")
        asset_names = getattr(info, "asset_names", []) or []
        if asset_names:
            lines.append(f"Release assets: {', '.join(asset_names)}")
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
        tab_text = self._tab_name()
        if tab_text == "Reports":
            sub = self._sub_tab_name(self.reports_sub)
            key = "history" if sub == "History" else "report"
        else:
            key = "report"
            self._jump_to_tab(self.reports_tab, sub=self.report_subtab)
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
        fonts = self.fonts
        base_font = tkfont.Font(font=fonts["body"])
        mono_font = tkfont.Font(font=fonts["mono"])
        widget.configure(font=base_font)
        widget.tag_configure(
            "h1",
            font=fonts["title"],
            foreground=self.text_strong,
            spacing1=8,
            spacing3=12,
        )
        widget.tag_configure(
            "h2",
            font=fonts["heading"],
            foreground=self.accent,
            spacing1=18,
            spacing3=8,
        )
        widget.tag_configure(
            "h3",
            font=fonts["subheading"],
            foreground=self.text_strong,
            spacing1=14,
            spacing3=6,
        )
        widget.tag_configure(
            "body",
            font=base_font,
            foreground=self.text,
            spacing1=2,
            spacing3=8,
        )
        widget.tag_configure(
            "bold",
            font=(fonts["body"][0], fonts["body"][1], "bold"),
            foreground=self.text_strong,
        )
        widget.tag_configure("bullet", lmargin1=22, lmargin2=40, spacing3=4)
        widget.tag_configure(
            "table",
            font=mono_font,
            background=self.surface,
            foreground=self.text,
            lmargin1=10,
            lmargin2=10,
            spacing1=1,
            spacing3=1,
        )
        widget.tag_configure(
            "table_header",
            font=(fonts["mono"][0], fonts["mono"][1], "bold"),
            background=self.card,
            foreground=self.text_strong,
            lmargin1=10,
            lmargin2=10,
        )
        widget.tag_configure(
            "rule",
            foreground=self.border_strong,
            spacing1=6,
            spacing3=6,
        )
        widget.tag_configure(
            "search_match",
            background="#b45309",
            foreground=self.text_strong,
        )
        widget.tag_configure(
            "search_current",
            background=self.accent,
            foreground=self.bg,
        )

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
            bg=self.surface,
            fg=self.text,
            font=self.fonts["body"],
            insertbackground=self.text,
            relief="flat",
            padx=12,
            pady=10,
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
        # Zebra striping for readability. These set *background* only, so they
        # stack cleanly with the semantic *foreground* tags above (a SELL row
        # stays red on its stripe). Selection still wins via style.map.
        tree.tag_configure("oddrow", background=self.surface)
        tree.tag_configure("evenrow", background=self.panel)
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
        self._set_status("Reading holdings CSV…")
        self._run_in_background(
            lambda: preview_holdings_csv(path),
            self._show_holdings_preview,
            on_error=lambda exc: messagebox.showerror("Preview failed", str(exc)),
        )

    def _show_holdings_preview(self, preview: dict) -> None:
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

    def refresh_run_preflight(self) -> dict[str, Any]:
        try:
            budget_usd = float(self.budget_usd_var.get() or 0)
        except ValueError:
            budget_usd = 0.0
        try:
            budget_cad = float(self.budget_cad_var.get() or 0)
        except ValueError:
            budget_cad = 0.0
        readiness = paid_run_readiness_view(
            holdings_csv=self.holdings_var.get().strip() or None,
            activities_csv=self.activities_var.get().strip() or None,
            use_fallback_config=not bool(self.holdings_var.get().strip()),
            model_choice=self.model_var.get(),
            budget_usd=budget_usd,
            budget_cad=budget_cad,
        )
        readiness_rows = [
            [
                row.get("step") or "",
                row.get("status") or "",
                row.get("detail") or "",
                row.get("action") or "",
            ]
            for row in readiness.get("steps") or []
        ]
        for row in readiness.get("confirmations_required") or []:
            readiness_rows.append(
                [
                    row.get("label") or row.get("code") or "Confirmation",
                    "CONFIRM" if row.get("required") else "INFO",
                    row.get("detail") or "",
                    row.get("accepted_by") or "",
                ]
            )
        self._replace_tree_rows(self.run_readiness_tree, readiness_rows, tag_index=1)
        self.run_readiness_summary.set(f"{readiness.get('status')}: {readiness.get('summary') or readiness.get('next_action')}")

        checklist = pre_run_checklist_view(
            holdings_csv=self.holdings_var.get().strip() or None,
            activities_csv=self.activities_var.get().strip() or None,
            use_fallback_config=not bool(self.holdings_var.get().strip()),
        )
        rows = []
        for row in checklist.get("rows") or []:
            rows.append(
                [
                    row.get("check") or "",
                    row.get("status") or "",
                    row.get("detail") or "",
                    row.get("action") or "",
                ]
            )
        self._replace_tree_rows(self.run_preflight_tree, rows)
        budget_note = self._budget_summary_line()
        budget_suffix = f" {budget_note}" if budget_note else ""
        if checklist.get("can_run"):
            if checklist.get("warning_count"):
                self.run_status.set(f"Checklist passed with {checklist['warning_count']} warning(s).{budget_suffix}")
            else:
                self.run_status.set(f"Checklist passed. Ready to generate a report.{budget_suffix}")
        else:
            self.run_status.set(f"Checklist blocked: {checklist.get('next_action')}")
        return checklist

    def run_demo_smoke_check(self) -> None:
        try:
            result = demo_smoke_view()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Demo smoke failed", str(exc))
            return
        passed = sum(1 for row in result.get("checks", []) if row.get("ok"))
        total = len(result.get("checks", []))
        detail = "\n".join(
            f"{'OK' if row.get('ok') else 'FAIL'} - {row.get('name')}: {row.get('detail')}" for row in result.get("checks", [])
        )
        if result.get("ok"):
            messagebox.showinfo("Demo smoke passed", f"{passed}/{total} checks passed.\n\n{detail}")
        else:
            messagebox.showerror("Demo smoke failed", f"{passed}/{total} checks passed.\n\n{detail}")

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

    def _budget_summary_line(self) -> str:
        """Short month-to-date vs cap line for the Run tab; '' when no cap set."""
        try:
            from src.cost_tracker import check_budget

            check = check_budget()
            if check.budget_usd <= 0:
                return ""
            remaining = max(0.0, check.budget_usd - check.month_to_date_usd)
            return f"Budget: ${check.month_to_date_usd:.2f} of ${check.budget_usd:.2f} this month (${remaining:.2f} left)."
        except Exception:
            logger.debug("Could not compute budget summary", exc_info=True)
            return ""

    def _budget_precheck(self) -> bool:
        """Surface the monthly spend cap before a run. Returns False to abort.

        On an explicit override the ``ALLOW_OVERAGE`` env is set for this run (so
        the pipeline's own cap check passes) and cleared again when the run
        finishes. A missing cap (budget == 0) is a silent pass.
        """
        try:
            from src.claude_analyst import typical_run_cost
            from src.cost_tracker import check_budget

            estimate = typical_run_cost(self.model_var.get())
            check = check_budget(expected_cost_usd=estimate)
        except Exception:
            logger.debug("Budget pre-check failed; allowing run", exc_info=True)
            return True

        if check.hard_block:
            proceed = messagebox.askyesno(
                "Monthly spend cap reached",
                f"{check.message}\n\nRun anyway and override the cap for this report?",
            )
            if not proceed:
                self.run_status.set("Run cancelled — monthly spend cap reached.")
                return False
            os.environ["ALLOW_OVERAGE"] = "1"
            self._desktop_overage = True
        elif check.soft_warn:
            message = check.message or "You're close to your monthly spend cap."
            if not messagebox.askyesno("Approaching spend cap", f"{message}\n\nGenerate this report anyway?"):
                self.run_status.set("Run cancelled.")
                return False
        return True

    def _clear_desktop_overage(self) -> None:
        """Drop the per-run ALLOW_OVERAGE override the desktop may have set."""
        if getattr(self, "_desktop_overage", False):
            os.environ.pop("ALLOW_OVERAGE", None)
            self._desktop_overage = False

    def start_report_run(self) -> None:
        try:
            budget_usd = float(self.budget_usd_var.get() or 0)
            budget_cad = float(self.budget_cad_var.get() or 0)
        except ValueError:
            messagebox.showerror("Invalid budget", "Budget fields must be numeric.")
            return

        checklist = self.refresh_run_preflight()
        if not checklist.get("can_run"):
            messagebox.showerror("Cannot run report yet", checklist.get("next_action") or "Fix blocking pre-run checklist items.")
            return
        if checklist.get("warning_count"):
            warning_lines = "\n".join(
                f"- {row.get('check')}: {row.get('detail')}" for row in checklist.get("rows") or [] if row.get("status") == "WARN"
            )
            if not messagebox.askyesno("Pre-run warnings", f"{warning_lines}\n\nRun anyway?"):
                return

        # Monthly Claude spend-cap gate — surface before we spend ~90s and money.
        if not self._budget_precheck():
            return

        self.run_button.configure(state="disabled")
        self.console_text.delete("1.0", "end")
        self.run_status.set("Generating your portfolio report... usually takes about 90 seconds.")
        self._set_status("Analyzing your portfolio with Claude...", tone="warning")
        self._jump_to_tab(self.reports_tab, sub=self.run_subtab)

        # Show progress bar
        import time as _time

        self._report_start_time = _time.time()
        self._report_progress_frame.pack(fill="x", pady=(10, 0))
        self._report_progress.start(15)
        self._tick_elapsed()

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

    def _tick_elapsed(self) -> None:
        import time as _time

        if self._report_start_time is None or self._closing:
            return
        elapsed = int(_time.time() - self._report_start_time)
        self._report_elapsed_var.set(f"Elapsed: {elapsed}s")
        self._report_elapsed_id = self.after(1000, self._tick_elapsed)

    def _stop_progress(self) -> None:
        self._report_start_time = None
        if self._report_elapsed_id:
            self.after_cancel(self._report_elapsed_id)
            self._report_elapsed_id = None
        try:
            self._report_progress.stop()
            self._report_progress_frame.pack_forget()
        except tk.TclError:
            pass

    def _drain_progress_queue(self) -> None:
        if self._closing:
            return
        # Each item is dispatched under its own guard and the reschedule lives in
        # a finally block: one handler raising (e.g. a render hitting malformed
        # data) must not kill the drain loop, which also pumps report-run
        # completion and background refreshes.
        try:
            while True:
                try:
                    kind, payload = self.progress_queue.get_nowait()
                except queue.Empty:
                    break
                try:
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
                    elif kind == "callback":
                        payload()
                except Exception:  # noqa: BLE001 — one bad handler must not stop the pump
                    logger.exception("Progress handler for %r failed", kind)
        finally:
            if not self._closing:
                self._drain_id = self.after(100, self._drain_progress_queue)

    def _run_in_background(self, work, on_success, *, on_error=None) -> None:
        """Run ``work()`` (slow, blocking I/O) off the Tk thread, then hand its
        result to ``on_success(result)`` back on the main thread.

        This keeps the event loop responsive so the window never freezes while
        a tab fetches market data or scans logs. Results are marshalled through
        ``progress_queue`` — the single-consumer queue the drain loop already
        pumps — so Tk widgets are only ever touched from the main thread, the
        one place Tkinter permits it. Failures route to ``on_error(exc)`` (also
        main-thread); without one the global status line shows the error.
        """

        def _worker() -> None:
            try:
                result = work()
            except Exception as exc:  # noqa: BLE001 — surfaced to the UI and logged
                logger.debug("Background task failed", exc_info=True)
                self.progress_queue.put(("callback", lambda e=exc: self._handle_async_error(e, on_error)))
                return
            self.progress_queue.put(("callback", lambda r=result: on_success(r)))

        threading.Thread(target=_worker, daemon=True).start()

    def _handle_async_error(self, exc: Exception, on_error) -> None:
        if on_error is not None:
            on_error(exc)
        else:
            self._set_status(f"Couldn't finish that — {exc}", tone="error")

    def _guarded_callbacks(self, key: str, on_success, on_error):
        """Bump the per-key generation once and return ``(success, error)``
        callbacks that BOTH apply only while this is the latest request for
        ``key``.

        A tab can be re-triggered (combobox, checkbox, double-clicked Refresh)
        faster than its work finishes; without this guard an older, slower
        result could land last and overwrite the newer one. Guarding *both*
        outcomes is essential: a stale request that fails after a newer one
        succeeded must not clobber the fresh data with a "Failed…" status.

        The success wrapper also catches a render that raises *on the UI thread*
        and routes it to ``on_error`` — otherwise a malformed-data crash inside
        the drain loop would be swallowed, leaving a success-looking status over
        empty tables with no error shown.
        """
        generation = self._async_generation.get(key, 0) + 1
        self._async_generation[key] = generation

        # Busy state: disable the tab's Refresh button while its work is in
        # flight so rapid clicks don't pile up, and re-enable it when the latest
        # request settles (stale requests leave it alone — the newer one owns it).
        button = self._refresh_buttons.get(key)
        self._set_button_state(button, "disabled")

        def _is_current() -> bool:
            return self._async_generation.get(key) == generation

        def _report(exc: Exception) -> None:
            if on_error is not None:
                on_error(exc)
            else:
                self._set_status(f"Couldn't finish that — {exc}", tone="error")

        def _success(result) -> None:
            if not _is_current():
                return
            self._set_button_state(button, "normal")
            try:
                on_success(result)
            except Exception as exc:  # noqa: BLE001 — render failed on the UI thread
                logger.exception("Render failed for %s tab", key)
                _report(exc)

        def _error(exc: Exception) -> None:
            if not _is_current():
                return
            self._set_button_state(button, "normal")
            _report(exc)

        return _success, _error

    @staticmethod
    def _set_button_state(button, state: str) -> None:
        """Best-effort widget state toggle — a destroyed/None button is a no-op."""
        if button is not None:
            try:
                button.configure(state=state)
            except Exception:
                pass

    def _on_close(self) -> None:
        """Stop the self-rescheduling ``after()`` loops before tearing the
        window down so they can't fire against destroyed widgets (which would
        spew TclError tracebacks to stderr on quit). Worker threads are daemons
        and exit with the process; their late queue writes are harmless once
        the drain loop has stopped."""
        self._closing = True
        self._save_window_size()
        for after_id in (self._drain_id, self._report_elapsed_id):
            if after_id:
                try:
                    self.after_cancel(after_id)
                except Exception:
                    pass
        self._drain_id = None
        self._report_elapsed_id = None
        self.destroy()

    def _report_run_done(self, result: Any) -> None:
        self._clear_desktop_overage()
        self._stop_progress()
        self.run_button.configure(state="normal")
        if not result.ok:
            self.run_status.set("Report could not be generated. Check the console output below for details.")
            self._set_status("Report failed.", tone="error")
            if result.console:
                self.console_text.insert("end", "\n" + result.console)
            messagebox.showerror("Report failed", result.error or "Unknown error.")
            return
        self.run_status.set("Report ready! Switch to Reports > Latest to read your recommendations.")
        self._set_status("Report complete!", tone="success")
        self.latest_report_path = result.report_path
        self.load_report(result.report_path, select_tab=True)
        self.refresh_dashboard()
        self.refresh_history()
        self._update_status_bar()
        messagebox.showinfo(
            "Report ready",
            "Your portfolio report has been generated.\n\n"
            f"Markdown: {relative_to_root(result.report_path)}\n"
            f"CSV: {relative_to_root(result.csv_path)}\n"
            f"JSON: {relative_to_root(result.log_path)}",
        )
        self.start_buy_signal_refresh()

    def start_buy_signal_refresh(self) -> None:
        if not hasattr(self, "buy_signal_button"):
            return
        self.buy_signal_button.configure(state="disabled")
        self.buy_signal_status.set("Checking real-time market data for buy opportunities...")
        action_filter = self._buy_action_filter_value()
        readiness_filter = self._buy_readiness_filter_value()
        source_filter = self._buy_source_filter_value()

        def worker() -> None:
            self.progress_queue.put(
                (
                    "buy_signals_done",
                    buy_signal_view(action_filter=action_filter, readiness_filter=readiness_filter, source_filter=source_filter),
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

    def _buy_source_filter_value(self) -> str:
        value = getattr(self, "buy_source_filter", tk.StringVar(value="All sources")).get()
        return {
            "Missing catalyst": "missing_catalyst",
            "Missing analyst": "missing_analyst",
            "Quote not timestamped": "quote_not_timestamped",
            "Source degraded": "source_degraded",
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
        confidence = payload.get("data_confidence") or {}
        self.buy_signal_status.set(
            f"{len(candidates)} shown / {counts.get('total', len(candidates))} total "
            f"({counts.get('TRADE_READY', 0)} ready, {counts.get('REVIEW_FIRST', 0)} review, {counts.get('BLOCKED', 0)} blocked) "
            f"· confidence {confidence.get('label', 'N/A')} · from {payload.get('session_file', 'latest log')}"
        )
        overview_rows = []
        consensus_rows = []
        catalyst_lines = []
        source_lines = [
            f"Session log: {payload.get('session_file', '')}",
            f"Data confidence: {confidence.get('label', 'N/A')} — {confidence.get('summary', '')}",
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
            source_confidence = item.get("source_confidence") or {}
            explainability = item.get("explainability") or {}
            components = source_confidence.get("components") or {}
            warnings = item.get("quality_warnings") or []
            amount = item.get("action_amount")
            amount_currency = item.get("action_amount_currency") or "USD"
            amount_text = f"{self._fmt_money(amount)} {amount_currency}" if amount else ""
            why = "; ".join((explainability.get("bullish_evidence") or [])[:2]) or explainability.get("readiness_reason") or ""
            overview_rows.append(
                [
                    readiness.get("label") or "N/A",
                    ticker,
                    item.get("action") or item.get("hold_tier") or "",
                    item.get("conviction"),
                    amount_text,
                    self._fmt_price(item.get("current_price")),
                    source_confidence.get("label") or "N/A",
                    (components.get("quote") or {}).get("status") or "N/A",
                    (components.get("catalyst") or {}).get("status") or "N/A",
                    (components.get("analyst") or {}).get("status") or "N/A",
                    why,
                    explainability.get("change_mind") or item.get("risk_or_invalidation") or "N/A",
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
            if source_confidence:
                source_lines.append(f"  confidence: {source_confidence.get('label')} ({source_confidence.get('overall_status')})")
                for name, component in (source_confidence.get("components") or {}).items():
                    source_lines.append(f"  - {name}: {component.get('status')} — {component.get('evidence')}")
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
        source_confidence = item.get("source_confidence") or {}
        if source_confidence:
            lines.append(
                f"Source confidence: {source_confidence.get('label')} — "
                f"{'; '.join(source_confidence.get('blockers') or source_confidence.get('review_reasons') or ['clear'])}"
            )
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
            return self.good, self.card
        if value in {"SELL", "HIGH"}:
            return self.danger, self.card
        if value in {"TRIM", "MEDIUM"}:
            return self.warning, self.card
        if value in {"WATCH", "LOW"}:
            return self.muted, self.card
        return self.accent, self.card

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
            fg=self.bg,
            font=self.fonts["small"],
            padx=8,
            pady=2,
        ).pack(side="left", padx=(0, 6))

    def _wrapped_dashboard_label(
        self,
        parent: tk.Widget,
        text: str,
        *,
        bg: str,
        fg: str,
        font: tuple | None = None,
    ) -> tk.Label:
        label = tk.Label(parent, text=text, bg=bg, fg=fg, font=font or self.fonts["body"], justify="left", anchor="w", wraplength=900)
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
            card = tk.Frame(self.action_cards, bg=bg, highlightthickness=1, highlightbackground=self.border)
            card.pack(fill="x", pady=(0, 6))
            tk.Frame(card, bg=accent, width=4).pack(side="left", fill="y")
            body = tk.Frame(card, bg=bg, padx=14, pady=10)
            body.pack(side="left", fill="both", expand=True)

            header = tk.Frame(body, bg=bg)
            header.pack(fill="x")
            self._dashboard_tag(header, f"#{row.get('order', '')}", color=accent)
            self._dashboard_tag(header, action, color=accent)
            tk.Label(
                header,
                text=str(row.get("ticker") or ""),
                bg=bg,
                fg=self.text_strong,
                font=self.fonts["subheading"],
            ).pack(side="left", padx=(2, 10))
            size = row.get("action_size_label") or row.get("shares") or row.get("invest_amount_usd") or ""
            if size:
                tk.Label(header, text=str(size), bg=bg, fg=self.muted, font=self.fonts["small"]).pack(side="left")

            reason = row.get("rationale") or row.get("reason") or row.get("message") or ""
            self._wrapped_dashboard_label(body, self._trim_text(reason, 360), bg=bg, fg=self.text)
        if len(rows) > 8:
            tk.Label(
                self.action_cards,
                text=f"{len(rows) - 8} more actions in the full report.",
                bg=self.panel,
                fg=self.muted,
                font=self.fonts["small"],
            ).pack(anchor="w", pady=(0, 4))

    def _render_warning_cards(self, rows: list[dict[str, Any]]) -> None:
        self._clear_dashboard_section(self.warning_cards)
        if not rows:
            self._empty_dashboard_section(self.warning_cards, "No quality warnings in the latest report.")
            return
        for row in rows[:7]:
            severity = str(row.get("severity") or "LOW").upper()
            accent, bg = self._dashboard_tone(severity)
            card = tk.Frame(self.warning_cards, bg=bg, highlightthickness=1, highlightbackground=self.border)
            card.pack(fill="x", pady=(0, 6))
            body = tk.Frame(card, bg=bg, padx=12, pady=8)
            body.pack(fill="both", expand=True)
            header = tk.Frame(body, bg=bg)
            header.pack(fill="x")
            self._dashboard_tag(header, severity, color=accent)
            if row.get("ticker"):
                self._dashboard_tag(header, row.get("ticker"), color=self.subtle)
            tk.Label(
                header,
                text=str(row.get("code") or ""),
                bg=bg,
                fg=self.text_strong,
                font=self.fonts["small"],
            ).pack(side="left", padx=(2, 0))
            message = row.get("action_required") or row.get("message") or ""
            self._wrapped_dashboard_label(body, self._trim_text(message, 240), bg=bg, fg=self.text, font=self.fonts["small"])
        if len(rows) > 7:
            tk.Label(
                self.warning_cards,
                text=f"{len(rows) - 7} more warnings in the report.",
                bg=self.panel,
                fg=self.muted,
                font=self.fonts["small"],
            ).pack(anchor="w", pady=(0, 4))

    def _render_stop_cards(self, rows: list[dict[str, Any]]) -> None:
        self._clear_dashboard_section(self.stop_cards)
        if not rows:
            self._empty_dashboard_section(self.stop_cards, "No trailing-stop breaches in the latest report.")
            return
        for row in rows[:5]:
            action = row.get("recommended_action") or "REVIEW"
            accent, bg = self._dashboard_tone(action)
            card = tk.Frame(self.stop_cards, bg=bg, highlightthickness=1, highlightbackground=self.border)
            card.pack(fill="x", pady=(0, 6))
            body = tk.Frame(card, bg=bg, padx=12, pady=8)
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
            tk.Label(header, text=metrics, bg=bg, fg=self.text, font=self.fonts["small"]).pack(side="left")
            note = row.get("rationale") or row.get("message") or ""
            if note:
                self._wrapped_dashboard_label(body, self._trim_text(note, 220), bg=bg, fg=self.muted, font=self.fonts["small"])

    def refresh_dashboard(self) -> None:
        # Keep the header status pill in lock-step with the dashboard.
        if hasattr(self, "header_status_var"):
            self._update_header_status()
        summary = latest_log_summary()
        if not summary:
            self.dashboard_caption.configure(text="Welcome! Generate your first report to see your portfolio analysis here.")
            self.signal_accent.configure(bg=self.muted)
            self.signal_kicker.set("ACTION PULSE")
            self.signal_title.set("Welcome to tech_stock")
            self.signal_body.set("Generate your first report to see your portfolio analysis here.")
            self.signal_meta.set("")
            for label in self.metric_vars:
                self._set_metric(label, "N/A")
            self._empty_dashboard_section(self.action_cards, "Generate a report to see recommended actions.")
            self._empty_dashboard_section(self.warning_cards, "Generate a report to see risk alerts.")
            self._empty_dashboard_section(self.stop_cards, "Generate a report to see price alerts.")
            self._set_readonly_text(self.risk_text, "No risk dashboard available yet.")
            self._set_readonly_text(self.signal_text, "No drift or market signals available yet.")
            return
        self.dashboard_caption.configure(text=str(summary.get("session_file", "")))
        title, body = self._dashboard_signal(summary)
        self.signal_title.set(title)
        self.signal_body.set(body)

        risk = summary.get("risk_dashboard") or {}
        health = summary.get("portfolio_health") or {}
        data_confidence = summary.get("data_confidence") or {}
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
        self._set_metric(
            "Data Conf.",
            data_confidence.get("label") or "N/A",
            data_confidence.get("summary") or "deterministic checks",
        )
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
        for offset, row in enumerate(rows):
            tags: list[str] = []
            if tag_index is not None and tag_index < len(row):
                tags.append(str(row[tag_index]).upper())
            tags.append("evenrow" if offset % 2 else "oddrow")
            tree.insert("", "end", values=row, tags=tuple(tags))

    def _refresh_report_review(self, path: Path | None) -> None:
        if not hasattr(self, "report_review_tree"):
            return
        if not path:
            self.report_review_status.set("No report selected.")
            self._replace_tree_rows(self.report_review_tree, [])
            self._replace_tree_rows(self.report_review_checklist_tree, [])
            self.report_review_decision_rows = []
            self.report_review_decision_box.configure(values=[])
            self.report_review_decision_var.set("")
            return
        try:
            view = report_review_view(report_path=path)
        except Exception as exc:  # noqa: BLE001
            self.report_review_status.set(f"Report review failed: {exc}")
            self._replace_tree_rows(self.report_review_tree, [])
            self._replace_tree_rows(self.report_review_checklist_tree, [])
            self.report_review_decision_rows = []
            self.report_review_decision_box.configure(values=[])
            self.report_review_decision_var.set("")
            return

        self.report_review_status.set(
            f"{view.get('status_label') or 'Unknown'} · "
            f"{view.get('session_file') or Path(path).name} · "
            f"{len(view.get('decision_rows') or [])} actionable row(s)"
        )
        rows = []
        for metric in view.get("metric_rows") or []:
            rows.append(
                [
                    metric.get("metric") or "",
                    metric.get("status") or "",
                    metric.get("value") or "",
                    metric.get("next_action") or metric.get("detail") or "",
                ]
            )
        self._replace_tree_rows(self.report_review_tree, rows)

        checklist_rows = []
        for row in view.get("execution_checklist_rows") or []:
            checklist_rows.append(
                [
                    row.get("ticker") or "",
                    row.get("label") or row.get("check") or "",
                    "YES" if row.get("required") else "",
                    row.get("status") or "",
                    row.get("detail") or "",
                ]
            )
        self._replace_tree_rows(self.report_review_checklist_tree, checklist_rows, tag_index=3)

        self.report_review_decision_rows = view.get("decision_rows") or []
        labels = [
            f"{row.get('ticker')} {row.get('recommended_action')} · {row.get('user_decision')} · {row.get('id')}"
            for row in self.report_review_decision_rows
        ]
        self.report_review_decision_box.configure(values=labels)
        self.report_review_decision_var.set(labels[0] if labels else "")

    def _save_report_review_decision(self) -> None:
        selected = self.report_review_decision_var.get()
        rows = getattr(self, "report_review_decision_rows", []) or []
        labels = [f"{row.get('ticker')} {row.get('recommended_action')} · {row.get('user_decision')} · {row.get('id')}" for row in rows]
        if not selected or selected not in labels:
            self.status.set("Choose a recommendation row before saving feedback.")
            return
        row = rows[labels.index(selected)]
        try:
            save_decision_from_ui(
                str(row.get("id")),
                user_decision=self.report_review_choice_var.get() or "accepted",
                reason="Recorded from Desktop Report Review.",
            )
        except Exception as exc:  # noqa: BLE001
            self.status.set(f"Could not save feedback: {exc}")
            return
        self.status.set(f"Saved feedback for {row.get('ticker')}.")
        self._refresh_report_review(self.latest_report_path)

    def _save_report_review_checklist(self) -> None:
        selected = self.report_review_decision_var.get()
        rows = getattr(self, "report_review_decision_rows", []) or []
        labels = [f"{row.get('ticker')} {row.get('recommended_action')} · {row.get('user_decision')} · {row.get('id')}" for row in rows]
        if not selected or selected not in labels:
            self.status.set("Choose a recommendation row before marking checklist reviewed.")
            return
        row = rows[labels.index(selected)]
        try:
            save_execution_checklist_from_ui(
                str(row.get("id")),
                checklist={
                    "quote_confirmed": True,
                    "catalyst_checked": True,
                    "sizing_checked": True,
                    "fee_fx_checked": True,
                    "manual_review_accepted": True,
                },
                notes="Marked reviewed from Desktop Report Review.",
            )
        except Exception as exc:  # noqa: BLE001
            self.status.set(f"Could not save checklist: {exc}")
            return
        self.status.set(f"Marked execution checklist reviewed for {row.get('ticker')}.")
        self._refresh_report_review(self.latest_report_path)

    def load_report(self, path: Path | None, *, select_tab: bool = False) -> None:
        self.refresh_report_paths_text()
        self.latest_report_path = path
        text = read_text_file(path)
        if not path or not text:
            self.report_path_label.configure(text="No report selected.")
            self._render_markdown(self.report_text, "## No report found yet\n\nRun a report or choose one from History.")
            self._refresh_report_review(None)
            self._refresh_search_after_text_change("report")
            if select_tab:
                self._jump_to_tab(self.reports_tab, sub=self.report_subtab)
            return
        self.report_path_label.configure(text=relative_to_root(path))
        self._refresh_report_review(path)
        self._render_markdown(self.report_text, text)
        self._refresh_search_after_text_change("report")
        if select_tab:
            self._jump_to_tab(self.reports_tab, sub=self.report_subtab)

    def refresh_history(self) -> None:
        self.refresh_report_paths_text()
        view = report_history_view(limit=100)
        self.history_rows = view.get("rows") or []
        self.history_paths = [row.get("report_path") for row in self.history_rows if row.get("report_path")]
        self.history_list.delete(0, "end")
        for row in self.history_rows:
            report_path = row.get("report_path")
            if not report_path:
                continue
            label = (
                f"{Path(report_path).name}  |  "
                f"BUY/ADD {row.get('buy_add_count', 0)}  "
                f"TRIM/SELL {row.get('trim_sell_count', 0)}  "
                f"WARN {row.get('warning_count', 0)}  |  "
                f"Holdings {Path(row.get('holdings_csv') or '').name or 'unknown'}"
            )
            self.history_list.insert("end", label)

    def _history_selected(self, _event: object) -> None:
        selection = self.history_list.curselection()
        if not selection:
            return
        index = selection[0]
        # A selection can outlive a refresh that shortened the list, so guard
        # the index before using it to avoid an IndexError.
        if index >= len(self.history_paths):
            return
        path = self.history_paths[index]
        row = (getattr(self, "history_rows", []) or [{}])[index if index < len(getattr(self, "history_rows", []) or [{}]) else 0]
        metadata = (
            f"## Report Metadata\n\n"
            f"- Holdings CSV: `{row.get('holdings_csv') or 'unknown'}`\n"
            f"- Activities CSV: `{row.get('activities_csv') or 'none'}`\n"
            f"- BUY/ADD: {row.get('buy_add_count', 0)} | TRIM/SELL: {row.get('trim_sell_count', 0)} | "
            f"Warnings: {row.get('warning_count', 0)} | Data confidence: {row.get('data_confidence') or 'unknown'}\n\n---\n\n"
        )
        self._render_markdown(self.history_text, metadata + (read_text_file(path) or "## Could not read report"))
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
        self.health_status.set("Testing connectivity to all data sources...")
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
        force_refresh = not startup
        self.update_status.set("Force-refreshing GitHub Releases..." if force_refresh else "Checking GitHub Releases...")
        if not startup:
            self._jump_to_tab(self.settings_tab, sub=self.update_subtab)

        def worker() -> None:
            info = check_update_available(force=force_refresh)
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
        self._jump_to_tab(self.settings_tab, sub=self.update_subtab)

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
