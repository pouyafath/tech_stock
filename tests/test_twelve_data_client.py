"""Error-path coverage for src.twelve_data_client."""

import pytest
import requests

from src import twelve_data_client as td


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
    monkeypatch.setattr(td, "load_settings", lambda: {"cache_enabled": False})


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(td.time, "sleep", lambda *_a, **_k: None)
    td._last_call_time = 0.0


def _set_key(monkeypatch):
    monkeypatch.setenv("TWELVE_DATA_API_KEY", "test-key")


def _stub_get(monkeypatch, response):
    monkeypatch.setattr(requests, "get", lambda *a, **k: response)


def test_request_no_key(monkeypatch):
    monkeypatch.delenv("TWELVE_DATA_API_KEY", raising=False)
    assert td._request("/quote", {}) is None


def test_request_http_error(monkeypatch):
    _set_key(monkeypatch)
    _stub_get(monkeypatch, FakeResponse(status_code=500))
    assert td._request("/quote", {}) is None


def test_request_malformed_json(monkeypatch):
    _set_key(monkeypatch)
    _stub_get(monkeypatch, FakeResponse(status_code=200, json_exc=ValueError("bad")))
    assert td._request("/quote", {}) is None


def test_request_soft_error_body(monkeypatch):
    _set_key(monkeypatch)
    _stub_get(monkeypatch, FakeResponse(status_code=200, json_data={"status": "error", "message": "bad symbol", "code": 400}))
    assert td._request("/quote", {}) is None


def test_request_valid(monkeypatch):
    _set_key(monkeypatch)
    _stub_get(monkeypatch, FakeResponse(status_code=200, json_data={"close": "10"}))
    assert td._request("/quote", {}) == {"close": "10"}


def test_quote_no_key(monkeypatch):
    monkeypatch.delenv("TWELVE_DATA_API_KEY", raising=False)
    assert td.quote("NVDA") is None


def test_earnings_no_key(monkeypatch):
    monkeypatch.delenv("TWELVE_DATA_API_KEY", raising=False)
    assert td.earnings("NVDA") is None


def test_fetch_quote_non_dict(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setattr(td, "_request", lambda *a, **k: None)
    assert td._fetch_quote("NVDA") is None


def test_fetch_quote_parse_error(monkeypatch):
    _set_key(monkeypatch)
    # Missing "close" -> KeyError caught.
    monkeypatch.setattr(td, "_request", lambda *a, **k: {"volume": "100"})
    assert td._fetch_quote("NVDA") is None


def test_fetch_quote_parses(monkeypatch):
    _set_key(monkeypatch)
    data = {
        "close": "110.5",
        "percent_change": "1.5",
        "volume": "1000",
        "fifty_two_week": {"high": "120", "low": "80"},
        "exchange": "NASDAQ",
        "currency": "USD",
    }
    monkeypatch.setattr(td, "_request", lambda *a, **k: data)
    out = td._fetch_quote("NVDA")
    assert out["price"] == 110.5
    assert out["52w_high"] == 120.0
    assert out["source"] == "twelve_data"


def test_fetch_earnings_empty(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setattr(td, "_request", lambda *a, **k: {"earnings": []})
    assert td._fetch_earnings("NVDA") is None


def test_fetch_earnings_non_dict(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setattr(td, "_request", lambda *a, **k: ["x"])
    assert td._fetch_earnings("NVDA") is None


def test_fetch_earnings_parses(monkeypatch):
    _set_key(monkeypatch)
    data = {
        "earnings": [
            {"date": "2026-08-01", "actual": None, "estimate": "1.3"},
            {"date": "2026-05-01", "actual": "1.2", "estimate": "1.0", "surprise": "0.2", "surprise_percentage": "20"},
        ]
    }
    monkeypatch.setattr(td, "_request", lambda *a, **k: data)
    out = td._fetch_earnings("NVDA")
    assert out["next_earnings_date"] == "2026-08-01"
    assert out["last_eps_actual"] == "1.2"
