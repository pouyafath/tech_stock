"""Real (headless) GUI tests for the desktop app.

Unlike ``test_desktop_app_macos.py`` — which only inspects source text and pure
helpers because it cannot assume a display — these tests actually instantiate
``DesktopApp`` under a virtual X server (xvfb in CI) and drive it. That gives the
4,800-line Tkinter app genuine smoke coverage: construction, the background
worker → progress-queue → main-thread render round-trip, the async refresh
handlers, and clean teardown.

The whole module skips cleanly when no display / Tk is available (local dev
without tkinter, or CI without xvfb), so it can never break those environments.
CI installs xvfb and runs the suite under ``xvfb-run`` so this executes for real.
"""

from __future__ import annotations

import os
import time

import pytest

tk = pytest.importorskip("tkinter")


def _display_available() -> bool:
    """True only if a real Tk root can be created and torn down."""
    try:
        root = tk.Tk()
    except Exception:
        return False
    try:
        root.destroy()
    except Exception:
        pass
    return True


if not _display_available():  # pragma: no cover — environment gate
    pytest.skip("no usable X display / Tk for GUI tests", allow_module_level=True)


@pytest.fixture
def app(monkeypatch):
    """A constructed DesktopApp, with network side-effects disabled, torn down
    safely after the test."""
    # No update-check network call, no interactive CSV-confirm dialogs.
    monkeypatch.setenv("TECH_STOCK_SKIP_UPDATE_CHECK", "1")
    monkeypatch.setenv("TECH_STOCK_SKIP_PATH_CONFIRM", "1")
    # Don't write the per-machine window-state file during tests.
    from src.desktop_app import DesktopApp

    monkeypatch.setattr(DesktopApp, "_save_window_size", lambda self: None)

    instance = DesktopApp()
    try:
        yield instance
    finally:
        instance._closing = True
        try:
            instance.destroy()
        except Exception:
            pass


def _pump_until(app, predicate, *, timeout: float = 5.0) -> bool:
    """Run the Tk event loop in short bursts until ``predicate()`` is true or the
    timeout elapses. Never enters mainloop(), so it can't hang the test."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        app.update()
        time.sleep(0.03)
    return predicate()


def test_app_constructs_with_core_widgets(app):
    """The window builds and exposes its primary tabs and status bar."""
    assert app.title() == "tech_stock"
    # The main notebook and the eight top-level tabs exist.
    assert hasattr(app, "tabs")
    for attr in (
        "dashboard_tab",
        "buy_signals_tab",
        "reports_tab",
        "performance_tab",
        "outcomes_tab",
        "learning_tab",
        "diagnostics_tab",
        "settings_tab",
    ):
        assert hasattr(app, attr), f"missing tab: {attr}"
    # The notebook carries all eight primary tabs.
    assert app.tabs.index("end") == 8


def test_background_round_trip_delivers_on_main_thread(app):
    """_run_in_background must run work() off-thread and deliver the result back
    through the progress queue on the main thread."""
    import threading

    delivered: list = []
    worker_thread: list = []

    def _work():
        worker_thread.append(threading.current_thread().name)
        return 21 * 2

    app._run_in_background(_work, lambda r: delivered.append(r))
    assert _pump_until(app, lambda: bool(delivered)), "callback never delivered"
    assert delivered == [42]
    # The work ran on a worker thread, not the main thread.
    assert worker_thread and worker_thread[0] != threading.main_thread().name


def test_background_error_routes_to_on_error(app):
    """A worker that raises must invoke on_error on the main thread, not crash."""
    errors: list = []

    def _boom():
        raise RuntimeError("kaboom")

    app._run_in_background(_boom, lambda r: None, on_error=lambda exc: errors.append(str(exc)))
    assert _pump_until(app, lambda: bool(errors)), "on_error never fired"
    assert "kaboom" in errors[0]


def test_refresh_performance_tab_renders_off_thread(app, monkeypatch):
    """The async refresh path updates the tab's status without blocking — here
    with a not-ready view so we don't need the full metrics payload."""
    import src.desktop.app as desktop_mod

    monkeypatch.setattr(
        desktop_mod,
        "portfolio_performance_summary",
        lambda **_kw: {"ready": False, "reason": "stubbed: not enough snapshots"},
    )
    app.refresh_performance_tab()
    assert _pump_until(app, lambda: "stubbed" in app.performance_status.get())


def test_guarded_callbacks_latest_wins_on_real_instance(app):
    """On a live instance, only the most recent request for a key renders."""
    rendered: list = []
    ok_old, _ = app._guarded_callbacks("perf", lambda r: rendered.append(("old", r)), None)
    ok_new, _ = app._guarded_callbacks("perf", lambda r: rendered.append(("new", r)), None)
    ok_old("stale")
    ok_new("fresh")
    assert rendered == [("new", "fresh")]


def test_refresh_button_disables_during_load_and_reenables_after(app, monkeypatch):
    """The busy-state guard must always return the button to 'normal' — a
    stuck-disabled Refresh button would be a real regression."""
    import src.desktop.app as desktop_mod

    monkeypatch.setattr(
        desktop_mod,
        "portfolio_performance_summary",
        lambda **_kw: {"ready": False, "reason": "stubbed"},
    )
    button = app._refresh_buttons.get("performance")
    assert button is not None
    app.refresh_performance_tab()
    # Disabled synchronously as the request starts.
    assert str(button.cget("state")) == "disabled"
    # Re-enabled once the async render completes.
    assert _pump_until(app, lambda: "stubbed" in app.performance_status.get())
    assert str(button.cget("state")) == "normal"


def test_on_close_cancels_after_loops(app, monkeypatch):
    """Closing cancels the repeating after() loops so they can't fire against a
    destroyed window."""
    assert app._drain_id is not None  # drain loop is scheduled at construction
    app._on_close()
    assert app._closing is True
    assert app._drain_id is None
