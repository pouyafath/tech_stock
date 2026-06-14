from __future__ import annotations

import plistlib
import stat
from pathlib import Path

from tools import package_smoke


def _write_required_tree(root: Path, version: str = "9.9.9") -> None:
    for rel in [
        "src/setup_readiness.py",
        "src/ui_support.py",
        "src/desktop/app.py",
        "ui/streamlit_app.py",
    ]:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# bundled\n", encoding="utf-8")
    version_path = root / "src/version.py"
    version_path.write_text(f'APP_VERSION = "{version}"\n', encoding="utf-8")


def _write_executable(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("binary", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_package_smoke_source(tmp_path):
    _write_required_tree(tmp_path)
    for rel in ["src/main.py", "src/app_gui.py", "tech_stock.spec"]:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# file\n", encoding="utf-8")

    assert package_smoke.main(["--platform", "source", "--dist", str(tmp_path), "--expected-version", "9.9.9"]) == 0


def test_package_smoke_macos(tmp_path):
    app = tmp_path / "tech_stock.app"
    contents = app / "Contents"
    contents.mkdir(parents=True)
    with (contents / "Info.plist").open("wb") as fh:
        plistlib.dump({"CFBundleShortVersionString": "9.9.9"}, fh)
    _write_executable(contents / "MacOS/tech_stock")
    _write_required_tree(contents / "Frameworks", version="9.9.9")

    assert package_smoke.main(["--platform", "macos", "--dist", str(tmp_path), "--expected-version", "9.9.9"]) == 0


def test_package_smoke_windows(tmp_path):
    app_dir = tmp_path / "tech_stock"
    _write_executable(app_dir / "tech_stock.exe")
    _write_required_tree(app_dir / "_internal", version="9.9.9")

    assert package_smoke.main(["--platform", "windows", "--dist", str(tmp_path), "--expected-version", "9.9.9"]) == 0


def test_package_smoke_linux(tmp_path):
    app_dir = tmp_path / "tech_stock"
    _write_executable(app_dir / "tech_stock")
    _write_required_tree(app_dir / "_internal", version="9.9.9")
    (tmp_path / "tech_stock-x86_64.AppImage").write_bytes(b"appimage")

    assert package_smoke.main(["--platform", "linux", "--dist", str(tmp_path), "--expected-version", "9.9.9"]) == 0
