from datetime import datetime, timedelta

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
    assert rec["conviction"] <= 5
    assert rec["hold_tier"] == "watch"
    assert rec["invest_amount_usd"] is None
    assert rec["manual_review_required"] is True
    assert gated["priority_actions"] == []


def test_quality_flags_normalized_range_and_near_earnings_catalyst():
    recommendation = _recommendation("BUY")
    rec = recommendation["recommendations"][0]
    rec["range_was_normalized"] = True
    rec["risk_controls"] = {
        "entry_zone_low_pct": -2,
        "entry_zone_high_pct": 1,
        "stop_loss_pct": -7,
        "take_profit_pct": 12,
    }
    warnings = evaluate(
        recommendation,
        {"MSFT": {"current_price": 100, "currency": "USD", "change_pct_1d": 1, "quote_timestamp_utc": "2026-04-30T20:00:00Z"}},
        enriched={"per_ticker": {"MSFT": {"upcoming_earnings": {"date": (datetime.now().date() + timedelta(days=3)).isoformat()}}}},
        news_by_ticker={"MSFT": []},
        settings={"news_catalyst_move_threshold_pct": 5},
    )

    codes = {warning["code"] for warning in warnings}
    assert "reversed_price_range" in codes
    assert "missing_catalyst_verification" in codes


def test_quality_flags_missing_decision_tree():
    recommendation = _recommendation("HOLD")
    recommendation["recommendations"][0]["thesis"] = "Strong company with solid trend."
    recommendation["recommendations"][0]["risk_or_invalidation"] = "Support break."

    warnings = evaluate(recommendation, {"MSFT": {"quote_timestamp_utc": "2026-04-30T20:00:00Z"}})

    assert "missing_decision_tree" in {warning["code"] for warning in warnings}
