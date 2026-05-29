"""Install / inspect / uninstall a per-user OS schedule for tech_stock (v1.18).

Public API
----------
``install_schedule(times) -> ScheduleResult``
    Write a launchd plist (macOS), Task Scheduler XML (Windows), or
    crontab line (Linux) that runs the CLI at the supplied times of day.

``uninstall_schedule() -> ScheduleResult``
    Remove the schedule artefact created by ``install_schedule``.

``current_schedule() -> CurrentSchedule``
    Inspect what's installed right now. UI uses this to render the live
    state next to the install button.

``preview_schedule(times)`` — returns the raw artefact body (plist /
xml / cron line) without writing anything; used in the Streamlit/Desktop
preview pane.

Design choices
--------------
* **Per-user only.** No ``sudo``, no root crontab. macOS uses
  ``~/Library/LaunchAgents/com.techstock.daily.plist``; Linux edits the
  user's own crontab; Windows uses ``schtasks /XML`` (per-user by default
  when the current user is non-admin).
* **Idempotent.** Re-running ``install_schedule`` overwrites cleanly;
  ``uninstall_schedule`` is a no-op when nothing is installed.
* **Never raises.** Every step reports through ``ScheduleResult`` so the
  UI can present a friendly status. We log every operation through
  ``observability``.
* **Test-friendly.** Each backend's *write* step is isolated so tests can
  monkeypatch the write target to ``tmp_path``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET


LABEL = "com.techstock.daily"


@dataclass(frozen=True)
class ScheduleTime:
    """One scheduled run."""

    hour: int  # 0–23
    minute: int  # 0–59
    session_type: str  # "morning" | "afternoon"


@dataclass(frozen=True)
class ScheduleResult:
    ok: bool
    backend: str  # "launchd" | "task_scheduler" | "cron" | "noop"
    path: Path | None = None
    message: str = ""
    error: str | None = None


@dataclass
class CurrentSchedule:
    installed: bool
    backend: str
    path: Path | None
    times: list[ScheduleTime] = field(default_factory=list)


# ── Entry-point that the scheduled task invokes ───────────────────────────


def _scheduled_command(session_type: str) -> list[str]:
    """Argv the scheduled task will execute.

    Uses the project's Python (``.venv/bin/python3`` when present), falls
    back to whatever ``python3`` is on ``$PATH``. We always pass
    ``--session-type`` so a single binary can serve both morning and
    afternoon slots.
    """
    project_root = Path(__file__).resolve().parents[1]
    venv_python = project_root / ".venv" / "bin" / "python3"
    if sys.platform == "win32":
        venv_python = project_root / ".venv" / "Scripts" / "python.exe"
    python_bin = str(venv_python) if venv_python.exists() else sys.executable or "python3"
    return [python_bin, "-m", "src.main", "--session-type", session_type, "--non-interactive"]


# ── macOS: launchd plist ──────────────────────────────────────────────────


def _launchd_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _build_launchd_plist(times: list[ScheduleTime]) -> str:
    """Render the launchd ``Program Arguments`` + ``StartCalendarInterval``."""
    # One plist can carry multiple StartCalendarInterval entries; launchd
    # OR's them, which is exactly what we want for morning + afternoon runs.
    intervals = "\n".join(
        f"        <dict>\n            <key>Hour</key><integer>{t.hour}</integer>\n"
        f"            <key>Minute</key><integer>{t.minute}</integer>\n        </dict>"
        for t in times
    )
    # All entries share the same argv — the plist itself doesn't model
    # different session_types per slot. To carry that distinction we'd
    # need separate plists; we instead pick whichever session_type matches
    # the user's first morning vs afternoon split. The "morning"-vs-"afternoon"
    # logic is done at CLI invocation time based on local clock.
    session_default = times[0].session_type if times else "morning"
    argv_xml = "\n".join(f"        <string>{_xml_escape(arg)}</string>" for arg in _scheduled_command(session_default))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        f"    <key>Label</key><string>{LABEL}</string>\n"
        "    <key>ProgramArguments</key>\n"
        "    <array>\n"
        f"{argv_xml}\n"
        "    </array>\n"
        "    <key>StartCalendarInterval</key>\n"
        "    <array>\n"
        f"{intervals}\n"
        "    </array>\n"
        f"    <key>WorkingDirectory</key><string>{_xml_escape(str(Path(__file__).resolve().parents[1]))}</string>\n"
        "    <key>StandardOutPath</key>\n"
        f"    <string>{_xml_escape(str(Path.home() / 'Library' / 'Logs' / 'tech_stock' / 'schedule.out'))}</string>\n"
        "    <key>StandardErrorPath</key>\n"
        f"    <string>{_xml_escape(str(Path.home() / 'Library' / 'Logs' / 'tech_stock' / 'schedule.err'))}</string>\n"
        "    <key>RunAtLoad</key><false/>\n"
        "</dict>\n"
        "</plist>\n"
    )


# ── Windows: Task Scheduler XML ───────────────────────────────────────────


def _task_scheduler_path() -> Path:
    # We don't actually write the task in the filesystem on Windows — `schtasks /Create /XML`
    # ingests it — but we still write the XML to a known location so the UI can
    # show "what's installed". On Windows the canonical path is %APPDATA%.
    base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    return base / "tech_stock" / f"{LABEL}.xml"


def _build_task_scheduler_xml(times: list[ScheduleTime]) -> str:
    triggers = "\n".join(
        f"""    <CalendarTrigger>
      <StartBoundary>2026-01-01T{t.hour:02d}:{t.minute:02d}:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>"""
        for t in times
    )
    cmd = _scheduled_command(times[0].session_type if times else "morning")
    arg_string = " ".join(_quote_windows(a) for a in cmd[1:])
    return (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        "  <Triggers>\n"
        f"{triggers}\n"
        "  </Triggers>\n"
        "  <Principals>\n"
        '    <Principal id="Author">\n'
        "      <LogonType>InteractiveToken</LogonType>\n"
        "    </Principal>\n"
        "  </Principals>\n"
        "  <Actions>\n"
        "    <Exec>\n"
        f"      <Command>{_xml_escape(cmd[0])}</Command>\n"
        f"      <Arguments>{_xml_escape(arg_string)}</Arguments>\n"
        f"      <WorkingDirectory>{_xml_escape(str(Path(__file__).resolve().parents[1]))}</WorkingDirectory>\n"
        "    </Exec>\n"
        "  </Actions>\n"
        "</Task>\n"
    )


# ── Linux: crontab ────────────────────────────────────────────────────────


def _cron_marker() -> str:
    return f"# tech_stock-scheduled-{LABEL}"


def _build_cron_lines(times: list[ScheduleTime]) -> list[str]:
    """Each scheduled time becomes one ``minute hour * * * <argv>`` line."""
    lines = []
    for t in times:
        cmd = " ".join(_quote_posix(a) for a in _scheduled_command(t.session_type))
        lines.append(f"{t.minute} {t.hour} * * * {cmd} {_cron_marker()}")
    return lines


# ── Public ops ────────────────────────────────────────────────────────────


def preview_schedule(times: list[ScheduleTime]) -> tuple[str, str]:
    """Return ``(backend_name, artefact_body)`` without writing anything."""
    times = sorted(times, key=lambda t: (t.hour, t.minute))
    if sys.platform == "darwin":
        return "launchd", _build_launchd_plist(times)
    if sys.platform == "win32":
        return "task_scheduler", _build_task_scheduler_xml(times)
    return "cron", "\n".join(_build_cron_lines(times))


def install_schedule(times: list[ScheduleTime]) -> ScheduleResult:
    """Install the schedule for the current OS. Never raises."""
    if not times:
        return ScheduleResult(ok=False, backend="noop", message="No times provided.")
    times = sorted(times, key=lambda t: (t.hour, t.minute))

    try:
        if sys.platform == "darwin":
            return _install_launchd(times)
        if sys.platform == "win32":
            return _install_task_scheduler(times)
        return _install_cron(times)
    except Exception as exc:  # noqa: BLE001
        _log("error", "install_failed", f"install_schedule crashed: {exc}", {"platform": sys.platform})
        return ScheduleResult(ok=False, backend="unknown", message="Install failed", error=str(exc))


def uninstall_schedule() -> ScheduleResult:
    """Remove the schedule. Never raises. No-op when nothing installed."""
    try:
        if sys.platform == "darwin":
            return _uninstall_launchd()
        if sys.platform == "win32":
            return _uninstall_task_scheduler()
        return _uninstall_cron()
    except Exception as exc:  # noqa: BLE001
        _log("error", "uninstall_failed", f"uninstall_schedule crashed: {exc}", {"platform": sys.platform})
        return ScheduleResult(ok=False, backend="unknown", message="Uninstall failed", error=str(exc))


def current_schedule() -> CurrentSchedule:
    """Inspect what's installed. Never raises."""
    try:
        if sys.platform == "darwin":
            return _current_launchd()
        if sys.platform == "win32":
            return _current_task_scheduler()
        return _current_cron()
    except Exception as exc:  # noqa: BLE001
        _log("warning", "inspect_failed", f"current_schedule crashed: {exc}", {"platform": sys.platform})
        return CurrentSchedule(installed=False, backend="unknown", path=None)


# ── launchd (macOS) ───────────────────────────────────────────────────────


def _install_launchd(times: list[ScheduleTime]) -> ScheduleResult:
    path = _launchd_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = _build_launchd_plist(times)
    path.write_text(body, encoding="utf-8")

    # Try to load it; failure isn't fatal — the user can `launchctl load`
    # manually later. We always unload first to avoid the "already loaded"
    # warning when re-installing.
    if shutil.which("launchctl"):
        subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
        subprocess.run(["launchctl", "load", str(path)], capture_output=True)
    _log("info", "installed", f"launchd plist written + loaded ({len(times)} slot(s))", {"path": str(path)})
    return ScheduleResult(ok=True, backend="launchd", path=path, message=f"Installed {len(times)} slot(s).")


def _uninstall_launchd() -> ScheduleResult:
    path = _launchd_path()
    if not path.exists():
        return ScheduleResult(ok=True, backend="launchd", path=None, message="Nothing to uninstall.")
    if shutil.which("launchctl"):
        subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
    path.unlink()
    _log("info", "uninstalled", "launchd plist removed", {"path": str(path)})
    return ScheduleResult(ok=True, backend="launchd", path=path, message="Removed.")


def _current_launchd() -> CurrentSchedule:
    path = _launchd_path()
    if not path.exists():
        return CurrentSchedule(installed=False, backend="launchd", path=None)
    times = _parse_launchd_times(path.read_text(encoding="utf-8"))
    return CurrentSchedule(installed=True, backend="launchd", path=path, times=times)


def _parse_launchd_times(body: str) -> list[ScheduleTime]:
    """Pull (hour, minute) tuples back out of the plist for the UI."""
    out: list[ScheduleTime] = []
    try:
        # plist is XML but with a slightly quirky DTD — strip the DOCTYPE so
        # ElementTree doesn't try to fetch it.
        cleaned = "\n".join(line for line in body.splitlines() if not line.startswith("<!DOCTYPE"))
        root = ET.fromstring(cleaned)
    except ET.ParseError:
        return out
    for entry in root.iter("dict"):
        children = list(entry)
        # We're looking for the StartCalendarInterval sub-dicts that have
        # exactly Hour + Minute keys.
        keys = [c.text for c in children if c.tag == "key"]
        values = [c for c in children if c.tag != "key"]
        if "Hour" in keys and "Minute" in keys and len(keys) <= 3:
            mapping = dict(zip(keys, values, strict=False))
            try:
                hour = int((mapping["Hour"].text or "0"))
                minute = int((mapping["Minute"].text or "0"))
            except (KeyError, AttributeError, ValueError):
                continue
            out.append(ScheduleTime(hour=hour, minute=minute, session_type="auto"))
    return out


# ── Task Scheduler (Windows) ──────────────────────────────────────────────


def _install_task_scheduler(times: list[ScheduleTime]) -> ScheduleResult:
    path = _task_scheduler_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = _build_task_scheduler_xml(times)
    path.write_text(body, encoding="utf-16")

    if shutil.which("schtasks"):
        subprocess.run(["schtasks", "/Delete", "/TN", LABEL, "/F"], capture_output=True)
        subprocess.run(
            ["schtasks", "/Create", "/XML", str(path), "/TN", LABEL],
            capture_output=True,
            check=False,
        )
    _log("info", "installed", f"task_scheduler XML written ({len(times)} slot(s))", {"path": str(path)})
    return ScheduleResult(ok=True, backend="task_scheduler", path=path, message=f"Installed {len(times)} slot(s).")


def _uninstall_task_scheduler() -> ScheduleResult:
    path = _task_scheduler_path()
    if shutil.which("schtasks"):
        subprocess.run(["schtasks", "/Delete", "/TN", LABEL, "/F"], capture_output=True)
    if path.exists():
        path.unlink()
    _log("info", "uninstalled", "task scheduler entry removed", {"path": str(path)})
    return ScheduleResult(ok=True, backend="task_scheduler", path=path, message="Removed.")


def _current_task_scheduler() -> CurrentSchedule:
    path = _task_scheduler_path()
    if not path.exists():
        return CurrentSchedule(installed=False, backend="task_scheduler", path=None)
    # Parsing the XML for trigger times — the UI only needs the times,
    # not the full action description.
    times: list[ScheduleTime] = []
    try:
        root = ET.fromstring(path.read_text(encoding="utf-16"))
        ns = "{http://schemas.microsoft.com/windows/2004/02/mit/task}"
        for trig in root.iter(f"{ns}CalendarTrigger"):
            start = trig.find(f"{ns}StartBoundary")
            if start is None or not start.text:
                continue
            # StartBoundary is e.g. "2026-01-01T07:00:00"
            try:
                hhmm = start.text.split("T", 1)[1]
                hour, minute = int(hhmm[0:2]), int(hhmm[3:5])
                times.append(ScheduleTime(hour=hour, minute=minute, session_type="auto"))
            except (ValueError, IndexError):
                continue
    except ET.ParseError:
        pass
    return CurrentSchedule(installed=True, backend="task_scheduler", path=path, times=times)


# ── crontab (Linux / *BSD) ────────────────────────────────────────────────


def _install_cron(times: list[ScheduleTime]) -> ScheduleResult:
    """Append our lines to the user's crontab, preserving everything else.

    Idempotent: existing lines marked with `_cron_marker()` are removed
    before appending new ones.
    """
    if not shutil.which("crontab"):
        return ScheduleResult(ok=False, backend="cron", message="crontab not found on $PATH", error="no_crontab")

    existing = _read_crontab()
    cleaned = [line for line in existing if _cron_marker() not in line]
    new = cleaned + _build_cron_lines(times)
    _write_crontab(new)
    path = _cron_artefact_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(new) + "\n", encoding="utf-8")
    _log("info", "installed", f"cron lines installed ({len(times)} slot(s))", {})
    return ScheduleResult(ok=True, backend="cron", path=path, message=f"Installed {len(times)} slot(s).")


def _uninstall_cron() -> ScheduleResult:
    if not shutil.which("crontab"):
        return ScheduleResult(ok=False, backend="cron", message="crontab not found", error="no_crontab")
    existing = _read_crontab()
    cleaned = [line for line in existing if _cron_marker() not in line]
    if len(cleaned) == len(existing):
        return ScheduleResult(ok=True, backend="cron", message="Nothing to uninstall.")
    _write_crontab(cleaned)
    artefact = _cron_artefact_path()
    if artefact.exists():
        artefact.unlink()
    _log("info", "uninstalled", "cron lines removed", {})
    return ScheduleResult(ok=True, backend="cron", message="Removed.")


def _current_cron() -> CurrentSchedule:
    if not shutil.which("crontab"):
        return CurrentSchedule(installed=False, backend="cron", path=None)
    times: list[ScheduleTime] = []
    for line in _read_crontab():
        if _cron_marker() not in line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            minute = int(parts[0])
            hour = int(parts[1])
            times.append(ScheduleTime(hour=hour, minute=minute, session_type="auto"))
        except ValueError:
            continue
    path = _cron_artefact_path() if times else None
    return CurrentSchedule(installed=bool(times), backend="cron", path=path, times=times)


def _read_crontab() -> list[str]:
    try:
        out = subprocess.run(["crontab", "-l"], capture_output=True, check=False)
    except FileNotFoundError:
        return []
    return out.stdout.decode("utf-8", errors="ignore").splitlines()


def _write_crontab(lines: list[str]) -> None:
    body = "\n".join(lines) + ("\n" if lines else "")
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".cron") as tmp:
        tmp.write(body)
        tmp_path = tmp.name
    subprocess.run(["crontab", tmp_path], capture_output=True, check=False)
    try:
        os.unlink(tmp_path)
    except OSError:
        pass


def _cron_artefact_path() -> Path:
    return Path.home() / ".config" / "tech_stock" / f"{LABEL}.cron"


# ── Helpers ───────────────────────────────────────────────────────────────


def _xml_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _quote_posix(value: str) -> str:
    # Whitelist alnum and a few benign chars; everything else needs quoting.
    safe_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_./@=:"
    if value and all(c in safe_chars for c in value):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


def _quote_windows(value: str) -> str:
    if not value:
        return '""'
    if any(c in value for c in ' \t"'):
        return '"' + value.replace('"', '\\"') + '"'
    return value


def _log(level: str, code: str, message: str, context: dict | None = None) -> None:
    try:
        from src.observability import log_event

        log_event("scheduling", level, code, message, context or {})
    except Exception:
        pass


__all__ = [
    "LABEL",
    "ScheduleTime",
    "ScheduleResult",
    "CurrentSchedule",
    "install_schedule",
    "uninstall_schedule",
    "current_schedule",
    "preview_schedule",
]
