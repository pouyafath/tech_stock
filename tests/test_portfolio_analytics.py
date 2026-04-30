from src.portfolio_analytics import (
    aggregate_company_exposure,
    build_hedge_suggestions,
    compute_risk_dashboard,
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
