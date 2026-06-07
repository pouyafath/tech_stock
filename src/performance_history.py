"""Portfolio performance history (v1.17).

Rebuilds the portfolio time-series from the recommendation-log snapshots in
``data/recommendations_log/*.json`` and computes the metrics that drive the
new Performance tab:

* Cumulative return (portfolio vs SPY rebased to start)
* Daily / session-to-session returns
* Annualized return and volatility (assumes 252 trading sessions / year)
* Sharpe ratio (rf=0)
* Max drawdown (peak-to-trough)
* Rolling 90-session Sharpe, alpha, beta vs SPY
* Sector contribution waterfall — P&L attribution by sector for the period
* Return distribution histogram (per-session return bins)

Design choices
--------------
* **Source of truth = recommendation logs.**  Every session writes one JSON
  with ``portfolio_health.total_value_usd_equivalent`` and a full
  ``portfolio_health.risk_dashboard.total_value_usd``.  Those two carry the
  authoritative valuation; we don't need to reconstruct from yfinance.
* **SPY is fetched once with a 4-hour cache** (via ``src.cache.cached``) so
  the Performance tab can be opened repeatedly without hammering Yahoo.
* **yfinance is optional.**  If it's unavailable or the call fails we just
  drop the SPY comparison instead of crashing; the function still returns
  a usable payload (cumulative_spy_return_pct = None, beta/alpha = None).
* **Every public call is wrapped** so a missing log directory or malformed
  JSON never raises — the UI degrades to an empty-state placeholder.

The engine is read-only.  No yfinance call ever fires unless the caller
explicitly invokes ``portfolio_performance_summary()``.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.cache import cached
from src.config import load_settings

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_DIR = ROOT / "data" / "recommendations_log"

# yfinance default cache TTL — 4h means a user repeatedly opening the
# Performance tab doesn't refetch SPY every time.
SPY_CACHE_TTL_SECONDS = 4 * 3600

# Filename pattern: 20260513_1345_afternoon.json
_FILENAME_RE = re.compile(r"^(\d{8})_(\d{4})_(morning|afternoon)\.json$")


# ── Snapshot loading ──────────────────────────────────────────────────────


def load_portfolio_snapshots(log_dir: str | Path = DEFAULT_LOG_DIR) -> list[dict[str, Any]]:
    """Return one row per recommendation log, ordered oldest → newest.

    Each row:
      {
        "timestamp": datetime,           # parsed from filename
        "session_file": str,
        "session_type": "morning"|"afternoon",
        "total_value_usd": float,        # from portfolio_health
        "overall_pnl_pct": float|None,
        "holdings_by_sector": {sector: usd_value, ...},
      }

    Rows missing a parseable filename OR a positive total_value_usd are
    skipped silently — they're not useful for the time-series.
    """
    log_dir = Path(log_dir)
    if not log_dir.exists():
        return []

    rows: list[dict[str, Any]] = []
    for path in sorted(log_dir.glob("*.json")):
        match = _FILENAME_RE.match(path.name)
        if not match:
            continue
        date_part, time_part, session_type = match.groups()
        try:
            timestamp = datetime.strptime(f"{date_part} {time_part}", "%Y%m%d %H%M")
        except ValueError:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue

        ph = payload.get("portfolio_health") or {}
        risk = ph.get("risk_dashboard") or {}
        # Prefer the more precise risk_dashboard total; fall back to the
        # rounded portfolio_health equivalent.
        total_value = risk.get("total_value_usd") or ph.get("total_value_usd_equivalent")
        try:
            total_value = float(total_value) if total_value is not None else None
        except (TypeError, ValueError):
            total_value = None
        if not total_value or total_value <= 0:
            continue

        # Sector buckets from the portfolio snapshot (where present).
        sectors: dict[str, float] = defaultdict(float)
        holdings = payload.get("portfolio_snapshot", {}).get("holdings") or payload.get("holdings") or []
        for holding in holdings:
            sector = (holding.get("sector") or "Unclassified").strip() or "Unclassified"
            try:
                value = float(holding.get("market_value_usd") or holding.get("market_value") or 0.0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                sectors[sector] += value

        rows.append(
            {
                "timestamp": timestamp,
                "session_file": path.name,
                "session_type": session_type,
                "total_value_usd": total_value,
                "overall_pnl_pct": ph.get("overall_pnl_pct"),
                "holdings_by_sector": dict(sectors),
            }
        )

    rows.sort(key=lambda row: row["timestamp"])
    return rows


# ── SPY series (yfinance, cached) ──────────────────────────────────────────


def _fetch_spy_series(start_date: str, end_date: str) -> dict[str, float]:
    """Return ``{ISO_DATE: spy_close, ...}`` between start and end (inclusive).

    Wrapped — caller never sees exceptions.  Returns ``{}`` if yfinance
    isn't installed or the call fails for any reason.
    """
    try:
        import yfinance as yf  # type: ignore[import-untyped]
    except Exception:
        return {}
    try:
        # auto_adjust=True gives total-return-style prices (handles SPY div)
        df = yf.download(
            "SPY",
            start=start_date,
            end=end_date,
            progress=False,
            auto_adjust=True,
            actions=False,
        )
    except Exception:
        return {}
    if df is None or df.empty:
        return {}
    try:
        closes = df["Close"]
        if hasattr(closes, "columns"):  # multi-index for some yfinance versions
            closes = closes.iloc[:, 0]
        return {idx.strftime("%Y-%m-%d"): float(val) for idx, val in closes.items() if val and not math.isnan(float(val))}
    except Exception:
        return {}


def spy_series(start_date: str, end_date: str) -> dict[str, float]:
    """Cached wrapper around ``_fetch_spy_series`` — TTL = 4h by default."""
    try:
        settings = load_settings()
        ttl = settings.get("performance_spy_cache_ttl_seconds", SPY_CACHE_TTL_SECONDS)
        cache_enabled = settings.get("cache_enabled", True)
    except Exception:
        ttl = SPY_CACHE_TTL_SECONDS
        cache_enabled = True
    return cached(
        namespace="performance_spy",
        key=f"{start_date}_{end_date}",
        ttl_seconds=ttl,
        loader=lambda: _fetch_spy_series(start_date, end_date),
        enabled=cache_enabled,
    )


# ── Math helpers ───────────────────────────────────────────────────────────


def _pct_changes(values: list[float]) -> list[float]:
    """Compute period-over-period percentage changes in percentage points."""
    out = []
    for i in range(1, len(values)):
        prev = values[i - 1]
        if prev <= 0:
            out.append(0.0)
        else:
            out.append((values[i] - prev) / prev * 100.0)
    return out


def _safe_mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _safe_stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _safe_mean(values)
    return (sum((v - mean) ** 2 for v in values) / (len(values) - 1)) ** 0.5


def _percentile(values: list[float], pct: float) -> float:
    """Linear-interpolated percentile (``pct`` in 0–100) of a numeric list."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return ordered[int(rank)]
    frac = rank - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def _max_drawdown_pct(series: list[float]) -> float:
    """Worst peak-to-trough drawdown of a cumulative-value series, in %.

    Returns 0.0 for an empty series, negative for any losing streak.
    """
    if not series:
        return 0.0
    peak = series[0]
    worst = 0.0
    for value in series:
        if value > peak:
            peak = value
        if peak > 0:
            drawdown = (value - peak) / peak * 100.0
            if drawdown < worst:
                worst = drawdown
    return worst


def _linear_regression(x: list[float], y: list[float]) -> tuple[float, float]:
    """Ordinary least squares.  Returns (slope, intercept).  (0, 0) when degenerate."""
    n = min(len(x), len(y))
    if n < 2:
        return (0.0, 0.0)
    mean_x = sum(x[:n]) / n
    mean_y = sum(y[:n]) / n
    num = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
    den = sum((x[i] - mean_x) ** 2 for i in range(n))
    if den == 0:
        return (0.0, mean_y)
    slope = num / den
    intercept = mean_y - slope * mean_x
    return (slope, intercept)


def _rolling(window: int, series: list[float], compute) -> list[float | None]:
    """Apply ``compute`` over a rolling window; emit ``None`` for warm-up periods."""
    out: list[float | None] = []
    for i in range(len(series)):
        if i + 1 < window:
            out.append(None)
            continue
        out.append(compute(series[i + 1 - window : i + 1]))
    return out


# ── Public API ─────────────────────────────────────────────────────────────


def portfolio_performance_summary(
    *,
    log_dir: str | Path = DEFAULT_LOG_DIR,
    lookback_days: int | None = None,
    fetch_spy: bool = True,
) -> dict[str, Any]:
    """Compute the full Performance-tab payload.

    Parameters
    ----------
    log_dir : path
        Where recommendation logs live. Defaults to ``data/recommendations_log/``.
    lookback_days : int | None
        If set, trim the series to the trailing ``lookback_days`` window.
    fetch_spy : bool
        Set to ``False`` to skip the yfinance fetch (useful for tests and
        for the Streamlit smoke tests).

    Returns
    -------
    dict
        See module docstring for the full shape.  When there are fewer than
        2 snapshots, returns ``{"n_snapshots": <0|1>, "ready": False, ...}``
        so the UI can render a friendly empty state.
    """
    snapshots = load_portfolio_snapshots(log_dir)
    if lookback_days is not None:
        cutoff = datetime.now() - timedelta(days=lookback_days)
        snapshots = [s for s in snapshots if s["timestamp"] >= cutoff]

    if len(snapshots) < 2:
        return {
            "ready": False,
            "n_snapshots": len(snapshots),
            "reason": (
                "Need at least two recommendation logs to compute a time series. "
                "Generate one more report and the Performance tab will populate."
            ),
        }

    timestamps = [s["timestamp"] for s in snapshots]
    values = [s["total_value_usd"] for s in snapshots]
    iso_dates = [t.strftime("%Y-%m-%d") for t in timestamps]

    initial = values[0]
    final = values[-1]
    cumulative_return_pct = (final - initial) / initial * 100.0 if initial > 0 else 0.0

    session_returns = _pct_changes(values)
    mean_return = _safe_mean(session_returns)
    stdev = _safe_stdev(session_returns)

    # Annualisation factor: most users run morning + afternoon, so 2/day ≈
    # 504 sessions a year, but that conflates intra-day noise.  Use the
    # actual span between first and last snapshot for a realistic figure.
    span_days = max((timestamps[-1] - timestamps[0]).days, 1)
    sessions_per_year = len(session_returns) * 365 / span_days if span_days else 252
    annualized_return_pct = mean_return * sessions_per_year
    annualized_volatility_pct = stdev * (sessions_per_year**0.5)
    sharpe = (annualized_return_pct / annualized_volatility_pct) if annualized_volatility_pct > 0 else 0.0

    max_dd_pct = _max_drawdown_pct(values)

    # ── Downside-risk metrics (v1.24) ──────────────────────────────────────
    # session_returns are per-session % changes. Sortino penalises only the
    # negative returns; Calmar compares annualized return to max drawdown;
    # VaR/CVaR summarise the left tail at the 95% confidence level.
    downside = [r for r in session_returns if r < 0]
    downside_dev = _safe_stdev(downside) * (sessions_per_year**0.5) if len(downside) >= 2 else 0.0
    sortino = (annualized_return_pct / downside_dev) if downside_dev > 0 else None
    calmar = (annualized_return_pct / abs(max_dd_pct)) if max_dd_pct < 0 else None
    var_95_pct = _percentile(session_returns, 5) if len(session_returns) >= 2 else None
    cvar_95_pct = None
    if var_95_pct is not None:
        tail = [r for r in session_returns if r <= var_95_pct]
        cvar_95_pct = _safe_mean(tail) if tail else None

    # ── SPY benchmark ──────────────────────────────────────────────────────
    spy_payload: dict[str, Any] = {
        "available": False,
        "values": [],
        "returns": [],
        "cumulative_return_pct": None,
        "beta": None,
        "alpha_annualized_pct": None,
    }
    if fetch_spy:
        try:
            start_iso = (timestamps[0] - timedelta(days=2)).strftime("%Y-%m-%d")
            end_iso = (timestamps[-1] + timedelta(days=2)).strftime("%Y-%m-%d")
            spy_closes = spy_series(start_iso, end_iso)
        except Exception:
            spy_closes = {}
        if spy_closes:
            spy_values: list[float] = []
            for iso in iso_dates:
                # Snap to most-recent SPY close ≤ session date (markets closed weekends).
                close = spy_closes.get(iso)
                if close is None:
                    # Walk back up to 4 days to find a prior close.
                    dt = datetime.strptime(iso, "%Y-%m-%d")
                    for back in range(1, 5):
                        candidate = (dt - timedelta(days=back)).strftime("%Y-%m-%d")
                        if candidate in spy_closes:
                            close = spy_closes[candidate]
                            break
                spy_values.append(close if close is not None else float("nan"))
            # Drop snapshots without an SPY anchor; align with portfolio returns.
            paired = [(v, s) for v, s in zip(values, spy_values) if isinstance(s, (int, float)) and not math.isnan(s)]
            if len(paired) >= 2:
                p_values = [pair[0] for pair in paired]
                s_values = [pair[1] for pair in paired]
                p_rets = _pct_changes(p_values)
                s_rets = _pct_changes(s_values)
                spy_cumulative = (s_values[-1] - s_values[0]) / s_values[0] * 100.0 if s_values[0] > 0 else 0.0
                # Beta = cov(p, s) / var(s) — same as slope of OLS regression
                beta, intercept = _linear_regression(s_rets, p_rets)
                # Alpha (intercept) is in per-session units; scale up by
                # sessions/year for an annualised hint.
                spy_payload = {
                    "available": True,
                    "values": s_values,
                    "returns": s_rets,
                    "cumulative_return_pct": round(spy_cumulative, 2),
                    "beta": round(beta, 2),
                    "alpha_annualized_pct": round(intercept * sessions_per_year, 2),
                }

    # ── Rolling metrics ────────────────────────────────────────────────────
    rolling_window = 30  # last 30 sessions ≈ ~2 weeks for morning+afternoon cadence
    rolling_sharpe: list[float | None] = _rolling(
        rolling_window,
        session_returns,
        lambda chunk: (
            (_safe_mean(chunk) * sessions_per_year) / (_safe_stdev(chunk) * (sessions_per_year**0.5)) if _safe_stdev(chunk) > 0 else 0.0
        ),
    )
    rolling_drawdown: list[float] = []
    running_peak = values[0]
    for v in values:
        running_peak = max(running_peak, v)
        rolling_drawdown.append((v - running_peak) / running_peak * 100.0 if running_peak > 0 else 0.0)

    # ── Sector contribution waterfall ──────────────────────────────────────
    # Compare last snapshot's sector buckets to the first snapshot's.
    first_sectors = snapshots[0].get("holdings_by_sector") or {}
    last_sectors = snapshots[-1].get("holdings_by_sector") or {}
    sector_keys = set(first_sectors) | set(last_sectors)
    sector_waterfall = [
        {
            "sector": sector,
            "start_usd": round(first_sectors.get(sector, 0.0), 2),
            "end_usd": round(last_sectors.get(sector, 0.0), 2),
            "delta_usd": round(last_sectors.get(sector, 0.0) - first_sectors.get(sector, 0.0), 2),
        }
        for sector in sorted(sector_keys, key=lambda s: -abs(last_sectors.get(s, 0.0) - first_sectors.get(s, 0.0)))
    ]

    # ── Return distribution histogram ─────────────────────────────────────
    # Bin the per-session returns into fixed 0.5% buckets from -5% to +5%.
    distribution: dict[str, int] = defaultdict(int)
    for ret in session_returns:
        if ret <= -5:
            label = "≤-5%"
        elif ret >= 5:
            label = "≥+5%"
        else:
            # Round down to the nearest 0.5%
            lower = math.floor(ret * 2) / 2
            upper = lower + 0.5
            label = f"{lower:+.1f} to {upper:+.1f}%"
        distribution[label] += 1

    return {
        "ready": True,
        "n_snapshots": len(snapshots),
        "first_ts": timestamps[0].isoformat(timespec="minutes"),
        "last_ts": timestamps[-1].isoformat(timespec="minutes"),
        "lookback_days": lookback_days,
        "iso_dates": iso_dates,
        "values_usd": values,
        "session_returns_pct": session_returns,
        "cumulative_return_pct": round(cumulative_return_pct, 2),
        "annualized_return_pct": round(annualized_return_pct, 2),
        "annualized_volatility_pct": round(annualized_volatility_pct, 2),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2) if sortino is not None else None,
        "calmar": round(calmar, 2) if calmar is not None else None,
        "var_95_pct": round(var_95_pct, 2) if var_95_pct is not None else None,
        "cvar_95_pct": round(cvar_95_pct, 2) if cvar_95_pct is not None else None,
        "max_drawdown_pct": round(max_dd_pct, 2),
        "sessions_per_year": round(sessions_per_year, 1),
        "rolling_sharpe": rolling_sharpe,
        "rolling_drawdown_pct": rolling_drawdown,
        "rolling_window_sessions": rolling_window,
        "spy": spy_payload,
        "sector_waterfall": sector_waterfall,
        "return_distribution": dict(distribution),
    }


__all__ = [
    "DEFAULT_LOG_DIR",
    "load_portfolio_snapshots",
    "spy_series",
    "portfolio_performance_summary",
]
