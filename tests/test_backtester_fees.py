"""Backtester now subtracts fees and slippage from realized returns."""
from datetime import datetime
from unittest.mock import patch

from src.backtester import evaluate_recommendations, summarize


def _rec(ticker="MSFT", action="BUY", conviction=8, expected_pct=4.0,
         time_horizon="1-2 weeks", session_date="2026-04-01"):
    return {
        "ticker": ticker,
        "action": action,
        "conviction": conviction,
        "net_expected_pct": expected_pct,
        "time_horizon": time_horizon,
        "session_date": session_date,
        "session_file": f"{session_date.replace('-','')}_0930_morning.json",
    }


@patch("src.backtester.price_at")
def test_actual_pct_is_net_of_fees(mock_price):
    """A 1% gross gain on a midcap can be wiped after fees + slippage."""
    mock_price.side_effect = [100.0, 101.0]  # +1% gross
    as_of = datetime(2026, 5, 1)  # 30 days later (passes 1-2w horizon)

    results = evaluate_recommendations(
        [_rec(ticker="PLTR")],  # midcap → higher fees
        as_of=as_of,
    )
    assert len(results) == 1
    row = results[0]
    # Gross +1.0%, fees should drag it to a smaller (or negative) net
    assert row["gross_pct"] == 1.0
    assert row["actual_pct"] < row["gross_pct"]
    assert row["fee_drag_pct"] > 0


@patch("src.backtester.price_at")
def test_summarize_returns_sizing_multipliers(mock_price):
    """Summary includes a sizing multiplier when bucket has ≥3 samples."""
    mock_price.side_effect = [100.0, 110.0] * 5  # 5 trades, +10% gross each
    as_of = datetime(2026, 5, 1)

    recs = [
        _rec(ticker="MSFT", session_date="2026-04-01", conviction=8),
        _rec(ticker="AAPL", session_date="2026-04-02", conviction=8),
        _rec(ticker="NVDA", session_date="2026-04-03", conviction=8),
        _rec(ticker="GOOG", session_date="2026-04-04", conviction=7),  # singleton
    ]
    results = evaluate_recommendations(recs, as_of=as_of)
    summary = summarize(results)
    multipliers = summary.get("sizing_multipliers_by_conviction") or {}
    assert 8 in multipliers  # 3 samples
    assert 7 not in multipliers  # only 1 sample → skipped
    assert 0.4 <= multipliers[8] <= 1.4  # clamped


@patch("src.backtester.price_at")
def test_sell_action_inverts_sign_for_hit_rate(mock_price):
    mock_price.side_effect = [100.0, 90.0]  # price drops 10%
    as_of = datetime(2026, 5, 1)
    recs = [_rec(ticker="MSFT", action="SELL", expected_pct=-5.0)]
    results = evaluate_recommendations(recs, as_of=as_of)
    assert len(results) == 1
    # SELL on a -10% move = a 10% gross "win", net positive after fees
    assert results[0]["gross_pct"] == 10.0
    assert results[0]["actual_pct"] > 0
    assert results[0]["hit"] is True
