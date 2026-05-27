"""Coverage for the Diagnostics-tab data layer (v1.17)."""

from __future__ import annotations

import pytest


@pytest.fixture
def isolated_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("TECH_STOCK_HOME", str(tmp_path))
    from src import observability

    observability.clear_diagnostics()
    yield tmp_path
    observability.clear_diagnostics()


def test_diagnostics_view_shape(isolated_workspace):
    from src.observability import log_event
    from src.ui_support import diagnostics_view

    log_event("finnhub", "info", "ok", "fine")
    log_event("finnhub", "error", "http_500", "boom")
    log_event("polygon", "info", "ok", "fine")

    view = diagnostics_view(hours=24)
    assert set(view.keys()) >= {"sources", "recent_errors", "total_events", "log_path"}
    assert set(view["sources"].keys()) == {"finnhub", "polygon"}
    for bucket in view["sources"].values():
        for key in ("total", "errors", "success_rate", "last_error", "codes", "health"):
            assert key in bucket


def test_diagnostics_view_health_thresholds(isolated_workspace):
    from src.observability import log_event
    from src.ui_support import diagnostics_view

    # Three sources, three health verdicts:
    #  ok       : 100% success
    #  degraded : 60% success
    #  down     : 0% success
    for _ in range(5):
        log_event("ok_source", "info", "ok", "fine")
    log_event("degraded_source", "info", "ok", "fine")
    log_event("degraded_source", "info", "ok", "fine")
    log_event("degraded_source", "info", "ok", "fine")
    log_event("degraded_source", "error", "boom", "bad")
    log_event("degraded_source", "error", "boom", "bad")
    for _ in range(3):
        log_event("down_source", "error", "boom", "bad")

    view = diagnostics_view(hours=24)
    assert view["sources"]["ok_source"]["health"] == "ok"
    assert view["sources"]["degraded_source"]["health"] == "degraded"
    assert view["sources"]["down_source"]["health"] == "down"


def test_degradation_health_returns_label_when_unhealthy(isolated_workspace):
    from src.observability import log_event
    from src.ui_support import degradation_health

    for _ in range(3):
        log_event("polygon", "error", "boom", "bad")
    assert degradation_health("polygon") == "down"


def test_degradation_health_returns_none_when_healthy(isolated_workspace):
    from src.observability import log_event
    from src.ui_support import degradation_health

    for _ in range(5):
        log_event("polygon", "info", "ok", "fine")
    assert degradation_health("polygon") is None


def test_degradation_health_returns_none_when_no_traffic(isolated_workspace):
    from src.ui_support import degradation_health

    assert degradation_health("nonexistent") is None


def test_support_bundle_is_redacted(isolated_workspace):
    from src.observability import log_event
    from src.ui_support import diagnostics_support_bundle

    log_event("finnhub", "error", "leak", "token=sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123")
    bundle = diagnostics_support_bundle(limit=10)
    assert "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123" not in bundle
    assert "[REDACTED" in bundle


# ── ui_theme health pill helpers ────────────────────────────────────────


def test_health_badge_carries_palette_color():
    from src.ui_theme import PALETTE, health_badge

    assert PALETTE.accent in health_badge("ok")
    assert PALETTE.warn in health_badge("degraded")
    assert PALETTE.danger in health_badge("down")
    assert PALETTE.subtle in health_badge("idle")


def test_degradation_pill_empty_when_ok():
    from src.ui_theme import degradation_pill

    assert degradation_pill("finnhub", "ok") == ""
    assert degradation_pill("finnhub", None) == ""


def test_degradation_pill_includes_source_and_label():
    from src.ui_theme import degradation_pill

    pill = degradation_pill("polygon", "degraded")
    assert "polygon" in pill
    assert "degraded" in pill
    assert "ts-badge" in pill


def test_degradation_pill_escapes_source_name():
    from src.ui_theme import degradation_pill

    pill = degradation_pill("<script>", "down")
    assert "<script>" not in pill
    assert "&lt;script&gt;" in pill
