"""Deterministic smoke checks for packaged tech_stock artifacts.

The packaged app entrypoint is a GUI launcher, so CI should not try to open it.
These checks verify the artifact shape, version metadata, and bundled source
modules that the launcher needs at runtime.
"""

from __future__ import annotations

import argparse
import plistlib
import re
from pathlib import Path

REQUIRED_BUNDLED_FILES = [
    "src/setup_readiness.py",
    "src/ui_support.py",
    "src/desktop/app.py",
    "ui/streamlit_app.py",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-check packaged tech_stock artifacts.")
    parser.add_argument("--platform", choices=["source", "macos", "windows", "linux"], required=True)
    parser.add_argument("--dist", type=Path, default=Path("dist"), help="Distribution root or source checkout for --platform source.")
    parser.add_argument("--expected-version", help="Expected app version. Defaults to src/version.py when available.")
    args = parser.parse_args(argv)

    dist = args.dist.resolve()
    expected_version = args.expected_version or _read_version(Path.cwd()) or _read_version(dist)
    checks = {
        "source": _check_source,
        "macos": _check_macos,
        "windows": _check_windows,
        "linux": _check_linux,
    }
    checks[args.platform](dist, expected_version)
    print(f"package smoke passed: platform={args.platform} version={expected_version or 'unknown'} dist={dist}")
    return 0


def _check_source(root: Path, expected_version: str | None) -> None:
    _require(root.exists(), f"source root not found: {root}")
    for rel in ["src/main.py", "src/app_gui.py", "src/version.py", "tech_stock.spec", *REQUIRED_BUNDLED_FILES]:
        _require((root / rel).exists(), f"missing source file: {rel}")
    version = _read_version(root)
    _require(version, "src/version.py does not define APP_VERSION")
    if expected_version:
        _require(version == expected_version, f"source version mismatch: expected {expected_version}, got {version}")


def _check_macos(dist: Path, expected_version: str | None) -> None:
    app = dist / "tech_stock.app"
    _require(app.exists(), f"macOS app bundle not found: {app}")
    info = app / "Contents" / "Info.plist"
    exe = app / "Contents" / "MacOS" / "tech_stock"
    _require(info.exists(), "macOS Info.plist missing")
    _require(exe.exists(), "macOS executable missing")
    _require(exe.stat().st_size > 0, "macOS executable is empty")
    with info.open("rb") as fh:
        plist = plistlib.load(fh)
    bundle_version = plist.get("CFBundleShortVersionString")
    if expected_version:
        _require(bundle_version == expected_version, f"macOS bundle version mismatch: expected {expected_version}, got {bundle_version}")
    _require_bundled_files(app)


def _check_windows(dist: Path, expected_version: str | None) -> None:
    app_dir = dist / "tech_stock"
    exe_candidates = [app_dir / "tech_stock.exe", dist / "tech_stock.exe"]
    exe = next((path for path in exe_candidates if path.exists()), None)
    _require(exe is not None, f"Windows executable not found in {dist}")
    _require(exe.stat().st_size > 0, "Windows executable is empty")
    if expected_version:
        version_files = list(app_dir.rglob("version.py")) if app_dir.exists() else list(dist.rglob("version.py"))
        version = _parse_version(version_files[0]) if version_files else None
        _require(version == expected_version, f"Windows bundled version mismatch: expected {expected_version}, got {version}")
    _require_bundled_files(app_dir if app_dir.exists() else dist)


def _check_linux(dist: Path, expected_version: str | None) -> None:
    app_dir = dist / "tech_stock"
    appimages = list(dist.glob("tech_stock-*.AppImage")) + list(dist.glob("tech_stock-x86_64.AppImage"))
    tarballs = list(dist.glob("tech_stock-*-linux-x86_64.tar.gz"))
    _require(app_dir.exists() or appimages or tarballs, f"No Linux app directory, AppImage, or tarball found in {dist}")
    if app_dir.exists():
        exe = app_dir / "tech_stock"
        _require(exe.exists(), "Linux executable missing from dist/tech_stock")
        _require(exe.stat().st_size > 0, "Linux executable is empty")
        if expected_version:
            version_file = next(app_dir.rglob("version.py"), None)
            version = _parse_version(version_file) if version_file else None
            _require(version == expected_version, f"Linux bundled version mismatch: expected {expected_version}, got {version}")
        _require_bundled_files(app_dir)
    for artifact in [*appimages, *tarballs]:
        _require(artifact.stat().st_size > 0, f"Linux artifact is empty: {artifact}")


def _require_bundled_files(root: Path) -> None:
    existing = {str(path.relative_to(root)) for path in root.rglob("*.py") if "src" in path.parts or "ui" in path.parts}
    normalized = {rel.replace("\\", "/") for rel in existing}
    for rel in REQUIRED_BUNDLED_FILES:
        if rel not in normalized:
            suffix = rel.split("/", 1)[1]
            _require(any(item.endswith(suffix) for item in normalized), f"bundled file missing: {rel}")


def _read_version(root: Path) -> str | None:
    return _parse_version(root / "src" / "version.py")


def _parse_version(path: Path | None) -> str | None:
    if not path or not path.exists():
        return None
    match = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', path.read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1) if match else None


def _require(condition: object, message: str) -> None:
    if not condition:
        raise SystemExit(message)


if __name__ == "__main__":
    raise SystemExit(main())
