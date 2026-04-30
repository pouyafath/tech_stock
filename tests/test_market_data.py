from types import SimpleNamespace

import pandas as pd

from src.market_data import _fetch_options_implied_move, _safe_float, compute_indicators


def test_compute_indicators_includes_atr_volatility_and_sma_cross():
    dates = pd.date_range("2025-01-01", periods=230, freq="B")
    close = pd.Series(range(100, 330), index=dates, dtype=float)
    hist = pd.DataFrame({
        "Open": close - 1,
        "High": close + 2,
        "Low": close - 2,
        "Close": close,
        "Volume": [1_000_000] * len(close),
    })

    indicators = compute_indicators(hist)

    assert indicators["atr_14"] is not None
    assert indicators["atr_pct_of_price"] is not None
    assert indicators["volatility_20d_pct"] is not None
    assert indicators["sma_50_above_200"] is True


def test_options_implied_move_uses_atm_straddle_mid_prices():
    calls = pd.DataFrame([
        {"strike": 95, "bid": 4, "ask": 5, "lastPrice": 4.5},
        {"strike": 100, "bid": 6, "ask": 8, "lastPrice": 7},
    ])
    puts = pd.DataFrame([
        {"strike": 100, "bid": 5, "ask": 7, "lastPrice": 6},
        {"strike": 105, "bid": 8, "ask": 10, "lastPrice": 9},
    ])
    ticker = SimpleNamespace(
        options=["2026-05-15"],
        option_chain=lambda expiry: SimpleNamespace(calls=calls, puts=puts),
    )

    move = _fetch_options_implied_move(ticker, 101)

    assert move["expiry"] == "2026-05-15"
    assert move["atm_strike"] == 100
    assert move["straddle_price"] == 13
    assert move["implied_move_pct"] == 12.87


def test_safe_float_preserves_negative_values_for_derived_metrics():
    assert _safe_float(-4.25) == -4.25
