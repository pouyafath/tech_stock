#!/usr/bin/env bash
# run.sh — One-command launcher for tech_stock portfolio advisor
#
# Usage:
#   ./run.sh                            # Show UI-choice menu (CLI / Streamlit / Textual)
#   ./run.sh morning                    # Skip menu → CLI, morning session
#   ./run.sh afternoon --model opus     # Skip menu → CLI, afternoon + Opus
#   ./run.sh 2                          # Skip menu → Streamlit directly
#   ./run.sh 3                          # Skip menu → Textual directly
#
# Requirements:
#   - ANTHROPIC_API_KEY set in .env (or exported in your shell)
#   - Python 3.11+ with venv in .venv/

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Load .env if present ────────────────────────────────────────────────────
if [ -f ".env" ]; then
    # Export KEY=VALUE lines, skip comments and blanks
    set -a
    # shellcheck disable=SC1091
    source <(grep -E '^[A-Z_]+=.+' .env | grep -v '^#')
    set +a
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

# ── Activate virtual environment ─────────────────────────────────────────────
if [ -d ".venv" ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
elif command -v python3 &>/dev/null; then
    echo "No .venv found — running with system Python. Consider: python3 -m venv .venv && pip install -r requirements.txt"
else
    echo "ERROR: Python 3 not found. Install Python 3.11+ first."
    exit 1
fi

# ── Launch ───────────────────────────────────────────────────────────────────
# With no arguments → show the UI-choice menu.
# With arguments that look like a session flag (morning/afternoon/--...) →
#   pass them straight to the CLI so existing cron/script callers still work.
# With "2" or "3" as the first argument → jump straight to that UI.

if [ $# -eq 0 ]; then
    # No args: interactive menu
    python src/ui_launcher.py
else
    python src/ui_launcher.py "$@"
fi
