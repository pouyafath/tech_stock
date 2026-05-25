"""Sector rotation 1-month relative-strength tracker."""

from src.sector_rotation import classify, format_for_prompt, rank_sectors


def _ctx(values: dict) -> dict:
    return {ticker: {"change_pct_21d": pct} for ticker, pct in values.items()}


def test_rank_sectors_orders_best_first():
    ctx = _ctx({"XLK": 5.0, "XLE": -2.0, "XLF": 1.0})
    ranked = rank_sectors(ctx)
    assert [r["ticker"] for r in ranked] == ["XLK", "XLF", "XLE"]


def test_rank_filters_errors_and_missing():
    ctx = {
        "XLK": {"change_pct_21d": 4.0},
        "XLF": {"error": "fetch failed"},
        "XLE": {"change_pct_21d": None},
    }
    ranked = rank_sectors(ctx)
    assert [r["ticker"] for r in ranked] == ["XLK"]


def test_classify_identifies_leaders_and_laggards():
    ctx = _ctx(
        {
            "XLK": 6.0,
            "XLY": 4.5,
            "XLV": 3.0,
            "XLF": 1.0,
            "XLI": 0.5,
            "XLU": -1.0,
            "XLP": -2.0,
            "XLE": -3.5,
        }
    )
    result = classify(ctx)
    leader_tickers = [r["ticker"] for r in result["leaders"]]
    laggard_tickers = [r["ticker"] for r in result["laggards"]]
    assert "XLK" in leader_tickers
    assert "XLE" in laggard_tickers


def test_rotating_in_detected_when_bottom_moves_to_top():
    prev = _ctx(
        {
            "XLK": 5.0,
            "XLY": 4.0,
            "XLV": 3.0,
            "XLF": 1.0,
            "XLI": -1.0,
            "XLU": -2.0,
            "XLP": -3.0,
            "XLE": -4.0,
        }
    )
    # XLE moves from worst to top half
    curr = _ctx(
        {
            "XLE": 5.0,
            "XLK": 4.0,
            "XLY": 3.0,
            "XLV": 2.0,
            "XLF": 0.0,
            "XLI": -1.0,
            "XLU": -2.0,
            "XLP": -3.0,
        }
    )
    result = classify(curr, previous_market_context=prev)
    assert "XLE" in result["rotating_in"]


def test_rotating_out_detected_when_top_moves_to_bottom():
    prev = _ctx(
        {
            "XLK": 5.0,
            "XLY": 4.0,
            "XLV": 3.0,
            "XLF": 1.0,
            "XLI": -1.0,
            "XLU": -2.0,
            "XLP": -3.0,
            "XLE": -4.0,
        }
    )
    # XLK falls from top to bottom
    curr = _ctx(
        {
            "XLF": 5.0,
            "XLY": 4.0,
            "XLV": 3.0,
            "XLI": 1.0,
            "XLU": 0.0,
            "XLP": -1.0,
            "XLE": -2.0,
            "XLK": -5.0,
        }
    )
    result = classify(curr, previous_market_context=prev)
    assert "XLK" in result["rotating_out"]


def test_classify_handles_no_data():
    result = classify({})
    assert result["leaders"] == []
    assert result["laggards"] == []
    assert result["rotating_in"] == []


def test_format_emits_block_when_data_present():
    classification = {
        "leaders": [{"ticker": "XLK", "change_pct": 5.0}],
        "laggards": [{"ticker": "XLE", "change_pct": -3.0}],
        "rotating_in": ["XLF"],
        "rotating_out": ["XLY"],
        "snapshot": [],
    }
    block = format_for_prompt(classification)
    assert "SECTOR ROTATION" in block
    assert "Leaders" in block and "XLK" in block
    assert "Laggards" in block and "XLE" in block
    assert "Rotating IN" in block and "XLF" in block
    assert "Rotating OUT" in block and "XLY" in block


def test_format_empty_when_no_leaders():
    assert format_for_prompt({"leaders": [], "laggards": []}) == ""


def test_classify_respects_universe_filter():
    """Cross-asset tickers (UUP, TLT) shouldn't pollute sector rotation."""
    ctx = _ctx({"XLK": 5.0, "XLE": -2.0, "TLT": 8.0, "GLD": 6.0})
    universe = {"XLK", "XLE"}
    result = classify(ctx, sector_universe=universe)
    snap_tickers = {r["ticker"] for r in result["snapshot"]}
    assert snap_tickers == {"XLK", "XLE"}
