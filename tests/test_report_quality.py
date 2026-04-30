from src.report_quality import apply_quality_gates, evaluate


def _recommendation(action="BUY"):
    return {
        "recommendations": [
            {
                "ticker": "MSFT",
                "action": action,
                "conviction": 7,
                "thesis": "If catalyst holds, buy; if it fails, hold.",
                "net_expected_pct": 4,
                "fee_hurdle_pct": 0.1,
                "time_horizon": "1-3 months",
                "price_target_low_pct": -5,
                "price_target_high_pct": 12,
                "risk_controls": {},
                "catalyst_verified": False,
                "manual_review_required": False,
            }
        ]
    }


def test_quality_flags_stale_quote_missing_catalyst_and_quote_mismatch():
    warnings = evaluate(
        _recommendation("BUY"),
        {
            "MSFT": {
                "current_price": 110,
                "currency": "USD",
                "previous_close": 100,
                "change_pct_1d": 10,
                "price_basis": "daily_history_close",
                "quote_timestamp_utc": None,
            }
        },
        portfolio={
            "holdings": [
                {
                    "ticker": "MSFT",
                    "market_price": 100,
                    "market_currency": "USD",
                    "market_value": 2600,
                    "market_value_currency": "USD",
                    "quantity": 1,
                }
            ]
        },
        news_by_ticker={"MSFT": []},
        settings={"max_position_pct": 25, "quote_reconciliation_threshold_pct": 1.5},
    )

    codes = {warning["code"] for warning in warnings}
    assert "stale_or_unstamped_quote" in codes
    assert "quote_source_mismatch" in codes
    assert "missing_catalyst_verification" in codes
    assert "missing_entry_zone" in codes


def test_quality_gate_downgrades_unverified_large_move_buy():
    recommendation = _recommendation("BUY")
    warnings = [{"code": "missing_catalyst_verification", "ticker": "MSFT"}]

    gated = apply_quality_gates(recommendation, warnings)
    rec = gated["recommendations"][0]

    assert rec["action"] == "HOLD"
    assert rec["invest_amount_usd"] is None
    assert rec["manual_review_required"] is True
    assert gated["priority_actions"] == []
