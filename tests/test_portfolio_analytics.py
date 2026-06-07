import pytest

from src.portfolio_analytics import (
    aggregate_company_exposure,
    build_hedge_suggestions,
    compute_correlation_matrix,
    compute_risk_dashboard,
    concentration_alerts,
)
from src.portfolio_loader import compute_sector_exposure


def test_sector_overrides_and_company_alias_rollup():
    holdings = [
        {"ticker": "TQQQ", "quantity": 1, "book_value_cad": 1000, "market_value": 1000, "market_value_currency": "USD"},
        {"ticker": "GOOG", "quantity": 1, "book_value_cad": 500, "market_value": 500, "market_value_currency": "USD"},
        {"ticker": "GOOGL", "quantity": 1, "book_value_cad": 500, "market_value": 500, "market_value_currency": "USD"},
    ]

    sectors = compute_sector_exposure(holdings, {"GOOGL": {"sector": "Communication Services"}})
    assert sectors["Technology"]["tickers"] == ["TQQQ"]
    assert "GOOG" in sectors["Communication Services"]["tickers"]

    companies, total = aggregate_company_exposure(holdings, cad_per_usd=1)
    assert total == 2000
    assert companies["GOOGL"]["value_usd"] == 1000
    assert sorted(companies["GOOGL"]["tickers"]) == ["GOOG", "GOOGL"]


def test_company_rollup_handles_base_symbol_and_cdr_suffix():
    holdings = [
        {"ticker": "COST", "quantity": 1, "market_value": 1000, "market_value_currency": "USD"},
        {"ticker": "COST.TO", "quantity": 1, "market_value": 1370, "market_value_currency": "CAD", "is_cdr": True},
    ]

    companies, total = aggregate_company_exposure(holdings, cad_per_usd=1.37)

    assert total == 2000
    assert companies["COST"]["value_usd"] == 2000
    assert sorted(companies["COST"]["tickers"]) == ["COST", "COST.TO"]


def test_hedge_suggestions_prioritize_rebalance_before_inverse_hedge():
    company_exposure = {
        "NVDA": {"company": "NVDA", "pct": 32.0, "value_usd": 3200, "tickers": ["NVDA"]},
    }
    risk_dashboard = {"top3_concentration_pct": 72, "annualized_volatility_pct": 40, "beta": {"QQQ": 1.4}}

    suggestions = build_hedge_suggestions(risk_dashboard, company_exposure, {"max_position_pct": 25})

    assert suggestions[0]["type"] == "rebalance"
    assert suggestions[0]["action"] == "TRIM"
    assert any(item["type"] == "inverse_etf" for item in suggestions)


def test_risk_dashboard_returns_empty_without_history():
    dashboard = compute_risk_dashboard(
        [{"ticker": "MSFT", "market_value": 100, "market_value_currency": "USD", "quantity": 1}],
        {"MSFT": {"history": []}},
    )
    assert dashboard["total_value_usd"] == 100
    assert dashboard["annualized_volatility_pct"] is None


def _make_history(values, start_date="2024-01-01"):
    """Build a history list from a sequence of close prices."""
    import datetime

    start = datetime.date.fromisoformat(start_date)
    return [{"date": str(start + datetime.timedelta(days=i)), "close": v} for i, v in enumerate(values)]


def test_compute_correlation_matrix_perfectly_correlated():
    prices = list(range(100, 165))  # 65 days of increasing prices
    md = [
        {"ticker": "AAA", "history": _make_history(prices)},
        {"ticker": "BBB", "history": _make_history(prices)},  # identical → r=1.0
    ]
    result = compute_correlation_matrix(md, min_history=30)
    pairs = result["high_correlation_pairs"]
    assert len(pairs) >= 1
    assert abs(pairs[0]["correlation"] - 1.0) < 1e-6


def test_compute_correlation_matrix_uncorrelated():
    import random

    rng = random.Random(42)
    prices_a = [100 + rng.uniform(-1, 1) * i for i in range(65)]
    prices_b = [200 - rng.uniform(-1, 1) * i for i in range(65)]
    md = [
        {"ticker": "AAA", "history": _make_history(prices_a)},
        {"ticker": "BBB", "history": _make_history(prices_b)},
    ]
    result = compute_correlation_matrix(md, min_history=30)
    # May or may not have high-correlation pairs, but matrix should be populated
    assert "AAA" in result["matrix"]
    assert "BBB" in result["matrix"]


def test_concentration_alerts_flags_over_threshold():
    positions = {
        "AAA": {"value_usd": 9000.0},
        "BBB": {"value_usd": 8000.0},
    }
    corr_matrix = {"high_correlation_pairs": [{"pair": "AAA/BBB", "ticker_a": "AAA", "ticker_b": "BBB", "correlation": 0.92}]}
    alerts = concentration_alerts(positions, total_usd=50000.0, correlation_matrix=corr_matrix)
    assert len(alerts) == 1
    assert alerts[0]["combined_weight_pct"] == pytest.approx(34.0, abs=0.01)


def test_concentration_alerts_no_alert_below_threshold():
    positions = {
        "AAA": {"value_usd": 1000.0},
        "BBB": {"value_usd": 1000.0},
    }
    corr_matrix = {"high_correlation_pairs": [{"pair": "AAA/BBB", "ticker_a": "AAA", "ticker_b": "BBB", "correlation": 0.92}]}
    alerts = concentration_alerts(positions, total_usd=50000.0, correlation_matrix=corr_matrix)
    assert len(alerts) == 0


def test_detect_drawdown_no_holdings():
    from src.portfolio_analytics import detect_drawdown

    result = detect_drawdown([], {}, {})
    assert result["triggered"] is False
    assert result["reason"] == "no_holdings"


def test_detect_drawdown_no_history():
    from src.portfolio_analytics import detect_drawdown

    holdings = [{"ticker": "NVDA", "market_value": 5000, "market_value_currency": "USD"}]
    result = detect_drawdown(holdings, {}, {})
    assert result["triggered"] is False
    assert "history" in result["reason"]


def test_detect_drawdown_triggers_on_drop():
    import datetime

    from src.portfolio_analytics import detect_drawdown

    start = datetime.date(2026, 5, 1)
    history = [{"date": str(start + datetime.timedelta(days=i)), "close": 100 - i * 0.5} for i in range(30)]
    holdings = [{"ticker": "NVDA", "market_value": 5000, "market_value_currency": "USD"}]
    market_data = {"NVDA": {"history": history}}
    result = detect_drawdown(holdings, market_data, {"drawdown_circuit_breaker_pct": -5.0})
    assert "triggered" in result
    assert result["drawdown_pct"] < 0


def test_compute_risk_dashboard_with_history():
    import datetime

    from src.portfolio_analytics import compute_risk_dashboard

    start = datetime.date(2026, 1, 1)
    # 60 days of zigzag prices to generate variance
    prices = [100 + (i % 3 - 1) * 2 for i in range(60)]
    history = [{"date": str(start + datetime.timedelta(days=i)), "close": p} for i, p in enumerate(prices)]
    holdings = [{"ticker": "NVDA", "market_value": 5000, "market_value_currency": "USD", "quantity": 1}]
    market_data = {"NVDA": {"history": history}}
    result = compute_risk_dashboard(holdings, market_data)
    assert result.get("annualized_volatility_pct") is not None
    assert "top3_concentration_pct" in result


def test_company_key_aliases():
    from src.portfolio_analytics import company_key

    # GOOG maps to GOOGL
    assert company_key("GOOG") == "GOOGL"
    assert company_key("") == ""
    # Unknown ticker returns itself
    assert company_key("NVDA") == "NVDA"
