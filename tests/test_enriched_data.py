from src import enriched_data
from src.enriched_data import _enrich_ticker_fast, enrich, format_enrichment_for_prompt


def test_enrich_disabled_returns_empty_structure(monkeypatch):
    monkeypatch.setattr(enriched_data, "load_settings", lambda: {"enable_enrichment": False})
    out = enrich(["NVDA"])
    assert out == {"per_ticker": {}, "macro": None, "crypto": None, "sources_active": [], "degradation": []}


def test_enrich_orchestrates_and_tallies_active_sources(monkeypatch):
    monkeypatch.setattr(enriched_data, "load_settings", lambda: {"enable_enrichment": True, "enrichment_max_workers": 2})
    monkeypatch.setattr(enriched_data, "economic_calendar_estimate", lambda: {"next_nfp_estimate": "2026-02-06"})
    monkeypatch.setattr(
        enriched_data,
        "_enrich_ticker_fast",
        lambda t: {"analyst_consensus": {"consensus_label": "Buy"}, "polygon_snapshot": {"vwap_pct": 1.0}},
    )
    monkeypatch.setattr(enriched_data, "macro_context", lambda: {"series": {}, "rate_regime": "neutral"})
    monkeypatch.setattr(enriched_data, "crypto_context", lambda: {"btc_price": 60000, "risk_signal": "NEUTRAL"})

    out = enrich(["NVDA"])
    assert out["per_ticker"]["NVDA"]["analyst_consensus"]["consensus_label"] == "Buy"
    assert out["macro"]["rate_regime"] == "neutral"
    assert out["crypto"]["btc_price"] == 60000
    # Sources are tallied from what actually came back.
    for expected in ("finnhub", "polygon", "fred", "coingecko", "calendar_estimate"):
        assert expected in out["sources_active"], f"{expected} not tallied"


def test_enrich_records_degradation_for_failing_ticker(monkeypatch):
    monkeypatch.setattr(enriched_data, "load_settings", lambda: {"enable_enrichment": True})
    monkeypatch.setattr(enriched_data, "economic_calendar_estimate", lambda: None)
    monkeypatch.setattr(enriched_data, "macro_context", lambda: None)
    monkeypatch.setattr(enriched_data, "crypto_context", lambda: None)

    def _boom(_ticker):
        raise RuntimeError("enrich failed")

    monkeypatch.setattr(enriched_data, "_enrich_ticker_fast", _boom)
    out = enrich(["NVDA"])
    assert out["per_ticker"]["NVDA"] == {}
    assert any(d.get("ticker") == "NVDA" for d in out["degradation"])


def test_format_enrichment_empty_returns_blank():
    assert format_enrichment_for_prompt({}) == ""
    assert format_enrichment_for_prompt({"per_ticker": {}, "macro": None, "crypto": None}) == ""


def test_format_enrichment_renders_macro_crypto_and_ticker_sections():
    text = format_enrichment_for_prompt(
        {
            "sources_active": ["finnhub", "fred"],
            "degradation": [],
            "macro": {
                "series": {"DGS10": {"label": "10Y Treasury", "value": 4.25, "units": "%"}},
                "rate_regime": "restrictive",
                "yield_curve_signal": "inverted",
                "inflation_signal": "cooling",
                "vix_regime": "calm",
            },
            "economic_calendar": {"next_nfp_estimate": "2026-02-06", "fomc_note": "FOMC in 2 weeks"},
            "crypto": {"btc_price": 61234, "btc_change_7d": 2.5, "risk_signal": "RISK-ON", "risk_note": "momentum"},
            "per_ticker": {
                "NVDA": {
                    "analyst_consensus": {
                        "consensus_label": "Strong Buy",
                        "buy": 30,
                        "hold": 5,
                        "sell": 1,
                        "total_analysts": 36,
                        "period": "2026-01",
                    },
                    "upcoming_earnings": {"date": "2026-02-20", "hour": "amc", "eps_estimate": "5.10"},
                    "earnings_history": [{"surprise_pct": 8.0, "period": "Q4"}, {"surprise_pct": 5.0}, {"surprise_pct": 3.0}],
                    "insider_activity": {"signal": "BUYING", "buys": 4, "sells": 1, "net_shares": 12000},
                    "polygon_snapshot": {"vwap_pct": 1.2, "vwap_signal": "above", "after_hrs_change_pct": 0.5},
                    "finnhub_sentiment": {"bullish_pct": 0.7, "bearish_pct": 0.3},
                },
                "EMPTY": {},  # skipped — no content
            },
        }
    )
    assert "### Macro Environment (FRED)" in text
    assert "10Y Treasury: 4.25%" in text
    assert "### Macro Event Calendar" in text
    assert "Next NFP estimate: 2026-02-06" in text
    assert "### Crypto Context" in text
    assert "Risk signal: **RISK-ON**" in text
    assert "#### NVDA" in text
    assert "Strong Buy" in text
    assert "Next earnings: 2026-02-20 (AMC)" in text
    assert "Beat estimates 3 quarters in a row" in text
    assert "BUYING" in text
    assert "#### EMPTY" not in text  # empty ticker omitted


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
    text = format_enrichment_for_prompt(
        {
            "per_ticker": {"MSFT": {}},
            "macro": None,
            "crypto": None,
            "sources_active": [],
            "degradation": [{"source": "finnhub", "operation": "recommendation_trends", "ticker": "MSFT", "error": "down"}],
        }
    )

    assert "Data Coverage / Degradation" in text
    assert "MSFT: finnhub.recommendation_trends unavailable" in text
