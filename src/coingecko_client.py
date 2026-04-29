"""
coingecko_client.py
CoinGecko API client — crypto market context.

Free tier: ~10,000-30,000 calls/month. API key optional (rate limits more lenient with key).
Docs: https://www.coingecko.com/en/api/documentation

Provides:
  - crypto_context(): BTC/ETH prices, 24h/7d change, dominance, Fear & Greed

Why crypto matters for a tech/growth portfolio:
  - Bitcoin is a leading risk-on/risk-off indicator for growth stocks
  - High crypto fear (<25) → broad risk-off, tech stocks often follow
  - BTC sell-off > 10% in 1 week → institutional risk reduction signal
  - Strong correlation: PLTR, IONQ, and small-cap tech often move with BTC
All functions return None on error — never raise.
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

BASE_URL = "https://api.coingecko.com/api/v3"
PRO_BASE_URL = "https://pro-api.coingecko.com/api/v3"


def _api_key() -> str | None:
    return os.environ.get("COINGECKO_API_KEY") or None


def _is_pro_key(key: str) -> bool:
    """Demo keys start with 'CG-' — they use the public API + demo header."""
    return bool(key) and not key.startswith("CG-")


def _base_url() -> str:
    key = _api_key()
    return PRO_BASE_URL if _is_pro_key(key or "") else BASE_URL


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((requests.RequestException, ConnectionError, TimeoutError)),
    reraise=True,
)
def _request(endpoint: str, params: dict | None = None) -> dict | list | None:
    headers = {}
    key = _api_key()
    if key:
        header_name = "x-cg-pro-api-key" if _is_pro_key(key) else "x-cg-demo-api-key"
        headers[header_name] = key

    r = requests.get(
        f"{_base_url()}{endpoint}",
        params=params or {},
        headers=headers,
        timeout=12,
    )
    if r.status_code == 429:
        raise requests.RequestException("CoinGecko rate limit")
    if r.status_code >= 400:
        return None
    try:
        return r.json()
    except Exception:
        return None


# ── Crypto market context ─────────────────────────────────────────────────────

def _fetch_crypto_context() -> dict | None:
    # Prices and changes
    data = _request(
        "/simple/price",
        {
            "ids": "bitcoin,ethereum",
            "vs_currencies": "usd",
            "include_24hr_change": True,
            "include_7d_change": True,
        },
    )
    if not data:
        return None

    btc = data.get("bitcoin", {})
    eth = data.get("ethereum", {})
    btc_price  = btc.get("usd")
    btc_24h    = btc.get("usd_24h_change")
    btc_7d     = btc.get("usd_7d_change")
    eth_price  = eth.get("usd")
    eth_24h    = eth.get("usd_24h_change")

    # Crypto fear & greed from alternative.me (free, no auth)
    fear_greed = None
    fear_label = None
    try:
        fg = requests.get(
            "https://api.alternative.me/fng/?limit=1",
            timeout=8,
        ).json()
        fg_data = (fg.get("data") or [{}])[0]
        fear_greed = int(fg_data.get("value", 0))
        fear_label = fg_data.get("value_classification", "")
    except Exception:
        pass

    # Risk-on/off interpretation
    risk_signal = "NEUTRAL"
    risk_note   = "Crypto market is stable — no special risk-off signal."

    if btc_7d is not None:
        if btc_7d < -15:
            risk_signal = "RISK-OFF"
            risk_note = (
                f"Bitcoin down {btc_7d:.1f}% this week — institutional risk reduction. "
                "Consider reducing exposure to high-beta tech (PLTR, IONQ, ARM)."
            )
        elif btc_7d < -8:
            risk_signal = "CAUTION"
            risk_note = (
                f"Bitcoin down {btc_7d:.1f}% this week — mild risk-off signal. "
                "Watch high-beta positions carefully."
            )
        elif btc_7d > 10:
            risk_signal = "RISK-ON"
            risk_note = (
                f"Bitcoin up {btc_7d:.1f}% this week — risk-on environment. "
                "High-beta tech typically benefits."
            )

    if fear_greed is not None and fear_greed < 25 and risk_signal == "NEUTRAL":
        risk_signal = "CAUTION"
        risk_note = f"Crypto Fear & Greed at {fear_greed} (extreme fear) — market-wide risk sentiment."

    return {
        "btc_price": btc_price,
        "btc_change_24h": round(btc_24h, 2) if btc_24h is not None else None,
        "btc_change_7d": round(btc_7d, 2) if btc_7d is not None else None,
        "eth_price": eth_price,
        "eth_change_24h": round(eth_24h, 2) if eth_24h is not None else None,
        "fear_greed_index": fear_greed,
        "fear_greed_label": fear_label,
        "risk_signal": risk_signal,
        "risk_note": risk_note,
    }


def crypto_context() -> dict | None:
    """BTC/ETH prices, weekly change, Fear & Greed, risk-on/off signal."""
    settings = load_settings()
    ttl = settings.get("coingecko_cache_ttl_seconds", 1800)  # 30min default
    try:
        return cached(
            namespace="coingecko",
            key="context",
            ttl_seconds=ttl,
            loader=_fetch_crypto_context,
            enabled=settings.get("cache_enabled", True),
        )
    except Exception:
        return None


if __name__ == "__main__":
    import json
    print("── crypto_context() ──")
    print(json.dumps(crypto_context(), indent=2))
