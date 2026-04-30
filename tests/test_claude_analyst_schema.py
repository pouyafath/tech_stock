import jsonschema

from src.claude_analyst import RECOMMENDATION_SCHEMA, normalize_recommendation


def test_normalization_adds_risk_and_catalyst_fields_and_sorts_range():
    recommendation = {
        "session_summary": "test",
        "portfolio_health": {},
        "recommendations": [
            {
                "ticker": "msft",
                "action": "HOLD",
                "conviction": 5,
                "thesis": "If price holds, keep; if it breaks, trim.",
                "net_expected_pct": 0,
                "fee_hurdle_pct": 0,
                "time_horizon": "1-3 months",
                "price_target_low_pct": 10,
                "price_target_high_pct": -5,
            }
        ],
        "warnings": [],
    }

    out = normalize_recommendation(recommendation)
    rec = out["recommendations"][0]

    assert rec["ticker"] == "MSFT"
    assert rec["price_target_low_pct"] == -5
    assert rec["price_target_high_pct"] == 10
    assert rec["risk_controls"]["stop_loss_pct"] is None
    assert rec["catalyst_verified"] is False
    assert rec["manual_review_required"] is False
    assert rec["hold_tier"] == "watch"


def test_schema_accepts_new_fields():
    payload = {
        "session_summary": "test",
        "portfolio_health": {"risk_dashboard": {"beta": {"QQQ": 1.2}}},
        "hedge_suggestions": [
            {
                "type": "inverse_etf",
                "instrument": "PSQ",
                "action": "OPTIONAL_SHORT_TERM_HEDGE",
                "max_portfolio_pct": 3,
                "rationale": "test",
                "risk_note": "test",
            }
        ],
        "recommendations": [
            {
                "ticker": "MSFT",
                "action": "HOLD",
                "conviction": 6,
                "thesis": "If trend holds, keep; if it fails, trim.",
                "net_expected_pct": 1,
                "fee_hurdle_pct": 0.1,
                "time_horizon": "1-3 months",
                "risk_controls": {
                    "entry_zone_low_pct": -2,
                    "entry_zone_high_pct": 1,
                    "stop_loss_pct": -8,
                    "take_profit_pct": 12,
                },
                "catalyst_verified": False,
                "catalyst_source": None,
                "manual_review_required": False,
            }
        ],
        "warnings": [],
    }
    jsonschema.validate(payload, RECOMMENDATION_SCHEMA)
