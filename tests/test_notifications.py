"""Coverage for src.notifications (v1.18 desktop notifications)."""

from __future__ import annotations

import subprocess
import sys

import pytest

from src import notifications


@pytest.fixture(autouse=True)
def _clear_dedup_cache():
    notifications.reset_dedup_cache()
    yield
    notifications.reset_dedup_cache()


# ── Argv builders (escaping logic) ─────────────────────────────────────────


def test_osascript_argv_escapes_double_quotes():
    argv = notifications._build_osascript_argv("hi", 'msg with "quote"')
    assert argv[0] == "osascript"
    assert argv[1] == "-e"
    script = argv[2]
    # Double-quotes inside the message must be escaped, not crash AppleScript.
    assert '\\"quote\\"' in script
    assert script.startswith("display notification")


def test_osascript_argv_escapes_backslashes():
    argv = notifications._build_osascript_argv("hi", "path/with\\backslash")
    assert "with\\\\backslash" in argv[2]


def test_notify_send_argv_normalises_urgency():
    argv = notifications._build_notify_send_argv("title", "body", urgency="invalid")
    # Unknown urgency should normalise to "normal" rather than fail.
    assert "normal" in argv


@pytest.mark.parametrize("urgency", ["low", "normal", "critical"])
def test_notify_send_argv_honours_valid_urgency(urgency):
    argv = notifications._build_notify_send_argv("title", "body", urgency=urgency)
    assert urgency in argv


# ── send() flow with mocked subprocess ─────────────────────────────────────


def test_send_dispatches_to_osascript_on_macos(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(notifications.subprocess, "run", fake_run)
    result = notifications.send("Title", "Body")
    assert result.sent is True
    assert result.backend == "osascript"
    assert captured["cmd"][0] == "osascript"


def test_send_dispatches_to_notify_send_on_linux(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(notifications.shutil, "which", lambda binary: "/usr/bin/notify-send" if binary == "notify-send" else None)
    monkeypatch.setattr(notifications.subprocess, "run", fake_run)
    result = notifications.send("Title", "Body", urgency="critical")
    assert result.sent is True
    assert result.backend == "notify-send"
    assert "critical" in captured["cmd"]


def test_send_returns_no_backend_when_no_native_handler(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(notifications.shutil, "which", lambda binary: None)
    result = notifications.send("Title", "Body")
    assert result.sent is False
    assert result.backend == "none"
    assert result.error in {"no_backend_available", None} or result.error.startswith("no_backend")


def test_send_dedup_suppresses_duplicate_within_window(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(notifications.subprocess, "run", fake_run)
    first = notifications.send("Same", "Same")
    second = notifications.send("Same", "Same")
    assert first.sent is True
    assert second.sent is False
    assert second.deduped is True


def test_send_dedup_allows_different_messages(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(notifications.subprocess, "run", fake_run)
    assert notifications.send("a", "x").sent is True
    assert notifications.send("a", "y").sent is True  # different body → not deduped


def test_send_channel_disabled_via_settings(monkeypatch):
    monkeypatch.setattr(notifications, "_load_settings", lambda: {"enabled": True, "channels": {"trailing_stop_breach": False}})
    monkeypatch.setattr(sys, "platform", "darwin")
    # Even though osascript would succeed, the channel is off → skipped.
    result = notifications.send("Title", "Body", channel="trailing_stop_breach")
    assert result.sent is False
    assert result.skipped_reason == "channel_disabled"


def test_send_top_level_enabled_false_silences_everything(monkeypatch):
    monkeypatch.setattr(notifications, "_load_settings", lambda: {"enabled": False, "channels": {"trailing_stop_breach": True}})
    monkeypatch.setattr(sys, "platform", "darwin")
    result = notifications.send("Title", "Body", channel="trailing_stop_breach")
    assert result.sent is False
    assert result.skipped_reason == "channel_disabled"


def test_send_never_raises_on_subprocess_error(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.SubprocessError("boom")

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(notifications.subprocess, "run", fake_run)
    result = notifications.send("Title", "Body")
    assert result.sent is False
    assert result.backend == "none"
    assert "subprocess_error" in (result.error or "")


# ── send_many() collapsing ─────────────────────────────────────────────────


def test_send_many_collapses_long_batches(monkeypatch):
    sent = []

    def fake_send(title, message, **kwargs):
        sent.append((title, message))
        return notifications.SendResult(sent=True, backend="fake")

    monkeypatch.setattr(notifications, "send", fake_send)
    results = notifications.send_many([(f"t{i}", f"m{i}") for i in range(10)], channel="trailing_stop_breach")
    # 3 individual + 1 collapsed summary = 4 total
    assert len(results) == 4
    assert "plus 7 more" in sent[-1][1]


def test_send_many_passes_through_small_batches(monkeypatch):
    sent = []

    def fake_send(title, message, **kwargs):
        sent.append((title, message))
        return notifications.SendResult(sent=True, backend="fake")

    monkeypatch.setattr(notifications, "send", fake_send)
    results = notifications.send_many([(f"t{i}", f"m{i}") for i in range(3)])
    assert len(results) == 3
