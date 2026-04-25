"""
news_fetcher.py
Fetches recent news headlines per ticker via yfinance (free) and scores
each headline with VADER sentiment (free, pure-Python).

Resilience:
  - tenacity retries on transient failures
  - pickle cache in data/.cache/news/ (default TTL 1h)
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import yfinance as yf
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.cache import cached
from src.config import load_settings

# VADER is lazy-loaded — instantiating the analyzer is ~50ms, skip if disabled
_vader_analyzer = None


def _get_vader():
    """Lazy-instantiate the VADER sentiment analyzer."""
    global _vader_analyzer
    if _vader_analyzer is None:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        _vader_analyzer = SentimentIntensityAnalyzer()
    return _vader_analyzer


def score_sentiment(text: str) -> float:
    """Return VADER compound sentiment score, -1.0 (bearish) to +1.0 (bullish)."""
    if not text:
        return 0.0
    try:
        return _get_vader().polarity_scores(text)["compound"]
    except Exception:
        return 0.0


def aggregate_sentiment(articles: list[dict]) -> dict:
    """
    Summarize article sentiments: average score + bullish/bearish counts.
    Thresholds: >0.2 bullish, <-0.2 bearish.
    """
    if not articles:
        return {
            "avg_sentiment": 0.0,
            "article_count": 0,
            "bullish_count": 0,
            "bearish_count": 0,
            "neutral_count": 0,
        }
    scores = [a.get("sentiment", 0.0) for a in articles if "sentiment" in a]
    if not scores:
        return {
            "avg_sentiment": 0.0,
            "article_count": len(articles),
            "bullish_count": 0,
            "bearish_count": 0,
            "neutral_count": len(articles),
        }
    avg = sum(scores) / len(scores)
    bullish = sum(1 for s in scores if s > 0.2)
    bearish = sum(1 for s in scores if s < -0.2)
    neutral = len(scores) - bullish - bearish
    return {
        "avg_sentiment": round(avg, 3),
        "article_count": len(articles),
        "bullish_count": bullish,
        "bearish_count": bearish,
        "neutral_count": neutral,
    }


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
    reraise=True,
)
def _fetch_news_raw(ticker: str, lookback_days: int, max_articles: int, enable_sentiment: bool) -> list[dict]:
    """Raw news fetch with retry. Scores sentiment inline if enabled."""
    t = yf.Ticker(ticker)
    news = t.news or []

    cutoff = datetime.now() - timedelta(days=lookback_days)
    articles = []

    for item in news:
        pub_time = item.get("providerPublishTime") or item.get("published", 0)
        if isinstance(pub_time, (int, float)):
            pub_dt = datetime.fromtimestamp(pub_time)
        else:
            pub_dt = datetime.now()

        if pub_dt < cutoff:
            continue

        # Handle both old and new yfinance news format
        content = item.get("content", {})
        title = content.get("title") or item.get("title", "")
        summary = content.get("summary") or item.get("summary", "")
        publisher = (content.get("provider", {}) or {}).get("displayName") or item.get("publisher", "")
        link = (content.get("canonicalUrl", {}) or {}).get("url") or item.get("link", "")

        if not title:
            continue

        article = {
            "title": title,
            "publisher": publisher,
            "published_at": pub_dt.strftime("%Y-%m-%d %H:%M"),
            "summary": summary[:300] if summary else "",
            "link": link,
        }

        if enable_sentiment:
            article["sentiment"] = round(score_sentiment(f"{title}. {summary or ''}"), 3)

        articles.append(article)

        if len(articles) >= max_articles:
            break

    return articles


def get_news(ticker: str, lookback_days: int = 7, max_articles: int = 5) -> list[dict]:
    """
    Fetch recent news for a ticker. Returns list of dicts with title, publisher,
    published_at, summary, link, and (if enabled) sentiment score.
    """
    settings = load_settings()
    cache_enabled = settings.get("cache_enabled", True)
    ttl = settings.get("cache_ttl_seconds", 3600)
    enable_sentiment = settings.get("enable_sentiment", True)

    try:
        return cached(
            namespace="news",
            key=f"{ticker}_{lookback_days}_{max_articles}_{int(enable_sentiment)}",
            ttl_seconds=ttl,
            loader=lambda: _fetch_news_raw(ticker, lookback_days, max_articles, enable_sentiment),
            enabled=cache_enabled,
        )
    except Exception as e:
        return [{
            "title": f"Error fetching news: {e}",
            "publisher": "",
            "published_at": "",
            "summary": "",
            "link": "",
        }]


def get_news_for_tickers(tickers: list, lookback_days: int = None) -> dict:
    """Fetch news for multiple tickers in parallel. Returns {ticker: [articles]}."""
    settings = load_settings()
    if lookback_days is None:
        lookback_days = settings.get("news_lookback_days", 7)

    result = {}
    max_workers = min(8, len(tickers)) if tickers else 1

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(get_news, t, lookback_days): t for t in tickers}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                result[ticker] = future.result()
            except Exception:
                result[ticker] = [{
                    "title": "Error fetching news",
                    "publisher": "",
                    "published_at": "",
                    "summary": "",
                    "link": "",
                }]

    return result


def format_news_for_prompt(news_by_ticker: dict) -> str:
    """Format news dict into a readable string for the Claude prompt."""
    lines = []
    for ticker, articles in news_by_ticker.items():
        lines.append(f"\n### {ticker} News")
        if not articles:
            lines.append("  No recent news.")
            continue

        agg = aggregate_sentiment(articles)
        if agg["article_count"] > 0 and "sentiment" in articles[0]:
            lines.append(
                f"  [sentiment: avg={agg['avg_sentiment']:+.2f}, "
                f"{agg['bullish_count']} bullish / {agg['neutral_count']} neutral / "
                f"{agg['bearish_count']} bearish]"
            )
        for a in articles:
            senti = f" ({a['sentiment']:+.2f})" if "sentiment" in a else ""
            lines.append(f"  - [{a['published_at']}] {a['title']}{senti} ({a['publisher']})")
            if a.get("summary"):
                lines.append(f"    {a['summary'][:200]}")
    return "\n".join(lines)


if __name__ == "__main__":
    tickers = ["NVDA", "PLTR"]
    news = get_news_for_tickers(tickers)
    print(format_news_for_prompt(news))

    # Sentiment self-test
    assert score_sentiment("NVDA beats earnings, stock soars") > 0.2, "Bullish test failed"
    assert score_sentiment("NVDA crashes on guidance miss, worst drop in years") < -0.2, "Bearish test failed"
    print("\n✓ news_fetcher.py sentiment self-test passed")
