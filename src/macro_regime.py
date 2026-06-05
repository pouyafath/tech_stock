"""
macro_regime.py
Auto-detects macro regime from VIX, yield curve, and SPY SMA cross.
"""

from __future__ import annotations


def classify_regime(fred_data: dict, market_context: dict) -> dict:
    """Classify the current macro regime from pre-fetched data.

    Args:
        fred_data: Dict containing FRED series (T10Y2Y, yield_curve_10y2y, ...).
        market_context: Dict containing per-ticker market data (VIX, SPY, ...).

    Returns:
        {
            "regime": "bull" | "correction" | "bear" | "transition",
            "conviction_cap": int | None,
            "signals": [{"name": str, "value": float | str, "interpretation": str}],
        }
    """
    fred_data = fred_data or {}
    market_context = market_context or {}

    # --- VIX ---
    vix_entry = market_context.get("VIX") or {}
    if isinstance(vix_entry, dict):
        vix = vix_entry.get("price") or vix_entry.get("current_price")
    else:
        try:
            vix = float(vix_entry)
        except (TypeError, ValueError):
            vix = None
    if vix is None:
        vix = 20.0
    try:
        vix = float(vix)
    except (TypeError, ValueError):
        vix = 20.0

    # --- Yield curve ---
    yield_curve = fred_data.get("T10Y2Y") or fred_data.get("yield_curve_10y2y")
    try:
        yield_curve = float(yield_curve) if yield_curve is not None else None
    except (TypeError, ValueError):
        yield_curve = None

    # --- SPY SMAs ---
    spy_entry = market_context.get("SPY") or {}
    if isinstance(spy_entry, dict):
        sma_50 = spy_entry.get("sma_50")
        sma_200 = spy_entry.get("sma_200")
    else:
        sma_50 = None
        sma_200 = None
    try:
        sma_50 = float(sma_50) if sma_50 is not None else None
    except (TypeError, ValueError):
        sma_50 = None
    try:
        sma_200 = float(sma_200) if sma_200 is not None else None
    except (TypeError, ValueError):
        sma_200 = None

    death_cross = sma_50 is not None and sma_200 is not None and sma_50 < sma_200

    # --- Primary regime classification ---
    if vix >= 35:
        regime = "bear"
        conviction_cap = 9
    elif vix >= 25:
        regime = "correction"
        conviction_cap = 8
    elif vix >= 16 and yield_curve is not None and yield_curve < 0:
        regime = "transition"
        conviction_cap = None
    else:
        regime = "bull"
        conviction_cap = None

    # --- Death cross upgrades severity one level ---
    if death_cross:
        if regime == "bull":
            regime = "transition"
        elif regime == "correction":
            regime = "bear"
            conviction_cap = 9

    # --- Build signals list ---
    signals: list[dict] = [
        {
            "name": "VIX",
            "value": vix,
            "interpretation": ("panic/high-fear" if vix >= 35 else "elevated" if vix >= 25 else "moderate" if vix >= 16 else "low/calm"),
        },
    ]
    if yield_curve is not None:
        signals.append(
            {
                "name": "T10Y2Y",
                "value": yield_curve,
                "interpretation": "inverted (recession risk)" if yield_curve < 0 else "positive (normal)",
            }
        )
    if sma_50 is not None and sma_200 is not None:
        signals.append(
            {
                "name": "SPY_SMA_cross",
                "value": f"50d={sma_50:.2f} 200d={sma_200:.2f}",
                "interpretation": "death cross (bearish)" if death_cross else "golden cross or neutral (bullish)",
            }
        )

    return {
        "regime": regime,
        "conviction_cap": conviction_cap,
        "signals": signals,
    }
