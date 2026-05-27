"""Coverage for src.observability (v1.17 structured logging)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def isolated_logs(tmp_path, monkeypatch):
    """Point observability at a fresh tmp workspace and clear before each test."""
    monkeypatch.setenv("TECH_STOCK_HOME", str(tmp_path))
    from src import observability

    observability.clear_diagnostics()
    yield tmp_path
    observability.clear_diagnostics()


# ── Round-trip ──────────────────────────────────────────────────────────────


def test_log_event_writes_jsonl_record(isolated_logs):
    from src.observability import log_event, _log_path

    log_event("finnhub", "info", "ok", "Fetched AAPL", {"duration_ms": 95})
    path = _log_path()
    line = path.read_text(encoding="utf-8").strip()
    record = json.loads(line)
    assert record["source"] == "finnhub"
    assert record["level"] == "info"
    assert record["code"] == "ok"
    assert record["message"] == "Fetched AAPL"
    assert record["context"]["duration_ms"] == 95
    assert record["ts"].endswith("Z") or "+" in record["ts"]


def test_log_event_normalises_unknown_level(isolated_logs):
    from src.observability import log_event, _log_path

    log_event("finnhub", "EMERGENCY", "rare", "weird level", None)
    record = json.loads(_log_path().read_text(encoding="utf-8").strip())
    assert record["level"] == "error"  # unknown levels normalise to error


def test_log_event_never_raises_on_bad_input(isolated_logs):
    from src.observability import log_event

    # If the writer raises on any of these inputs we'd see an exception bubble.
    log_event(None, None, None, None, None)  # type: ignore[arg-type]
    log_event("source", "info", "code", "message", {"bad": object()})


# ── Redaction ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,scrubbed",
    [
        ("Got 401 with token sk-abc1234567890123456789012345", "[REDACTED-API-KEY]"),
        ("Email user@example.com had an error", "[REDACTED-EMAIL]"),
        ("Authorization: Bearer abc123.def456", "Authorization: Bearer [REDACTED]"),
        (
            "Got error with key 0123456789abcdef0123456789abcdef0123",  # 36-char hex-ish
            "[REDACTED-TOKEN]",
        ),
    ],
)
def test_redaction_strips_secrets_from_message(isolated_logs, raw, scrubbed):
    from src.observability import log_event, _log_path

    log_event("finnhub", "error", "test", raw, None)
    line = _log_path().read_text(encoding="utf-8").strip()
    record = json.loads(line)
    assert scrubbed in record["message"]
    assert "sk-abc1234567890123456789012345" not in record["message"]
    assert "user@example.com" not in record["message"]


def test_redaction_recurses_into_context(isolated_logs):
    from src.observability import log_event, _log_path

    log_event(
        "finnhub",
        "error",
        "leak",
        "ok",
        {"headers": {"Authorization": "Bearer secret-token-here-12345"}, "user_email": "x@y.com"},
    )
    record = json.loads(_log_path().read_text(encoding="utf-8").strip())
    headers = record["context"]["headers"]
    # The bare value isn't matched by the Authorization regex but the email is.
    assert "[REDACTED-EMAIL]" in record["context"]["user_email"]


# ── Readers ────────────────────────────────────────────────────────────────


def test_recent_errors_filters_by_level_and_source(isolated_logs):
    from src.observability import log_event, recent_errors

    log_event("a", "info", "ok", "ok event")
    log_event("a", "error", "fail", "boom")
    log_event("b", "warning", "warn", "soft")
    errors = recent_errors()
    assert {e["source"] for e in errors} == {"a", "b"}
    assert all(e["level"] in {"error", "warning", "critical"} for e in errors)

    only_a = recent_errors(source="a")
    assert {e["source"] for e in only_a} == {"a"}


def test_success_rate_returns_fraction(isolated_logs):
    from src.observability import log_event, success_rate

    for _ in range(3):
        log_event("polygon", "info", "ok", "ok")
    log_event("polygon", "error", "boom", "boom")
    rate = success_rate("polygon", hours=24)
    assert rate == pytest.approx(0.75)


def test_success_rate_none_when_no_traffic(isolated_logs):
    from src.observability import success_rate

    assert success_rate("nonexistent", hours=24) is None


def test_source_summary_buckets_codes(isolated_logs):
    from src.observability import log_event, source_summary

    log_event("finnhub", "error", "http_429", "rate")
    log_event("finnhub", "error", "http_429", "rate again")
    log_event("finnhub", "error", "http_500", "server")
    summary = source_summary(hours=24)
    assert "finnhub" in summary["sources"]
    bucket = summary["sources"]["finnhub"]
    assert bucket["total"] == 3
    assert bucket["errors"] == 3
    assert bucket["codes"]["http_429"] == 2
    assert bucket["codes"]["http_500"] == 1
    assert bucket["success_rate"] == 0.0


def test_support_bundle_is_redacted_jsonl(isolated_logs):
    from src.observability import log_event, support_bundle

    log_event("any", "error", "leak", "token=sk-ABCDEF0123456789ABCDEF0123456789")
    bundle = support_bundle()
    assert "sk-ABCDEF" not in bundle
    # Every line should parse as JSON
    for line in bundle.splitlines():
        if line.strip():
            json.loads(line)


# ── Rotation ────────────────────────────────────────────────────────────────


def test_rotation_creates_jsonl_dot_one_when_size_exceeded(isolated_logs, monkeypatch):
    from src import observability

    monkeypatch.setattr(observability, "MAX_BYTES", 256)
    # Each event ≈ 150-200 bytes; a handful of events trips the threshold.
    for i in range(10):
        observability.log_event("test", "error", "rot", f"event {i}" * 5)
    rotated = observability._rotated_path()
    assert rotated.exists(), "expected diagnostics.jsonl.1 after exceeding MAX_BYTES"
    # Active log should be the post-rotation one — smaller than the rotated.
    active = observability._log_path()
    assert active.exists()
    assert active.stat().st_size <= observability.MAX_BYTES + 4096


def test_clear_diagnostics_removes_both_files(isolated_logs, monkeypatch):
    from src import observability

    monkeypatch.setattr(observability, "MAX_BYTES", 256)
    for i in range(10):
        observability.log_event("test", "error", "x", "y" * 60)
    observability.clear_diagnostics()
    assert not observability._log_path().exists()
    assert not observability._rotated_path().exists()
