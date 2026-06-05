"""Coverage for v1.16 thesis-text drift detection in drift_tracker."""

from __future__ import annotations

import pytest

from src.drift_tracker import (
    _is_thesis_text_drift,
    _thesis_text_similarity,
    _thesis_tokens,
    compute_drift,
)

# ── _thesis_text_similarity / Jaccard fallback ────────────────────────────


def test_identical_strings_have_similarity_one():
    text = "AI tailwind drives FY26 revenue acceleration powered by data-center demand"
    assert _thesis_text_similarity(text, text) == pytest.approx(1.0)


def test_paraphrase_above_drift_threshold():
    a = "AI tailwind drives FY26 revenue acceleration powered by data-center demand"
    b = "FY26 revenue acceleration driven by AI tailwind and data-center demand"
    assert _thesis_text_similarity(a, b) >= 0.55


def test_wholesale_rewrite_below_drift_threshold():
    a = "AI tailwind drives FY26 revenue acceleration powered by data-center demand"
    b = "Activist investor stake disclosure triggers merger speculation"
    assert _thesis_text_similarity(a, b) < 0.55


def test_short_thesis_returns_neutral_similarity_to_avoid_noise():
    """Token-count under the minimum threshold → treat as identical, not drift."""
    assert _thesis_text_similarity("Buy now", "Buy then") == 1.0


def test_empty_or_none_thesis_returns_zero():
    assert _thesis_text_similarity(None, "anything substantive") == 0.0
    assert _thesis_text_similarity("anything substantive", "") == 0.0


def test_thesis_tokens_filters_stopwords_and_punctuation():
    tokens = _thesis_tokens("The AI tailwind drives FY26 revenue.")
    # 'the' is a stop-word and the period must be stripped.
    assert "the" not in tokens
    assert "ai" in tokens
    assert "revenue" in tokens


# ── _is_thesis_text_drift gate ────────────────────────────────────────────


def test_drift_only_fires_when_action_steady():
    was = {"action": "BUY", "thesis": "AI tailwind drives FY26 revenue acceleration"}
    now = {"action": "SELL", "thesis": "Wholesale unrelated rationale about M&A speculation"}
    # Action changed → other handler (action_flip) owns it; no text drift here.
    is_drift, _ = _is_thesis_text_drift(was, now)
    assert is_drift is False


def test_drift_fires_when_action_same_but_thesis_rewritten():
    was = {"action": "BUY", "thesis": "AI tailwind drives FY26 revenue acceleration"}
    now = {"action": "BUY", "thesis": "Wholesale unrelated rationale about M&A speculation"}
    is_drift, sim = _is_thesis_text_drift(was, now)
    assert is_drift is True
    assert sim < 0.55


def test_drift_silent_for_paraphrase():
    was = {
        "action": "BUY",
        "thesis": "AI tailwind drives FY26 revenue acceleration powered by data-center demand",
    }
    now = {
        "action": "BUY",
        "thesis": "FY26 revenue acceleration driven by AI tailwind and data-center demand",
    }
    is_drift, sim = _is_thesis_text_drift(was, now)
    assert is_drift is False
    assert sim >= 0.55


# ── compute_drift integration ────────────────────────────────────────────


def _rec(ticker, action, conviction, thesis, net_expected_pct=2.0):
    return {
        "ticker": ticker,
        "action": action,
        "conviction": conviction,
        "thesis": thesis,
        "net_expected_pct": net_expected_pct,
    }


def test_compute_drift_emits_thesis_text_drift_event():
    previous = {"recommendations": [_rec("AAA", "BUY", 8, "AI tailwind drives FY26 revenue acceleration powered by data-center demand")]}
    current = {"recommendations": [_rec("AAA", "BUY", 8, "Activist investor stake disclosure triggers merger speculation surge")]}
    events = compute_drift(current, previous)
    text_events = [e for e in events if e["drift_type"] == "thesis_text_drift"]
    assert len(text_events) == 1
    event = text_events[0]
    assert event["ticker"] == "AAA"
    assert "similarity" in event
    assert event["similarity"] < 0.55
    assert event["was"]["thesis"]
    assert event["now"]["thesis"]


def test_compute_drift_skips_text_drift_when_action_flipped():
    previous = {"recommendations": [_rec("AAA", "BUY", 8, "AI tailwind drives FY26 revenue acceleration")]}
    current = {"recommendations": [_rec("AAA", "SELL", 8, "Wholesale unrelated rationale about M&A")]}
    events = compute_drift(current, previous)
    text_events = [e for e in events if e["drift_type"] == "thesis_text_drift"]
    assert text_events == []
    action_events = [e for e in events if e["drift_type"] == "action_flip"]
    assert len(action_events) == 1


def test_compute_drift_no_text_event_for_paraphrase():
    previous = {"recommendations": [_rec("AAA", "BUY", 8, "AI tailwind drives FY26 revenue acceleration powered by data-center demand")]}
    current = {"recommendations": [_rec("AAA", "BUY", 8, "FY26 revenue acceleration driven by AI tailwind and data-center demand")]}
    events = compute_drift(current, previous)
    assert all(e["drift_type"] != "thesis_text_drift" for e in events)
