from pathlib import Path

from src import updater


def test_is_newer_version_handles_v_prefix_and_padding():
    assert updater.is_newer_version("v1.13.0", "1.12.3") is True
    assert updater.is_newer_version("v1.13", "1.13.0") is False
    assert updater.is_newer_version("1.12.3", "1.13.0") is False


def test_current_platform_asset_name(monkeypatch):
    monkeypatch.setattr(updater.platform, "system", lambda: "Darwin")
    assert updater.current_platform_asset_name() == "tech_stock.dmg"

    monkeypatch.setattr(updater.platform, "system", lambda: "Windows")
    assert updater.current_platform_asset_name() == "tech_stock-windows.zip"

    monkeypatch.setattr(updater.platform, "system", lambda: "Linux")
    assert updater.current_platform_asset_name() is None


def test_check_for_update_selects_platform_asset(monkeypatch):
    payload = {
        "tag_name": "v9.9.9",
        "html_url": "https://example.test/release",
        "published_at": "2026-05-16T00:00:00Z",
        "body": "release notes",
        "assets": [
            {"name": "tech_stock-windows.zip", "browser_download_url": "https://example.test/windows.zip"},
            {"name": "tech_stock.dmg", "browser_download_url": "https://example.test/app.dmg"},
        ],
    }
    monkeypatch.setattr(updater, "fetch_latest_release", lambda timeout=6.0: payload)
    monkeypatch.setattr(updater, "current_platform_asset_name", lambda: "tech_stock.dmg")

    info = updater.check_for_update(current_version="1.0.0")

    assert info.available is True
    assert info.latest_version == "9.9.9"
    assert info.asset_name == "tech_stock.dmg"
    assert info.asset_url == "https://example.test/app.dmg"


def test_apply_update_preserves_workspace_for_no_update(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "user_workspace", lambda: tmp_path)
    info = updater.UpdateInfo(current_version="1.13.1", latest_version="1.13.1", available=False)

    result = updater.apply_update(info)

    assert result.ok is True
    assert result.downloaded_path is None
    assert result.log_path == tmp_path / "logs" / "update.log"


def test_check_for_update_explains_certificate_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "update_log_path", lambda: tmp_path / "update.log")

    def fail_fetch(timeout=6.0):
        raise updater.urllib.error.URLError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")

    monkeypatch.setattr(updater, "fetch_latest_release", fail_fetch)

    info = updater.check_for_update(current_version="1.13.1")

    assert info.available is False
    assert "Could not verify GitHub's HTTPS certificate" in str(info.error)
    assert "CERTIFICATE_VERIFY_FAILED" in str(info.error)
