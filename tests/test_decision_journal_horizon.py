"""Coverage for v1.16 by_horizon block on decision_journal.summarize_outcomes."""

from __future__ import annotations

import pytest

from src.decision_journal import summarize_outcomes


def _outcome(horizon: int, *, user_avg: float = 1.0, model_avg: float = 0.5, hit_user: bool = True, hit_model: bool = True) -> dict:
    """Build a single outcome row with just the fields summarize_outcomes reads."""
    return {
        "id": f"id-{horizon}-{user_avg}",
        "horizon_days": horizon,
        "recommended_action": "BUY",
        "user_decision": "executed",
        "actual_action": "BUY",
        "model_action_return_pct": model_avg,
        "user_action_return_pct": user_avg,
        "decision_delta_pct": user_avg - model_avg,
        "model_hit": hit_model,
        "user_hit": hit_user,
    }


def test_by_horizon_groups_outcomes_by_horizon_days():
    outcomes = [
        _outcome(1, user_avg=0.5, model_avg=0.3),
        _outcome(5, user_avg=1.2, model_avg=0.6),
        _outcome(5, user_avg=2.0, model_avg=1.0),
        _outcome(20, user_avg=3.1, model_avg=2.0),
        _outcome(60, user_avg=-0.5, model_avg=1.5),
    ]
    summary = summarize_outcomes(outcomes, status={"recorded": 5})
    by_horizon = summary["by_horizon"]
    assert sorted(by_horizon.keys()) == [1, 5, 20, 60]
    assert by_horizon[5]["n"] == 2
    # 5-day average = (1.2 + 2.0) / 2 = 1.6
    assert by_horizon[5]["user_avg_return_pct"] == pytest.approx(1.6, rel=0.01)


def test_by_horizon_is_empty_when_no_outcomes():
    summary = summarize_outcomes([], status={"recorded": 0})
    assert summary["by_horizon"] == {}


def test_by_horizon_handles_single_horizon():
    outcomes = [_outcome(20, user_avg=2.0), _outcome(20, user_avg=4.0)]
    summary = summarize_outcomes(outcomes, status={"recorded": 2})
    assert list(summary["by_horizon"].keys()) == [20]
    assert summary["by_horizon"][20]["n"] == 2


def test_by_horizon_carries_all_bucket_stat_fields():
    summary = summarize_outcomes([_outcome(5)], status={"recorded": 1})
    bucket = summary["by_horizon"][5]
    for key in (
        "n",
        "model_avg_return_pct",
        "user_avg_return_pct",
        "avg_decision_delta_pct",
        "model_hit_rate",
        "user_hit_rate",
    ):
        assert key in bucket, f"missing key in by_horizon bucket: {key}"


def test_existing_keys_unchanged_after_additive_field():
    """Regression guard — pre-v1.16 consumers must still see the same keys."""
    summary = summarize_outcomes([_outcome(5)], status={"recorded": 1})
    for key in (
        "journal",
        "n_scored_windows",
        "n_scored_decisions",
        "overall",
        "by_user_decision",
        "by_recommended_action",
        "best_user_overrides",
        "worst_user_overrides",
        "missed_model_winners",
    ):
        assert key in summary, f"v1.15 key disappeared from summary: {key}"


def test_by_horizon_hit_rates_are_fractions():
    outcomes = [
        _outcome(20, user_avg=1.0, hit_user=True, hit_model=True),
        _outcome(20, user_avg=-1.0, hit_user=False, hit_model=False),
        _outcome(20, user_avg=1.0, hit_user=True, hit_model=False),
    ]
    summary = summarize_outcomes(outcomes, status={"recorded": 3})
    bucket = summary["by_horizon"][20]
    assert 0.0 <= bucket["user_hit_rate"] <= 1.0
    assert 0.0 <= bucket["model_hit_rate"] <= 1.0
    assert bucket["user_hit_rate"] == pytest.approx(2 / 3, rel=0.01)


def test_by_horizon_handles_unknown_horizon_zero_value():
    """Outcomes with missing/zero horizon_days are skipped, not crashed on."""
    outcomes = [
        _outcome(5),
        # Bad row — horizon_days missing entirely.
        {
            **_outcome(5),
            "horizon_days": None,
        },
    ]
    summary = summarize_outcomes(outcomes, status={"recorded": 2})
    assert 5 in summary["by_horizon"]
    # None / 0 horizon must not pollute the keyspace.
    assert 0 not in summary["by_horizon"]
    assert None not in summary["by_horizon"]


def test_empty_outcomes_includes_by_horizon_key():
    summary = summarize_outcomes([], status={"recorded": 0})
    assert "by_horizon" in summary
