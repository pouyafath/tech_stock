from datetime import datetime

from src import news_fetcher


def test_fetch_news_raw_parses_current_yfinance_pubdate(monkeypatch):
    now = datetime.now().replace(microsecond=0).isoformat() + "Z"

    class FakeTicker:
        news = [
            {
                "content": {
                    "title": "AMD jumps after AI accelerator update",
                    "summary": "Shares rose after a product update.",
                    "pubDate": now,
                    "provider": {"displayName": "Yahoo Finance"},
                    "canonicalUrl": {"url": "https://example.com/amd"},
                }
            }
        ]

    monkeypatch.setattr(news_fetcher.yf, "Ticker", lambda ticker: FakeTicker())

    articles = news_fetcher._fetch_news_raw("AMD", lookback_days=1, max_articles=5, enable_sentiment=False)

    assert len(articles) == 1
    assert articles[0]["title"] == "AMD jumps after AI accelerator update"
    assert articles[0]["publisher"] == "Yahoo Finance"
    assert articles[0]["link"] == "https://example.com/amd"
