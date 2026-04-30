"""
portfolio_analytics.py
Deterministic portfolio analytics used by prompts, quality gates, and reports.
"""

from __future__ import annotations

import math
from itertools import combinations

import pandas as pd

from src.constants import COMPANY_ALIASES


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
        suggestions.append({
            "type": "rebalance",
            "instrument": company,
            "action": "TRIM",
            "max_portfolio_pct": max_position_pct,
            "rationale": (
                f"Reduce {company} economic exposure from {pct:.1f}% toward "
                f"the configured {max_position_pct}% single-company cap."
            ),
            "risk_note": "Prefer direct trim/rebalance before adding hedge complexity.",
        })

    top3 = (risk_dashboard or {}).get("top3_concentration_pct")
    vol = (risk_dashboard or {}).get("annualized_volatility_pct")
    beta = (risk_dashboard or {}).get("beta") or {}
    qqq_beta = beta.get("QQQ")
    high_concentration = top3 is not None and top3 >= settings.get("top3_concentration_warning_pct", 60)
    high_vol = vol is not None and vol >= settings.get("portfolio_volatility_warning_pct", 35)
    high_beta = qqq_beta is not None and qqq_beta >= settings.get("portfolio_beta_warning_threshold", 1.25)

    if high_concentration or high_vol or high_beta:
        suggestions.append({
            "type": "inverse_etf",
            "instrument": "PSQ",
            "action": "OPTIONAL_SHORT_TERM_HEDGE",
            "max_portfolio_pct": inverse_cap_pct,
            "rationale": "Small inverse Nasdaq hedge may offset concentrated tech beta during event risk.",
            "risk_note": (
                "Inverse ETFs reset daily and can decay quickly. Use only as a short-term hedge, "
                "size small, and prefer trims when risk is position-specific."
            ),
        })

    return suggestions
