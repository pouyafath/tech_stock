"""Coverage for src.config persistence helpers."""

from __future__ import annotations

import json

from src import config


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(config, "SETTINGS_PATH", path)
    config.save_settings({"a": 1, "b": "two"})
    assert config.load_settings() == {"a": 1, "b": "two"}
    # Trailing newline for clean diffs.
    assert path.read_text(encoding="utf-8").endswith("}\n")


def test_set_setting_if_absent_seeds_only_when_missing(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(config, "SETTINGS_PATH", path)
    # No file yet → seeds the default and reports a write.
    assert config.set_setting_if_absent("monthly_budget_usd", 25) is True
    assert config.load_settings()["monthly_budget_usd"] == 25
    # Already present → never overwritten.
    assert config.set_setting_if_absent("monthly_budget_usd", 99) is False
    assert config.load_settings()["monthly_budget_usd"] == 25


def test_set_setting_if_absent_treats_null_as_absent(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"monthly_budget_usd": None, "other": 1}), encoding="utf-8")
    monkeypatch.setattr(config, "SETTINGS_PATH", path)
    assert config.set_setting_if_absent("monthly_budget_usd", 25) is True
    saved = config.load_settings()
    assert saved["monthly_budget_usd"] == 25
    assert saved["other"] == 1  # preserved
