"""
_utils.py
Small shared helpers used across loaders, the backtester, and the drift tracker.
Underscore-prefixed module name signals "internal — no public API guarantees."
"""

import re

# Recommendation log filename pattern: 20260423_2101_morning.json
_FILENAME_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})_\d{4}_(morning|afternoon)\.json$")


def safe_float(v) -> float | None:
    """Convert a possibly-blank/quoted string to float, returning None on failure."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().strip('"')
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def clean_csv_row(row: dict) -> dict:
    """
    Strip surrounding whitespace and quote characters from every key + value
    of a csv.DictReader row.
    """
    return {
        (k.strip().strip('"') if isinstance(k, str) else k):
        (v.strip().strip('"') if isinstance(v, str) else v)
        for k, v in row.items()
    }


def parse_session_filename(name: str) -> tuple[str, str] | None:
    """
    Parse a recommendation-log filename into (session_date_iso, session_type).
    Example: '20260423_2101_morning.json' → ('2026-04-23', 'morning')
    Returns None for non-matching filenames.
    """
    m = _FILENAME_RE.match(name)
    if not m:
        return None
    yr, mo, da, sess = m.groups()
    return f"{yr}-{mo}-{da}", sess
