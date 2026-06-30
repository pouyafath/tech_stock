from src.report_generator import (
    _render_catalyst_section,
    _render_company_exposure_section,
    _render_concentration_alerts_section,
    _render_cost_footer,
    _render_critical_actions_section,
    _render_data_coverage_section,
    _render_data_quality_section,
    _render_fee_assumptions_section,
    _render_hedge_suggestions_section,
    _render_leveraged_etf_section,
    _render_market_context_section,
    _render_position_sizing_section,
    _render_priority_actions_section,
    _render_quality_warnings_section,
    _render_risk_controls,
    _render_risk_dashboard_section,
    _render_sector_section,
    _render_track_record_section,
    _render_trailing_stops_table,
    _sparkline,
    _table_cell,
    conviction_bar,
    generate_markdown,
    leveraged_etf_warnings,
    tax_loss_candidates,
    watchlist_price_alerts,
)


def test_report_renders_quality_risk_hedge_and_bear_bull_sections():
    recommendation = {
        "session_summary": "Risk is elevated.",
        "portfolio_health": {
            "total_value_usd_equivalent": 10000,
            "overall_pnl_pct": 5,
            "concentration_risk": "high",
            "cash_deployment": "limited",
        },
        "quality_warnings": [
            {
                "severity": "high",
                "code": "stale_or_unstamped_quote",
                "ticker": "MSFT",
                "message": "Quote stale.",
                "action_required": "Verify quote.",
            }
        ],
        "hedge_suggestions": [
            {
                "type": "inverse_etf",
                "instrument": "PSQ",
                "action": "OPTIONAL_SHORT_TERM_HEDGE",
                "max_portfolio_pct": 3,
                "rationale": "Offset tech beta.",
                "risk_note": "Daily reset risk.",
            }
        ],
        "recommendations": [
            {
                "ticker": "MSFT",
                "action": "HOLD",
                "conviction": 6,
                "thesis": "If support holds, keep; if it fails, trim.",
                "risk_or_invalidation": "If support breaks, trim.",
                "technical_basis": "Above SMA200.",
                "liquidity_tier": "megacap",
                "expected_move_pct": 8,
                "fee_hurdle_pct": 0.1,
                "net_expected_pct": 7.9,
                "time_horizon": "1-3 months",
                "price_target_low_pct": -5,
                "price_target_high_pct": 12,
                "risk_controls": {
                    "entry_zone_low_pct": -3,
                    "entry_zone_high_pct": 1,
                    "stop_loss_pct": -8,
                    "take_profit_pct": 12,
                },
                "catalyst_verified": False,
                "catalyst_source": None,
                "manual_review_required": False,
                "hold_tier": "keep",
            }
        ],
        "warnings": [],
    }

    markdown = generate_markdown(
        "afternoon",
        recommendation,
        {"MSFT": {"current_price": 100, "currency": "USD", "error": None, "quote_source": "test"}},
        portfolio={"holdings": []},
        risk_dashboard={
            "total_value_usd": 10000,
            "annualized_volatility_pct": 32.5,
            "max_drawdown_estimate_pct": -18.2,
            "top3_concentration_pct": 70,
            "beta": {"QQQ": 1.2},
            "correlated_pairs": [],
        },
        company_exposure={"MSFT": {"company": "MSFT", "value_usd": 3000, "pct": 30, "tickers": ["MSFT"]}},
        usage={"passes": 2, "total_tokens": 1000, "cost_usd": 0.22},
        decision_scorecard={"journal": {"total": 1, "pending": 1, "recorded": 0}},
    )

    assert "## Report Quality Warnings" in markdown
    assert "## Critical Actions" in markdown
    assert "## Actionability Check" in markdown
    assert "## Can I Act On This?" in markdown
    assert "TRADE READY" in markdown or "REVIEW FIRST" in markdown or "BLOCKED" in markdown
    assert "## Data Confidence" in markdown
    assert "## Source Coverage" in markdown
    assert "## Why These Recommendations?" in markdown
    assert "What Changes My Mind" in markdown
    assert "## Source Provenance" in markdown
    assert "Quotes" in markdown
    assert "Source footnote" in markdown
    assert "## Portfolio Risk Dashboard" in markdown
    assert "## Hedge And Rebalance Suggestions" in markdown
    assert "Bear Case" in markdown
    assert "Bull Case" in markdown
    assert "## Decision Journal" in markdown
    assert "Claude passes: 2" in markdown

    markdown_with_retry = generate_markdown(
        "afternoon",
        recommendation,
        {"MSFT": {"current_price": 100, "currency": "USD", "error": None, "quote_source": "test"}},
        portfolio={"holdings": []},
        usage={"passes": 2, "total_tokens": 1200, "cost_usd": 0.3, "retries": 1},
    )
    assert "JSON retries: 1" in markdown_with_retry


def test_leveraged_etf_warning_uses_activity_lower_bound():
    activities = [
        {"date": "2026-03-30", "type": "Trade", "sub_type": "BUY", "ticker": "META", "quantity": 1},
    ]
    holdings = [{"ticker": "SOXL", "quantity": 1, "unrealized_pnl_pct": 10}]

    warnings = leveraged_etf_warnings(holdings, activities, market_data={}, max_hold_days=14)

    assert len(warnings) == 1
    assert warnings[0]["days_held"] is None
    assert warnings[0]["lower_bound_days"] is not None


def test_track_record_renders_fixed_window_outcomes():
    recommendation = {
        "session_summary": "Track record check.",
        "portfolio_health": {},
        "recommendations": [],
        "warnings": [],
    }

    markdown = generate_markdown(
        "morning",
        recommendation,
        {},
        portfolio={"holdings": []},
        backtest_summary={
            "n_samples": 2,
            "overall": {"n": 2, "avg_return_pct": 1.2, "hit_rate": 0.5},
            "recommendation_outcomes": {
                "scored_windows": 4,
                "scored_recommendations": 2,
                "overall": {
                    "avg_action_return_pct": 2.5,
                    "hit_rate": 0.75,
                    "avg_alpha_vs_benchmark_pct": 1.1,
                },
                "buy_add_success_rate": 0.8,
                "trim_sell_saved_drawdown_count": 1,
                "trim_sell_saved_drawdown_avg_pct": 3.4,
            },
        },
    )

    assert "Fixed-window outcomes" in markdown
    assert "Avg alpha vs benchmark" in markdown
    assert "BUY/ADD success rate" in markdown


def test_leveraged_etf_warning_prefers_full_holding_days_map():
    holdings = [{"ticker": "SOXL", "quantity": 1, "unrealized_pnl_pct": 10}]
    warnings = leveraged_etf_warnings(
        holdings,
        activities=[],
        market_data={},
        max_hold_days=14,
        holding_days_map={"SOXL": {"days_held": 220, "duration_unknown": False}},
    )

    assert warnings[0]["days_held"] == 220
    assert warnings[0]["duration_unknown"] is False


def test_critical_actions_groups_quote_mismatches():
    warnings = [
        {
            "severity": "medium",
            "code": "quote_source_mismatch",
            "ticker": "SOXL",
            "message": "Wealthsimple CSV price $100 differs from yfinance quote $150 by 50.0%.",
            "action_required": "Check whether the holdings CSV or quote feed is stale before trading.",
        },
        {
            "severity": "medium",
            "code": "quote_source_mismatch",
            "ticker": "AMD",
            "message": "Wealthsimple CSV price $100 differs from yfinance quote $130 by 30.0%.",
            "action_required": "Check whether the holdings CSV or quote feed is stale before trading.",
        },
    ]

    section = "\n".join(_render_critical_actions_section(warnings, [], [], []))

    assert "Quote mismatches" in section
    assert "2 holdings differ" in section
    assert "SOXL 50.0%" in section
    assert "Check whether the holdings CSV" not in section


def test_concentration_alerts_rendered_in_markdown():
    """Concentration alert warnings with code CONCENTRATION appear in the report."""
    warnings = [
        {
            "severity": "medium",
            "code": "CONCENTRATION",
            "ticker": "NVDA/AMD",
            "message": "NVDA and AMD are highly correlated (0.92) with combined weight 22.5% — exceeds 15% threshold.",
            "action_required": "Review combined weight of correlated positions and consider reducing exposure.",
        }
    ]
    section = "\n".join(_render_concentration_alerts_section(warnings))
    assert "Concentration Alerts" in section
    assert "NVDA/AMD" in section


# ── Additional coverage tests ─────────────────────────────────────────────────


def test_conviction_bar_all_tiers():
    assert "░" in conviction_bar(None)
    assert conviction_bar(2) == "▓░░░░░░░░░"
    assert conviction_bar(5) == "▓▓▓▓░░░░░░"
    assert conviction_bar(7) == "▓▓▓▓▓▓░░░░"
    assert conviction_bar(9) == "▓▓▓▓▓▓▓▓░░"
    assert conviction_bar(10) == "▓▓▓▓▓▓▓▓▓▓"
    assert "░" in conviction_bar(11)  # out of range fallback


def test_table_cell_escapes_pipes_and_newlines():
    assert _table_cell(None) == ""
    assert _table_cell("a|b") == "a\\|b"
    assert _table_cell("a\nb") == "a b"


def test_sparkline_values():
    assert _sparkline(None) == ""
    assert _sparkline(0.0).startswith("+")
    assert _sparkline(-5.0).startswith("-")


def test_tax_loss_candidates_filters_threshold():
    holdings = [
        {"ticker": "NVDA", "unrealized_pnl_pct": -20.0, "unrealized_pnl": -1000, "market_value": 4000, "market_value_currency": "USD"},
        {"ticker": "MSFT", "unrealized_pnl_pct": -5.0, "unrealized_pnl": -200, "market_value": 4000, "market_value_currency": "USD"},
        {"ticker": "CASH", "unrealized_pnl_pct": -25.0},
    ]
    result = tax_loss_candidates(holdings, threshold_pct=-15)
    assert len(result) == 1
    assert result[0]["ticker"] == "NVDA"


def test_watchlist_price_alerts_entry_and_exit():
    watchlist = {
        "entries": [
            {"ticker": "AMD", "target_entry_price": 150.0, "target_exit_price": 200.0},
        ]
    }
    # price below entry → entry alert
    alerts = watchlist_price_alerts(watchlist, {"AMD": {"current_price": 140.0}})
    assert any(a["kind"] == "entry" for a in alerts)

    # price above exit → exit alert
    alerts = watchlist_price_alerts(watchlist, {"AMD": {"current_price": 210.0}})
    assert any(a["kind"] == "exit" for a in alerts)

    # no market data
    assert watchlist_price_alerts(watchlist, {}) == []
    assert watchlist_price_alerts(None, {"AMD": {"current_price": 140.0}}) == []


def test_render_sector_section():
    sector_exposure = {
        "Technology": {"pct": 60.0, "value_cad": 60000, "tickers": ["NVDA", "AMD"]},
    }
    lines = _render_sector_section(sector_exposure)
    assert any("Technology" in l for l in lines)
    assert any("⚠️" in l for l in lines)  # >40% should flag


def test_render_track_record_section_empty():
    assert _render_track_record_section({}) == []
    assert _render_track_record_section({"n_samples": 0}) == []


def test_render_track_record_section_with_data():
    summary = {
        "n_samples": 5,
        "overall": {"n": 5, "avg_return_pct": 8.5, "hit_rate": 0.8},
        "avg_return_by_action": {"BUY": {"n": 3, "avg_return_pct": 10.0, "hit_rate": 0.9}},
        "avg_return_by_conviction": {8: {"n": 2, "avg_return_pct": 12.0, "hit_rate": 1.0}},
        "avg_return_by_ticker": {"NVDA": {"n": 2, "avg_return_pct": 15.0, "hit_rate": 1.0}},
    }
    lines = _render_track_record_section(summary)
    assert any("Track Record" in l for l in lines)
    assert any("BUY" in l for l in lines)
    assert any("NVDA" in l for l in lines)


def test_render_fee_assumptions_section():
    settings = {
        "fee_model": {
            "commission": 0,
            "fx_spread_pct": 1.5,
            "bid_ask_megacap_pct": 0.05,
            "bid_ask_midcap_pct": 0.1,
            "bid_ask_smallcap_pct": 0.2,
            "regulatory_per_us_trade_usd": 0.01,
        },
        "account_type": "wealthsimple_premium_usd",
        "cad_per_usd_assumption": 1.37,
    }
    lines = _render_fee_assumptions_section(settings)
    assert any("wealthsimple_premium_usd" in l for l in lines)


def test_render_position_sizing_section_empty():
    result = _render_position_sizing_section([], {})
    assert result == []


def test_render_position_sizing_section_with_holdings():
    holdings = [
        {"ticker": "NVDA", "quantity": 10, "market_value": 5000, "market_value_currency": "USD", "book_value_cad": 5000},
    ]
    lines = _render_position_sizing_section(holdings, {"cad_per_usd_assumption": 1.37})
    assert any("NVDA" in l for l in lines)


def test_render_data_quality_section():
    market_data = {
        "NVDA": {
            "current_price": 900,
            "currency": "USD",
            "previous_close": 880.0,
            "change_pct_1d": 2.3,
            "quote_timestamp_utc": "2026-06-07T10:00:00Z",
            "quote_source": "yfinance",
        },
        "FAIL": {"error": "No data"},
    }
    lines = _render_data_quality_section(market_data)
    assert any("NVDA" in l for l in lines)
    assert any("ERROR" in l for l in lines)


def test_render_quality_warnings_section():
    warnings = [
        {"severity": "high", "code": "stale", "ticker": "AMD", "message": "Stale quote", "action_required": "Verify"},
    ]
    lines = _render_quality_warnings_section(warnings)
    assert any("Report Quality Warnings" in l for l in lines)
    assert any("AMD" in l for l in lines)
    assert _render_quality_warnings_section([]) == []


def test_render_risk_dashboard_section():
    rd = {
        "total_value_usd": 50000,
        "annualized_volatility_pct": 22.0,
        "max_drawdown_estimate_pct": -15.0,
        "top3_concentration_pct": 65.0,
        "beta": {"QQQ": 1.1},
        "correlated_pairs": [{"pair": "NVDA/AMD", "correlation": 0.92}],
    }
    lines = _render_risk_dashboard_section(rd)
    assert any("Risk Dashboard" in l for l in lines)
    assert any("QQQ" in l for l in lines)
    assert _render_risk_dashboard_section({}) == []


def test_render_company_exposure_section():
    exposure = {
        "NVDA": {"company": "NVDA", "value_usd": 5000, "pct": 25.0, "tickers": ["NVDA"]},
    }
    lines = _render_company_exposure_section(exposure)
    assert any("NVDA" in l for l in lines)
    assert _render_company_exposure_section({}) == []


def test_render_market_context_section():
    mc = {
        "SPY": {"current_price": 520.0, "change_pct_5d": 1.2, "change_pct_21d": 3.5, "quote_source": "yfinance"},
        "BAD": {"error": "timeout"},
    }
    lines = _render_market_context_section(mc)
    assert any("SPY" in l for l in lines)
    assert any("ERROR" in l for l in lines)
    assert _render_market_context_section({}) == []


def test_render_hedge_suggestions_section():
    suggestions = [
        {
            "type": "inverse_etf",
            "instrument": "PSQ",
            "action": "OPTIONAL_HEDGE",
            "max_portfolio_pct": 3,
            "rationale": "Tech hedge",
            "risk_note": "Daily reset risk.",
        },
    ]
    lines = _render_hedge_suggestions_section(suggestions)
    assert any("PSQ" in l for l in lines)


def test_render_risk_controls():
    recs = [
        {
            "ticker": "NVDA",
            "action": "BUY",
            "risk_controls": {"entry_zone_low_pct": -2, "entry_zone_high_pct": 1, "stop_loss_pct": -8, "take_profit_pct": 20},
        },
        {"ticker": "MSFT", "action": "HOLD", "risk_controls": {}},  # no fields, should be skipped
    ]
    lines = _render_risk_controls(recs)
    assert any("Risk Controls" in l for l in lines)
    assert any("NVDA" in l for l in lines)
    assert _render_risk_controls([]) == []


def test_render_trailing_stops_table():
    holdings = [
        {"ticker": "NVDA", "avg_cost_market": 500.0},
        {"ticker": "AMD", "avg_cost_market": 100.0},  # no price in market_data
    ]
    market_data = {
        "NVDA": {"current_price": 600.0},  # +20% gain → should appear
        "AMD": {},
    }
    lines = _render_trailing_stops_table(holdings, market_data)
    assert any("NVDA" in l for l in lines)


def test_render_cost_footer_with_retries():
    lines = _render_cost_footer({"passes": 2, "total_tokens": 5000, "cost_usd": 0.05, "retries": 1})
    text = "\n".join(lines)
    assert "JSON retries: 1" in text


def test_render_cost_footer_no_retries():
    lines = _render_cost_footer({"passes": 1, "total_tokens": 2000, "cost_usd": 0.02})
    text = "\n".join(lines)
    assert "JSON retries" not in text
    assert _render_cost_footer({}) == []


def test_render_catalyst_section():
    market_data = {
        "NVDA": {"change_pct_1d": 8.0},
        "AMD": {"change_pct_1d": 1.0},  # below threshold, skipped
    }
    news = {"NVDA": [{"title": "NVDA Soars on AI demand", "link": "http://x.com", "publisher": "Reuters", "published_at": "2026-06-07"}]}
    lines = _render_catalyst_section(market_data, news, threshold_pct=5.0)
    assert any("NVDA" in l for l in lines)
    assert _render_catalyst_section({}, {}, 5.0) == []


def test_render_priority_actions_section():
    priority_actions = [
        {"order": 1, "ticker": "NVDA", "action": "BUY", "invest_amount_usd": 2000, "rationale": "Strong momentum"},
        {"order": 2, "ticker": "AMD", "action": "SELL", "shares": 5, "rationale": "Stop hit"},
    ]
    recs = [{"ticker": "NVDA", "risk_or_invalidation": "If breaks 850, exit."}]
    lines = _render_priority_actions_section(priority_actions, recs)
    assert any("NVDA" in l for l in lines)
    assert any("$2,000" in l for l in lines)
    assert any("5 sh" in l for l in lines)
    assert _render_priority_actions_section([]) == []


def test_render_leveraged_etf_section():
    warnings = [
        {
            "ticker": "SOXL",
            "days_held": 30,
            "lower_bound_days": None,
            "duration_unknown": False,
            "earliest_open_buy": "2026-05-01",
            "pnl_pct": 10.0,
            "market_value": 3000,
            "max_hold_days": 14,
            "estimated_decay_pct": 2.5,
        },
    ]
    lines = _render_leveraged_etf_section(warnings)
    assert any("SOXL" in l for l in lines)
    assert _render_leveraged_etf_section([]) == []


def test_render_data_coverage_section():
    enriched = {
        "degradation": [
            {"source": "fred", "ticker": None, "operation": "fetch_series", "error": "timeout"},
        ]
    }
    lines = _render_data_coverage_section(enriched)
    assert any("fred" in l for l in lines)
    assert _render_data_coverage_section({}) == []
