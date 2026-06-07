"""Tests for the smaller P2 fixes: news cache key, drift tracker, tranches."""

import json
import os
from datetime import datetime, timedelta

from src.claude_analyst import (
    _default_entry_plan,
    _default_exit_plan,
    normalize_recommendation,
)
from src.drift_tracker import get_previous_session

# ── Tranched plans ──────────────────────────────────────────────────────


def test_default_entry_plan_sums_to_100pct():
    rec = {"risk_controls": {"entry_zone_low_pct": -3, "entry_zone_high_pct": 2, "stop_loss_pct": -7, "take_profit_pct": 15}}
    plan = _default_entry_plan(rec)
    assert len(plan) == 3
    assert abs(sum(t["fraction"] for t in plan) - 1.0) < 0.001
    triggers = [t["trigger"] for t in plan]
    assert "now" in triggers
    assert "pullback" in triggers
    assert "confirmation" in triggers


def test_default_entry_plan_uses_zone_when_provided():
    rec = {"risk_controls": {"entry_zone_low_pct": -4, "entry_zone_high_pct": 6}}
    plan = _default_entry_plan(rec)
    pullback = next(t for t in plan if t["trigger"] == "pullback")
    confirm = next(t for t in plan if t["trigger"] == "confirmation")
    assert pullback["price_pct"] == -2.0  # half of -4
    assert confirm["price_pct"] == 3.0  # half of 6


def test_default_entry_plan_uses_safe_defaults_when_no_zone():
    plan = _default_entry_plan({})
    pullback = next(t for t in plan if t["trigger"] == "pullback")
    assert pullback["price_pct"] == -3.0


def test_default_exit_plan_full_stop_at_stop_loss():
    rec = {"risk_controls": {"entry_zone_high_pct": 4, "stop_loss_pct": -8}}
    plan = _default_exit_plan(rec)
    assert len(plan) == 3
    stop = next(t for t in plan if t["trigger"] == "stop_loss")
    assert stop["price_pct"] == -8.0


def test_normalize_backfills_entry_plan_for_buy():
    rec = {
        "recommendations": [
            {
                "ticker": "MSFT",
                "action": "BUY",
                "conviction": 8,
                "risk_controls": {"entry_zone_low_pct": -3, "entry_zone_high_pct": 2, "stop_loss_pct": -7, "take_profit_pct": 15},
            },
        ]
    }
    out = normalize_recommendation(rec)
    plan = out["recommendations"][0]["entry_plan"]
    assert len(plan) == 3
    assert out["recommendations"][0]["entry_plan_auto_generated"] is True


def test_normalize_backfills_exit_plan_for_trim():
    rec = {
        "recommendations": [
            {"ticker": "PLTR", "action": "TRIM", "conviction": 7, "risk_controls": {"stop_loss_pct": -5}},
        ]
    }
    out = normalize_recommendation(rec)
    assert "exit_plan" in out["recommendations"][0]
    assert out["recommendations"][0]["exit_plan_auto_generated"] is True


def test_normalize_does_not_overwrite_existing_plan():
    custom_plan = [{"trigger": "now", "fraction": 1.0, "price_pct": 0, "note": "all in"}]
    rec = {
        "recommendations": [
            {"ticker": "NVDA", "action": "BUY", "conviction": 9, "entry_plan": custom_plan, "risk_controls": {}},
        ]
    }
    out = normalize_recommendation(rec)
    assert out["recommendations"][0]["entry_plan"] == custom_plan
    assert "entry_plan_auto_generated" not in out["recommendations"][0]


def test_normalize_skips_plan_for_hold():
    rec = {
        "recommendations": [
            {"ticker": "MSFT", "action": "HOLD", "conviction": 6, "risk_controls": {}},
        ]
    }
    out = normalize_recommendation(rec)
    assert "entry_plan" not in out["recommendations"][0]
    assert "exit_plan" not in out["recommendations"][0]


# ── Drift tracker self-compare fix ──────────────────────────────────────


def test_drift_tracker_skips_recent_re_run(tmp_path):
    """A morning re-run minutes apart should not be treated as previous session."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    # Newest file: 5 minutes ago (this is a re-run scenario)
    now = datetime.now()
    ten_min_ago = now - timedelta(minutes=10)
    six_hours_ago_morning = now - timedelta(hours=22)  # yesterday's morning

    file_recent = log_dir / f"{ten_min_ago.strftime('%Y%m%d')}_{ten_min_ago.strftime('%H%M')}_morning.json"
    file_recent.write_text(json.dumps({"recommendations": [{"ticker": "RECENT"}]}))

    file_old = log_dir / f"{six_hours_ago_morning.strftime('%Y%m%d')}_{six_hours_ago_morning.strftime('%H%M')}_morning.json"
    file_old.write_text(json.dumps({"recommendations": [{"ticker": "OLD"}]}))

    # Without min_age: returns the recent re-run (broken)
    out = get_previous_session(log_dir, current_session_type="morning", min_age_hours=0)
    assert out is not None
    assert out["recommendations"][0]["ticker"] == "RECENT"

    # With min_age 4h: skips the re-run, returns yesterday's morning
    out = get_previous_session(log_dir, current_session_type="morning", min_age_hours=4)
    assert out is not None
    assert out["recommendations"][0]["ticker"] == "OLD"


def test_drift_tracker_prefers_same_session_type(tmp_path):
    """Morning session prefers a previous morning over a more-recent afternoon."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    now = datetime.now()
    yesterday_afternoon = now - timedelta(hours=18)
    two_days_ago_morning = now - timedelta(hours=48)

    file_aft = log_dir / f"{yesterday_afternoon.strftime('%Y%m%d')}_{yesterday_afternoon.strftime('%H%M')}_afternoon.json"
    file_aft.write_text(json.dumps({"recommendations": [{"ticker": "AFT"}]}))

    file_morn = log_dir / f"{two_days_ago_morning.strftime('%Y%m%d')}_{two_days_ago_morning.strftime('%H%M')}_morning.json"
    file_morn.write_text(json.dumps({"recommendations": [{"ticker": "MORN"}]}))

    out = get_previous_session(log_dir, current_session_type="morning", min_age_hours=4)
    assert out is not None
    assert out["recommendations"][0]["ticker"] == "MORN"  # picked same type


def test_drift_tracker_returns_none_when_empty(tmp_path):
    out = get_previous_session(tmp_path / "nonexistent")
    assert out is None
