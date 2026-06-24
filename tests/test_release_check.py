from pathlib import Path

from src.release_check import build_release_check
from src.version import APP_VERSION


def test_release_check_static_scripts_are_ready():
    payload = build_release_check()

    assert payload["ok"] is True
    assert payload["tag"].startswith("v")
    assert all(row["ok"] for row in payload["static_checks"])
    assert payload["dist_checked"] is False


def test_release_check_validates_required_assets(tmp_path):
    for name in [
        "tech_stock.dmg",
        "tech_stock-windows.zip",
        "tech_stock_setup.exe",
        "SHA256SUMS.txt",
    ]:
        (tmp_path / name).write_text("x", encoding="utf-8")
    (tmp_path / f"tech_stock-{APP_VERSION}-linux-x86_64.tar.gz").write_text("x", encoding="utf-8")

    payload = build_release_check(dist_dir=tmp_path)

    assert payload["ok"] is True
    required = [row for row in payload["assets"] if row["required"]]
    assert required
    assert all(row["ok"] for row in required)


def test_release_check_flags_missing_required_asset(tmp_path):
    (tmp_path / "tech_stock.dmg").write_text("x", encoding="utf-8")

    payload = build_release_check(dist_dir=Path(tmp_path))

    assert payload["ok"] is False
    assert any(row["name"] == "Linux tarball" and not row["ok"] for row in payload["assets"])
