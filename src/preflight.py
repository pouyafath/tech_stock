"""Doctor/preflight health checks for supportability and release readiness."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any

from src.cost_tracker import check_budget, spend_summary
from src.onboarding import demo_snapshot
from src.updater import UpdateInfo, check_for_update
from src.version import APP_VERSION

API_FIELDS = [
    {"env": "ANTHROPIC_API_KEY", "source": "Anthropic", "required": True},
    {"env": "FINNHUB_API_KEY", "source": "Finnhub", "required": False},
    {"env": "POLYGON_API_KEY", "source": "Polygon", "required": False},
    {"env": "TWELVE_DATA_API_KEY", "source": "Twelve Data", "required": False},
    {"env": "FRED_API_KEY", "source": "FRED", "required": False},
    {"env": "COINGECKO_API_KEY", "source": "CoinGecko", "required": False},
    {"env": "ALPHA_VANTAGE_API_KEY", "source": "Alpha Vantage", "required": False},
]


def _path_exists(path: Path | str | None) -> bool:
    return bool(path and Path(path).expanduser().exists())


def _as_jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _as_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_as_jsonable(item) for item in value]
    return value


def _read_env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        return values
    return values


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _api_key_status() -> dict[str, Any]:
    from src.main import _load_api_keys_from_file, api_key_search_paths

    _load_api_keys_from_file()
    files = [{"path": path, "exists": path.exists()} for path in api_key_search_paths()]
    file_values = [(Path(row["path"]), _read_env_values(Path(row["path"]))) for row in files if row["exists"]]
    checks: list[dict[str, Any]] = []
    for field in API_FIELDS:
        env_name = field["env"]
        value = os.environ.get(env_name) or ""
        source_path = None
        for path, values in file_values:
            if values.get(env_name):
                value = values[env_name]
                source_path = path
                break
        configured = bool(value)
        checks.append(
            {
                "source": field["source"],
                "env": env_name,
                "required": field["required"],
                "configured": configured,
                "status": "configured" if configured else "missing",
                "masked": _mask(value),
                "source_path": source_path,
            }
        )
    required_missing = [row for row in checks if row["required"] and not row["configured"]]
    optional_missing = [row for row in checks if not row["required"] and not row["configured"]]
    return {
        "storage_mode": "API_KEYS.txt / .env files",
        "search_paths": files,
        "checks": checks,
        "required_missing": len(required_missing),
        "optional_missing": len(optional_missing),
        "configured_count": sum(1 for row in checks if row["configured"]),
    }


def _csv_date_from_name(path: Path) -> str | None:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
    return match.group(1) if match else None


def _csv_freshness() -> dict[str, Any]:
    from src.main import UPLOAD_DIR

    search_dirs = [UPLOAD_DIR, Path.home() / "Downloads"]
    out: dict[str, Any] = {}
    now = datetime.now()
    for kind, pattern in {"holdings": "holdings-report*.csv", "activities": "activities-export*.csv"}.items():
        candidates: list[Path] = []
        for directory in search_dirs:
            if directory.exists():
                candidates.extend(directory.glob(pattern))
        unique = sorted({path.resolve() for path in candidates if path.exists()}, key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
        latest = unique[0] if unique else None
        age_hours = None
        if latest:
            age_hours = round((now.timestamp() - latest.stat().st_mtime) / 3600, 2)
        out[kind] = {
            "latest_path": latest,
            "filename_date": _csv_date_from_name(latest) if latest else None,
            "candidate_count": len(unique),
            "age_hours": age_hours,
            "stale": age_hours is None or age_hours > 72,
            "search_dirs": search_dirs,
        }
    return out


def _workspace_status() -> dict[str, Any]:
    from src.main import runtime_locations

    locations = runtime_locations()
    return {
        "locations": locations,
        "writable": {name: _is_writable(path) for name, path in locations.items()},
    }


def _is_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".tech_stock_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _budget_status() -> dict[str, Any]:
    spend = spend_summary(lookback_days=30)
    budget = check_budget(expected_cost_usd=0.0)
    return {
        "budget_usd": budget.budget_usd,
        "month_to_date_usd": budget.month_to_date_usd,
        "projected_monthly_usd": budget.projected_monthly_usd,
        "ok": budget.ok,
        "soft_warn": budget.soft_warn,
        "hard_block": budget.hard_block,
        "message": budget.message,
        "runs_30d": spend.last_30d_runs,
        "cost_log_path": spend.log_path,
    }


def _update_status(update: UpdateInfo) -> dict[str, Any]:
    return {
        "current_version": update.current_version,
        "latest_version": update.latest_version,
        "available": update.available,
        "release_url": update.release_url,
        "published_at": update.published_at,
        "error": update.error,
        "from_cache": update.from_cache,
        "cache_path": update.cache_path,
        "cache_age_seconds": update.cache_age_seconds,
        "platform_asset": update.asset_name,
        "asset_available": update.asset_available,
        "checksum_available": update.checksum_available,
        "asset_names": update.asset_names,
    }


def run_demo_smoke_test() -> dict[str, Any]:
    """Validate bundled sample data and UI view models without network or Claude."""
    checks: list[dict[str, Any]] = []
    errors: list[str] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            errors.append(f"{name}: {detail}")

    try:
        snapshot = demo_snapshot()
        record("sample_holdings_exists", _path_exists(snapshot.holdings_csv), str(snapshot.holdings_csv))
        record("sample_activities_exists", _path_exists(snapshot.activities_csv), str(snapshot.activities_csv))
        record("sample_log_exists", _path_exists(snapshot.recommendation_json), str(snapshot.recommendation_json))

        from src.portfolio_loader import parse_holdings_csv
        from src.report_generator import generate_markdown
        from src.view_models import build_buy_signals_view, build_dashboard_view

        portfolio = parse_holdings_csv(Path(snapshot.holdings_csv or ""))
        record("holdings_parse", len(portfolio.get("holdings", [])) > 0, f"{len(portfolio.get('holdings', []))} positions")

        payload = json.loads(Path(snapshot.recommendation_json or "").read_text(encoding="utf-8"))
        dashboard = build_dashboard_view({"session_file": "demo.json", **payload})
        record("dashboard_view_model", bool(dashboard.get("metric_cards")), f"{len(dashboard.get('metric_cards', []))} cards")

        candidates = []
        for rec in payload.get("recommendations", [])[:5]:
            candidates.append(
                {
                    **rec,
                    "current_price": rec.get("target_entry_or_exit") or 100,
                    "quote_timestamp_utc": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
                    "quote_source": "demo",
                    "analyst_consensus": {"total_analysts": 1, "consensus_label": "DEMO"},
                    "price_targets": {"mean": rec.get("target_entry_or_exit") or 100, "source": "demo"},
                    "source_notes": ["Demo bundled sample"],
                }
            )
        buy_view = build_buy_signals_view({"session_file": "demo.json", "candidates": candidates})
        record("buy_signals_view_model", "counts" in buy_view, str(buy_view.get("counts")))

        markdown = generate_markdown("morning", payload, {}, portfolio=portfolio, usage={"passes": 0, "cost_usd": 0})
        record("markdown_render", "# Tech Stock Advisor" in markdown, f"{len(markdown)} chars")
    except Exception as exc:  # noqa: BLE001
        record("demo_smoke_exception", False, str(exc))

    return {
        "ok": not errors,
        "checks": checks,
        "errors": errors,
    }


def _summary_rows(payload: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    update = payload.get("update") or {}
    api = payload.get("api_keys") or {}
    csv = payload.get("csv_freshness") or {}
    budget = payload.get("budget") or {}

    simulated_current = payload.get("simulated_current_version")
    version_detail = f"installed {payload.get('app_version')} / latest {update.get('latest_version') or 'unknown'}"
    if simulated_current:
        version_detail = (
            f"installed {payload.get('app_version')}; "
            f"simulated current {simulated_current} / latest {update.get('latest_version') or 'unknown'}"
        )
    rows.append(
        {
            "check": "Version",
            "status": "UPDATE" if update.get("available") else "OK",
            "detail": version_detail,
        }
    )
    rows.append(
        {
            "check": "Update cache",
            "status": "CACHE" if update.get("from_cache") else "LIVE",
            "detail": f"age {update.get('cache_age_seconds', 0)}s; release {update.get('release_url')}",
        }
    )
    rows.append(
        {
            "check": "Release assets",
            "status": "OK" if update.get("asset_available") and update.get("checksum_available") else "WARN",
            "detail": f"asset={update.get('platform_asset') or 'none'} checksum={bool(update.get('checksum_available'))}",
        }
    )
    rows.append(
        {
            "check": "API keys",
            "status": "OK" if api.get("required_missing", 0) == 0 else "FAIL",
            "detail": f"{api.get('configured_count', 0)} configured; required missing {api.get('required_missing', 0)}; optional missing {api.get('optional_missing', 0)}",
        }
    )
    for kind in ("holdings", "activities"):
        item = csv.get(kind) or {}
        rows.append(
            {
                "check": f"{kind.title()} CSV",
                "status": "WARN" if item.get("stale") else "OK",
                "detail": f"{item.get('latest_path') or 'not found'}; age_hours={item.get('age_hours')}",
            }
        )
    rows.append(
        {
            "check": "Monthly budget",
            "status": "FAIL" if budget.get("hard_block") else "WARN" if budget.get("soft_warn") else "OK",
            "detail": budget.get("message") or "",
        }
    )
    if "demo_smoke" in payload:
        demo = payload["demo_smoke"]
        rows.append(
            {
                "check": "Demo smoke",
                "status": "OK" if demo.get("ok") else "FAIL",
                "detail": f"{sum(1 for row in demo.get('checks', []) if row.get('ok'))}/{len(demo.get('checks', []))} checks passed",
            }
        )
    return rows


def _next_action(payload: dict[str, Any]) -> str:
    update = payload.get("update") or {}
    api = payload.get("api_keys") or {}
    csv = payload.get("csv_freshness") or {}
    budget = payload.get("budget") or {}

    if api.get("required_missing", 0):
        return "Add ANTHROPIC_API_KEY in API_KEYS.txt or .env, then run API Checks again."
    if budget.get("hard_block"):
        return "Increase the monthly budget, wait for the next month, or rerun with --force if you accept the overage."
    holdings = csv.get("holdings") or {}
    if not holdings.get("latest_path"):
        return "Upload or select a Wealthsimple holdings-report CSV before running a paid report."
    if holdings.get("stale"):
        return "Export a fresh Wealthsimple holdings-report CSV before trading from the report."
    if update.get("available"):
        return f"Update to {update.get('latest_version')} after reviewing the release notes."
    if api.get("optional_missing", 0):
        return "Optional APIs are missing; the app can run, but analyst/news/macro coverage may be reduced."
    return "Ready for a report run."


def build_preflight(
    *,
    force_update: bool = False,
    live_api_checks: bool = False,
    include_demo_smoke: bool = False,
    simulated_current_version: str | None = None,
    timeout: float = 6.0,
) -> dict[str, Any]:
    """Build the doctor payload used by CLI and UI Diagnostics."""
    try:
        update_info = check_for_update(
            current_version=simulated_current_version,
            timeout=timeout,
            use_cache=not force_update,
        )
    except Exception as exc:  # noqa: BLE001
        update_info = UpdateInfo(current_version=simulated_current_version or APP_VERSION, error=str(exc))

    payload: dict[str, Any] = {
        "app_version": APP_VERSION,
        "simulated_current_version": simulated_current_version,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "update": _update_status(update_info),
        "workspace": _workspace_status(),
        "api_keys": _api_key_status(),
        "api_health": {"mode": "configured_keys", "checks": []},
        "csv_freshness": _csv_freshness(),
        "budget": _budget_status(),
    }

    if live_api_checks:
        try:
            from src.ui_support import check_connectivity

            payload["api_health"] = {"mode": "live", "checks": check_connectivity(timeout=timeout)}
        except Exception as exc:  # noqa: BLE001
            payload["api_health"] = {"mode": "live", "checks": [], "error": str(exc)}
    else:
        payload["api_health"]["checks"] = [
            {
                "source": row["source"],
                "ok": bool(row["configured"]) if row["required"] else True,
                "detail": row["status"],
                "required": row["required"],
            }
            for row in payload["api_keys"]["checks"]
        ]

    if include_demo_smoke:
        payload["demo_smoke"] = run_demo_smoke_test()

    payload["summary_rows"] = _summary_rows(payload)
    payload["next_action"] = _next_action(payload)
    return _as_jsonable(payload)


def doctor_text(payload: dict[str, Any]) -> str:
    lines = [f"tech_stock doctor v{payload.get('app_version')}"]
    for row in payload.get("summary_rows") or []:
        lines.append(f"- [{row.get('status')}] {row.get('check')}: {row.get('detail')}")
    if payload.get("next_action"):
        lines.append(f"Next action: {payload['next_action']}")
    return "\n".join(lines)


def cli_doctor(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run tech_stock preflight diagnostics.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--force-refresh", action="store_true", help="Bypass the update-check cache.")
    parser.add_argument("--live-api-checks", action="store_true", help="Run live connectivity probes for configured APIs.")
    parser.add_argument("--demo-smoke", action="store_true", help="Validate bundled demo data and UI view models without paid API calls.")
    parser.add_argument(
        "--simulate-current-version",
        metavar="VERSION",
        help="Run update diagnostics as if the installed app were VERSION, without applying an update.",
    )
    args = parser.parse_args(argv)

    payload = build_preflight(
        force_update=args.force_refresh,
        live_api_checks=args.live_api_checks,
        include_demo_smoke=args.demo_smoke,
        simulated_current_version=args.simulate_current_version,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(doctor_text(payload))
    return 0
