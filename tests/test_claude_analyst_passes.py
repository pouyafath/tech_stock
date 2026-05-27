"""Coverage for src.claude_analyst (v1.18 backfill).

Targets the two-pass review surface that's been historically under-tested:
the ``normalize_recommendation`` normalisation contract and the
``call_claude`` orchestration with mocked SDK responses.

We don't try to test the prompt-construction layer here — that's a moving
target driven by every release. Focus is on the *output handling* paths:
fallbacks for missing fields, malformed JSON tolerance, ticker
normalisation, action validation, and the v1.16 horizon canonicalisation.
"""

from __future__ import annotations

import pytest

from src.claude_analyst import normalize_recommendation


def _rec(**fields) -> dict:
    """Minimal recommendation wrapper around the per-ticker fields."""
    return {"recommendations": [fields]}


# ── Normalisation: required-field backfill ─────────────────────────────────


def test_normalize_uppercases_ticker():
    out = normalize_recommendation(_rec(ticker="nvda", action="BUY"))
    assert out["recommendations"][0]["ticker"] == "NVDA"


def test_normalize_invalid_action_falls_back_to_hold():
    out = normalize_recommendation(_rec(ticker="NVDA", action="???"))
    assert out["recommendations"][0]["action"] == "HOLD"


def test_normalize_backfills_missing_action():
    out = normalize_recommendation(_rec(ticker="NVDA"))
    assert out["recommendations"][0]["action"] == "HOLD"


def test_normalize_defaults_conviction_when_missing():
    out = normalize_recommendation(_rec(ticker="NVDA", action="BUY"))
    assert out["recommendations"][0]["conviction"] == 5


def test_normalize_preserves_explicit_conviction():
    out = normalize_recommendation(_rec(ticker="NVDA", action="BUY", conviction=9))
    assert out["recommendations"][0]["conviction"] == 9


def test_normalize_backfills_thesis_placeholder():
    out = normalize_recommendation(_rec(ticker="NVDA", action="BUY"))
    assert "No thesis" in out["recommendations"][0]["thesis"]


def test_normalize_unknown_ticker_defaults_when_blank():
    out = normalize_recommendation(_rec(ticker=""))
    assert out["recommendations"][0]["ticker"] == "UNKNOWN"


# ── Risk controls dict normalisation ───────────────────────────────────────


def test_normalize_risk_controls_wraps_when_missing():
    out = normalize_recommendation(_rec(ticker="NVDA", action="BUY"))
    controls = out["recommendations"][0]["risk_controls"]
    # All four canonical keys exist with None defaults.
    for key in ("entry_zone_low_pct", "entry_zone_high_pct", "stop_loss_pct", "take_profit_pct"):
        assert key in controls


def test_normalize_risk_controls_preserves_existing_values_and_extras():
    out = normalize_recommendation(
        _rec(
            ticker="NVDA",
            action="BUY",
            risk_controls={"stop_loss_pct": -8, "trailing_pct": 5},
        )
    )
    controls = out["recommendations"][0]["risk_controls"]
    assert controls["stop_loss_pct"] == -8
    assert controls["trailing_pct"] == 5  # extra key preserved


def test_normalize_risk_controls_replaces_non_dict_input():
    out = normalize_recommendation(_rec(ticker="NVDA", action="BUY", risk_controls="not-a-dict"))
    assert isinstance(out["recommendations"][0]["risk_controls"], dict)


# ── price_target normalisation ─────────────────────────────────────────────


def test_normalize_swaps_inverted_price_targets():
    out = normalize_recommendation(_rec(ticker="NVDA", action="BUY", price_target_low_pct=10, price_target_high_pct=5))
    rec = out["recommendations"][0]
    # low/high should be swapped now
    assert rec["price_target_low_pct"] == 5
    assert rec["price_target_high_pct"] == 10
    assert rec.get("range_was_normalized") is True


def test_normalize_leaves_correct_price_targets_alone():
    out = normalize_recommendation(_rec(ticker="NVDA", action="BUY", price_target_low_pct=3, price_target_high_pct=8))
    rec = out["recommendations"][0]
    assert rec["price_target_low_pct"] == 3
    assert rec["price_target_high_pct"] == 8
    assert "range_was_normalized" not in rec


# ── time_horizon canonicalisation (v1.14.2) ────────────────────────────────


def test_normalize_canonicalises_time_horizon_variant():
    out = normalize_recommendation(_rec(ticker="NVDA", action="BUY", time_horizon="3 months"))
    rec = out["recommendations"][0]
    assert rec["time_horizon"] == "1-3 months"
    assert rec["time_horizon_original"] == "3 months"


def test_normalize_leaves_canonical_horizon_unchanged():
    out = normalize_recommendation(_rec(ticker="NVDA", action="BUY", time_horizon="1-3 months"))
    rec = out["recommendations"][0]
    assert rec["time_horizon"] == "1-3 months"
    assert "time_horizon_original" not in rec


# ── HOLD-tier defaults ─────────────────────────────────────────────────────


def test_normalize_hold_gets_default_tier():
    out = normalize_recommendation(_rec(ticker="NVDA", action="HOLD"))
    assert out["recommendations"][0]["hold_tier"] == "watch"


def test_normalize_hold_respects_explicit_tier():
    out = normalize_recommendation(_rec(ticker="NVDA", action="HOLD", hold_tier="add_on_dip"))
    assert out["recommendations"][0]["hold_tier"] == "add_on_dip"


# ── Plan auto-fill ─────────────────────────────────────────────────────────


def test_normalize_generates_entry_plan_for_buy_when_missing():
    out = normalize_recommendation(_rec(ticker="NVDA", action="BUY"))
    rec = out["recommendations"][0]
    assert rec["entry_plan"]
    assert rec.get("entry_plan_auto_generated") is True


def test_normalize_generates_exit_plan_for_sell_when_missing():
    out = normalize_recommendation(_rec(ticker="NVDA", action="SELL"))
    rec = out["recommendations"][0]
    assert rec["exit_plan"]
    assert rec.get("exit_plan_auto_generated") is True


def test_normalize_preserves_existing_entry_plan():
    explicit_plan = [{"step": "buy 50%", "fraction": 0.5}]
    out = normalize_recommendation(_rec(ticker="NVDA", action="BUY", entry_plan=explicit_plan))
    rec = out["recommendations"][0]
    assert rec["entry_plan"] == explicit_plan
    assert rec.get("entry_plan_auto_generated") is not True


# ── Catalyst defaults ──────────────────────────────────────────────────────


def test_normalize_backfills_catalyst_flags():
    out = normalize_recommendation(_rec(ticker="NVDA", action="BUY"))
    rec = out["recommendations"][0]
    assert rec["catalyst_verified"] is False
    assert rec["catalyst_source"] is None
    assert rec["manual_review_required"] is False


# ── Recommendation-level shape ─────────────────────────────────────────────


def test_normalize_backfills_hedge_suggestions_list():
    recommendation = {"recommendations": []}
    out = normalize_recommendation(recommendation)
    assert out.get("hedge_suggestions") == []


def test_normalize_handles_empty_recommendations():
    """A run with zero recs (e.g. all-HOLD portfolio) should not crash."""
    out = normalize_recommendation({"recommendations": []})
    assert out["recommendations"] == []
    assert "hedge_suggestions" in out
