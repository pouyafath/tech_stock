from src.csv_health import inspect_csv, validate_csv_pair

HOLDINGS_HEADER = "Symbol,Quantity,Market Price,Market Price Currency,Book Value (Market),Market Value,Market Unrealized Returns"
ACTIVITIES_HEADER = "transaction_date,activity_type,symbol,quantity,unit_price,net_cash_amount"


def test_inspect_csv_identifies_holdings_export(tmp_path):
    path = tmp_path / "holdings-report-2026-06-13.csv"
    path.write_text(f"{HOLDINGS_HEADER}\nNVDA,1,100,USD,90,100,10\n", encoding="utf-8")

    result = inspect_csv(path, expected_kind="holdings")

    assert result.kind == "holdings"
    assert result.ok_for_expected is True
    assert result.swapped is False


def test_inspect_csv_identifies_activities_export(tmp_path):
    path = tmp_path / "activities-export-2026-06-13.csv"
    path.write_text(f"{ACTIVITIES_HEADER}\n2026-06-13,Trade,NVDA,1,100,-100\n", encoding="utf-8")

    result = inspect_csv(path, expected_kind="activities")

    assert result.kind == "activities"
    assert result.ok_for_expected is True
    assert result.swapped is False


def test_validate_csv_pair_auto_swaps_when_both_fields_are_reversed(tmp_path):
    holdings = tmp_path / "holdings-report-2026-06-13.csv"
    holdings.write_text(f"{HOLDINGS_HEADER}\nNVDA,1,100,USD,90,100,10\n", encoding="utf-8")
    activities = tmp_path / "activities-export-2026-06-13.csv"
    activities.write_text(f"{ACTIVITIES_HEADER}\n2026-06-13,Trade,NVDA,1,100,-100\n", encoding="utf-8")

    result = validate_csv_pair(activities, holdings)

    assert result["holdings_csv"] == holdings
    assert result["activities_csv"] == activities
    assert result["warnings"]


def test_validate_csv_pair_blocks_sample_holdings_for_paid_run(tmp_path):
    path = tmp_path / "holdings-report-sample.csv"
    path.write_text(f"{HOLDINGS_HEADER}\nNVDA,1,100,USD,90,100,10\n", encoding="utf-8")

    try:
        validate_csv_pair(path, None)
    except ValueError as exc:
        assert "sample/demo data" in str(exc)
    else:
        raise AssertionError("sample holdings should be blocked unless demo mode allows it")


def test_validate_csv_pair_allows_sample_holdings_in_demo_mode(tmp_path):
    path = tmp_path / "holdings-report-sample.csv"
    path.write_text(f"{HOLDINGS_HEADER}\nNVDA,1,100,USD,90,100,10\n", encoding="utf-8")

    result = validate_csv_pair(path, None, allow_sample=True)

    assert result["holdings_csv"] == path
