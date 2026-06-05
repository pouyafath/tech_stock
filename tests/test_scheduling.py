"""Coverage for src.scheduling (v1.18 schedule installer)."""

from __future__ import annotations

import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from src import scheduling
from src.scheduling import (
    LABEL,
    ScheduleTime,
    current_schedule,
    install_schedule,
    preview_schedule,
    uninstall_schedule,
)

# ── Artefact builders (no side effects) ────────────────────────────────────


def test_preview_schedule_returns_backend_and_body():
    times = [ScheduleTime(7, 0, "morning"), ScheduleTime(13, 30, "afternoon")]
    backend, body = preview_schedule(times)
    assert backend in {"launchd", "task_scheduler", "cron"}
    assert body  # non-empty


def test_launchd_plist_contains_both_intervals():
    times = [ScheduleTime(7, 0, "morning"), ScheduleTime(13, 30, "afternoon")]
    body = scheduling._build_launchd_plist(times)
    # Both Hour entries must appear, in any order.
    assert "<integer>7</integer>" in body
    assert "<integer>13</integer>" in body
    assert "<integer>0</integer>" in body
    assert "<integer>30</integer>" in body
    assert LABEL in body


def test_launchd_plist_parses_as_xml_after_doctype_strip():
    times = [ScheduleTime(8, 15, "morning")]
    body = scheduling._build_launchd_plist(times)
    cleaned = "\n".join(line for line in body.splitlines() if not line.startswith("<!DOCTYPE"))
    root = ET.fromstring(cleaned)  # must not raise
    assert root.tag == "plist"


def test_task_scheduler_xml_includes_triggers_for_each_time():
    times = [ScheduleTime(7, 0, "morning"), ScheduleTime(14, 30, "afternoon")]
    body = scheduling._build_task_scheduler_xml(times)
    root = ET.fromstring(body)
    # Triggers element with two CalendarTriggers
    ns = "{http://schemas.microsoft.com/windows/2004/02/mit/task}"
    triggers = root.findall(f"{ns}Triggers/{ns}CalendarTrigger")
    assert len(triggers) == 2


def test_cron_lines_one_per_slot():
    times = [ScheduleTime(7, 0, "morning"), ScheduleTime(14, 30, "afternoon")]
    lines = scheduling._build_cron_lines(times)
    assert len(lines) == 2
    # First line should start with "0 7 * * *"; second with "30 14 * * *"
    assert lines[0].startswith("0 7 * * *")
    assert lines[1].startswith("30 14 * * *")
    # Both lines carry the marker for idempotent removal
    assert all(scheduling._cron_marker() in line for line in lines)


# ── Install / uninstall (macOS, redirected to tmp_path) ────────────────────


@pytest.fixture
def isolated_launchd(monkeypatch, tmp_path):
    """Redirect the launchd plist path into tmp_path and skip launchctl."""
    fake_path = tmp_path / f"{LABEL}.plist"
    monkeypatch.setattr(scheduling, "_launchd_path", lambda: fake_path)

    # Make ``launchctl`` look absent so ``_install_launchd`` won't shell out.
    monkeypatch.setattr(scheduling.shutil, "which", lambda binary: None)
    monkeypatch.setattr(sys, "platform", "darwin")
    return fake_path


def test_install_then_current_then_uninstall_launchd(isolated_launchd):
    times = [ScheduleTime(7, 0, "morning"), ScheduleTime(13, 30, "afternoon")]
    result = install_schedule(times)
    assert result.ok
    assert result.backend == "launchd"
    assert isolated_launchd.exists()

    current = current_schedule()
    assert current.installed
    assert len(current.times) == 2
    assert {(t.hour, t.minute) for t in current.times} == {(7, 0), (13, 30)}

    removed = uninstall_schedule()
    assert removed.ok
    assert not isolated_launchd.exists()


def test_install_empty_times_returns_noop(isolated_launchd):
    result = install_schedule([])
    assert result.ok is False
    assert result.backend == "noop"


def test_current_schedule_returns_not_installed_when_missing(isolated_launchd):
    current = current_schedule()
    assert current.installed is False
    assert current.times == []


def test_uninstall_is_safe_when_nothing_installed(isolated_launchd):
    result = uninstall_schedule()
    assert result.ok is True
    # File should still not exist after a no-op uninstall
    assert not isolated_launchd.exists()


# ── Quoting helpers ────────────────────────────────────────────────────────


def test_xml_escape_handles_special_characters():
    assert scheduling._xml_escape("<a>") == "&lt;a&gt;"
    assert scheduling._xml_escape('quote"') == "quote&quot;"
    assert scheduling._xml_escape("a & b") == "a &amp; b"


def test_quote_posix_passes_through_safe_strings():
    assert scheduling._quote_posix("python3") == "python3"
    assert scheduling._quote_posix("/usr/bin/python3") == "/usr/bin/python3"


def test_quote_posix_quotes_strings_with_spaces():
    assert scheduling._quote_posix("path with space").startswith("'")
    # Single quotes inside must be escaped.
    quoted = scheduling._quote_posix("it's")
    assert "'\\''" in quoted


def test_quote_windows_wraps_strings_with_spaces():
    out = scheduling._quote_windows("path with space")
    assert out.startswith('"') and out.endswith('"')


def test_scheduled_command_uses_session_type_flag():
    cmd = scheduling._scheduled_command("afternoon")
    assert "--session-type" in cmd
    assert "afternoon" in cmd
    assert "src.main" in cmd
    assert "--non-interactive" in cmd


# ── Round-trip: parse_launchd_times reproduces install times ──────────────


def test_parse_launchd_times_round_trip():
    times = [ScheduleTime(6, 45, "morning"), ScheduleTime(15, 5, "afternoon")]
    body = scheduling._build_launchd_plist(times)
    parsed = scheduling._parse_launchd_times(body)
    assert {(t.hour, t.minute) for t in parsed} == {(6, 45), (15, 5)}


def test_parse_launchd_times_returns_empty_on_garbage():
    assert scheduling._parse_launchd_times("not xml") == []
