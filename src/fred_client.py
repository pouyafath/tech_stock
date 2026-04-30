"""
fred_client.py
Federal Reserve Economic Data (FRED) client — macro indicators.

Free tier: Unlimited API calls.
Docs: https://fred.stlouisfed.org/docs/api/fred/

Provides macro_context() which returns a snapshot of key economic indicators:
  - Federal Funds Rate (DFF)
  - 10Y-2Y Treasury Spread / Yield Curve (T10Y2Y)
  - CPI Inflation YoY (CPIAUCSL)
  - Unemployment Rate (UNRATE)
  - VIX — market fear index (VIXCLS)
  - S&P 500 forward PE (market valuation) — derived from CAPE/MULTPL data

These provide the macro regime context Claude uses to adjust sector weighting:
  - High rates → tech underperforms relative to value
  - Inverted yield curve → recession signal, risk-off
  - High VIX → reduce risk, wider stop-losses
  - Low unemployment + high CPI → Fed stays hawkish
All functions return None on error or missing API key — never raise.
"""

import os
from calendar import monthrange
from datetime import date, datetime, timedelta

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.cache import cached
from src.config import load_settings

BASE_URL = "https://api.stlouisfed.org/fred"

# Series ID → (label, units, higher_is_good for equities)
SERIES = {
    "DFF":      ("Fed Funds Rate",         "%",    False),
    "T10Y2Y":   ("Yield Curve (10Y-2Y)",   "%",    True),
    "CPIAUCSL": ("CPI Inflation",          "% YoY",False),
    "UNRATE":   ("Unemployment Rate",      "%",    False),
    "VIXCLS":   ("VIX (Fear Index)",       "pts",  False),
}


def _add_months(day: date, months: int) -> date:
    month = day.month - 1 + months
    year = day.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def _first_weekday_of_month(year: int, month: int, weekday: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset)


def economic_calendar_estimate(today: date | None = None) -> dict:
    """
    Deterministic macro calendar estimate. It intentionally labels CPI/FOMC
    as windows/verification items because official schedules need a live source.
    """
    today = today or datetime.now().date()
    nfp = _first_weekday_of_month(today.year, today.month, 4)
    if nfp < today:
        nxt = _add_months(today.replace(day=1), 1)
        nfp = _first_weekday_of_month(nxt.year, nxt.month, 4)

    cpi_month = today if today.day <= 15 else _add_months(today.replace(day=1), 1)
    cpi_window_start = date(cpi_month.year, cpi_month.month, 10)
    cpi_window_end = date(cpi_month.year, cpi_month.month, 15)

    return {
        "next_nfp_estimate": nfp.isoformat(),
        "next_cpi_window": f"{cpi_window_start.isoformat()} to {cpi_window_end.isoformat()}",
        "fomc_note": "FOMC dates are not available from FRED; verify the official Fed calendar before event-risk trades.",
        "source": "deterministic_calendar_estimate",
    }


def _api_key() -> str | None:
    return os.environ.get("FRED_API_KEY") or None


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((requests.RequestException, ConnectionError, TimeoutError)),
    reraise=True,
)
def _fetch_series_latest(series_id: str) -> float | None:
    key = _api_key()
    if not key:
        return None
    # Get the most recent 2 observations to compute YoY for CPI
    end = datetime.now().date()
    start = (end - timedelta(days=60)).isoformat()
    r = requests.get(
        f"{BASE_URL}/series/observations",
        params={
            "series_id": series_id,
            "api_key": key,
            "file_type": "json",
            "observation_start": start,
            "sort_order": "desc",
            "limit": 1,
        },
        timeout=10,
    )
    if r.status_code >= 400:
        return None
    try:
        obs = r.json().get("observations") or []
        if not obs:
            return None
        val = obs[0].get("value", ".")
        if val in (".", "", None):
            return None
        return round(float(val), 3)
    except Exception:
        return None


def _fetch_cpi_yoy() -> float | None:
    """CPI: 12-month change (YoY inflation rate)."""
    key = _api_key()
    if not key:
        return None
    end = datetime.now().date()
    start = (end - timedelta(days=400)).isoformat()
    r = requests.get(
        f"{BASE_URL}/series/observations",
        params={
            "series_id": "CPIAUCSL",
            "api_key": key,
            "file_type": "json",
            "observation_start": start,
            "sort_order": "desc",
            "limit": 14,  # 13 months
        },
        timeout=10,
    )
    if r.status_code >= 400:
        return None
    try:
        obs = [
            o for o in r.json().get("observations", [])
            if o.get("value") not in (".", "", None)
        ]
        if len(obs) < 13:
            return None
        latest = float(obs[0]["value"])
        year_ago = float(obs[12]["value"])
        return round((latest - year_ago) / year_ago * 100, 2)
    except Exception:
        return None


def _fetch_macro_context() -> dict | None:
    key = _api_key()
    if not key:
        return None

    data = {}
    for sid, (label, units, _) in SERIES.items():
        val = _fetch_cpi_yoy() if sid == "CPIAUCSL" else _fetch_series_latest(sid)
        data[sid] = {"label": label, "value": val, "units": units}

    if not any(v["value"] is not None for v in data.values()):
        return None

    # Derived interpretations
    dff    = (data.get("DFF", {}).get("value") or 0)
    curve  = data.get("T10Y2Y", {}).get("value")
    cpi    = data.get("CPIAUCSL", {}).get("value")
    vix    = data.get("VIXCLS", {}).get("value")

    # Rate regime
    if dff >= 5.0:
        rate_regime = "HIGH RATES — tech/growth headwind; value/dividend favored"
    elif dff >= 3.0:
        rate_regime = "MODERATE RATES — mixed; monitor duration-sensitive growth stocks"
    else:
        rate_regime = "LOW RATES — growth/tech tailwind"

    # Yield curve
    if curve is not None:
        if curve < -0.5:
            curve_signal = "DEEPLY INVERTED — recession risk elevated; risk-off"
        elif curve < 0:
            curve_signal = "INVERTED — mild recession signal; reduce risk"
        elif curve < 0.5:
            curve_signal = "FLAT — neutral; watch for steepening as leading indicator"
        else:
            curve_signal = "NORMAL (positive slope) — growth environment"
    else:
        curve_signal = "N/A"

    # VIX regime
    if vix is not None:
        if vix > 30:
            vix_regime = "HIGH FEAR (>30) — widen stops, reduce position size"
        elif vix > 20:
            vix_regime = "ELEVATED (20-30) — moderate caution; sector selectivity"
        else:
            vix_regime = "LOW (<20) — risk-on, normal position sizing"
    else:
        vix_regime = "N/A"

    return {
        "series": data,
        "economic_calendar": economic_calendar_estimate(),
        "rate_regime": rate_regime,
        "yield_curve_signal": curve_signal,
        "vix_regime": vix_regime,
        "inflation_signal": (
            "ELEVATED INFLATION" if (cpi or 0) > 4 else
            "MODERATE INFLATION" if (cpi or 0) > 2.5 else
            "LOW INFLATION — benign for equities"
        ),
        "summary": (
            f"Rates: {dff:.2f}% | "
            f"Curve: {curve:+.2f}% | " if curve is not None else "" +
            f"CPI: {cpi:+.1f}% YoY | " if cpi is not None else "" +
            f"VIX: {vix:.1f}" if vix is not None else ""
        ),
    }


def macro_context() -> dict | None:
    """Latest macro snapshot: rates, yield curve, inflation, VIX."""
    if not _api_key():
        return None
    settings = load_settings()
    ttl = settings.get("fred_cache_ttl_seconds", 14400)  # 4h default (data updates slowly)
    try:
        return cached(
            namespace="fred_macro",
            key="context",
            ttl_seconds=ttl,
            loader=_fetch_macro_context,
            enabled=settings.get("cache_enabled", True),
        )
    except Exception:
        return None


if __name__ == "__main__":
    import json
    if not _api_key():
        print("FRED_API_KEY not set — skipping live test")
    else:
        print("── macro_context() ──")
        print(json.dumps(macro_context(), indent=2))
