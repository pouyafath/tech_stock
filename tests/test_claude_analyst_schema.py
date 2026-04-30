import json
from types import SimpleNamespace

import jsonschema

from src.claude_analyst import RECOMMENDATION_SCHEMA, _market_phase, _response_text, call_claude, normalize_recommendation


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
    assert rec["range_was_normalized"] is True
    assert rec["risk_controls"]["stop_loss_pct"] is None
    assert rec["catalyst_verified"] is False
    assert rec["manual_review_required"] is False
    assert rec["hold_tier"] == "watch"


def test_normalization_defaults_missing_required_model_fields():
    recommendation = {
        "session_summary": "test",
        "portfolio_health": {},
        "recommendations": [{"ticker": "msft"}],
        "warnings": [],
    }

    rec = normalize_recommendation(recommendation)["recommendations"][0]

    assert rec["action"] == "HOLD"
    assert rec["conviction"] == 5
    assert rec["net_expected_pct"] == 0
    assert rec["fee_hurdle_pct"] == 0
    assert rec["time_horizon"] == "1-3 months"


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


def test_response_text_ignores_non_text_blocks():
    response = SimpleNamespace(content=[
        SimpleNamespace(type="thinking", thinking="hidden"),
        SimpleNamespace(type="text", text='{"ok": true}'),
    ])

    assert _response_text(response) == '{"ok": true}'


def test_market_phase_labels_overnight_and_after_close_correctly():
    from datetime import datetime

    assert _market_phase(datetime(2026, 4, 30, 1, 44)) == "outside regular market hours — before next open"
    assert _market_phase(datetime(2026, 4, 30, 16, 0)) == "after regular market close"
    assert _market_phase(datetime(2026, 4, 30, 15, 0)) == "regular session or pre-close"


def _claude_payload(summary: str) -> dict:
    return {
        "session_summary": summary,
        "portfolio_health": {
            "total_value_usd_equivalent": 0,
            "overall_pnl_pct": 0,
            "concentration_risk": "low",
            "cash_deployment": "none",
        },
        "hedge_suggestions": [],
        "priority_actions": [],
        "recommendations": [
            {
                "ticker": "MSFT",
                "action": "HOLD",
                "conviction": 6,
                "thesis": "Hold if support holds; trim if RSI exceeds 78.",
                "technical_basis": "Above SMA200.",
                "liquidity_tier": "megacap",
                "expected_move_pct": 3,
                "fee_hurdle_pct": 0.1,
                "net_expected_pct": 2.9,
                "risk_or_invalidation": "Trim if support fails.",
                "time_horizon": "1-3 months",
                "target_exit_date": "Jul 2026",
                "price_target_low_pct": -4,
                "price_target_high_pct": 8,
                "risk_controls": {
                    "entry_zone_low_pct": -2,
                    "entry_zone_high_pct": 1,
                    "stop_loss_pct": -6,
                    "take_profit_pct": 8,
                },
                "catalyst_verified": False,
                "catalyst_source": None,
                "manual_review_required": False,
                "hold_tier": "keep",
                "earnings_alert": False,
            }
        ],
        "watchlist_flags": [],
        "sector_warnings": [],
        "warnings": [],
    }


def test_call_claude_runs_two_passes_with_mocked_anthropic(monkeypatch):
    created_calls = []

    class FakeMessages:
        def __init__(self):
            self.count = 0

        def create(self, **kwargs):
            self.count += 1
            created_calls.append(kwargs)
            payload = _claude_payload(f"pass {self.count}")
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text=json.dumps(payload))],
                usage=SimpleNamespace(
                    input_tokens=100,
                    output_tokens=50,
                    cache_creation_input_tokens=10 if self.count == 1 else 0,
                    cache_read_input_tokens=20 if self.count == 2 else 0,
                ),
            )

    class FakeAnthropic:
        def __init__(self, **_kwargs):
            self.messages = FakeMessages()

    monkeypatch.setattr("src.claude_analyst.anthropic.Anthropic", FakeAnthropic)

    recommendation, usage = call_claude(
        session_type="afternoon",
        portfolio={"holdings": [], "cash_cad": 0},
        market_data={
            "MSFT": {
                "current_price": 100,
                "currency": "USD",
                "change_pct_1d": 0,
                "quote_timestamp_utc": "2026-04-30T20:00:00Z",
                "price_basis": "regular_market_quote",
                "history": [],
            }
        },
        news_by_ticker={"MSFT": []},
        fee_snapshot={"MSFT": {"hurdle_pct": 0.1, "bid_ask_pct_one_way": 0.05, "total_usd": 1}},
        settings_override={"claude_model": "claude-sonnet-4-6", "claude_max_tokens": 1000},
    )

    assert len(created_calls) == 2
    assert recommendation["session_summary"] == "pass 2"
    assert recommendation["review_passes"] == 2
    assert usage["passes"] == 2
    assert usage["cache_hit"] is True
    assert created_calls[1]["messages"][0]["content"][0]["cache_control"]["type"] == "ephemeral"
