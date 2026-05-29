"""Coverage for src/app_gui.py — the native launcher (v1.18 backfill).

The launcher is pure dispatch glue: it builds argv lists, picks a free
port, opens log files, and routes ``--desktop``/``--streamlit``/``--textual``/
``--cli`` flags to the right sub-runner. We mock subprocess, tkinter, and
streamlit so the tests run in CI without a display.
"""

from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

import pytest

from src import app_gui


# ── _self_command ──────────────────────────────────────────────────────────


def test_self_command_in_dev_mode_points_at_python(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(sys, "executable", "/usr/bin/python3")
    argv = app_gui._self_command("--cli")
    assert argv[0] == "/usr/bin/python3"
    # In dev mode the second element is the absolute path to app_gui.py.
    assert argv[1].endswith("app_gui.py")
    assert argv[2] == "--cli"


def test_self_command_in_frozen_mode_uses_executable(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/Applications/tech_stock.app/Contents/MacOS/tech_stock")
    argv = app_gui._self_command("--streamlit")
    # When frozen, sys.executable IS the relaunch target — no app_gui.py needed.
    assert argv == ["/Applications/tech_stock.app/Contents/MacOS/tech_stock", "--streamlit"]


# ── _find_free_port ─────────────────────────────────────────────────────────


def test_find_free_port_returns_start_when_first_is_free(monkeypatch):
    class FakeSock:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def settimeout(self, _t):
            pass

        def connect_ex(self, _addr):
            return 1  # non-zero == port is FREE (connect failed)

    monkeypatch.setattr(socket, "socket", FakeSock)
    assert app_gui._find_free_port(start=8501) == 8501


def test_find_free_port_walks_when_ports_are_busy(monkeypatch):
    busy_until = 8505

    class FakeSock:
        def __init__(self, *_args, **_kwargs):
            self.port = None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def settimeout(self, _t):
            pass

        def connect_ex(self, addr):
            # 0 means "port is busy" (connect succeeded).
            return 0 if addr[1] < busy_until else 1

    monkeypatch.setattr(socket, "socket", FakeSock)
    assert app_gui._find_free_port(start=8501) == busy_until


# ── _tail ───────────────────────────────────────────────────────────────────


def test_tail_returns_last_n_chars(tmp_path):
    path = tmp_path / "log.txt"
    path.write_text("a" * 100 + "TAIL")
    assert app_gui._tail(path, max_chars=4) == "TAIL"


def test_tail_returns_empty_on_missing_file(tmp_path):
    assert app_gui._tail(tmp_path / "absent.txt") == ""


# ── _open_path_in_finder ────────────────────────────────────────────────────


def test_open_path_in_finder_uses_open_on_macos(monkeypatch):
    captured = []
    expected_path = str(Path("/tmp/example"))
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(app_gui.subprocess, "Popen", lambda cmd, **kw: captured.append(cmd) or object())
    app_gui._open_path_in_finder(Path("/tmp/example"))
    assert captured == [["open", expected_path]]


def test_open_path_in_finder_uses_xdg_on_linux(monkeypatch):
    captured = []
    expected_path = str(Path("/tmp/example"))
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(app_gui.subprocess, "Popen", lambda cmd, **kw: captured.append(cmd) or object())
    app_gui._open_path_in_finder(Path("/tmp/example"))
    assert captured == [["xdg-open", expected_path]]


def test_open_path_in_finder_swallows_errors(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("simulated")

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(app_gui.subprocess, "Popen", boom)
    # Must not raise — launcher must never crash on a Finder failure.
    app_gui._open_path_in_finder(Path("/tmp/anything"))


# ── _latest_report_summary ──────────────────────────────────────────────────


def test_latest_report_summary_empty_when_no_reports(monkeypatch):
    # Mock ui_support to return None — simulates a fresh install with no reports.
    monkeypatch.setattr("src.ui_support.latest_report", lambda: None)
    title, hint = app_gui._latest_report_summary()
    assert title == "No reports yet"
    assert "first one" in hint.lower() or "your first" in hint.lower()


def test_latest_report_summary_returns_title_when_present(monkeypatch, tmp_path):
    report = tmp_path / "20260527_0930_morning.md"
    report.write_text("# example")
    monkeypatch.setattr("src.ui_support.latest_report", lambda: report)
    title, hint = app_gui._latest_report_summary()
    assert title == report.name
    # The hint includes a timestamp string ("Updated …")
    assert "Updated" in hint


# ── _CHOICES table integrity ────────────────────────────────────────────────


def test_choices_list_has_four_entries_with_required_shape():
    assert len(app_gui._CHOICES) == 4
    for label, description, icon, mode in app_gui._CHOICES:
        assert label and isinstance(label, str)
        assert description and isinstance(description, str)
        assert icon and isinstance(icon, str)
        assert mode in {"desktop", "streamlit", "textual", "cli"}


# ── PALETTE wiring ─────────────────────────────────────────────────────────


def test_palette_shared_with_ui_theme():
    """app_gui should consume the same PALETTE as the rest of the UI."""
    from src.ui_theme import PALETTE as theme_palette

    if app_gui.PALETTE is None:  # pragma: no cover — bundle-edge fallback
        pytest.skip("PALETTE fallback path; nothing to compare")
    assert app_gui.PALETTE.accent == theme_palette.accent
    assert app_gui.PALETTE.danger == theme_palette.danger
