"""Headless tests for the macOS-focused desktop_app polish.

We cannot spin up a real Tk window in CI (no display), so these tests focus
on the *importable* helpers that don't require a root window:

* ``_platform_fonts`` returns a sensible font ladder per OS
* The shared ``PALETTE`` is wired through (not the hard-coded hex values)
* Module-level macOS / modifier-key constants are consistent
* The PyInstaller spec carries the new macOS Info.plist keys

These tests intentionally do **not** instantiate ``DesktopApp`` — that
needs a live X server / Quartz session. The actual GUI is exercised
manually via ``./run.sh`` and ``./build_macos.sh``.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

tkinter = pytest.importorskip("tkinter")

ROOT = Path(__file__).resolve().parents[1]
DESKTOP_IMPL = ROOT / "src" / "desktop" / "app.py"


def test_platform_fonts_returns_complete_ladder():
    from src.desktop_app import _platform_fonts

    fonts = _platform_fonts()
    for key in ("title", "heading", "subheading", "body", "small", "mono"):
        assert key in fonts, f"missing font slot: {key}"
        family, size, weight = fonts[key]
        assert isinstance(family, str) and family
        assert isinstance(size, int) and size > 0
        assert weight in {"normal", "bold"}


def test_legacy_desktop_app_module_aliases_new_package():
    import src.desktop.app as desktop_impl
    import src.desktop_app as legacy

    assert legacy is desktop_impl
    assert desktop_impl.ROOT == ROOT


def test_platform_fonts_picks_sf_pro_on_macos(monkeypatch):
    """On macOS the ladder should use the SF Pro family — best system match."""
    import src.desktop_app as dapp

    monkeypatch.setattr(dapp, "IS_MACOS", True)
    fonts = dapp._platform_fonts()
    assert "SF Pro" in fonts["title"][0]
    assert "SF Pro" in fonts["body"][0]
    assert "SF Mono" in fonts["mono"][0]


def test_palette_is_shared_with_ui_theme():
    """desktop_app must read the same PALETTE that Streamlit + Textual use."""
    from src.desktop_app import PALETTE as desktop_palette
    from src.ui_theme import PALETTE as theme_palette

    # In the non-fallback path they're the same object
    assert desktop_palette.accent == theme_palette.accent
    assert desktop_palette.danger == theme_palette.danger
    assert desktop_palette.bg == theme_palette.bg


def test_mod_key_matches_platform():
    """Cmd on macOS, Ctrl elsewhere — the menu accelerators rely on this."""
    from src.desktop_app import IS_MACOS, MOD_KEY

    if IS_MACOS:
        assert MOD_KEY == "Command"
    else:
        assert MOD_KEY == "Control"


def test_desktop_app_no_longer_hardcodes_hex():
    """The constructor should reference PALETTE attributes, not literal hex."""
    src = DESKTOP_IMPL.read_text(encoding="utf-8")
    tree = ast.parse(src)
    in_init = False
    hex_assignments: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "__init__":
            in_init = True
            for child in ast.walk(node):
                if isinstance(child, ast.Assign) and isinstance(child.value, ast.Constant):
                    val = child.value.value
                    if isinstance(val, str) and val.startswith("#") and len(val) in (4, 7, 9):
                        for target in child.targets:
                            if isinstance(target, ast.Attribute) and target.attr in {
                                "bg",
                                "panel",
                                "text",
                                "muted",
                                "accent",
                                "danger",
                                "warning",
                                "good",
                                "card",
                            }:
                                hex_assignments.append(f"self.{target.attr} = {val!r}")
            break
    assert in_init, "DesktopApp.__init__ not found"
    assert not hex_assignments, "Found hard-coded hex assignments in DesktopApp.__init__; use PALETTE tokens instead:\n  " + "\n  ".join(
        hex_assignments
    )


def test_macos_spec_includes_required_info_plist_keys():
    """The .app bundle must expose the macOS-required Info.plist keys."""
    spec = (ROOT / "tech_stock.spec").read_text(encoding="utf-8")
    required = [
        "CFBundleShortVersionString",
        "CFBundleVersion",
        "CFBundleDisplayName",
        "CFBundleIdentifier",
        "NSHighResolutionCapable",
        "NSRequiresAquaSystemAppearance",
        "LSApplicationCategoryType",
        "LSMinimumSystemVersion",
        "NSAppleEventsUsageDescription",
        "NSDownloadsFolderUsageDescription",
        "CFBundleDocumentTypes",
    ]
    missing = [key for key in required if key not in spec]
    assert not missing, f"tech_stock.spec is missing Info.plist keys: {missing}"


def test_spec_csv_file_association_is_complete():
    """Double-clicking a CSV should at least be advertised as an open hint."""
    spec = (ROOT / "tech_stock.spec").read_text(encoding="utf-8")
    assert '"CFBundleTypeExtensions": ["csv"]' in spec
    assert "public.comma-separated-values-text" in spec


def test_menu_factory_is_defined():
    """The menu bar setup must exist on the class (without instantiating Tk)."""
    src = DESKTOP_IMPL.read_text(encoding="utf-8")
    assert "def _build_menu(self)" in src
    assert "tk::mac::ShowPreferences" in src
    assert "tk::mac::Quit" in src
    # The accelerators are bound through ``bind_all(f"<{MOD_KEY}-X>", ...)``
    # so check the f-string accelerator suffixes that drive them.
    for accel_suffix in ("-r>", "-comma>", "-n>", "-l>", "-f>"):
        assert f"<{{MOD_KEY}}{accel_suffix}" in src, f"missing bind_all for accelerator suffix: {accel_suffix}"


def test_post_paint_warmup_is_used_in_init():
    """Heavy startup work should be deferred to _post_paint_warmup."""
    src = DESKTOP_IMPL.read_text(encoding="utf-8")
    init_start = src.index("def __init__(self)")
    next_def = src.index("\n    def ", init_start + 10)
    init_body = src[init_start:next_def]
    # The constructor should NOT directly call refresh_dashboard / refresh_history /
    # start_buy_signal_refresh anymore — they're moved into the warm-up handler.
    assert "self.refresh_dashboard()" not in init_body, "refresh_dashboard should be deferred to _post_paint_warmup"
    assert "self.start_buy_signal_refresh" not in init_body
    assert "self.after_idle(self._post_paint_warmup)" in init_body


def test_about_handler_reads_dynamic_version():
    """The About dialog must use the live APP_VERSION, not a hard-coded string."""
    src = DESKTOP_IMPL.read_text(encoding="utf-8")
    # The dialog title and body should both interpolate current_app_version().
    assert "current_app_version()" in src
    assert "About tech_stock" in src


def test_window_icon_is_set_on_init():
    """A plain `python src/desktop_app.py` run must not fall back to Tk's
    generic feather icon — the packaged app icon should be applied."""
    src = DESKTOP_IMPL.read_text(encoding="utf-8")
    init_start = src.index("def __init__(self)")
    init_body = src[init_start : src.index("\n    def ", init_start + 10)]
    assert "self._set_window_icon()" in init_body

    icon_start = src.index("def _set_window_icon(self)")
    icon_body = src[icon_start : src.index("\n    def ", icon_start + 10)]
    assert "icon.png" in icon_body
    assert "iconphoto" in icon_body
    # src/desktop/app.py is two levels under the repo root.
    assert "parents[2]" in icon_body


def test_reveal_in_finder_surfaces_failures_instead_of_silently_failing():
    src = DESKTOP_IMPL.read_text(encoding="utf-8")
    fn_start = src.index("def _reveal_in_finder(self")
    fn_body = src[fn_start : src.index("\n    def ", fn_start + 10)]
    assert "except Exception:\n            pass" not in fn_body
    assert "_set_status" in fn_body


def test_coerce_time_field_rejects_bad_spinbox_input():
    """Out-of-range / non-numeric schedule Spinbox values coerce to None
    (slot skipped) instead of raising ValueError on Install/Preview."""
    from src.desktop_app import DesktopApp

    coerce = DesktopApp._coerce_time_field
    assert coerce("0", lo=0, hi=23) == 0
    assert coerce("23", lo=0, hi=23) == 23
    assert coerce(" 9 ", lo=0, hi=23) == 9
    assert coerce("59", lo=0, hi=59) == 59
    assert coerce("24", lo=0, hi=23) is None
    assert coerce("-1", lo=0, hi=23) is None
    assert coerce("abc", lo=0, hi=23) is None
    assert coerce("", lo=0, hi=23) is None
    assert coerce("9.5", lo=0, hi=23) is None


def test_close_handler_stops_after_loops():
    """The window must register a close handler that cancels its repeating
    after() loops so they don't fire against destroyed widgets on quit."""
    src = DESKTOP_IMPL.read_text(encoding="utf-8")
    assert 'self.protocol("WM_DELETE_WINDOW", self._on_close)' in src
    close_start = src.index("def _on_close(self)")
    close_body = src[close_start : src.index("\n    def ", close_start + 10)]
    assert "self._closing = True" in close_body
    assert "after_cancel" in close_body
    assert "self.destroy()" in close_body
    drain_start = src.index("def _drain_progress_queue(self)")
    drain_body = src[drain_start : src.index("\n    def ", drain_start + 10)]
    assert "if self._closing:" in drain_body


def test_history_selection_is_bounds_checked():
    src = DESKTOP_IMPL.read_text(encoding="utf-8")
    fn_start = src.index("def _history_selected(self")
    fn_body = src[fn_start : src.index("\n    def ", fn_start + 10)]
    assert "len(self.history_paths)" in fn_body


def test_preferences_reject_invalid_numbers():
    """Saving Preferences with a non-numeric field must not claim success."""
    src = DESKTOP_IMPL.read_text(encoding="utf-8")
    fn_start = src.index("def _save_preferences(self")
    fn_body = src[fn_start : src.index("\n    def ", fn_start + 10)]
    assert "must be numbers" in fn_body


def test_onboarding_budgets_persist_all_three_fields():
    """The wizard's budget stage saves the spend cap and both trade budgets."""
    src = DESKTOP_IMPL.read_text(encoding="utf-8")
    primary_start = src.index("def _primary(self)")
    primary_body = src[primary_start : src.index("\n    def ", primary_start + 10)]
    budgets_start = primary_body.index('elif self._current == "budgets":')
    budgets_body = primary_body[budgets_start : primary_body.index("elif self._current ==", budgets_start + 10)]
    assert "monthly_budget_usd" in budgets_body
    assert "budget_usd" in budgets_body
    assert "budget_cad" in budgets_body


def test_settings_paths_resolve_to_repo_root_config():
    """src/desktop/app.py is two levels deep, so config paths must use the
    module ROOT (repo-root/config), not parents[1] (which is src/config)."""
    src = DESKTOP_IMPL.read_text(encoding="utf-8")
    assert 'parents[1] / "config"' not in src


def test_scrollable_frames_support_mousewheel():
    """Both scrollable panes must react to the wheel/trackpad — dragging the
    scrollbar by hand is not an acceptable production UX."""
    src = DESKTOP_IMPL.read_text(encoding="utf-8")
    sf_start = src.index("def _scrollable_frame(self")
    sf_body = src[sf_start : src.index("\n    @staticmethod", sf_start)]
    assert "self._bind_mousewheel(canvas, content)" in sf_body

    bind_start = src.index("def _bind_mousewheel(self")
    bind_body = src[bind_start : src.index("\n    def ", bind_start + 10)]
    # All three platform wheel events must be wired.
    for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        assert seq in bind_body, f"missing wheel binding for {seq}"
    # Crossing onto a child widget must not tear the binding down.
    assert "NotifyInferior" in bind_body


def test_wheel_scroll_steps_handles_every_platform():
    """Linux (Button-4/5), Windows (±120 deltas), macOS (small deltas)."""
    from src.desktop_app import DesktopApp

    steps = DesktopApp._wheel_scroll_steps
    # Linux buttons
    assert steps(0, 4) == -1
    assert steps(0, 5) == 1
    # Windows multiples of 120 (positive delta = scroll up = negative units)
    assert steps(120, None) == -1
    assert steps(-120, None) == 1
    assert steps(240, None) == -2
    # macOS small deltas
    assert steps(1, None) == -1
    assert steps(-3, None) == 1
    # No movement
    assert steps(0, None) == 0


def test_tree_rows_are_zebra_striped():
    """Data tables alternate row backgrounds; the stripe tags are background-
    only so they stack with the semantic foreground tags (BUY/SELL/etc.)."""
    src = DESKTOP_IMPL.read_text(encoding="utf-8")

    make_start = src.index("def _make_tree(self")
    make_body = src[make_start : src.index("\n    def ", make_start + 10)]
    assert 'tree.tag_configure("oddrow"' in make_body
    assert 'tree.tag_configure("evenrow"' in make_body

    fill_start = src.index("def _replace_tree_rows(self")
    fill_body = src[fill_start : src.index("\n    def ", fill_start + 10)]
    assert '"evenrow" if offset % 2 else "oddrow"' in fill_body


def test_sanitize_window_size_clamps_to_screen():
    """A restored size must fit on the current screen and respect the minimum."""
    from src.desktop_app import DesktopApp

    clamp = DesktopApp._sanitize_window_size
    # Normal case passes through.
    assert clamp("1400x900", 1920, 1080) == "1400x900"
    # Too big for the screen → clamped down to the screen.
    assert clamp("4000x3000", 1920, 1080) == "1920x1080"
    # Below the minimum → bumped up to the floor.
    assert clamp("400x300", 1920, 1080) == "1024x720"
    # Junk / missing → None so the default geometry is kept.
    assert clamp("not-a-size", 1920, 1080) is None
    assert clamp(None, 1920, 1080) is None


def test_window_size_is_persisted_on_close_and_restored_on_init():
    src = DESKTOP_IMPL.read_text(encoding="utf-8")
    # Restore is attempted during construction.
    init_start = src.index("def __init__(self)")
    init_body = src[init_start : src.index("\n    def ", init_start + 10)]
    assert "self._restore_window_size()" in init_body
    # And the current size is saved before the window is torn down.
    close_start = src.index("def _on_close(self)")
    close_body = src[close_start : src.index("\n    def ", close_start + 10)]
    assert "self._save_window_size()" in close_body


def test_heavy_refresh_handlers_run_off_the_ui_thread():
    """The Performance / Learning / Outcomes / Diagnostics tabs do network and
    disk I/O. Each must hand the slow call to a worker and render from the
    result, never blocking the Tk event loop (which freezes the window)."""
    src = DESKTOP_IMPL.read_text(encoding="utf-8")
    specs = [
        ("refresh_performance_tab", "_render_performance_view", "portfolio_performance_summary"),
        ("refresh_learning_tab", "_render_learning_view", "learning_view"),
        ("refresh_outcomes_tab", "_render_outcomes_view", "outcomes_view"),
        ("refresh_diagnostics_tab", "_render_diagnostics_view", "diagnostics_view"),
    ]
    for refresh, render, slow_symbol in specs:
        r_start = src.index(f"def {refresh}(self")
        r_body = src[r_start : src.index("\n    def ", r_start + 10)]
        assert "self._run_in_background(" in r_body, f"{refresh} must offload to a worker thread"
        assert "self._latest_only(" in r_body, f"{refresh} must guard against stale renders"
        assert render in r_body, f"{refresh} must hand off to {render}"
        assert slow_symbol in r_body, f"the slow call should be wired into {refresh}'s worker"
        # The expensive widget population (tree fills) must live in the render
        # half, not the front — proving the work really moved off the UI thread.
        assert "_replace_tree_rows(" not in r_body, f"{refresh} should not render tables synchronously"
        assert f"def {render}(self" in src, f"{render} should exist"
        rd_start = src.index(f"def {render}(self")
        rd_body = src[rd_start : src.index("\n    def ", rd_start + 10)]
        assert "_replace_tree_rows(" in rd_body, f"{render} should populate the tables"


def test_background_helper_marshals_results_through_the_queue():
    """Worker threads must never touch Tk directly — results come back through
    the single progress queue the drain loop already pumps on the UI thread."""
    src = DESKTOP_IMPL.read_text(encoding="utf-8")
    helper = src[src.index("def _run_in_background(self") : src.index("def _handle_async_error(self")]
    assert "threading.Thread(" in helper and "daemon=True" in helper
    assert 'self.progress_queue.put(("callback"' in helper

    drain = src[src.index("def _drain_progress_queue(self") : src.index("def _run_in_background(self")]
    assert 'kind == "callback"' in drain
    assert "payload()" in drain


def test_drain_loop_is_resilient_to_handler_errors():
    """A single failing progress handler must not kill the drain loop — the
    reschedule lives in a finally and each item is dispatched under a guard, so
    report-run completion and background refreshes keep pumping."""
    src = DESKTOP_IMPL.read_text(encoding="utf-8")
    drain = src[src.index("def _drain_progress_queue(self") : src.index("def _run_in_background(self")]
    assert "finally:" in drain
    assert "logger.exception" in drain
    # The reschedule must sit inside the finally (after the dispatch loop) so it
    # still runs when a handler raised.
    assert drain.index("finally:") < drain.index("self._drain_id = self.after(100")


def test_latest_only_drops_stale_renders():
    """A slow result that finishes after a newer refresh was requested must be
    discarded, so the tab always shows the most recently requested data."""
    from types import SimpleNamespace

    from src.desktop_app import DesktopApp

    host = SimpleNamespace(_async_generation={})
    applied: list = []

    guard_old = DesktopApp._latest_only(host, "perf", lambda r: applied.append(("old", r)))
    guard_new = DesktopApp._latest_only(host, "perf", lambda r: applied.append(("new", r)))

    # The stale (older) worker finishes last — it must be dropped.
    guard_old("stale")
    # The newest worker renders.
    guard_new("fresh")
    assert applied == [("new", "fresh")]

    # A different key tracks its own generation independently.
    guard_other = DesktopApp._latest_only(host, "diagnostics", lambda r: applied.append(("other", r)))
    guard_other("ok")
    assert ("other", "ok") in applied


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
