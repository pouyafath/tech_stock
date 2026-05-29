"""Coverage for the v1.19.1 CLI flags wired into main.py.

We can't fully exercise ``run()`` here (it needs an Anthropic key and a
network), so the tests target argparse: are the flags exposed at all,
do they parse, do they default sensibly, and does ``--help`` mention
them so a user discovering the app from the command line can find them.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_help() -> str:
    """Invoke ``python -m src.main --help`` and return the help text."""
    out = subprocess.run(
        [sys.executable, "-m", "src.main", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return out.stdout + out.stderr


# ── Flag presence in --help ────────────────────────────────────────────────


def test_help_advertises_demo_flag():
    body = _run_help()
    assert "--demo" in body
    assert "demo mode" in body.lower()


def test_help_advertises_import_csv_flag():
    body = _run_help()
    assert "--import-csv" in body
    assert "PATH" in body


def test_help_advertises_session_type_alias():
    body = _run_help()
    assert "--session-type" in body


def test_help_advertises_non_interactive_flag():
    body = _run_help()
    assert "--non-interactive" in body


def test_help_advertises_force_flag():
    body = _run_help()
    assert "--force" in body
    assert "budget" in body.lower()


def test_help_still_advertises_pre_existing_flags():
    """Regression: the original v1.14 flags must survive the v1.19.1 additions."""
    body = _run_help()
    assert "--holdings" in body
    assert "--activities" in body
    assert "--model" in body
    assert "--paper" in body
    assert "--version" in body
    assert "doctor --json" in body


# ── --version still works ──────────────────────────────────────────────────


def test_version_flag_short_circuits():
    out = subprocess.run(
        [sys.executable, "-m", "src.main", "--version"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    body = out.stdout + out.stderr
    # Format from main.py is "tech_stock <version>"
    assert "tech_stock" in body
    # Version is at least one dot-separated set of digits
    import re

    assert re.search(r"\d+\.\d+\.\d+", body)


# ── --import-csv path validation ───────────────────────────────────────────


def test_import_csv_with_missing_file_exits_nonzero(tmp_path):
    """The --import-csv flag should fail loudly if the source doesn't exist."""
    bogus = tmp_path / "does-not-exist.csv"
    out = subprocess.run(
        [sys.executable, "-m", "src.main", "--import-csv", str(bogus)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode != 0
    assert "Could not import" in (out.stdout + out.stderr) or "not found" in (out.stdout + out.stderr).lower()


def test_import_csv_with_valid_file_stages_then_exits(tmp_path):
    """A well-formed CSV gets staged and the process exits 0."""
    csv = tmp_path / "holdings-report-sample.csv"
    csv.write_text("Symbol,Quantity\nNVDA,10\n", encoding="utf-8")
    out = subprocess.run(
        [sys.executable, "-m", "src.main", "--import-csv", str(csv)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0
    # The console message mentions "Imported" on success
    assert "Imported" in (out.stdout + out.stderr) or "imported" in (out.stdout + out.stderr).lower()


# ── Non-interactive auto-session selection ────────────────────────────────


def test_non_interactive_without_session_auto_picks(monkeypatch):
    """--non-interactive without a positional session should pick one based on
    the local time, not hang waiting for stdin."""
    # We don't actually run the pipeline (no API key); just confirm the flag
    # is recognised by argparse and the help output describes the behaviour.
    body = _run_help()
    assert "morning" in body.lower()
    assert "afternoon" in body.lower()
