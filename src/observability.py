"""Structured logging for the API surface (v1.17).

Why this exists
---------------
Pre-v1.17 the API clients used silent ``except Exception:`` to keep graceful
degradation working — when finnhub was down the report just continued with
partial data.  Great for resilience, terrible for debugging.  Users (and
developers) had no way to know *why* a number was missing.

This module is the structured-log layer that those silent excepts now talk
to.  Every degradation event becomes one JSON-lines record on disk; the
Diagnostics tab in every UI then reads those records back to show success
rates per source, recent errors, and inline degradation pills.

Design choices
--------------
* **JSON Lines**: one record per line, machine-readable, ``jq``-friendly.
* **User workspace**: lives under ``user_workspace()/logs/diagnostics.jsonl``
  so it survives app updates (the same place reports + caches live).
* **Size-based rotation**: when the file exceeds ``MAX_BYTES`` we rotate to
  ``.1`` and start fresh.  No timestamp file names — keeps grep simple.
* **Redaction**: a small allow-list of secret-shaped patterns (API keys,
  bearer tokens, ``ANTHROPIC_API_KEY``-style env strings, email addresses)
  is scrubbed from every record's ``message`` and ``context`` before it hits
  disk.  Better than nothing without becoming a full DLP system.
* **Never raises**: the whole point is to *not* break behaviour when the
  underlying call is already failing.  Every public call is wrapped in
  ``try/except`` so a logger bug can't cascade.
* **Thread-safe**: ``threading.Lock`` around the write so concurrent
  enrichment workers don't corrupt records.

Public API
----------
``log_event(source, level, code, message, context=None) -> None``
``success_rate(source, hours=24) -> float``  (0.0–1.0, or None if no data)
``recent_errors(limit=50) -> list[dict]``  (newest first)
``source_summary(hours=24) -> dict``         (full Diagnostics tab payload)
``support_bundle() -> str``                  (last 500 events, redacted)
``clear_diagnostics() -> None``              (used by tests)
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections import defaultdict
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.updater import user_workspace

# ── Configuration ──────────────────────────────────────────────────────────

# Max size before rotating to .1.  ~5 MB ≈ tens of thousands of events; plenty
# for forensic look-backs without unbounded growth.
MAX_BYTES = 5 * 1024 * 1024

# Cap the in-memory tail used for the Diagnostics queries.  Even if the file
# is huge we never load more than this many lines.
TAIL_LINES = 5000

# Allowed level values — anything else is normalised to "error".
_VALID_LEVELS = {"debug", "info", "warning", "error", "critical"}


# ── Path helpers ────────────────────────────────────────────────────────────


def _log_path() -> Path:
    path = user_workspace() / "logs" / "diagnostics.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _rotated_path() -> Path:
    return _log_path().with_suffix(".jsonl.1")


# ── Redaction ───────────────────────────────────────────────────────────────

# Patterns we proactively redact before writing.  Order matters — match the
# most specific first so the more generic catch-all doesn't pre-empt them.
_REDACTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # OpenAI/Anthropic-style keys: sk-..., sk-ant-...
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), "[REDACTED-API-KEY]"),
    # Hex-ish 32+ char strings often used as Finnhub / Alpha Vantage keys
    (re.compile(r"\b[a-zA-Z0-9]{32,}\b"), "[REDACTED-TOKEN]"),
    # Bearer tokens inside Authorization headers
    (re.compile(r"(?i)Authorization:\s*Bearer\s+[A-Za-z0-9._-]+"), "Authorization: Bearer [REDACTED]"),
    # Email addresses
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "[REDACTED-EMAIL]"),
]


def _redact(value: Any) -> Any:
    """Recursively scrub secret-shaped substrings from strings, dicts, and lists."""
    if isinstance(value, str):
        out = value
        for pattern, replacement in _REDACTION_PATTERNS:
            out = pattern.sub(replacement, out)
        return out
    if isinstance(value, dict):
        return {k: _redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value]
    return value


# ── Writer (thread-safe, never raises) ─────────────────────────────────────

_write_lock = threading.Lock()


def _rotate_if_needed(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size >= MAX_BYTES:
            rotated = _rotated_path()
            if rotated.exists():
                rotated.unlink()
            path.replace(rotated)
    except OSError:
        # Best-effort — if the FS refuses we just keep appending.
        pass


def log_event(
    source: str,
    level: str,
    code: str,
    message: str,
    context: dict | None = None,
) -> None:
    """Append a single structured event.  Never raises.

    Parameters
    ----------
    source : str
        Logical source — typically the module/client name ("finnhub",
        "polygon", "cache.read", etc.).
    level : str
        ``info`` / ``warning`` / ``error`` / ``critical``.  Anything else
        is normalised to ``error``.
    code : str
        Machine-friendly short tag for filtering.  Examples: ``rate_limited``,
        ``corrupt_cache``, ``http_500``, ``json_decode``.
    message : str
        Human-readable description.  Will be redacted before write.
    context : dict | None
        Free-form structured fields (ticker, http status, duration_ms, etc.).
        Will be redacted before write.
    """
    try:
        record = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "source": str(source or "unknown"),
            "level": level.lower() if level and level.lower() in _VALID_LEVELS else "error",
            "code": str(code or ""),
            "message": _redact(str(message or "")),
            "context": _redact(context or {}),
        }
        line = json.dumps(record, default=str, ensure_ascii=False)
    except Exception:
        # If even building the record failed, drop it silently — observability
        # must never break the caller.
        return

    with _write_lock:
        try:
            path = _log_path()
            _rotate_if_needed(path)
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
                f.write("\n")
        except OSError:
            # Disk full / permission denied / etc.  Silent — same rationale.
            return


# ── Readers ─────────────────────────────────────────────────────────────────


def _iter_recent(limit: int = TAIL_LINES) -> list[dict[str, Any]]:
    """Return up to ``limit`` of the most-recent records, newest first.

    Reads the active file plus rotated file when needed.  Skips lines that
    can't be parsed — never raises.
    """
    out: list[dict[str, Any]] = []
    for path in (_log_path(), _rotated_path()):
        if not path.exists():
            continue
        try:
            # Cheap-and-good: read whole file, parse, sort.  Capped by
            # TAIL_LINES anyway; we won't load gigabytes.
            with path.open("r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(record, dict):
                        out.append(record)
        except OSError:
            continue
        if len(out) >= limit:
            break
    # Newest first
    out.sort(key=lambda r: r.get("ts", ""), reverse=True)
    return out[:limit]


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # We always emit Z; tolerate either trailing.
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def recent_errors(limit: int = 50, *, source: str | None = None) -> list[dict[str, Any]]:
    """Return the most recent error-level events, optionally filtered by source."""
    out = []
    for record in _iter_recent(TAIL_LINES):
        if record.get("level") not in {"error", "critical", "warning"}:
            continue
        if source and record.get("source") != source:
            continue
        out.append(record)
        if len(out) >= limit:
            break
    return out


def success_rate(source: str, *, hours: int = 24) -> float | None:
    """Fraction of events in the last ``hours`` that were not errors.

    Returns ``None`` when there's no data for the source — the Diagnostics tab
    renders that as "no recent traffic" instead of a misleading 1.0.
    """
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    total = 0
    ok = 0
    for record in _iter_recent(TAIL_LINES):
        if record.get("source") != source:
            continue
        ts = _parse_ts(record.get("ts"))
        if ts is None or ts < cutoff:
            continue
        total += 1
        if record.get("level") in {"info", "debug"}:
            ok += 1
    return (ok / total) if total else None


def source_summary(*, hours: int = 24) -> dict[str, Any]:
    """One pass over the log to produce the full Diagnostics-tab payload.

    Returns:
      {
        "window_hours": int,
        "sources": {
            "finnhub": {"total": 42, "errors": 3, "success_rate": 0.93,
                        "last_error": {ts, code, message}, "codes": {"rate_limited": 2}},
            ...
        },
        "recent_errors": [...up to 50 newest...],
        "total_events": int,
        "log_path": str,
        "rotated_path": str | None,
      }
    """
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    sources: dict[str, dict[str, Any]] = defaultdict(lambda: {"total": 0, "errors": 0, "last_error": None, "codes": defaultdict(int)})
    recent = []
    total = 0
    for record in _iter_recent(TAIL_LINES):
        ts = _parse_ts(record.get("ts"))
        if ts is None or ts < cutoff:
            continue
        total += 1
        source = record.get("source") or "unknown"
        bucket = sources[source]
        bucket["total"] += 1
        bucket["codes"][record.get("code") or "_"] += 1
        if record.get("level") in {"error", "critical", "warning"}:
            bucket["errors"] += 1
            if bucket["last_error"] is None:
                bucket["last_error"] = {
                    "ts": record.get("ts"),
                    "code": record.get("code"),
                    "message": record.get("message"),
                }
            if len(recent) < 50:
                recent.append(record)
    out_sources: dict[str, dict[str, Any]] = {}
    for source, bucket in sources.items():
        total_for_source = bucket["total"]
        errors_for_source = bucket["errors"]
        rate = (total_for_source - errors_for_source) / total_for_source if total_for_source else None
        out_sources[source] = {
            "total": total_for_source,
            "errors": errors_for_source,
            "success_rate": rate,
            "last_error": bucket["last_error"],
            "codes": dict(bucket["codes"]),
        }
    return {
        "window_hours": hours,
        "sources": out_sources,
        "recent_errors": recent[:50],
        "total_events": total,
        "log_path": str(_log_path()),
        "rotated_path": str(_rotated_path()) if _rotated_path().exists() else None,
    }


def support_bundle(*, limit: int = 500) -> str:
    """Return a redacted, sorted (newest-first) jsonl tail for copy-paste support.

    Useful for the "Copy support bundle" button in the Diagnostics tab — the
    user can paste it into an issue without worrying about leaking secrets.
    """
    events = _iter_recent(limit)
    return "\n".join(json.dumps(event, ensure_ascii=False) for event in events)


def clear_diagnostics() -> None:
    """Delete both the active and rotated logs.  Used by tests."""
    for path in (_log_path(), _rotated_path()):
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


# Optional: also mirror to stderr when an env var is set — useful for dev.
def _maybe_echo_stderr(record_line: str) -> None:  # pragma: no cover
    if os.environ.get("TECH_STOCK_OBSERVABILITY_ECHO") == "1":
        import sys

        sys.stderr.write(record_line + "\n")


__all__ = [
    "log_event",
    "recent_errors",
    "success_rate",
    "source_summary",
    "support_bundle",
    "clear_diagnostics",
    "MAX_BYTES",
]
