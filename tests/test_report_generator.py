from src.report_generator import generate_markdown


def test_report_renders_quality_risk_hedge_and_bear_bull_sections():
    recommendation = {
        "session_summary": "Risk is elevated.",
        "portfolio_health": {
            "total_value_usd_equivalent": 10000,
            "overall_pnl_pct": 5,
            "concentration_risk": "high",
            "cash_deployment": "limited",
        },
        "quality_warnings": [
            {
                "severity": "high",
                "code": "stale_or_unstamped_quote",
                "ticker": "MSFT",
                "message": "Quote stale.",
                "action_required": "Verify quote.",
            }
        ],
        "hedge_suggestions": [
            {
                "type": "inverse_etf",
                "instrument": "PSQ",
                "action": "OPTIONAL_SHORT_TERM_HEDGE",
                "max_portfolio_pct": 3,
                "rationale": "Offset tech beta.",
                "risk_note": "Daily reset risk.",
            }
        ],
        "recommendations": [
            {
                "ticker": "MSFT",
                "action": "HOLD",
                "conviction": 6,
                "thesis": "If support holds, keep; if it fails, trim.",
                "risk_or_invalidation": "If support breaks, trim.",
                "technical_basis": "Above SMA200.",
                "liquidity_tier": "megacap",
                "expected_move_pct": 8,
                "fee_hurdle_pct": 0.1,
                "net_expected_pct": 7.9,
                "time_horizon": "1-3 months",
                "price_target_low_pct": -5,
                "price_target_high_pct": 12,
                "risk_controls": {
                    "entry_zone_low_pct": -3,
                    "entry_zone_high_pct": 1,
                    "stop_loss_pct": -8,
                    "take_profit_pct": 12,
                },
                "catalyst_verified": False,
                "catalyst_source": None,
                "manual_review_required": False,
                "hold_tier": "keep",
            }
        ],
        "warnings": [],
    }

    markdown = generate_markdown(
        "afternoon",
        recommendation,
        {"MSFT": {"current_price": 100, "currency": "USD", "error": None, "quote_source": "test"}},
        portfolio={"holdings": []},
        risk_dashboard={
            "total_value_usd": 10000,
            "annualized_volatility_pct": 32.5,
            "max_drawdown_estimate_pct": -18.2,
            "top3_concentration_pct": 70,
            "beta": {"QQQ": 1.2},
            "correlated_pairs": [],
        },
        company_exposure={"MSFT": {"company": "MSFT", "value_usd": 3000, "pct": 30, "tickers": ["MSFT"]}},
        usage={"passes": 2, "total_tokens": 1000, "cost_usd": 0.22},
    )

    assert "## Report Quality Warnings" in markdown
    assert "## Critical Actions" in markdown
    assert "Source footnote" in markdown
    assert "## Portfolio Risk Dashboard" in markdown
    assert "## Hedge And Rebalance Suggestions" in markdown
    assert "Bear Case" in markdown
    assert "Bull Case" in markdown
    assert "Claude passes: 2" in markdown
