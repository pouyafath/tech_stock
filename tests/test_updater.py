from pathlib import Path
from io import BytesIO

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
            {"name": "SHA256SUMS.txt", "browser_download_url": "https://example.test/SHA256SUMS.txt"},
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
    assert info.checksum_url == "https://example.test/SHA256SUMS.txt"


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


def test_verify_asset_checksum_passes_when_release_checksum_matches(tmp_path, monkeypatch):
    asset = tmp_path / "tech_stock.dmg"
    asset.write_bytes(b"asset")
    digest = updater.hashlib.sha256(b"asset").hexdigest()
    info = updater.UpdateInfo(
        current_version="1.0.0",
        asset_name="tech_stock.dmg",
        checksum_url="https://example.test/SHA256SUMS.txt",
    )

    class Response(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        updater.urllib.request,
        "urlopen",
        lambda request, timeout=30.0, context=None: Response(f"{digest}  tech_stock.dmg\n".encode()),
    )

    assert updater.verify_asset_checksum(asset, info) is True


def test_verify_asset_checksum_raises_on_mismatch(tmp_path, monkeypatch):
    asset = tmp_path / "tech_stock.dmg"
    asset.write_bytes(b"asset")
    info = updater.UpdateInfo(
        current_version="1.0.0",
        asset_name="tech_stock.dmg",
        checksum_url="https://example.test/SHA256SUMS.txt",
    )

    class Response(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        updater.urllib.request,
        "urlopen",
        lambda request, timeout=30.0, context=None: Response(b"deadbeef  tech_stock.dmg\n"),
    )

    try:
        updater.verify_asset_checksum(asset, info)
    except RuntimeError as exc:
        assert "Checksum verification failed" in str(exc)
    else:
        raise AssertionError("Expected checksum mismatch to raise")


def test_apply_update_reports_checksum_result(tmp_path, monkeypatch):
    asset = tmp_path / "tech_stock.dmg"
    asset.write_bytes(b"asset")
    opened = []
    info = updater.UpdateInfo(
        current_version="1.0.0",
        latest_version="9.9.9",
        available=True,
        asset_name="tech_stock.dmg",
        asset_url="https://example.test/tech_stock.dmg",
        checksum_url="https://example.test/SHA256SUMS.txt",
    )

    monkeypatch.setattr(updater, "is_source_checkout", lambda: False)
    monkeypatch.setattr(updater, "download_asset", lambda update_info: asset)
    monkeypatch.setattr(updater, "verify_asset_checksum", lambda path, update_info: True)
    monkeypatch.setattr(updater.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(updater.subprocess, "Popen", lambda args, **kwargs: opened.append(args))

    result = updater.apply_update(info, restart=False)

    assert result.ok is True
    assert result.checksum_verified is True
    assert result.downloaded_path == asset
    assert opened == [["open", str(asset)]]
