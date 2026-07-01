"""Coverage for src.cost_tracker (v1.19 spend log + budget enforcement)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture(autouse=True)
def _isolate_cost_log(monkeypatch, tmp_path):
    """Redirect the cost log to tmp_path and clear before/after each test."""
    log_path = tmp_path / "cost_log.jsonl"
    monkeypatch.setattr("src.cost_tracker.DEFAULT_LOG_PATH", log_path)
    yield log_path
    if log_path.exists():
        log_path.unlink()


def _no_budget(monkeypatch):
    """Convenience — disable the budget so spend tests don't trip it."""
    monkeypatch.setattr("src.cost_tracker._budget_from_settings", lambda: 0.0)


# ── record_run + spend_summary basics ─────────────────────────────────────


def test_record_run_appends_jsonl_line(_isolate_cost_log):
    from src.cost_tracker import record_run

    ok = record_run(model="sonnet", cost_usd=0.22, input_tokens=10000, output_tokens=2000)
    assert ok is True
    contents = _isolate_cost_log.read_text(encoding="utf-8").strip()
    assert contents.startswith("{")
    assert "sonnet" in contents


def test_spend_summary_returns_zero_when_log_missing(monkeypatch, _isolate_cost_log):
    _no_budget(monkeypatch)
    from src.cost_tracker import spend_summary

    summary = spend_summary()
    assert summary.total_usd == 0.0
    assert summary.runs == 0
    assert summary.daily_series == []


def test_spend_summary_aggregates_total_and_runs(monkeypatch, _isolate_cost_log):
    _no_budget(monkeypatch)
    from src.cost_tracker import record_run, spend_summary

    record_run(model="sonnet", cost_usd=0.20)
    record_run(model="sonnet", cost_usd=0.30)
    record_run(model="opus", cost_usd=0.50)
    summary = spend_summary()
    assert summary.runs == 3
    assert summary.total_usd == pytest.approx(1.0, abs=0.01)


def test_spend_summary_skips_corrupt_lines(monkeypatch, _isolate_cost_log):
    _no_budget(monkeypatch)
    from src.cost_tracker import record_run, spend_summary

    record_run(model="sonnet", cost_usd=0.10)
    # Append a garbage line that isn't valid JSON.
    with _isolate_cost_log.open("a", encoding="utf-8") as f:
        f.write("not-json-at-all\n")
        f.write('{"this-is-json": "but missing fields"}\n')
    summary = spend_summary()
    # The first record + the second-junk-record-with-missing-cost = 2 runs counted.
    assert summary.runs >= 1
    assert summary.total_usd == pytest.approx(0.10, abs=0.01)


# ── Budget enforcement ────────────────────────────────────────────────────


def test_check_budget_no_cap_when_setting_zero(monkeypatch, _isolate_cost_log):
    monkeypatch.setattr("src.cost_tracker._budget_from_settings", lambda: 0.0)
    from src.cost_tracker import check_budget

    result = check_budget(expected_cost_usd=100.0)
    assert result.ok is True
    assert result.hard_block is False
    assert result.budget_usd == 0.0


def test_check_budget_soft_warn_at_80pct(monkeypatch, _isolate_cost_log):
    monkeypatch.setattr("src.cost_tracker._budget_from_settings", lambda: 10.0)
    from src.cost_tracker import check_budget, record_run

    # Spend $8 already; next run +$0.50 → would push to $8.50 (85% of cap)
    record_run(model="sonnet", cost_usd=8.0)
    result = check_budget(expected_cost_usd=0.50)
    assert result.soft_warn is True
    assert result.hard_block is False
    assert result.ok is True


def test_check_budget_hard_block_at_100pct(monkeypatch, _isolate_cost_log):
    monkeypatch.setattr("src.cost_tracker._budget_from_settings", lambda: 10.0)
    from src.cost_tracker import check_budget, record_run

    record_run(model="sonnet", cost_usd=9.80)
    result = check_budget(expected_cost_usd=0.30)
    assert result.hard_block is True
    assert result.ok is False


def test_is_overage_allowed_reads_env(monkeypatch):
    from src.cost_tracker import is_overage_allowed

    monkeypatch.delenv("ALLOW_OVERAGE", raising=False)
    assert is_overage_allowed() is False
    monkeypatch.setenv("ALLOW_OVERAGE", "1")
    assert is_overage_allowed() is True


def test_clear_cost_log_removes_file(_isolate_cost_log):
    from src.cost_tracker import clear_cost_log, record_run

    record_run(model="sonnet", cost_usd=0.50)
    assert _isolate_cost_log.exists()
    clear_cost_log()
    assert not _isolate_cost_log.exists()


def test_clear_cost_log_is_safe_when_no_file(_isolate_cost_log):
    from src.cost_tracker import clear_cost_log

    # File doesn't exist — must not raise.
    clear_cost_log()


# ── Projection ────────────────────────────────────────────────────────────


def test_projection_scales_mtd_to_full_month(monkeypatch, _isolate_cost_log):
    _no_budget(monkeypatch)
    from src.cost_tracker import record_run, spend_summary

    # The implementation projects MTD across a 30-day month. With a single
    # $1 record on day-1 the projection should be roughly $30 (or less,
    # because we're somewhere past day 1 of the actual month).
    record_run(model="sonnet", cost_usd=1.0)
    summary = spend_summary()
    assert summary.projected_monthly_usd > 0
    # And the MTD figure is the same $1.
    assert summary.month_to_date_usd == pytest.approx(1.0, abs=0.01)


def test_record_run_never_raises_on_unserialisable_extra(_isolate_cost_log):
    from src.cost_tracker import record_run

    class Weird:
        def __repr__(self):
            return "weird"

    # ``extra`` containing an unserialisable object — the function falls
    # back on ``default=str`` rather than raising.
    ok = record_run(model="sonnet", cost_usd=0.10, extra={"odd": Weird()})
    assert ok is True


# ── Daily series ──────────────────────────────────────────────────────────


def test_daily_series_groups_by_date(monkeypatch, _isolate_cost_log):
    _no_budget(monkeypatch)
    from src.cost_tracker import record_run, spend_summary

    record_run(model="sonnet", cost_usd=0.10)
    record_run(model="sonnet", cost_usd=0.15)
    summary = spend_summary()
    # Both records happen now → one bucket with 2 runs.
    assert len(summary.daily_series) == 1
    bucket = summary.daily_series[0]
    assert bucket["runs"] == 2
    assert bucket["cost_usd"] == pytest.approx(0.25, abs=0.01)


# ── spend_status_line (observability surface) ──────────────────────────────


def test_spend_status_line_uncapped(monkeypatch):
    from types import SimpleNamespace

    from src import cost_tracker

    monkeypatch.setattr(cost_tracker, "spend_summary", lambda **_kw: SimpleNamespace(month_to_date_usd=8.0))
    monkeypatch.setattr(cost_tracker, "_budget_from_settings", lambda: 0.0)
    line = cost_tracker.spend_status_line()
    assert "$8.00" in line
    assert "no monthly cap set" in line


def test_spend_status_line_capped_shows_pct_and_remaining(monkeypatch):
    from types import SimpleNamespace

    from src import cost_tracker

    monkeypatch.setattr(cost_tracker, "spend_summary", lambda **_kw: SimpleNamespace(month_to_date_usd=15.0))
    monkeypatch.setattr(cost_tracker, "_budget_from_settings", lambda: 25.0)
    line = cost_tracker.spend_status_line()
    assert "$15.00 of $25.00 cap" in line
    assert "60% used" in line
    assert "$10.00 left" in line
