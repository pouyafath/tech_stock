#!/usr/bin/env bash
# Optional interface launcher for tech_stock.
# Keeps ./run.sh unchanged for the original CLI workflow.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -d ".venv" ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

python src/ui_launcher.py
