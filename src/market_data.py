"""
market_data.py
Fetches live prices, ~10-month OHLCV history, key fundamentals, and
technical indicators (RSI/MACD/Bollinger/SMA/volume spike) via yfinance.
No API key required — all free.

Resilience:
  - tenacity retries on transient yfinance failures (3 tries, 2-10s backoff)
  - pickle cache in data/.cache/market_data/ (default TTL 1h)
  - outer try/except returns {"ticker": t, "error": str} so one bad ticker
    never kills the whole run.
"""

import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import pandas as pd
import yfinance as yf
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.cache import cached
from src.config import load_settings


# ── Technical indicators ────────────────────────────────────────────────────

def _safe_float(x) -> float | None:
    """Convert possibly-NaN value to None or rounded float."""
    try:
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v, 4)
    except (TypeError, ValueError):
        return None


def _first_float(*values) -> float | None:
    """Return the first non-null numeric value from a list of provider fields."""
    for value in values:
        parsed = _safe_float(value)
        if parsed is not None:
            return parsed
    return None


def _first_float_with_source(*fields: tuple[str, object]) -> tuple[str | None, float | None]:
    """Return the first numeric provider field as (field_name, value)."""
    for name, value in fields:
        parsed = _safe_float(value)
        if parsed is not None:
            return name, parsed
    return None, None


def _epoch_to_utc_iso(value) -> str | None:
    """Convert a provider epoch timestamp to a compact UTC ISO string."""
    try:
        if value is None:
            return None
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError):
        return None


def compute_indicators(hist: pd.DataFrame) -> dict:
    """
    Compute technical indicators from OHLCV history. Returns None for any
    indicator that lacks enough history (e.g. SMA-200 needs 200 closes).

    Pure pandas — no TA-Lib dependency.
    """
    if hist is None or hist.empty or len(hist) < 15:
        return {
            "rsi_14": None, "macd": None, "macd_signal": None, "macd_hist": None,
            "bb_upper": None, "bb_middle": None, "bb_lower": None, "bb_pct": None,
            "sma_50": None, "sma_200": None,
            "price_vs_sma50_pct": None, "price_vs_sma200_pct": None,
            "volume_spike_ratio": None,
        }

    close = hist["Close"].astype(float)
    volume = hist["Volume"].astype(float) if "Volume" in hist.columns else None
    current_price = float(close.iloc[-1])

    # ── RSI(14) via Wilder smoothing ──────────────────────────────────────
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    # Wilder uses alpha = 1/period (EWM with com=period-1, adjust=False)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    rsi = 100 - (100 / (1 + rs))
    rsi_14 = _safe_float(rsi.iloc[-1])

    # ── MACD (12, 26, 9) ──────────────────────────────────────────────────
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line

    macd = _safe_float(macd_line.iloc[-1]) if len(close) >= 26 else None
    macd_signal = _safe_float(signal_line.iloc[-1]) if len(close) >= 35 else None
    macd_hist = _safe_float(histogram.iloc[-1]) if len(close) >= 35 else None

    # ── Bollinger Bands (20, 2σ) ───────────────────────────────────────────
    bb_upper = bb_middle = bb_lower = bb_pct = None
    if len(close) >= 20:
        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        bb_middle_val = float(sma20.iloc[-1])
        bb_upper_val = bb_middle_val + 2 * float(std20.iloc[-1])
        bb_lower_val = bb_middle_val - 2 * float(std20.iloc[-1])
        bb_middle = _safe_float(bb_middle_val)
        bb_upper = _safe_float(bb_upper_val)
        bb_lower = _safe_float(bb_lower_val)
        band_width = bb_upper_val - bb_lower_val
        if band_width > 0:
            bb_pct = _safe_float((current_price - bb_lower_val) / band_width)

    # ── SMA 50 / 200 and price vs SMA ─────────────────────────────────────
    sma_50 = _safe_float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
    sma_200 = _safe_float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None

    price_vs_sma50_pct = (
        _safe_float((current_price - sma_50) / sma_50 * 100) if sma_50 else None
    )
    price_vs_sma200_pct = (
        _safe_float((current_price - sma_200) / sma_200 * 100) if sma_200 else None
    )

    # ── Volume spike ratio (today vs 30d avg) ─────────────────────────────
    volume_spike_ratio = None
    if volume is not None and len(volume) >= 30:
        today_vol = float(volume.iloc[-1])
        avg_30 = float(volume.tail(30).mean())
        if avg_30 > 0:
            volume_spike_ratio = _safe_float(today_vol / avg_30)

    return {
        "rsi_14": rsi_14,
        "macd": macd,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        "bb_upper": bb_upper,
        "bb_middle": bb_middle,
        "bb_lower": bb_lower,
        "bb_pct": bb_pct,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "price_vs_sma50_pct": price_vs_sma50_pct,
        "price_vs_sma200_pct": price_vs_sma200_pct,
        "volume_spike_ratio": volume_spike_ratio,
    }


# ── yfinance fetch with retry + cache ───────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
    reraise=True,
)
def _fetch_ticker_raw(ticker: str, history_months: int) -> dict:
    """Raw yfinance fetch (no cache, retries on transient failures)."""
    t = yf.Ticker(ticker)
    info = t.info or {}

    end = datetime.now()
    start = end - timedelta(days=history_months * 31)
    # yfinance treats `end` as exclusive. Include tomorrow so today's intraday
    # daily bar is available during/after the current trading session.
    hist = t.history(
        start=start.strftime("%Y-%m-%d"),
        end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
    )

    if hist.empty:
        return {"ticker": ticker, "error": "No history data returned"}

    history_close = float(hist["Close"].iloc[-1])
    quote_source_field, quote_price = _first_float_with_source(
        ("regularMarketPrice", info.get("regularMarketPrice")),
        ("currentPrice", info.get("currentPrice")),
        ("postMarketPrice", info.get("postMarketPrice")),
        ("preMarketPrice", info.get("preMarketPrice")),
    )
    current_price = quote_price if quote_price is not None else history_close
    previous_close = _first_float(
        info.get("regularMarketPreviousClose"),
        info.get("previousClose"),
    )
    currency = info.get("currency", "USD")
    quote_timestamp_utc = _epoch_to_utc_iso(info.get("regularMarketTime"))
    quote_source = f"yfinance:{quote_source_field}" if quote_source_field else "yfinance:historyClose"
    price_basis = "regular_market_quote" if quote_price is not None else "daily_history_close"

    def pct_change(n_days: int) -> float | None:
        if len(hist) < n_days + 1:
            return None
        prev = float(hist["Close"].iloc[-(n_days + 1)])
        return round((current_price - prev) / prev * 100, 2)

    change_pct_1d = (
        round((current_price - previous_close) / previous_close * 100, 2)
        if previous_close else pct_change(1)
    )

    # Tail history (last 90 days) as list of dicts
    history_records = []
    for idx, row in hist.tail(90).iterrows():
        history_records.append({
            "date": str(idx.date()),
            "open": round(float(row["Open"]), 2),
            "high": round(float(row["High"]), 2),
            "low": round(float(row["Low"]), 2),
            "close": round(float(row["Close"]), 2),
            "volume": int(row["Volume"]),
        })

    fifty_two_week_high = info.get("fiftyTwoWeekHigh")
    pct_from_52w_high = None
    if fifty_two_week_high and fifty_two_week_high > 0:
        pct_from_52w_high = round(
            (current_price - fifty_two_week_high) / fifty_two_week_high * 100, 2
        )

    avg_vol = info.get("averageVolume") or info.get("averageDailyVolume10Day")
    indicators = compute_indicators(hist)

    return {
        "ticker": ticker,
        "current_price": round(current_price, 2),
        "currency": currency,
        "change_pct_1d": change_pct_1d,
        "change_pct_5d": pct_change(5),
        "change_pct_1mo": pct_change(21),
        "previous_close": round(previous_close, 2) if previous_close else None,
        "open": _first_float(info.get("regularMarketOpen"), info.get("open")),
        "day_high": _first_float(info.get("regularMarketDayHigh"), info.get("dayHigh")),
        "day_low": _first_float(info.get("regularMarketDayLow"), info.get("dayLow")),
        "quote_timestamp_utc": quote_timestamp_utc,
        "quote_source": quote_source,
        "price_basis": price_basis,
        "market_state": info.get("marketState"),
        "volume_today": int(hist["Volume"].iloc[-1]) if not hist.empty else None,
        "avg_volume_30d": int(avg_vol) if avg_vol else None,
        "market_cap": info.get("marketCap"),
        "pe_ratio": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "52w_high": fifty_two_week_high,
        "52w_low": info.get("fiftyTwoWeekLow"),
        "pct_from_52w_high": pct_from_52w_high,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "indicators": indicators,
        "history": history_records,
        "error": None,
    }


def get_ticker_data(ticker: str, history_months: int = 10) -> dict:
    """
    Fetch data for a single ticker, using cache where possible.
    See _fetch_ticker_raw for the underlying network call.
    """
    settings = load_settings()
    cache_enabled = settings.get("cache_enabled", True)
    ttl = settings.get("market_data_cache_ttl_seconds", settings.get("cache_ttl_seconds", 3600))
    cache_version = settings.get("market_data_cache_version", 2)

    try:
        return cached(
            namespace="market_data",
            key=f"v{cache_version}_{ticker}_{history_months}",
            ttl_seconds=ttl,
            loader=lambda: _fetch_ticker_raw(ticker, history_months),
            enabled=cache_enabled,
        )
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def get_market_data(tickers: list, history_months: int = None) -> dict:
    """Fetch data for a list of tickers in parallel. Returns {ticker: data_dict}."""
    settings = load_settings()
    if history_months is None:
        history_months = settings.get("history_months", 10)

    result = {}
    max_workers = min(8, len(tickers)) if tickers else 1

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(get_ticker_data, t, history_months): t for t in tickers}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                result[ticker] = future.result()
                print(f"  ✓ {ticker}", flush=True)
            except Exception as e:
                result[ticker] = {"ticker": ticker, "error": str(e)}
                print(f"  ✗ {ticker}: {e}", flush=True)

    return result


def get_portfolio_prices(holdings: list) -> dict:
    """
    Given a list of holding dicts (with 'ticker' key), fetch current prices.
    Returns {ticker: current_price}.
    """
    if not holdings:
        return {}
    tickers = [h["ticker"] for h in holdings]
    data = get_market_data(tickers)
    return {ticker: d.get("current_price") for ticker, d in data.items()}


# ── Historical price lookup (for backtester) ────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
    reraise=True,
)
def _fetch_price_at(ticker: str, iso_date: str) -> float | None:
    """Raw historical close-price fetch. iso_date = 'YYYY-MM-DD'."""
    target = datetime.strptime(iso_date, "%Y-%m-%d")
    # Fetch a small window around the target so market holidays don't kill us
    start = (target - timedelta(days=5)).strftime("%Y-%m-%d")
    end = (target + timedelta(days=3)).strftime("%Y-%m-%d")
    t = yf.Ticker(ticker)
    hist = t.history(start=start, end=end)
    if hist.empty:
        return None
    # Use the close on or just before the target date
    target_pd = pd.Timestamp(iso_date)
    on_or_before = hist[hist.index <= target_pd.tz_localize(hist.index.tz) if hist.index.tz else hist.index <= target_pd]
    if not on_or_before.empty:
        return round(float(on_or_before["Close"].iloc[-1]), 4)
    return round(float(hist["Close"].iloc[0]), 4)


def price_at(ticker: str, iso_date: str) -> float | None:
    """Cached historical close price for (ticker, date). Used by backtester."""
    settings = load_settings()
    cache_enabled = settings.get("cache_enabled", True)
    ttl = settings.get("historical_price_cache_ttl_seconds", 30 * 86400)
    try:
        return cached(
            namespace="historical_price",
            key=f"{ticker}_{iso_date}",
            ttl_seconds=ttl,
            loader=lambda: _fetch_price_at(ticker, iso_date),
            enabled=cache_enabled,
        )
    except Exception:
        return None


if __name__ == "__main__":
    test_tickers = ["NVDA", "PLTR", "MSFT"]
    data = get_market_data(test_tickers)
    for ticker, d in data.items():
        if d.get("error"):
            print(f"{ticker}: ERROR — {d['error']}")
            continue
        ind = d.get("indicators", {}) or {}
        print(
            f"{ticker}: ${d['current_price']} ({d['change_pct_1d']:+.2f}% today) | "
            f"RSI={ind.get('rsi_14')} | MACD={ind.get('macd_hist')} | "
            f"BB%={ind.get('bb_pct')} | VolX={ind.get('volume_spike_ratio')}"
        )
