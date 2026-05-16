"""
app_gui.py — Native GUI launcher for tech_stock (packaged .app / .exe).

This module is the entry point for the PyInstaller-packaged application.
It shows a small Tkinter window so users can pick an interface without
needing a terminal.

Dispatch rules
--------------
* --desktop    : run the embedded Tkinter desktop app
* --streamlit  : run the Streamlit web server in-process and open browser
* --textual    : run the Textual TUI (same process)
* --cli [args] : run the CLI (same process, remaining argv forwarded)
* (no args)    : show the tkinter launcher window
"""
import json
import os
import shlex
import socket
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

from src.updater import apply_update, check_for_update  # noqa: E402
from src.version import APP_VERSION  # noqa: E402


def _log_dir() -> Path:
    """Return a user-writable log directory for packaged GUI launches."""
    if sys.platform == "darwin":
        path = Path.home() / "Library" / "Logs" / "tech_stock"
    elif sys.platform == "win32":
        path = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "tech_stock" / "logs"
    else:
        path = Path.home() / ".cache" / "tech_stock" / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _tail(path: Path, max_chars: int = 2500) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-max_chars:]


def _find_free_port(start: int = 8501) -> int:
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start


def _self_command(flag: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, flag]
    return [sys.executable, str(Path(__file__).resolve()), flag]


def _spawn_logged(flag: str, log_name: str, env: dict[str, str] | None = None) -> tuple[subprocess.Popen, Path]:
    log_path = _log_dir() / log_name
    log_file = log_path.open("a", encoding="utf-8")
    log_file.write(f"\n--- tech_stock launch {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    log_file.flush()
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    proc = subprocess.Popen(
        _self_command(flag),
        cwd=ROOT,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env=merged_env,
        start_new_session=(sys.platform != "win32"),
    )
    log_file.close()
    return proc, log_path


def _open_terminal(flag: str) -> None:
    cmd = _self_command(flag)
    if sys.platform == "darwin":
        script = " ".join(shlex.quote(part) for part in cmd)
        subprocess.Popen([
            "osascript",
            "-e",
            'tell application "Terminal" to activate',
            "-e",
            f'tell application "Terminal" to do script {json.dumps(script)}',
        ])
        return
    if sys.platform == "win32":
        subprocess.Popen(["cmd", "/c", "start", "tech_stock", "cmd", "/k", *cmd])
        return
    terminal = os.environ.get("TERMINAL") or "x-terminal-emulator"
    subprocess.Popen([terminal, "-e", *cmd])

# ── Sub-process dispatch (called when the bundled exe is re-invoked) ─────────

def _run_streamlit() -> None:
    """Launch Streamlit server and open browser."""
    port = int(os.environ.get("TECH_STOCK_STREAMLIT_PORT", "8501"))

    def _open_browser() -> None:
        if os.environ.get("TECH_STOCK_NO_AUTO_BROWSER") == "1":
            return
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
    flag_options = {
        "server_port": port,
        "server_headless": True,
        "browser_gatherUsageStats": False,
    }
    bootstrap.load_config_options(flag_options)
    bootstrap.run(
        str(STREAMLIT_SCRIPT),
        False,
        [],
        flag_options,
    )


def _run_desktop() -> None:
    """Run the embedded Tkinter desktop app."""
    from src.desktop_app import main as desktop_main

    desktop_main()


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
    mod.main()


# ── GUI launcher ─────────────────────────────────────────────────────────────

_CHOICES = [
    ("Desktop App",
     "Embedded dashboard inside this app.\nNo browser required.",
     "desktop"),
    ("Streamlit Web UI",
     "Opens a dashboard in your browser.\nFull feature set: Dashboard, Run, History, Backtest, Editor.",
     "streamlit"),
    ("Textual Terminal UI",
     "Keyboard-driven interface in Terminal.\nNo browser needed.",
     "textual"),
    ("Command-Line (CLI)",
     "Classic terminal mode.\nUse for scripting, cron, or maximum speed.",
     "cli"),
]


def _show_launcher() -> None:
    import tkinter as tk
    from tkinter import font as tkfont
    from tkinter import messagebox

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

    status_var = tk.StringVar(value="Choose an interface to start.")

    def check_for_updates(manual: bool = False) -> None:
        status_var.set("Checking GitHub Releases for updates...")

        def worker() -> None:
            info = check_for_update()

            def finish_check() -> None:
                if info.error:
                    status_var.set("Update check failed.")
                    if manual:
                        messagebox.showwarning("Update check failed", info.error)
                    return
                if not info.available:
                    status_var.set(f"tech_stock v{info.current_version} is up to date.")
                    if manual:
                        messagebox.showinfo("No update available", f"tech_stock v{info.current_version} is up to date.")
                    return
                status_var.set(f"Version {info.latest_version} is available.")
                should_update = messagebox.askyesno(
                    "Update available",
                    f"Version {info.latest_version} is available.\n\n"
                    f"You are currently on version {info.current_version}.\n\n"
                    "Do you want to update now?\n\n"
                    "Reports, logs, uploaded CSVs, config files, and API key files will be kept.",
                )
                if not should_update:
                    return
                status_var.set(f"Updating to version {info.latest_version}...")

                def apply_worker() -> None:
                    result = apply_update(info, restart=True)

                    def finish_apply() -> None:
                        details = f"{result.message}\n\nUpdate log:\n{result.log_path}"
                        if result.downloaded_path:
                            details += f"\n\nDownloaded file:\n{result.downloaded_path}"
                        if not result.ok:
                            status_var.set("Update failed.")
                            messagebox.showerror("Update failed", details)
                            return
                        status_var.set("Update started.")
                        messagebox.showinfo("Update started", details)
                        if result.restart_started:
                            root.after(800, root.destroy)

                    root.after(0, finish_apply)

                threading.Thread(target=apply_worker, daemon=True).start()

            root.after(0, finish_check)

        threading.Thread(target=worker, daemon=True).start()

    def launch_desktop() -> None:
        status_var.set("Starting embedded desktop app ...")
        proc, log_path = _spawn_logged("--desktop", "desktop.log")

        def check_startup() -> None:
            if proc.poll() is not None:
                details = _tail(log_path)
                status_var.set("Desktop app failed to start. See the log file.")
                messagebox.showerror(
                    "Desktop app failed to start",
                    "The embedded desktop app could not start.\n\n"
                    f"Log file:\n{log_path}\n\n"
                    f"Last log lines:\n{details or '(log was empty)'}",
                )
                return
            status_var.set("Embedded desktop app is running.")

        root.after(2000, check_startup)

    def launch_streamlit() -> None:
        port = _find_free_port()
        url = f"http://localhost:{port}"
        status_var.set(f"Starting Streamlit at {url} ...")
        proc, log_path = _spawn_logged(
            "--streamlit",
            "streamlit.log",
            {
                "TECH_STOCK_STREAMLIT_PORT": str(port),
                "TECH_STOCK_NO_AUTO_BROWSER": "1",
            },
        )

        def check_startup() -> None:
            if proc.poll() is not None:
                details = _tail(log_path)
                status_var.set("Streamlit failed to start. See the log file.")
                messagebox.showerror(
                    "Streamlit failed to start",
                    "The Web UI could not start.\n\n"
                    f"Log file:\n{log_path}\n\n"
                    f"Last log lines:\n{details or '(log was empty)'}",
                )
                return
            webbrowser.open(url)
            status_var.set(f"Streamlit is running at {url}")
            messagebox.showinfo(
                "Streamlit started",
                f"The Web UI is running at:\n{url}\n\n"
                "It opened in your default browser. If the browser did not open, paste this URL manually.",
            )

        root.after(3500, check_startup)

    def launch_terminal(flag: str) -> None:
        try:
            _open_terminal(flag)
            status_var.set("Opened Terminal for tech_stock.")
        except Exception as exc:
            status_var.set("Could not open Terminal.")
            messagebox.showerror("Could not open Terminal", str(exc))

    def launch(mode: str) -> None:
        if mode == "desktop":
            launch_desktop()
        elif mode == "streamlit":
            launch_streamlit()
        elif mode == "textual":
            launch_terminal("--textual")
        elif mode == "cli":
            launch_terminal("--cli")

    for label, description, mode in _CHOICES:
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
                        command=lambda m=mode: launch(m))
        btn.pack(side="right", padx=(12, 0))

        def on_enter(e, b=btn):   b.configure(bg=BTN_HOVER)
        def on_leave(e, b=btn):   b.configure(bg=BTN_BG)
        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)

        # Clicking anywhere on the card also triggers launch
        def on_card_click(e, m=mode): launch(m)
        for w in (card, inner, left):
            w.bind("<Button-1>", on_card_click)

    # ── Footer ────────────────────────────────────────────────────────────────
    sep2 = tk.Frame(root, bg=BORDER, height=1)
    sep2.pack(fill="x", padx=32)
    tk.Label(root, textvariable=status_var,
             fg=MUTED, bg=BG, font=desc_font).pack(pady=(10, 0))
    tk.Button(
        root,
        text=f"Check Updates (v{APP_VERSION})",
        font=desc_font,
        bg=BG,
        fg=GREEN,
        relief="flat",
        cursor="hand2",
        command=lambda: check_for_updates(manual=True),
    ).pack(pady=(4, 0))
    tk.Label(root, text="Powered by Claude  ·  Anthropic",
             fg=MUTED, bg=BG, font=desc_font).pack(pady=(4, 10))

    # Centre window on screen
    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")
    if os.environ.get("TECH_STOCK_SKIP_UPDATE_CHECK") != "1":
        root.after(900, lambda: check_for_updates(manual=False))

    root.mainloop()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    argv = sys.argv[1:]

    if argv and argv[0] == "--desktop":
        _run_desktop()
    elif argv and argv[0] == "--streamlit":
        _run_streamlit()
    elif argv and argv[0] == "--textual":
        _run_textual()
    elif argv and argv[0] == "--cli":
        _run_cli(argv[1:])
    else:
        _show_launcher()


if __name__ == "__main__":
    main()
