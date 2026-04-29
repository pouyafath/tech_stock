"""
alpha_vantage_client.py
Alpha Vantage API client — backup prices, additional technical indicators,
and earnings/revenue estimates.

Free tier: 5 requests/minute, 500/day.
Docs: https://www.alphavantage.co/documentation/

Provides:
  - news_sentiment(ticker): AI-scored news articles with topics
  - earnings_estimates(ticker): analyst EPS/revenue forecasts

Used as supplementary signal layer — yfinance remains the primary source.
All functions return None on error or missing API key — never raise.
"""

import os
import threading
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

BASE_URL = "https://www.alphavantage.co/query"

# Thread-safe rate-limit guard — free tier: 5 calls/min
_rate_lock = threading.Lock()
_last_call_time: float = 0.0
_MIN_CALL_INTERVAL = 12.5  # seconds between calls (5/min → one per 12s)


def _api_key() -> str | None:
    return os.environ.get("ALPHA_VANTAGE_API_KEY") or None


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=5, max=15),
    retry=retry_if_exception_type((requests.RequestException, ConnectionError, TimeoutError)),
    reraise=True,
)
def _request(params: dict) -> dict | None:
    global _last_call_time
    key = _api_key()
    if not key:
        return None

    # Acquire lock so only one thread measures + sleeps at a time
    with _rate_lock:
        elapsed = time.monotonic() - _last_call_time
        if elapsed < _MIN_CALL_INTERVAL:
            time.sleep(_MIN_CALL_INTERVAL - elapsed)
        _last_call_time = time.monotonic()

    params = {**params, "apikey": key}
    r = requests.get(BASE_URL, params=params, timeout=15)

    if r.status_code >= 400:
        return None
    try:
        data = r.json()
    except Exception:
        return None

    # Alpha Vantage wraps errors as JSON {"Note": "...", "Information": "..."}
    if "Note" in data or "Information" in data:
        return None
    return data


# ── News & Sentiment ──────────────────────────────────────────────────────────

def _fetch_news_sentiment(ticker: str, limit: int = 10) -> dict | None:
    data = _request({
        "function": "NEWS_SENTIMENT",
        "tickers": ticker,
        "limit": limit,
        "sort": "LATEST",
    })
    if not data:
        return None
    items = data.get("feed") or []
    if not items:
        return None

    scores = [float(a["overall_sentiment_score"]) for a in items if "overall_sentiment_score" in a]
    if not scores:
        return None

    avg_score = sum(scores) / len(scores)
    bullish = sum(1 for s in scores if s > 0.15)
    bearish = sum(1 for s in scores if s < -0.15)
    neutral = len(scores) - bullish - bearish

    # Ticker-specific scores (filtered)
    ticker_scores = []
    for article in items:
        for ts in (article.get("ticker_sentiment") or []):
            if ts.get("ticker") == ticker:
                try:
                    ticker_scores.append(float(ts["ticker_sentiment_score"]))
                except (ValueError, KeyError):
                    pass

    ticker_avg = sum(ticker_scores) / len(ticker_scores) if ticker_scores else avg_score

    return {
        "ticker": ticker,
        "avg_sentiment": round(avg_score, 3),
        "ticker_avg_sentiment": round(ticker_avg, 3),
        "articles_analyzed": len(scores),
        "bullish": bullish,
        "bearish": bearish,
        "neutral": neutral,
        "label": (
            "BULLISH" if avg_score > 0.35 else
            "SOMEWHAT BULLISH" if avg_score > 0.15 else
            "NEUTRAL" if avg_score > -0.15 else
            "SOMEWHAT BEARISH" if avg_score > -0.35 else
            "BEARISH"
        ),
    }


def news_sentiment(ticker: str, limit: int = 10) -> dict | None:
    """AI-scored news sentiment from Alpha Vantage (distinct from VADER)."""
    if not _api_key():
        return None
    settings = load_settings()
    ttl = settings.get("alpha_vantage_cache_ttl_seconds", 14400)  # 4h default
    try:
        return cached(
            namespace="av_sentiment",
            key=f"{ticker}_{limit}",
            ttl_seconds=ttl,
            loader=lambda: _fetch_news_sentiment(ticker, limit),
            enabled=settings.get("cache_enabled", True),
        )
    except Exception:
        return None


# ── Earnings Calendar ──────────────────────────────────────────────────────────

def _fetch_earnings_calendar(ticker: str) -> dict | None:
    """Annual and quarterly earnings + analyst estimates."""
    data = _request({"function": "EARNINGS", "symbol": ticker})
    if not data:
        return None

    quarterly = data.get("quarterlyEarnings") or []
    if not quarterly:
        return None

    # Most recent reported quarter
    recent = quarterly[0]
    reported_eps = recent.get("reportedEPS")
    estimated_eps = recent.get("estimatedEPS")
    surprise = recent.get("surprisePercentage")

    out = {
        "ticker": ticker,
        "most_recent_period": recent.get("fiscalDateEnding"),
        "reported_eps": reported_eps,
        "estimated_eps": estimated_eps,
        "surprise_pct": float(surprise) if surprise else None,
    }

    # Next upcoming quarter if available
    for q in quarterly:
        if q.get("reportedEPS") in (None, "", "None"):
            out["next_period"] = q.get("fiscalDateEnding")
            out["next_eps_estimate"] = q.get("estimatedEPS")
            break

    return out


def earnings_calendar(ticker: str) -> dict | None:
    """Recent and upcoming EPS from Alpha Vantage."""
    if not _api_key():
        return None
    settings = load_settings()
    ttl = settings.get("alpha_vantage_cache_ttl_seconds", 14400)
    try:
        return cached(
            namespace="av_earnings",
            key=ticker,
            ttl_seconds=ttl,
            loader=lambda: _fetch_earnings_calendar(ticker),
            enabled=settings.get("cache_enabled", True),
        )
    except Exception:
        return None


if __name__ == "__main__":
    import json
    if not _api_key():
        print("ALPHA_VANTAGE_API_KEY not set — skipping live test")
    else:
        print("── news_sentiment(NVDA) ──")
        print(json.dumps(news_sentiment("NVDA"), indent=2))
        print("\n── earnings_calendar(NVDA) ──")
        print(json.dumps(earnings_calendar("NVDA"), indent=2))
