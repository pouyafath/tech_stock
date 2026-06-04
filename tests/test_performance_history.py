"""Coverage for src.performance_history (v1.17 Performance dashboard engine)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.performance_history import (
    _linear_regression,
    _max_drawdown_pct,
    _pct_changes,
    load_portfolio_snapshots,
    portfolio_performance_summary,
)


# ── Pure math helpers ─────────────────────────────────────────────────────


def test_pct_changes_basic():
    assert _pct_changes([100, 110, 99]) == pytest.approx([10.0, -10.0])


def test_pct_changes_handles_zero_or_negative_prev():
    assert _pct_changes([0, 100]) == [0.0]
    assert _pct_changes([100]) == []


def test_max_drawdown_zero_on_monotonic_gainer():
    assert _max_drawdown_pct([100, 110, 120, 130]) == 0.0


def test_max_drawdown_captures_peak_to_trough():
    # peak 200, trough 150 → -25%
    series = [100, 150, 200, 175, 150, 165]
    assert _max_drawdown_pct(series) == pytest.approx(-25.0, abs=0.01)


def test_linear_regression_recovers_slope_and_intercept():
    x = [0, 1, 2, 3, 4]
    y = [1, 3, 5, 7, 9]  # y = 2x + 1
    slope, intercept = _linear_regression(x, y)
    assert slope == pytest.approx(2.0, abs=1e-6)
    assert intercept == pytest.approx(1.0, abs=1e-6)


def test_linear_regression_handles_degenerate_input():
    assert _linear_regression([], []) == (0.0, 0.0)
    assert _linear_regression([1], [2]) == (0.0, 0.0)
    # All x identical → can't infer slope
    assert _linear_regression([5, 5, 5], [1, 2, 3]) == (0.0, 2.0)


# ── load_portfolio_snapshots ─────────────────────────────────────────────


def _write_log(dir_: Path, filename: str, total_value: float | None, sectors: dict | None = None) -> None:
    payload = {
        "portfolio_health": {
            "total_value_usd_equivalent": total_value,
            "risk_dashboard": {"total_value_usd": total_value} if total_value is not None else {},
        },
    }
    if sectors:
        payload["portfolio_snapshot"] = {
            "holdings": [{"ticker": f"T{i}", "sector": sector, "market_value": value} for i, (sector, value) in enumerate(sectors.items())]
        }
    (dir_ / filename).write_text(json.dumps(payload))


def test_load_portfolio_snapshots_skips_unparseable_filenames(tmp_path):
    _write_log(tmp_path, "20260501_0930_morning.json", 10000.0)
    (tmp_path / "garbage.json").write_text("not a log")
    snaps = load_portfolio_snapshots(tmp_path)
    assert len(snaps) == 1
    assert snaps[0]["session_file"] == "20260501_0930_morning.json"


def test_load_portfolio_snapshots_skips_zero_or_missing_value(tmp_path):
    _write_log(tmp_path, "20260501_0930_morning.json", 0)
    _write_log(tmp_path, "20260502_0930_morning.json", None)
    _write_log(tmp_path, "20260503_0930_morning.json", 10000.0)
    snaps = load_portfolio_snapshots(tmp_path)
    assert len(snaps) == 1
    assert snaps[0]["total_value_usd"] == 10000.0


def test_load_portfolio_snapshots_orders_oldest_first(tmp_path):
    _write_log(tmp_path, "20260503_0930_morning.json", 10300.0)
    _write_log(tmp_path, "20260501_0930_morning.json", 10000.0)
    _write_log(tmp_path, "20260502_0930_morning.json", 10100.0)
    snaps = load_portfolio_snapshots(tmp_path)
    assert [s["session_file"] for s in snaps] == [
        "20260501_0930_morning.json",
        "20260502_0930_morning.json",
        "20260503_0930_morning.json",
    ]


def test_load_portfolio_snapshots_collects_sector_buckets(tmp_path):
    _write_log(tmp_path, "20260501_0930_morning.json", 10000.0, {"Tech": 6000.0, "Energy": 4000.0})
    snaps = load_portfolio_snapshots(tmp_path)
    assert snaps[0]["holdings_by_sector"] == {"Tech": 6000.0, "Energy": 4000.0}


# ── portfolio_performance_summary ────────────────────────────────────────


def test_portfolio_performance_summary_returns_not_ready_when_no_data(tmp_path):
    summary = portfolio_performance_summary(log_dir=tmp_path, fetch_spy=False)
    assert summary["ready"] is False
    assert summary["n_snapshots"] == 0
    assert "reason" in summary


def test_portfolio_performance_summary_needs_at_least_two_snapshots(tmp_path):
    _write_log(tmp_path, "20260501_0930_morning.json", 10000.0)
    summary = portfolio_performance_summary(log_dir=tmp_path, fetch_spy=False)
    assert summary["ready"] is False
    assert summary["n_snapshots"] == 1


def test_portfolio_performance_summary_computes_cumulative_return(tmp_path):
    _write_log(tmp_path, "20260101_0930_morning.json", 10000.0)
    _write_log(tmp_path, "20260201_0930_morning.json", 10500.0)
    _write_log(tmp_path, "20260301_0930_morning.json", 11000.0)
    summary = portfolio_performance_summary(log_dir=tmp_path, fetch_spy=False)
    assert summary["ready"] is True
    assert summary["n_snapshots"] == 3
    assert summary["cumulative_return_pct"] == pytest.approx(10.0, abs=0.01)
    # Two session-returns: +5%, +4.76%
    assert len(summary["session_returns_pct"]) == 2


def test_portfolio_performance_summary_downside_risk_metrics(tmp_path):
    # A series with both up and down sessions so Sortino / VaR / CVaR are defined.
    _write_log(tmp_path, "20260101_0930_morning.json", 10000.0)
    _write_log(tmp_path, "20260102_0930_morning.json", 10400.0)  # +4%
    _write_log(tmp_path, "20260103_0930_morning.json", 9900.0)  # -4.8%
    _write_log(tmp_path, "20260104_0930_morning.json", 10200.0)  # +3%
    _write_log(tmp_path, "20260105_0930_morning.json", 9700.0)  # -4.9%
    summary = portfolio_performance_summary(log_dir=tmp_path, fetch_spy=False)
    assert summary["ready"] is True
    # All four new fields are present and numeric (not the "—" placeholder).
    for key in ("sortino", "calmar", "var_95_pct", "cvar_95_pct"):
        assert key in summary
    # VaR 95% is a left-tail figure → should be negative given the down sessions.
    assert summary["var_95_pct"] is not None
    assert summary["var_95_pct"] <= 0
    # CVaR is the mean of the tail at/below VaR → no worse than VaR.
    assert summary["cvar_95_pct"] is not None
    assert summary["cvar_95_pct"] <= summary["var_95_pct"] + 1e-9


def test_portfolio_performance_summary_skips_spy_when_disabled(tmp_path):
    _write_log(tmp_path, "20260101_0930_morning.json", 10000.0)
    _write_log(tmp_path, "20260201_0930_morning.json", 10500.0)
    summary = portfolio_performance_summary(log_dir=tmp_path, fetch_spy=False)
    assert summary["spy"]["available"] is False
    assert summary["spy"]["beta"] is None


def test_portfolio_performance_summary_lookback_window_filters_old(tmp_path):
    # One ancient snapshot + two recent — lookback should keep only recents.
    _write_log(tmp_path, "20240101_0930_morning.json", 5000.0)
    # Build filenames programmatically so they're within the lookback window.
    today = datetime.now()
    recent_a = (today - timedelta(days=10)).strftime("%Y%m%d_0930") + "_morning.json"
    recent_b = (today - timedelta(days=1)).strftime("%Y%m%d_0930") + "_morning.json"
    _write_log(tmp_path, recent_a, 10000.0)
    _write_log(tmp_path, recent_b, 11000.0)
    summary = portfolio_performance_summary(log_dir=tmp_path, lookback_days=30, fetch_spy=False)
    assert summary["ready"] is True
    assert summary["n_snapshots"] == 2  # ancient one excluded


def test_portfolio_performance_summary_sector_waterfall(tmp_path):
    _write_log(tmp_path, "20260101_0930_morning.json", 10000.0, {"Tech": 6000.0, "Energy": 4000.0})
    _write_log(tmp_path, "20260201_0930_morning.json", 11000.0, {"Tech": 8000.0, "Energy": 3000.0})
    summary = portfolio_performance_summary(log_dir=tmp_path, fetch_spy=False)
    waterfall = summary["sector_waterfall"]
    tech = next(row for row in waterfall if row["sector"] == "Tech")
    energy = next(row for row in waterfall if row["sector"] == "Energy")
    assert tech["delta_usd"] == 2000.0
    assert energy["delta_usd"] == -1000.0


def test_portfolio_performance_summary_return_distribution_bucketing(tmp_path):
    # Cumulative ~0 with strong wobble — make sure buckets land in the histogram.
    _write_log(tmp_path, "20260101_0930_morning.json", 10000.0)
    _write_log(tmp_path, "20260102_0930_morning.json", 10500.0)  # +5%
    _write_log(tmp_path, "20260103_0930_morning.json", 10000.0)  # -4.76%
    _write_log(tmp_path, "20260104_0930_morning.json", 10100.0)  # +1%
    summary = portfolio_performance_summary(log_dir=tmp_path, fetch_spy=False)
    dist = summary["return_distribution"]
    assert sum(dist.values()) == 3  # three session-returns total
    # +5% bucket caps at ≥+5%
    assert any(label.startswith("≥") or label.startswith("+4") or label.startswith("+5") for label in dist)
