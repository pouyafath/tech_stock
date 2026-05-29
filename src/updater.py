"""GitHub release updater shared by CLI and optional UIs."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import ssl
import urllib.error
import urllib.request
import zipfile
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.version import APP_VERSION

REPO_OWNER = "pouyafath"
REPO_NAME = "tech_stock"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/releases"


def _certificate_error_message(exc: Exception) -> str:
    return (
        "Could not verify GitHub's HTTPS certificate while checking for updates. "
        "This usually means the packaged app could not find a trusted CA bundle. "
        f"Details: {exc}"
    )


@dataclass
class UpdateInfo:
    current_version: str
    latest_version: str | None = None
    available: bool = False
    release_url: str = RELEASES_PAGE_URL
    asset_name: str | None = None
    asset_url: str | None = None
    checksum_url: str | None = None
    published_at: str | None = None
    body: str = ""
    error: str | None = None
    from_cache: bool = False
    cache_path: str | None = None
    cache_age_seconds: int | None = None
    asset_available: bool | None = None
    checksum_available: bool | None = None
    asset_names: list[str] = field(default_factory=list)


@dataclass
class UpdateResult:
    ok: bool
    message: str
    log_path: Path
    downloaded_path: Path | None = None
    restart_started: bool = False
    checksum_verified: bool | None = None
    error: str | None = None


def user_workspace() -> Path:
    """Return the same durable workspace concept used by packaged builds."""
    override = os.environ.get("TECH_STOCK_HOME")
    if override:
        return Path(override).expanduser()
    documents = Path.home() / "Documents"
    if documents.exists():
        return documents / "tech_stock"
    return Path.home() / "tech_stock"


def update_dir() -> Path:
    path = user_workspace() / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def update_log_path() -> Path:
    path = user_workspace() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path / "update.log"


def _log(message: str) -> None:
    path = update_log_path()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")


def normalize_version(version: str | None) -> tuple[int, ...]:
    if not version:
        return (0,)
    cleaned = version.strip().lstrip("vV")
    parts: list[int] = []
    for token in cleaned.replace("-", ".").split("."):
        digits = ""
        for char in token:
            if not char.isdigit():
                break
            digits += char
        if digits:
            parts.append(int(digits))
    return tuple(parts or [0])


def is_newer_version(latest: str | None, current: str | None = None) -> bool:
    latest_tuple = normalize_version(latest)
    current_tuple = normalize_version(current or APP_VERSION)
    width = max(len(latest_tuple), len(current_tuple))
    latest_tuple += (0,) * (width - len(latest_tuple))
    current_tuple += (0,) * (width - len(current_tuple))
    return latest_tuple > current_tuple


def current_platform_asset_name() -> str | None:
    system = platform.system().lower()
    if system == "darwin":
        return "tech_stock.dmg"
    if system == "windows":
        return "tech_stock-windows.zip"
    return None


def source_root() -> Path:
    return Path(__file__).resolve().parents[1]


def is_source_checkout() -> bool:
    return (source_root() / ".git").exists() and not getattr(sys, "frozen", False)


def ssl_context() -> ssl.SSLContext:
    """Build an HTTPS context that works inside PyInstaller bundles."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def fetch_latest_release(timeout: float = 6.0) -> dict[str, Any]:
    request = urllib.request.Request(
        LATEST_RELEASE_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"tech_stock/{APP_VERSION}",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
        return json.loads(response.read().decode("utf-8"))


DEFAULT_UPDATE_CHECK_TTL_SECONDS = 6 * 60 * 60  # 6 hours


def _update_cache_path() -> Path:
    path = user_workspace() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path / "update_check.json"


def _serialize_update_info(info: "UpdateInfo") -> dict[str, Any]:
    return {
        "current_version": info.current_version,
        "latest_version": info.latest_version,
        "available": info.available,
        "release_url": info.release_url,
        "asset_name": info.asset_name,
        "asset_url": info.asset_url,
        "checksum_url": info.checksum_url,
        "published_at": info.published_at,
        "body": info.body,
        "error": info.error,
        "asset_available": info.asset_available,
        "checksum_available": info.checksum_available,
        "asset_names": info.asset_names,
    }


def _deserialize_update_info(payload: dict[str, Any]) -> "UpdateInfo":
    return UpdateInfo(
        current_version=payload.get("current_version") or APP_VERSION,
        latest_version=payload.get("latest_version"),
        available=bool(payload.get("available")),
        release_url=payload.get("release_url") or RELEASES_PAGE_URL,
        asset_name=payload.get("asset_name"),
        asset_url=payload.get("asset_url"),
        checksum_url=payload.get("checksum_url"),
        published_at=payload.get("published_at"),
        body=payload.get("body") or "",
        error=payload.get("error"),
        asset_available=payload.get("asset_available"),
        checksum_available=payload.get("checksum_available"),
        asset_names=list(payload.get("asset_names") or []),
    )


def _load_cached_update_info(ttl_seconds: int) -> "UpdateInfo | None":
    cache_path = _update_cache_path()
    if not cache_path.exists():
        return None
    try:
        envelope = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    cached_at_iso = envelope.get("cached_at")
    info_payload = envelope.get("info")
    cached_current = envelope.get("for_current_version")
    if not (cached_at_iso and isinstance(info_payload, dict)):
        return None
    try:
        cached_at = datetime.fromisoformat(cached_at_iso)
    except ValueError:
        return None
    cache_age = (datetime.now() - cached_at).total_seconds()
    if cache_age > ttl_seconds:
        return None
    # Invalidate stale-current-version entries: after the user updates,
    # the cache key on disk would otherwise lie about "available".
    if cached_current and cached_current != APP_VERSION:
        return None
    info = _deserialize_update_info(info_payload)
    # An error result should not stick — let the next call retry the network path.
    if info.error:
        return None
    info.from_cache = True
    info.cache_path = str(cache_path)
    info.cache_age_seconds = max(0, int(cache_age))
    return info


def _save_update_cache(info: "UpdateInfo") -> None:
    if info.error:
        # Don't persist failed lookups — let the next caller retry.
        return
    try:
        envelope = {
            "cached_at": datetime.now().isoformat(timespec="seconds"),
            "for_current_version": APP_VERSION,
            "info": _serialize_update_info(info),
        }
        _update_cache_path().write_text(json.dumps(envelope, indent=2), encoding="utf-8")
    except OSError as exc:
        _log(f"cache write failed: {exc}")


def check_for_update(
    current_version: str | None = None,
    timeout: float = 6.0,
    *,
    use_cache: bool = False,
    cache_ttl_seconds: int = DEFAULT_UPDATE_CHECK_TTL_SECONDS,
) -> UpdateInfo:
    """Check GitHub Releases for a newer public release.

    By default this hits the live GitHub API every call (keeping prior CLI
    behaviour). UI surfaces that probe on every refresh should set
    ``use_cache=True`` to read the last successful result from
    ``user_workspace()/cache/update_check.json`` when fresher than
    ``cache_ttl_seconds`` (default 6 hours). Failed lookups are never cached.
    """
    if use_cache:
        cached = _load_cached_update_info(cache_ttl_seconds)
        if cached is not None:
            return cached
    current = current_version or APP_VERSION
    try:
        release = fetch_latest_release(timeout=timeout)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        message = _certificate_error_message(exc) if "CERTIFICATE_VERIFY_FAILED" in str(exc) else str(exc)
        _log(f"check failed: {message}")
        return UpdateInfo(current_version=current, error=message)

    latest_tag = str(release.get("tag_name") or "")
    release_url = str(release.get("html_url") or RELEASES_PAGE_URL)
    wanted_asset = current_platform_asset_name()
    asset_name = None
    asset_url = None
    checksum_url = None
    asset_names: list[str] = []
    for asset in release.get("assets") or []:
        name = str(asset.get("name") or "")
        if name:
            asset_names.append(name)
        if name == "SHA256SUMS.txt":
            checksum_url = str(asset.get("browser_download_url") or "")
        if wanted_asset and name == wanted_asset:
            asset_name = name
            asset_url = str(asset.get("browser_download_url") or "")

    available = is_newer_version(latest_tag, current)
    info = UpdateInfo(
        current_version=current,
        latest_version=latest_tag.lstrip("vV") if latest_tag else None,
        available=available,
        release_url=release_url,
        asset_name=asset_name,
        asset_url=asset_url,
        checksum_url=checksum_url,
        published_at=release.get("published_at"),
        body=str(release.get("body") or ""),
        from_cache=False,
        cache_path=str(_update_cache_path()),
        cache_age_seconds=0,
        asset_available=bool(asset_url),
        checksum_available=bool(checksum_url),
        asset_names=asset_names,
    )
    _save_update_cache(info)
    return info


def download_asset(info: UpdateInfo, timeout: float = 60.0) -> Path:
    if not info.asset_url or not info.asset_name:
        raise RuntimeError("No downloadable asset is available for this platform.")
    destination = update_dir() / f"{info.latest_version}-{info.asset_name}"
    tmp_destination = destination.with_suffix(destination.suffix + ".part")
    _log(f"download start: {info.asset_url} -> {destination}")
    request = urllib.request.Request(info.asset_url, headers={"User-Agent": f"tech_stock/{APP_VERSION}"})
    with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response, tmp_destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    tmp_destination.replace(destination)
    _log(f"download complete: {destination}")
    return destination


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_asset_checksum(path: Path, info: UpdateInfo, timeout: float = 30.0) -> bool | None:
    """Verify a downloaded release asset against SHA256SUMS.txt when present."""
    if not info.checksum_url or not info.asset_name:
        _log("checksum skipped: SHA256SUMS.txt not available for this release")
        return None
    request = urllib.request.Request(info.checksum_url, headers={"User-Agent": f"tech_stock/{APP_VERSION}"})
    with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
        checksum_text = response.read().decode("utf-8")
    expected = None
    for line in checksum_text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == info.asset_name:
            expected = parts[0].lower()
            break
    if not expected:
        _log(f"checksum skipped: no entry for {info.asset_name}")
        return None
    actual = _sha256(path)
    if actual != expected:
        _log(f"checksum mismatch for {info.asset_name}: expected {expected}, got {actual}")
        raise RuntimeError(f"Checksum verification failed for {info.asset_name}.")
    _log(f"checksum verified for {info.asset_name}: {actual}")
    return True


def _app_bundle_path() -> Path | None:
    executable = Path(sys.executable).resolve()
    for parent in [executable, *executable.parents]:
        if parent.suffix == ".app":
            return parent
    return None


def _start_macos_update(dmg_path: Path) -> bool:
    app_bundle = _app_bundle_path()
    if not app_bundle:
        subprocess.Popen(["open", str(dmg_path)])
        return False

    script_path = update_dir() / "apply_macos_update.sh"
    mount_dir = update_dir() / "mount"
    script = f"""#!/bin/bash
set -u
PID="{os.getpid()}"
DMG={str(dmg_path)!r}
APP_DEST={str(app_bundle)!r}
MOUNT={str(mount_dir)!r}
LOG={str(update_log_path())!r}
echo "$(date -Iseconds) macOS updater waiting for $PID" >> "$LOG"
while kill -0 "$PID" 2>/dev/null; do sleep 1; done
rm -rf "$MOUNT"
mkdir -p "$MOUNT"
if ! hdiutil attach "$DMG" -nobrowse -mountpoint "$MOUNT" >> "$LOG" 2>&1; then
  echo "$(date -Iseconds) attach failed; opening dmg" >> "$LOG"
  open "$DMG"
  exit 1
fi
TMP_APP="$(mktemp -d)/tech_stock.app"
ditto "$MOUNT/tech_stock.app" "$TMP_APP" >> "$LOG" 2>&1
rm -rf "$APP_DEST" >> "$LOG" 2>&1
if ditto "$TMP_APP" "$APP_DEST" >> "$LOG" 2>&1; then
  xattr -dr com.apple.quarantine "$APP_DEST" >> "$LOG" 2>&1 || true
  hdiutil detach "$MOUNT" >> "$LOG" 2>&1 || true
  open "$APP_DEST"
  echo "$(date -Iseconds) macOS update applied" >> "$LOG"
else
  echo "$(date -Iseconds) copy failed; opening dmg for manual install" >> "$LOG"
  hdiutil detach "$MOUNT" >> "$LOG" 2>&1 || true
  open "$DMG"
  exit 1
fi
"""
    script_path.write_text(script, encoding="utf-8")
    script_path.chmod(0o755)
    subprocess.Popen(["/bin/bash", str(script_path)], start_new_session=True)
    return True


def _start_windows_update(zip_path: Path) -> bool:
    if not getattr(sys, "frozen", False):
        return False
    install_dir = Path(sys.executable).resolve().parent
    script_path = update_dir() / "apply_windows_update.ps1"
    extract_dir = update_dir() / "windows_extract"
    script = f"""
$ErrorActionPreference = "Continue"
$PidToWait = {os.getpid()}
$Zip = {str(zip_path)!r}
$Dest = {str(install_dir)!r}
$Extract = {str(extract_dir)!r}
$Log = {str(update_log_path())!r}
Add-Content -Path $Log -Value "$(Get-Date -Format o) Windows updater waiting for $PidToWait"
try {{ Wait-Process -Id $PidToWait -Timeout 120 }} catch {{ Start-Sleep -Seconds 3 }}
Remove-Item -Recurse -Force $Extract -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $Extract | Out-Null
Expand-Archive -Force -Path $Zip -DestinationPath $Extract
$NewRoot = Join-Path $Extract "windows"
if (!(Test-Path $NewRoot)) {{ $NewRoot = $Extract }}
Copy-Item -Recurse -Force (Join-Path $NewRoot "*") $Dest
$Exe = Join-Path $Dest "tech_stock.exe"
if (Test-Path $Exe) {{
  Start-Process $Exe
  Add-Content -Path $Log -Value "$(Get-Date -Format o) Windows update applied"
}} else {{
  Invoke-Item $Extract
  Add-Content -Path $Log -Value "$(Get-Date -Format o) Windows update extracted; exe not found"
}}
"""
    script_path.write_text(script, encoding="utf-8")
    subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ]
    )
    return True


def _restart_source_process() -> None:
    script = Path(sys.argv[0]).resolve() if sys.argv else None
    if script and script.name == "streamlit_app.py":
        subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(script)], cwd=source_root())
        return
    subprocess.Popen([sys.executable, *sys.argv], cwd=source_root())


def apply_update(info: UpdateInfo, *, restart: bool = True) -> UpdateResult:
    """Apply or stage an update while keeping user workspace data intact."""
    log_path = update_log_path()
    if not info.available:
        return UpdateResult(ok=True, message="Already on the latest version.", log_path=log_path)

    if is_source_checkout():
        _log("source update start: git pull --ff-only")
        completed = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=source_root(),
            text=True,
            capture_output=True,
            timeout=120,
        )
        _log(f"source update exit={completed.returncode}: {completed.stdout[-800:]} {completed.stderr[-800:]}")
        if completed.returncode != 0:
            return UpdateResult(
                ok=False,
                message="Git update failed. See update.log for details.",
                log_path=log_path,
                error=completed.stderr or completed.stdout,
            )
        if restart:
            _restart_source_process()
        return UpdateResult(
            ok=True,
            message="Source checkout updated with git pull. Restart the app if it did not reopen automatically.",
            log_path=log_path,
            restart_started=restart,
        )

    if not info.asset_url:
        return UpdateResult(
            ok=False,
            message=f"No auto-update asset is available for this platform. Open {info.release_url}",
            log_path=log_path,
            error="missing asset",
        )

    checksum_verified = None
    try:
        downloaded = download_asset(info)
        checksum_verified = verify_asset_checksum(downloaded, info)
    except Exception as exc:
        _log(f"download or verification failed: {exc}")
        return UpdateResult(
            ok=False,
            message="Update download or verification failed.",
            log_path=log_path,
            error=str(exc),
            checksum_verified=checksum_verified,
        )

    system = platform.system().lower()
    restart_started = False
    if restart and system == "darwin":
        restart_started = _start_macos_update(downloaded)
    elif restart and system == "windows":
        restart_started = _start_windows_update(downloaded)

    if not restart_started:
        if system == "darwin":
            subprocess.Popen(["open", str(downloaded)])
        elif system == "windows":
            extract_dir = update_dir() / f"tech_stock-{info.latest_version}-windows"
            shutil.rmtree(extract_dir, ignore_errors=True)
            with zipfile.ZipFile(downloaded) as archive:
                archive.extractall(extract_dir)
            os.startfile(extract_dir)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["open", info.release_url] if sys.platform == "darwin" else ["xdg-open", info.release_url])

    return UpdateResult(
        ok=True,
        message=(
            "Update downloaded and installer started. The app will restart when replacement finishes."
            if restart_started
            else "Update downloaded. Follow the opened installer/folder to finish updating."
        ),
        log_path=log_path,
        downloaded_path=downloaded,
        restart_started=restart_started,
        checksum_verified=checksum_verified,
    )


def update_status_text(info: UpdateInfo) -> str:
    if info.error:
        return f"Update check failed: {info.error}"
    if info.available:
        return f"Version {info.latest_version} is available. Current version: {info.current_version}."
    return f"You are up to date. Current version: {info.current_version}."


def cli_update_check(*, apply: bool = False) -> int:
    info = check_for_update()
    print(update_status_text(info))
    if info.release_url:
        print(f"Release page: {info.release_url}")
    if info.error:
        return 1
    if apply and info.available:
        result = apply_update(info, restart=False)
        print(result.message)
        print(f"Update log: {result.log_path}")
        return 0 if result.ok else 1
    return 0
