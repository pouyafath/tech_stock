"""CLI surface tests for main.py and ui_launcher.py.

These tests cover the small but user-visible behaviors of the command-line
entrypoint (--version, --help shape) without exercising the full report
pipeline. They protect against silent regressions in the flag wiring that
the broader pipeline tests would not catch.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest

from src import ui_launcher
from src.version import APP_VERSION


def test_main_version_flag_prints_app_version(capsys, monkeypatch):
    """`python -m src.main --version` must print the canonical app version string."""
    monkeypatch.setattr("sys.argv", ["main.py", "--version"])
    from src import main as main_module

    with pytest.raises(SystemExit) as exc_info:
        main_module.main()

    assert exc_info.value.code == 0
    captured = capsys.readouterr().out
    assert APP_VERSION in captured
    assert "tech_stock" in captured


@pytest.mark.parametrize("flag", ["--version", "-V"])
def test_ui_launcher_version_flag(flag, monkeypatch):
    """`./run.sh --version` should answer without launching the menu or update check."""
    # The launcher must not call check_for_update or network code on --version.
    monkeypatch.setattr(
        "src.ui_launcher.check_for_update",
        lambda *args, **kwargs: pytest.fail("update check should not run on --version"),
    )

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        rc = ui_launcher.main([flag])

    assert rc == 0
    output = buffer.getvalue()
    assert APP_VERSION in output
    assert "tech_stock" in output
