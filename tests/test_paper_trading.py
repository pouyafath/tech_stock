"""Tests for the --paper trading simulator."""

from datetime import date

from src.paper_trading import (
    DEFAULT_STARTING_CASH_USD,
    apply_session,
    format_for_report,
    initialize,
    mark_to_market,
    performance_summary,
)


def test_initialize_defaults_to_25k(tmp_path):
    state = initialize(tmp_path / "p.json")
    assert state["starting_cash_usd"] == DEFAULT_STARTING_CASH_USD
    assert state["current_cash_usd"] == DEFAULT_STARTING_CASH_USD
    assert state["positions"] == {}


def test_buy_deducts_cash_credits_shares(tmp_path):
    p = tmp_path / "p.json"
    initialize(p, starting_cash_usd=10_000)
    rec = {
        "recommendations": [
            {"ticker": "NVDA", "action": "BUY", "invest_amount_usd": 1000},
        ]
    }
    md = {"NVDA": {"current_price": 500.0}}
    state = apply_session(p, rec, md, session_file="s.json", today=date(2026, 5, 6))
    assert state["current_cash_usd"] < 10_000
    assert "NVDA" in state["positions"]
    # ~2 shares minus a small fee
    assert 1.9 < state["positions"]["NVDA"]["shares"] < 2.05
    assert len(state["trade_log"]) == 1


def test_buy_skips_when_no_amount(tmp_path):
    p = tmp_path / "p.json"
    initialize(p)
    rec = {"recommendations": [{"ticker": "NVDA", "action": "BUY"}]}
    md = {"NVDA": {"current_price": 100}}
    state = apply_session(p, rec, md, session_file="s.json")
    assert state["positions"] == {}
    assert state["trade_log"] == []  # nothing recorded


def test_buy_skips_when_no_market_price(tmp_path):
    p = tmp_path / "p.json"
    initialize(p)
    rec = {"recommendations": [{"ticker": "NVDA", "action": "BUY", "invest_amount_usd": 500}]}
    state = apply_session(p, rec, {}, session_file="s.json")
    assert state["positions"] == {}


def test_sell_closes_position(tmp_path):
    p = tmp_path / "p.json"
    initialize(p, starting_cash_usd=10_000)
    md_buy = {"NVDA": {"current_price": 500.0}}
    apply_session(
        p,
        {"recommendations": [{"ticker": "NVDA", "action": "BUY", "invest_amount_usd": 1000}]},
        md_buy,
        session_file="b.json",
        today=date(2026, 5, 6),
    )
    md_sell = {"NVDA": {"current_price": 600.0}}  # +20%
    state = apply_session(
        p, {"recommendations": [{"ticker": "NVDA", "action": "SELL"}]}, md_sell, session_file="s.json", today=date(2026, 6, 6)
    )
    assert "NVDA" not in state["positions"]
    # Cash recovered + profit (less fees)
    assert state["current_cash_usd"] > 10_000


def test_trim_partial_exit(tmp_path):
    p = tmp_path / "p.json"
    initialize(p, starting_cash_usd=10_000)
    md = {"NVDA": {"current_price": 500}}
    apply_session(p, {"recommendations": [{"ticker": "NVDA", "action": "BUY", "invest_amount_usd": 5000}]}, md, session_file="b.json")
    state_before = apply_session(
        p, {"recommendations": [{"ticker": "NVDA", "action": "TRIM"}]}, md, session_file="t.json", trim_fraction=0.30
    )
    # After 30% trim, ~70% of original shares remain
    remaining = state_before["positions"]["NVDA"]["shares"]
    assert remaining > 0
    # The trade log shows two trades: BUY + TRIM
    actions = [t["action"] for t in state_before["trade_log"]]
    assert actions == ["BUY", "TRIM"]


def test_mark_to_market_includes_cash_and_positions(tmp_path):
    p = tmp_path / "p.json"
    state = initialize(p, starting_cash_usd=5000)
    state["positions"]["NVDA"] = {"shares": 2.0, "avg_cost": 500, "first_entry_date": "2026-01-01"}
    state["current_cash_usd"] = 4000
    md = {"NVDA": {"current_price": 600}}
    value = mark_to_market(state, md)
    # cash + 2 shares × $600 = 4000 + 1200 = 5200
    assert abs(value - 5200) < 0.01


def test_performance_summary_returns_metrics(tmp_path):
    p = tmp_path / "p.json"
    initialize(p, starting_cash_usd=10_000)
    md = {"NVDA": {"current_price": 500}}
    apply_session(p, {"recommendations": [{"ticker": "NVDA", "action": "BUY", "invest_amount_usd": 1000}]}, md, session_file="x.json")
    md["NVDA"]["current_price"] = 600  # +20% on $1000 invested ≈ $200 gain (less fees)
    import json

    state = json.loads(p.read_text())
    summary = performance_summary(state, md)
    assert summary["starting_value_usd"] == 10_000
    assert summary["n_trades"] == 1
    assert summary["n_open_positions"] == 1


def test_format_for_report_renders_when_trades_present():
    summary = {
        "starting_value_usd": 10000,
        "current_value_usd": 11000,
        "current_cash_usd": 5000,
        "total_return_pct": 10.0,
        "n_trades": 5,
        "n_open_positions": 2,
    }
    out = "\n".join(format_for_report(summary))
    assert "Paper Portfolio" in out
    assert "10,000" in out  # starting capital
    assert "+10.00%" in out


def test_format_for_report_empty_when_no_trades():
    summary = {"n_trades": 0}
    assert format_for_report(summary) == []
    assert format_for_report({}) == []
