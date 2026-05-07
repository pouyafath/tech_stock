"""Tests covering None-safety in claude_analyst.build_user_message.

The original bug: build_user_message crashed with TypeError when a holding
had `unrealized_pnl_pct` set but `unrealized_pnl` set to None (or vice versa).
The format string was guarded by checking pnl_pct alone, then formatting both.
"""
from src.claude_analyst import build_user_message


def _portfolio(*holdings):
    return {"holdings": list(holdings), "cash_cad": 0, "exported_at": "2026-05-06"}


def _holding(ticker, **overrides):
    base = {
        "ticker": ticker, "quantity": 1, "avg_cost_market": 100, "market_price": 110,
        "market_currency": "USD", "market_value": 110, "market_value_currency": "USD",
        "unrealized_pnl_pct": 10, "unrealized_pnl": 10,
    }
    base.update(overrides)
    return base


def test_pct_set_but_dollars_none_does_not_crash():
    portfolio = _portfolio(_holding("X", unrealized_pnl=None))
    msg = build_user_message("morning", portfolio, {}, {}, {}, {})
    assert "X " in msg
    assert "+10.0%" in msg


def test_dollars_set_but_pct_none_does_not_crash():
    portfolio = _portfolio(_holding("Y", unrealized_pnl_pct=None))
    msg = build_user_message("morning", portfolio, {}, {}, {}, {})
    assert "Y " in msg
    assert "$+10" in msg or "$+10.00" in msg or "+10" in msg


def test_both_pnl_fields_none_renders_no_pnl_string():
    portfolio = _portfolio(_holding("Z", unrealized_pnl_pct=None, unrealized_pnl=None))
    msg = build_user_message("morning", portfolio, {}, {}, {}, {})
    # Find Z's line, ensure it doesn't contain "P&L"
    z_line = next(line for line in msg.split("\n") if line.strip().startswith("Z "))
    assert "P&L" not in z_line


def test_quantity_none_renders_question_mark_not_crash():
    portfolio = _portfolio(_holding("Q", quantity=None))
    msg = build_user_message("morning", portfolio, {}, {}, {}, {})
    assert "Q " in msg


def test_all_market_fields_none_renders_safely():
    portfolio = _portfolio(_holding(
        "W", quantity=None, avg_cost_market=None, market_price=None,
        market_value=None, unrealized_pnl=None, unrealized_pnl_pct=None,
    ))
    # Should not raise
    msg = build_user_message("morning", portfolio, {}, {}, {}, {})
    assert "W " in msg


def test_cad_holdings_with_partial_pnl_does_not_crash():
    portfolio = _portfolio(_holding(
        "TD.TO", market_currency="CAD", market_value_currency="CAD",
        unrealized_pnl=None,
    ))
    msg = build_user_message("morning", portfolio, {}, {}, {}, {})
    assert "TD.TO" in msg
    assert "+10.0%" in msg


def test_string_quantity_does_not_crash():
    """Wealthsimple sometimes exports quantity as a string."""
    portfolio = _portfolio(_holding("S", quantity="3.5"))
    msg = build_user_message("morning", portfolio, {}, {}, {}, {})
    assert "S " in msg
    assert "3.5000" in msg
