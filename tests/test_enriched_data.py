from src.enriched_data import _enrich_ticker_fast, format_enrichment_for_prompt


def test_enrichment_degradation_is_structured(monkeypatch):
    def fail(_ticker):
        raise RuntimeError("provider down")

    monkeypatch.setattr("src.enriched_data.recommendation_trends", fail)
    monkeypatch.setattr("src.enriched_data.upgrade_downgrade", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("src.enriched_data.earnings_calendar", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("src.enriched_data.earnings_surprises", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("src.enriched_data.insider_summary", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("src.enriched_data.finnhub_sentiment", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("src.enriched_data.stock_snapshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("src.enriched_data.td_quote", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("src.enriched_data.td_earnings", lambda *_args, **_kwargs: None)

    result = _enrich_ticker_fast("MSFT")

    assert result["_degradation"][0]["source"] == "finnhub"
    assert result["_degradation"][0]["ticker"] == "MSFT"


def test_enrichment_prompt_renders_degradation():
    text = format_enrichment_for_prompt({
        "per_ticker": {"MSFT": {}},
        "macro": None,
        "crypto": None,
        "sources_active": [],
        "degradation": [
            {"source": "finnhub", "operation": "recommendation_trends", "ticker": "MSFT", "error": "down"}
        ],
    })

    assert "Data Coverage / Degradation" in text
    assert "MSFT: finnhub.recommendation_trends unavailable" in text
