"""Integration test: classify_regime wired with enriched dict shaped like real output."""

from src.macro_regime import classify_regime


def _make_enriched(vixcls_value=18.0, t10y2y_value=0.5):
    """Build a mock enriched dict matching the real enriched_data.py output shape."""
    return {
        "macro": {
            "series": {
                "VIXCLS": {"value": vixcls_value, "date": "2026-06-01"},
                "T10Y2Y": {"value": t10y2y_value, "date": "2026-06-01"},
                "DFF": {"value": 5.33, "date": "2026-06-01"},
                "CPIAUCSL": {"value": 3.2, "date": "2026-06-01"},
            },
            "rate_regime": "HIGH RATES",
            "yield_curve_signal": "NORMAL",
            "vix_regime": "LOW (<20) — risk-on, normal position sizing",
            "inflation_signal": "MODERATE INFLATION",
        },
        "per_ticker": {},
        "crypto": None,
        "sources_active": ["fred"],
    }


def test_classify_regime_with_enriched_dict_returns_required_keys():
    enriched = _make_enriched()
    fred_series = (enriched.get("macro") or {}).get("series") or {}
    market_context = {"SPY": {"sma_50": 520.0, "sma_200": 510.0}}

    result = classify_regime(fred_series, market_context)

    assert "regime" in result
    assert "conviction_cap" in result
    assert "signals" in result


def test_classify_regime_bull_from_enriched():
    enriched = _make_enriched(vixcls_value=14.0, t10y2y_value=0.8)
    fred_series = (enriched["macro"] or {})["series"]
    result = classify_regime(fred_series, {})
    assert result["regime"] == "bull"
    assert result["conviction_cap"] is None


def test_classify_regime_bear_from_enriched():
    enriched = _make_enriched(vixcls_value=40.0, t10y2y_value=-0.5)
    fred_series = enriched["macro"]["series"]
    result = classify_regime(fred_series, {})
    assert result["regime"] == "bear"
    assert result["conviction_cap"] == 9


def test_classify_regime_fallback_when_macro_missing():
    """Simulates the main.py safety fallback when enriched['macro'] is None."""
    enriched = {"macro": None, "per_ticker": {}}
    fred_series = ((enriched.get("macro") or {}).get("series")) or {}
    result = classify_regime(fred_series, {})
    # Should still return a valid dict with required keys (defaults to bull)
    assert "regime" in result
    assert "conviction_cap" in result
