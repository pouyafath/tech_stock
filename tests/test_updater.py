from io import BytesIO
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
    assert info.asset_available is True
    assert info.checksum_available is True
    assert info.asset_names == ["tech_stock-windows.zip", "SHA256SUMS.txt", "tech_stock.dmg"]


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


def test_apply_update_refuses_install_when_checksum_unverified(tmp_path, monkeypatch):
    """A None checksum result (no SHA256SUMS entry) must NOT auto-install the asset."""
    asset = tmp_path / "tech_stock.dmg"
    asset.write_bytes(b"asset")
    opened = []
    info = updater.UpdateInfo(
        current_version="1.0.0",
        latest_version="9.9.9",
        available=True,
        asset_name="tech_stock.dmg",
        asset_url="https://example.test/tech_stock.dmg",
        checksum_url=None,
    )

    monkeypatch.setattr(updater, "is_source_checkout", lambda: False)
    monkeypatch.setattr(updater, "download_asset", lambda update_info: asset)
    monkeypatch.setattr(updater, "verify_asset_checksum", lambda path, update_info: None)
    monkeypatch.setattr(updater.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(updater.subprocess, "Popen", lambda args, **kwargs: opened.append(args))

    result = updater.apply_update(info, restart=True)

    assert result.ok is False
    assert result.checksum_verified is None
    assert result.error == "checksum not verified"
    # Must only reveal the download (open -R), never mount/execute it.
    assert opened == [["open", "-R", str(asset)]]


# ── Update-check cache (throttling) ─────────────────────────────────────


def _stub_fetch_payload(latest_tag: str = "v9.9.9"):
    return {
        "tag_name": latest_tag,
        "html_url": "https://example.test/release",
        "published_at": "2026-05-24T00:00:00Z",
        "body": "release notes",
        "assets": [
            {"name": "tech_stock.dmg", "browser_download_url": "https://example.test/app.dmg"},
            {"name": "SHA256SUMS.txt", "browser_download_url": "https://example.test/SHA256SUMS.txt"},
        ],
    }


def test_check_for_update_uses_disk_cache_when_fresh(tmp_path, monkeypatch):
    """Second call within TTL must hit the disk cache, not the network."""
    monkeypatch.setattr(updater, "user_workspace", lambda: tmp_path)
    monkeypatch.setattr(updater, "current_platform_asset_name", lambda: "tech_stock.dmg")

    call_counter = {"n": 0}

    def fake_fetch(timeout=6.0):
        call_counter["n"] += 1
        return _stub_fetch_payload()

    monkeypatch.setattr(updater, "fetch_latest_release", fake_fetch)

    first = updater.check_for_update(current_version="1.0.0", use_cache=True)
    second = updater.check_for_update(current_version="1.0.0", use_cache=True)

    assert call_counter["n"] == 1, "second call should have read the disk cache"
    assert first.latest_version == "9.9.9"
    assert second.latest_version == "9.9.9"
    assert first.from_cache is False
    assert second.from_cache is True
    assert second.cache_path == str(tmp_path / "cache" / "update_check.json")
    assert second.cache_age_seconds is not None
    assert (tmp_path / "cache" / "update_check.json").exists()


def test_check_for_update_bypasses_cache_when_force(tmp_path, monkeypatch):
    """force=use_cache=False must always hit the network."""
    monkeypatch.setattr(updater, "user_workspace", lambda: tmp_path)
    monkeypatch.setattr(updater, "current_platform_asset_name", lambda: "tech_stock.dmg")

    call_counter = {"n": 0}

    def fake_fetch(timeout=6.0):
        call_counter["n"] += 1
        return _stub_fetch_payload()

    monkeypatch.setattr(updater, "fetch_latest_release", fake_fetch)

    updater.check_for_update(current_version="1.0.0", use_cache=True)  # populates cache
    updater.check_for_update(current_version="1.0.0", use_cache=False)  # forced refresh
    updater.check_for_update(current_version="1.0.0")  # default = forced

    assert call_counter["n"] == 3


def test_check_for_update_cache_invalidates_when_app_version_changes(tmp_path, monkeypatch):
    """After the user upgrades, the on-disk cache must not pretend an old update is still available."""
    monkeypatch.setattr(updater, "user_workspace", lambda: tmp_path)
    monkeypatch.setattr(updater, "current_platform_asset_name", lambda: "tech_stock.dmg")

    call_counter = {"n": 0}

    def fake_fetch(timeout=6.0):
        call_counter["n"] += 1
        return _stub_fetch_payload()

    monkeypatch.setattr(updater, "fetch_latest_release", fake_fetch)

    # First call populates the cache while APP_VERSION = X
    monkeypatch.setattr(updater, "APP_VERSION", "1.0.0")
    updater.check_for_update(current_version="1.0.0", use_cache=True)

    # User upgrades — APP_VERSION rolls forward. Cache must be invalidated.
    monkeypatch.setattr(updater, "APP_VERSION", "9.9.9")
    updater.check_for_update(current_version="9.9.9", use_cache=True)

    assert call_counter["n"] == 2


def test_check_for_update_does_not_cache_failures(tmp_path, monkeypatch):
    """Errored lookups must never be cached — next call should retry."""
    monkeypatch.setattr(updater, "user_workspace", lambda: tmp_path)

    def bad_fetch(timeout=6.0):
        raise updater.urllib.error.URLError("boom")

    monkeypatch.setattr(updater, "fetch_latest_release", bad_fetch)
    info = updater.check_for_update(current_version="1.0.0")

    assert info.error
    assert not (tmp_path / "cache" / "update_check.json").exists()


def test_check_for_update_cache_expires_after_ttl(tmp_path, monkeypatch):
    """Stale entries beyond cache_ttl_seconds must trigger a network refresh."""
    monkeypatch.setattr(updater, "user_workspace", lambda: tmp_path)
    monkeypatch.setattr(updater, "current_platform_asset_name", lambda: "tech_stock.dmg")

    call_counter = {"n": 0}

    def fake_fetch(timeout=6.0):
        call_counter["n"] += 1
        return _stub_fetch_payload()

    monkeypatch.setattr(updater, "fetch_latest_release", fake_fetch)

    updater.check_for_update(current_version="1.0.0", use_cache=True)
    # ttl=0 forces the cached value to be treated as expired immediately.
    updater.check_for_update(current_version="1.0.0", use_cache=True, cache_ttl_seconds=0)

    assert call_counter["n"] == 2


def test_user_workspace_uses_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("TECH_STOCK_HOME", str(tmp_path))
    result = updater.user_workspace()
    assert result == tmp_path


def test_normalize_version_various():
    assert updater.normalize_version(None) == (0,)
    assert updater.normalize_version("") == (0,)
    assert updater.normalize_version("v1.28.0") == (1, 28, 0)
    assert updater.normalize_version("1.0.0-beta") == (1, 0, 0)


def test_is_source_checkout_returns_bool():
    # Just verify it doesn't crash and returns a bool
    result = updater.is_source_checkout()
    assert isinstance(result, bool)


def test_ssl_context_returns_context():
    import ssl

    ctx = updater.ssl_context()
    assert isinstance(ctx, ssl.SSLContext)


def test_update_dir_and_log_path(monkeypatch, tmp_path):
    monkeypatch.setenv("TECH_STOCK_HOME", str(tmp_path))
    update_dir = updater.update_dir()
    log_path = updater.update_log_path()
    assert update_dir.exists()
    assert log_path.parent.exists()
