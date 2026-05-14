from src.position_aging import (
    DEFAULT_TIERS,
    aging_summary,
    annotate_holdings,
    classify_age,
    format_aging_for_prompt,
)


def test_classify_age_default_boundaries():
    assert classify_age(0) == "fresh"
    assert classify_age(30) == "fresh"
    assert classify_age(90) == "fresh"
    assert classify_age(91) == "core"
    assert classify_age(180) == "core"
    assert classify_age(181) == "mature"
    assert classify_age(365) == "mature"
    assert classify_age(366) == "aged"
    assert classify_age(730) == "aged"
    assert classify_age(731) == "stale"
    assert classify_age(2000) == "stale"


def test_classify_age_handles_unknown():
    assert classify_age(None) is None


def test_classify_age_respects_custom_tiers():
    tiers = {"fresh_max_days": 30, "core_max_days": 90,
             "mature_max_days": 180, "aged_max_days": 365}
    assert classify_age(15, tiers) == "fresh"
    assert classify_age(45, tiers) == "core"
    assert classify_age(150, tiers) == "mature"
    assert classify_age(300, tiers) == "aged"
    assert classify_age(400, tiers) == "stale"


def test_annotate_holdings_attaches_days_and_tier():
    holdings = [
        {"ticker": "AAPL", "quantity": 10},
        {"ticker": "NVDA", "quantity": 5},
        {"ticker": "PLTR", "quantity": 0},  # no map entry
    ]
    days_map = {
        "AAPL": {"days_held": 200, "duration_unknown": False, "lower_bound_days": None},
        "NVDA": {"days_held": 800, "duration_unknown": False},
    }
    out = annotate_holdings(holdings, days_map)
    aapl = next(h for h in out if h["ticker"] == "AAPL")
    nvda = next(h for h in out if h["ticker"] == "NVDA")
    pltr = next(h for h in out if h["ticker"] == "PLTR")
    assert aapl["aging_tier"] == "mature"
    assert aapl["days_held"] == 200
    assert aapl["lower_bound_days"] is None
    assert nvda["aging_tier"] == "stale"
    assert pltr["aging_tier"] is None  # no data
    # Original holdings dict not mutated
    assert "aging_tier" not in holdings[0]


def test_annotate_holdings_preserves_unknown_duration_lower_bound():
    holdings = [{"ticker": "SOXL", "quantity": 1}]
    days_map = {"SOXL": {"days_held": None, "duration_unknown": True, "lower_bound_days": 41}}

    out = annotate_holdings(holdings, days_map)

    assert out[0]["holding_duration_unknown"] is True
    assert out[0]["lower_bound_days"] == 41


def test_aging_summary_lists_stale_aged_mature():
    annotated = [
        {"ticker": "FRESH", "aging_tier": "fresh"},
        {"ticker": "CORE",  "aging_tier": "core"},
        {"ticker": "MATU",  "aging_tier": "mature"},
        {"ticker": "AGED",  "aging_tier": "aged"},
        {"ticker": "OLD",   "aging_tier": "stale"},
        {"ticker": "X",     "aging_tier": None},
    ]
    summary = aging_summary(annotated)
    assert summary["counts"]["fresh"] == 1
    assert summary["counts"]["stale"] == 1
    assert summary["counts"]["unknown"] == 1
    assert summary["stale_tickers"] == ["OLD"]
    assert summary["aged_tickers"] == ["AGED"]
    assert summary["mature_tickers"] == ["MATU"]


def test_format_for_prompt_emits_only_when_actionable():
    # All fresh/core: returns empty string (nothing actionable)
    summary = {"counts": {"fresh": 3, "core": 2, "mature": 0, "aged": 0, "stale": 0},
               "stale_tickers": [], "aged_tickers": [], "mature_tickers": []}
    assert format_aging_for_prompt([], summary) == ""

    # With stale: returns block
    summary["stale_tickers"] = ["OLD"]
    summary["counts"]["stale"] = 1
    block = format_aging_for_prompt([], summary)
    assert "STALE" in block
    assert "OLD" in block
    assert "FORCE EXIT" in block


def test_default_tiers_match_strategy_doc():
    # The user's strategy: 3-6 month sweet spot, 2-year cap
    assert DEFAULT_TIERS["fresh_max_days"] == 90
    assert DEFAULT_TIERS["core_max_days"] == 180
    assert DEFAULT_TIERS["aged_max_days"] == 730  # 2 years
