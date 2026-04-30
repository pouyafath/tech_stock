"""
Choose between the original CLI, Streamlit dashboard, and Textual TUI.

This launcher is additive. The original commands still work:
    python src/main.py
    ./run.sh
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    options = {
        "1": ("Original CLI", [sys.executable, str(ROOT / "src" / "main.py")]),
        "2": ("Streamlit dashboard", [sys.executable, "-m", "streamlit", "run", str(ROOT / "ui" / "streamlit_app.py")]),
        "3": ("Textual terminal UI", [sys.executable, str(ROOT / "ui" / "textual_app.py")]),
    }

    print("\ntech_stock interface launcher")
    for key, (label, _) in options.items():
        print(f"  [{key}] {label}")
    choice = input("Choose interface [1/2/3, Enter = 1]: ").strip() or "1"

    if choice not in options:
        print("Invalid choice.")
        return 2

    _, command = options[choice]
    return subprocess.call(command, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
