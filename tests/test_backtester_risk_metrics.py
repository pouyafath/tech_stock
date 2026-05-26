"""Coverage for v1.16 risk metrics in backtester._avg_and_hit_rate and the
Sharpe-dampened sizing multiplier.
"""

from __future__ import annotations

import pytest

from src.backtester import _avg_and_hit_rate, summarize


def _row(actual_pct: float, *, hit: bool | None = None) -> dict:
    return {
        "actual_pct": actual_pct,
        "hit": actual_pct > 0 if hit is None else hit,
        "action": "BUY",
        "conviction": 8,
        "ticker": "AAA",
    }


# ── _avg_and_hit_rate output shape ────────────────────────────────────────


def test_avg_and_hit_rate_returns_v16_keys():
    out = _avg_and_hit_rate([_row(1.0), _row(-0.5), _row(2.0)])
    for key in ("n", "avg_return_pct", "hit_rate", "stdev_pct", "sharpe", "max_drawdown_pct"):
        assert key in out


def test_empty_rows_returns_zeroed_v16_block():
    out = _avg_and_hit_rate([])
    assert out["n"] == 0
    assert out["sharpe"] == 0.0
    assert out["max_drawdown_pct"] == 0.0
    assert out["stdev_pct"] == 0.0


# ── Stdev / Sharpe / max-DD math ──────────────────────────────────────────


def test_stdev_pct_matches_population_sample_formula():
    # Series with known sample stdev: [1, 2, 3, 4, 5] → mean 3, stdev √2.5
    rows = [_row(x) for x in (1, 2, 3, 4, 5)]
    out = _avg_and_hit_rate(rows)
    assert out["stdev_pct"] == pytest.approx(2.5**0.5, abs=0.01)


def test_sharpe_zero_when_only_one_sample():
    out = _avg_and_hit_rate([_row(2.0)])
    assert out["sharpe"] == 0.0
    assert out["stdev_pct"] == 0.0


def test_sharpe_zero_when_all_returns_identical():
    out = _avg_and_hit_rate([_row(1.0), _row(1.0), _row(1.0)])
    # mean=1, stdev=0 → sharpe forced to 0 (no div-by-zero)
    assert out["sharpe"] == 0.0


def test_sharpe_positive_when_mean_positive_and_variance_present():
    out = _avg_and_hit_rate([_row(2.0), _row(3.0), _row(2.5)])
    assert out["sharpe"] > 0
    # Same mean but lower variance → higher Sharpe
    tighter = _avg_and_hit_rate([_row(2.4), _row(2.5), _row(2.6)])
    assert tighter["sharpe"] > out["sharpe"]


def test_max_drawdown_pct_zero_for_monotonic_gainer():
    rows = [_row(x) for x in (0.5, 0.5, 0.5, 0.5)]
    out = _avg_and_hit_rate(rows)
    # Only positive contributions → cumulative never drops below peak.
    assert out["max_drawdown_pct"] == 0.0


def test_max_drawdown_pct_captures_peak_to_trough_gap():
    # Cumulative path: 5 → 8 → 3 → 1 → 4
    #   peaks: 5, 8, 8, 8, 8   drawdown min = 1-8 = -7
    rows = [_row(x) for x in (5, 3, -5, -2, 3)]
    out = _avg_and_hit_rate(rows)
    assert out["max_drawdown_pct"] == pytest.approx(-7.0, abs=0.01)


# ── Sizing multiplier (Sharpe-dampened) ──────────────────────────────────


def _summary_for_one_conviction(returns: list[float], conviction: int = 8) -> dict:
    """Run summarize() on a synthetic single-conviction bucket."""
    results = [
        {
            "actual_pct": r,
            "hit": r > 0,
            "action": "BUY",
            "conviction": conviction,
            "ticker": "AAA",
            "session_date": f"2026-01-{i + 1:02d}",
        }
        for i, r in enumerate(returns)
    ]
    return summarize(results)


def test_sizing_multipliers_are_clamped_to_canonical_range():
    # Wildly profitable bucket — should still clamp at 1.4
    high = _summary_for_one_conviction([10.0, 12.0, 11.0, 9.5])
    assert max(high["sizing_multipliers_by_conviction"].values()) <= 1.4 + 1e-6
    # All-losing bucket — should clamp at 0.4 floor
    low = _summary_for_one_conviction([-5.0, -4.0, -6.0, -4.5])
    assert min(low["sizing_multipliers_by_conviction"].values()) >= 0.4 - 1e-6


def test_sizing_multiplier_only_computed_when_three_or_more_samples():
    one_sample = _summary_for_one_conviction([2.0])
    assert one_sample["sizing_multipliers_by_conviction"] == {}


def test_sharpe_dampener_shrinks_high_variance_buckets():
    """Same expectation, more variance → smaller multiplier."""
    tight = _summary_for_one_conviction([1.0, 1.1, 0.9, 1.05])
    wide = _summary_for_one_conviction([1.0, -5.0, 7.0, 1.0])
    tight_mult = tight["sizing_multipliers_by_conviction"][8]
    wide_mult = wide["sizing_multipliers_by_conviction"][8]
    # Tight bucket has both higher Sharpe AND higher hit-rate, so its
    # multiplier must beat the high-variance bucket.
    assert tight_mult > wide_mult
