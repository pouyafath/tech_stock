"""Coverage for v1.18 calibration helpers in src.backtester."""

from __future__ import annotations

import pytest

from src.backtester import evaluate_rolling_window, reliability_diagram, summarize


def _row(conviction: int, *, hit: bool = True, actual_pct: float = 1.0, session_date: str = "2026-01-01", ticker: str = "AAA") -> dict:
    return {
        "ticker": ticker,
        "session_date": session_date,
        "action": "BUY",
        "conviction": conviction,
        "actual_pct": actual_pct,
        "hit": hit,
    }


# ── reliability_diagram ────────────────────────────────────────────────────


def test_reliability_diagram_basic_overconfidence():
    # Conviction 8 (stated 80% win) but only 50% realized → error_pp = -30
    rows = [_row(8, hit=True)] * 5 + [_row(8, hit=False)] * 5
    out = reliability_diagram(rows)
    assert 8 in out
    bucket = out[8]
    assert bucket["n"] == 10
    assert bucket["stated_pct"] == 80.0
    assert bucket["realized_pct"] == 50.0
    assert bucket["error_pp"] == -30.0
    assert bucket["overconfident"] is True


def test_reliability_diagram_well_calibrated_band():
    # Conviction 7 (stated 70%) with realized 70% → error_pp = 0, not overconfident
    rows = [_row(7, hit=True)] * 7 + [_row(7, hit=False)] * 3
    out = reliability_diagram(rows)
    bucket = out[7]
    assert bucket["realized_pct"] == 70.0
    assert bucket["error_pp"] == 0.0
    assert bucket["overconfident"] is False


def test_reliability_diagram_under_confident_band():
    # Conviction 6 (stated 60%) with realized 80% → error_pp = +20, NOT overconfident
    rows = [_row(6, hit=True)] * 8 + [_row(6, hit=False)] * 2
    out = reliability_diagram(rows)
    bucket = out[6]
    assert bucket["realized_pct"] == 80.0
    assert bucket["error_pp"] == 20.0
    assert bucket["overconfident"] is False


def test_reliability_diagram_skips_thin_buckets():
    rows = [_row(8, hit=True)] * 2  # only 2 samples in bucket
    out = reliability_diagram(rows)
    assert out == {}


def test_reliability_diagram_returns_empty_on_no_rows():
    assert reliability_diagram([]) == {}


def test_reliability_diagram_includes_avg_actual_pct():
    rows = [_row(9, hit=True, actual_pct=3.0)] * 4 + [_row(9, hit=False, actual_pct=-1.0)] * 2
    out = reliability_diagram(rows)
    bucket = out[9]
    # mean = (3*4 + -1*2) / 6 = 10/6 ≈ 1.67
    assert bucket["avg_actual_pct"] == pytest.approx(1.67, abs=0.01)


# ── evaluate_rolling_window ────────────────────────────────────────────────


def _series(n: int, *, hit_pattern: list[bool] | None = None, conviction: int = 8) -> list[dict]:
    pattern = hit_pattern if hit_pattern is not None else [True] * n
    out = []
    for i in range(n):
        out.append(
            _row(
                conviction,
                hit=pattern[i % len(pattern)],
                actual_pct=1.0 if pattern[i % len(pattern)] else -1.0,
                session_date=f"2026-01-{i + 1:02d}",
                ticker=f"T{i % 5}",
            )
        )
    return out


def test_rolling_window_returns_empty_when_too_few_samples():
    rows = _series(5)
    assert evaluate_rolling_window(rows, window_size=10) == []


def test_rolling_window_produces_step_indexed_windows():
    rows = _series(20)
    windows = evaluate_rolling_window(rows, window_size=5, step=5)
    # 20 / 5 = 4 windows starting at 0, 5, 10, 15
    assert len(windows) == 4
    assert windows[0]["window_start"] < windows[1]["window_start"]


def test_rolling_window_carries_required_fields():
    rows = _series(10)
    windows = evaluate_rolling_window(rows, window_size=5, step=5)
    for window in windows:
        for key in (
            "window_start",
            "window_end",
            "n",
            "hit_rate",
            "avg_return_pct",
            "sharpe",
            "max_drawdown_pct",
            "stdev_pct",
            "sizing_multiplier_avg",
        ):
            assert key in window, f"missing key in rolling window: {key}"


def test_rolling_window_detects_decaying_hit_rate():
    """Early windows should beat later windows when wins move to the front."""
    pattern_strong_then_weak = [True] * 10 + [False] * 10
    rows = [
        _row(
            8,
            hit=pattern_strong_then_weak[i],
            actual_pct=1.0 if pattern_strong_then_weak[i] else -1.0,
            session_date=f"2026-01-{i + 1:02d}",
            ticker=f"T{i}",
        )
        for i in range(20)
    ]
    windows = evaluate_rolling_window(rows, window_size=5, step=5)
    # First window: all wins → 100%
    # Last window: all losses → 0%
    assert windows[0]["hit_rate"] == 1.0
    assert windows[-1]["hit_rate"] == 0.0


def test_rolling_window_handles_zero_step_or_window():
    """Invalid window/step values shouldn't crash — just return []."""
    rows = _series(10)
    assert evaluate_rolling_window(rows, window_size=0) == []
    assert evaluate_rolling_window(rows, window_size=5, step=0) == []


# ── summarize() integration ────────────────────────────────────────────────


def test_summarize_includes_reliability_and_walk_forward_keys():
    rows = _series(80)
    out = summarize(rows)
    assert "reliability" in out
    assert "walk_forward" in out
    # 80 samples with default window=60, step=10 → 3 windows
    assert len(out["walk_forward"]) >= 1


def test_summarize_empty_results_returns_empty_calibration_blocks():
    out = summarize([])
    assert out["reliability"] == {}
    assert out["walk_forward"] == []
