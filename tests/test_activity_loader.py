from datetime import datetime, timedelta

from src.activity_loader import holding_days_by_ticker


def test_holding_days_records_lower_bound_when_entry_predates_activity_export():
    oldest = (datetime.now() - timedelta(days=41)).strftime("%Y-%m-%d")
    newer = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    activities = [
        {"date": oldest, "type": "Trade", "sub_type": "BUY", "ticker": "META", "quantity": 1},
        {"date": newer, "type": "Trade", "sub_type": "BUY", "ticker": "NVDA", "quantity": 1},
    ]
    holdings = [{"ticker": "SOXL", "quantity": 2}]

    out = holding_days_by_ticker(activities, holdings)

    assert out["SOXL"]["days_held"] is None
    assert out["SOXL"]["duration_unknown"] is True
    assert out["SOXL"]["lower_bound_days"] == 41
