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


def save_settings(settings: dict) -> None:
    """Persist the full settings dict back to config/settings.json."""
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")


def set_setting_if_absent(key: str, value) -> bool:
    """Seed ``key`` with ``value`` only when it isn't already configured.

    Returns True if a write happened. This never overwrites an existing value,
    so it can seed a sensible default (e.g. a monthly spend cap) for new users
    without disrupting anyone who already set it.
    """
    try:
        settings = load_settings()
    except (FileNotFoundError, json.JSONDecodeError):
        settings = {}
    if settings.get(key) not in (None, ""):
        return False
    settings[key] = value
    save_settings(settings)
    return True
