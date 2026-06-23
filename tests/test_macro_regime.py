"""Tests for src/macro_regime.py — classify_regime."""

from src.macro_regime import classify_regime


def _mc(vix=None, sma_50=None, sma_200=None):
    ctx = {}
    if vix is not None:
        ctx["VIX"] = {"price": vix}
    if sma_50 is not None or sma_200 is not None:
        ctx["SPY"] = {"sma_50": sma_50, "sma_200": sma_200}
    return ctx


def test_bull_low_vix():
    result = classify_regime({}, _mc(vix=12))
    assert result["regime"] == "bull"
    assert result["conviction_cap"] is None


def test_correction_mid_vix():
    result = classify_regime({}, _mc(vix=30))
    assert result["regime"] == "correction"
    assert result["conviction_cap"] == 8


def test_bear_high_vix():
    result = classify_regime({}, _mc(vix=40))
    assert result["regime"] == "bear"
    assert result["conviction_cap"] == 9


def test_death_cross_upgrades_bull_to_transition():
    result = classify_regime({}, _mc(vix=12, sma_50=400.0, sma_200=450.0))
    assert result["regime"] == "transition"
    assert result["conviction_cap"] is None


def test_inverted_yield_curve_gives_transition():
    result = classify_regime({"T10Y2Y": -0.5}, _mc(vix=20))
    assert result["regime"] == "transition"
    assert result["conviction_cap"] is None


def test_empty_data_defaults_to_bull():
    result = classify_regime({}, {})
    assert result["regime"] == "bull"
    assert result["conviction_cap"] is None


def test_signals_list_is_populated():
    result = classify_regime({"T10Y2Y": -0.3}, _mc(vix=18, sma_50=500.0, sma_200=490.0))
    names = [s["name"] for s in result["signals"]]
    assert "VIX" in names
    assert "T10Y2Y" in names
    assert "SPY_SMA_cross" in names


def test_death_cross_upgrades_correction_to_bear():
    result = classify_regime({}, _mc(vix=27, sma_50=400.0, sma_200=450.0))
    assert result["regime"] == "bear"
    assert result["conviction_cap"] == 9


def test_vix_from_fred_data():
    """FRED VIXCLS key takes priority over market_context."""
    result = classify_regime({"VIXCLS": {"value": 40.0}}, {})
    assert result["regime"] == "bear"


def test_yield_curve_from_fred_dict_value():
    """T10Y2Y as dict with 'value' key is read correctly."""
    result = classify_regime({"T10Y2Y": {"value": -0.5}}, _mc(vix=18))
    assert result["regime"] == "transition"


def test_yield_curve_positive_no_transition():
    result = classify_regime({"T10Y2Y": {"value": 1.0}}, _mc(vix=18))
    assert result["regime"] == "bull"


def test_vix_fallback_to_scalar_in_market_context():
    """VIX as a scalar float in market_context."""
    result = classify_regime({}, {"VIX": 35.0})
    assert result["regime"] == "bear"


def test_invalid_vix_falls_back_to_default():
    result = classify_regime({"VIXCLS": {"value": "n/a"}}, {})
    # Default vix=20 → bull
    assert result["regime"] == "bull"
