"""Tests for the thesis-decay tracker."""
from datetime import date, timedelta

from src.thesis_tracker import (
    DEFAULT_FORCE_EXIT_AFTER,
    DEFAULT_REVIEW_INTERVAL_DAYS,
    append_review,
    evaluate_progress,
    force_exit_candidates,
    format_for_prompt,
    quarterly_reviews_due,
    record_new_entries,
)


def test_record_new_entries_only_records_buys(tmp_path):
    log = tmp_path / "thesis.json"
    rec = {"recommendations": [
        {"ticker": "NVDA", "action": "BUY", "conviction": 8, "thesis": "AI growth"},
        {"ticker": "AAPL", "action": "ADD", "conviction": 7, "thesis": "iPhone refresh"},
        {"ticker": "MSFT", "action": "HOLD", "conviction": 6},
        {"ticker": "TSLA", "action": "SELL", "conviction": 8},
    ]}
    out = record_new_entries(rec, log, session_file="20260506_morning.json")
    tickers = [e["ticker"] for e in out]
    assert "NVDA" in tickers
    assert "AAPL" not in tickers   # ADD doesn't create new thesis
    assert "MSFT" not in tickers
    assert "TSLA" not in tickers


def test_record_new_entries_skips_already_held(tmp_path):
    log = tmp_path / "thesis.json"
    rec = {"recommendations": [{"ticker": "NVDA", "action": "BUY", "conviction": 8}]}
    holdings = [{"ticker": "NVDA", "quantity": 5}]
    out = record_new_entries(rec, log, session_file="x.json", holdings_pre_run=holdings)
    assert out == []


def test_record_new_entries_skips_existing_thesis(tmp_path):
    log = tmp_path / "thesis.json"
    rec = {"recommendations": [{"ticker": "NVDA", "action": "BUY", "conviction": 8}]}
    record_new_entries(rec, log, session_file="x.json")
    out = record_new_entries(rec, log, session_file="y.json")
    assert out == []


def test_quarterly_reviews_due_after_90_days(tmp_path):
    log = tmp_path / "thesis.json"
    today = date.today()
    rec = {"recommendations": [{"ticker": "NVDA", "action": "BUY", "conviction": 8}]}
    record_new_entries(rec, log, session_file="x.json", today=today - timedelta(days=100))
    due = quarterly_reviews_due(log, today=today)
    assert len(due) == 1
    assert due[0]["ticker"] == "NVDA"


def test_quarterly_reviews_not_due_before_interval(tmp_path):
    log = tmp_path / "thesis.json"
    today = date.today()
    rec = {"recommendations": [{"ticker": "NVDA", "action": "BUY", "conviction": 8}]}
    record_new_entries(rec, log, session_file="x.json", today=today - timedelta(days=30))
    due = quarterly_reviews_due(log, today=today)
    assert due == []


def test_evaluate_progress_classifications():
    thesis = {"original_conviction": 8}
    # Invalidated: position closed
    assert evaluate_progress(thesis, None, {"quantity": 0}) == "invalidated"
    # Invalidated: SELL
    assert evaluate_progress(thesis, {"action": "SELL"}, {"quantity": 5, "unrealized_pnl_pct": 10}) == "invalidated"
    # Materialized: +20% gain
    assert evaluate_progress(thesis, {"action": "HOLD", "conviction": 7},
                              {"quantity": 5, "unrealized_pnl_pct": 20}) == "materialized"
    # Partial: similar conviction, modest gain
    assert evaluate_progress(thesis, {"action": "HOLD", "conviction": 7},
                              {"quantity": 5, "unrealized_pnl_pct": 5}) == "partial"
    # Not yet: conviction down, position underwater
    assert evaluate_progress(thesis, {"action": "HOLD", "conviction": 5},
                              {"quantity": 5, "unrealized_pnl_pct": -10}) == "not_yet"


def test_force_exit_after_4_consecutive_not_yet(tmp_path):
    log = tmp_path / "thesis.json"
    today = date.today()
    rec = {"recommendations": [{"ticker": "BAD", "action": "BUY", "conviction": 7}]}
    record_new_entries(rec, log, session_file="x.json", today=today - timedelta(days=400))

    import json
    state = json.loads(log.read_text())
    key = next(iter(state))
    for i in range(DEFAULT_FORCE_EXIT_AFTER):
        append_review(log, key, "not_yet", current_conviction=6, current_action="HOLD",
                      today=today - timedelta(days=300 - i * 60))

    forced = force_exit_candidates(log)
    assert len(forced) == 1
    assert forced[0]["ticker"] == "BAD"


def test_force_exit_resets_after_partial(tmp_path):
    log = tmp_path / "thesis.json"
    rec = {"recommendations": [{"ticker": "MAYBE", "action": "BUY", "conviction": 7}]}
    record_new_entries(rec, log, session_file="x.json")
    import json
    key = next(iter(json.loads(log.read_text())))
    append_review(log, key, "not_yet", 6, "HOLD")
    append_review(log, key, "not_yet", 6, "HOLD")
    append_review(log, key, "partial", 7, "HOLD")  # resets streak
    append_review(log, key, "not_yet", 6, "HOLD")
    assert force_exit_candidates(log) == []


def test_format_for_prompt_includes_forced_exits():
    forced = [{"ticker": "BAD", "entry_date": "2025-04-01", "original_conviction": 8}]
    due = [{"ticker": "MAYBE", "entry_date": "2025-08-01", "original_thesis": "Long thesis text..."}]
    out = format_for_prompt(due, forced)
    assert "FORCED EXIT" in out
    assert "BAD" in out
    assert "MAYBE" in out
    assert "Due for review" in out


def test_format_for_prompt_empty_when_nothing_due():
    assert format_for_prompt([], []) == ""


def test_constants_match_strategy_doc():
    assert DEFAULT_REVIEW_INTERVAL_DAYS == 90
    assert DEFAULT_FORCE_EXIT_AFTER == 4   # 4 quarters = ~12 months
