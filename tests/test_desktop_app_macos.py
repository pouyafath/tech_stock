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


def test_platform_fonts_returns_complete_ladder():
    from src.desktop_app import _platform_fonts

    fonts = _platform_fonts()
    for key in ("title", "heading", "subheading", "body", "small", "mono"):
        assert key in fonts, f"missing font slot: {key}"
        family, size, weight = fonts[key]
        assert isinstance(family, str) and family
        assert isinstance(size, int) and size > 0
        assert weight in {"normal", "bold"}


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
    src = (ROOT / "src" / "desktop_app.py").read_text(encoding="utf-8")
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
    src = (ROOT / "src" / "desktop_app.py").read_text(encoding="utf-8")
    assert "def _build_menu(self)" in src
    assert "tk::mac::ShowPreferences" in src
    assert "tk::mac::Quit" in src
    # The accelerators are bound through ``bind_all(f"<{MOD_KEY}-X>", ...)``
    # so check the f-string accelerator suffixes that drive them.
    for accel_suffix in ("-r>", "-comma>", "-n>", "-l>", "-f>"):
        assert f"<{{MOD_KEY}}{accel_suffix}" in src, f"missing bind_all for accelerator suffix: {accel_suffix}"


def test_post_paint_warmup_is_used_in_init():
    """Heavy startup work should be deferred to _post_paint_warmup."""
    src = (ROOT / "src" / "desktop_app.py").read_text(encoding="utf-8")
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
    src = (ROOT / "src" / "desktop_app.py").read_text(encoding="utf-8")
    # The dialog title and body should both interpolate current_app_version().
    assert "current_app_version()" in src
    assert "About tech_stock" in src


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
