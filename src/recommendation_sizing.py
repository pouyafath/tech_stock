"""Deterministic trade-size helpers for rendered recommendations."""
from __future__ import annotations

from copy import deepcopy


DEFAULT_TRIM_FRACTION = 0.30


def apply_trade_sizes(
    recommendation: dict,
    portfolio: dict | None,
    market_data: dict | None = None,
    default_trim_fraction: float = DEFAULT_TRIM_FRACTION,
) -> dict:
    """Populate deterministic share/fraction fields for SELL/TRIM recommendations."""
    out = deepcopy(recommendation or {})
    positions = _positions_by_ticker((portfolio or {}).get("holdings") or [])
    market_data = market_data or {}

    recs = out.get("recommendations") or []
    for rec in recs:
        _populate_rec_size(rec, positions, market_data, default_trim_fraction)

    rec_by_ticker = {rec.get("ticker"): rec for rec in recs if rec.get("ticker")}
    for priority in out.get("priority_actions") or []:
        ticker = priority.get("ticker")
        rec = rec_by_ticker.get(ticker)
        if rec:
            for key in (
                "shares",
                "action_fraction",
                "position_shares",
                "action_amount",
                "action_amount_currency",
                "action_size_label",
            ):
                if rec.get(key) is not None:
                    priority[key] = rec[key]
        else:
            _populate_rec_size(priority, positions, market_data, default_trim_fraction)

    return out


def _positions_by_ticker(holdings: list[dict]) -> dict[str, dict]:
    positions: dict[str, dict] = {}
    for holding in holdings:
        ticker = holding.get("ticker")
        quantity = _to_float(holding.get("quantity"))
        if not ticker or not quantity:
            continue
        position = positions.setdefault(
            ticker,
            {
                "quantity": 0.0,
                "market_value": 0.0,
                "market_value_currency": holding.get("market_value_currency") or holding.get("market_currency"),
                "market_price": None,
                "market_currency": holding.get("market_currency") or holding.get("market_value_currency"),
            },
        )
        position["quantity"] += quantity
        value = _to_float(holding.get("market_value"))
        if value:
            position["market_value"] += value
            position["market_value_currency"] = holding.get("market_value_currency") or position["market_value_currency"]
        price = _to_float(holding.get("market_price"))
        if price:
            position["market_price"] = price
            position["market_currency"] = holding.get("market_currency") or position["market_currency"]
    return positions


def _populate_rec_size(
    rec: dict,
    positions: dict[str, dict],
    market_data: dict,
    default_trim_fraction: float,
) -> None:
    action = (rec.get("action") or "").upper()
    if action not in {"SELL", "TRIM"}:
        return
    ticker = rec.get("ticker")
    position = positions.get(ticker)
    if not position:
        return
    quantity = position.get("quantity") or 0.0
    if quantity <= 0:
        return

    fraction = 1.0 if action == "SELL" else _trim_fraction(rec, default_trim_fraction)
    shares = min(quantity, quantity * fraction)
    rec["position_shares"] = _round_shares(quantity)
    rec["action_fraction"] = round(fraction, 4)
    rec["shares"] = _round_shares(shares)

    price, currency = _execution_price(ticker, position, market_data)
    if price:
        rec["action_amount"] = round(shares * price, 2)
        rec["action_amount_currency"] = currency or "USD"
    rec["action_size_label"] = _size_label(rec)


def _trim_fraction(rec: dict, default_trim_fraction: float) -> float:
    for plan_key in ("exit_plan", "entry_plan"):
        plan = rec.get(plan_key) or []
        if not plan:
            continue
        first = plan[0] if isinstance(plan, list) else None
        if isinstance(first, dict):
            fraction = _to_float(first.get("fraction"))
            if fraction and 0 < fraction <= 1:
                return fraction
    fraction = _to_float(rec.get("action_fraction")) or default_trim_fraction
    return max(0.01, min(1.0, fraction))


def _execution_price(ticker: str, position: dict, market_data: dict) -> tuple[float | None, str | None]:
    md = market_data.get(ticker) or {}
    price = _to_float(md.get("current_price"))
    currency = md.get("currency")
    if price:
        return price, currency
    price = _to_float(position.get("market_price"))
    currency = position.get("market_currency")
    if price:
        return price, currency
    quantity = position.get("quantity") or 0
    value = position.get("market_value") or 0
    if quantity and value:
        return value / quantity, position.get("market_value_currency")
    return None, currency


def _size_label(rec: dict) -> str:
    shares = rec.get("shares")
    if shares is None:
        return ""
    pct = (rec.get("action_fraction") or 0) * 100
    label = f"{shares:g} sh ({pct:.0f}% of position)"
    amount = rec.get("action_amount")
    currency = rec.get("action_amount_currency")
    if amount is not None:
        label += f" ≈ ${amount:,.0f} {currency or 'USD'}"
    return label


def _to_float(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_shares(value: float) -> float:
    rounded = round(float(value), 4)
    return int(rounded) if rounded.is_integer() else rounded
