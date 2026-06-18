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
DESKTOP_IMPL = ROOT / "src" / "desktop_app.py"


def test_platform_fonts_returns_complete_ladder():
    from src.desktop_app import _platform_fonts

    fonts = _platform_fonts()
    for key in ("title", "heading", "subheading", "body", "small", "mono"):
        assert key in fonts, f"missing font slot: {key}"
        family, size, weight = fonts[key]
        assert isinstance(family, str) and family
        assert isinstance(size, int) and size > 0
        assert weight in {"normal", "bold"}


def test_legacy_desktop_app_has_root():
    import src.desktop_app as legacy

    assert legacy.ROOT == ROOT


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
    next_def = src.index("\n    def ", init_start + 10)
    init_body = src[init_start:next_def]
    assert "self._set_window_icon()" in init_body

    icon_start = src.index("def _set_window_icon(self)")
    icon_next_def = src.index("\n    def ", icon_start + 10)
    icon_body = src[icon_start:icon_next_def]
    assert "icon.png" in icon_body
    assert "iconphoto" in icon_body


def test_reveal_in_finder_surfaces_failures_instead_of_silently_failing():
    """If the OS file-manager command fails, the user must see *something*
    (status bar message) rather than a button click that does nothing."""
    src = DESKTOP_IMPL.read_text(encoding="utf-8")
    fn_start = src.index("def _reveal_in_finder(self")
    fn_next_def = src.index("\n    def ", fn_start + 10)
    fn_body = src[fn_start:fn_next_def]
    assert "except Exception:\n            pass" not in fn_body
    assert "_set_status" in fn_body


def test_coerce_time_field_rejects_bad_spinbox_input():
    """The schedule Spinbox accepts free text; out-of-range / non-numeric
    values must coerce to None (slot skipped) instead of raising ValueError."""
    from src.desktop_app import DesktopApp

    coerce = DesktopApp._coerce_time_field
    # Valid values pass through.
    assert coerce("0", lo=0, hi=23) == 0
    assert coerce("23", lo=0, hi=23) == 23
    assert coerce(" 9 ", lo=0, hi=23) == 9
    assert coerce("59", lo=0, hi=59) == 59
    # Out of range / junk → None, never an exception.
    assert coerce("24", lo=0, hi=23) is None
    assert coerce("-1", lo=0, hi=23) is None
    assert coerce("99", lo=0, hi=59) is None
    assert coerce("abc", lo=0, hi=23) is None
    assert coerce("", lo=0, hi=23) is None
    assert coerce("9.5", lo=0, hi=23) is None


def test_close_handler_stops_after_loops():
    """The window must register a close handler that cancels its repeating
    after() loops so they don't fire against destroyed widgets on quit."""
    src = DESKTOP_IMPL.read_text(encoding="utf-8")
    assert 'self.protocol("WM_DELETE_WINDOW", self._on_close)' in src
    close_start = src.index("def _on_close(self)")
    close_next = src.index("\n    def ", close_start + 10)
    close_body = src[close_start:close_next]
    assert "self._closing = True" in close_body
    assert "after_cancel" in close_body
    assert "self.destroy()" in close_body
    # The repeating loops must bail out when closing.
    drain_start = src.index("def _drain_progress_queue(self)")
    drain_body = src[drain_start : src.index("\n    def ", drain_start + 10)]
    assert "if self._closing:" in drain_body


def test_history_selection_is_bounds_checked():
    src = DESKTOP_IMPL.read_text(encoding="utf-8")
    fn_start = src.index("def _history_selected(self")
    fn_body = src[fn_start : src.index("\n    def ", fn_start + 10)]
    assert "len(self.history_paths)" in fn_body


def test_onboarding_budgets_persist_all_three_fields():
    """The wizard's budget stage must save the spend cap and both trade
    budgets, not just budget_cad."""
    src = DESKTOP_IMPL.read_text(encoding="utf-8")
    # Scope to the _primary() save handler (there is also a "budgets" branch in
    # the UI-building _render method that we must not match instead).
    primary_start = src.index("def _primary(self)")
    primary_body = src[primary_start : src.index("\n    def ", primary_start + 10)]
    budgets_start = primary_body.index('elif self._current == "budgets":')
    budgets_body = primary_body[budgets_start : primary_body.index("elif self._current ==", budgets_start + 10)]
    assert "monthly_budget_usd" in budgets_body
    assert "budget_usd" in budgets_body
    assert "budget_cad" in budgets_body


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
