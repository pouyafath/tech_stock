from types import SimpleNamespace

import pandas as pd

from src import market_data
from src.market_data import (
    _epoch_to_utc_iso,
    _fetch_options_implied_move,
    _first_float,
    _first_float_with_source,
    _safe_float,
    compute_indicators,
    get_context_moves,
    get_market_data,
    get_portfolio_prices,
    get_ticker_data,
    price_at,
)


def test_first_float_and_source_pick_first_numeric():
    assert _first_float(None, "nan", "12.5", 3) == 12.5
    assert _first_float(None, None) is None
    name, value = _first_float_with_source(("a", None), ("b", "7.25"), ("c", 9))
    assert (name, value) == ("b", 7.25)
    assert _first_float_with_source(("a", None), ("b", None)) == (None, None)


def test_epoch_to_utc_iso_handles_bad_input():
    assert _epoch_to_utc_iso(None) is None
    assert _epoch_to_utc_iso("not-a-number") is None
    iso = _epoch_to_utc_iso(1_700_000_000)
    assert iso is not None and iso.endswith("+00:00")


def test_compute_indicators_returns_all_none_for_short_history():
    hist = pd.DataFrame({"Close": [100.0, 101.0, 102.0]})  # < 15 rows
    out = compute_indicators(hist)
    assert out["rsi_14"] is None
    assert out["sma_50"] is None
    assert out["atr_14"] is None
    # Empty / None frames are handled too.
    assert compute_indicators(pd.DataFrame())["rsi_14"] is None
    assert compute_indicators(None)["macd"] is None


def test_get_ticker_data_success_and_error(monkeypatch):
    # Bypass the disk cache: call the loader directly.
    monkeypatch.setattr(market_data, "cached", lambda **kw: kw["loader"]())
    monkeypatch.setattr(market_data, "load_settings", lambda: {})
    monkeypatch.setattr(market_data, "_fetch_ticker_raw", lambda t, m, include_options=False: {"ticker": t, "current_price": 42.0})
    assert get_ticker_data("AAPL")["current_price"] == 42.0

    def _boom(*_a, **_k):
        raise ConnectionError("yfinance down")

    monkeypatch.setattr(market_data, "cached", lambda **kw: kw["loader"]())
    monkeypatch.setattr(market_data, "_fetch_ticker_raw", _boom)
    err = get_ticker_data("BAD")
    assert err["ticker"] == "BAD" and "down" in err["error"]


def test_get_market_data_isolates_per_ticker_failures(monkeypatch):
    monkeypatch.setattr(market_data, "load_settings", lambda: {"yfinance_max_workers": 2})

    def fake_get_ticker_data(ticker, history_months):
        if ticker == "BAD":
            raise ValueError("kaboom")
        return {"ticker": ticker, "current_price": 10.0}

    monkeypatch.setattr(market_data, "get_ticker_data", fake_get_ticker_data)
    out = get_market_data(["GOOD", "BAD"], history_months=6)
    assert out["GOOD"]["current_price"] == 10.0
    assert "kaboom" in out["BAD"]["error"]


def test_get_portfolio_prices(monkeypatch):
    assert get_portfolio_prices([]) == {}
    monkeypatch.setattr(
        market_data,
        "get_market_data",
        lambda tickers: {t: {"current_price": 5.0} for t in tickers},
    )
    prices = get_portfolio_prices([{"ticker": "NVDA"}, {"ticker": "AMD"}])
    assert prices == {"NVDA": 5.0, "AMD": 5.0}


def test_price_at_returns_value_and_swallows_errors(monkeypatch):
    monkeypatch.setattr(market_data, "cached", lambda **kw: kw["loader"]())
    monkeypatch.setattr(market_data, "load_settings", lambda: {})
    monkeypatch.setattr(market_data, "_fetch_price_at", lambda t, d: 123.45)
    assert price_at("AAPL", "2026-01-05") == 123.45

    def _boom(*_a, **_k):
        raise TimeoutError("slow")

    monkeypatch.setattr(market_data, "cached", lambda **kw: kw["loader"]())
    monkeypatch.setattr(market_data, "_fetch_price_at", _boom)
    assert price_at("AAPL", "2026-01-05") is None


def test_add_options_implied_moves_populates_and_skips(monkeypatch):
    monkeypatch.setattr(market_data, "_fetch_options_implied_move", lambda obj, price: {"implied_move_pct": 5.0})
    monkeypatch.setattr(market_data.yf, "Ticker", lambda t: SimpleNamespace())
    md = {
        "AAPL": {"current_price": 100.0},
        "ERR": {"error": "boom"},  # skipped
        "NOPRICE": {"current_price": None},  # skipped
    }
    out = market_data.add_options_implied_moves(md, ["AAPL", "ERR", "NOPRICE"])
    assert out["AAPL"]["options_implied_move"] == {"implied_move_pct": 5.0}
    assert "options_implied_move" not in out["ERR"]


def test_compute_indicators_includes_atr_volatility_and_sma_cross():
    dates = pd.date_range("2025-01-01", periods=230, freq="B")
    close = pd.Series(range(100, 330), index=dates, dtype=float)
    hist = pd.DataFrame(
        {
            "Open": close - 1,
            "High": close + 2,
            "Low": close - 2,
            "Close": close,
            "Volume": [1_000_000] * len(close),
        }
    )

    indicators = compute_indicators(hist)

    assert indicators["atr_14"] is not None
    assert indicators["atr_pct_of_price"] is not None
    assert indicators["volatility_20d_pct"] is not None
    assert indicators["sma_50_above_200"] is True


def test_options_implied_move_uses_atm_straddle_mid_prices():
    calls = pd.DataFrame(
        [
            {"strike": 95, "bid": 4, "ask": 5, "lastPrice": 4.5},
            {"strike": 100, "bid": 6, "ask": 8, "lastPrice": 7},
        ]
    )
    puts = pd.DataFrame(
        [
            {"strike": 100, "bid": 5, "ask": 7, "lastPrice": 6},
            {"strike": 105, "bid": 8, "ask": 10, "lastPrice": 9},
        ]
    )
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


def test_context_moves_exposes_one_month_label_and_compat_alias(monkeypatch):
    def fake_get_market_data(symbols, history_months):
        return {
            "XLK": {
                "current_price": 100,
                "change_pct_5d": 1.2,
                "change_pct_1mo": 4.5,
                "quote_timestamp_utc": "2026-04-30T20:00:00Z",
                "quote_source": "test",
            }
        }

    monkeypatch.setattr("src.market_data.get_market_data", fake_get_market_data)

    out = get_context_moves(["XLK"])

    assert out["XLK"]["change_pct_21d"] == 4.5
    assert out["XLK"]["change_pct_20d"] == 4.5
