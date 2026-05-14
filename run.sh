#!/usr/bin/env bash
# run.sh — One-command launcher for tech_stock portfolio advisor
#
# Usage:
#   ./run.sh                            # Show UI-choice menu (CLI / Streamlit / Textual / Desktop)
#   ./run.sh morning                    # Skip menu → CLI, morning session
#   ./run.sh afternoon --model opus     # Skip menu → CLI, afternoon + Opus
#   ./run.sh 2                          # Skip menu → Streamlit directly
#   ./run.sh 3                          # Skip menu → Textual directly
#   ./run.sh 4                          # Skip menu → embedded desktop UI
#
# Requirements:
#   - ANTHROPIC_API_KEY set in .env (or exported in your shell)
#   - Python 3.11+ with venv in .venv/

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Load .env if present ────────────────────────────────────────────────────
# We use a `while read` loop instead of `source <(grep ...)` because macOS
# ships bash 3.2, where process substitution can return before the subprocess
# finishes writing — leading to silently-empty environment variables. This
# pattern works on bash 3.2+ and any POSIX-compatible shell.
if [ -f ".env" ]; then
    while IFS='=' read -r key value; do
        case "$key" in
            ''|\#*) continue ;;        # skip blanks and comments
        esac
        # Strip optional surrounding quotes from the value
        value="${value%\"}"
        value="${value#\"}"
        value="${value%\'}"
        value="${value#\'}"
        export "$key"="$value"
    done < .env
fi

# Also load API_KEYS.txt if .env didn't have a key but the legacy file does.
if [ -z "$ANTHROPIC_API_KEY" ] && [ -f "API_KEYS.txt" ]; then
    while IFS='=' read -r key value; do
        case "$key" in
            ''|\#*) continue ;;
        esac
        value="${value%\"}"; value="${value#\"}"
        value="${value%\'}"; value="${value#\'}"
        export "$key"="$value"
    done < API_KEYS.txt
fi

# ── Check API key ────────────────────────────────────────────────────────────
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo ""
    echo "  ERROR: ANTHROPIC_API_KEY is not set."
    echo "  Add it to your .env file:"
    echo "    ANTHROPIC_API_KEY=sk-ant-api03-..."
    echo ""
    exit 1
fi

# ── Pick the Python interpreter ──────────────────────────────────────────────
# Use .venv/bin/python directly when available — `source .venv/bin/activate`
# can be silently overridden when Anaconda has injected its own python earlier
# in PATH.  Direct invocation is unambiguous.
if [ -x ".venv/bin/python" ]; then
    PYTHON_BIN=".venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON_BIN="python3"
    echo "  Note: no .venv/bin/python found — falling back to system python3."
    echo "  For best results: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
else
    echo "ERROR: Python 3 not found. Install Python 3.11+ first."
    exit 1
fi

# ── Launch ───────────────────────────────────────────────────────────────────
# With no arguments → show the UI-choice menu.
# With arguments that look like a session flag (morning/afternoon/--...) →
#   pass them straight to the CLI so existing cron/script callers still work.
# With "2", "3", or "4" as the first argument → jump straight to that UI.

if [ $# -eq 0 ]; then
    # No args: interactive menu
    "$PYTHON_BIN" src/ui_launcher.py
else
    "$PYTHON_BIN" src/ui_launcher.py "$@"
fi
