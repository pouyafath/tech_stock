"""Tests for the new strategy-gate report sections."""

from src.report_sections import (
    render_entry_or_exit_plan,
    render_market_state_banner,
    render_position_aging,
    render_sector_rotation,
    render_trailing_stops,
)

# ── Position aging ──────────────────────────────────────────────────────


def test_position_aging_shows_actionable_tiers():
    holdings = [
        {"ticker": "FRESH"},
        {"ticker": "MATU"},
        {"ticker": "STALE"},
    ]
    days = {
        "FRESH": {"days_held": 30},
        "MATU": {"days_held": 250},
        "STALE": {"days_held": 800},
    }
    out = "\n".join(render_position_aging(holdings, days))
    assert "Position Aging" in out
    assert "MATU" in out
    assert "STALE" in out
    assert "Auto-TRIM" in out


def test_position_aging_quiet_when_only_fresh():
    holdings = [{"ticker": "FRESH"}]
    days = {"FRESH": {"days_held": 30}}
    out = "\n".join(render_position_aging(holdings, days))
    assert "fresh" in out.lower() or "core" in out.lower()
    assert "STALE" not in out  # no stale section


def test_position_aging_discloses_unknown_durations():
    holdings = [{"ticker": "FRESH"}, {"ticker": "UNKNOWN"}]
    days = {
        "FRESH": {"days_held": 30},
        "UNKNOWN": {"days_held": None, "duration_unknown": True, "lower_bound_days": 41},
    }

    out = "\n".join(render_position_aging(holdings, days))

    assert "Known activity-derived ages" in out
    assert "unknown entry dates" in out
    assert "All open positions" not in out


def test_position_aging_empty_when_no_data():
    assert render_position_aging([], {}) == []


# ── Trailing stops ──────────────────────────────────────────────────────


def test_trailing_stops_renders_breached_first():
    alerts = [
        {
            "ticker": "OK",
            "trail_kind": "trail_pct",
            "stop_price": 95.0,
            "current_price": 110.0,
            "peak_price": 115.0,
            "avg_cost": 100.0,
            "current_gain_pct": 10.0,
            "peak_gain_pct": 15.0,
            "breached": False,
        },
        {
            "ticker": "BREACH",
            "trail_kind": "trail_pct",
            "stop_price": 100.0,
            "current_price": 99.0,
            "peak_price": 120.0,
            "avg_cost": 90.0,
            "current_gain_pct": 10.0,
            "peak_gain_pct": 33.0,
            "breached": True,
        },
    ]
    out = "\n".join(render_trailing_stops(alerts))
    assert "Trailing Stops" in out
    assert "Breached" in out
    assert "BREACH" in out
    assert out.index("BREACH") < out.index("OK")


def test_trailing_stops_empty_when_no_alerts():
    assert render_trailing_stops([]) == []
    assert render_trailing_stops(None) == []


# ── Sector rotation ─────────────────────────────────────────────────────


def test_sector_rotation_shows_leaders_laggards():
    market_context = {
        "XLK": {"change_pct_21d": 5.0},
        "XLE": {"change_pct_21d": -3.0},
        "XLF": {"change_pct_21d": 1.0},
    }
    out = "\n".join(render_sector_rotation(market_context, None, settings={"sector_rotation_tickers": ["XLK", "XLE", "XLF"]}))
    assert "Sector Rotation" in out
    assert "XLK" in out
    assert "Leaders" in out


def test_sector_rotation_empty_when_no_data():
    assert render_sector_rotation({}, None) == []
    assert render_sector_rotation(None, None) == []


def test_sector_rotation_includes_rotating_arrows():
    prev = {"XLK": {"change_pct_21d": 5.0}, "XLE": {"change_pct_21d": -5.0}}
    curr = {"XLE": {"change_pct_21d": 5.0}, "XLK": {"change_pct_21d": -5.0}}
    out = "\n".join(render_sector_rotation(curr, prev, settings={"sector_rotation_tickers": ["XLK", "XLE"]}))
    assert "Rotating IN" in out or "Rotating OUT" in out


# ── Risk modifier banner ────────────────────────────────────────────────


def test_banner_shows_drawdown():
    drawdown = {"triggered": True, "drawdown_pct": -7.5, "peak_label": "30d peak", "threshold_pct": -6}
    out = "\n".join(render_market_state_banner(drawdown, None, None))
    assert "DRAWDOWN CIRCUIT BREAKER ACTIVE" in out
    assert "-7.5%" in out


def test_banner_shows_vix_adjustment():
    out = "\n".join(render_market_state_banner(None, {"macro": {"vix": 28}}, 0.6))
    assert "VIX-regime sizing" in out
    assert "0.6" in out


def test_banner_empty_when_no_modifiers():
    assert render_market_state_banner(None, None, None) == []
    assert render_market_state_banner({"triggered": False}, None, None) == []


# ── Tranched plan rendering ─────────────────────────────────────────────


def test_render_entry_plan_full_table():
    rec = {
        "entry_plan": [
            {"trigger": "now", "fraction": 0.4, "price_pct": 0, "note": "immediate"},
            {"trigger": "pullback", "fraction": 0.3, "price_pct": -3, "note": "on pullback"},
            {"trigger": "confirmation", "fraction": 0.3, "price_pct": 2, "note": "on upside"},
        ]
    }
    out = "\n".join(render_entry_or_exit_plan(rec))
    assert "Entry Plan" in out
    assert "now" in out and "pullback" in out and "confirmation" in out
    assert "40%" in out


def test_render_exit_plan_uses_exit_label():
    rec = {
        "exit_plan": [
            {"trigger": "now", "fraction": 1.0, "price_pct": 0, "note": "full exit"},
        ]
    }
    out = "\n".join(render_entry_or_exit_plan(rec))
    assert "Exit Plan" in out


def test_render_plan_marks_auto_generated():
    rec = {"entry_plan": [{"trigger": "now", "fraction": 1.0, "price_pct": 0}], "entry_plan_auto_generated": True}
    out = "\n".join(render_entry_or_exit_plan(rec))
    assert "auto-generated" in out


def test_render_plan_empty_when_no_plan():
    assert render_entry_or_exit_plan({}) == []
    assert render_entry_or_exit_plan({"entry_plan": []}) == []
