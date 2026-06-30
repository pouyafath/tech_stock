"""Unit + error-path coverage for src.fred_client."""

from datetime import date

import pytest
import requests

from src import fred_client
from src.fred_client import _macro_summary


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
    monkeypatch.setattr(fred_client, "load_settings", lambda: {"cache_enabled": False})


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)


def _set_key(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")


def _stub_get(monkeypatch, response):
    monkeypatch.setattr(requests, "get", lambda *a, **k: response)


# ── existing summary tests (kept) ─────────────────────────────────────────────


def test_macro_summary_includes_all_available_fields():
    assert _macro_summary(5.25, 0.18, 3.1, 17.8) == "Rates: 5.25% | Curve: +0.18% | CPI: +3.1% YoY | VIX: 17.8"


def test_macro_summary_handles_missing_optional_fields():
    assert _macro_summary(5.25, None, 3.1, None) == "Rates: 5.25% | CPI: +3.1% YoY"


# ── _fetch_series_latest ──────────────────────────────────────────────────────


def test_fetch_series_no_key(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert fred_client._fetch_series_latest("DFF") is None


def test_fetch_series_http_error(monkeypatch):
    _set_key(monkeypatch)
    _stub_get(monkeypatch, FakeResponse(status_code=500))
    assert fred_client._fetch_series_latest("DFF") is None


def test_fetch_series_empty_obs(monkeypatch):
    _set_key(monkeypatch)
    _stub_get(monkeypatch, FakeResponse(status_code=200, json_data={"observations": []}))
    assert fred_client._fetch_series_latest("DFF") is None


def test_fetch_series_missing_value(monkeypatch):
    _set_key(monkeypatch)
    _stub_get(monkeypatch, FakeResponse(status_code=200, json_data={"observations": [{"value": "."}]}))
    assert fred_client._fetch_series_latest("DFF") is None


def test_fetch_series_parse_error(monkeypatch):
    _set_key(monkeypatch)
    _stub_get(monkeypatch, FakeResponse(status_code=200, json_exc=ValueError("bad")))
    assert fred_client._fetch_series_latest("DFF") is None


def test_fetch_series_valid(monkeypatch):
    _set_key(monkeypatch)
    _stub_get(monkeypatch, FakeResponse(status_code=200, json_data={"observations": [{"value": "5.25"}]}))
    assert fred_client._fetch_series_latest("DFF") == 5.25


# ── _fetch_cpi_yoy ────────────────────────────────────────────────────────────


def test_fetch_cpi_no_key(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert fred_client._fetch_cpi_yoy() is None


def test_fetch_cpi_http_error(monkeypatch):
    _set_key(monkeypatch)
    _stub_get(monkeypatch, FakeResponse(status_code=429))
    assert fred_client._fetch_cpi_yoy() is None


def test_fetch_cpi_insufficient_obs(monkeypatch):
    _set_key(monkeypatch)
    _stub_get(monkeypatch, FakeResponse(status_code=200, json_data={"observations": [{"value": "300"}]}))
    assert fred_client._fetch_cpi_yoy() is None


def test_fetch_cpi_parse_error(monkeypatch):
    _set_key(monkeypatch)
    _stub_get(monkeypatch, FakeResponse(status_code=200, json_exc=ValueError("bad")))
    assert fred_client._fetch_cpi_yoy() is None


def test_fetch_cpi_valid(monkeypatch):
    _set_key(monkeypatch)
    obs = [{"value": str(110 + i)} for i in range(13)]  # newest 110, year ago 122
    _stub_get(monkeypatch, FakeResponse(status_code=200, json_data={"observations": obs}))
    out = fred_client._fetch_cpi_yoy()
    assert out == round((110 - 122) / 122 * 100, 2)


# ── macro_context / live_cad_per_usd no-key paths ─────────────────────────────


def test_macro_context_no_key(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert fred_client.macro_context() is None


def test_live_cad_no_key(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert fred_client.live_cad_per_usd() is None


def test_fetch_macro_context_no_key(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert fred_client._fetch_macro_context() is None


def test_fetch_macro_context_all_none(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setattr(fred_client, "_fetch_series_latest", lambda sid: None)
    monkeypatch.setattr(fred_client, "_fetch_cpi_yoy", lambda: None)
    assert fred_client._fetch_macro_context() is None


def test_fetch_macro_context_builds_signals(monkeypatch):
    _set_key(monkeypatch)
    values = {"DFF": 5.5, "T10Y2Y": -0.8, "UNRATE": 4.0, "VIXCLS": 35.0}
    monkeypatch.setattr(fred_client, "_fetch_series_latest", lambda sid: values.get(sid))
    monkeypatch.setattr(fred_client, "_fetch_cpi_yoy", lambda: 5.0)
    out = fred_client._fetch_macro_context()
    assert out["rate_regime"].startswith("HIGH RATES")
    assert out["yield_curve_signal"].startswith("DEEPLY INVERTED")
    assert out["vix_regime"].startswith("HIGH FEAR")
    assert out["inflation_signal"] == "ELEVATED INFLATION"


def test_macro_context_loader_exception(monkeypatch):
    _set_key(monkeypatch)

    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(fred_client, "_fetch_macro_context", boom)
    assert fred_client.macro_context() is None


# ── economic_calendar_estimate ────────────────────────────────────────────────


def test_economic_calendar_estimate_shape():
    out = fred_client.economic_calendar_estimate(date(2026, 6, 18))
    assert "next_nfp_estimate" in out
    assert "next_cpi_window" in out
    assert out["source"] == "deterministic_calendar_estimate"
