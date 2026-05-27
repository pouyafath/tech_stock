"""Anthropic spend tracker + monthly budget enforcement (v1.19).

Why this exists
---------------
Pre-v1.19 the only visibility into Anthropic spend was the per-run cost
printed at the end of a CLI session. No rolling totals, no monthly
projection, no way to cap accidental over-spending. For a productised
tool aimed at non-developers this is unacceptable: a runaway loop or a
forgotten cron job could rack up real charges silently.

This module appends every run's usage block to ``data/cost_log.jsonl``
(one record per run), computes rolling 7-day / 30-day / month-to-date
totals, projects the monthly run-rate, and exposes a check
(``check_budget``) that the CLI calls before invoking Claude to decide
whether to warn or hard-block.

Design choices
--------------
* **JSONL on disk, not in-memory state.** Survives restarts; trivial
  to grep; small (≤ 200 bytes per record).
* **Settings-gated budget.** ``settings.json → monthly_budget_usd``
  controls the cap. Missing → no cap (back-compat for existing users).
* **Soft warn at 80%, hard block at 100% with override.** The CLI
  reads the ``allow_overage`` flag (env var or ``--force``) so a user
  who hits the cap mid-day can still run for an explicit one-off.
* **Never raises.** Logging a record never breaks a report run.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_PATH = ROOT / "data" / "cost_log.jsonl"
DEFAULT_BUDGET_USD = 0.0  # 0 disables the cap


# ── Recording ──────────────────────────────────────────────────────────────


def _log_path() -> Path:
    path = DEFAULT_LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def record_run(
    *,
    model: str,
    cost_usd: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
    session_type: str | None = None,
    extra: dict | None = None,
) -> bool:
    """Append one run record. Returns True on success.  Never raises."""
    try:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "model": model or "unknown",
            "cost_usd": round(float(cost_usd or 0.0), 6),
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "session_type": session_type,
            "extra": extra or {},
        }
        line = json.dumps(record, default=str, ensure_ascii=False)
        with _log_path().open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        return True
    except OSError:
        return False
    except Exception:
        return False


# ── Read helpers ───────────────────────────────────────────────────────────


def _iter_records() -> list[dict[str, Any]]:
    path = _log_path()
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    out.append(record)
    except OSError:
        return []
    return out


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass(frozen=True)
class SpendSummary:
    total_usd: float
    runs: int
    last_7d_usd: float
    last_7d_runs: int
    last_30d_usd: float
    last_30d_runs: int
    month_to_date_usd: float
    month_to_date_runs: int
    projected_monthly_usd: float  # MTD scaled to a full 30-day month
    daily_series: list[dict[str, Any]]  # [{"date": "YYYY-MM-DD", "cost_usd": x, "runs": n}, ...]
    log_path: str


def spend_summary(*, lookback_days: int = 30) -> SpendSummary:
    """Aggregate cost log into the Spend-tab payload.  Never raises."""
    now = datetime.now(timezone.utc)
    cutoff_7 = now - timedelta(days=7)
    cutoff_30 = now - timedelta(days=lookback_days)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    records = _iter_records()
    daily: dict[str, dict[str, float]] = {}
    total = 0.0
    last7 = 0.0
    last7_n = 0
    last30 = 0.0
    last30_n = 0
    mtd = 0.0
    mtd_n = 0
    total_n = 0
    for record in records:
        ts = _parse_ts(record.get("ts"))
        if ts is None:
            continue
        cost = float(record.get("cost_usd") or 0.0)
        total += cost
        total_n += 1
        if ts >= cutoff_7:
            last7 += cost
            last7_n += 1
        if ts >= cutoff_30:
            last30 += cost
            last30_n += 1
        if ts >= month_start:
            mtd += cost
            mtd_n += 1
        date_key = ts.date().isoformat()
        bucket = daily.setdefault(date_key, {"cost_usd": 0.0, "runs": 0})
        bucket["cost_usd"] += cost
        bucket["runs"] += 1

    # Build daily series in ascending order, capped at lookback_days
    cutoff_date = (now - timedelta(days=lookback_days)).date()
    daily_series = sorted(
        (
            {"date": day, "cost_usd": round(stats["cost_usd"], 4), "runs": int(stats["runs"])}
            for day, stats in daily.items()
            if datetime.fromisoformat(day).date() >= cutoff_date
        ),
        key=lambda row: row["date"],
    )

    # Monthly projection — MTD scaled to a full 30-day month
    days_into_month = max(1, (now - month_start).days + 1)
    projection = mtd / days_into_month * 30.0 if days_into_month else 0.0

    return SpendSummary(
        total_usd=round(total, 4),
        runs=total_n,
        last_7d_usd=round(last7, 4),
        last_7d_runs=last7_n,
        last_30d_usd=round(last30, 4),
        last_30d_runs=last30_n,
        month_to_date_usd=round(mtd, 4),
        month_to_date_runs=mtd_n,
        projected_monthly_usd=round(projection, 2),
        daily_series=daily_series,
        log_path=str(_log_path()),
    )


# ── Budget enforcement ────────────────────────────────────────────────────


@dataclass(frozen=True)
class BudgetCheck:
    ok: bool
    soft_warn: bool
    hard_block: bool
    budget_usd: float
    month_to_date_usd: float
    projected_monthly_usd: float
    message: str


def _budget_from_settings() -> float:
    try:
        from src.config import load_settings

        return float(load_settings().get("monthly_budget_usd", DEFAULT_BUDGET_USD) or 0.0)
    except Exception:
        return DEFAULT_BUDGET_USD


def check_budget(*, expected_cost_usd: float = 0.0) -> BudgetCheck:
    """Decide whether the next run should proceed, warn, or be blocked.

    * ``budget_usd == 0`` → no cap, always ok.
    * ``mtd + expected ≥ budget`` → hard block (caller can override).
    * ``mtd + expected ≥ 0.8 × budget`` → soft warn.
    """
    budget = _budget_from_settings()
    summary = spend_summary(lookback_days=30)
    projected_after = summary.month_to_date_usd + expected_cost_usd

    if budget <= 0:
        return BudgetCheck(
            ok=True,
            soft_warn=False,
            hard_block=False,
            budget_usd=0.0,
            month_to_date_usd=summary.month_to_date_usd,
            projected_monthly_usd=summary.projected_monthly_usd,
            message="No monthly budget set — set one in settings.json → monthly_budget_usd.",
        )

    if projected_after >= budget:
        remaining = max(0.0, budget - summary.month_to_date_usd)
        return BudgetCheck(
            ok=False,
            soft_warn=False,
            hard_block=True,
            budget_usd=budget,
            month_to_date_usd=summary.month_to_date_usd,
            projected_monthly_usd=summary.projected_monthly_usd,
            message=(
                f"Monthly cap reached: ${summary.month_to_date_usd:.2f} of ${budget:.2f} spent. "
                f"Only ${remaining:.2f} left, and this run estimates ${expected_cost_usd:.2f}. "
                "Set ALLOW_OVERAGE=1 in your env (or pass --force) to override."
            ),
        )

    if projected_after >= 0.8 * budget:
        return BudgetCheck(
            ok=True,
            soft_warn=True,
            hard_block=False,
            budget_usd=budget,
            month_to_date_usd=summary.month_to_date_usd,
            projected_monthly_usd=summary.projected_monthly_usd,
            message=(
                f"Approaching monthly cap: ${summary.month_to_date_usd:.2f} of ${budget:.2f} spent "
                f"({(summary.month_to_date_usd / budget) * 100:.0f}%)."
            ),
        )

    return BudgetCheck(
        ok=True,
        soft_warn=False,
        hard_block=False,
        budget_usd=budget,
        month_to_date_usd=summary.month_to_date_usd,
        projected_monthly_usd=summary.projected_monthly_usd,
        message=f"${summary.month_to_date_usd:.2f} of ${budget:.2f} budget used ({(summary.month_to_date_usd / budget) * 100:.0f}%).",
    )


def is_overage_allowed() -> bool:
    """User explicit-override switch read by the CLI when hard-block fires."""
    return os.environ.get("ALLOW_OVERAGE") == "1"


def clear_cost_log() -> bool:
    """Delete the cost log.  Used by the Privacy → Delete-all-data action and tests."""
    try:
        path = _log_path()
        if path.exists():
            path.unlink()
        return True
    except OSError:
        return False


__all__ = [
    "DEFAULT_BUDGET_USD",
    "SpendSummary",
    "BudgetCheck",
    "record_run",
    "spend_summary",
    "check_budget",
    "is_overage_allowed",
    "clear_cost_log",
]
