"""
decision_journal.py
Persist user decisions against each generated recommendation and score whether
the user's follow-through helped or hurt versus the model's recommendation.

The journal is intentionally local/private:
    data/decision_journal.json
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from src._utils import parse_session_filename, safe_float
from src.backtester import price_at

JOURNAL_VERSION = 1
RECORDED_DECISIONS = {"accepted", "ignored", "modified", "delayed", "watch", "executed"}
ALL_DECISIONS = RECORDED_DECISIONS | {"pending"}
ACTIONABLE_ACTIONS = {"BUY", "ADD", "SELL", "TRIM"}
DEFAULT_HORIZONS = (1, 5, 20, 60)


def empty_journal() -> dict:
    return {
        "version": JOURNAL_VERSION,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "decisions": [],
    }


def load_journal(path: str | Path) -> dict:
    journal_path = Path(path)
    if not journal_path.exists():
        return empty_journal()
    try:
        data = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_journal()
    data.setdefault("version", JOURNAL_VERSION)
    data.setdefault("decisions", [])
    return data


def save_journal(path: str | Path, journal: dict) -> Path:
    journal_path = Path(path)
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal["version"] = JOURNAL_VERSION
    journal["updated_at"] = datetime.now().isoformat(timespec="seconds")
    journal_path.write_text(json.dumps(journal, indent=2, default=str) + "\n", encoding="utf-8")
    return journal_path


def decision_id(session_file: str, ticker: str) -> str:
    return f"{session_file}:{(ticker or '').upper()}"


def seed_from_recommendation_log(
    log_path: str | Path,
    journal_path: str | Path,
    include_holds: bool = False,
) -> list[dict]:
    """Create pending journal rows for recommendations in a saved JSON log."""
    log_path = Path(log_path)
    try:
        payload = json.loads(log_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    parsed = parse_session_filename(log_path.name)
    session_date, session_type = parsed if parsed else ("", "")
    journal = load_journal(journal_path)
    existing = {row.get("id") for row in journal.get("decisions", [])}
    created = []

    for rec in payload.get("recommendations", []) or []:
        ticker = (rec.get("ticker") or "").upper()
        action = (rec.get("action") or "HOLD").upper()
        if not ticker or ticker == "CASH":
            continue
        if action == "HOLD" and not include_holds:
            continue
        row_id = decision_id(log_path.name, ticker)
        if row_id in existing:
            continue
        row = {
            "id": row_id,
            "session_file": log_path.name,
            "session_date": session_date,
            "session_type": session_type,
            "ticker": ticker,
            "recommended_action": action,
            "recommended_shares": rec.get("shares"),
            "recommended_fraction": rec.get("action_fraction"),
            "recommended_amount": rec.get("action_amount") or rec.get("invest_amount_usd"),
            "recommended_amount_currency": rec.get("action_amount_currency", "USD"),
            "conviction": rec.get("conviction"),
            "time_horizon": rec.get("time_horizon", ""),
            "expected_pct": rec.get("net_expected_pct") or rec.get("expected_move_pct"),
            "manual_review_required": bool(rec.get("manual_review_required")),
            "catalyst_verified": bool(rec.get("catalyst_verified")),
            "thesis": rec.get("thesis", ""),
            "user_decision": "pending",
            "actual_action": "",
            "actual_shares": None,
            "actual_price": None,
            "actual_currency": "USD",
            "decision_date": "",
            "execution_date": "",
            "reason": "",
            "notes": "",
            "execution_checklist": _empty_execution_checklist(),
            "execution_checklist_updated_at": "",
            "execution_checklist_notes": "",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        journal["decisions"].append(row)
        existing.add(row_id)
        created.append(row)

    if created:
        save_journal(journal_path, journal)
    return created


def record_decision(
    journal_path: str | Path,
    row_id: str,
    *,
    user_decision: str,
    actual_action: str | None = None,
    actual_shares=None,
    actual_price=None,
    actual_currency: str = "USD",
    decision_date: str | None = None,
    execution_date: str | None = None,
    reason: str = "",
    notes: str = "",
) -> dict:
    """Update one journal row with the user's actual decision/execution."""
    journal = load_journal(journal_path)
    row = next((item for item in journal.get("decisions", []) if item.get("id") == row_id), None)
    if row is None:
        raise ValueError(f"Decision row not found: {row_id}")

    normalized_decision = (user_decision or "").strip().lower()
    if normalized_decision not in ALL_DECISIONS:
        raise ValueError(f"Unsupported decision: {user_decision}")

    row["user_decision"] = normalized_decision
    row["actual_action"] = _default_actual_action(row, actual_action)
    row["actual_shares"] = safe_float(actual_shares)
    row["actual_price"] = safe_float(actual_price)
    row["actual_currency"] = (actual_currency or "USD").upper()
    row["decision_date"] = decision_date or datetime.now().date().isoformat()
    row["execution_date"] = execution_date or row["decision_date"]
    row["reason"] = reason or ""
    row["notes"] = notes or ""
    row["updated_at"] = datetime.now().isoformat(timespec="seconds")
    save_journal(journal_path, journal)
    return row


def record_execution_checklist(
    journal_path: str | Path,
    row_id: str,
    *,
    checklist: dict[str, bool],
    notes: str = "",
) -> dict:
    """Persist the manual execution checklist for one journal row."""
    journal = load_journal(journal_path)
    row = next((item for item in journal.get("decisions", []) if item.get("id") == row_id), None)
    if row is None:
        raise ValueError(f"Decision row not found: {row_id}")
    current = _empty_execution_checklist()
    existing = row.get("execution_checklist")
    if isinstance(existing, dict):
        current.update({key: bool(existing.get(key)) for key in current})
    for key in current:
        if key in checklist:
            current[key] = bool(checklist[key])
    row["execution_checklist"] = current
    row["execution_checklist_updated_at"] = datetime.now().isoformat(timespec="seconds")
    row["execution_checklist_notes"] = notes or row.get("execution_checklist_notes") or ""
    row["updated_at"] = datetime.now().isoformat(timespec="seconds")
    save_journal(journal_path, journal)
    return row


def execution_checklist_status(row: dict) -> dict:
    checklist = _empty_execution_checklist()
    existing = row.get("execution_checklist")
    if isinstance(existing, dict):
        checklist.update({key: bool(existing.get(key)) for key in checklist})
    done = sum(1 for value in checklist.values() if value)
    total = len(checklist)
    return {
        "done": done,
        "total": total,
        "status": "DONE" if done == total else "PENDING" if done else "NOT_STARTED",
        "checklist": checklist,
        "updated_at": row.get("execution_checklist_updated_at") or "",
        "notes": row.get("execution_checklist_notes") or "",
    }


def journal_status(journal: dict) -> dict:
    rows = journal.get("decisions", []) or []
    counts = {key: 0 for key in sorted(ALL_DECISIONS)}
    for row in rows:
        decision = row.get("user_decision") or "pending"
        counts[decision] = counts.get(decision, 0) + 1
    return {
        "total": len(rows),
        "pending": counts.get("pending", 0),
        "recorded": len(rows) - counts.get("pending", 0),
        "by_decision": counts,
        "latest_entries": sorted(
            rows,
            key=lambda row: (row.get("session_date") or "", row.get("ticker") or ""),
            reverse=True,
        )[:20],
    }


def _empty_execution_checklist() -> dict[str, bool]:
    return {
        "quote_confirmed": False,
        "catalyst_checked": False,
        "sizing_checked": False,
        "fee_fx_checked": False,
        "manual_review_accepted": False,
    }


def score_decisions(
    journal: dict,
    *,
    as_of: datetime | None = None,
    horizons: tuple[int, ...] | list[int] = DEFAULT_HORIZONS,
    price_lookup: Callable[[str, str], float | None] = price_at,
    max_decisions: int = 200,
) -> list[dict]:
    """Score recorded decisions over fixed windows from the report date."""
    as_of = as_of or datetime.now()
    recorded = [
        row
        for row in journal.get("decisions", []) or []
        if row.get("user_decision") in RECORDED_DECISIONS and (row.get("recommended_action") or "").upper() in ACTIONABLE_ACTIONS
    ]
    recorded = sorted(recorded, key=lambda row: row.get("session_date") or "", reverse=True)[:max_decisions]

    rows = []
    for row in recorded:
        try:
            start_dt = datetime.strptime(row.get("session_date", ""), "%Y-%m-%d")
        except ValueError:
            continue

        ticker = row.get("ticker")
        if not ticker:
            continue
        start_price = price_lookup(ticker, start_dt.strftime("%Y-%m-%d"))
        if not start_price or start_price <= 0:
            continue

        for horizon in horizons:
            end_dt = start_dt + timedelta(days=int(horizon))
            if end_dt > as_of:
                continue
            end_price = price_lookup(ticker, end_dt.strftime("%Y-%m-%d"))
            if not end_price or end_price <= 0:
                continue

            model_raw = (end_price - start_price) / start_price * 100.0
            recommended_action = (row.get("recommended_action") or "").upper()
            actual_action = (row.get("actual_action") or "").upper()
            user_start_price = _user_start_price(row, start_dt, end_dt, start_price)
            user_raw = (end_price - user_start_price) / user_start_price * 100.0
            model_return = _model_action_return_pct(recommended_action, model_raw)
            user_return = _user_action_return_pct(actual_action, recommended_action, user_raw)

            rows.append(
                {
                    "id": row.get("id"),
                    "ticker": ticker,
                    "session_date": row.get("session_date"),
                    "horizon_days": int(horizon),
                    "recommended_action": recommended_action,
                    "user_decision": row.get("user_decision"),
                    "actual_action": actual_action,
                    "conviction": row.get("conviction"),
                    "raw_move_pct": round(model_raw, 2),
                    "model_action_return_pct": round(model_return, 2),
                    "user_action_return_pct": round(user_return, 2),
                    "decision_delta_pct": round(user_return - model_return, 2),
                    "model_hit": model_return > 0,
                    "user_hit": user_return > 0,
                }
            )
    return rows


def summarize_outcomes(outcomes: list[dict], status: dict) -> dict:
    if not outcomes:
        return {
            "journal": status,
            "n_scored_windows": 0,
            "n_scored_decisions": 0,
            "overall": {
                "model_avg_return_pct": 0.0,
                "user_avg_return_pct": 0.0,
                "avg_decision_delta_pct": 0.0,
                "model_hit_rate": 0.0,
                "user_hit_rate": 0.0,
            },
            "by_user_decision": {},
            "by_recommended_action": {},
            "by_horizon": {},
            "best_user_overrides": [],
            "worst_user_overrides": [],
            "missed_model_winners": [],
        }

    def avg(values: list[float]) -> float:
        return round(sum(values) / len(values), 2) if values else 0.0

    def bucket_stats(rows: list[dict]) -> dict:
        return {
            "n": len(rows),
            "model_avg_return_pct": avg([r["model_action_return_pct"] for r in rows]),
            "user_avg_return_pct": avg([r["user_action_return_pct"] for r in rows]),
            "avg_decision_delta_pct": avg([r["decision_delta_pct"] for r in rows]),
            "model_hit_rate": round(sum(1 for r in rows if r["model_hit"]) / len(rows), 3) if rows else 0.0,
            "user_hit_rate": round(sum(1 for r in rows if r["user_hit"]) / len(rows), 3) if rows else 0.0,
        }

    by_decision = {}
    for decision in sorted({row.get("user_decision") for row in outcomes}):
        by_decision[decision] = bucket_stats([row for row in outcomes if row.get("user_decision") == decision])

    by_action = {}
    for action in sorted({row.get("recommended_action") for row in outcomes}):
        by_action[action] = bucket_stats([row for row in outcomes if row.get("recommended_action") == action])

    # Per-horizon breakdown — keyed by horizon_days as int, sorted ascending.
    # This is what Claude reads downstream to bias time_horizon selection
    # toward the user's strongest window (e.g. "User edge by horizon: 1d -0.3
    # | 5d +1.1 | 20d +3.2 | 60d -1.1 → bias toward 5-20d at conviction ≥7").
    #
    # Rows with missing / 0 / None horizon_days are silently dropped — they
    # carry no signal for this grouping and used to raise TypeError when the
    # field came back as None (legacy rows).
    def _row_horizon(row: dict) -> int:
        raw = row.get("horizon_days")
        try:
            return int(raw) if raw else 0
        except (TypeError, ValueError):
            return 0

    by_horizon: dict[int, dict] = {}
    horizons_seen = sorted({h for h in (_row_horizon(row) for row in outcomes) if h > 0})
    for horizon in horizons_seen:
        bucket = [row for row in outcomes if _row_horizon(row) == horizon]
        if bucket:
            by_horizon[horizon] = bucket_stats(bucket)

    override_rows = [row for row in outcomes if row.get("user_decision") not in {"accepted", "executed"}]
    missed_winners = [
        row for row in override_rows if row.get("recommended_action") in {"BUY", "ADD"} and row.get("model_action_return_pct", 0) > 3
    ]

    return {
        "journal": status,
        "n_scored_windows": len(outcomes),
        "n_scored_decisions": len({row.get("id") for row in outcomes}),
        "overall": bucket_stats(outcomes),
        "by_user_decision": by_decision,
        "by_recommended_action": by_action,
        "by_horizon": by_horizon,
        "best_user_overrides": sorted(override_rows, key=lambda row: row["decision_delta_pct"], reverse=True)[:8],
        "worst_user_overrides": sorted(override_rows, key=lambda row: row["decision_delta_pct"])[:8],
        "missed_model_winners": sorted(missed_winners, key=lambda row: row["model_action_return_pct"], reverse=True)[:8],
    }


def run_scorecard(
    journal_path: str | Path,
    *,
    as_of: datetime | None = None,
    horizons: tuple[int, ...] | list[int] = DEFAULT_HORIZONS,
    price_lookup: Callable[[str, str], float | None] = price_at,
    max_decisions: int = 200,
) -> dict:
    journal = load_journal(journal_path)
    status = journal_status(journal)
    outcomes = score_decisions(
        journal,
        as_of=as_of,
        horizons=horizons,
        price_lookup=price_lookup,
        max_decisions=max_decisions,
    )
    summary = summarize_outcomes(outcomes, status)
    summary["outcomes"] = outcomes
    return summary


def format_for_report(scorecard: dict) -> list[str]:
    journal = (scorecard or {}).get("journal") or {}
    if not journal or journal.get("total", 0) == 0:
        return []

    lines = [
        "## Decision Journal",
        "",
        "_Tracks what you actually did versus what the model recommended._",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Journal entries | {journal.get('total', 0)} |",
        f"| Pending decisions | {journal.get('pending', 0)} |",
        f"| Recorded decisions | {journal.get('recorded', 0)} |",
    ]

    overall = (scorecard or {}).get("overall") or {}
    if scorecard.get("n_scored_windows", 0):
        lines += [
            f"| Scored windows | {scorecard.get('n_scored_windows', 0)} |",
            f"| Model avg action return | {overall.get('model_avg_return_pct', 0):+.2f}% |",
            f"| Your avg action return | {overall.get('user_avg_return_pct', 0):+.2f}% |",
            f"| Avg discretion delta | {overall.get('avg_decision_delta_pct', 0):+.2f}% |",
            f"| Model hit rate | {overall.get('model_hit_rate', 0):.0%} |",
            f"| Your hit rate | {overall.get('user_hit_rate', 0):.0%} |",
        ]
    lines.append("")

    by_decision = scorecard.get("by_user_decision") or {}
    if by_decision:
        lines += [
            "**By your decision:**",
            "",
            "| Decision | n | Model Avg | Your Avg | Delta |",
            "|---|---:|---:|---:|---:|",
        ]
        for decision, stats in by_decision.items():
            lines.append(
                f"| {decision} | {stats['n']} | {stats['model_avg_return_pct']:+.2f}% | "
                f"{stats['user_avg_return_pct']:+.2f}% | {stats['avg_decision_delta_pct']:+.2f}% |"
            )
        lines.append("")

    worst = scorecard.get("worst_user_overrides") or []
    if worst:
        lines += [
            "**Overrides that hurt most:**",
            "",
            "| Ticker | Date | Rec | Your Decision | Horizon | Delta |",
            "|---|---|---|---|---:|---:|",
        ]
        for row in worst[:5]:
            lines.append(
                f"| {row['ticker']} | {row['session_date']} | {row['recommended_action']} | "
                f"{row['user_decision']} | {row['horizon_days']}d | {row['decision_delta_pct']:+.2f}% |"
            )
        lines.append("")

    if journal.get("pending", 0):
        lines.append("_Record pending decisions in the UI or `python -m src.decision_journal` after trading._")
        lines.append("")

    lines += ["---", ""]
    return lines


def _default_actual_action(row: dict, actual_action: str | None) -> str:
    if actual_action:
        return actual_action.strip().upper()
    decision = row.get("user_decision")
    rec_action = (row.get("recommended_action") or "HOLD").upper()
    if decision in {"accepted", "executed"}:
        return rec_action
    if decision in {"ignored", "delayed", "watch"}:
        return "HOLD" if rec_action in {"SELL", "TRIM"} else "NONE"
    if decision == "modified":
        return rec_action
    return ""


def _model_action_return_pct(action: str, raw_move_pct: float) -> float:
    if action in {"SELL", "TRIM"}:
        return -raw_move_pct
    return raw_move_pct


def _user_action_return_pct(actual_action: str, recommended_action: str, raw_move_pct: float) -> float:
    if actual_action in {"SELL", "TRIM"}:
        return -raw_move_pct
    if actual_action in {"BUY", "ADD", "HOLD"}:
        return raw_move_pct
    if recommended_action in {"SELL", "TRIM"}:
        return raw_move_pct
    return 0.0


def _user_start_price(row: dict, session_dt: datetime, end_dt: datetime, fallback_price: float) -> float:
    actual_price = safe_float(row.get("actual_price"))
    if not actual_price or actual_price <= 0:
        return fallback_price
    actual_action = (row.get("actual_action") or "").upper()
    if actual_action not in ACTIONABLE_ACTIONS:
        return fallback_price
    try:
        execution_dt = datetime.strptime(row.get("execution_date") or row.get("decision_date") or "", "%Y-%m-%d")
    except ValueError:
        execution_dt = session_dt
    if session_dt <= execution_dt <= end_dt:
        return actual_price
    return fallback_price


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Manage the local decision journal.")
    parser.add_argument("--journal", default="data/decision_journal.json", help="Path to decision journal JSON")
    parser.add_argument("--seed-log", help="Seed pending rows from a recommendation JSON log")
    parser.add_argument("--score", action="store_true", help="Print the current decision scorecard")
    parser.add_argument("--record-id", help="Journal row id to update, e.g. 20260510_2011_afternoon.json:SOXL")
    parser.add_argument("--decision", choices=sorted(ALL_DECISIONS), help="User decision")
    parser.add_argument("--actual-action", choices=["BUY", "ADD", "HOLD", "TRIM", "SELL", "NONE"])
    parser.add_argument("--shares")
    parser.add_argument("--price")
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--reason", default="")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    if args.seed_log:
        rows = seed_from_recommendation_log(args.seed_log, args.journal)
        print(f"Seeded {len(rows)} pending decision(s).")
    if args.record_id:
        if not args.decision:
            parser.error("--record-id requires --decision")
        row = record_decision(
            args.journal,
            args.record_id,
            user_decision=args.decision,
            actual_action=args.actual_action,
            actual_shares=args.shares,
            actual_price=args.price,
            actual_currency=args.currency,
            reason=args.reason,
            notes=args.notes,
        )
        print(f"Recorded {row['id']} as {row['user_decision']} / {row.get('actual_action')}.")
    if args.score or not any([args.seed_log, args.record_id]):
        card = run_scorecard(args.journal)
        status = card.get("journal") or {}
        overall = card.get("overall") or {}
        print(f"Journal: {status.get('total', 0)} entries, {status.get('pending', 0)} pending, {status.get('recorded', 0)} recorded")
        print(
            f"Scored windows: {card.get('n_scored_windows', 0)} | "
            f"model avg {overall.get('model_avg_return_pct', 0):+.2f}% | "
            f"your avg {overall.get('user_avg_return_pct', 0):+.2f}% | "
            f"delta {overall.get('avg_decision_delta_pct', 0):+.2f}%"
        )
