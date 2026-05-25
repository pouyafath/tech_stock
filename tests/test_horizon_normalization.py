"""Tests for time_horizon snap-to-canonical inside normalize_recommendation.

Claude occasionally drifts away from Rule 20's exact strings (e.g. "3 months"
instead of "1-3 months", or "long term" instead of "12-36 months").
normalize_recommendation must snap these to the canonical values used by:
  - backtester.HORIZON_DAYS lookups (drives mature-recommendation evaluation)
  - UI horizon filters
  - Report rendering and CSV exports
"""

import pytest

from src.claude_analyst import (
    _CANONICAL_HORIZONS,
    _normalize_time_horizon,
    normalize_recommendation,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Exact canonical strings pass through unchanged
        ("intraday", "intraday"),
        ("next session", "next session"),
        ("1-3 trading days", "1-3 trading days"),
        ("1-2 weeks", "1-2 weeks"),
        ("1-3 months", "1-3 months"),
        ("3-6 months", "3-6 months"),
        ("6-12 months", "6-12 months"),
        ("12-36 months", "12-36 months"),
        # Common variants we know Claude emits
        ("3 months", "1-3 months"),
        ("1 month", "1-3 months"),
        ("6 months", "3-6 months"),
        ("12 months", "6-12 months"),
        ("1 year", "6-12 months"),
        ("2 years", "12-36 months"),
        ("long term", "12-36 months"),
        ("long-term", "12-36 months"),
        ("multi-year", "12-36 months"),
        ("next quarter", "1-3 months"),
        ("1-3 days", "1-3 trading days"),
        ("overnight", "next session"),
        # Case- and whitespace-insensitive
        ("  3 MONTHS  ", "1-3 months"),
        ("LONG TERM", "12-36 months"),
    ],
)
def test_normalize_snaps_to_canonical(raw, expected):
    assert _normalize_time_horizon(raw) == expected


def test_normalize_falls_back_to_default_on_unknown():
    # Pure gibberish → default 1-3 months
    assert _normalize_time_horizon("abc xyz") == "1-3 months"


def test_normalize_handles_missing_value():
    assert _normalize_time_horizon(None) == "1-3 months"
    assert _normalize_time_horizon("") == "1-3 months"


def test_normalize_recommendation_records_original_when_changed():
    rec = {
        "recommendations": [
            {"ticker": "NVDA", "action": "BUY", "conviction": 8, "time_horizon": "3 months"},
        ]
    }
    out = normalize_recommendation(rec)
    target = out["recommendations"][0]
    assert target["time_horizon"] == "1-3 months"
    assert target["time_horizon_original"] == "3 months"


def test_normalize_recommendation_skips_original_when_already_canonical():
    rec = {
        "recommendations": [
            {"ticker": "NVDA", "action": "BUY", "conviction": 8, "time_horizon": "3-6 months"},
        ]
    }
    out = normalize_recommendation(rec)
    target = out["recommendations"][0]
    assert target["time_horizon"] == "3-6 months"
    assert "time_horizon_original" not in target


def test_all_canonical_values_round_trip():
    """Sanity check: every canonical string normalizes to itself."""
    for canonical in _CANONICAL_HORIZONS:
        assert _normalize_time_horizon(canonical) == canonical


def test_normalize_does_not_misclassify_borderline():
    """Edge case: '4 months' should map to 3-6, not 1-3."""
    assert _normalize_time_horizon("4 months") == "3-6 months"
    assert _normalize_time_horizon("5 months") == "3-6 months"


def test_normalize_handles_weeks_and_days_heuristically():
    assert _normalize_time_horizon("a couple days") == "1-3 trading days"
    assert _normalize_time_horizon("a few weeks") == "1-2 weeks"
