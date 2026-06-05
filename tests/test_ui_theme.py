"""Tests for the shared UI theme + component helpers (src.ui_theme).

Covers the small but critical surface used by every front-end:
* action / severity / readiness lookups never raise on unknown input
* HTML helpers escape user-supplied content (XSS guard)
* badges, cards, and the empty-state placeholder render the expected
  CSS class hooks so the Streamlit CSS bundle can style them
"""

from __future__ import annotations

import pytest

from src.ui_theme import (
    ACTION_META,
    PALETTE,
    READINESS_META,
    SEVERITY_META,
    STREAMLIT_CSS,
    VERDICT_META,
    action_badge,
    action_card,
    action_meta,
    badge,
    conviction_bar,
    empty_state,
    hero,
    metric_card,
    readiness_badge,
    readiness_meta,
    severity_badge,
    severity_meta,
    status_dot,
    verdict_badge,
    verdict_meta,
    warning_row,
)

# ── Lookup safety ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("action", ["BUY", "ADD", "HOLD", "TRIM", "SELL", "NONE"])
def test_action_meta_returns_color_and_emoji(action):
    meta = action_meta(action)
    assert "color" in meta and meta["color"].startswith("#") or meta["color"].startswith("rgb")
    assert "emoji" in meta and meta["emoji"]


def test_action_meta_unknown_falls_back_to_none():
    assert action_meta("xyz") == ACTION_META["NONE"]
    assert action_meta(None) == ACTION_META["NONE"]


@pytest.mark.parametrize("severity", ["critical", "high", "medium", "low", "info"])
def test_severity_meta_returns_color(severity):
    assert "color" in severity_meta(severity)


def test_severity_meta_unknown_falls_back_to_info():
    assert severity_meta("nonsense") == SEVERITY_META["info"]
    assert severity_meta(None) == SEVERITY_META["info"]


@pytest.mark.parametrize("readiness", ["TRADE_READY", "REVIEW_FIRST", "BLOCKED"])
def test_readiness_meta_returns_label(readiness):
    meta = readiness_meta(readiness)
    assert "label" in meta
    assert "color" in meta


def test_readiness_meta_unknown_returns_passthrough_label():
    meta = readiness_meta("custom_state")
    assert meta["label"] == "custom_state"


# ── HTML escaping (XSS guard) ──────────────────────────────────────────────


def test_badge_escapes_html_in_text():
    out = badge("<script>alert('x')</script>", color="#fff")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_action_card_escapes_rationale():
    rationale = "Sell <b>NOW</b> & exit"
    out = action_card("AAPL", "SELL", rationale)
    assert "<b>NOW</b>" not in out
    assert "&lt;b&gt;NOW&lt;/b&gt;" in out
    assert "&amp;" in out  # & must be escaped


def test_action_card_escapes_ticker():
    out = action_card("<img src=x>", "BUY", "ok")
    assert "<img src=x>" not in out
    assert "&lt;img" in out


def test_empty_state_escapes_both_fields():
    out = empty_state("<h1>", "<svg onload=x>")
    assert "<h1>" not in out
    assert "<svg" not in out
    assert "&lt;h1&gt;" in out


def test_hero_escapes_meta_parts():
    out = hero("Title", "Sub", meta=["safe", "<script>bad</script>"])
    assert "<script>bad</script>" not in out
    assert "&lt;script&gt;bad&lt;/script&gt;" in out


def test_warning_row_escapes_message():
    out = warning_row("high", "AAPL", "<svg onload=alert(1)>")
    assert "<svg onload" not in out
    assert "&lt;svg" in out


def test_metric_card_escapes_all_fields():
    out = metric_card("<x>", "<y>", hint="<z>")
    for ch in ["<x>", "<y>", "<z>"]:
        assert ch not in out


# ── Component output shape ─────────────────────────────────────────────────


def test_action_badge_has_css_hook_and_color():
    out = action_badge("BUY")
    assert "ts-badge" in out
    assert PALETTE.accent in out
    assert "BUY" in out
    assert "🟢" in out


def test_action_badge_without_emoji_omits_it():
    out = action_badge("BUY", with_emoji=False)
    assert "🟢" not in out
    assert "BUY" in out


def test_severity_badge_uses_severity_color():
    high = severity_badge("high")
    assert PALETTE.danger in high
    low = severity_badge("low")
    assert PALETTE.info in low


def test_readiness_badge_returns_known_label():
    out = readiness_badge("TRADE_READY")
    assert "Trade Ready" in out
    assert PALETTE.accent in out


def test_conviction_bar_clamps_to_range():
    # below 0 → 0 ; above 10 → 10
    low = conviction_bar(-5)
    high = conviction_bar(99)
    assert "0%" in low
    assert "100%" in high


@pytest.mark.parametrize(
    "score,expected_color",
    [(8.0, PALETTE.accent), (5.0, PALETTE.warn), (2.0, PALETTE.neutral)],
)
def test_conviction_bar_color_thresholds(score, expected_color):
    out = conviction_bar(score)
    assert expected_color in out


def test_conviction_bar_handles_none_and_invalid():
    assert "0%" in conviction_bar(None)
    assert "0%" in conviction_bar("not_a_number")


def test_status_dot_renders_three_states():
    assert "background:" in status_dot(True)
    assert PALETTE.accent in status_dot(True)
    assert PALETTE.danger in status_dot(False)
    assert PALETTE.subtle in status_dot(None)


def test_action_card_carries_action_class():
    sell = action_card("XYZ", "SELL", "exit")
    buy = action_card("ABC", "BUY", "enter")
    assert "is-sell" in sell
    # BUY has no special class because base style is BUY
    assert "ts-action-card" in buy


def test_warning_row_severity_classes():
    assert "is-critical" in warning_row("critical", "X", "msg")
    assert "is-critical" in warning_row("high", "X", "msg")
    assert "is-low" in warning_row("low", "X", "msg")


def test_streamlit_css_bundle_includes_palette_variables():
    """Spot-check the CSS bundle for our brand colour and a few class hooks."""
    css = STREAMLIT_CSS
    assert PALETTE.accent in css
    assert PALETTE.danger in css
    assert ".ts-badge" in css
    assert ".ts-action-card" in css
    assert ".ts-warning-row" in css
    assert ".ts-conviction" in css
    assert ".ts-empty" in css
    assert ".ts-hero" in css


def test_action_meta_handles_lowercase_input():
    # tolerate lowercase / mixed-case
    assert action_meta("buy") == ACTION_META["BUY"]
    assert action_meta("Buy") == ACTION_META["BUY"]


def test_readiness_meta_handles_label_passthrough():
    # Calling with the display label (not code) should also resolve
    assert readiness_meta("BLOCKED") == READINESS_META["BLOCKED"]


def test_hero_handles_empty_meta():
    out = hero("Title")
    assert "Title" in out
    assert "ts-hero-meta" not in out


# ── v1.16 verdict_badge ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "verdict,expected_color",
    [
        ("materialized", PALETTE.accent),
        ("partial", PALETTE.warn),
        ("not_yet", PALETTE.neutral),
        ("invalidated", PALETTE.danger),
    ],
)
def test_verdict_badge_uses_palette_color(verdict, expected_color):
    out = verdict_badge(verdict)
    assert expected_color in out


def test_verdict_meta_falls_back_for_unknown_input():
    meta = verdict_meta("never-heard-of-it")
    assert "color" in meta
    assert "label" in meta
    # Falls back to neutral subtle colour rather than raising
    assert meta["label"] == "never-heard-of-it"


def test_verdict_badge_handles_none():
    out = verdict_badge(None)
    # Should still produce a well-formed pill, not raise
    assert "ts-badge" in out
    assert "Unknown" in out


def test_verdict_badge_escapes_html_in_label():
    out = verdict_badge("<script>alert(1)</script>")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_verdict_meta_dictionary_is_complete():
    """All four canonical verdicts the tracker emits must have entries."""
    for verdict in ("materialized", "partial", "not_yet", "invalidated"):
        assert verdict in VERDICT_META
        meta = VERDICT_META[verdict]
        for key in ("color", "bg", "emoji", "label"):
            assert key in meta
