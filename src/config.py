"""
config.py
Single source of truth for loading config/settings.json.

Future home for env-var overrides and validation.
"""

import json
from pathlib import Path

SETTINGS_PATH = Path(__file__).parent.parent / "config" / "settings.json"


def load_settings() -> dict:
    """Load config/settings.json as a dict."""
    with open(SETTINGS_PATH) as f:
        return json.load(f)
