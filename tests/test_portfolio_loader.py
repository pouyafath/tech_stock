import pytest

from src.portfolio_loader import parse_holdings_csv


HEADER = [
    "Symbol",
    "Exchange",
    "MIC",
    "Name",
    "Security Type",
    "Quantity",
    "Market Price",
    "Market Price Currency",
    "Book Value (CAD)",
    "Book Value Currency (CAD)",
    "Book Value (Market)",
    "Book Value Currency (Market)",
    "Market Value",
    "Market Value Currency",
    "Market Unrealized Returns",
    "Market Unrealized Returns Currency",
]


def _write_holdings(path, rows):
    lines = [",".join(HEADER)]
    for row in rows:
        lines.append(",".join(str(row.get(col, "")) for col in HEADER))
    lines.append('"As of 2026-04-29 16:00"')
    path.write_text("\n".join(lines))


def test_holdings_parsing_cdr_to_cash_and_required_columns(tmp_path):
    path = tmp_path / "holdings.csv"
    _write_holdings(path, [
        {
            "Symbol": "AAPL",
            "Exchange": "NASDAQ",
            "MIC": "XNAS",
            "Name": "Apple Inc",
            "Security Type": "EQUITY",
            "Quantity": 1,
            "Market Price": 200,
            "Market Price Currency": "USD",
            "Book Value (CAD)": 240,
            "Book Value (Market)": 180,
            "Market Value": 200,
            "Market Value Currency": "USD",
            "Market Unrealized Returns": 20,
            "Market Unrealized Returns Currency": "USD",
        },
        {
            "Symbol": "COST",
            "Exchange": "TSX",
            "MIC": "XTSE",
            "Name": "Costco CDR CAD Hedged",
            "Security Type": "EQUITY",
            "Quantity": 2,
            "Market Price": 35,
            "Market Price Currency": "CAD",
            "Book Value (CAD)": 60,
            "Book Value (Market)": 60,
            "Market Value": 70,
            "Market Value Currency": "CAD",
            "Market Unrealized Returns": 10,
            "Market Unrealized Returns Currency": "CAD",
        },
        {
            "Symbol": "SHOP",
            "Exchange": "TSX",
            "MIC": "XTSE",
            "Name": "Shopify Inc",
            "Security Type": "EQUITY",
            "Quantity": 1,
            "Market Price": 100,
            "Market Price Currency": "CAD",
            "Book Value (CAD)": 90,
            "Book Value (Market)": 90,
            "Market Value": 100,
            "Market Value Currency": "CAD",
            "Market Unrealized Returns": 10,
            "Market Unrealized Returns Currency": "CAD",
        },
        {
            "Symbol": "CASH",
            "Exchange": "TSX",
            "MIC": "XTSE",
            "Name": "Global X High Interest Savings",
            "Security Type": "EXCHANGE_TRADED_FUND",
            "Quantity": 10,
            "Market Price": 50,
            "Market Price Currency": "CAD",
            "Book Value (CAD)": 500,
            "Book Value (Market)": 500,
            "Market Value": 500,
            "Market Value Currency": "CAD",
            "Market Unrealized Returns": 0,
            "Market Unrealized Returns Currency": "CAD",
        },
    ])

    portfolio = parse_holdings_csv(path)
    by_ticker = {row["ticker"]: row for row in portfolio["holdings"]}

    assert by_ticker["COST"]["is_cdr"] is True
    assert "SHOP.TO" in by_ticker
    assert portfolio["cash_cad"] == 500


def test_holdings_missing_required_columns_fails(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("Symbol,Quantity\nAAPL,1\n")

    with pytest.raises(ValueError, match="missing required columns"):
        parse_holdings_csv(path)
