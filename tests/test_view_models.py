from src.view_models import (
    BLOCKED,
    REVIEW_FIRST,
    TRADE_READY,
    build_api_health_view,
    build_buy_signals_view,
    build_decision_journal_view,
    classify_trade_readiness,
)


def _candidate(**overrides):
    base = {
        "ticker": "NVDA",
        "action": "BUY",
        "conviction": 8,
        "current_price": 200,
        "quote_timestamp_utc": "2026-05-18T15:30:00Z",
        "quote_source": "yfinance:regularMarketPrice",
        "analyst_consensus": {"total_analysts": 40, "consensus_label": "STRONG BUY"},
        "price_targets": {"mean": 250, "mean_upside_pct": 25.0},
        "quality_warnings": [],
        "source_notes": ["Quote: yfinance:regularMarketPrice", "Analyst targets: Yahoo Finance via yfinance"],
    }
    base.update(overrides)
    return base


def test_classify_trade_readiness_trade_ready():
    result = classify_trade_readiness(_candidate())

    assert result["status"] == TRADE_READY
    assert result["label"] == "Trade Ready"


def test_classify_trade_readiness_blocks_stale_quote_and_catalyst_warning():
    result = classify_trade_readiness(
        _candidate(
            quote_timestamp_utc=None,
            quality_warnings=[{"severity": "high", "code": "missing_catalyst_verification"}],
        )
    )

    assert result["status"] == BLOCKED
    assert any("Quote is stale" in reason for reason in result["reasons"])
    assert any("missing_catalyst_verification" in reason for reason in result["reasons"])


def test_classify_trade_readiness_review_first_for_manual_review_or_optional_sources():
    result = classify_trade_readiness(
        _candidate(
            manual_review_required=True,
            analyst_consensus={},
            source_notes=["Analyst targets: unavailable"],
        )
    )

    assert result["status"] == REVIEW_FIRST
    assert any("Manual review" in reason for reason in result["reasons"])


def test_classify_trade_readiness_blocks_source_confidence_blocker():
    result = classify_trade_readiness(
        _candidate(
            source_confidence={
                "overall_status": "BLOCKED",
                "blockers": ["Verify catalyst manually before buying/adding."],
            }
        )
    )

    assert result["status"] == BLOCKED
    assert any("Verify catalyst" in reason for reason in result["reasons"])


def test_build_buy_signals_view_filters_action_and_readiness():
    raw = {
        "session_file": "latest.json",
        "candidates": [
            _candidate(ticker="NVDA", action="BUY"),
            _candidate(
                ticker="MSFT",
                action="HOLD",
                hold_tier="add_on_dip",
                quality_warnings=[{"severity": "medium", "code": "quote_source_mismatch"}],
            ),
            _candidate(ticker="SOXL", action="BUY", quote_timestamp_utc=None),
        ],
    }

    view = build_buy_signals_view(raw, action_filter="add_on_dip", readiness_filter="REVIEW_FIRST")

    assert view["counts"]["total"] == 3
    assert view["counts"][TRADE_READY] == 1
    assert view["counts"][REVIEW_FIRST] == 1
    assert view["counts"][BLOCKED] == 1
    assert [row["ticker"] for row in view["overview_rows"]] == ["MSFT"]
    assert view["data_confidence"]["readiness_counts"][BLOCKED] == 1


def test_build_buy_signals_view_filters_source_confidence():
    raw = {
        "session_file": "latest.json",
        "candidates": [
            _candidate(ticker="NVDA"),
            _candidate(
                ticker="AMD",
                source_confidence={
                    "overall_status": "REVIEW_FIRST",
                    "label": "Review First",
                    "filters": ["missing_analyst"],
                    "review_reasons": ["Do not treat analyst consensus/targets as sourced."],
                    "components": {
                        "quote": {"status": "OK"},
                        "catalyst": {"status": "OK"},
                        "analyst": {"status": "MISSING"},
                    },
                },
            ),
        ],
    }

    view = build_buy_signals_view(raw, source_filter="missing_analyst")

    assert [row["ticker"] for row in view["overview_rows"]] == ["AMD"]
    assert view["overview_rows"][0]["source_confidence"] == "Review First"
    assert view["counts"]["missing_analyst"] == 1


def test_api_and_decision_journal_view_models():
    health = build_api_health_view(
        [
            {"source": "Anthropic", "ok": True},
            {"source": "Finnhub", "ok": False, "detail": "missing"},
        ]
    )
    journal = build_decision_journal_view({"status": {"pending": 2, "recorded": 3}, "entries": [{"id": "x"}]})

    assert health["ok_count"] == 1
    assert health["fail_count"] == 1
    assert health["storage_mode"] == "API_KEYS.txt / .env files"
    assert journal["pending_count"] == 2
    assert journal["recorded_count"] == 3
