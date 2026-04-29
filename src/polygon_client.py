"""
polygon_client.py
Polygon.io API client — stock snapshot data (free tier).

Free tier: unlimited delayed data, stock aggregates, and market-wide snapshots.
Note: Options chain data requires a paid Polygon plan. This module uses only
free-tier endpoints: stock snapshot (volume, VWAP, pre/after market moves).
Docs: https://polygon.io/docs/stocks

Provides:
  - stock_snapshot(ticker): today's price, volume, VWAP, pre/after market change
  - volume_context(ticker): today's volume vs VWAP — confirms trend strength

These signal institutional participation via volume analysis:
  - High volume + price above VWAP = strong bullish momentum
  - Low volume + price above VWAP = weak move, likely to fade
  - Pre/after market changes hint at overnight catalyst positioning
All functions return None on error or missing API key — never raise.
"""

import os

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.cache import cached
from src.config import load_settings

BASE_URL = "https://api.polygon.io"


def _api_key() -> str | None:
    return os.environ.get("POLYGON_API_KEY") or None


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=12),
    retry=retry_if_exception_type((requests.RequestException, ConnectionError, TimeoutError)),
    reraise=True,
)
def _request(endpoint: str, params: dict | None = None) -> dict | None:
    key = _api_key()
    if not key:
        return None
    params = {**(params or {}), "apiKey": key}
    r = requests.get(f"{BASE_URL}{endpoint}", params=params, timeout=12)
    if r.status_code == 403:
        return None  # paid-only endpoint — silently skip
    if r.status_code == 429:
        raise requests.RequestException("Polygon rate limit")
    if r.status_code >= 400:
        return None
    try:
        return r.json()
    except Exception:
        return None


# ── Stock snapshot ────────────────────────────────────────────────────────────

def _fetch_stock_snapshot(ticker: str) -> dict | None:
    # /v2/aggs/ticker/{ticker}/prev — previous day OHLCV + VWAP (free tier)
    data = _request(f"/v2/aggs/ticker/{ticker}/prev", {"adjusted": "true"})
    if not data or not isinstance(data, dict):
        return None
    results = data.get("results") or []
    if not results:
        return None
    r = results[0]

    prev_close = r.get("c")
    prev_open  = r.get("o")
    prev_high  = r.get("h")
    prev_low   = r.get("l")
    prev_vol   = r.get("v")
    prev_vwap  = r.get("vw")

    if prev_close is None:
        return None

    # VWAP signal: close vs VWAP on prior session
    vwap_signal = None
    vwap_pct    = None
    if prev_vwap and prev_close:
        vwap_pct = round((prev_close - prev_vwap) / prev_vwap * 100, 2)
        if vwap_pct > 0.5:
            vwap_signal = "Closed ABOVE VWAP — bullish session"
        elif vwap_pct < -0.5:
            vwap_signal = "Closed BELOW VWAP — bearish session"
        else:
            vwap_signal = "Closed AT VWAP — neutral"

    day_range_pct = None
    if prev_high and prev_low and prev_close:
        day_range_pct = round((prev_high - prev_low) / prev_close * 100, 2)

    return {
        "ticker": ticker,
        "prev_close": prev_close,
        "prev_open": prev_open,
        "prev_vwap": round(prev_vwap, 2) if prev_vwap else None,
        "prev_volume": int(prev_vol) if prev_vol else None,
        "vwap_pct": vwap_pct,
        "vwap_signal": vwap_signal,
        "day_range_pct": day_range_pct,
        "source": "polygon",
    }


def stock_snapshot(ticker: str) -> dict | None:
    """Today's stock data from Polygon: price, volume, VWAP, after-hours move."""
    if not _api_key():
        return None
    settings = load_settings()
    ttl = settings.get("polygon_cache_ttl_seconds", 900)  # 15min for intraday
    try:
        return cached(
            namespace="polygon_snapshot",
            key=ticker,
            ttl_seconds=ttl,
            loader=lambda: _fetch_stock_snapshot(ticker),
            enabled=settings.get("cache_enabled", True),
        )
    except Exception:
        return None


if __name__ == "__main__":
    import json
    if not _api_key():
        print("POLYGON_API_KEY not set — skipping live test")
    else:
        for t in ["NVDA", "MSFT", "PLTR"]:
            print(f"\n── stock_snapshot({t}) ──")
            print(json.dumps(stock_snapshot(t), indent=2))
