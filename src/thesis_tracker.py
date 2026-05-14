"""
thesis_tracker.py — track every BUY/ADD's original thesis and force exit
when it has not materialized after a configurable number of review cycles.

Persistent state:  data/thesis_log.json
  Format: {
    "AAPL_2026-04-01": {
      "ticker": "AAPL",
      "entry_date": "2026-04-01",
      "entry_session": "20260401_0930_morning.json",
      "original_thesis": "Strong AI iPhone catalyst before Q4 launch.",
      "original_conviction": 8,
      "original_action": "BUY",
      "review_log": [
        {"review_date": "2026-07-01", "verdict": "partial",
         "current_conviction": 7, "current_action": "HOLD",
         "notes": "Catalyst delayed but still in play."},
        ...
      ],
      "force_exit_after": 4,           # configurable per-thesis
      "force_exit_after_days": 90,     # 90d ≈ quarterly review
    }
  }

The tracker:
  1. record_new_entry()         — called when a ticker enters as BUY/ADD with no
                                   active thesis log (i.e. this is a new position).
  2. quarterly_review_due()     — returns thesis IDs whose last review was
                                   >= force_exit_after_days ago.
  3. evaluate_due()             — heuristic comparison of current vs original;
                                   classifies as 'materialized', 'partial',
                                   'not_yet', or 'invalidated'.
  4. force_exit_candidates()    — IDs with N consecutive 'not_yet' reviews.

The Claude prompt sees a "THESIS DECAY" block listing positions due for
review and any forced exits.  apply_quality_gates enforces forced exits
similarly to the 2-year stale rule.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

DEFAULT_REVIEW_INTERVAL_DAYS = 90    # ~quarterly
DEFAULT_FORCE_EXIT_AFTER = 4          # 4 quarters of "not yet" → force exit


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def _thesis_key(ticker: str, entry_date: str) -> str:
    return f"{ticker}_{entry_date}"


def _coerce_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def record_new_entries(
    recommendation: dict,
    log_path: Path | str,
    session_file: str,
    holdings_pre_run: Iterable[dict] | None = None,
    today: date | None = None,
) -> list[dict]:
    """Record fresh thesis entries for any BUY/ADD on a ticker not yet in the log.

    `holdings_pre_run` lets the caller skip recording if the ticker was already
    held (so a follow-up ADD doesn't replace the original thesis). When omitted,
    we only check the thesis log.

    Returns the list of newly-recorded thesis dicts.
    """
    log_path = Path(log_path)
    today = today or date.today()
    today_iso = today.isoformat()
    state = _load(log_path)
    existing_tickers = {entry["ticker"] for entry in state.values()}
    held_tickers = {h.get("ticker") for h in holdings_pre_run or [] if h.get("ticker")}

    recorded = []
    for rec in recommendation.get("recommendations", []) or []:
        action = (rec.get("action") or "").upper()
        if action != "BUY":
            # ADD on a position we already hold should not start a new thesis
            continue
        ticker = rec.get("ticker")
        if not ticker or ticker == "CASH":
            continue
        if ticker in existing_tickers or ticker in held_tickers:
            continue
        entry = {
            "ticker":              ticker,
            "entry_date":          today_iso,
            "entry_session":       session_file,
            "original_thesis":     rec.get("thesis", ""),
            "original_conviction": rec.get("conviction", 0),
            "original_action":     action,
            "review_log":          [],
            "force_exit_after":    DEFAULT_FORCE_EXIT_AFTER,
            "force_exit_after_days": DEFAULT_REVIEW_INTERVAL_DAYS,
        }
        state[_thesis_key(ticker, today_iso)] = entry
        recorded.append(entry)

    if recorded:
        _save(log_path, state)
    return recorded


def evaluate_progress(
    thesis_entry: dict,
    current_rec: dict | None,
    current_holding: dict | None,
) -> str:
    """Classify how the original thesis is progressing.

    Heuristics (deterministic, transparent):
        - 'invalidated' — current rec is SELL or position closed (no holding)
        - 'materialized' — original was BUY/ADD with conviction X, now HOLD-add_on_dip
                           or trim-protect-gains, AND current_holding is up >= 15%
        - 'partial' — current rec exists with conviction within ±1 of original
        - 'not_yet' — current rec downgraded, or position underwater

    Used both by force_exit_candidates and the optional 'verdict' field.
    """
    if current_holding is None or float(current_holding.get("quantity", 0) or 0) <= 0:
        return "invalidated"

    pnl_pct = current_holding.get("unrealized_pnl_pct")
    pnl_pct = float(pnl_pct) if pnl_pct is not None else 0.0

    if current_rec is None:
        # No new recommendation, we still hold it — partial unless underwater
        return "not_yet" if pnl_pct < -5 else "partial"

    action = (current_rec.get("action") or "HOLD").upper()
    if action == "SELL":
        return "invalidated"

    if pnl_pct >= 15:
        return "materialized"

    try:
        delta = int(current_rec.get("conviction", 0)) - int(thesis_entry.get("original_conviction", 0))
    except (TypeError, ValueError):
        delta = 0
    if abs(delta) <= 1 and pnl_pct >= 0:
        return "partial"
    return "not_yet"


def quarterly_reviews_due(
    log_path: Path | str,
    today: date | None = None,
) -> list[dict]:
    """Return thesis entries whose last review was >= interval days ago."""
    log_path = Path(log_path)
    today = today or date.today()
    state = _load(log_path)
    out = []
    for key, entry in state.items():
        interval = entry.get("force_exit_after_days", DEFAULT_REVIEW_INTERVAL_DAYS)
        last_dt_str = entry["entry_date"]
        if entry.get("review_log"):
            last_dt_str = entry["review_log"][-1].get("review_date", last_dt_str)
        last_dt = _coerce_date(last_dt_str) or today
        if (today - last_dt).days >= interval:
            entry_with_key = dict(entry)
            entry_with_key["key"] = key
            out.append(entry_with_key)
    return out


def force_exit_candidates(
    log_path: Path | str,
) -> list[dict]:
    """Return thesis entries with N+ consecutive 'not_yet' reviews."""
    log_path = Path(log_path)
    state = _load(log_path)
    out = []
    for key, entry in state.items():
        threshold = entry.get("force_exit_after", DEFAULT_FORCE_EXIT_AFTER)
        log = entry.get("review_log") or []
        if len(log) < threshold:
            continue
        consecutive = 0
        for review in reversed(log):
            if review.get("verdict") == "not_yet":
                consecutive += 1
            else:
                break
        if consecutive >= threshold:
            entry_with_key = dict(entry)
            entry_with_key["key"] = key
            out.append(entry_with_key)
    return out


def append_review(
    log_path: Path | str,
    key: str,
    verdict: str,
    current_conviction: int | None,
    current_action: str | None,
    notes: str = "",
    today: date | None = None,
) -> None:
    """Append a review entry to a thesis log."""
    log_path = Path(log_path)
    today = today or date.today()
    state = _load(log_path)
    if key not in state:
        return
    state[key].setdefault("review_log", []).append({
        "review_date":        today.isoformat(),
        "verdict":            verdict,
        "current_conviction": current_conviction,
        "current_action":     current_action,
        "notes":              notes,
    })
    _save(log_path, state)


def remove_thesis(log_path: Path | str, key: str) -> None:
    """Drop a thesis entry (called when position is closed)."""
    log_path = Path(log_path)
    state = _load(log_path)
    if key in state:
        del state[key]
        _save(log_path, state)


def format_for_prompt(
    due_for_review: list[dict],
    forced_exits: list[dict],
) -> str:
    """Render a Claude-friendly THESIS DECAY block."""
    if not due_for_review and not forced_exits:
        return ""
    lines = ["THESIS DECAY (each BUY's original thesis is reviewed every 90 days):"]
    if forced_exits:
        lines.append("  ⚠ FORCED EXIT (4+ consecutive 'not_yet' reviews — strategy rule):")
        for entry in forced_exits:
            lines.append(
                f"    - {entry['ticker']}: entered {entry['entry_date']} at conviction "
                f"{entry.get('original_conviction', '?')} — output SELL."
            )
    if due_for_review:
        lines.append("  Due for review (assess thesis progress, output verdict in your thesis text):")
        for entry in due_for_review[:8]:
            lines.append(
                f"    - {entry['ticker']}: entered {entry['entry_date']}, "
                f"original thesis: \"{entry.get('original_thesis', '')[:140]}\""
            )
    return "\n".join(lines)


def update_reviews_from_recommendation(
    log_path: Path | str,
    recommendation: dict,
    holdings_by_ticker: dict,
    today: date | None = None,
) -> None:
    """For every thesis due for review, append a verdict based on this session.

    Called *after* recommendation is finalized (so we use the gated output).
    """
    log_path = Path(log_path)
    today = today or date.today()
    due = quarterly_reviews_due(log_path, today=today)
    if not due:
        return
    recs_by_ticker = {
        (r.get("ticker") or "").upper(): r
        for r in recommendation.get("recommendations") or []
    }
    for entry in due:
        ticker = entry["ticker"]
        rec = recs_by_ticker.get(ticker)
        holding = holdings_by_ticker.get(ticker)
        verdict = evaluate_progress(entry, rec, holding)
        append_review(
            log_path,
            entry["key"],
            verdict,
            current_conviction=(rec or {}).get("conviction"),
            current_action=(rec or {}).get("action"),
            notes="auto-evaluated",
            today=today,
        )
