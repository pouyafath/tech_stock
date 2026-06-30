"""Static checks on v1.19 installer artefacts.

We can't run the actual installers in CI (Inno Setup is Windows-only,
appimagetool is Linux-only), so these tests verify the *content* of the
scripts: required directives, version-injection plumbing, registry keys
for the Windows CSV file association, etc.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


# ── Windows: installer_windows.iss ─────────────────────────────────────────


def test_iss_defines_appname_and_publisher():
    iss = (ROOT / "installer_windows.iss").read_text(encoding="utf-8")
    assert "#define AppName" in iss
    assert "#define AppPublisher" in iss


def test_iss_references_app_version_macro():
    """v1.19: the hard-coded AppVersion=1.0.0 should be gone; the file must
    consume #ifndef AppVersion / #define AppVersion injected by the .bat."""
    iss = (ROOT / "installer_windows.iss").read_text(encoding="utf-8")
    assert "AppVersion={#AppVersion}" in iss
    assert "#ifndef AppVersion" in iss


def test_iss_registers_csv_file_association():
    iss = (ROOT / "installer_windows.iss").read_text(encoding="utf-8")
    # ProgId entry + OpenWithProgids hint
    assert "tech_stock.holdings_csv" in iss
    assert "OpenWithProgids" in iss
    assert ".csv" in iss
    # Open-command line that passes %1 to the EXE
    assert "--import-csv" in iss


def test_iss_creates_start_menu_group_and_optional_desktop_shortcut():
    iss = (ROOT / "installer_windows.iss").read_text(encoding="utf-8")
    assert "[Icons]" in iss
    assert "{group}\\{#AppName}" in iss
    assert "Tasks: desktopicon" in iss


def test_iss_offers_demo_mode_shortcut():
    iss = (ROOT / "installer_windows.iss").read_text(encoding="utf-8")
    assert "(Demo mode)" in iss
    assert "--demo" in iss


def test_iss_ships_samples_component():
    iss = (ROOT / "installer_windows.iss").read_text(encoding="utf-8")
    assert "[Components]" in iss
    assert "samples" in iss
    assert "data\\samples\\*" in iss


def test_iss_is_per_user_by_default():
    iss = (ROOT / "installer_windows.iss").read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in iss


# ── Windows: build_windows.bat ─────────────────────────────────────────────


def test_build_bat_parses_version_from_version_py():
    bat = (ROOT / "build_windows.bat").read_text(encoding="utf-8")
    # The .bat should read src\version.py and pass /D AppVersion=… to iscc
    assert "src\\version.py" in bat
    assert "/DAppVersion" in bat


def test_build_bat_has_signing_hook():
    bat = (ROOT / "build_windows.bat").read_text(encoding="utf-8")
    assert "SIGN_PFX_PATH" in bat
    assert "signtool" in bat


# ── Linux: build_linux.sh ──────────────────────────────────────────────────


def test_build_linux_script_exists_and_is_executable():
    if sys.platform == "win32":
        pytest.skip("POSIX executable bits are not preserved in Windows checkouts")
    path = ROOT / "build_linux.sh"
    assert path.exists()
    assert (path.stat().st_mode & 0o111) != 0, "build_linux.sh should be executable"


def test_build_linux_script_reads_version_py():
    body = (ROOT / "build_linux.sh").read_text(encoding="utf-8")
    assert "src/version.py" in body
    assert "APP_VERSION" in body


def test_build_linux_script_emits_appimage_and_required_tarball():
    body = (ROOT / "build_linux.sh").read_text(encoding="utf-8")
    # AppImage path
    assert "appimagetool" in body
    assert ".AppImage" in body
    # Tarball is a required output, not only an appimagetool fallback.
    assert "Packaging Linux tarball" in body
    assert "tar -C" in body
    assert ".tar.gz" in body
    assert "packaging tarball instead" not in body


def test_build_linux_script_emits_desktop_entry():
    body = (ROOT / "build_linux.sh").read_text(encoding="utf-8")
    assert "[Desktop Entry]" in body
    assert "Categories=Finance" in body


def test_release_workflow_requires_linux_tarball_upload():
    workflow = (ROOT / ".github" / "workflows" / "build_release.yml").read_text(encoding="utf-8")
    assert "name: tech_stock-linux-tarball" in workflow
    assert "dist/tech_stock-*-linux-x86_64.tar.gz" in workflow
    assert "if-no-files-found: error" in workflow
    assert "python src/main.py release-check --dist release --strict" in workflow


def test_macos_spec_appversion_still_injected():
    """Regression: the macOS bundle has always read APP_VERSION; make sure
    that's still the case after the Windows-side parity work didn't break it."""
    spec = (ROOT / "tech_stock.spec").read_text(encoding="utf-8")
    assert "APP_VERSION" in spec
    assert "CFBundleShortVersionString" in spec
