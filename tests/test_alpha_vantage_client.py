"""Error-path coverage for src.alpha_vantage_client."""

import pytest
import requests

from src import alpha_vantage_client as av


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, json_exc=None):
        self.status_code = status_code
        self._json_data = json_data
        self._json_exc = json_exc

    def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self._json_data


@pytest.fixture(autouse=True)
def _no_cache(monkeypatch):
    monkeypatch.setattr(av, "load_settings", lambda: {"cache_enabled": False})


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    # Disable the rate-limit sleep and tenacity backoff.
    monkeypatch.setattr(av.time, "sleep", lambda *_a, **_k: None)
    av._last_call_time = 0.0


def _set_key(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "test-key")


def _stub_get(monkeypatch, response):
    monkeypatch.setattr(requests, "get", lambda *a, **k: response)


def test_request_no_key(monkeypatch):
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    assert av._request({"function": "X"}) is None


def test_request_http_error(monkeypatch):
    _set_key(monkeypatch)
    _stub_get(monkeypatch, FakeResponse(status_code=500))
    assert av._request({"function": "X"}) is None


def test_request_malformed_json(monkeypatch):
    _set_key(monkeypatch)
    _stub_get(monkeypatch, FakeResponse(status_code=200, json_exc=ValueError("bad")))
    assert av._request({"function": "X"}) is None


def test_request_note_soft_fail(monkeypatch):
    _set_key(monkeypatch)
    _stub_get(monkeypatch, FakeResponse(status_code=200, json_data={"Note": "rate limited"}))
    assert av._request({"function": "X"}) is None


def test_request_information_soft_fail(monkeypatch):
    _set_key(monkeypatch)
    _stub_get(monkeypatch, FakeResponse(status_code=200, json_data={"Information": "premium"}))
    assert av._request({"function": "X"}) is None


def test_request_valid(monkeypatch):
    _set_key(monkeypatch)
    _stub_get(monkeypatch, FakeResponse(status_code=200, json_data={"feed": []}))
    assert av._request({"function": "X"}) == {"feed": []}


def test_news_sentiment_no_key(monkeypatch):
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    assert av.news_sentiment("NVDA") is None


def test_earnings_calendar_no_key(monkeypatch):
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    assert av.earnings_calendar("NVDA") is None


def test_fetch_news_sentiment_empty_feed(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setattr(av, "_request", lambda *a, **k: {"feed": []})
    assert av._fetch_news_sentiment("NVDA") is None


def test_fetch_news_sentiment_no_scores(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setattr(av, "_request", lambda *a, **k: {"feed": [{"title": "x"}]})
    assert av._fetch_news_sentiment("NVDA") is None


def test_fetch_news_sentiment_parses(monkeypatch):
    _set_key(monkeypatch)
    feed = [
        {
            "overall_sentiment_score": "0.5",
            "ticker_sentiment": [{"ticker": "NVDA", "ticker_sentiment_score": "0.6"}],
        }
    ]
    monkeypatch.setattr(av, "_request", lambda *a, **k: {"feed": feed})
    out = av._fetch_news_sentiment("NVDA")
    assert out["label"] == "BULLISH"
    assert out["articles_analyzed"] == 1


def test_fetch_earnings_calendar_empty(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setattr(av, "_request", lambda *a, **k: {"quarterlyEarnings": []})
    assert av._fetch_earnings_calendar("NVDA") is None


def test_fetch_earnings_calendar_none(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setattr(av, "_request", lambda *a, **k: None)
    assert av._fetch_earnings_calendar("NVDA") is None


def test_fetch_earnings_calendar_parses(monkeypatch):
    _set_key(monkeypatch)
    data = {
        "quarterlyEarnings": [
            {"fiscalDateEnding": "2026-03-31", "reportedEPS": "1.2", "estimatedEPS": "1.0", "surprisePercentage": "20"},
            {"fiscalDateEnding": "2026-06-30", "reportedEPS": "None", "estimatedEPS": "1.3"},
        ]
    }
    monkeypatch.setattr(av, "_request", lambda *a, **k: data)
    out = av._fetch_earnings_calendar("NVDA")
    assert out["surprise_pct"] == 20.0
    assert out["next_period"] == "2026-06-30"
