"""Desktop notifications (v1.18).

Cross-platform pop-up notifications fired when:
  * a report run completes
  * a trailing-stop breach is detected
  * a thesis is flagged for force-exit

Why this exists
---------------
Pre-v1.18 the app was passive — users only saw breaches when they actively
opened the Dashboard. Time-sensitive alerts could sit for a day. This
module wires the existing detection paths (already producing well-shaped
dicts) into the native OS notification channels.

Platform backends
-----------------
* **macOS**       — ``osascript`` (no install required, ships with macOS).
* **Windows**     — PowerShell ``New-BurntToastNotification`` first; on
                    failure (BurntToast not installed) falls back to a
                    PowerShell MessageBox via ``[System.Windows.Forms]``.
* **Linux**       — ``notify-send`` (``libnotify``-bin).

Design choices
--------------
* **Settings-driven**: a ``notifications`` block in ``config/settings.json``
  controls which channels fire. Missing block → disabled by default so v1.17
  upgrades don't suddenly bombard users.
* **Best-effort + never raises**: a notification failure must never break a
  report run. Every send is wrapped and logged via observability.
* **Subprocess**: we shell out rather than depend on platform libraries —
  zero new pip dependencies, and the PyInstaller bundle stays slim.
* **Rate-limited**: a small in-memory dedup window suppresses duplicate
  notifications fired within 5 seconds (e.g. two breach events that share
  a ticker).
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Iterable


# ── Config ─────────────────────────────────────────────────────────────────


DEFAULT_CHANNELS: dict[str, bool] = {
    "report_complete": True,
    "trailing_stop_breach": True,
    "thesis_force_exit": True,
    "high_priority_action": True,
}

# In-memory dedup: title+message → epoch seconds of last send. Cheap enough
# to never need eviction at the app's scale.
_recent_sends: dict[str, float] = {}
_DEDUP_WINDOW_SECONDS = 5.0


def _load_settings() -> dict:
    """Read ``config/settings.json``'s ``notifications`` block. Tolerant."""
    try:
        from src.config import load_settings

        return load_settings().get("notifications") or {}
    except Exception:
        return {}


def is_channel_enabled(channel: str) -> bool:
    """Return True if the named channel should fire.

    Settings overlay layered on the DEFAULT_CHANNELS, gated by the top-level
    ``enabled`` switch. When ``enabled`` is explicitly False, ALL channels are
    disabled even if their per-channel flag is True.
    """
    settings = _load_settings()
    if settings.get("enabled") is False:
        return False
    channels = {**DEFAULT_CHANNELS, **(settings.get("channels") or {})}
    return bool(channels.get(channel, True))


# ── Public API ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SendResult:
    """Captures what happened during a send attempt — useful for tests."""

    sent: bool
    backend: str
    error: str | None = None
    deduped: bool = False
    skipped_reason: str | None = None


def send(
    title: str,
    message: str,
    *,
    channel: str = "general",
    urgency: str = "normal",
) -> SendResult:
    """Fire a desktop notification. Never raises.

    Parameters
    ----------
    title : str
        Bold title shown at the top of the notification.
    message : str
        Body text. Multi-line is allowed but most OSes truncate at ~3 lines.
    channel : str
        Used to look up the per-channel ``settings.json`` toggle. Pass
        ``"report_complete"``, ``"trailing_stop_breach"``,
        ``"thesis_force_exit"``, or ``"high_priority_action"`` to use the
        documented channels; anything else is treated as ``general``.
    urgency : str
        ``"low"`` / ``"normal"`` / ``"critical"`` — only honoured by Linux's
        ``notify-send`` today; other backends ignore it.
    """
    title = (title or "tech_stock").strip()
    message = (message or "").strip()

    # Settings gate
    if channel != "general" and not is_channel_enabled(channel):
        _log("info", "channel_disabled", f"Skipped {channel}: disabled in settings", {"title": title})
        return SendResult(sent=False, backend="none", skipped_reason="channel_disabled")

    # Dedup window
    key = f"{title}|{message}"
    now = time.monotonic()
    last = _recent_sends.get(key)
    if last is not None and now - last < _DEDUP_WINDOW_SECONDS:
        _log("info", "deduped", "Suppressed duplicate within dedup window", {"title": title})
        return SendResult(sent=False, backend="none", deduped=True)

    backend, error = _send_via_native(title, message, urgency=urgency)
    if backend != "none":
        _recent_sends[key] = now
        _log(
            "info" if error is None else "warning",
            "sent" if error is None else "backend_failed",
            f"notification → {backend}",
            {"title": title, "channel": channel, "error": error},
        )
        return SendResult(sent=error is None, backend=backend, error=error)

    # No backend produced a result.  Distinguish between "the backend crashed"
    # (error already set by ``_send_via_native``) and "no backend is even
    # available on this platform" — surface whichever the caller actually
    # encountered so tests + diagnostics can tell them apart.
    surfaced_error = error or "no_backend_available"
    _log(
        "warning",
        "no_backend" if surfaced_error == "no_backend_available" else "backend_failed",
        f"notification failed: {surfaced_error}",
        {"title": title, "platform": sys.platform},
    )
    return SendResult(sent=False, backend="none", error=surfaced_error)


def send_many(items: Iterable[tuple[str, str]], *, channel: str = "general") -> list[SendResult]:
    """Convenience for batched notifications (e.g. a list of breaches).

    Items beyond 5 are collapsed into a single summary line so the user
    isn't flooded.
    """
    items = list(items)
    if not items:
        return []
    if len(items) <= 5:
        return [send(title, message, channel=channel) for title, message in items]
    # Collapse: send the first 3 individually, then a single summary.
    out = [send(title, message, channel=channel) for title, message in items[:3]]
    extras = len(items) - 3
    out.append(send("tech_stock", f"… plus {extras} more {channel} notifications", channel=channel))
    return out


# ── Native backends ────────────────────────────────────────────────────────


def _send_via_native(title: str, message: str, *, urgency: str) -> tuple[str, str | None]:
    """Dispatch to the right OS backend. Returns ``(backend_name, error_or_None)``.

    ``backend_name`` is ``"none"`` when no backend was available.
    """
    try:
        if sys.platform == "darwin":
            return _send_via_osascript(title, message), None
        if sys.platform == "win32":
            return _send_via_windows(title, message)
        # Linux / *BSD
        if shutil.which("notify-send"):
            return _send_via_notify_send(title, message, urgency=urgency), None
        return "none", "no_backend_available"
    except FileNotFoundError as exc:
        return "none", f"binary_missing: {exc}"
    except subprocess.SubprocessError as exc:
        return "none", f"subprocess_error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return "none", f"unexpected: {exc}"


def _quote_applescript_string(value: str) -> str:
    """Escape a string for safe interpolation into an AppleScript literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _send_via_osascript(title: str, message: str) -> str:
    """macOS Notification Center via osascript."""
    script = f'display notification "{_quote_applescript_string(message)}" with title "{_quote_applescript_string(title)}"'
    subprocess.run(
        ["osascript", "-e", script],
        check=True,
        capture_output=True,
        timeout=5,
    )
    return "osascript"


def _send_via_notify_send(title: str, message: str, *, urgency: str) -> str:
    """Linux libnotify via notify-send."""
    cmd = ["notify-send", "-u", urgency if urgency in {"low", "normal", "critical"} else "normal", title, message]
    subprocess.run(cmd, check=True, capture_output=True, timeout=5)
    return "notify-send"


def _send_via_windows(title: str, message: str) -> tuple[str, str | None]:
    """Windows: prefer BurntToast, fall back to a Forms MessageBox.

    Uses ``shlex.quote``-equivalent escaping via ``"\""`` doubling so the
    PowerShell argv never gets misparsed on Windows shells.
    """

    def _esc(value: str) -> str:
        return value.replace("`", "``").replace('"', '`"')

    burnt = (
        f"if (Get-Module -ListAvailable BurntToast) {{ "
        f'  New-BurntToastNotification -Text "{_esc(title)}", "{_esc(message)}" '
        f"}} else {{ "
        f"  Add-Type -AssemblyName PresentationFramework; "
        f'  [System.Windows.MessageBox]::Show("{_esc(message)}", "{_esc(title)}") | Out-Null '
        f"}}"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", burnt],
        capture_output=True,
        timeout=8,
    )
    if result.returncode != 0:
        stderr = (result.stderr or b"").decode("utf-8", errors="ignore").strip()
        return "powershell", f"non_zero_exit: {stderr or 'unknown'}"
    return "powershell", None


# ── Observability hook ────────────────────────────────────────────────────


def _log(level: str, code: str, message: str, context: dict | None = None) -> None:
    """Lazy import so the module load doesn't pull observability at startup."""
    try:
        from src.observability import log_event

        log_event("notifications", level, code, message, context or {})
    except Exception:
        pass


# ── Debug / build inspection helpers (used by tests) ──────────────────────


def _build_osascript_argv(title: str, message: str) -> list[str]:
    """Return the argv list ``osascript`` would receive — without firing it.

    Lets tests assert the escaping logic without actually shelling out.
    """
    script = f'display notification "{_quote_applescript_string(message)}" with title "{_quote_applescript_string(title)}"'
    return ["osascript", "-e", script]


def _build_notify_send_argv(title: str, message: str, *, urgency: str = "normal") -> list[str]:
    return ["notify-send", "-u", urgency if urgency in {"low", "normal", "critical"} else "normal", title, message]


def reset_dedup_cache() -> None:
    """Clear the in-memory dedup window. Used by tests + diagnostics."""
    _recent_sends.clear()


__all__ = [
    "DEFAULT_CHANNELS",
    "SendResult",
    "send",
    "send_many",
    "is_channel_enabled",
    "reset_dedup_cache",
]
