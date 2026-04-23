"""
market_data.py
Fetches live prices, 3-month OHLCV history, and key fundamentals via yfinance.
No API key required — all free.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

SETTINGS_PATH = Path(__file__).parent.parent / "config" / "settings.json"


def load_settings() -> dict:
    with open(SETTINGS_PATH) as f:
        return json.load(f)


def get_ticker_data(ticker: str, history_months: int = 3) -> dict:
    """
    Fetch data for a single ticker. Returns a dict with:
        - ticker, current_price, currency
        - change_pct_1d, change_pct_5d, change_pct_1mo
        - volume, avg_volume_30d
        - market_cap, pe_ratio, forward_pe
        - 52w_high, 52w_low, pct_from_52w_high
        - history: list of {date, open, high, low, close, volume}
        - error: None or error message
    """
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}

        end = datetime.now()
        start = end - timedelta(days=history_months * 31)
        hist = t.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))

        if hist.empty:
            return {"ticker": ticker, "error": "No history data returned"}

        current_price = float(hist["Close"].iloc[-1])
        currency = info.get("currency", "USD")

        # Price changes
        def pct_change(n_days: int) -> float | None:
            if len(hist) < n_days + 1:
                return None
            prev = float(hist["Close"].iloc[-(n_days + 1)])
            return round((current_price - prev) / prev * 100, 2)

        # History as list of dicts (last 90 days)
        history_records = []
        for idx, row in hist.tail(90).iterrows():
            history_records.append({
                "date": str(idx.date()),
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"]),
            })

        fifty_two_week_high = info.get("fiftyTwoWeekHigh")
        pct_from_52w_high = None
        if fifty_two_week_high and fifty_two_week_high > 0:
            pct_from_52w_high = round((current_price - fifty_two_week_high) / fifty_two_week_high * 100, 2)

        avg_vol = info.get("averageVolume") or info.get("averageDailyVolume10Day")

        return {
            "ticker": ticker,
            "current_price": round(current_price, 2),
            "currency": currency,
            "change_pct_1d": pct_change(1),
            "change_pct_5d": pct_change(5),
            "change_pct_1mo": pct_change(21),
            "volume_today": int(hist["Volume"].iloc[-1]) if not hist.empty else None,
            "avg_volume_30d": int(avg_vol) if avg_vol else None,
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "52w_high": fifty_two_week_high,
            "52w_low": info.get("fiftyTwoWeekLow"),
            "pct_from_52w_high": pct_from_52w_high,
            "sector": info.get("sector"),
            "history": history_records,
            "error": None,
        }

    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def get_market_data(tickers: list, history_months: int = None) -> dict:
    """Fetch data for a list of tickers. Returns {ticker: data_dict}."""
    settings = load_settings()
    if history_months is None:
        history_months = settings.get("history_months", 3)

    result = {}
    for ticker in tickers:
        print(f"  Fetching {ticker}...", flush=True)
        result[ticker] = get_ticker_data(ticker, history_months)

    return result


def get_portfolio_prices(holdings: list) -> dict:
    """
    Given a list of holding dicts (with 'ticker' key), fetch current prices.
    Returns {ticker: current_price}.
    """
    if not holdings:
        return {}
    tickers = [h["ticker"] for h in holdings]
    data = get_market_data(tickers)
    return {
        ticker: d.get("current_price")
        for ticker, d in data.items()
    }


if __name__ == "__main__":
    test_tickers = ["NVDA", "PLTR", "MSFT"]
    data = get_market_data(test_tickers)
    for ticker, d in data.items():
        if d.get("error"):
            print(f"{ticker}: ERROR — {d['error']}")
        else:
            print(f"{ticker}: ${d['current_price']} ({d['change_pct_1d']:+.2f}% today), "
                  f"PE={d['pe_ratio']}, {d['pct_from_52w_high']:+.1f}% from 52w high")
