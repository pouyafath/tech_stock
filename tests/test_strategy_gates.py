"""Tests for the new VIX, drawdown, conviction-sizing, and stale-position gates."""
from src.report_quality import apply_quality_gates, vix_size_multiplier


def _rec(action="BUY", invest_amount=500, conviction=8, ticker="MSFT"):
    return {
        "recommendations": [
            {
                "ticker": ticker,
                "action": action,
                "conviction": conviction,
                "invest_amount_usd": invest_amount,
                "thesis": "Test thesis",
            }
        ],
        "priority_actions": [],
    }


# ── VIX-regime sizing ────────────────────────────────────────────────────

def test_vix_multiplier_brackets():
    assert vix_size_multiplier(None) == 1.0
    assert vix_size_multiplier(12) == 1.0
    assert vix_size_multiplier(20) == 0.85
    assert vix_size_multiplier(28) == 0.6
    assert vix_size_multiplier(40) == 0.4


def test_vix_multiplier_respects_overrides():
    settings = {"vix_size_thresholds": {"low": 10, "low_mult": 0.9}}
    assert vix_size_multiplier(8, settings) == 0.9


def test_vix_scales_invest_amount_when_elevated():
    rec = _rec(action="BUY", invest_amount=400, conviction=8)
    out = apply_quality_gates(
        rec, [],
        market_context={"macro": {"vix": 28}},
    )
    # 400 * 0.6 = 240
    assert out["recommendations"][0]["invest_amount_usd"] == 240
    assert out["vix_size_multiplier"] == 0.6


def test_vix_does_not_scale_when_calm():
    rec = _rec(invest_amount=500)
    out = apply_quality_gates(rec, [], market_context={"macro": {"vix": 12}})
    assert out["recommendations"][0]["invest_amount_usd"] == 500
    assert "vix_size_multiplier" not in out  # only set when adjusted


# ── Drawdown circuit breaker ─────────────────────────────────────────────

def test_drawdown_kills_buys_and_halves_adds():
    rec = {
        "recommendations": [
            {"ticker": "NVDA", "action": "BUY", "conviction": 8, "invest_amount_usd": 600},
            {"ticker": "AAPL", "action": "ADD", "conviction": 8, "invest_amount_usd": 400},
            {"ticker": "MSFT", "action": "HOLD", "conviction": 6, "hold_tier": "keep"},
        ],
        "priority_actions": [],
    }
    drawdown = {"triggered": True, "drawdown_pct": -7.5, "peak_label": "30d peak"}
    out = apply_quality_gates(rec, [], drawdown_state=drawdown)
    nvda = out["recommendations"][0]
    aapl = out["recommendations"][1]
    msft = out["recommendations"][2]

    # BUY → HOLD-watch
    assert nvda["action"] == "HOLD"
    assert nvda["hold_tier"] == "watch"
    assert nvda["invest_amount_usd"] is None
    # ADD halved
    assert aapl["invest_amount_usd"] == 200
    assert "DRAWDOWN MODE" in aapl["thesis"]
    # Weak HOLD → forced watch
    assert msft["hold_tier"] == "watch"
    # State preserved on output
    assert out["drawdown_state"]["triggered"] is True


def test_drawdown_no_change_when_not_triggered():
    rec = _rec(action="ADD", invest_amount=400)
    out = apply_quality_gates(rec, [], drawdown_state={"triggered": False})
    assert out["recommendations"][0]["invest_amount_usd"] == 400


# ── Stale-position gate (>2 years) ───────────────────────────────────────

def test_stale_position_forces_trim():
    rec = {
        "recommendations": [
            {"ticker": "OLDCO", "action": "HOLD", "conviction": 7, "hold_tier": "keep",
             "thesis": "Long term hold"},
        ],
        "priority_actions": [],
    }
    aging = {"stale_tickers": ["OLDCO"], "aged_tickers": [], "mature_tickers": []}
    out = apply_quality_gates(rec, [], aging_summary_data=aging)
    target = out["recommendations"][0]
    assert target["action"] == "TRIM"
    assert "OVER 2-YEAR CAP" in target["thesis"]
    assert target["manual_review_required"] is True


def test_stale_position_appends_when_not_in_recommendations():
    """If a stale ticker has no Claude recommendation, the gate adds a TRIM."""
    rec = {"recommendations": [
        {"ticker": "OTHER", "action": "BUY", "conviction": 7, "invest_amount_usd": 100},
    ], "priority_actions": []}
    aging = {"stale_tickers": ["GHOSTCO"]}
    out = apply_quality_gates(rec, [], aging_summary_data=aging)
    auto = [r for r in out["recommendations"] if r.get("auto_generated")]
    assert len(auto) == 1
    assert auto[0]["ticker"] == "GHOSTCO"
    assert auto[0]["action"] == "TRIM"


# ── Conviction-stratified sizing from hit rates ──────────────────────────

def test_conviction_sizing_uses_hit_rates():
    rec = _rec(invest_amount=500, conviction=8)
    backtest = {
        "sizing_multipliers_by_conviction": {8: 0.7, 9: 1.2}
    }
    out = apply_quality_gates(rec, [], backtest_summary=backtest)
    assert out["recommendations"][0]["invest_amount_usd"] == 350
    assert out["recommendations"][0]["sizing_multiplier_applied"] == 0.7


def test_conviction_sizing_no_op_when_bucket_missing():
    rec = _rec(invest_amount=500, conviction=6)
    backtest = {"sizing_multipliers_by_conviction": {8: 0.7}}
    out = apply_quality_gates(rec, [], backtest_summary=backtest)
    assert out["recommendations"][0]["invest_amount_usd"] == 500
    assert "sizing_multiplier_applied" not in out["recommendations"][0]


def test_vix_and_conviction_compose():
    """VIX runs before conviction sizing — both should compose multiplicatively."""
    rec = _rec(invest_amount=1000, conviction=8)
    out = apply_quality_gates(
        rec, [],
        market_context={"macro": {"vix": 28}},  # 0.6×
        backtest_summary={"sizing_multipliers_by_conviction": {8: 0.5}},
    )
    # 1000 × 0.6 = 600 → × 0.5 = 300
    assert out["recommendations"][0]["invest_amount_usd"] == 300
