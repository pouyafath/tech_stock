"""
fee_calculator.py
Wealthsimple Premium + USD account fee model.
Zero commission, zero FX spread (USD account), tiered bid-ask, small regulatory fee.
"""

import json
from pathlib import Path

SETTINGS_PATH = Path(__file__).parent.parent / "config" / "settings.json"


def load_settings() -> dict:
    with open(SETTINGS_PATH) as f:
        return json.load(f)


def get_bid_ask_pct(ticker: str, settings: dict) -> float:
    """Return estimated bid-ask spread (one-way) based on ticker liquidity tier."""
    megacaps = [t.upper() for t in settings.get("megacap_tickers", [])]
    ticker_upper = ticker.upper().replace(".TO", "")

    if ticker_upper in megacaps:
        return settings["fee_model"]["bid_ask_megacap_pct"]
    elif ticker_upper in ["PLTR", "SMCI", "ARM", "IONQ", "SHOP", "CSU", "OTEX", "KXS"]:
        return settings["fee_model"]["bid_ask_smallcap_pct"]
    else:
        return settings["fee_model"]["bid_ask_midcap_pct"]


def calculate_round_trip_cost(
    ticker: str,
    notional_usd: float = 1000.0,
    settings: dict = None,
) -> dict:
    """
    Calculate the true round-trip trading cost for a given ticker and notional.

    Returns a dict with:
        - commission_usd: always 0 for Wealthsimple Premium
        - fx_spread_usd: always 0 for USD account
        - bid_ask_usd: estimated bid-ask cost (buy + sell)
        - regulatory_usd: SEC/FINRA fees (buy + sell)
        - total_usd: sum of all costs
        - total_pct: total cost as % of notional
        - hurdle_pct: min expected move needed to profit (total_pct * 2 for round-trip)
    """
    if settings is None:
        settings = load_settings()

    fm = settings["fee_model"]

    commission = fm["commission"]
    fx_spread = fm["fx_spread_pct"] / 100 * notional_usd  # 0 for Premium USD

    # Bid-ask is paid on both entry and exit
    ba_pct = get_bid_ask_pct(ticker, settings)
    bid_ask = (ba_pct / 100) * notional_usd * 2  # round-trip

    # Regulatory: ~$0.03 per US trade (buy + sell), $0 for CAD
    is_canadian = ticker.upper().endswith(".TO")
    reg_per_trade = fm["regulatory_per_cad_trade_usd"] if is_canadian else fm["regulatory_per_us_trade_usd"]
    regulatory = reg_per_trade * 2  # buy + sell

    total_usd = commission + fx_spread + bid_ask + regulatory
    total_pct = (total_usd / notional_usd) * 100

    return {
        "ticker": ticker,
        "notional_usd": notional_usd,
        "commission_usd": commission,
        "fx_spread_usd": fx_spread,
        "bid_ask_usd": round(bid_ask, 4),
        "bid_ask_pct_one_way": ba_pct,
        "regulatory_usd": round(regulatory, 4),
        "total_usd": round(total_usd, 4),
        "total_pct": round(total_pct, 4),
        "hurdle_pct": round(total_pct, 4),  # must beat this to profit
    }


def build_fee_snapshot(tickers: list, notional_usd: float = 1000.0) -> dict:
    """Build a fee snapshot dict for all tickers."""
    settings = load_settings()
    return {
        ticker: calculate_round_trip_cost(ticker, notional_usd, settings)
        for ticker in tickers
    }


if __name__ == "__main__":
    tickers = ["NVDA", "PLTR", "SHOP.TO", "MSFT"]
    snapshot = build_fee_snapshot(tickers)
    for t, fees in snapshot.items():
        print(f"{t}: hurdle={fees['hurdle_pct']}%, total_cost=${fees['total_usd']} on ${fees['notional_usd']} notional")
