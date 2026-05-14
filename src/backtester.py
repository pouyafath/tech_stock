"""
backtester.py
Evaluate past recommendations against actual market outcomes.

Reads every JSON log in data/recommendations_log/ and compares each
recommendation's target/predicted move to what actually happened over the
next 1-2 weeks / 1-3 months (depending on time_horizon).

Summary is fed back into the Claude prompt so the model can calibrate its
own conviction scores over time.
"""

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

from src._utils import parse_session_filename, safe_float
from src.fee_calculator import calculate_round_trip_cost
from src.market_data import price_at

# Approximate horizon windows in calendar days.
HORIZON_DAYS = {
    "intraday": 1,
    "next session": 1,
    "1-3 trading days": 5,
    "1-2 weeks": 10,
    "1-3 months": 60,
    "3-6 months": 120,
    "6-12 months": 240,
    "12-36 months": 540,
}

# Conviction buckets we report on (6 = threshold for trading recs).
CONVICTION_BUCKETS = [6, 7, 8, 9, 10]


def _session_date_from_filename(filename: str) -> str | None:
    parsed = parse_session_filename(filename)
    return parsed[0] if parsed else None


def load_all_recommendations(log_dir: str | Path) -> list[dict]:
    """
    Read every JSON file in `log_dir` and return a flat list of recommendation
    dicts, each enriched with `session_date` (YYYY-MM-DD) inferred from the
    filename.

    Each rec dict keeps all its original fields plus:
      session_date: str
      session_file: str (filename only, for traceability)
    """
    log_dir = Path(log_dir)
    if not log_dir.exists():
        return []

    all_recs = []
    for path in sorted(log_dir.glob("*.json")):
        session_date = _session_date_from_filename(path.name)
        if not session_date:
            continue
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue

        for rec in data.get("recommendations", []) or []:
            if not rec.get("ticker"):
                continue
            rec_copy = dict(rec)
            rec_copy["session_date"] = session_date
            rec_copy["session_file"] = path.name
            all_recs.append(rec_copy)

    return all_recs


def load_trade_history(csv_path: str | Path) -> list[dict]:
    """
    Parse data/trade_history.csv — the user's manually-logged executions.
    Columns: date,ticker,action,shares,price_cad,followed_recommendation,notes
    Returns list of dicts, or [] if the file is missing/empty.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        return []

    trades = []
    try:
        with open(csv_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not row.get("date") or not row.get("ticker"):
                    continue
                trades.append({
                    "date": row["date"].strip(),
                    "ticker": row["ticker"].strip(),
                    "action": row.get("action", "").strip().upper(),
                    "shares": safe_float(row.get("shares", "")),
                    "price_cad": safe_float(row.get("price_cad", "")),
                    "followed_recommendation": row.get("followed_recommendation", "").strip().lower() in ("y", "yes", "true", "1"),
                    "notes": row.get("notes", "").strip(),
                })
    except (OSError, csv.Error):
        return []

    return trades


def _horizon_days(horizon: str) -> int:
    """Map a Claude time_horizon string to calendar-day count."""
    if not horizon:
        return 10
    key = horizon.strip().lower()
    return HORIZON_DAYS.get(key, 10)


def _is_rec_mature(rec: dict, as_of: datetime) -> bool:
    """True if enough time has passed to evaluate this recommendation."""
    session_date = rec.get("session_date")
    if not session_date:
        return False
    try:
        rec_dt = datetime.strptime(session_date, "%Y-%m-%d")
    except ValueError:
        return False
    days = _horizon_days(rec.get("time_horizon", ""))
    return (as_of - rec_dt).days >= days


def evaluate_recommendations(recs: list[dict], as_of: datetime = None) -> list[dict]:
    """
    For each recommendation that has passed its time horizon, compute the
    actual realized return using yfinance historical closes.

    Returns list of result dicts:
      {
        ticker, session_date, action, conviction, time_horizon,
        expected_pct, actual_pct, hit: bool (actual direction matched expected)
      }
    """
    if as_of is None:
        as_of = datetime.now()

    results = []
    for rec in recs:
        if not _is_rec_mature(rec, as_of):
            continue

        ticker = rec.get("ticker")
        action = rec.get("action", "HOLD")
        session_date = rec["session_date"]
        horizon_days = _horizon_days(rec.get("time_horizon", ""))

        # Skip HOLD — can't judge a non-action against price
        if action == "HOLD":
            continue

        try:
            start_dt = datetime.strptime(session_date, "%Y-%m-%d")
        except ValueError:
            continue
        end_dt = start_dt + timedelta(days=horizon_days)
        if end_dt > as_of:
            end_dt = as_of

        start_price = price_at(ticker, start_dt.strftime("%Y-%m-%d"))
        end_price = price_at(ticker, end_dt.strftime("%Y-%m-%d"))
        if not start_price or not end_price or start_price <= 0:
            continue

        raw_move_pct = (end_price - start_price) / start_price * 100.0

        # For SELL/TRIM, a price drop is a "win" (avoided loss)
        if action in ("SELL", "TRIM"):
            actual_for_action = -raw_move_pct
        else:  # BUY, ADD
            actual_for_action = raw_move_pct

        # Subtract round-trip fees + estimated slippage so the reported edge is
        # what the user would actually have captured.  Slippage is half the
        # one-way bid-ask (a market-order tax).  Without this, a 0.5% Sonnet
        # edge can be entirely consumed by midcap costs.
        try:
            fees = calculate_round_trip_cost(ticker, notional_usd=1000.0)
            round_trip_cost_pct = fees.get("total_pct", 0.0)
            slippage_pct = fees.get("bid_ask_pct_one_way", 0.0) * 0.5
        except (KeyError, ValueError):
            round_trip_cost_pct = 0.0
            slippage_pct = 0.0
        net_actual_for_action = actual_for_action - round_trip_cost_pct - slippage_pct

        expected_pct = rec.get("net_expected_pct") or rec.get("expected_move_pct") or 0.0
        if action in ("SELL", "TRIM") and expected_pct < 0:
            # User expects the stock to drop; align sign with "our bet paid off"
            expected_for_action = -expected_pct
        else:
            expected_for_action = expected_pct

        # Hit-rate now uses the after-fee return so we don't reward marginal moves
        # that lose money after slippage.
        hit = net_actual_for_action > 0

        results.append({
            "ticker": ticker,
            "session_date": session_date,
            "action": action,
            "conviction": rec.get("conviction"),
            "time_horizon": rec.get("time_horizon", ""),
            "expected_pct": round(float(expected_for_action), 2),
            # actual_pct is now the NET return (after fees + slippage) for honesty
            "actual_pct": round(float(net_actual_for_action), 2),
            # gross_pct preserves the pre-fee number for calibration / debugging
            "gross_pct": round(float(actual_for_action), 2),
            "fee_drag_pct": round(float(round_trip_cost_pct + slippage_pct), 4),
            "start_price": start_price,
            "end_price": end_price,
            "hit": hit,
        })

    return results


def _avg_and_hit_rate(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0, "avg_return_pct": 0.0, "hit_rate": 0.0}
    actuals = [r["actual_pct"] for r in rows]
    hits = [1 for r in rows if r.get("hit")]
    return {
        "n": len(rows),
        "avg_return_pct": round(sum(actuals) / len(actuals), 2),
        "hit_rate": round(len(hits) / len(rows), 3),
    }


def summarize(results: list[dict]) -> dict:
    """
    Summarize evaluation results into per-action and per-conviction stats.

    Returns:
      {
        "n_samples": int,
        "avg_return_by_action": {ACTION: {n, avg_return_pct, hit_rate}},
        "avg_return_by_conviction": {6: {...}, 7: {...}, ...},
        "overall": {n, avg_return_pct, hit_rate},
      }
    """
    if not results:
        return {
            "n_samples": 0,
            "avg_return_by_action": {},
            "avg_return_by_conviction": {},
            "avg_return_by_ticker": {},
            "recent_realized_examples": [],
            "overall": {"n": 0, "avg_return_pct": 0.0, "hit_rate": 0.0},
        }

    by_action = {}
    for action in ("BUY", "ADD", "SELL", "TRIM"):
        rows = [r for r in results if r["action"] == action]
        if rows:
            by_action[action] = _avg_and_hit_rate(rows)

    by_conv = {}
    for conv in CONVICTION_BUCKETS:
        rows = [r for r in results if r.get("conviction") == conv]
        if rows:
            by_conv[conv] = _avg_and_hit_rate(rows)

    by_ticker = {}
    for ticker in sorted({r.get("ticker") for r in results if r.get("ticker")}):
        rows = [r for r in results if r.get("ticker") == ticker]
        if rows:
            by_ticker[ticker] = _avg_and_hit_rate(rows)
    by_ticker = dict(
        sorted(
            by_ticker.items(),
            key=lambda item: (-item[1]["n"], item[0]),
        )
    )

    recent_examples = sorted(
        results,
        key=lambda row: (row.get("session_date") or "", row.get("ticker") or ""),
        reverse=True,
    )[:8]

    # Conviction-stratified sizing multipliers — feed actual hit rates back into
    # position sizing.  Multiplier formula (Kelly-lite, dampened):
    #     mult = clamp(0.4, hit_rate * (1 + avg_return / 10), 1.4)
    # Applied to invest_amount_usd downstream of Rule 18.  Only computed when
    # the bucket has ≥3 mature samples — otherwise falls back to 1.0.
    sizing_multipliers = {}
    for conv, stats in by_conv.items():
        if stats.get("n", 0) < 3:
            continue
        hit_rate = float(stats.get("hit_rate", 0.0))
        avg_return = float(stats.get("avg_return_pct", 0.0))
        raw = hit_rate * (1.0 + avg_return / 10.0)
        sizing_multipliers[int(conv)] = max(0.4, min(raw, 1.4))

    return {
        "n_samples": len(results),
        "avg_return_by_action": by_action,
        "avg_return_by_conviction": by_conv,
        "avg_return_by_ticker": by_ticker,
        "sizing_multipliers_by_conviction": sizing_multipliers,
        "recent_realized_examples": recent_examples,
        "overall": _avg_and_hit_rate(results),
    }


def run_backtest(log_dir: str | Path, as_of: datetime = None) -> dict:
    """Convenience wrapper: load → evaluate → summarize."""
    recs = load_all_recommendations(log_dir)
    results = evaluate_recommendations(recs, as_of=as_of)
    summary = summarize(results)
    summary["evaluated_results"] = results  # keep raw rows for optional rendering
    return summary


if __name__ == "__main__":
    import sys
    log_dir = sys.argv[1] if len(sys.argv) > 1 else "data/recommendations_log"
    summary = run_backtest(log_dir)
    print(f"Evaluated {summary['n_samples']} mature recommendations")
    overall = summary["overall"]
    print(f"Overall: n={overall['n']}  avg={overall['avg_return_pct']:+.2f}%  hit_rate={overall['hit_rate']:.0%}")

    print("\nBy action:")
    for action, stats in summary["avg_return_by_action"].items():
        print(f"  {action:5s} n={stats['n']:3d}  avg={stats['avg_return_pct']:+.2f}%  win={stats['hit_rate']:.0%}")

    print("\nBy conviction:")
    for conv in sorted(summary["avg_return_by_conviction"].keys()):
        stats = summary["avg_return_by_conviction"][conv]
        print(f"  {conv}  n={stats['n']:3d}  avg={stats['avg_return_pct']:+.2f}%  win={stats['hit_rate']:.0%}")
