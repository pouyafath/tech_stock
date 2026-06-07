"""Integration test: run key pipeline components against bundled sample data."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

SAMPLES_DIR = Path(__file__).parent.parent / "data" / "samples"


def test_sample_holdings_csv_exists():
    csv = SAMPLES_DIR / "holdings-report-sample.csv"
    assert csv.exists(), f"Sample holdings CSV not found at {csv}"


def test_sample_holdings_csv_loads():
    from src.portfolio_loader import parse_holdings_csv

    csv = SAMPLES_DIR / "holdings-report-sample.csv"
    if not csv.exists():
        pytest.skip("Sample CSV not present")
    portfolio = parse_holdings_csv(str(csv))
    holdings = portfolio.get("holdings") or []
    assert isinstance(holdings, list)
    assert len(holdings) > 0
    # Each holding should have at minimum a ticker
    assert all("ticker" in h for h in holdings)


def test_sample_recommendation_log_valid_json():
    log = SAMPLES_DIR / "recommendation_log_sample.json"
    if not log.exists():
        pytest.skip("Sample recommendation log not present")
    data = json.loads(log.read_text())
    # Accept either a list or a dict with a list inside
    recs = data if isinstance(data, list) else data.get("recommendations", [])
    assert len(recs) >= 0  # just validate it parses


def test_report_quality_evaluate_on_sample(tmp_path):
    """evaluate() should not crash on plausible input; returns structured result."""
    from src.report_quality import evaluate

    recommendation = {
        "session_summary": "Test session.",
        "portfolio_health": {"total_value_usd": 50000},
        "recommendations": [
            {
                "ticker": "AAPL",
                "action": "HOLD",
                "conviction_score": 7,
                "time_horizon": "3-6 months",
                "thesis": "Strong fundamentals with services growth continuing.",
                "sector": "Technology",
            }
        ],
        "warnings": [],
        "sector_warnings": [],
    }
    portfolio = {
        "holdings": [
            {
                "ticker": "AAPL",
                "market_value": 10000,
                "cost_basis": 8000,
                "market_value_currency": "USD",
            }
        ]
    }
    result = evaluate(
        recommendation=recommendation,
        market_data={},
        portfolio=portfolio,
        news_by_ticker={},
        enriched={},
    )
    assert result is not None
    # evaluate() returns a list of warning dicts
    assert isinstance(result, list)
