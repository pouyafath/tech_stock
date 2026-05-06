"""
paper_trading.py — simulate execution of every Claude recommendation against
a parallel "what if I'd followed every rec" portfolio.

Persistent state:  data/paper_portfolio.json
  Format: {
    "starting_cash_usd":   25000,
    "current_cash_usd":    18250.42,
    "positions": {
      "NVDA": {"shares": 1.25, "avg_cost": 800.0, "first_entry_date": "2026-04-01"},
      ...
    },
    "trade_log": [
      {"date": "2026-04-01", "ticker": "NVDA", "action": "BUY",
       "shares": 0.5, "price": 800.0, "fee_usd": 0.40, "session_file": "..."},
      ...
    ],
    "value_history": [
      {"date": "2026-04-01", "value_usd": 25000.0},
      {"date": "2026-04-15", "value_usd": 25420.50},
      ...
    ]
  }

The simulator:
  1. Reads `recommendation` from each session
  2. For each BUY/ADD with `invest_amount_usd`: deducts the amount from cash,
     credits fractional shares at current price, applies estimated fees
  3. For each SELL/TRIM: closes a configurable fraction of the position
  4. For each HOLD: no-op
  5. Marks-to-market the portfolio using current prices
  6. Appends to value_history

Allows the user to quantify their *discretion penalty*: the gap between
recommendations and what they actually traded. Without this, you can't
say "Claude's picks would have made me 12% YTD; I made 8%; the gap is
my hesitation."
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

DEFAULT_STARTING_CASH_USD = 25_000.0
DEFAULT_TRIM_FRACTION = 0.30  # how much of position to sell on TRIM
DEFAULT_FEE_PCT = 0.10          # 0.1% one-way default; override per ticker via fee_calculator


def _load_state(path: Path) -> dict:
    if not path.exists():
        return _empty_state()
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return _empty_state()


def _empty_state() -> dict:
    return {
        "starting_cash_usd":  DEFAULT_STARTING_CASH_USD,
        "current_cash_usd":   DEFAULT_STARTING_CASH_USD,
        "positions":          {},
        "trade_log":          [],
        "value_history":      [],
    }


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, default=str))


def _estimate_fee(ticker: str, notional_usd: float) -> float:
    """Estimate one-way fee using fee_calculator.calculate_round_trip_cost."""
    try:
        from src.fee_calculator import calculate_round_trip_cost
        fees = calculate_round_trip_cost(ticker, notional_usd=notional_usd)
        # round-trip / 2 = one-way
        return float(fees.get("total_usd", 0)) / 2
    except Exception:
        return notional_usd * DEFAULT_FEE_PCT / 100


def initialize(state_path: Path | str, starting_cash_usd: float | None = None) -> dict:
    """Initialize a new paper portfolio with the given starting cash."""
    path = Path(state_path)
    state = _empty_state()
    if starting_cash_usd is not None:
        state["starting_cash_usd"] = float(starting_cash_usd)
        state["current_cash_usd"] = float(starting_cash_usd)
    _save_state(path, state)
    return state


def apply_session(
    state_path: Path | str,
    recommendation: dict,
    market_data: dict,
    session_file: str,
    trim_fraction: float = DEFAULT_TRIM_FRACTION,
    today: date | None = None,
) -> dict:
    """Apply this session's recommendations to the paper portfolio.

    Returns the updated state. Skips:
      - BUY/ADD without `invest_amount_usd` set
      - Any ticker without a `current_price` in market_data
      - SELL/TRIM on a position we don't hold (no-op)
    """
    path = Path(state_path)
    state = _load_state(path)
    today = today or date.today()
    today_iso = today.isoformat()

    for rec in recommendation.get("recommendations", []) or []:
        ticker = (rec.get("ticker") or "").upper()
        action = (rec.get("action") or "HOLD").upper()
        if not ticker or ticker == "CASH" or action == "HOLD":
            continue

        md = (market_data or {}).get(ticker) or {}
        price = md.get("current_price")
        if not price or price <= 0:
            continue

        if action in {"BUY", "ADD"}:
            invest_usd = rec.get("invest_amount_usd")
            if invest_usd is None or invest_usd <= 0:
                continue
            invest_usd = min(float(invest_usd), state["current_cash_usd"])
            if invest_usd <= 0:
                continue
            fee = _estimate_fee(ticker, invest_usd)
            shares_bought = (invest_usd - fee) / price
            position = state["positions"].setdefault(ticker, {
                "shares": 0.0, "avg_cost": price, "first_entry_date": today_iso,
            })
            new_shares = position["shares"] + shares_bought
            if new_shares > 0:
                position["avg_cost"] = (
                    position["shares"] * position["avg_cost"] + shares_bought * price
                ) / new_shares
            position["shares"] = new_shares
            state["current_cash_usd"] -= invest_usd
            state["trade_log"].append({
                "date": today_iso, "ticker": ticker, "action": action,
                "shares": round(shares_bought, 4), "price": price,
                "fee_usd": round(fee, 4), "session_file": session_file,
            })

        elif action in {"SELL", "TRIM"}:
            position = state["positions"].get(ticker)
            if not position or position["shares"] <= 0:
                continue
            if action == "SELL":
                shares_sold = position["shares"]
            else:
                shares_sold = position["shares"] * trim_fraction
            proceeds = shares_sold * price
            fee = _estimate_fee(ticker, proceeds)
            net_proceeds = proceeds - fee
            position["shares"] -= shares_sold
            state["current_cash_usd"] += net_proceeds
            state["trade_log"].append({
                "date": today_iso, "ticker": ticker, "action": action,
                "shares": round(shares_sold, 4), "price": price,
                "fee_usd": round(fee, 4), "session_file": session_file,
            })
            if position["shares"] <= 1e-6:
                del state["positions"][ticker]

    # Mark-to-market for value_history
    portfolio_value = mark_to_market(state, market_data)
    state["value_history"].append({
        "date":      today_iso,
        "value_usd": round(portfolio_value, 2),
    })

    _save_state(path, state)
    return state


def mark_to_market(state: dict, market_data: dict) -> float:
    """Total USD value of cash + positions at current market prices."""
    total = float(state.get("current_cash_usd", 0))
    for ticker, position in (state.get("positions") or {}).items():
        md = (market_data or {}).get(ticker) or {}
        price = md.get("current_price") or position.get("avg_cost") or 0
        total += float(position.get("shares", 0)) * float(price)
    return total


def performance_summary(state: dict, market_data: dict | None = None) -> dict:
    """Return key performance metrics for the paper portfolio."""
    starting = float(state.get("starting_cash_usd", 0)) or 1.0
    current_value = mark_to_market(state, market_data or {})
    total_return_pct = (current_value / starting - 1.0) * 100.0
    history = state.get("value_history") or []
    n_trades = len(state.get("trade_log") or [])
    n_positions = len(state.get("positions") or {})
    return {
        "starting_value_usd":  round(starting, 2),
        "current_value_usd":   round(current_value, 2),
        "current_cash_usd":    round(float(state.get("current_cash_usd", 0)), 2),
        "total_return_pct":    round(total_return_pct, 2),
        "n_trades":            n_trades,
        "n_open_positions":    n_positions,
        "n_marks_recorded":    len(history),
    }


def format_for_report(summary: dict) -> list[str]:
    """Render a paper-trading summary block for the markdown report."""
    if not summary or summary.get("n_trades", 0) == 0:
        return []
    return [
        "## Paper Portfolio (`--paper` mode)",
        "",
        f"Tracking what would happen if every Claude recommendation had been executed at the suggested size.",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Starting capital | ${summary['starting_value_usd']:,.0f} |",
        f"| Current value | ${summary['current_value_usd']:,.0f} |",
        f"| Cash available | ${summary['current_cash_usd']:,.0f} |",
        f"| **Total return** | **{summary['total_return_pct']:+.2f}%** |",
        f"| Trades executed | {summary['n_trades']} |",
        f"| Open positions | {summary['n_open_positions']} |",
        "",
        "_Compare to your actual P&L to quantify the discretion penalty._",
        "",
        "---",
        "",
    ]
