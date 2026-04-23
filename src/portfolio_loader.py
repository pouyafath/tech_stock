"""
portfolio_loader.py
Parses a Wealthsimple Holdings CSV export into the portfolio dict format.

Holdings CSV columns:
  Account Name, Account Type, Account Classification, Account Number,
  Symbol, Exchange, MIC, Name, Security Type,
  Quantity, Position Direction,
  Market Price, Market Price Currency,
  Book Value (CAD), Book Value Currency (CAD),
  Book Value (Market), Book Value Currency (Market),
  Market Value, Market Value Currency,
  Market Unrealized Returns, Market Unrealized Returns Currency
"""

import csv
import json
from pathlib import Path


CDR_EXCHANGES = {"XTSE", "TSX"}  # Toronto Stock Exchange = CDR or CAD-listed


def _safe_float(val: str) -> float | None:
    try:
        return float(val.strip()) if val and val.strip() else None
    except ValueError:
        return None


def parse_holdings_csv(csv_path: str | Path) -> dict:
    """
    Parse a Wealthsimple Holdings CSV into a portfolio dict.

    Returns:
    {
      "source": "holdings_csv",
      "exported_at": "As of..." string from the CSV,
      "cash_cad": estimated cash (from CASH ETF if present),
      "holdings": [
        {
          "ticker": str,
          "exchange": str,
          "name": str,
          "security_type": str,        # EQUITY, EXCHANGE_TRADED_FUND
          "is_cdr": bool,              # True if CAD-hedged CDR on TSX
          "quantity": float,
          "market_price": float,
          "market_currency": str,      # "USD" or "CAD"
          "avg_cost_market": float,    # avg cost in market currency
          "avg_cost_cad": float,       # avg cost in CAD
          "market_value_market": float,
          "market_value_cad": float,   # approx, from CSV
          "unrealized_pnl": float,     # in market currency
          "unrealized_pnl_cad": float,
          "unrealized_pnl_pct": float,
        }
      ]
    }
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Holdings CSV not found: {csv_path}")

    holdings = []
    exported_at = ""

    with open(csv_path, encoding="utf-8-sig") as f:
        lines = f.read().splitlines()

    # The last non-empty line is usually "As of YYYY-MM-DD ..." metadata
    data_lines = []
    for line in lines:
        stripped = line.strip().strip('"')
        if stripped.startswith("As of"):
            exported_at = stripped
        elif line.strip():
            data_lines.append(line)

    reader = csv.DictReader(data_lines)

    # Normalize column names (strip quotes and spaces)
    for row in reader:
        row = {k.strip().strip('"'): v.strip().strip('"') for k, v in row.items()}

        symbol = row.get("Symbol", "").strip()
        if not symbol:
            continue

        exchange = row.get("Exchange", "").strip()
        mic = row.get("MIC", "").strip()
        name = row.get("Name", "").strip()
        security_type = row.get("Security Type", "").strip()
        quantity = _safe_float(row.get("Quantity", ""))
        market_price = _safe_float(row.get("Market Price", ""))
        market_currency = row.get("Market Price Currency", "USD").strip()

        book_value_cad = _safe_float(row.get("Book Value (CAD)", ""))
        book_value_market = _safe_float(row.get("Book Value (Market)", ""))
        book_currency_market = row.get("Book Value Currency (Market)", market_currency).strip()

        market_value = _safe_float(row.get("Market Value", ""))
        market_value_currency = row.get("Market Value Currency", market_currency).strip()

        unrealized = _safe_float(row.get("Market Unrealized Returns", ""))
        unrealized_currency = row.get("Market Unrealized Returns Currency", market_currency).strip()

        if quantity is None or quantity == 0:
            continue

        is_cdr = mic in CDR_EXCHANGES or exchange in CDR_EXCHANGES

        # Average cost in market currency
        avg_cost_market = None
        if book_value_market and quantity:
            avg_cost_market = book_value_market / quantity

        avg_cost_cad = None
        if book_value_cad and quantity:
            avg_cost_cad = book_value_cad / quantity

        # Unrealized P&L %
        unrealized_pct = None
        if unrealized and book_value_market and book_value_market != 0:
            unrealized_pct = round(unrealized / book_value_market * 100, 2)

        holdings.append({
            "ticker": symbol,
            "exchange": exchange,
            "name": name,
            "security_type": security_type,
            "is_cdr": is_cdr,
            "quantity": round(quantity, 6) if quantity else 0,
            "market_price": round(market_price, 4) if market_price else None,
            "market_currency": market_currency,
            "avg_cost_market": round(avg_cost_market, 4) if avg_cost_market else None,
            "avg_cost_cad": round(avg_cost_cad, 4) if avg_cost_cad else None,
            "market_value": round(market_value, 2) if market_value else None,
            "market_value_currency": market_value_currency,
            "book_value_cad": round(book_value_cad, 2) if book_value_cad else None,
            "unrealized_pnl": round(unrealized, 4) if unrealized else None,
            "unrealized_pnl_currency": unrealized_currency,
            "unrealized_pnl_pct": unrealized_pct,
        })

    # Estimate cash from CASH ETF (Global X High Interest Savings)
    cash_cad = 0.0
    for h in holdings:
        if h["ticker"] == "CASH" and h["market_currency"] == "CAD":
            cash_cad = h.get("market_value") or 0.0
            break

    return {
        "source": "holdings_csv",
        "exported_at": exported_at,
        "cash_cad": cash_cad,
        "holdings": holdings,
    }


def save_portfolio_json(portfolio: dict, output_path: str | Path):
    """Save parsed portfolio to JSON (useful for inspection)."""
    with open(output_path, "w") as f:
        json.dump(portfolio, f, indent=2)


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "holdings-report.csv"
    portfolio = parse_holdings_csv(path)
    print(f"Loaded {len(portfolio['holdings'])} positions | {portfolio['exported_at']}")
    total_cad = sum(
        h["book_value_cad"] or 0 for h in portfolio["holdings"]
    )
    print(f"Total book value (CAD): ${total_cad:,.2f}")
    for h in portfolio["holdings"]:
        cdr_flag = " [CDR]" if h["is_cdr"] else ""
        pnl = h.get("unrealized_pnl_pct")
        pnl_str = f" | P&L {pnl:+.1f}%" if pnl is not None else ""
        print(f"  {h['ticker']:8s}{cdr_flag:6s} {h['quantity']:8.4f} × "
              f"${h['market_price'] or 0:.2f} {h['market_currency']}{pnl_str}")
