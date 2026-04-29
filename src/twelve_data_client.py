"""
twelve_data_client.py
Twelve Data API client — global markets, ETF support, price redundancy.

Free tier: 800 API calls/day, 2 requests/second.
Docs: https://twelvedata.com/docs

Provides:
  - quote(ticker): real-time quote (backup when yfinance is slow/unavailable)
  - earnings(ticker): upcoming and historical earnings dates

Twelve Data handles global exchanges well — useful for Canadian tickers
(e.g. SHOP.TO, CSU.TO) that yfinance sometimes returns stale data for.
All functions return None on error or missing API key — never raise.
"""

import os
import time

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.cache import cached
from src.config import load_settings

BASE_URL = "https://api.twelvedata.com"

# Rate-limit guard: free tier = 2 req/sec
_last_call_time: float = 0.0
_MIN_CALL_INTERVAL = 0.55  # 2 req/sec with a tiny margin


def _api_key() -> str | None:
    return os.environ.get("TWELVE_DATA_API_KEY") or None


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((requests.RequestException, ConnectionError, TimeoutError)),
    reraise=True,
)
def _request(endpoint: str, params: dict) -> dict | None:
    global _last_call_time
    key = _api_key()
    if not key:
        return None

    elapsed = time.monotonic() - _last_call_time
    if elapsed < _MIN_CALL_INTERVAL:
        time.sleep(_MIN_CALL_INTERVAL - elapsed)

    params = {**params, "apikey": key}
    r = requests.get(f"{BASE_URL}{endpoint}", params=params, timeout=10)
    _last_call_time = time.monotonic()

    if r.status_code >= 400:
        return None
    try:
        data = r.json()
    except Exception:
        return None

    # Twelve Data signals errors in the JSON body
    if isinstance(data, dict) and data.get("status") == "error":
        return None
    return data


# ── Real-time quote ───────────────────────────────────────────────────────────

def _fetch_quote(ticker: str) -> dict | None:
    # Twelve Data uses "/" instead of "." for Canadian tickers (e.g. SHOP/TSX)
    symbol = ticker.replace(".TO", "/TSX").replace(".V", "/TSXV")
    data = _request("/quote", {"symbol": symbol})
    if not data or not isinstance(data, dict):
        return None
    try:
        close = float(data["close"])
        change_pct = float(data.get("percent_change", 0))
        return {
            "ticker": ticker,
            "price": round(close, 2),
            "change_pct_1d": round(change_pct, 2),
            "volume": int(data.get("volume") or 0),
            "52w_high": float(data["fifty_two_week"]["high"]) if data.get("fifty_two_week") else None,
            "52w_low": float(data["fifty_two_week"]["low"]) if data.get("fifty_two_week") else None,
            "exchange": data.get("exchange"),
            "currency": data.get("currency"),
            "source": "twelve_data",
        }
    except (KeyError, ValueError, TypeError):
        return None


def quote(ticker: str) -> dict | None:
    """Real-time quote — backup for yfinance or better Canadian ticker data."""
    if not _api_key():
        return None
    settings = load_settings()
    ttl = settings.get("twelve_data_cache_ttl_seconds", 1800)  # 30min default
    try:
        return cached(
            namespace="td_quote",
            key=ticker,
            ttl_seconds=ttl,
            loader=lambda: _fetch_quote(ticker),
            enabled=settings.get("cache_enabled", True),
        )
    except Exception:
        return None


# ── Earnings dates ────────────────────────────────────────────────────────────

def _fetch_earnings(ticker: str) -> dict | None:
    symbol = ticker.replace(".TO", "/TSX").replace(".V", "/TSXV")
    data = _request("/earnings", {"symbol": symbol, "outputsize": 4, "type": "eps"})
    if not data or not isinstance(data, dict):
        return None
    earnings = data.get("earnings") or []
    if not earnings:
        return None

    upcoming = None
    recent = None
    for e in earnings:
        if e.get("actual") is None:
            if upcoming is None:
                upcoming = e
        else:
            if recent is None:
                recent = e

    return {
        "ticker": ticker,
        "next_earnings_date": (upcoming or {}).get("date"),
        "next_eps_estimate": (upcoming or {}).get("estimate"),
        "last_earnings_date": (recent or {}).get("date"),
        "last_eps_actual": (recent or {}).get("actual"),
        "last_eps_estimate": (recent or {}).get("estimate"),
        "last_eps_surprise": (recent or {}).get("surprise"),
        "last_eps_surprise_pct": (recent or {}).get("surprise_percentage"),
    }


def earnings(ticker: str) -> dict | None:
    """Upcoming earnings date + recent EPS from Twelve Data."""
    if not _api_key():
        return None
    settings = load_settings()
    ttl = settings.get("twelve_data_cache_ttl_seconds", 14400)  # 4h for earnings
    try:
        return cached(
            namespace="td_earnings",
            key=ticker,
            ttl_seconds=ttl,
            loader=lambda: _fetch_earnings(ticker),
            enabled=settings.get("cache_enabled", True),
        )
    except Exception:
        return None


if __name__ == "__main__":
    import json
    if not _api_key():
        print("TWELVE_DATA_API_KEY not set — skipping live test")
    else:
        for ticker in ["SHOP.TO", "NVDA", "MSFT"]:
            print(f"\n── quote({ticker}) ──")
            print(json.dumps(quote(ticker), indent=2))
            print(f"── earnings({ticker}) ──")
            print(json.dumps(earnings(ticker), indent=2))
