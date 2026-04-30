import json

from src.drift_tracker import compute_drift, get_previous_session


def _write_log(path, ticker, action, conviction):
    path.write_text(json.dumps({
        "recommendations": [
            {
                "ticker": ticker,
                "action": action,
                "conviction": conviction,
                "net_expected_pct": 1.0,
            }
        ]
    }))


def test_get_previous_session_latest_and_skip_newest(tmp_path):
    older = tmp_path / "20260428_0900_morning.json"
    newest = tmp_path / "20260429_0900_morning.json"
    _write_log(older, "MSFT", "HOLD", 5)
    _write_log(newest, "MSFT", "BUY", 8)

    assert get_previous_session(tmp_path)["_session_file"] == newest.name
    assert get_previous_session(tmp_path, skip_newest=True)["_session_file"] == older.name


def test_compute_drift_action_flip_and_conviction_jump():
    previous = {
        "recommendations": [
            {"ticker": "MSFT", "action": "HOLD", "conviction": 5, "net_expected_pct": 0.2},
            {"ticker": "NVDA", "action": "HOLD", "conviction": 4, "net_expected_pct": 1.0},
        ]
    }
    current = {
        "recommendations": [
            {"ticker": "MSFT", "action": "BUY", "conviction": 7, "net_expected_pct": 3.0},
            {"ticker": "NVDA", "action": "HOLD", "conviction": 8, "net_expected_pct": 2.0},
        ]
    }

    drift = compute_drift(current, previous, conviction_delta_threshold=2)
    assert {item["drift_type"] for item in drift} == {"action_flip", "conviction_jump"}
