from datetime import datetime, timedelta

import pytest

from src.activity_loader import holding_days_by_ticker, parse_activities_csv


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


def test_parse_activities_csv_can_parse_full_export(tmp_path):
    old_date = (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d")
    csv_path = tmp_path / "activities.csv"
    csv_path.write_text(
        "\n".join(
            [
                "transaction_date,settlement_date,account_id,account_type,activity_type,activity_sub_type,direction,symbol,name,currency,quantity,unit_price,commission,net_cash_amount",
                f"{old_date},{old_date},1,TFSA,Trade,BUY,LONG,SOXL,Direxion Daily Semiconductor Bull 3X,USD,1,10,0,-10",
            ]
        )
    )

    assert parse_activities_csv(csv_path, days=90) == []
    full = parse_activities_csv(csv_path, days=None)

    assert len(full) == 1
    assert full[0]["ticker"] == "SOXL"


def test_activities_parser_detects_holdings_export(tmp_path):
    csv_path = tmp_path / "holdings-report-2026-06-01.csv"
    csv_path.write_text(
        "\n".join(
            [
                "Symbol,Quantity,Market Price,Market Price Currency,Book Value (Market),Market Value,Market Unrealized Returns",
                "NVDA,1,100,USD,90,100,10",
            ]
        )
    )

    with pytest.raises(ValueError, match="Holdings CSV.*Activities CSV"):
        parse_activities_csv(csv_path, days=None)


def test_get_recent_trades_summary():
    from src.activity_loader import get_recent_trades_summary

    activities = [
        {"date": "2026-05-01", "type": "Trade", "sub_type": "BUY", "ticker": "NVDA", "quantity": 2},
        {"date": "2026-05-15", "type": "Trade", "sub_type": "SELL", "ticker": "NVDA", "quantity": 1},
        {"date": "2026-05-01", "type": "Dividend", "sub_type": "", "ticker": "MSFT", "quantity": 0},  # skipped
        {"date": "2026-05-01", "type": "Trade", "sub_type": "BUY", "ticker": "", "quantity": 1},  # no ticker, skipped
    ]
    result = get_recent_trades_summary(activities)
    assert "NVDA" in result
    assert len(result["NVDA"]["buys"]) == 1
    assert len(result["NVDA"]["sells"]) == 1
    assert "MSFT" not in result


def test_parse_activities_csv_no_header_error(tmp_path):
    import pytest

    from src.activity_loader import parse_activities_csv

    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("")
    with pytest.raises(ValueError, match="no header"):
        parse_activities_csv(csv_path, days=None)


def test_parse_activities_csv_filters_by_activity_type(tmp_path):
    from src.activity_loader import parse_activities_csv

    today = datetime.now().strftime("%Y-%m-%d")
    csv_path = tmp_path / "activities.csv"
    csv_path.write_text(
        "\n".join(
            [
                "transaction_date,settlement_date,account_id,account_type,activity_type,activity_sub_type,direction,symbol,name,currency,quantity,unit_price,commission,net_cash_amount",
                f"{today},{today},1,TFSA,Dividend,DIV,LONG,MSFT,Microsoft,USD,0,0,0,50",
                f"{today},{today},1,TFSA,Trade,BUY,LONG,NVDA,Nvidia,USD,1,100,0,-100",
            ]
        )
    )
    trades = parse_activities_csv(csv_path, days=30, activity_types=["Trade"])
    assert all(a["type"] == "Trade" for a in trades)
    assert any(a["ticker"] == "NVDA" for a in trades)

    all_types = parse_activities_csv(csv_path, days=30, activity_types=None)
    # activity_types=None → defaults to Trade only
    assert all(a["type"] == "Trade" for a in all_types)
