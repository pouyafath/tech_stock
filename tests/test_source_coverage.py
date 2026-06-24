from src.source_coverage import build_source_coverage, build_source_provenance, build_ticker_source_confidence


def test_source_coverage_reports_required_and_optional_sources():
    payload = build_source_coverage(
        recommendation={
            "recommendations": [
                {
                    "ticker": "NVDA",
                    "action": "ADD",
                    "catalyst_verified": True,
                    "catalyst_source": "Yahoo Finance",
                }
            ],
            "market_context_snapshot": {"vix": 14.5},
        },
        market_data={
            "NVDA": {
                "current_price": 100,
                "quote_timestamp_utc": "2026-06-24T14:30:00Z",
                "analyst_target_mean": 125,
                "forward_pe": 30,
                "options_implied_move_pct": 6.5,
            }
        },
        enriched={
            "per_ticker": {
                "NVDA": {
                    "analyst_consensus": {"buy": 30},
                    "insider_activity": {"net_shares": 10},
                }
            }
        },
        news_by_ticker={"NVDA": [{"title": "AI demand"}]},
    )

    assert payload["status"] == "OK"
    rows = {row["source"]: row for row in payload["rows"]}
    assert rows["Quotes"]["status"] == "OK"
    assert rows["News/catalyst"]["status"] == "OK"
    assert rows["Analyst consensus/targets"]["status"] == "OK"


def test_source_coverage_blocks_missing_required_quote_and_catalyst():
    payload = build_source_coverage(
        recommendation={"recommendations": [{"ticker": "AMD", "action": "BUY"}]},
        market_data={},
        enriched={},
        news_by_ticker={},
    )

    assert payload["status"] == "BLOCKED"
    rows = {row["source"]: row for row in payload["rows"]}
    assert rows["Quotes"]["status"] == "MISSING"
    assert rows["News/catalyst"]["status"] == "MISSING"
    assert payload["required_missing_count"] >= 2


def test_source_coverage_marks_provider_degradation():
    payload = build_source_coverage(
        recommendation={"recommendations": [{"ticker": "MSFT", "action": "HOLD"}]},
        market_data={"MSFT": {"quote_timestamp_utc": "2026-06-24T14:30:00Z"}},
        enriched={"degradation": [{"source": "finnhub", "operation": "analyst_consensus"}]},
    )

    rows = {row["source"]: row for row in payload["rows"]}
    assert rows["Analyst consensus/targets"]["status"] == "DEGRADED"
    assert payload["degraded_count"] >= 1


def test_ticker_source_confidence_blocks_missing_buy_catalyst_and_quote():
    confidence = build_ticker_source_confidence(
        recommendation={"ticker": "AMD", "action": "BUY"},
        market_data={},
        enriched={},
        news=[],
    )

    assert confidence["overall_status"] == "BLOCKED"
    assert "missing_catalyst" in confidence["filters"]
    assert "quote_not_timestamped" in confidence["filters"]
    assert confidence["components"]["quote"]["status"] == "MISSING"


def test_ticker_source_confidence_reviews_missing_optional_analyst():
    confidence = build_ticker_source_confidence(
        recommendation={"ticker": "NVDA", "action": "ADD", "catalyst_verified": True, "catalyst_source": "Yahoo Finance"},
        market_data={"current_price": 100, "quote_timestamp_utc": "2026-06-24T14:30:00Z"},
        enriched={},
        news=[{"title": "Fresh catalyst"}],
    )

    assert confidence["overall_status"] == "REVIEW_FIRST"
    assert "missing_analyst" in confidence["filters"]
    assert confidence["components"]["catalyst"]["status"] == "OK"


def test_source_provenance_reports_ticker_provider_rows():
    provenance = build_source_provenance(
        recommendation={
            "recommendations": [
                {
                    "ticker": "NVDA",
                    "action": "ADD",
                    "catalyst_verified": True,
                    "catalyst_source": "Yahoo Finance",
                }
            ]
        },
        market_data={
            "NVDA": {
                "current_price": 100,
                "quote_source": "yfinance:regularMarketPrice",
                "quote_timestamp_utc": "2026-06-24T14:30:00Z",
                "analyst_target_mean": 125,
            }
        },
        enriched={"per_ticker": {"NVDA": {"analyst_consensus": {"buy": 30}}}},
        news_by_ticker={"NVDA": [{"title": "AI demand", "source": "Yahoo", "published_at": "2026-06-24T13:00:00Z"}]},
    )

    assert provenance["status"] in {"OK", "PARTIAL", "REVIEW_FIRST"}
    quote = next(row for row in provenance["rows"] if row["ticker"] == "NVDA" and row["source"] == "Quote")
    assert quote["provider"] == "yfinance:regularMarketPrice"
    catalyst = next(row for row in provenance["rows"] if row["ticker"] == "NVDA" and row["source"] == "Catalyst")
    assert catalyst["timestamp"] == "2026-06-24T13:00:00Z"
