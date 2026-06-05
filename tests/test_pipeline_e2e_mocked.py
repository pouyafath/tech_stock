import json

from src import main
from src.portfolio_loader import parse_holdings_csv
from src.view_models import build_buy_signals_view

HEADER = [
    "Symbol",
    "Exchange",
    "MIC",
    "Name",
    "Security Type",
    "Quantity",
    "Market Price",
    "Market Price Currency",
    "Book Value (CAD)",
    "Book Value Currency (CAD)",
    "Book Value (Market)",
    "Book Value Currency (Market)",
    "Market Value",
    "Market Value Currency",
    "Market Unrealized Returns",
    "Market Unrealized Returns Currency",
]


def _write_holdings(path):
    row = {
        "Symbol": "AAPL",
        "Exchange": "NASDAQ",
        "MIC": "XNAS",
        "Name": "Apple Inc",
        "Security Type": "EQUITY",
        "Quantity": 1,
        "Market Price": 200,
        "Market Price Currency": "USD",
        "Book Value (CAD)": 240,
        "Book Value (Market)": 180,
        "Market Value": 200,
        "Market Value Currency": "USD",
        "Market Unrealized Returns": 20,
        "Market Unrealized Returns Currency": "USD",
    }
    path.write_text(
        "\n".join(
            [
                ",".join(HEADER),
                ",".join(str(row.get(col, "")) for col in HEADER),
                '"As of 2026-05-18 16:00"',
            ]
        )
    )


def test_mocked_report_pipeline_creates_artifacts_and_view_model(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    reports_dir = tmp_path / "reports"
    log_dir = data_dir / "recommendations_log"
    config_dir.mkdir()
    data_dir.mkdir()
    reports_dir.mkdir()
    log_dir.mkdir()
    (config_dir / "settings.json").write_text(
        json.dumps(
            {
                "budget_usd": 500,
                "budget_cad": 0,
                "enable_decision_journal": False,
                "cad_per_usd_assumption": 1.37,
                "risk_benchmark_tickers": ["SPY", "QQQ", "SMH"],
            }
        )
    )
    (config_dir / "watchlist.json").write_text('{"entries": []}')
    holdings = tmp_path / "holdings-report-2026-05-18.csv"
    _write_holdings(holdings)

    parsed = parse_holdings_csv(holdings)
    assert parsed["holdings"][0]["ticker"] == "AAPL"

    md = {
        "AAPL": {
            "ticker": "AAPL",
            "current_price": 205,
            "previous_close": 200,
            "currency": "USD",
            "quote_timestamp_utc": "2026-05-18T19:30:00Z",
            "quote_source": "mock",
            "price_basis": "regular_market",
        },
        "SPY": {"current_price": 600, "currency": "USD"},
        "QQQ": {"current_price": 500, "currency": "USD"},
        "SMH": {"current_price": 300, "currency": "USD"},
    }
    recommendation = {
        "session_summary": "mocked report",
        "portfolio_health": {"total_value_usd_equivalent": 200, "overall_pnl_pct": 10, "concentration_risk": "low"},
        "recommendations": [
            {
                "ticker": "AAPL",
                "action": "BUY",
                "invest_amount_usd": 100,
                "conviction": 8,
                "thesis": "If quote stays fresh, buy; if catalyst fails, wait.",
                "technical_basis": "mock",
                "net_expected_pct": 5,
                "fee_hurdle_pct": 0.5,
                "time_horizon": "1-3 months",
                "risk_controls": {"entry_zone_low_pct": -2, "entry_zone_high_pct": 1, "stop_loss_pct": -6, "take_profit_pct": 12},
                "catalyst_verified": True,
                "catalyst_source": "Mock source",
                "manual_review_required": False,
                "hold_tier": None,
            }
        ],
        "warnings": [],
        "quality_warnings": [],
    }

    monkeypatch.setattr(main, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(main, "DATA_DIR", data_dir)
    monkeypatch.setattr(main, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(main, "RECS_LOG_DIR", log_dir)
    monkeypatch.setattr(main, "THESIS_LOG_PATH", data_dir / "thesis_log.json")
    monkeypatch.setattr(main, "DECISION_JOURNAL_PATH", data_dir / "decision_journal.json")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        main, "get_market_data", lambda tickers: {ticker: md.get(ticker, {"current_price": 1, "currency": "USD"}) for ticker in tickers}
    )
    monkeypatch.setattr(main, "get_news_for_tickers", lambda tickers: {"AAPL": [{"title": "Mock catalyst", "published_at": "2026-05-18"}]})
    monkeypatch.setattr(main, "enrich", lambda tickers: {"sources_active": ["mock"], "degradation": [], "per_ticker": {}})
    monkeypatch.setattr(main, "build_fee_snapshot", lambda tickers: {})
    monkeypatch.setattr(main, "compute_sector_exposure", lambda holdings, market_data: {})
    monkeypatch.setattr(main, "aggregate_company_exposure", lambda holdings, cad_per_usd: ({}, {}))
    monkeypatch.setattr(main, "compute_risk_dashboard", lambda holdings, market_data, settings: {})
    monkeypatch.setattr(main, "build_hedge_suggestions", lambda risk, exposure, settings: [])
    monkeypatch.setattr(main, "holding_days_by_ticker", lambda activities, holdings: {})
    monkeypatch.setattr(main, "detect_drawdown", lambda holdings, market_data, settings: {})
    monkeypatch.setattr(main, "get_context_moves", lambda symbols: {})
    monkeypatch.setattr(main, "watchlist_price_alerts", lambda watchlist, market_data: [])
    monkeypatch.setattr(main, "get_previous_session", lambda log_dir, current_session_type: None)
    monkeypatch.setattr(main, "run_backtest", lambda log_dir: {"n_samples": 0})
    monkeypatch.setattr(main, "call_claude", lambda **kwargs: (recommendation, {"cost_usd": 0.01, "total_tokens": 100}))
    monkeypatch.setattr(main, "apply_trade_sizes", lambda rec, portfolio, market_data: rec)
    monkeypatch.setattr(main, "compute_drift", lambda rec, previous_session, conviction_delta_threshold=2: [])
    monkeypatch.setattr(main, "generate_markdown", lambda *args, **kwargs: "# Mock Report\n")
    monkeypatch.setattr("src.fred_client.live_cad_per_usd", lambda: None)
    monkeypatch.setattr("src.thesis_tracker.quarterly_reviews_due", lambda path: [])
    monkeypatch.setattr("src.thesis_tracker.force_exit_candidates", lambda path: [])
    monkeypatch.setattr("src.thesis_tracker.record_new_entries", lambda *args, **kwargs: [])
    monkeypatch.setattr("src.thesis_tracker.update_reviews_from_recommendation", lambda *args, **kwargs: None)

    artifacts = main.run("morning", holdings_csv=holdings, open_report=False)

    assert artifacts["report_path"].exists()
    assert artifacts["csv_path"].exists()
    assert artifacts["log_path"].exists()
    saved = json.loads(artifacts["log_path"].read_text())
    view = build_buy_signals_view({"candidates": saved["recommendations"]})
    assert view["overview_rows"][0]["ticker"] == "AAPL"
