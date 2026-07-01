from datetime import datetime, timedelta

from src import news_fetcher


def test_score_sentiment_empty_and_error_paths(monkeypatch):
    assert news_fetcher.score_sentiment("") == 0.0
    # A bullish headline scores positive; a bearish one negative.
    assert news_fetcher.score_sentiment("great record profit surge growth") > 0
    assert news_fetcher.score_sentiment("terrible crash collapse bankruptcy fraud") < 0
    # A broken analyzer degrades to neutral, never raises.
    monkeypatch.setattr(news_fetcher, "_get_vader", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert news_fetcher.score_sentiment("anything") == 0.0


def test_aggregate_sentiment_buckets():
    assert news_fetcher.aggregate_sentiment([]) == {
        "avg_sentiment": 0.0,
        "article_count": 0,
        "bullish_count": 0,
        "bearish_count": 0,
        "neutral_count": 0,
    }
    # Articles without a sentiment key count as neutral only.
    no_score = news_fetcher.aggregate_sentiment([{"title": "x"}, {"title": "y"}])
    assert no_score["article_count"] == 2
    assert no_score["neutral_count"] == 2
    assert no_score["bullish_count"] == 0

    mixed = news_fetcher.aggregate_sentiment([{"sentiment": 0.8}, {"sentiment": -0.5}, {"sentiment": 0.1}])
    assert mixed["bullish_count"] == 1
    assert mixed["bearish_count"] == 1
    assert mixed["neutral_count"] == 1
    assert mixed["avg_sentiment"] == round((0.8 - 0.5 + 0.1) / 3, 3)


def test_parse_publish_time_shapes():
    # Unix epoch seconds.
    epoch = 1_700_000_000
    assert news_fetcher._parse_publish_time({"providerPublishTime": epoch}) == datetime.fromtimestamp(epoch)
    # ISO string with a Z suffix parses (and is made tz-naive).
    iso = news_fetcher._parse_publish_time({"content": {"pubDate": "2026-01-02T03:04:05Z"}})
    assert iso.tzinfo is None and iso.year == 2026
    # Garbage / missing falls back to "now" without raising.
    before = datetime.now()
    fallback = news_fetcher._parse_publish_time({"providerPublishTime": "not-a-date"})
    assert before <= fallback <= datetime.now() + timedelta(seconds=5)


def test_fetch_news_raw_filters_old_and_untitled(monkeypatch):
    old = (datetime.now() - timedelta(days=30)).isoformat()
    fresh = datetime.now().isoformat()

    class FakeTicker:
        news = [
            {"content": {"title": "Old but titled", "pubDate": old}},  # too old → dropped
            {"content": {"title": "", "pubDate": fresh}},  # no title → dropped
            {"content": {"title": "Fresh headline", "summary": "s" * 500, "pubDate": fresh}},
        ]

    monkeypatch.setattr(news_fetcher.yf, "Ticker", lambda ticker: FakeTicker())
    articles = news_fetcher._fetch_news_raw("AMD", lookback_days=7, max_articles=5, enable_sentiment=True)
    assert len(articles) == 1
    assert articles[0]["title"] == "Fresh headline"
    assert len(articles[0]["summary"]) <= 300  # summary is truncated
    assert "sentiment" in articles[0]  # scored inline when enabled


def test_get_news_for_tickers_isolates_failures(monkeypatch):
    def fake_get_news(ticker, lookback_days):
        if ticker == "BAD":
            raise ConnectionError("down")
        return [{"title": f"{ticker} news", "publisher": "p", "published_at": "", "summary": "", "link": ""}]

    monkeypatch.setattr(news_fetcher, "get_news", fake_get_news)
    monkeypatch.setattr(news_fetcher, "load_settings", lambda: {"news_lookback_days": 7, "yfinance_max_workers": 2})
    result = news_fetcher.get_news_for_tickers(["GOOD", "BAD"])
    assert result["GOOD"][0]["title"] == "GOOD news"
    # A failing ticker yields a placeholder error article, not a crash.
    assert result["BAD"][0]["title"] == "Error fetching news"


def test_format_news_for_prompt_renders_sentiment_and_empty():
    text = news_fetcher.format_news_for_prompt(
        {
            "AMD": [{"title": "Up", "publisher": "Yahoo", "published_at": "2026-01-01", "summary": "note", "sentiment": 0.5}],
            "NVDA": [],
        }
    )
    assert "### AMD News" in text
    assert "sentiment: avg=+0.50" in text
    assert "(+0.50)" in text
    assert "### NVDA News" in text
    assert "No recent news." in text


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
