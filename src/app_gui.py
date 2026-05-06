"""
app_gui.py — Native GUI launcher for tech_stock (packaged .app / .exe).

This module is the entry point for the PyInstaller-packaged application.
It shows a small Tkinter window so users can pick an interface without
needing a terminal.

Dispatch rules
--------------
* --streamlit  : run the Streamlit web server in-process and open browser
* --textual    : run the Textual TUI (same process)
* --cli [args] : run the CLI (same process, remaining argv forwarded)
* (no args)    : show the tkinter launcher window
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

# ── Resolve project root whether frozen or not ───────────────────────────────
if getattr(sys, "frozen", False):
    # PyInstaller: _MEIPASS is the temp extraction dir; the exe itself is here
    ROOT = Path(sys.executable).resolve().parent
    _BUNDLE = Path(sys._MEIPASS)  # type: ignore[attr-defined]
else:
    ROOT = Path(__file__).resolve().parents[1]
    _BUNDLE = ROOT

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(_BUNDLE))

STREAMLIT_SCRIPT = _BUNDLE / "ui" / "streamlit_app.py"
TEXTUAL_SCRIPT = _BUNDLE / "ui" / "textual_app.py"
CLI_SCRIPT = _BUNDLE / "src" / "main.py"

# ── Sub-process dispatch (called when the bundled exe is re-invoked) ─────────

def _run_streamlit() -> None:
    """Launch Streamlit server and open browser."""
    port = 8501

    def _open_browser() -> None:
        time.sleep(2.5)
        webbrowser.open(f"http://localhost:{port}")

    threading.Thread(target=_open_browser, daemon=True).start()

    # streamlit.web.bootstrap is available in the bundle
    from streamlit.web import bootstrap  # type: ignore[import]
    sys.argv = [
        "streamlit",
        "run",
        str(STREAMLIT_SCRIPT),
        f"--server.port={port}",
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
    ]
    bootstrap.run(str(STREAMLIT_SCRIPT), "", [], {})


def _run_textual() -> None:
    """Run the Textual TUI app directly."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("textual_app", TEXTUAL_SCRIPT)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    mod.TechStockTUI().run()


def _run_cli(extra: list[str]) -> None:
    """Run the CLI main module, forwarding extra argv."""
    sys.argv = [str(CLI_SCRIPT)] + extra
    import importlib.util
    spec = importlib.util.spec_from_file_location("main", CLI_SCRIPT)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]


# ── GUI launcher ─────────────────────────────────────────────────────────────

_CHOICES = [
    ("Streamlit Web UI",
     "Opens a dashboard in your browser.\nFull feature set: Dashboard, Run, History, Backtest, Editor.",
     _run_streamlit),
    ("Textual Terminal UI",
     "Keyboard-driven interface inside this window.\nNo browser needed.",
     _run_textual),
    ("Command-Line (CLI)",
     "Classic terminal mode.\nUse for scripting, cron, or maximum speed.",
     lambda: _run_cli([])),
]


def _show_launcher() -> None:
    import tkinter as tk
    from tkinter import font as tkfont

    root = tk.Tk()
    root.title("tech_stock")
    root.resizable(False, False)

    # ── Colours ──────────────────────────────────────────────────────────────
    BG = "#12121a"
    CARD = "#1e1e2e"
    BORDER = "#313147"
    GREEN = "#22c55e"
    TEXT = "#e2e8f0"
    MUTED = "#94a3b8"
    BTN_BG = "#22c55e"
    BTN_FG = "#0a0a10"
    BTN_HOVER = "#16a34a"

    root.configure(bg=BG)

    # ── Fonts ─────────────────────────────────────────────────────────────────
    try:
        title_font = tkfont.Font(family="SF Pro Display", size=22, weight="bold")
        sub_font   = tkfont.Font(family="SF Pro Text",    size=12)
        label_font = tkfont.Font(family="SF Pro Text",    size=13, weight="bold")
        desc_font  = tkfont.Font(family="SF Pro Text",    size=11)
        btn_font   = tkfont.Font(family="SF Pro Text",    size=12, weight="bold")
    except Exception:
        title_font = tkfont.Font(size=20, weight="bold")
        sub_font   = tkfont.Font(size=11)
        label_font = tkfont.Font(size=12, weight="bold")
        desc_font  = tkfont.Font(size=10)
        btn_font   = tkfont.Font(size=11, weight="bold")

    # ── Header ────────────────────────────────────────────────────────────────
    header = tk.Frame(root, bg=BG, padx=32, pady=24)
    header.pack(fill="x")
    tk.Label(header, text="tech_stock", fg=GREEN, bg=BG, font=title_font).pack(anchor="w")
    tk.Label(header, text="AI-powered portfolio advisor — choose your interface",
             fg=MUTED, bg=BG, font=sub_font).pack(anchor="w", pady=(2, 0))

    sep = tk.Frame(root, bg=BORDER, height=1)
    sep.pack(fill="x", padx=32)

    # ── Option cards ─────────────────────────────────────────────────────────
    body = tk.Frame(root, bg=BG, padx=32, pady=20)
    body.pack(fill="both")

    selected_action = [None]

    def launch(action):
        selected_action[0] = action
        root.destroy()

    for label, description, action in _CHOICES:
        card = tk.Frame(body, bg=CARD, bd=0, highlightthickness=1,
                        highlightbackground=BORDER, highlightcolor=GREEN)
        card.pack(fill="x", pady=6, ipady=14, ipadx=16)

        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="x", padx=16, pady=8)

        left = tk.Frame(inner, bg=CARD)
        left.pack(side="left", fill="both", expand=True)

        tk.Label(left, text=label, fg=TEXT, bg=CARD, font=label_font,
                 anchor="w").pack(fill="x")
        tk.Label(left, text=description, fg=MUTED, bg=CARD, font=desc_font,
                 anchor="w", justify="left", wraplength=340).pack(fill="x", pady=(3, 0))

        btn = tk.Button(inner, text="Launch →", font=btn_font,
                        bg=BTN_BG, fg=BTN_FG, relief="flat", cursor="hand2",
                        padx=14, pady=6, bd=0,
                        command=lambda a=action: launch(a))
        btn.pack(side="right", padx=(12, 0))

        def on_enter(e, b=btn):   b.configure(bg=BTN_HOVER)
        def on_leave(e, b=btn):   b.configure(bg=BTN_BG)
        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)

        # Clicking anywhere on the card also triggers launch
        def on_card_click(e, a=action): launch(a)
        for w in (card, inner, left):
            w.bind("<Button-1>", on_card_click)

    # ── Footer ────────────────────────────────────────────────────────────────
    sep2 = tk.Frame(root, bg=BORDER, height=1)
    sep2.pack(fill="x", padx=32)
    tk.Label(root, text="Powered by Claude  ·  Anthropic",
             fg=MUTED, bg=BG, font=desc_font).pack(pady=10)

    # Centre window on screen
    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")

    root.mainloop()

    if selected_action[0]:
        selected_action[0]()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    argv = sys.argv[1:]

    if argv and argv[0] == "--streamlit":
        _run_streamlit()
    elif argv and argv[0] == "--textual":
        _run_textual()
    elif argv and argv[0] == "--cli":
        _run_cli(argv[1:])
    else:
        _show_launcher()


if __name__ == "__main__":
    main()
