from src.data_confidence import build_data_confidence


def test_data_confidence_high_when_sources_are_clean():
    confidence = build_data_confidence(
        recommendations=[{"ticker": "NVDA", "action": "BUY", "catalyst_verified": True}],
        market_data={"NVDA": {"quote_timestamp_utc": "2026-05-29T14:30:00Z"}},
        quality_warnings=[],
        enriched={"sources_active": ["finnhub"]},
    )

    assert confidence["label"] == "HIGH"
    assert confidence["quote_freshness"] == "fresh_timestamped"
    assert confidence["catalyst_coverage"]["verified_count"] == 1


def test_data_confidence_medium_for_degradation_or_fallback_quotes():
    confidence = build_data_confidence(
        market_data={"MSFT": {"quote_timestamp_utc": "2026-05-29T14:30:00Z", "price_basis": "daily_history_close"}},
        enriched={"degradation": [{"source": "polygon", "error": "rate limited"}]},
    )

    assert confidence["label"] == "MEDIUM"
    assert confidence["fallback_quotes"] == 1
    assert confidence["source_coverage"]["degradation_count"] == 1


def test_data_confidence_low_for_blocking_warnings():
    confidence = build_data_confidence(
        market_data={"AMD": {"error": "market data unavailable"}},
        quality_warnings=[{"severity": "high", "code": "market_data_error"}],
        readiness_counts={"BLOCKED": 1},
    )

    assert confidence["label"] == "LOW"
    assert confidence["status"] == "blocked"
    assert confidence["quote_errors"] == 1
