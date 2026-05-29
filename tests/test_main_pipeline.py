"""Coverage for the main.py orchestration layer (v1.18 backfill).

Targets the helpers main.py exposes to make the pipeline testable, not the
full end-to-end run (which would need real network calls and is exercised
elsewhere via mocked e2e tests). Focus areas:

* ``find_csv_by_date`` — bounded-search behaviour (fixed in v1.15 hang)
* ``ensure_workspace`` — idempotent workspace creation
* ``api_key_search_paths`` — produces a deduplicated list of candidate paths
* ``validate_environment`` — exit codes + success
* ``_maybe_fire_notifications`` — the new v1.18 hook
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from src import main as main_module


# ── find_csv_by_date ───────────────────────────────────────────────────────


def test_find_csv_by_date_returns_none_when_nothing_found(monkeypatch, tmp_path):
    monkeypatch.setattr(main_module, "UPLOAD_DIR", tmp_path / "uploads", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    # Empty Downloads / Desktop / Documents — nothing matches today's pattern.
    assert main_module.find_csv_by_date("holdings-report") is None


def test_find_csv_by_date_finds_in_upload_dir_first(monkeypatch, tmp_path):
    from datetime import datetime as _dt

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    today = _dt.now().strftime("%Y-%m-%d")
    candidate = upload_dir / f"holdings-report-{today}.csv"
    candidate.write_text("ticker,quantity\nNVDA,5\n")
    monkeypatch.setattr(main_module, "UPLOAD_DIR", upload_dir, raising=False)

    found = main_module.find_csv_by_date("holdings-report")
    assert found == candidate


def test_find_csv_by_date_does_not_recurse_home(monkeypatch, tmp_path):
    """v1.15 hang regression guard — should NOT recursively glob the home dir."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(main_module, "UPLOAD_DIR", tmp_path / "uploads", raising=False)

    # Place a file in a deeply nested folder that the old implementation
    # would have found via Path.home().glob("**/{pattern}").
    deep = tmp_path / "a" / "b" / "c" / "d" / "node_modules"
    deep.mkdir(parents=True)
    from datetime import datetime as _dt

    today = _dt.now().strftime("%Y-%m-%d")
    (deep / f"holdings-report-{today}.csv").write_text("")
    # The bounded search must NOT find this file.
    assert main_module.find_csv_by_date("holdings-report") is None


# ── api_key_search_paths ──────────────────────────────────────────────────


def test_api_key_search_paths_is_deduped():
    paths = main_module.api_key_search_paths()
    assert len(paths) == len(set(paths))
    assert all(isinstance(p, Path) for p in paths)


def test_api_key_search_paths_includes_template_locations():
    paths = main_module.api_key_search_paths()
    names = {p.name for p in paths}
    # Several known fallback file names should appear:
    assert "API_KEYS.txt" in names or any("api_keys" in n.lower() for n in names)
    assert ".env" in names


# ── ensure_workspace ───────────────────────────────────────────────────────


def test_ensure_workspace_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setattr(main_module, "ROOT", tmp_path, raising=False)
    monkeypatch.setattr(main_module, "CONFIG_DIR", tmp_path / "config", raising=False)
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path / "data", raising=False)
    monkeypatch.setattr(main_module, "REPORTS_DIR", tmp_path / "reports", raising=False)
    monkeypatch.setattr(main_module, "RECS_LOG_DIR", tmp_path / "data" / "recommendations_log", raising=False)
    monkeypatch.setattr(main_module, "UPLOAD_DIR", tmp_path / "temporary_upload", raising=False)
    # First call — creates everything.
    main_module.ensure_workspace()
    # Second call — must not raise.
    main_module.ensure_workspace()
    assert (tmp_path / "data").exists()
    assert (tmp_path / "reports").exists()


# ── validate_environment ───────────────────────────────────────────────────


def test_validate_environment_passes_when_anthropic_key_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake-key-12345")
    # Don't actually load anything from disk — bypass the file loader.
    monkeypatch.setattr(main_module, "_load_api_keys_from_file", lambda: None)
    # Must not call sys.exit.
    main_module.validate_environment()


def test_validate_environment_exits_when_key_missing(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(main_module, "_load_api_keys_from_file", lambda: None)
    with pytest.raises(SystemExit) as excinfo:
        main_module.validate_environment()
    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert "ANTHROPIC_API_KEY" in out


# ── _maybe_fire_notifications (v1.18) ─────────────────────────────────────


def test_maybe_fire_notifications_calls_send_for_report_complete(monkeypatch, tmp_path):
    sent: list[tuple[str, str, str]] = []

    def fake_send(title, message, *, channel="general"):
        sent.append((title, message, channel))
        from src.notifications import SendResult

        return SendResult(sent=True, backend="fake")

    # Patch send in BOTH the notifications module and any cached import
    monkeypatch.setattr("src.notifications.send", fake_send)

    recommendation = {
        "priority_actions": [
            {"ticker": "NVDA", "action": "BUY", "priority": 1},
            {"ticker": "AAPL", "action": "HOLD", "priority": 3},
        ],
        "portfolio_health": {"total_value_usd_equivalent": 20000},
    }
    main_module._maybe_fire_notifications(recommendation, "morning", tmp_path / "report.md")
    # One report_complete call expected.
    report_calls = [c for c in sent if c[2] == "report_complete"]
    assert len(report_calls) == 1


def test_maybe_fire_notifications_sends_breach_when_present(monkeypatch, tmp_path):
    sent: list[tuple[str, str, str]] = []

    def fake_send(title, message, *, channel="general"):
        sent.append((title, message, channel))
        from src.notifications import SendResult

        return SendResult(sent=True, backend="fake")

    monkeypatch.setattr("src.notifications.send", fake_send)

    recommendation = {
        "priority_actions": [],
        "trailing_stop_breaches": [
            {"ticker": "TSLA", "stop_price": 240, "current_price": 235},
            {"ticker": "AMZN", "stop_price": 165, "current_price": 162},
        ],
    }
    main_module._maybe_fire_notifications(recommendation, "afternoon", tmp_path / "report.md")
    breach_calls = [c for c in sent if c[2] == "trailing_stop_breach"]
    assert len(breach_calls) == 1
    assert "2 trailing-stop" in breach_calls[0][0]


def test_maybe_fire_notifications_high_priority_threshold(monkeypatch, tmp_path):
    sent: list[tuple[str, str, str]] = []

    def fake_send(title, message, *, channel="general"):
        sent.append((title, message, channel))
        from src.notifications import SendResult

        return SendResult(sent=True, backend="fake")

    monkeypatch.setattr("src.notifications.send", fake_send)

    # Three actions with priority <= 2 → high_priority_action channel fires.
    recommendation = {
        "priority_actions": [
            {"ticker": "A", "action": "BUY", "priority": 1},
            {"ticker": "B", "action": "ADD", "priority": 2},
            {"ticker": "C", "action": "TRIM", "priority": 2},
        ]
    }
    main_module._maybe_fire_notifications(recommendation, "morning", tmp_path / "r.md")
    hp_calls = [c for c in sent if c[2] == "high_priority_action"]
    assert len(hp_calls) == 1


def test_maybe_fire_notifications_swallows_send_failures(monkeypatch, tmp_path):
    def boom(*args, **kwargs):
        raise RuntimeError("simulated")

    monkeypatch.setattr("src.notifications.send", boom)
    # Must not raise — even if every notification call fails the report run
    # is already complete.
    try:
        main_module._maybe_fire_notifications({}, "morning", tmp_path / "r.md")
    except RuntimeError:
        pytest.fail("_maybe_fire_notifications must never propagate notification errors")
