"""Error-path coverage for src.polygon_client."""

import pytest
import requests

from src import polygon_client


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
    """Bypass the on-disk cache so loaders run directly."""
    monkeypatch.setattr(polygon_client, "load_settings", lambda: {"cache_enabled": False})


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Keep tenacity retries fast."""
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)


def _set_key(monkeypatch):
    monkeypatch.setenv("POLYGON_API_KEY", "test-key")


def _stub_get(monkeypatch, response):
    monkeypatch.setattr(requests, "get", lambda *a, **k: response)


def test_request_no_api_key_returns_none(monkeypatch):
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    assert polygon_client._request("/x") is None


def test_request_403_paid_only_returns_none(monkeypatch):
    _set_key(monkeypatch)
    _stub_get(monkeypatch, FakeResponse(status_code=403))
    assert polygon_client._request("/x") is None


def test_request_429_raises_for_retry(monkeypatch):
    _set_key(monkeypatch)
    _stub_get(monkeypatch, FakeResponse(status_code=429))
    with pytest.raises(requests.RequestException):
        polygon_client._request("/x")


def test_request_500_returns_none(monkeypatch):
    _set_key(monkeypatch)
    _stub_get(monkeypatch, FakeResponse(status_code=500))
    assert polygon_client._request("/x") is None


def test_request_malformed_json_returns_none(monkeypatch):
    _set_key(monkeypatch)
    _stub_get(monkeypatch, FakeResponse(status_code=200, json_exc=ValueError("bad json")))
    assert polygon_client._request("/x") is None


def test_request_valid_json(monkeypatch):
    _set_key(monkeypatch)
    _stub_get(monkeypatch, FakeResponse(status_code=200, json_data={"ok": 1}))
    assert polygon_client._request("/x") == {"ok": 1}


def test_stock_snapshot_no_api_key(monkeypatch):
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    assert polygon_client.stock_snapshot("NVDA") is None


def test_fetch_stock_snapshot_empty_results(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setattr(polygon_client, "_request", lambda *a, **k: {"results": []})
    assert polygon_client._fetch_stock_snapshot("NVDA") is None


def test_fetch_stock_snapshot_missing_close(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setattr(polygon_client, "_request", lambda *a, **k: {"results": [{"o": 1}]})
    assert polygon_client._fetch_stock_snapshot("NVDA") is None


def test_fetch_stock_snapshot_non_dict(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setattr(polygon_client, "_request", lambda *a, **k: ["not", "dict"])
    assert polygon_client._fetch_stock_snapshot("NVDA") is None


def test_fetch_stock_snapshot_parses_and_signals(monkeypatch):
    _set_key(monkeypatch)

    def fake_request(endpoint, params=None):
        if "/prev" in endpoint:
            return {"results": [{"c": 110.0, "o": 100.0, "h": 112.0, "l": 99.0, "v": 1_000_000, "vw": 100.0}]}
        return None  # current snapshot unavailable (paid)

    monkeypatch.setattr(polygon_client, "_request", fake_request)
    out = polygon_client._fetch_stock_snapshot("NVDA")
    assert out["prev_close"] == 110.0
    assert out["vwap_signal"].startswith("Closed ABOVE VWAP")
    assert "snapshot_price" not in out


def test_fetch_current_snapshot_empty(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setattr(polygon_client, "_request", lambda *a, **k: {"ticker": {}})
    assert polygon_client._fetch_current_snapshot("NVDA") is None


def test_stock_snapshot_loader_exception_returns_none(monkeypatch):
    _set_key(monkeypatch)

    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(polygon_client, "_fetch_stock_snapshot", lambda t: boom())
    assert polygon_client.stock_snapshot("NVDA") is None
