"""
news_fetcher.py
Fetches recent news headlines per ticker via yfinance (last N days).
No API key required.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import yfinance as yf

SETTINGS_PATH = Path(__file__).parent.parent / "config" / "settings.json"


def load_settings() -> dict:
    with open(SETTINGS_PATH) as f:
        return json.load(f)


def get_news(ticker: str, lookback_days: int = 7, max_articles: int = 5) -> list[dict]:
    """
    Fetch recent news for a ticker.
    Returns a list of dicts: {title, publisher, published_at, summary, link}
    """
    try:
        t = yf.Ticker(ticker)
        news = t.news or []

        cutoff = datetime.now() - timedelta(days=lookback_days)
        articles = []

        for item in news:
            # yfinance returns providerPublishTime as unix timestamp
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

            articles.append({
                "title": title,
                "publisher": publisher,
                "published_at": pub_dt.strftime("%Y-%m-%d %H:%M"),
                "summary": summary[:300] if summary else "",
                "link": link,
            })

            if len(articles) >= max_articles:
                break

        return articles

    except Exception as e:
        return [{"title": f"Error fetching news: {e}", "publisher": "", "published_at": "", "summary": "", "link": ""}]


def get_news_for_tickers(tickers: list, lookback_days: int = None) -> dict:
    """Fetch news for multiple tickers. Returns {ticker: [articles]}."""
    settings = load_settings()
    if lookback_days is None:
        lookback_days = settings.get("news_lookback_days", 7)

    result = {}
    for ticker in tickers:
        result[ticker] = get_news(ticker, lookback_days)

    return result


def format_news_for_prompt(news_by_ticker: dict) -> str:
    """Format news dict into a readable string for the Claude prompt."""
    lines = []
    for ticker, articles in news_by_ticker.items():
        lines.append(f"\n### {ticker} News")
        if not articles:
            lines.append("  No recent news.")
            continue
        for a in articles:
            lines.append(f"  - [{a['published_at']}] {a['title']} ({a['publisher']})")
            if a.get("summary"):
                lines.append(f"    {a['summary'][:200]}")
    return "\n".join(lines)


if __name__ == "__main__":
    tickers = ["NVDA", "PLTR"]
    news = get_news_for_tickers(tickers)
    print(format_news_for_prompt(news))
