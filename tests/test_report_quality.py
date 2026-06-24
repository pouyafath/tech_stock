from datetime import datetime, timedelta

from src.report_quality import apply_quality_gates, evaluate


def _codes(warnings):
    return {warning["code"] for warning in warnings}


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

    codes = _codes(warnings)
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
    assert rec["trade_readiness"] == "BLOCKED"
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

    codes = _codes(warnings)
    assert "reversed_price_range" in codes
    assert "missing_catalyst_verification" in codes


def test_quality_flags_missing_decision_tree():
    recommendation = _recommendation("HOLD")
    recommendation["recommendations"][0]["thesis"] = "Strong company with solid trend."
    recommendation["recommendations"][0]["risk_or_invalidation"] = "Support break."

    warnings = evaluate(recommendation, {"MSFT": {"quote_timestamp_utc": "2026-04-30T20:00:00Z"}})

    assert "missing_decision_tree" in _codes(warnings)


def test_decision_tree_allows_action_before_if_clause():
    recommendation = _recommendation("TRIM")
    rec = recommendation["recommendations"][0]
    rec["thesis"] = "Trim 20% if RSI exceeds 78; hold if price reclaims support."
    rec["risk_or_invalidation"] = "Sell if support fails."
    rec["risk_controls"] = {"stop_loss_pct": 6}

    warnings = evaluate(recommendation, {"MSFT": {"quote_timestamp_utc": "2026-04-30T20:00:00Z"}})

    assert "missing_decision_tree" not in _codes(warnings)


def test_quality_flags_missing_stop_loss_and_invalid_horizon():
    recommendation = _recommendation("SELL")
    rec = recommendation["recommendations"][0]
    rec["time_horizon"] = "soon"
    rec["risk_controls"] = {}

    warnings = evaluate(recommendation, {"MSFT": {"quote_timestamp_utc": "2026-04-30T20:00:00Z"}})

    codes = _codes(warnings)
    assert "missing_stop_loss" in codes
    assert "invalid_time_horizon" in codes


def test_quality_flags_oversized_position_and_buy_add_cap():
    recommendation = _recommendation("BUY")
    recommendation["recommendations"][0]["risk_controls"] = {
        "entry_zone_low_pct": -2,
        "entry_zone_high_pct": 1,
        "stop_loss_pct": -8,
        "take_profit_pct": 12,
    }

    warnings = evaluate(
        recommendation,
        {"MSFT": {"current_price": 100, "currency": "USD", "change_pct_1d": 0, "quote_timestamp_utc": "2026-04-30T20:00:00Z"}},
        portfolio={
            "holdings": [
                {"ticker": "MSFT", "market_value": 1000, "market_value_currency": "USD", "quantity": 10},
            ]
        },
        settings={"max_position_pct": 25},
    )

    codes = _codes(warnings)
    assert "oversized_company_exposure" in codes
    assert "buy_add_over_position_cap" in codes


def test_quality_flags_missing_enrichment_citations():
    recommendation = _recommendation("HOLD")
    rec = recommendation["recommendations"][0]
    rec["thesis"] = "If trend holds, keep; if it breaks, trim."
    rec["risk_or_invalidation"] = "If support fails, trim."

    warnings = evaluate(
        recommendation,
        {"MSFT": {"quote_timestamp_utc": "2026-04-30T20:00:00Z"}},
        enriched={
            "per_ticker": {
                "MSFT": {
                    "analyst_consensus": {"consensus_label": "BUY"},
                    "insider_activity": {"signal": "SELLING"},
                }
            }
        },
    )

    codes = _codes(warnings)
    assert "missing_analyst_citation" in codes
    assert "missing_insider_citation" in codes


def test_quality_flags_high_conviction_missing_analyst_and_target_sources():
    recommendation = _recommendation("BUY")
    rec = recommendation["recommendations"][0]
    rec["conviction"] = 9
    rec["risk_controls"] = {"entry_zone_low_pct": -2, "entry_zone_high_pct": 1}

    warnings = evaluate(
        recommendation,
        {"MSFT": {"current_price": 100, "currency": "USD", "change_pct_1d": 0, "quote_timestamp_utc": "2026-04-30T20:00:00Z"}},
        settings={"high_conviction_source_threshold": 8},
    )

    codes = _codes(warnings)
    assert "missing_analyst_source" in codes
    assert "missing_price_target_source" in codes


def test_quality_flags_near_earnings_missing_options_implied_move():
    recommendation = _recommendation("BUY")
    recommendation["recommendations"][0]["risk_controls"] = {"entry_zone_low_pct": -2, "entry_zone_high_pct": 1}

    warnings = evaluate(
        recommendation,
        {"MSFT": {"current_price": 100, "currency": "USD", "change_pct_1d": 0, "quote_timestamp_utc": "2026-04-30T20:00:00Z"}},
        enriched={"per_ticker": {"MSFT": {"upcoming_earnings": {"date": (datetime.now().date() + timedelta(days=2)).isoformat()}}}},
        news_by_ticker={"MSFT": [{"title": "Fresh catalyst", "published_at": datetime.now().strftime("%Y-%m-%d %H:%M")}]},
    )

    assert "missing_options_implied_move" in _codes(warnings)


def test_quality_flags_stale_catalyst_source():
    recommendation = _recommendation("BUY")
    rec = recommendation["recommendations"][0]
    rec["catalyst_verified"] = True
    rec["catalyst_source"] = "Yahoo Finance"
    rec["risk_controls"] = {"entry_zone_low_pct": -2, "entry_zone_high_pct": 1}
    old = (datetime.now().date() - timedelta(days=14)).strftime("%Y-%m-%d %H:%M")

    warnings = evaluate(
        recommendation,
        {"MSFT": {"current_price": 100, "currency": "USD", "change_pct_1d": 8, "quote_timestamp_utc": "2026-04-30T20:00:00Z"}},
        news_by_ticker={"MSFT": [{"title": "Old catalyst", "published_at": old}]},
        settings={"catalyst_max_age_days": 7},
    )

    assert "stale_catalyst_source" in _codes(warnings)


def test_quality_flags_market_data_error():
    warnings = evaluate(_recommendation("HOLD"), {"MSFT": {"error": "provider down"}})

    assert "market_data_error" in _codes(warnings)


def test_macro_regime_conviction_gate_fires():
    """Gate fires when macro_regime has conviction_cap and a BUY has conviction below cap."""
    recommendation = _recommendation("BUY")
    recommendation["recommendations"][0]["conviction"] = 6
    recommendation["macro_regime"] = {"regime": "bear", "conviction_cap": 9}

    warnings = evaluate(
        recommendation,
        {"MSFT": {"current_price": 100, "currency": "USD", "change_pct_1d": 0, "quote_timestamp_utc": "2026-04-30T20:00:00Z"}},
    )

    assert "macro_regime_conviction" in _codes(warnings)


def test_macro_regime_conviction_gate_does_not_fire_with_wrong_key():
    """Gate must NOT fire when using the old wrong key market_context instead of macro_regime."""
    recommendation = _recommendation("BUY")
    recommendation["recommendations"][0]["conviction"] = 6
    # Set via old wrong key — gate should not see it
    recommendation["market_context"] = {"macro_regime": {"regime": "bear", "conviction_cap": 9}}

    warnings = evaluate(
        recommendation,
        {"MSFT": {"current_price": 100, "currency": "USD", "change_pct_1d": 0, "quote_timestamp_utc": "2026-04-30T20:00:00Z"}},
    )

    assert "macro_regime_conviction" not in _codes(warnings)
