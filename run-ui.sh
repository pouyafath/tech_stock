#!/usr/bin/env bash
# run-ui.sh — Alias for ./run.sh with no arguments (shows the UI-choice menu).
# Kept for backward compatibility.  ./run.sh is now the canonical launcher.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/run.sh" "$@"
