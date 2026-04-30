"""
finnhub_client.py
Finnhub API client — earnings calendar, analyst recommendations, news sentiment.

Free tier: 60 requests/minute, unlimited daily.
Docs: https://finnhub.io/docs/api

Provides:
  - earnings_calendar(ticker, days_ahead): upcoming earnings + EPS estimates
  - recommendation_trends(ticker): analyst buy/hold/sell consensus
  - upgrade_downgrade(ticker): recent analyst rating changes
  - news_sentiment(ticker): aggregate sentiment score from finance news
  - earnings_surprises(ticker): historical beat/miss vs estimates

All functions return None on error or missing API key — never raise.
"""

import os
from datetime import datetime, timedelta

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.cache import cached
from src.config import load_settings

BASE_URL = "https://finnhub.io/api/v1"


def _api_key() -> str | None:
    return os.environ.get("FINNHUB_API_KEY") or None


def _get_settings() -> dict:
    return load_settings()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((requests.RequestException, ConnectionError, TimeoutError)),
    reraise=True,
)
def _request(endpoint: str, params: dict) -> dict | list | None:
    key = _api_key()
    if not key:
        return None
    params = {**params, "token": key}
    r = requests.get(f"{BASE_URL}{endpoint}", params=params, timeout=10)
    if r.status_code == 429:
        # rate limited; let tenacity retry
        raise requests.RequestException("Finnhub rate limit")
    if r.status_code >= 400:
        return None
    try:
        return r.json()
    except Exception:
        return None


# ── Earnings calendar ─────────────────────────────────────────────────────────

def _fetch_earnings_calendar(ticker: str, days_ahead: int) -> dict | None:
    today = datetime.now().date()
    end = today + timedelta(days=days_ahead)
    data = _request(
        "/calendar/earnings",
        {"from": today.isoformat(), "to": end.isoformat(), "symbol": ticker},
    )
    if not data:
        return None
    rows = data.get("earningsCalendar", []) or []
    if not rows:
        return None
    # Earliest upcoming earnings
    rows.sort(key=lambda r: r.get("date", ""))
    nxt = rows[0]
    return {
        "ticker": ticker,
        "date": nxt.get("date"),
        "hour": nxt.get("hour"),  # bmo / amc
        "eps_estimate": nxt.get("epsEstimate"),
        "revenue_estimate": nxt.get("revenueEstimate"),
        "year": nxt.get("year"),
        "quarter": nxt.get("quarter"),
    }


def earnings_calendar(ticker: str, days_ahead: int = 30) -> dict | None:
    """Next earnings date + EPS/revenue estimates within `days_ahead` days."""
    if not _api_key():
        return None
    settings = _get_settings()
    ttl = settings.get("finnhub_cache_ttl_seconds", 21600)  # 6h default
    return cached(
        namespace="finnhub_earnings",
        key=f"{ticker}_{days_ahead}",
        ttl_seconds=ttl,
        loader=lambda: _fetch_earnings_calendar(ticker, days_ahead),
        enabled=settings.get("cache_enabled", True),
    )


# ── Analyst recommendation trends ─────────────────────────────────────────────

def _fetch_recommendation_trends(ticker: str) -> dict | None:
    data = _request("/stock/recommendation", {"symbol": ticker})
    if not data or not isinstance(data, list) or not data:
        return None
    # Most recent month is first
    latest = data[0]
    buy = (latest.get("buy") or 0) + (latest.get("strongBuy") or 0)
    hold = latest.get("hold") or 0
    sell = (latest.get("sell") or 0) + (latest.get("strongSell") or 0)
    total = buy + hold + sell
    if total == 0:
        return None
    # Net score: -1 (all sell) to +1 (all buy)
    net = (buy - sell) / total
    return {
        "ticker": ticker,
        "period": latest.get("period"),
        "buy": buy,
        "hold": hold,
        "sell": sell,
        "total_analysts": total,
        "consensus_score": round(net, 2),
        "consensus_label": (
            "STRONG BUY" if net > 0.5 else
            "BUY" if net > 0.15 else
            "HOLD" if net > -0.15 else
            "SELL" if net > -0.5 else
            "STRONG SELL"
        ),
    }


def recommendation_trends(ticker: str) -> dict | None:
    """Analyst buy/hold/sell consensus from latest period."""
    if not _api_key():
        return None
    settings = _get_settings()
    ttl = settings.get("finnhub_cache_ttl_seconds", 21600)
    return cached(
        namespace="finnhub_recommendations",
        key=ticker,
        ttl_seconds=ttl,
        loader=lambda: _fetch_recommendation_trends(ticker),
        enabled=settings.get("cache_enabled", True),
    )


# ── Analyst upgrade / downgrade events ───────────────────────────────────────

def _fetch_upgrade_downgrade(ticker: str, days_back: int = 90) -> list | None:
    end = datetime.now().date()
    start = end - timedelta(days=days_back)
    data = _request(
        "/stock/upgrade-downgrade",
        {"symbol": ticker, "from": start.isoformat(), "to": end.isoformat()},
    )
    if not data or not isinstance(data, list):
        return None
    rows = []
    for row in data[:8]:
        rows.append({
            "ticker": ticker,
            "date": row.get("gradeTime") or row.get("date"),
            "firm": row.get("company"),
            "from_grade": row.get("fromGrade"),
            "to_grade": row.get("toGrade"),
            "action": row.get("action"),
        })
    return rows or None


def upgrade_downgrade(ticker: str, days_back: int = 90) -> list | None:
    """Recent analyst upgrade/downgrade events."""
    if not _api_key():
        return None
    settings = _get_settings()
    ttl = settings.get("finnhub_cache_ttl_seconds", 21600)
    return cached(
        namespace="finnhub_upgrades",
        key=f"{ticker}_{days_back}",
        ttl_seconds=ttl,
        loader=lambda: _fetch_upgrade_downgrade(ticker, days_back),
        enabled=settings.get("cache_enabled", True),
    )


# ── News sentiment ────────────────────────────────────────────────────────────

def _fetch_news_sentiment(ticker: str) -> dict | None:
    data = _request("/news-sentiment", {"symbol": ticker})
    if not data or not isinstance(data, dict):
        return None
    sentiment = data.get("sentiment") or {}
    bullish = sentiment.get("bullishPercent")
    bearish = sentiment.get("bearishPercent")
    if bullish is None and bearish is None:
        return None
    return {
        "ticker": ticker,
        "bullish_pct": bullish,
        "bearish_pct": bearish,
        "company_news_score": data.get("companyNewsScore"),  # vs market avg
        "sector_avg_news_score": data.get("sectorAverageNewsScore"),
        "buzz_articles_in_last_week": (data.get("buzz") or {}).get("articlesInLastWeek"),
        "buzz_weekly_avg": (data.get("buzz") or {}).get("weeklyAverage"),
    }


def news_sentiment(ticker: str) -> dict | None:
    """Aggregate news sentiment + buzz vs sector average."""
    if not _api_key():
        return None
    settings = _get_settings()
    ttl = settings.get("finnhub_cache_ttl_seconds", 21600)
    return cached(
        namespace="finnhub_sentiment",
        key=ticker,
        ttl_seconds=ttl,
        loader=lambda: _fetch_news_sentiment(ticker),
        enabled=settings.get("cache_enabled", True),
    )


# ── Earnings surprises (historical) ──────────────────────────────────────────

def _fetch_earnings_surprises(ticker: str, limit: int = 4) -> list | None:
    data = _request("/stock/earnings", {"symbol": ticker, "limit": limit})
    if not data or not isinstance(data, list):
        return None
    out = []
    for q in data:
        actual = q.get("actual")
        estimate = q.get("estimate")
        if actual is None or estimate is None or estimate == 0:
            continue
        surprise_pct = (actual - estimate) / abs(estimate) * 100
        out.append({
            "period": q.get("period"),
            "year": q.get("year"),
            "quarter": q.get("quarter"),
            "eps_actual": actual,
            "eps_estimate": estimate,
            "surprise_pct": round(surprise_pct, 2),
        })
    return out or None


def earnings_surprises(ticker: str, limit: int = 4) -> list | None:
    """Last N quarters of EPS beat/miss vs estimates."""
    if not _api_key():
        return None
    settings = _get_settings()
    ttl = settings.get("finnhub_cache_ttl_seconds", 21600)
    return cached(
        namespace="finnhub_surprises",
        key=f"{ticker}_{limit}",
        ttl_seconds=ttl,
        loader=lambda: _fetch_earnings_surprises(ticker, limit),
        enabled=settings.get("cache_enabled", True),
    )


# ── Insider transactions ──────────────────────────────────────────────────────

def _fetch_insider_summary(ticker: str, days: int = 90) -> dict | None:
    end = datetime.now().date()
    start = end - timedelta(days=days)
    data = _request(
        "/stock/insider-transactions",
        {"symbol": ticker, "from": start.isoformat(), "to": end.isoformat()},
    )
    if not data or not isinstance(data, dict):
        return None
    rows = data.get("data") or []
    if not rows:
        return None
    # Net shares: positive = net buying
    net_shares = sum((r.get("change") or 0) for r in rows)
    n_buys = sum(1 for r in rows if (r.get("change") or 0) > 0)
    n_sells = sum(1 for r in rows if (r.get("change") or 0) < 0)
    return {
        "ticker": ticker,
        "lookback_days": days,
        "transactions": len(rows),
        "net_shares": net_shares,
        "buys": n_buys,
        "sells": n_sells,
        "signal": "BUYING" if net_shares > 0 else "SELLING" if net_shares < 0 else "NEUTRAL",
    }


def insider_summary(ticker: str, days: int = 90) -> dict | None:
    """Last 90 days of insider buying/selling signal."""
    if not _api_key():
        return None
    settings = _get_settings()
    ttl = settings.get("finnhub_cache_ttl_seconds", 21600)
    return cached(
        namespace="finnhub_insider",
        key=f"{ticker}_{days}",
        ttl_seconds=ttl,
        loader=lambda: _fetch_insider_summary(ticker, days),
        enabled=settings.get("cache_enabled", True),
    )


if __name__ == "__main__":
    import json
    if not _api_key():
        print("FINNHUB_API_KEY not set — skipping live test")
    else:
        for fn, name in [
            (lambda: earnings_calendar("NVDA"), "earnings_calendar(NVDA)"),
            (lambda: recommendation_trends("NVDA"), "recommendation_trends(NVDA)"),
            (lambda: upgrade_downgrade("NVDA"), "upgrade_downgrade(NVDA)"),
            (lambda: news_sentiment("NVDA"), "news_sentiment(NVDA)"),
            (lambda: earnings_surprises("NVDA"), "earnings_surprises(NVDA)"),
            (lambda: insider_summary("NVDA"), "insider_summary(NVDA)"),
        ]:
            print(f"\n── {name} ──")
            print(json.dumps(fn(), indent=2, default=str))
