from src.recommendation_sizing import apply_trade_sizes


def test_apply_trade_sizes_fills_sell_and_trim_amounts():
    recommendation = {
        "priority_actions": [
            {"order": 1, "ticker": "GOOG", "action": "SELL", "rationale": "duplicate"},
            {"order": 2, "ticker": "ARKF", "action": "TRIM", "rationale": "stop"},
        ],
        "recommendations": [
            {"ticker": "GOOG", "action": "SELL"},
            {
                "ticker": "ARKF",
                "action": "TRIM",
                "exit_plan": [{"trigger": "now", "fraction": 0.6, "price_pct": 0}],
            },
        ],
    }
    portfolio = {
        "holdings": [
            {"ticker": "GOOG", "quantity": 0.7247, "market_price": 350.33, "market_currency": "USD"},
            {"ticker": "ARKF", "quantity": 2.0, "market_price": 40.73, "market_currency": "USD"},
        ]
    }

    out = apply_trade_sizes(
        recommendation,
        portfolio,
        {"ARKF": {"current_price": 42.26, "currency": "USD"}},
    )

    goog = next(rec for rec in out["recommendations"] if rec["ticker"] == "GOOG")
    arkf = next(rec for rec in out["recommendations"] if rec["ticker"] == "ARKF")

    assert goog["shares"] == 0.7247
    assert goog["action_fraction"] == 1.0
    assert goog["action_amount"] == 253.88
    assert "100% of position" in goog["action_size_label"]
    assert arkf["shares"] == 1.2
    assert arkf["action_fraction"] == 0.6
    assert arkf["action_amount"] == 50.71
    assert out["priority_actions"][0]["action_size_label"] == goog["action_size_label"]


def test_apply_trade_sizes_defaults_trim_to_30_percent():
    recommendation = {"recommendations": [{"ticker": "MSFT", "action": "TRIM"}]}
    portfolio = {"holdings": [{"ticker": "MSFT", "quantity": 10, "market_price": 100, "market_currency": "USD"}]}

    out = apply_trade_sizes(recommendation, portfolio)

    assert out["recommendations"][0]["shares"] == 3
    assert out["recommendations"][0]["action_fraction"] == 0.3


def test_apply_trade_sizes_syncs_buy_amount_to_priority_actions():
    recommendation = {
        "priority_actions": [
            {"order": 1, "ticker": "CRM", "action": "BUY", "invest_amount_usd": 175},
        ],
        "recommendations": [
            {"ticker": "CRM", "action": "BUY", "invest_amount_usd": 70},
        ],
    }

    out = apply_trade_sizes(recommendation, portfolio={})

    assert out["priority_actions"][0]["invest_amount_usd"] == 70
