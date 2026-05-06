"""Tests for cache pricing fix and drawdown detection."""
from src.claude_analyst import MODEL_PRICING, estimate_cost
from src.portfolio_analytics import detect_drawdown


# ── Cache pricing ───────────────────────────────────────────────────────

def test_pricing_table_has_1h_cache_write_at_2x_input():
    """The code uses ttl='1h' which charges 2× input for cache writes."""
    for model, prices in MODEL_PRICING.items():
        assert "cache_write_1h" in prices, f"{model} missing cache_write_1h"
        assert "cache_write_5m" in prices, f"{model} missing cache_write_5m"
        # 1h write must be 2× input within rounding
        assert abs(prices["cache_write_1h"] - 2 * prices["input"]) < 0.01, (
            f"{model}: 1h cache write should be 2× input"
        )
        # 5m write should be 1.25× input
        assert abs(prices["cache_write_5m"] - 1.25 * prices["input"]) < 0.01


def test_estimate_cost_uses_1h_write_rate():
    class FakeUsage:
        input_tokens = 1000
        output_tokens = 500
        cache_creation_input_tokens = 5000
        cache_read_input_tokens = 10000
    out = estimate_cost(FakeUsage(), "claude-sonnet-4-6")
    # input: 0.001 * 3 = 0.003
    # output: 0.0005 * 15 = 0.0075
    # cache_write (1h): 0.005 * 6 = 0.030
    # cache_read: 0.01 * 0.30 = 0.003
    # Total: 0.0435
    assert abs(out["cost_usd"] - 0.0435) < 0.0001
    assert out["cache_hit"] is True


def test_estimate_cost_unknown_model_falls_back_to_sonnet():
    class FakeUsage:
        input_tokens = 1000
        output_tokens = 0
        cache_creation_input_tokens = 0
        cache_read_input_tokens = 0
    out = estimate_cost(FakeUsage(), "claude-some-future-model")
    # input only: 1000 / 1M * $3 = $0.003
    assert abs(out["cost_usd"] - 0.003) < 0.0001


# ── Drawdown detection ─────────────────────────────────────────────────

def _holding(ticker, market_value=10000, currency="USD"):
    return {
        "ticker": ticker,
        "market_value": market_value,
        "market_value_currency": currency,
    }


def _history(prices):
    """Build a market_data history list of {date, close} from a list of closes."""
    return [{"date": f"2026-04-{i+1:02d}", "close": p} for i, p in enumerate(prices)]


def test_drawdown_triggers_when_below_threshold():
    holdings = [_holding("AAPL")]
    # Prices peaked at 100, now at 92 — that's -8%
    market_data = {"AAPL": {"history": _history([100, 95, 100, 98, 92])}}
    state = detect_drawdown(holdings, market_data, {})
    assert state["triggered"] is True
    assert state["drawdown_pct"] < -6


def test_drawdown_does_not_trigger_at_peak():
    holdings = [_holding("AAPL")]
    market_data = {"AAPL": {"history": _history([90, 95, 100, 98, 100])}}
    state = detect_drawdown(holdings, market_data, {})
    assert state["triggered"] is False


def test_drawdown_handles_no_history():
    state = detect_drawdown([_holding("AAPL")], {}, {})
    assert state["triggered"] is False
    assert state["reason"] in {"no_history", "no_holdings"}


def test_drawdown_handles_no_holdings():
    state = detect_drawdown([], {"AAPL": {"history": _history([100, 90])}}, {})
    assert state["triggered"] is False


def test_drawdown_weighted_by_market_value():
    """Two holdings, one tanks, one stable — drawdown weighted by value."""
    holdings = [
        _holding("BAD", market_value=50_000),   # 5x weight
        _holding("OK",  market_value=10_000),
    ]
    market_data = {
        "BAD": {"history": _history([100, 100, 100, 90, 80])},  # -20% from peak
        "OK":  {"history": _history([100, 100, 100, 100, 100])},
    }
    state = detect_drawdown(holdings, market_data, {})
    assert state["triggered"] is True
    # BAD weight ≈ 5/6 → portfolio drawdown ≈ -16.7%
    assert state["drawdown_pct"] < -10


def test_drawdown_threshold_configurable():
    holdings = [_holding("AAPL")]
    market_data = {"AAPL": {"history": _history([100, 99, 98])}}  # -2% drawdown
    # Default threshold -6%: not triggered
    state = detect_drawdown(holdings, market_data, {})
    assert state["triggered"] is False
    # Custom threshold -1%: triggered
    state = detect_drawdown(holdings, market_data, {"drawdown_circuit_breaker_pct": -1})
    assert state["triggered"] is True
