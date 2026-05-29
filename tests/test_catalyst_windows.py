from datetime import date

from src.catalyst_windows import (
    annotate_tickers,
    classify_earnings_window,
    format_for_prompt,
    macro_session_tags,
)


def test_lockdown_window_blocks_buys():
    today = date(2026, 5, 6)
    earnings = date(2026, 5, 8)  # 2 days out
    tag = classify_earnings_window(earnings, today)
    assert tag is not None
    assert tag["window"] == "lockdown"
    assert tag["days_to"] == 2


def test_setup_window_allows_entries():
    today = date(2026, 5, 6)
    earnings = date(2026, 5, 25)  # 19 days out
    tag = classify_earnings_window(earnings, today)
    assert tag is not None
    assert tag["window"] == "setup"


def test_drift_window_allows_post_earnings_adds():
    today = date(2026, 5, 6)
    earnings = date(2026, 5, 4)  # 2 days ago
    tag = classify_earnings_window(earnings, today)
    assert tag is not None
    assert tag["window"] == "drift"


def test_no_tag_outside_known_windows():
    today = date(2026, 5, 6)
    far_future = date(2026, 8, 1)
    far_past = date(2026, 1, 1)
    assert classify_earnings_window(far_future, today) is None
    assert classify_earnings_window(far_past, today) is None
    assert classify_earnings_window(None, today) is None


def test_classify_handles_string_dates():
    today = date(2026, 5, 6)
    tag = classify_earnings_window("2026-05-08", today)
    assert tag and tag["window"] == "lockdown"


def test_annotate_tickers_filters_to_meaningful_windows():
    today = date(2026, 5, 6)
    enriched = {
        "AAPL": {"upcoming_earnings": {"date": "2026-05-09"}},  # lockdown
        "MSFT": {"upcoming_earnings": {"date": "2026-08-01"}},  # too far
        "NVDA": {"upcoming_earnings": {"date": "2026-05-25"}},  # setup
        "GOOG": {},  # missing
    }
    out = annotate_tickers(enriched, today)
    assert "AAPL" in out and out["AAPL"]["window"] == "lockdown"
    assert "NVDA" in out and out["NVDA"]["window"] == "setup"
    assert "MSFT" not in out
    assert "GOOG" not in out


def test_macro_session_tags_detects_nfp_first_friday():
    # First Friday of May 2026 is the 1st
    nfp_day = date(2026, 5, 1)
    tags = macro_session_tags({}, nfp_day)
    assert any("NFP_DAY" in t for t in tags)


def test_macro_session_tags_detects_cpi_window():
    today = date(2026, 5, 12)
    cal = {"next_cpi_window": "2026-05-10 to 2026-05-15"}
    tags = macro_session_tags(cal, today)
    assert any("CPI_WEEK" in t for t in tags)


def test_macro_session_tags_detects_fomc_in_2_days():
    today = date(2026, 5, 6)
    cal = {"next_fomc_dates": ["2026-05-08"]}
    tags = macro_session_tags(cal, today)
    assert any("FOMC_IN_2D" in t for t in tags)


def test_format_for_prompt_groups_by_window():
    ticker_tags = {
        "AAPL": {"window": "lockdown", "days_to": 2, "label": "earnings lockdown"},
        "NVDA": {"window": "setup", "days_to": 19, "label": "earnings setup"},
    }
    block = format_for_prompt(ticker_tags, ["FOMC_TODAY"])
    assert "CATALYST WINDOWS" in block
    assert "LOCKDOWN" in block
    assert "SETUP" in block
    assert "AAPL" in block and "NVDA" in block
    assert "FOMC_TODAY" in block


def test_format_for_prompt_empty_when_no_tags():
    assert format_for_prompt({}, []) == ""
