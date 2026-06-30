"""Error-path coverage for src.coingecko_client."""

import pytest
import requests

from src import coingecko_client as cg


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
    monkeypatch.setattr(cg, "load_settings", lambda: {"cache_enabled": False})


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)


def _stub_get(monkeypatch, response):
    monkeypatch.setattr(requests, "get", lambda *a, **k: response)


def test_is_pro_key():
    assert cg._is_pro_key("CG-abc") is False
    assert cg._is_pro_key("prokey123") is True
    assert cg._is_pro_key("") is False


def test_base_url_pro(monkeypatch):
    monkeypatch.setenv("COINGECKO_API_KEY", "prokey123")
    assert cg._base_url() == cg.PRO_BASE_URL


def test_base_url_public(monkeypatch):
    monkeypatch.setenv("COINGECKO_API_KEY", "CG-demo")
    assert cg._base_url() == cg.BASE_URL


def test_request_429_retries(monkeypatch):
    monkeypatch.delenv("COINGECKO_API_KEY", raising=False)
    _stub_get(monkeypatch, FakeResponse(status_code=429))
    with pytest.raises(requests.RequestException):
        cg._request("/x")


def test_request_http_error(monkeypatch):
    monkeypatch.delenv("COINGECKO_API_KEY", raising=False)
    _stub_get(monkeypatch, FakeResponse(status_code=403))
    assert cg._request("/x") is None


def test_request_malformed_json(monkeypatch):
    monkeypatch.delenv("COINGECKO_API_KEY", raising=False)
    _stub_get(monkeypatch, FakeResponse(status_code=200, json_exc=ValueError("bad")))
    assert cg._request("/x") is None


def test_request_valid_with_demo_header(monkeypatch):
    monkeypatch.setenv("COINGECKO_API_KEY", "CG-demo")
    _stub_get(monkeypatch, FakeResponse(status_code=200, json_data=[{"id": "bitcoin"}]))
    assert cg._request("/x") == [{"id": "bitcoin"}]


def test_fetch_crypto_context_not_list(monkeypatch):
    monkeypatch.setattr(cg, "_request", lambda *a, **k: {"error": "x"})
    assert cg._fetch_crypto_context() is None


def test_fetch_crypto_context_none(monkeypatch):
    monkeypatch.setattr(cg, "_request", lambda *a, **k: None)
    assert cg._fetch_crypto_context() is None


def test_fetch_crypto_context_risk_off(monkeypatch):
    rows = [
        {
            "id": "bitcoin",
            "current_price": 60000,
            "price_change_percentage_24h": -2.0,
            "price_change_percentage_7d_in_currency": -20.0,
        },
        {
            "id": "ethereum",
            "current_price": 3000,
            "price_change_percentage_24h": -1.0,
        },
    ]
    monkeypatch.setattr(cg, "_request", lambda *a, **k: rows)
    # Fear & greed fetch fails -> exercises the except branch.
    _stub_get(monkeypatch, FakeResponse(status_code=200, json_exc=ValueError("no fng")))
    out = cg._fetch_crypto_context()
    assert out["risk_signal"] == "RISK-OFF"
    assert out["btc_change_7d"] == -20.0
    assert out["fear_greed_index"] is None


def test_fetch_crypto_context_fear_greed_caution(monkeypatch):
    rows = [
        {
            "id": "bitcoin",
            "current_price": 60000,
            "price_change_percentage_24h": 0.5,
            "price_change_percentage_7d_in_currency": 1.0,
        },
        {"id": "ethereum", "current_price": 3000, "price_change_percentage_24h": 0.2},
    ]
    monkeypatch.setattr(cg, "_request", lambda *a, **k: rows)
    fng = {"data": [{"value": "10", "value_classification": "Extreme Fear"}]}
    _stub_get(monkeypatch, FakeResponse(status_code=200, json_data=fng))
    out = cg._fetch_crypto_context()
    assert out["risk_signal"] == "CAUTION"
    assert out["fear_greed_index"] == 10


def test_crypto_context_loader_exception(monkeypatch):
    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(cg, "_fetch_crypto_context", boom)
    assert cg.crypto_context() is None
