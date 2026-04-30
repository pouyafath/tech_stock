"""
activity_loader.py
Parses a Wealthsimple Activities CSV export.
Extracts recent trades for context (last N days).

Activities CSV columns:
  transaction_date, settlement_date, account_id, account_type,
  activity_type, activity_sub_type, direction,
  symbol, name, currency, quantity, unit_price, commission, net_cash_amount
"""

import csv
from datetime import datetime, timedelta
from pathlib import Path

from src._utils import clean_csv_row, safe_float
from src.constants import LEVERAGED_ETFS


# Minimum columns we need from the Wealthsimple Activities CSV.
REQUIRED_ACTIVITIES_COLUMNS = {
    "transaction_date",
    "activity_type",
    "symbol",
    "quantity",
    "unit_price",
    "net_cash_amount",
}


def parse_activities_csv(
    csv_path: str | Path,
    days: int = 90,
    activity_types: list[str] = None,
) -> list[dict]:
    """
    Parse a Wealthsimple Activities CSV. Returns recent activities within last N days.

    activity_types filter: defaults to ['Trade'] only.
    Pass None to get all types (Trade, Dividend, MoneyMovement, etc.)

    Returns list of dicts:
    {
      "date": "YYYY-MM-DD",
      "type": str,         # Trade, Dividend, MoneyMovement, etc.
      "sub_type": str,     # BUY, SELL, EFT, etc.
      "direction": str,    # LONG
      "ticker": str,
      "name": str,
      "currency": str,
      "quantity": float,
      "unit_price": float,
      "net_cash": float,   # negative = money out (buy), positive = money in (sell/dividend)
    }
    """
    if activity_types is None:
        activity_types = ["Trade"]

    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Activities CSV not found: {csv_path}")

    cutoff = datetime.now() - timedelta(days=days)
    activities = []

    with open(csv_path, encoding="utf-8-sig") as f:
        lines = [l for l in f.read().splitlines() if l.strip() and not l.strip().strip('"').startswith("As of")]

    reader = csv.DictReader(lines)

    # ── Validate CSV schema ─────────────────────────────────────────────
    if reader.fieldnames:
        actual_cols = {c.strip().strip('"') for c in reader.fieldnames}
        missing = REQUIRED_ACTIVITIES_COLUMNS - actual_cols
        if missing:
            raise ValueError(
                f"Activities CSV is missing required columns: {sorted(missing)}. "
                f"Wealthsimple may have changed the export format. "
                f"Got columns: {sorted(actual_cols)}. "
                f"Update REQUIRED_ACTIVITIES_COLUMNS in activity_loader.py if intentional."
            )
    else:
        raise ValueError(
            f"Activities CSV has no header row. Expected columns: {sorted(REQUIRED_ACTIVITIES_COLUMNS)}"
        )

    for row in reader:
        row = clean_csv_row(row)

        date_str = row.get("transaction_date", "").strip()
        if not date_str:
            continue

        try:
            tx_date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue

        if tx_date < cutoff:
            continue

        activity_type = row.get("activity_type", "").strip()
        if activity_types and activity_type not in activity_types:
            continue

        ticker = row.get("symbol", "").strip()
        quantity = safe_float(row.get("quantity", ""))
        unit_price = safe_float(row.get("unit_price", ""))
        net_cash = safe_float(row.get("net_cash_amount", ""))

        activities.append({
            "date": date_str,
            "type": activity_type,
            "sub_type": row.get("activity_sub_type", "").strip(),
            "direction": row.get("direction", "").strip(),
            "ticker": ticker,
            "name": row.get("name", "").strip(),
            "currency": row.get("currency", "").strip(),
            "quantity": abs(quantity) if quantity else None,
            "unit_price": unit_price,
            "net_cash": net_cash,
        })

    # Newest first
    activities.sort(key=lambda x: x["date"], reverse=True)
    return activities


def get_recent_trades_summary(activities: list[dict]) -> dict:
    """
    Summarize recent trades by ticker.
    Returns {ticker: {"buys": [...], "sells": [...]}}
    """
    by_ticker = {}
    for a in activities:
        if a["type"] != "Trade":
            continue
        ticker = a["ticker"]
        if not ticker:
            continue
        if ticker not in by_ticker:
            by_ticker[ticker] = {"buys": [], "sells": []}
        sub = a.get("sub_type", "").upper()
        if "BUY" in sub:
            by_ticker[ticker]["buys"].append(a)
        elif "SELL" in sub:
            by_ticker[ticker]["sells"].append(a)
    return by_ticker


def holding_days_by_ticker(activities: list[dict], holdings: list[dict] = None) -> dict:
    """
    Estimate open-lot holding days by ticker from recent activities.

    Uses FIFO sells against buys. If the activity window misses the original
    buy, returns duration_unknown=True for currently held tickers.
    """
    held_tickers = {h.get("ticker") for h in holdings or [] if h.get("quantity")}
    lots_by_ticker = {}
    for activity in sorted(activities or [], key=lambda row: row.get("date", "")):
        if activity.get("type") != "Trade":
            continue
        ticker = activity.get("ticker")
        if not ticker:
            continue
        sub_type = (activity.get("sub_type") or "").upper()
        quantity = activity.get("quantity") or 0
        if quantity <= 0:
            continue
        lots = lots_by_ticker.setdefault(ticker, [])
        if "BUY" in sub_type:
            lots.append({"date": activity.get("date"), "quantity": quantity})
        elif "SELL" in sub_type:
            remaining = quantity
            while lots and remaining > 0:
                lot = lots[0]
                used = min(lot["quantity"], remaining)
                lot["quantity"] -= used
                remaining -= used
                if lot["quantity"] <= 1e-8:
                    lots.pop(0)

    today = datetime.now().date()
    out = {}
    tickers = held_tickers or set(lots_by_ticker)
    for ticker in tickers:
        if not ticker:
            continue
        lots = [lot for lot in lots_by_ticker.get(ticker, []) if lot.get("quantity", 0) > 1e-8]
        earliest = None
        for lot in lots:
            try:
                lot_date = datetime.strptime(lot["date"], "%Y-%m-%d").date()
            except (TypeError, ValueError):
                continue
            earliest = lot_date if earliest is None or lot_date < earliest else earliest
        out[ticker] = {
            "ticker": ticker,
            "days_held": (today - earliest).days if earliest else None,
            "earliest_open_buy": earliest.isoformat() if earliest else None,
            "duration_unknown": earliest is None and ticker in held_tickers,
            "is_leveraged_etf": ticker in LEVERAGED_ETFS,
        }
    return out


def format_activities_for_prompt(activities: list[dict], days: int = 90) -> str:
    """Format recent trade activities into a readable string for the Claude prompt."""
    if not activities:
        return f"No trades in the last {days} days."

    lines = [f"Recent trades (last {days} days, newest first):"]
    for a in activities:
        if a["type"] != "Trade":
            continue
        sub = a.get("sub_type", "?").upper()
        qty = a.get("quantity")
        price = a.get("unit_price")
        ticker = a.get("ticker", "?")
        currency = a.get("currency", "")
        date = a.get("date", "")
        net = a.get("net_cash")

        qty_str = f"{qty:.4f} shares" if qty else ""
        price_str = f"@ ${price:.4f} {currency}" if price else ""
        net_str = f"(net ${net:+.2f})" if net else ""

        lines.append(f"  {date}  {sub:4s}  {ticker:8s}  {qty_str} {price_str} {net_str}")

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "activities-export.csv"
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 90
    activities = parse_activities_csv(path, days=days)
    print(f"Loaded {len(activities)} trades from last {days} days")
    print(format_activities_for_prompt(activities, days))
