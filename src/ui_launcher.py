"""
Choose between the original CLI, Streamlit dashboard, and Textual TUI.

Usage:
    python src/ui_launcher.py          # interactive menu
    python src/ui_launcher.py 1        # CLI (pass args through)
    python src/ui_launcher.py 2        # Streamlit
    python src/ui_launcher.py 3        # Textual
    python src/ui_launcher.py 4        # Embedded desktop UI
"""

from __future__ import annotations

import subprocess
import os
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.updater import apply_update, check_for_update, update_status_text  # noqa: E402

BANNER = r"""
  _            _        _            _
 | |_ ___  ___| |__    | |_ ___  ___| | __
 | __/ _ \/ __| '_ \   | __/ _ \/ __| |/ /
 | ||  __/ (__| | | |  | ||  __/ (__|   <
  \__\___|\___|_| |_|   \__\___|\___|_|\_\

  AI-powered portfolio advisor
"""

OPTIONS = {
    "1": {
        "label": "CLI             — Terminal, fastest, pass session flags directly",
        "desc": "Original command-line interface",
    },
    "2": {
        "label": "Streamlit UI    — Web dashboard, open in browser, full feature set",
        "desc": "Streamlit web dashboard",
    },
    "3": {
        "label": "Textual TUI     — Rich terminal UI, keyboard-driven, no browser needed",
        "desc": "Textual terminal dashboard",
    },
    "4": {
        "label": "Desktop App     — Embedded dashboard, no browser needed",
        "desc": "embedded desktop dashboard",
    },
    "5": {
        "label": "Update          — Check GitHub Releases and update",
        "desc": "application updater",
    },
}


def _streamlit_command() -> list[str]:
    return [sys.executable, "-m", "streamlit", "run", str(ROOT / "ui" / "streamlit_app.py")]


def _launch_streamlit(extra_args: list[str]) -> int:
    port = 8501
    cmd = _streamlit_command()
    # Detect a custom port flag already in extra_args
    for i, arg in enumerate(extra_args):
        if arg == "--server.port" and i + 1 < len(extra_args):
            try:
                port = int(extra_args[i + 1])
            except ValueError:
                pass
    cmd += extra_args

    print(f"\n  Starting Streamlit on http://localhost:{port} …")
    print("  Press Ctrl+C to stop.\n")

    # Give streamlit a moment to bind, then open the browser
    proc = subprocess.Popen(cmd, cwd=ROOT)
    try:
        time.sleep(2)
        webbrowser.open(f"http://localhost:{port}")
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    # Non-interactive: first arg is a choice key (1/2/3/4) passed by the shell script
    choice = ""
    extra_args: list[str] = []
    if argv:
        first = argv[0]
        if first in OPTIONS:
            choice = first
            extra_args = argv[1:]
        else:
            # Treat all args as CLI passthrough (e.g. "morning --model opus")
            choice = "1"
            extra_args = argv

    # Interactive menu
    if not choice:
        if os.environ.get("TECH_STOCK_SKIP_UPDATE_CHECK") != "1":
            info = check_for_update(timeout=4.0)
            if info.available:
                print(f"\n  Update available: version {info.latest_version} (current {info.current_version})")
                try:
                    answer = input("  Do you want to update before launching? [y/N]: ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    answer = ""
                    print()
                if answer in {"y", "yes"}:
                    result = apply_update(info, restart=False)
                    print(f"  {result.message}")
                    print(f"  Update log: {result.log_path}")
                    return 0 if result.ok else 1
            elif info.error:
                print(f"  Update check skipped: {info.error}")

        print(BANNER)
        print("  How would you like to run tech_stock?\n")
        for key, meta in OPTIONS.items():
            print(f"    [{key}]  {meta['label']}")
        print()
        try:
            choice = input("  Choose [1/2/3/4/5, Enter = 1]: ").strip() or "1"
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

    if choice not in OPTIONS:
        print(f"  Invalid choice: {choice!r}. Pick 1, 2, 3, 4, or 5.")
        return 2

    print(f"\n  Launching: {OPTIONS[choice]['desc']} …\n")

    if choice == "1":
        cmd = [sys.executable, str(ROOT / "src" / "main.py")] + extra_args
        return subprocess.call(cmd, cwd=ROOT)

    if choice == "2":
        return _launch_streamlit(extra_args)

    if choice == "3":
        cmd = [sys.executable, str(ROOT / "ui" / "textual_app.py")] + extra_args
        return subprocess.call(cmd, cwd=ROOT)

    if choice == "4":
        cmd = [sys.executable, str(ROOT / "src" / "desktop_app.py")] + extra_args
        return subprocess.call(cmd, cwd=ROOT)

    if choice == "5":
        info = check_for_update()
        print(update_status_text(info))
        if info.error or not info.available:
            return 1 if info.error else 0
        answer = input("  Do you want to update now? [y/N]: ").strip().lower()
        if answer not in {"y", "yes"}:
            return 0
        result = apply_update(info, restart=False)
        print(result.message)
        print(f"Update log: {result.log_path}")
        return 0 if result.ok else 1

    return 0  # unreachable


if __name__ == "__main__":
    raise SystemExit(main())
