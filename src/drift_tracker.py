"""
drift_tracker.py
Detects significant changes between this session's recommendations and the
prior session — flips in action (BUY → SELL), large conviction jumps, sign
flips on net_expected_pct, etc.

Fed back into the Claude prompt so the model can either justify drift or
self-correct (and into the markdown report so the user sees it).
"""

import json
from pathlib import Path

from src._utils import parse_session_filename


def get_previous_session(log_dir: str | Path) -> dict | None:
    """
    Return the most recently-saved recommendation JSON _before_ the current run.
    Treats the newest file as "current" and returns the second-newest.

    Returns the parsed JSON dict (with extra `_session_file` key) or None.
    """
    log_dir = Path(log_dir)
    if not log_dir.exists():
        return None

    files = sorted(
        [p for p in log_dir.glob("*.json") if parse_session_filename(p.name) is not None],
        key=lambda p: p.name,
        reverse=True,
    )
    if len(files) < 2:
        return None

    prev_path = files[1]
    try:
        with open(prev_path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    data["_session_file"] = prev_path.name
    return data


def _recs_by_ticker(recommendation: dict) -> dict:
    """Index recommendations by ticker for quick lookup."""
    out = {}
    for rec in recommendation.get("recommendations", []) or []:
        ticker = rec.get("ticker")
        if ticker:
            out[ticker] = rec
    return out


def compute_drift(
    current: dict,
    previous: dict | None,
    conviction_delta_threshold: int = 2,
) -> list[dict]:
    """
    Compare current recommendations to previous session's, return list of
    drift events. Each event is a dict:
      {
        "ticker": str,
        "drift_type": "action_flip" | "conviction_jump" | "sign_flip" |
                      "new_ticker" | "dropped_ticker",
        "was": {"action": str, "conviction": int, "net_expected_pct": float} | None,
        "now": {"action": str, "conviction": int, "net_expected_pct": float} | None,
      }

    Returns [] if no previous session is available.
    """
    if not previous:
        return []

    current_by = _recs_by_ticker(current)
    prev_by = _recs_by_ticker(previous)

    drift = []

    # Tickers in both sessions — check action/conviction/sign flips
    for ticker, now_rec in current_by.items():
        if ticker not in prev_by:
            drift.append({
                "ticker": ticker,
                "drift_type": "new_ticker",
                "was": None,
                "now": _summary(now_rec),
            })
            continue

        was_rec = prev_by[ticker]
        was_summary = _summary(was_rec)
        now_summary = _summary(now_rec)

        was_action = (was_rec.get("action") or "").upper()
        now_action = (now_rec.get("action") or "").upper()
        was_conv = was_rec.get("conviction") or 0
        now_conv = now_rec.get("conviction") or 0
        was_net = was_rec.get("net_expected_pct") or 0
        now_net = now_rec.get("net_expected_pct") or 0

        # Action flip: HOLD ↔ trade is interesting; trade ↔ trade is more so
        if was_action != now_action and was_action and now_action:
            drift.append({
                "ticker": ticker,
                "drift_type": "action_flip",
                "was": was_summary,
                "now": now_summary,
            })
            continue  # action flip is the dominant signal — skip lesser checks

        # Conviction jump (only when action stayed the same)
        if abs(now_conv - was_conv) >= conviction_delta_threshold:
            drift.append({
                "ticker": ticker,
                "drift_type": "conviction_jump",
                "was": was_summary,
                "now": now_summary,
            })
            continue

        # Sign flip on net_expected_pct (e.g. +5% → -3%)
        if was_net and now_net and (was_net > 0) != (now_net > 0):
            drift.append({
                "ticker": ticker,
                "drift_type": "sign_flip",
                "was": was_summary,
                "now": now_summary,
            })

    # Tickers dropped from prior session
    for ticker, was_rec in prev_by.items():
        if ticker not in current_by:
            drift.append({
                "ticker": ticker,
                "drift_type": "dropped_ticker",
                "was": _summary(was_rec),
                "now": None,
            })

    return drift


def _summary(rec: dict) -> dict:
    return {
        "action": rec.get("action", ""),
        "conviction": rec.get("conviction"),
        "net_expected_pct": rec.get("net_expected_pct"),
    }


if __name__ == "__main__":
    import sys
    log_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/recommendations_log")
    files = sorted(
        [p for p in log_dir.glob("*.json") if parse_session_filename(p.name) is not None],
        key=lambda p: p.name,
        reverse=True,
    )
    if len(files) < 2:
        print(f"Need at least 2 logs in {log_dir} to compute drift. Found {len(files)}.")
        sys.exit(0)

    with open(files[0]) as f:
        current = json.load(f)
    previous = get_previous_session(log_dir)

    drift = compute_drift(current, previous)
    print(f"Drift: {len(drift)} events between {files[1].name} → {files[0].name}")
    for d in drift:
        was = d["was"] or {}
        now = d["now"] or {}
        print(
            f"  {d['ticker']:8s} {d['drift_type']:18s} "
            f"was={was.get('action', '-')}/{was.get('conviction', '-')}  "
            f"now={now.get('action', '-')}/{now.get('conviction', '-')}"
        )
