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
