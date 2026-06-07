"""
drift_tracker.py
Detects significant changes between this session's recommendations and the
prior session — flips in action (BUY → SELL), large conviction jumps, sign
flips on net_expected_pct, etc.

Fed back into the Claude prompt so the model can either justify drift or
self-correct (and into the markdown report so the user sees it).
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from src._utils import parse_session_filename

# ── Thesis-text drift constants ────────────────────────────────────────────

# Words that carry little semantic load — present in nearly every thesis
# regardless of the actual rationale.  Filtered out before Jaccard so a
# rewrite from "AI tailwind drives revenue acceleration" to "M&A speculation
# from META lifts price" doesn't get inflated similarity from "drives" /
# "from" / "the".  Small, deliberate, English-only.
_THESIS_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "of",
        "for",
        "in",
        "on",
        "at",
        "by",
        "with",
        "from",
        "to",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "this",
        "that",
        "these",
        "those",
        "it",
        "as",
        "than",
        "then",
        "so",
        "we",
        "you",
        "your",
        "our",
        "their",
        "they",
        "should",
        "would",
        "could",
        "may",
        "might",
        "will",
        "shall",
        "do",
        "does",
        "did",
        "has",
        "have",
        "had",
        "into",
        "out",
        "over",
        "under",
        "above",
        "below",
        "between",
        "after",
        "before",
        "while",
        "via",
    }
)

# Token-set similarity threshold below which we flag a thesis_text_drift
# event.  Tuned empirically: identical → 1.0, paraphrase typically 0.65+,
# wholesale rewrite < 0.4.  0.55 is the boundary that catches "rewritten
# rationale" without being noisy for ordinary edits.
_THESIS_DRIFT_SIM_THRESHOLD = 0.55

# Don't run the comparison for very short theses — too noisy.  Real
# rationales typically run 20-50 meaningful tokens; we just want to skip
# 2-3-word stubs ("Buy now" vs "Sell now") where the comparison would be
# whim-driven.  4 is the floor at which a real rewrite has enough surface
# area to detect.
_THESIS_DRIFT_MIN_TOKENS = 4

_WORD_RE = re.compile(r"[a-z0-9]+")


def _thesis_tokens(text: str | None) -> set[str]:
    """Lower-case, strip punctuation, drop stop-words. Stable across calls."""
    if not text:
        return set()
    tokens = _WORD_RE.findall(text.lower())
    return {tok for tok in tokens if tok not in _THESIS_STOPWORDS and len(tok) > 1}


def _thesis_text_similarity(was: str | None, now: str | None) -> float:
    """Jaccard similarity between two thesis strings after stop-word filtering.

    Returns a float in [0.0, 1.0].  1.0 means token-equivalent (after
    normalisation); 0.0 means no shared content.  Pure-Python so we don't
    pull in rapidfuzz as a hard dependency; tested to be plenty fast for
    the few-dozen-tickers-per-run scale of this app.
    """
    was_tokens = _thesis_tokens(was)
    now_tokens = _thesis_tokens(now)
    if not was_tokens or not now_tokens:
        return 0.0
    if min(len(was_tokens), len(now_tokens)) < _THESIS_DRIFT_MIN_TOKENS:
        return 1.0  # too short to be a meaningful comparison — treat as identical
    intersection = was_tokens & now_tokens
    union = was_tokens | now_tokens
    return len(intersection) / len(union) if union else 0.0


def _is_thesis_text_drift(was_rec: dict, now_rec: dict) -> tuple[bool, float]:
    """True iff action stayed the same but the thesis was substantially rewritten.

    Returns ``(is_drift, similarity)`` so callers can show the score.  We
    deliberately skip this check when the action flipped — that's already
    flagged by ``action_flip`` and adding a second event would just be
    noise.
    """
    was_action = (was_rec.get("action") or "").upper()
    now_action = (now_rec.get("action") or "").upper()
    if was_action != now_action or not was_action:
        return False, 1.0
    similarity = _thesis_text_similarity(was_rec.get("thesis"), now_rec.get("thesis"))
    return similarity < _THESIS_DRIFT_SIM_THRESHOLD, similarity


def get_previous_session(
    log_dir: str | Path,
    skip_newest: bool = False,
    current_session_type: str | None = None,
    min_age_hours: float = 4.0,
) -> dict | None:
    """
    Return the most recently-saved recommendation JSON *before* the current run.

    Improvements over the naive "newest file" approach:

    1. **Skip re-runs of the same session.** If you ran morning at 9:30am and
       again at 9:35am, the 9:35am run treats the 9:30am one as "previous",
       which produces zero useful drift signal. Files within `min_age_hours`
       of now are skipped.

    2. **Prefer same-session-type from the previous trading day.** If
       `current_session_type` is "morning", we'd rather compare against
       yesterday's morning than this afternoon's report. We try same-type
       first, then fall back to any session.

    During normal app execution the current run has not been saved yet, so
    the newest existing file is a candidate for "previous". When comparing
    two already saved logs in the standalone script, pass skip_newest=True
    to treat the newest file as current and return the second-newest.

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
    if skip_newest and files:
        files = files[1:]
    if not files:
        return None

    cutoff = datetime.now() - timedelta(hours=min_age_hours)

    # Filenames look like 20260506_0930_morning.json — extract date+time directly.
    import re as _re

    _filename_pattern = _re.compile(r"^(\d{8})_(\d{4})_(morning|afternoon)\.json$")

    def _file_dt(path: Path) -> datetime | None:
        m = _filename_pattern.match(path.name)
        if not m:
            return None
        date_str, time_str, _ = m.groups()
        try:
            return datetime.strptime(f"{date_str} {time_str}", "%Y%m%d %H%M")
        except ValueError:
            return None

    aged_files = [p for p in files if (_file_dt(p) or datetime.min) <= cutoff]

    # Pass 1: prefer same session type
    chosen = None
    if current_session_type:
        for path in aged_files:
            parsed = parse_session_filename(path.name)
            if parsed and parsed[1] == current_session_type:
                chosen = path
                break

    # Pass 2: any aged file
    if chosen is None and aged_files:
        chosen = aged_files[0]

    # Pass 3: nothing aged enough — fall back to absolute newest (preserves
    # legacy behaviour for users who only ever run once a day).
    if chosen is None:
        chosen = files[0]

    try:
        with open(chosen) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    data["_session_file"] = chosen.name
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
            drift.append(
                {
                    "ticker": ticker,
                    "drift_type": "new_ticker",
                    "was": None,
                    "now": _summary(now_rec),
                }
            )
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
            drift.append(
                {
                    "ticker": ticker,
                    "drift_type": "action_flip",
                    "was": was_summary,
                    "now": now_summary,
                }
            )
            continue  # action flip is the dominant signal — skip lesser checks

        # Conviction jump (only when action stayed the same)
        if abs(now_conv - was_conv) >= conviction_delta_threshold:
            drift.append(
                {
                    "ticker": ticker,
                    "drift_type": "conviction_jump",
                    "was": was_summary,
                    "now": now_summary,
                }
            )
            continue

        # Sign flip on net_expected_pct (e.g. +5% → -3%)
        if was_net and now_net and (was_net > 0) != (now_net > 0):
            drift.append(
                {
                    "ticker": ticker,
                    "drift_type": "sign_flip",
                    "was": was_summary,
                    "now": now_summary,
                }
            )
            continue

        # Thesis-text drift — action stayed the same, conviction is steady,
        # net direction is consistent, but the rationale was substantially
        # rewritten.  This is the "moving goalposts" smell: same call, new
        # reason.  Often indicates the model couldn't reproduce its prior
        # reasoning and is post-rationalising — worth surfacing to Claude
        # for self-check on the next pass.
        is_drift, similarity = _is_thesis_text_drift(was_rec, now_rec)
        if is_drift:
            drift.append(
                {
                    "ticker": ticker,
                    "drift_type": "thesis_text_drift",
                    "was": was_summary,
                    "now": now_summary,
                    "similarity": round(similarity, 2),
                }
            )

    # Tickers dropped from prior session
    for ticker, was_rec in prev_by.items():
        if ticker not in current_by:
            drift.append(
                {
                    "ticker": ticker,
                    "drift_type": "dropped_ticker",
                    "was": _summary(was_rec),
                    "now": None,
                }
            )

    return drift


def _summary(rec: dict) -> dict:
    # ``thesis`` is included so downstream renderers can show "Was: <text> →
    # Now: <text>" for thesis_text_drift events.  Truncated upstream when
    # the prompt budget is tight; here we just preserve the field.
    return {
        "action": rec.get("action", ""),
        "conviction": rec.get("conviction"),
        "net_expected_pct": rec.get("net_expected_pct"),
        "thesis": rec.get("thesis"),
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
    previous = get_previous_session(log_dir, skip_newest=True)

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
