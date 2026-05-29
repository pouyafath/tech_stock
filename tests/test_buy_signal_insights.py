from src.ui_support import is_buy_signal_candidate, target_upside_pct


def test_buy_signal_candidate_includes_buy_add_and_add_on_dip() -> None:
    assert is_buy_signal_candidate({"action": "BUY"}) is True
    assert is_buy_signal_candidate({"action": "ADD"}) is True
    assert is_buy_signal_candidate({"action": "HOLD", "hold_tier": "add_on_dip"}) is True


def test_buy_signal_candidate_excludes_non_buy_actions() -> None:
    assert is_buy_signal_candidate({"action": "TRIM"}) is False
    assert is_buy_signal_candidate({"action": "SELL"}) is False
    assert is_buy_signal_candidate({"action": "HOLD", "hold_tier": "keep"}) is False


def test_target_upside_pct_handles_valid_and_invalid_inputs() -> None:
    assert target_upside_pct(125, 100) == 25.0
    assert target_upside_pct(90, 100) == -10.0
    assert target_upside_pct(None, 100) is None
    assert target_upside_pct(125, 0) is None
