"""Error-path coverage for src.finnhub_client."""

import pytest
import requests

from src import finnhub_client


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
    monkeypatch.setattr(finnhub_client, "load_settings", lambda: {"cache_enabled": False})


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)


def _set_key(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")


def _stub_get(monkeypatch, response):
    monkeypatch.setattr(requests, "get", lambda *a, **k: response)


def test_request_no_api_key(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    assert finnhub_client._request("/x", {}) is None


def test_request_429_retries(monkeypatch):
    _set_key(monkeypatch)
    _stub_get(monkeypatch, FakeResponse(status_code=429))
    with pytest.raises(requests.RequestException):
        finnhub_client._request("/x", {})


def test_request_http_error(monkeypatch):
    _set_key(monkeypatch)
    _stub_get(monkeypatch, FakeResponse(status_code=404))
    assert finnhub_client._request("/x", {}) is None


def test_request_malformed_json(monkeypatch):
    _set_key(monkeypatch)
    _stub_get(monkeypatch, FakeResponse(status_code=200, json_exc=ValueError("bad")))
    assert finnhub_client._request("/x", {}) is None


def test_request_valid(monkeypatch):
    _set_key(monkeypatch)
    _stub_get(monkeypatch, FakeResponse(status_code=200, json_data={"a": 1}))
    assert finnhub_client._request("/x", {}) == {"a": 1}


# ── public functions return None without key ──────────────────────────────────


@pytest.mark.parametrize(
    "call",
    [
        lambda: finnhub_client.earnings_calendar("NVDA"),
        lambda: finnhub_client.recommendation_trends("NVDA"),
        lambda: finnhub_client.upgrade_downgrade("NVDA"),
        lambda: finnhub_client.news_sentiment("NVDA"),
        lambda: finnhub_client.earnings_surprises("NVDA"),
        lambda: finnhub_client.insider_summary("NVDA"),
    ],
)
def test_public_no_key_returns_none(monkeypatch, call):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    assert call() is None


# ── _fetch_* malformed/empty handling ─────────────────────────────────────────


def test_earnings_calendar_empty(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setattr(finnhub_client, "_request", lambda *a, **k: {"earningsCalendar": []})
    assert finnhub_client._fetch_earnings_calendar("NVDA", 30) is None


def test_earnings_calendar_none(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setattr(finnhub_client, "_request", lambda *a, **k: None)
    assert finnhub_client._fetch_earnings_calendar("NVDA", 30) is None


def test_earnings_calendar_parses(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setattr(
        finnhub_client,
        "_request",
        lambda *a, **k: {"earningsCalendar": [{"date": "2026-07-01", "epsEstimate": 1.2}]},
    )
    out = finnhub_client._fetch_earnings_calendar("NVDA", 30)
    assert out["date"] == "2026-07-01"
    assert out["eps_estimate"] == 1.2


def test_recommendation_trends_not_list(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setattr(finnhub_client, "_request", lambda *a, **k: {"x": 1})
    assert finnhub_client._fetch_recommendation_trends("NVDA") is None


def test_recommendation_trends_zero_total(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setattr(finnhub_client, "_request", lambda *a, **k: [{"buy": 0, "hold": 0, "sell": 0}])
    assert finnhub_client._fetch_recommendation_trends("NVDA") is None


def test_recommendation_trends_parses(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setattr(
        finnhub_client,
        "_request",
        lambda *a, **k: [{"period": "2026-06", "strongBuy": 5, "buy": 5, "hold": 1, "sell": 0}],
    )
    out = finnhub_client._fetch_recommendation_trends("NVDA")
    assert out["consensus_label"] == "STRONG BUY"


def test_upgrade_downgrade_not_list(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setattr(finnhub_client, "_request", lambda *a, **k: {"x": 1})
    assert finnhub_client._fetch_upgrade_downgrade("NVDA") is None


def test_upgrade_downgrade_empty(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setattr(finnhub_client, "_request", lambda *a, **k: [])
    assert finnhub_client._fetch_upgrade_downgrade("NVDA") is None


def test_news_sentiment_no_sentiment(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setattr(finnhub_client, "_request", lambda *a, **k: {"sentiment": {}})
    assert finnhub_client._fetch_news_sentiment("NVDA") is None


def test_news_sentiment_parses(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setattr(
        finnhub_client,
        "_request",
        lambda *a, **k: {"sentiment": {"bullishPercent": 0.6, "bearishPercent": 0.4}},
    )
    out = finnhub_client._fetch_news_sentiment("NVDA")
    assert out["bullish_pct"] == 0.6


def test_earnings_surprises_skips_missing(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setattr(
        finnhub_client,
        "_request",
        lambda *a, **k: [{"actual": None, "estimate": 1.0}, {"actual": 1.0, "estimate": 0}],
    )
    assert finnhub_client._fetch_earnings_surprises("NVDA") is None


def test_earnings_surprises_parses(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setattr(
        finnhub_client,
        "_request",
        lambda *a, **k: [{"actual": 1.5, "estimate": 1.0, "period": "2026-Q1"}],
    )
    out = finnhub_client._fetch_earnings_surprises("NVDA")
    assert out[0]["surprise_pct"] == 50.0


def test_insider_summary_empty(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setattr(finnhub_client, "_request", lambda *a, **k: {"data": []})
    assert finnhub_client._fetch_insider_summary("NVDA") is None


def test_insider_summary_signal(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setattr(
        finnhub_client,
        "_request",
        lambda *a, **k: {"data": [{"change": 100}, {"change": -10}]},
    )
    out = finnhub_client._fetch_insider_summary("NVDA")
    assert out["signal"] == "BUYING"
    assert out["buys"] == 1
    assert out["sells"] == 1
