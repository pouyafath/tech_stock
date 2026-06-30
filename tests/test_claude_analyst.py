"""Unit tests for src/claude_analyst.py — no live API calls."""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.claude_analyst import (
    _normalize_time_horizon,
    _parse_validate_recommendation,
    normalize_recommendation,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_rec(**overrides) -> dict:
    """Return a minimal valid recommendation payload for one ticker."""
    rec = {
        "ticker": "AAPL",
        "action": "HOLD",
        "conviction": 7,
        "thesis": "If earnings beat, keep; if miss, trim.",
        "net_expected_pct": 2.0,
        "fee_hurdle_pct": 0.5,
        "time_horizon": "1-3 months",
    }
    rec.update(overrides)
    return rec


def _minimal_payload(**overrides) -> dict:
    """Return a minimal valid top-level recommendation payload."""
    payload = {
        "session_summary": "Test session.",
        "portfolio_health": {},
        "recommendations": [_minimal_rec()],
        "warnings": [],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# normalize_recommendation — ticker normalisation
# ---------------------------------------------------------------------------


def test_normalize_recommendation_missing_ticker():
    """Empty ticker becomes 'UNKNOWN'."""
    payload = _minimal_payload(recommendations=[_minimal_rec(ticker="")])
    result = normalize_recommendation(payload)
    assert result["recommendations"][0]["ticker"] == "UNKNOWN"


def test_normalize_recommendation_none_ticker():
    """None ticker also becomes 'UNKNOWN'."""
    payload = _minimal_payload(recommendations=[_minimal_rec(ticker=None)])
    result = normalize_recommendation(payload)
    assert result["recommendations"][0]["ticker"] == "UNKNOWN"


def test_normalize_recommendation_ticker_uppercased():
    """Known ticker is uppercased."""
    payload = _minimal_payload(recommendations=[_minimal_rec(ticker="msft")])
    result = normalize_recommendation(payload)
    assert result["recommendations"][0]["ticker"] == "MSFT"


def test_normalize_recommendation_unknown_action_becomes_hold():
    """Unrecognised action collapses to HOLD."""
    payload = _minimal_payload(recommendations=[_minimal_rec(action="YOLO")])
    result = normalize_recommendation(payload)
    assert result["recommendations"][0]["action"] == "HOLD"


def test_normalize_recommendation_conviction_defaults_to_5():
    """Missing conviction defaults to 5."""
    rec = _minimal_rec()
    del rec["conviction"]
    payload = _minimal_payload(recommendations=[rec])
    result = normalize_recommendation(payload)
    assert result["recommendations"][0]["conviction"] == 5


# ---------------------------------------------------------------------------
# _normalize_time_horizon
# ---------------------------------------------------------------------------


def test_normalize_time_horizon_canonical_pass_through():
    """Canonical values are returned unchanged."""
    for horizon in ("intraday", "next session", "1-3 months", "12-36 months"):
        assert _normalize_time_horizon(horizon) == horizon


def test_normalize_time_horizon_known_variants():
    """Common Claude-drift variants map to canonical values."""
    assert _normalize_time_horizon("long term") == "12-36 months"
    assert _normalize_time_horizon("tomorrow") == "next session"
    assert _normalize_time_horizon("next quarter") == "1-3 months"
    assert _normalize_time_horizon("1 week") == "1-2 weeks"
    assert _normalize_time_horizon("2 years") == "12-36 months"


def test_normalize_time_horizon_unknown_falls_back():
    """Completely unknown values fall back to '1-3 months'."""
    assert _normalize_time_horizon("whenever") == "1-3 months"
    assert _normalize_time_horizon("sometime soon") == "1-3 months"


def test_normalize_time_horizon_empty_falls_back():
    """None/empty values fall back to '1-3 months'."""
    assert _normalize_time_horizon(None) == "1-3 months"
    assert _normalize_time_horizon("") == "1-3 months"


# ---------------------------------------------------------------------------
# _parse_validate_recommendation
# ---------------------------------------------------------------------------


def test_parse_validate_recommendation_valid():
    """Valid JSON with required fields passes without error."""
    raw = json.dumps(_minimal_payload())
    result = _parse_validate_recommendation(raw)
    assert isinstance(result, dict)
    assert "recommendations" in result


def test_parse_validate_recommendation_missing_session_summary():
    """Missing session_summary raises ValueError (schema violation)."""
    payload = _minimal_payload()
    del payload["session_summary"]
    raw = json.dumps(payload)
    with pytest.raises(ValueError, match="schema validation"):
        _parse_validate_recommendation(raw)


def test_parse_validate_recommendation_non_json():
    """Non-JSON input raises ValueError."""
    with pytest.raises(ValueError, match="non-JSON"):
        _parse_validate_recommendation("this is not json")


def test_parse_validate_recommendation_strips_markdown_fence():
    """JSON wrapped in markdown code fences is accepted."""
    raw = "```json\n" + json.dumps(_minimal_payload()) + "\n```"
    result = _parse_validate_recommendation(raw)
    assert "session_summary" in result


# ---------------------------------------------------------------------------
# Pass 2 fallback — mock _create_parse_message raising on second call
# ---------------------------------------------------------------------------


def test_call_claude_pass2_fallback(tmp_path, monkeypatch):
    """When Pass 2 _create_parse_message raises, call_claude falls back to Pass 1 result with pass2_fallback=True."""
    import src.claude_analyst as analyst_module

    first_rec = _minimal_payload(session_summary="Pass 1 output")
    first_usage = {
        "cost_usd": 0.01,
        "total_tokens": 100,
        "input_tokens": 80,
        "output_tokens": 20,
        "cache_write_tokens": 0,
        "cache_read_tokens": 0,
        "cache_hit": False,
        "retries": 0,
    }

    call_count = {"n": 0}

    def fake_create_parse(client, model, settings, messages):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return first_rec, first_usage
        raise ValueError("Simulated Pass 2 failure")

    # Minimal stubs for the heavy collaborators
    fake_settings = {
        "claude_model": "claude-sonnet-4-6",
        "cad_per_usd_assumption": 1.37,
        "max_position_pct": 25,
        "drift_conviction_delta": 2,
    }

    with (
        patch.object(analyst_module, "_create_parse_message", side_effect=fake_create_parse),
        patch.object(analyst_module, "load_settings", return_value=fake_settings),
        patch.object(analyst_module, "build_user_message", return_value="stub user message"),
        patch.object(analyst_module, "compute_drift", return_value=[]),
        patch.object(analyst_module, "evaluate_report_quality", return_value=[]),
        patch.object(analyst_module, "apply_quality_gates", side_effect=lambda rec, *a, **kw: rec),
        patch.object(analyst_module, "build_hedge_suggestions", return_value=[]),
        patch("anthropic.Anthropic", return_value=MagicMock()),
        patch("src.position_aging.annotate_holdings", return_value=[]) as _ph1,
        patch("src.position_aging.aging_summary", return_value={}) as _ph2,
        patch("src.trailing_stops.evaluate", return_value=[]) as _ph3,
    ):
        recommendation, usage = analyst_module.call_claude(
            session_type="morning",
            portfolio={"holdings": []},
            market_data={},
            news_by_ticker={},
            fee_snapshot={},
        )

    assert recommendation.get("pass2_fallback") is True
    assert recommendation.get("session_summary") == "Pass 1 output"


def test_typical_run_cost_matches_pricing_keys():
    """typical_run_cost must cover every model in MODEL_PRICING and fall back
    to the default for unknown models — guards the budget/menu single source."""
    from src.claude_analyst import (
        _DEFAULT_RUN_COST_USD,
        MODEL_PRICING,
        TYPICAL_RUN_COST_USD,
        typical_run_cost,
    )

    for model in MODEL_PRICING:
        assert model in TYPICAL_RUN_COST_USD, f"missing run-cost estimate for {model}"
        assert typical_run_cost(model) == TYPICAL_RUN_COST_USD[model]

    # Opus costs more than Sonnet, Sonnet more than Haiku.
    assert typical_run_cost("claude-opus-4-7") > typical_run_cost("claude-sonnet-4-6")
    assert typical_run_cost("claude-sonnet-4-6") > typical_run_cost("claude-haiku-4-5")

    # Unknown model → default estimate, never a crash.
    assert typical_run_cost("some-future-model") == _DEFAULT_RUN_COST_USD
