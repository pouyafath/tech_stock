"""Trailing stops auto-tighten as positions appreciate."""
from src.report_quality import apply_quality_gates
from src.trailing_stops import (
    DEFAULT_SCHEDULE,
    compute_trailing_stop,
    evaluate,
    format_for_prompt,
)


def test_below_first_threshold_returns_none_kind():
    out = compute_trailing_stop(avg_cost=100, current_price=105, peak_price=108)
    assert out["trail_kind"] == "none"


def test_breakeven_after_10pct_gain():
    out = compute_trailing_stop(avg_cost=100, current_price=112, peak_price=115)
    assert out["trail_kind"] == "breakeven"
    assert out["stop_price"] == 100.0


def test_trail_8pct_after_20pct_gain():
    out = compute_trailing_stop(avg_cost=100, current_price=125, peak_price=130)
    assert out["trail_kind"] == "trail_pct"
    # 130 × (1 - 0.08) = 119.6
    assert out["stop_price"] == 119.6


def test_trail_12pct_after_40pct_gain():
    out = compute_trailing_stop(avg_cost=100, current_price=145, peak_price=150)
    assert out["trail_kind"] == "trail_pct"
    # 150 × (1 - 0.12) = 132.0
    assert out["stop_price"] == 132.0


def test_returns_none_for_invalid_avg_cost():
    assert compute_trailing_stop(None, 100, 100) is None
    assert compute_trailing_stop(0, 100, 100) is None


def test_evaluate_only_returns_active_or_breached():
    holdings = [
        {"ticker": "WIN",  "avg_cost_market": 100},   # +20%, active
        {"ticker": "FLAT", "avg_cost_market": 100},   # +5%, no trail
    ]
    market_data = {
        "WIN":  {"current_price": 120, "history": [{"date": "2026-04-01", "close": 130}]},
        "FLAT": {"current_price": 105, "history": [{"date": "2026-04-01", "close": 106}]},
    }
    out = evaluate(holdings, market_data, holding_days_map={})
    tickers = [r["ticker"] for r in out]
    assert "WIN" in tickers
    assert "FLAT" not in tickers


def test_evaluate_marks_breached():
    holdings = [{"ticker": "DROP", "avg_cost_market": 100}]
    # Peaked at 130 (+30%), now at 115 (+15%)
    # Trail by 8% from peak = stop at 119.6 → breached at 115
    market_data = {
        "DROP": {
            "current_price": 115,
            "history": [
                {"date": "2026-04-01", "close": 110},
                {"date": "2026-04-15", "close": 130},
                {"date": "2026-05-01", "close": 115},
            ],
        }
    }
    out = evaluate(holdings, market_data, holding_days_map={})
    assert len(out) == 1
    assert out[0]["breached"] is True
    assert out[0]["recommended_action"] == "TRIM"


def test_format_for_prompt_groups_breached_first():
    alerts = [
        {"ticker": "OK", "trail_kind": "trail_pct", "stop_price": 95.0,
         "current_price": 110.0, "peak_price": 115.0, "avg_cost": 100.0,
         "current_gain_pct": 10.0, "peak_gain_pct": 15.0, "breached": False,
         "recommended_action": "HOLD"},
        {"ticker": "OUT", "trail_kind": "trail_pct", "stop_price": 100.0,
         "current_price": 99.0, "peak_price": 120.0, "avg_cost": 90.0,
         "current_gain_pct": 10.0, "peak_gain_pct": 33.0, "breached": True,
         "recommended_action": "TRIM"},
    ]
    block = format_for_prompt(alerts)
    assert "BREACHED" in block
    # Breached must come before active in the rendered block
    assert block.index("OUT") < block.index("OK")


def test_default_schedule_matches_strategy_doc():
    assert DEFAULT_SCHEDULE[0] == (10.0, "breakeven", 0.0)
    assert DEFAULT_SCHEDULE[1] == (20.0, "trail_pct", 8.0)
    assert DEFAULT_SCHEDULE[2] == (40.0, "trail_pct", 12.0)


def test_apply_quality_gates_auto_trims_breached():
    rec = {"recommendations": [
        {"ticker": "WINNER", "action": "HOLD", "conviction": 7,
         "thesis": "long term hold"},
    ], "priority_actions": []}
    alerts = [{
        "ticker": "WINNER", "trail_kind": "trail_pct", "stop_price": 119.6,
        "current_price": 115.0, "peak_price": 130.0, "avg_cost": 100.0,
        "current_gain_pct": 15.0, "peak_gain_pct": 30.0, "breached": True,
        "recommended_action": "TRIM",
    }]
    out = apply_quality_gates(rec, [], trailing_alerts=alerts)
    target = out["recommendations"][0]
    assert target["action"] == "TRIM"
    assert "TRAILING STOP BREACHED" in target["thesis"]


def test_apply_quality_gates_appends_breach_for_unrec_ticker():
    rec = {"recommendations": [
        {"ticker": "OTHER", "action": "BUY", "conviction": 7, "invest_amount_usd": 200},
    ], "priority_actions": []}
    alerts = [{
        "ticker": "ORPHAN", "trail_kind": "trail_pct", "stop_price": 95.0,
        "current_price": 90.0, "peak_price": 110.0, "avg_cost": 80.0,
        "current_gain_pct": 12.5, "peak_gain_pct": 37.5, "breached": True,
        "recommended_action": "TRIM",
    }]
    out = apply_quality_gates(rec, [], trailing_alerts=alerts)
    auto = [r for r in out["recommendations"] if r.get("auto_generated")]
    assert any(r["ticker"] == "ORPHAN" and r["action"] == "TRIM" for r in auto)
