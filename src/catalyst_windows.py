"""
catalyst_windows.py — classify each ticker's relationship to known catalysts.

Aligns trades with the user's 3-6 month sweet-spot strategy. Three windows
matter most for that horizon:

    setup     T-30..T-5     30 days before earnings → entry ok if conv >= 7
    lockdown  T-5..T+0      ≤5 days before earnings → no new ADD/BUY (IV crush)
    drift     T+1..T+3      ≤3 days after earnings → post-earnings drift window
                            high-conviction adds OK if direction confirmed

Plus session-level macro tags:

    fomc_week / cpi_week    Reduce risk Tue-before; re-add Thu-after.
    nfp_day                 First Friday of month.

This module is pure: given today's date and per-ticker earnings dates, it returns
deterministic tags. The Claude prompt lists tags so the model can pre-position
without us having to hard-code each rule.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta


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


def classify_earnings_window(earnings_date, today: date | None = None) -> dict | None:
    """Return {window, days_to, label} for a single ticker's earnings date.

    Returns None if earnings_date is missing or far outside any meaningful window.
    """
    today = today or datetime.now().date()
    earnings = _coerce_date(earnings_date)
    if earnings is None:
        return None
    days_to = (earnings - today).days

    if 5 < days_to <= 30:
        return {
            "window": "setup",
            "days_to": days_to,
            "label": f"earnings setup (T-{days_to}d) — entry OK if conviction ≥7",
        }
    if 0 <= days_to <= 5:
        return {
            "window": "lockdown",
            "days_to": days_to,
            "label": f"earnings lockdown (T-{days_to}d) — no new ADD/BUY, IV crush risk",
        }
    if -3 <= days_to < 0:
        return {
            "window": "drift",
            "days_to": days_to,
            "label": f"post-earnings drift (T{days_to}d) — high-conviction adds OK if direction confirmed",
        }
    return None


def annotate_tickers(per_ticker_enriched: dict, today: date | None = None) -> dict:
    """Build {ticker: {window, days_to, label}} from enrichment data."""
    out: dict[str, dict] = {}
    for ticker, blob in (per_ticker_enriched or {}).items():
        if not isinstance(blob, dict):
            continue
        earnings = (blob.get("upcoming_earnings") or {}).get("date")
        tag = classify_earnings_window(earnings, today)
        if tag:
            out[ticker] = tag
    return out


# ─────────────────────────────────────────────────────────────────────────
# Macro / session-level catalyst windows (FOMC, CPI, NFP)
# ─────────────────────────────────────────────────────────────────────────


def _first_friday(year: int, month: int) -> date:
    d = date(year, month, 1)
    return d + timedelta(days=(4 - d.weekday()) % 7)


def macro_session_tags(macro_calendar: dict | None, today: date | None = None) -> list[str]:
    """Return free-text tags for session-level macro events near `today`.

    Inputs:
        macro_calendar: optional dict like
            {"next_cpi_window": "2026-05-10 to 2026-05-15",
             "next_fomc_dates": ["2026-05-12", ...]}
        today: defaults to today's local date

    Even without a macro_calendar payload, NFP is detectable from the date.
    """
    today = today or datetime.now().date()
    tags: list[str] = []

    nfp_day = _first_friday(today.year, today.month)
    if today == nfp_day:
        tags.append("NFP_DAY: jobs report at 8:30 ET — expect volatility spike")
    elif (nfp_day - today).days == 1:
        tags.append("NFP_TOMORROW: trim short-dated risk before close")

    if macro_calendar:
        # CPI window
        window = macro_calendar.get("next_cpi_window") or ""
        if " to " in window:
            try:
                start_s, end_s = [s.strip() for s in window.split(" to ", 1)]
                start = datetime.strptime(start_s, "%Y-%m-%d").date()
                end = datetime.strptime(end_s, "%Y-%m-%d").date()
                if start <= today <= end:
                    tags.append("CPI_WEEK: inflation print due — defensive bias on growth names")
                elif (start - today).days in (1, 2):
                    tags.append(f"CPI_IN_{(start - today).days}D: pre-position; consider trim of high-beta")
            except ValueError:
                pass

        # FOMC dates
        for fomc_str in macro_calendar.get("next_fomc_dates") or []:
            fomc = _coerce_date(fomc_str)
            if not fomc:
                continue
            delta = (fomc - today).days
            if delta == 0:
                tags.append("FOMC_TODAY: rate decision — hold off on new entries until after 2pm ET")
            elif delta in (1, 2):
                tags.append(f"FOMC_IN_{delta}D: trim 10-20% across portfolio Tue-before")
            elif delta == -1:
                tags.append("FOMC_YESTERDAY: re-add quality if direction is clear")
    return tags


def format_for_prompt(ticker_tags: dict, session_tags: Iterable[str]) -> str:
    """Render catalyst-window context for the Claude prompt."""
    if not ticker_tags and not session_tags:
        return ""
    lines = ["CATALYST WINDOWS:"]
    if session_tags:
        for tag in session_tags:
            lines.append(f"  ⚠ {tag}")
    if ticker_tags:
        lines.append("  Per-ticker earnings windows:")
        # Group by window for readability
        by_window: dict[str, list[str]] = {}
        for ticker, tag in ticker_tags.items():
            by_window.setdefault(tag["window"], []).append(f"{ticker} ({tag['label']})")
        for window in ("lockdown", "drift", "setup"):
            tickers = by_window.get(window) or []
            if not tickers:
                continue
            lines.append(f"    {window.upper()}: {', '.join(tickers)}")
    return "\n".join(lines)
