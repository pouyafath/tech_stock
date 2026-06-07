"""
portfolio_analytics.py
Deterministic portfolio analytics used by prompts, quality gates, and reports.
"""

from __future__ import annotations

import logging
import math
import time
from itertools import combinations

import pandas as pd

from src.constants import COMPANY_ALIASES

_fx_cache: tuple[float, float] | None = None  # (rate, timestamp)
_FX_TTL = 4 * 3600  # 4 hours


def get_usd_cad_rate() -> float:
    """Fetch live USD/CAD rate; cache for 4 h; fall back to 1.37 on error."""
    global _fx_cache
    now = time.monotonic()
    if _fx_cache and (now - _fx_cache[1]) < _FX_TTL:
        return _fx_cache[0]
    try:
        import json as _json
        import urllib.request

        with urllib.request.urlopen("https://api.exchangerate-api.com/v4/latest/USD", timeout=5) as resp:
            data = _json.loads(resp.read())
        rate = float(data["rates"]["CAD"])
        _fx_cache = (rate, now)
        return rate
    except Exception:
        pass
    try:
        import urllib.request

        with urllib.request.urlopen("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXCAUS", timeout=5) as resp:
            lines = resp.read().decode().strip().splitlines()
        # Walk from the newest row backwards; DEXCAUS uses "." for missing days,
        # so skip any row whose value column does not parse as a float.
        for line in reversed(lines):
            if line.startswith("DATE"):
                continue
            parts = line.split(",")
            if len(parts) < 2:
                continue
            try:
                rate = float(parts[1])
            except ValueError:
                continue
            _fx_cache = (rate, now)
            return rate
    except Exception:
        pass
    logging.getLogger(__name__).warning("FX rate fetch failed; using hardcoded 1.37")
    return 1.37


def company_key(ticker: str) -> str:
    """Map tradeable tickers/share classes to one economic exposure key."""
    if not ticker:
        return ""
    return COMPANY_ALIASES.get(ticker, ticker)


def aggregate_positions(holdings: list, cad_per_usd: float = 1.37) -> tuple[dict, float]:
    """Aggregate reported holdings to approximate USD-equivalent position values."""
    positions = {}
    total_usd = 0.0
    for holding in holdings or []:
        ticker = holding.get("ticker")
        if not ticker or ticker == "CASH":
            continue
        value = holding.get("market_value")
        currency = holding.get("market_value_currency")
        if not value or not currency:
            continue
        if currency == "USD":
            value_usd = float(value)
        elif currency == "CAD" and cad_per_usd:
            value_usd = float(value) / cad_per_usd
        else:
            continue

        position = positions.setdefault(
            ticker,
            {"ticker": ticker, "value_usd": 0.0, "reported_values": [], "quantity": 0.0},
        )
        position["value_usd"] += value_usd
        position["quantity"] += holding.get("quantity") or 0.0
        position["reported_values"].append(f"${value:,.0f} {currency}")
        total_usd += value_usd

    if total_usd > 0:
        for position in positions.values():
            position["pct"] = position["value_usd"] / total_usd * 100
    return positions, total_usd


def aggregate_company_exposure(holdings: list, cad_per_usd: float = 1.37) -> tuple[dict, float]:
    """Roll tradeable holdings up to company/economic exposure groups."""
    positions, total_usd = aggregate_positions(holdings, cad_per_usd)
    companies = {}
    for ticker, position in positions.items():
        key = company_key(ticker)
        row = companies.setdefault(
            key,
            {"company": key, "value_usd": 0.0, "tickers": [], "reported_values": []},
        )
        row["value_usd"] += position["value_usd"]
        if ticker not in row["tickers"]:
            row["tickers"].append(ticker)
        row["reported_values"].extend(position.get("reported_values", []))

    if total_usd > 0:
        for row in companies.values():
            row["pct"] = row["value_usd"] / total_usd * 100
    return dict(sorted(companies.items(), key=lambda item: -item[1]["value_usd"])), total_usd


def _returns_from_history(history: list[dict]) -> pd.Series:
    if not history or len(history) < 3:
        return pd.Series(dtype=float)
    frame = pd.DataFrame(history)
    if "date" not in frame or "close" not in frame:
        return pd.Series(dtype=float)
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.dropna(subset=["date", "close"]).drop_duplicates("date").sort_values("date")
    if len(frame) < 3:
        return pd.Series(dtype=float)
    return frame.set_index("date")["close"].astype(float).pct_change().dropna()


def compute_risk_dashboard(
    holdings: list,
    market_data: dict,
    settings: dict | None = None,
) -> dict:
    """Compute portfolio risk metrics from available historical closes."""
    settings = settings or {}
    positions, total_usd = aggregate_positions(
        holdings,
        settings.get("cad_per_usd_assumption", 1.37),
    )
    if not positions or total_usd <= 0:
        return {}

    weighted_returns = []
    ticker_returns = {}
    for ticker, position in positions.items():
        data = (market_data or {}).get(ticker) or {}
        returns = _returns_from_history(data.get("history") or [])
        if returns.empty:
            continue
        ticker_returns[ticker] = returns
        weighted_returns.append(returns.rename(ticker) * (position["value_usd"] / total_usd))

    portfolio_returns = pd.concat(weighted_returns, axis=1).dropna().sum(axis=1) if weighted_returns else pd.Series(dtype=float)
    annualized_volatility_pct = None
    max_drawdown_pct = None
    if not portfolio_returns.empty:
        annualized_volatility_pct = round(float(portfolio_returns.std() * math.sqrt(252) * 100), 2)
        cumulative = (1 + portfolio_returns).cumprod()
        drawdown = cumulative / cumulative.cummax() - 1
        max_drawdown_pct = round(float(drawdown.min() * 100), 2)

    sortino_ratio = None
    calmar_ratio = None
    var_95_pct = None
    cvar_95_pct = None
    if not portfolio_returns.empty and len(portfolio_returns) >= 10:
        mean_return = portfolio_returns.mean()
        downside = portfolio_returns[portfolio_returns < 0]
        if len(downside) > 1:
            downside_std = float(downside.std())
            if downside_std:
                sortino_ratio = round(float(mean_return / downside_std * math.sqrt(252)), 2)
        ann_return = float((1 + mean_return) ** 252 - 1) * 100
        if max_drawdown_pct and max_drawdown_pct < 0:
            calmar_ratio = round(ann_return / abs(max_drawdown_pct), 2)
        var_95_pct = round(float(portfolio_returns.quantile(0.05) * 100), 2)
        below_var = portfolio_returns[portfolio_returns <= portfolio_returns.quantile(0.05)]
        if not below_var.empty:
            cvar_95_pct = round(float(below_var.mean() * 100), 2)

    benchmark_beta = {}
    for benchmark in settings.get("risk_benchmark_tickers", ("SPY", "QQQ", "SMH")):
        bench_data = (market_data or {}).get(benchmark) or {}
        bench_returns = _returns_from_history(bench_data.get("history") or [])
        if portfolio_returns.empty or bench_returns.empty:
            continue
        aligned = pd.concat([portfolio_returns.rename("portfolio"), bench_returns.rename("bench")], axis=1).dropna()
        if len(aligned) < 20:
            continue
        variance = aligned["bench"].var()
        if not variance:
            continue
        beta = aligned["portfolio"].cov(aligned["bench"]) / variance
        benchmark_beta[benchmark] = round(float(beta), 2)

    correlated_pairs = []
    for a, b in combinations(sorted(ticker_returns), 2):
        aligned = pd.concat([ticker_returns[a].rename(a), ticker_returns[b].rename(b)], axis=1).dropna()
        if len(aligned) < 20:
            continue
        corr = aligned[a].corr(aligned[b])
        if corr is not None and abs(corr) >= settings.get("correlation_threshold", 0.85):
            correlated_pairs.append({"pair": f"{a}/{b}", "correlation": round(float(corr), 2)})
    correlated_pairs = sorted(correlated_pairs, key=lambda row: -abs(row["correlation"]))[:8]

    top_positions = sorted(positions.values(), key=lambda row: -row["value_usd"])
    top3_concentration_pct = round(sum(row.get("pct", 0) for row in top_positions[:3]), 2)

    return {
        "total_value_usd": round(total_usd, 2),
        "annualized_volatility_pct": annualized_volatility_pct,
        "max_drawdown_estimate_pct": max_drawdown_pct,
        "beta": benchmark_beta,
        "top3_concentration_pct": top3_concentration_pct,
        "correlated_pairs": correlated_pairs,
        "sortino_ratio": sortino_ratio,
        "calmar_ratio": calmar_ratio,
        "var_95_pct": var_95_pct,
        "cvar_95_pct": cvar_95_pct,
    }


def build_hedge_suggestions(
    risk_dashboard: dict,
    company_exposure: dict,
    settings: dict | None = None,
) -> list[dict]:
    """Build deterministic hedge/rebalance suggestions for high-risk portfolios."""
    settings = settings or {}
    suggestions = []
    max_position_pct = settings.get("max_position_pct", 25)
    inverse_cap_pct = settings.get("inverse_etf_hedge_cap_pct", 3)

    for company, row in (company_exposure or {}).items():
        pct = row.get("pct") or 0
        if pct <= max_position_pct:
            continue
        suggestions.append(
            {
                "type": "rebalance",
                "instrument": company,
                "action": "TRIM",
                "max_portfolio_pct": max_position_pct,
                "rationale": (
                    f"Reduce {company} economic exposure from {pct:.1f}% toward the configured {max_position_pct}% single-company cap."
                ),
                "risk_note": "Prefer direct trim/rebalance before adding hedge complexity.",
            }
        )

    top3 = (risk_dashboard or {}).get("top3_concentration_pct")
    vol = (risk_dashboard or {}).get("annualized_volatility_pct")
    beta = (risk_dashboard or {}).get("beta") or {}
    qqq_beta = beta.get("QQQ")
    high_concentration = top3 is not None and top3 >= settings.get("top3_concentration_warning_pct", 60)
    high_vol = vol is not None and vol >= settings.get("portfolio_volatility_warning_pct", 35)
    high_beta = qqq_beta is not None and qqq_beta >= settings.get("portfolio_beta_warning_threshold", 1.25)

    if high_concentration or high_vol or high_beta:
        suggestions.append(
            {
                "type": "inverse_etf",
                "instrument": "PSQ",
                "action": "OPTIONAL_SHORT_TERM_HEDGE",
                "max_portfolio_pct": inverse_cap_pct,
                "rationale": "Small inverse Nasdaq hedge may offset concentrated tech beta during event risk.",
                "risk_note": (
                    "Inverse ETFs reset daily and can decay quickly. Use only as a short-term hedge, "
                    "size small, and prefer trims when risk is position-specific."
                ),
            }
        )

    return suggestions


def detect_drawdown(holdings: list, market_data: dict, settings: dict) -> dict:
    """Compute portfolio-level drawdown from peak using yfinance history.

    Approach:
      1. Build per-ticker daily close series from `market_data.history` for the
         last ~30 days (already fetched).
      2. Weight by current `market_value` to construct a portfolio time series.
      3. Compute peak-to-current drawdown as a percentage.
      4. Trigger when drawdown ≤ -threshold (default -6%).

    The returned dict feeds both the prompt and `apply_quality_gates`. When the
    inputs are insufficient (no history, no holdings), returns
    {"triggered": False, "reason": "insufficient_data"}.
    """
    threshold_pct = float(settings.get("drawdown_circuit_breaker_pct", -6.0))
    lookback_days = int(settings.get("drawdown_lookback_days", 30))

    if not holdings:
        return {"triggered": False, "reason": "no_holdings"}

    cad_per_usd = float(settings.get("cad_per_usd_assumption", 1.37) or 1.37)
    series_per_ticker: dict[str, pd.Series] = {}
    weights: dict[str, float] = {}
    for holding in holdings:
        ticker = holding.get("ticker")
        if not ticker or ticker == "CASH":
            continue
        data = (market_data or {}).get(ticker) or {}
        history = data.get("history") or []
        if not history:
            continue

        # Closes by date (last `lookback_days` rows, plus a small buffer)
        closes = {}
        for row in history[-(lookback_days + 5) :]:
            date = row.get("date")
            close = row.get("close")
            if date and close:
                closes[date] = float(close)
        if len(closes) < 3:  # 3+ points enough for peak/current comparison
            continue
        series_per_ticker[ticker] = pd.Series(closes).sort_index()

        # USD weight = current market value in USD-equivalent
        mv = holding.get("market_value") or 0.0
        currency = (holding.get("market_value_currency") or "USD").upper()
        weight = float(mv) / cad_per_usd if currency == "CAD" else float(mv)
        weights[ticker] = weight

    if not series_per_ticker:
        return {"triggered": False, "reason": "no_history"}

    # Weighted portfolio price index — normalize each series to its own first
    # observation, then weight-average.
    df = pd.DataFrame(series_per_ticker).dropna(how="all")
    if df.empty:
        return {"triggered": False, "reason": "no_history"}
    normalized = df / df.iloc[0]
    weights_series = pd.Series({t: weights.get(t, 0.0) for t in normalized.columns})
    if weights_series.sum() <= 0:
        return {"triggered": False, "reason": "zero_weight"}
    weights_series = weights_series / weights_series.sum()

    portfolio_index = (normalized * weights_series).sum(axis=1)
    if portfolio_index.empty:
        return {"triggered": False, "reason": "no_history"}

    peak = portfolio_index.max()
    current = portfolio_index.iloc[-1]
    drawdown_pct = (current / peak - 1.0) * 100.0 if peak else 0.0

    triggered = bool(drawdown_pct <= threshold_pct)
    return {
        "triggered": triggered,
        "drawdown_pct": round(float(drawdown_pct), 2),
        "threshold_pct": threshold_pct,
        "peak_label": f"{lookback_days}d peak",
        "lookback_days": lookback_days,
        "samples": int(len(portfolio_index)),
    }


def compute_correlation_matrix(market_data: list[dict], min_history: int = 30) -> dict:
    """Build pairwise Pearson correlation matrix from 60-day daily returns.

    market_data is the list of per-ticker dicts returned by market_data.py.
    Each dict has ticker (str) and history (list of {"date":..., "close":...}).
    Returns {"matrix": {ticker: {ticker: float}}, "high_correlation_pairs": [...]}.
    """
    if not market_data:
        return {"matrix": {}, "high_correlation_pairs": []}

    series: dict[str, pd.Series] = {}
    for item in market_data or []:
        ticker = item.get("ticker") or item.get("symbol")
        if not ticker:
            continue
        history = item.get("history") or []
        ret = _returns_from_history(history[-65:] if len(history) > 65 else history)
        if len(ret) >= min_history:
            series[ticker] = ret

    if len(series) < 2:
        return {"matrix": {}, "high_correlation_pairs": []}

    df = pd.DataFrame(series).dropna(how="all")
    if df.shape[0] < min_history or df.shape[1] < 2:
        return {"matrix": {}, "high_correlation_pairs": []}

    corr_df = df.corr()

    matrix: dict[str, dict[str, float]] = {}
    for ticker in corr_df.index:
        matrix[ticker] = {other: round(float(corr_df.loc[ticker, other]), 4) for other in corr_df.columns}

    high_pairs: list[dict] = []
    tickers = list(corr_df.index)
    for i, a in enumerate(tickers):
        for b in tickers[i + 1 :]:
            val = corr_df.loc[a, b]
            if pd.isna(val):
                continue
            if abs(val) >= 0.85:
                high_pairs.append({"pair": f"{a}/{b}", "ticker_a": a, "ticker_b": b, "correlation": round(float(val), 4)})

    high_pairs.sort(key=lambda r: -abs(r["correlation"]))
    return {"matrix": matrix, "high_correlation_pairs": high_pairs}


def concentration_alerts(
    positions: dict,
    total_usd: float,
    correlation_matrix: dict,
    threshold_corr: float = 0.85,
    threshold_weight_pct: float = 15.0,
) -> list[dict]:
    """Return list of {pair, correlation, combined_weight_pct, message} for risky pairs.

    positions: {ticker: {"value_usd": float, ...}}
    total_usd: total portfolio value in USD
    correlation_matrix: output of compute_correlation_matrix
    """
    if not positions or not total_usd or not correlation_matrix:
        return []

    alerts: list[dict] = []
    high_pairs = (correlation_matrix or {}).get("high_correlation_pairs") or []

    for pair_info in high_pairs:
        a = pair_info.get("ticker_a") or ""
        b = pair_info.get("ticker_b") or ""
        corr = pair_info.get("correlation", 0.0)
        if abs(corr) < threshold_corr:
            continue

        val_a = (positions.get(a) or {}).get("value_usd") or 0.0
        val_b = (positions.get(b) or {}).get("value_usd") or 0.0
        combined_weight_pct = (val_a + val_b) / total_usd * 100.0

        if combined_weight_pct > threshold_weight_pct:
            alerts.append(
                {
                    "pair": pair_info.get("pair", f"{a}/{b}"),
                    "correlation": corr,
                    "combined_weight_pct": round(combined_weight_pct, 2),
                    "message": (
                        f"{a} and {b} are {corr:.2f} correlated and together represent "
                        f"{combined_weight_pct:.1f}% of the portfolio — above the "
                        f"{threshold_weight_pct:.0f}% combined-weight threshold."
                    ),
                }
            )

    return alerts
