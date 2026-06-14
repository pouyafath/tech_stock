"""Setup readiness and redacted support-bundle helpers.

This module is intentionally UI-agnostic. Desktop, Streamlit, Textual, and
CLI can all ask the same questions:

* Is the app ready for a paid run?
* Which Wealthsimple CSVs did we find, and which one should the user confirm?
* Can we export enough diagnostic context for support without leaking secrets?
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.csv_health import inspect_csv
from src.data_files import (
    build_pre_run_checklist,
    csv_search_dirs,
    data_files_view,
    discover_csv_candidates,
    selected_data_files,
)
from src.onboarding import current_state, demo_snapshot, stage_guidance
from src.preflight import build_preflight, run_demo_smoke_test
from src.version import APP_VERSION

_SECRET_RE = re.compile(r"(sk-ant-[A-Za-z0-9_\-]+|[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,})")
_DATE_RE = re.compile(r"(20\d{2})[-_]?([01]\d)[-_]?([0-3]\d)")


@dataclass(frozen=True)
class SupportBundleResult:
    ok: bool
    output_path: Path | None
    bytes_written: int = 0
    file_count: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


SUPPORT_BUNDLE_FILES = [
    {
        "path": "support/doctor.json",
        "description": "Doctor/preflight status: version, update cache, workspace, API-key discovery, CSV freshness, budget, release assets.",
        "privacy": "Contains only API-key presence/status, never raw key values.",
    },
    {
        "path": "support/setup_readiness.json",
        "description": "First-run readiness, paid-run checklist, and CSV candidate metadata.",
        "privacy": "Contains CSV filenames, paths, schema summaries, row-count hints, and freshness; no raw CSV contents.",
    },
    {
        "path": "support/data_files.json",
        "description": "Workspace folders, selected CSV defaults, report/log/upload paths, and API key search paths.",
        "privacy": "Path metadata only.",
    },
    {
        "path": "support/diagnostics.jsonl",
        "description": "Recent structured diagnostic events from logs/diagnostics.jsonl.",
        "privacy": "Secret-like tokens are redacted before writing.",
    },
    {
        "path": "support/README.txt",
        "description": "Plain-language privacy notes for the support bundle.",
        "privacy": "No app data.",
    },
]

SUPPORT_BUNDLE_EXCLUSIONS = [
    "API_KEYS.txt",
    ".env",
    ".env.zip",
    "raw Wealthsimple holdings/activity CSV contents",
    "generated report markdown",
    "generated recommendation JSON logs",
    "browser cookies, OS keychain entries, and unrelated local files",
]


def csv_choice_rows(kind: str, *, limit: int = 12) -> list[dict[str, Any]]:
    """Return inspectable CSV candidates for a user confirmation table."""
    if kind not in {"holdings", "activities"}:
        raise ValueError("kind must be 'holdings' or 'activities'")

    selected = selected_data_files().get(kind)
    paths: list[Path] = []
    if selected:
        paths.append(Path(selected))
    paths.extend(discover_csv_candidates(kind, limit=limit))

    rows: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = Path(path).expanduser()
        key = resolved.resolve() if resolved.exists() else resolved
        if key in seen:
            continue
        seen.add(key)
        inspection = inspect_csv(resolved, expected_kind=kind)
        age = _age_hours(resolved)
        status, reason = _csv_choice_status(inspection.to_dict(), age)
        rows.append(
            {
                "kind": kind,
                "recommended": False,
                "selected": bool(selected and Path(selected).expanduser() == resolved),
                "status": status,
                "reason": reason,
                "path": str(resolved),
                "filename": resolved.name,
                "filename_date": _date_from_filename(resolved.name),
                "modified": _modified_iso(resolved),
                "age_hours": age,
                "schema_kind": inspection.kind,
                "confidence": inspection.confidence,
                "row_count_hint": inspection.row_count_hint,
                "is_sample": inspection.is_sample,
                "swapped": inspection.swapped,
                "ok_for_expected": inspection.ok_for_expected,
                "action": inspection.action,
            }
        )

    _mark_recommended(rows, required=(kind == "holdings"))
    return rows


def setup_readiness_view(
    *,
    include_demo_smoke: bool = False,
    force_update: bool = False,
    timeout: float = 4.0,
) -> dict[str, Any]:
    """Build a compact first-run/setup status payload."""
    state = current_state()
    selected = selected_data_files()
    checklist = build_pre_run_checklist(
        holdings_csv=selected.get("holdings"),
        activities_csv=selected.get("activities"),
        use_fallback_config=False,
        dry_run=False,
        timeout=timeout,
    )
    try:
        preflight = build_preflight(
            force_update=force_update,
            live_api_checks=False,
            include_demo_smoke=include_demo_smoke,
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001
        preflight = {"summary_rows": [{"check": "Preflight", "status": "FAIL", "detail": str(exc)}], "next_action": str(exc)}

    demo = demo_snapshot()
    version_summary = _preflight_summary_row(preflight, "Version")
    update_cache_summary = _preflight_summary_row(preflight, "Update cache")
    rows = [
        {
            "check": "Onboarding",
            "status": "OK" if state.is_complete else "WARN",
            "detail": "Completed" if state.is_complete else f"Current stage: {state.stage}",
            "action": "" if state.is_complete else stage_guidance(state.stage).primary_action,
        },
        {
            "check": "Workspace",
            "status": _workspace_status(preflight),
            "detail": _workspace_detail(preflight),
            "action": "" if _workspace_status(preflight) == "OK" else "Choose a writable workspace or fix folder permissions.",
        },
        {
            "check": "Update status",
            "status": _summary_status(version_summary),
            "detail": version_summary.get("detail") or "No update status available.",
            "action": "Open Updates or run python src/main.py update." if version_summary.get("status") == "UPDATE" else "",
        },
        {
            "check": "Update cache",
            "status": _summary_status(update_cache_summary),
            "detail": update_cache_summary.get("detail") or "No update-cache status available.",
            "action": "Use setup --force-refresh or the Updates tab force refresh."
            if update_cache_summary.get("status") == "STALE"
            else "",
        },
        {
            "check": "API keys",
            "status": "FAIL" if (preflight.get("api_keys") or {}).get("required_missing") else "OK",
            "detail": _api_key_detail(preflight),
            "action": "Add ANTHROPIC_API_KEY in API_KEYS.txt or .env." if (preflight.get("api_keys") or {}).get("required_missing") else "",
        },
        *_checklist_rows(checklist),
        {
            "check": "Demo smoke",
            "status": "OK" if demo.available else "FAIL",
            "detail": "Bundled demo files are available." if demo.available else "Bundled demo files are missing.",
            "action": "" if demo.available else "Reinstall the app or run from a complete source checkout.",
        },
    ]
    if include_demo_smoke:
        smoke = run_demo_smoke_test()
        rows.append(
            {
                "check": "Demo smoke run",
                "status": "OK" if smoke.get("ok") else "FAIL",
                "detail": f"{sum(1 for row in smoke.get('checks', []) if row.get('ok'))}/{len(smoke.get('checks', []))} checks passed",
                "action": "" if smoke.get("ok") else "Open Diagnostics and export a support bundle.",
            }
        )

    status = (
        "READY"
        if all(row["status"] in {"OK", "SKIP"} for row in rows)
        else "BLOCKED"
        if any(row["status"] == "FAIL" for row in rows)
        else "REVIEW"
    )
    return _jsonable(
        {
            "app_version": APP_VERSION,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "status": status,
            "next_action": _setup_next_action(rows, preflight.get("next_action") or ""),
            "onboarding": {
                "stage": state.stage,
                "completed": state.completed,
                "is_complete": state.is_complete,
                "stamped_at": state.stamped_at,
                "skipped_demo": state.skipped_demo,
            },
            "selected_files": selected,
            "rows": rows,
            "csv_choices": {
                "holdings": csv_choice_rows("holdings"),
                "activities": csv_choice_rows("activities"),
            },
            "pre_run_checklist": checklist,
            "preflight_summary": preflight.get("summary_rows") or [],
        }
    )


def paid_run_readiness_view(
    *,
    holdings_csv: str | Path | None = None,
    activities_csv: str | Path | None = None,
    use_fallback_config: bool = False,
    dry_run: bool = False,
    model_choice: str | None = "sonnet",
    budget_usd: float | None = None,
    budget_cad: float | None = None,
    timeout: float = 4.0,
) -> dict[str, Any]:
    """Convert the pre-run checklist into a compact run/no-run guide."""
    checklist = build_pre_run_checklist(
        holdings_csv=holdings_csv,
        activities_csv=activities_csv,
        use_fallback_config=use_fallback_config,
        dry_run=dry_run,
        timeout=timeout,
    )
    rows = list(checklist.get("rows") or [])
    warning_rows = [row for row in rows if row.get("status") == "WARN"]
    blocking_rows = [row for row in rows if row.get("blocking")]
    if blocking_rows:
        status = "BLOCKED"
        primary_action = checklist.get("next_action") or "Fix blocking checklist items before running."
        summary = f"{len(blocking_rows)} blocking issue(s) must be fixed before a paid run."
    elif warning_rows:
        status = "REVIEW_FIRST"
        primary_action = "Review warning rows and run only if you accept the reduced coverage or stale-data risk."
        summary = f"Ready with {len(warning_rows)} warning(s). Paid run is allowed, but review first."
    else:
        status = "READY"
        primary_action = "Run report."
        summary = "Ready for a paid Claude report run."

    run_mode = "Dry run / demo smoke" if dry_run else "Paid Claude report"
    spend_detail = "No Claude spend." if dry_run else "Uses Anthropic credits; current Sonnet baseline is about $0.22/run."
    if not dry_run and (budget_usd or budget_cad):
        spend_detail += f" User budget input: ${float(budget_usd or 0):,.0f} USD / ${float(budget_cad or 0):,.0f} CAD."
    steps = [
        {
            "step": "Run mode",
            "status": "SKIP" if dry_run else "OK",
            "detail": f"{run_mode}; model={model_choice or 'default'}. {spend_detail}",
            "action": "",
        },
        *_readiness_steps(rows),
    ]
    return _jsonable(
        {
            "app_version": APP_VERSION,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "status": status,
            "can_run": bool(checklist.get("can_run")),
            "requires_warning_confirmation": bool(checklist.get("can_run") and warning_rows and not dry_run),
            "blocking_count": len(blocking_rows),
            "warning_count": len(warning_rows),
            "summary": summary,
            "primary_action": primary_action,
            "next_action": primary_action,
            "checklist": checklist,
            "steps": steps,
        }
    )


def support_bundle_payload(*, include_demo_smoke: bool = False, force_update: bool = True) -> dict[str, Any]:
    """Return a redacted JSON payload suitable for support tickets."""
    from src.observability import support_bundle as diagnostics_jsonl

    setup = setup_readiness_view(include_demo_smoke=include_demo_smoke, force_update=force_update)
    doctor = build_preflight(force_update=force_update, live_api_checks=False, include_demo_smoke=include_demo_smoke)
    files = data_files_view()
    diagnostics_text = diagnostics_jsonl(limit=500)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "app_version": APP_VERSION,
        "doctor": doctor,
        "setup_readiness": setup,
        "data_files": files,
        "csv_search_dirs": [str(path) for path in csv_search_dirs()],
        "diagnostics_jsonl": diagnostics_text,
        "notes": [
            "This support bundle intentionally excludes API_KEYS.txt, .env, .env.zip, and raw Wealthsimple CSV contents.",
            "CSV entries include only filenames, schema summaries, row counts, freshness, and action text.",
        ],
    }
    return _redact(_jsonable(payload))


def support_bundle_preview(*, include_demo_smoke: bool = False) -> dict[str, Any]:
    """Describe support-bundle contents before writing a zip file."""
    files = [dict(row) for row in SUPPORT_BUNDLE_FILES]
    if include_demo_smoke:
        files[1]["description"] += " Includes bundled demo-smoke results."
    return _jsonable(
        {
            "app_version": APP_VERSION,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "file_count": len(files),
            "files": files,
            "excluded": SUPPORT_BUNDLE_EXCLUSIONS,
            "safe_to_share": True,
            "privacy_note": "The export is redacted and excludes raw API key files, raw CSV contents, generated reports, and unrelated local files.",
        }
    )


def export_support_bundle(*, output_dir: str | Path | None = None, include_demo_smoke: bool = False) -> SupportBundleResult:
    """Write a redacted setup/support zip and return its path."""
    from src import main

    dest = Path(output_dir).expanduser() if output_dir else main.ROOT / "exports"
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return SupportBundleResult(ok=False, output_path=None, error=str(exc))

    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    output = dest / f"tech_stock_support_{stamp}.zip"
    payload = support_bundle_payload(include_demo_smoke=include_demo_smoke)
    files = {
        "support/doctor.json": json.dumps(payload.get("doctor") or {}, indent=2, sort_keys=True),
        "support/setup_readiness.json": json.dumps(payload.get("setup_readiness") or {}, indent=2, sort_keys=True),
        "support/data_files.json": json.dumps(payload.get("data_files") or {}, indent=2, sort_keys=True),
        "support/diagnostics.jsonl": str(payload.get("diagnostics_jsonl") or ""),
        "support/README.txt": "\n".join(payload.get("notes") or []),
    }
    try:
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
            for arcname, text in files.items():
                zf.writestr(arcname, _redact_text(text) + ("\n" if text and not text.endswith("\n") else ""))
    except (OSError, zipfile.BadZipFile) as exc:
        return SupportBundleResult(ok=False, output_path=None, error=str(exc))
    return SupportBundleResult(ok=True, output_path=output, bytes_written=output.stat().st_size, file_count=len(files))


def support_bundle_summary_text(result: SupportBundleResult) -> str:
    if not result.ok:
        return f"Support bundle export failed: {result.error or 'unknown error'}"
    return f"Exported support bundle ({result.file_count} files, {result.bytes_written / 1024:,.1f} KB): {result.output_path}"


def support_bundle_preview_text(preview: dict[str, Any]) -> str:
    lines = [
        f"tech_stock support bundle preview v{preview.get('app_version')} — {preview.get('file_count', 0)} files",
        preview.get("privacy_note") or "Redacted support bundle.",
        "",
        "Included:",
    ]
    for item in preview.get("files") or []:
        lines.append(f"- {item.get('path')}: {item.get('description')} Privacy: {item.get('privacy')}")
    lines.append("")
    lines.append("Excluded:")
    for item in preview.get("excluded") or []:
        lines.append(f"- {item}")
    return "\n".join(lines)


def setup_readiness_text(view: dict[str, Any]) -> str:
    lines = [f"tech_stock setup readiness v{view.get('app_version')} — {view.get('status')}"]
    for row in view.get("rows") or []:
        action = f" Action: {row.get('action')}" if row.get("action") else ""
        lines.append(f"- [{row.get('status')}] {row.get('check')}: {row.get('detail')}{action}")
    if view.get("next_action"):
        lines.append(f"Next action: {view['next_action']}")
    return "\n".join(lines)


def cli_setup(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show first-run/setup readiness.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--demo-smoke", action="store_true", help="Run no-spend bundled demo smoke checks.")
    parser.add_argument("--force-refresh", action="store_true", help="Bypass the update-check cache.")
    args = parser.parse_args(argv)
    view = setup_readiness_view(include_demo_smoke=args.demo_smoke, force_update=args.force_refresh)
    print(json.dumps(view, indent=2, sort_keys=True) if args.json else setup_readiness_text(view))
    return 0


def cli_support_bundle(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a redacted support bundle zip.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--output-dir", type=Path, help="Directory for the support zip. Defaults to <workspace>/exports.")
    parser.add_argument("--demo-smoke", action="store_true", help="Include no-spend demo smoke output in the support payload.")
    parser.add_argument("--preview", action="store_true", help="Show the redacted bundle contents without writing a zip.")
    args = parser.parse_args(argv)
    if args.preview:
        preview = support_bundle_preview(include_demo_smoke=args.demo_smoke)
        print(json.dumps(preview, indent=2, sort_keys=True) if args.json else support_bundle_preview_text(preview))
        return 0
    result = export_support_bundle(output_dir=args.output_dir, include_demo_smoke=args.demo_smoke)
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True) if args.json else support_bundle_summary_text(result))
    return 0 if result.ok else 1


def _readiness_steps(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for row in rows:
        status = "BLOCKED" if row.get("blocking") else row.get("status") or ""
        steps.append(
            {
                "step": row.get("check") or "",
                "status": status,
                "detail": row.get("detail") or "",
                "action": row.get("action") or "",
            }
        )
    return steps


def _checklist_rows(checklist: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in checklist.get("rows") or []:
        rows.append(
            {
                "check": row.get("check") or "",
                "status": "FAIL" if row.get("blocking") else row.get("status") or "",
                "detail": row.get("detail") or "",
                "action": row.get("action") or "",
            }
        )
    return rows


def _csv_choice_status(inspection: dict[str, Any], age_hours: float | None) -> tuple[str, str]:
    if not inspection.get("exists"):
        return "MISSING", "File does not exist."
    if not inspection.get("readable"):
        return "BLOCKED", "File cannot be read."
    if inspection.get("swapped"):
        return "BLOCKED", "This file belongs in the other CSV field."
    if inspection.get("is_sample"):
        return "DEMO_ONLY", "Sample/demo CSV; use only for demo mode."
    if not inspection.get("ok_for_expected"):
        return "BLOCKED", "; ".join(inspection.get("issues") or []) or inspection.get("action") or "Schema is incomplete."
    if age_hours is not None and age_hours > 72:
        return "REVIEW", f"Looks valid but is {age_hours:.1f} hours old."
    return "READY", "Looks like the correct Wealthsimple export."


def _mark_recommended(rows: list[dict[str, Any]], *, required: bool) -> None:
    for row in rows:
        if row["status"] == "READY" and not row["is_sample"]:
            row["recommended"] = True
            return
    if not required:
        return
    for row in rows:
        if row["status"] == "REVIEW" and not row["is_sample"]:
            row["recommended"] = True
            return


def _setup_next_action(rows: list[dict[str, Any]], fallback: str) -> str:
    for row in rows:
        if row.get("status") == "FAIL" and row.get("action"):
            return row["action"]
    for row in rows:
        if row.get("status") == "WARN" and row.get("action"):
            return row["action"]
    return fallback or "Ready for a report run."


def _workspace_status(preflight: dict[str, Any]) -> str:
    writable = (preflight.get("workspace") or {}).get("writable") or {}
    if not writable:
        return "WARN"
    return "OK" if all(bool(value) for value in writable.values()) else "FAIL"


def _workspace_detail(preflight: dict[str, Any]) -> str:
    workspace = ((preflight.get("workspace") or {}).get("locations") or {}).get("workspace") or ""
    writable = (preflight.get("workspace") or {}).get("writable") or {}
    bad = [key for key, value in writable.items() if not value]
    return f"{workspace}; not writable: {', '.join(bad)}" if bad else str(workspace)


def _api_key_detail(preflight: dict[str, Any]) -> str:
    api = preflight.get("api_keys") or {}
    return f"{api.get('configured_count', 0)} configured; required missing {api.get('required_missing', 0)}; optional missing {api.get('optional_missing', 0)}"


def _preflight_summary_row(preflight: dict[str, Any], check: str) -> dict[str, Any]:
    for row in preflight.get("summary_rows") or []:
        if row.get("check") == check:
            return row
    return {}


def _summary_status(row: dict[str, Any]) -> str:
    status = str(row.get("status") or "").upper()
    if not status:
        return "WARN"
    if status in {"OK", "PASS"}:
        return "OK"
    if status in {"FAIL", "BLOCKED"}:
        return "FAIL"
    return "WARN"


def _age_hours(path: Path) -> float | None:
    try:
        if not path.exists():
            return None
        return round((datetime.now(UTC).timestamp() - path.stat().st_mtime) / 3600, 2)
    except OSError:
        return None


def _modified_iso(path: Path) -> str:
    try:
        if not path.exists():
            return ""
        return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    except OSError:
        return ""


def _date_from_filename(name: str) -> str:
    match = _DATE_RE.search(name)
    if not match:
        return ""
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in {"api_key", "apikey", "value", "raw", "secret", "token", "password"} or lowered.endswith(
                ("_secret", "_token", "_password")
            ):
                redacted[str(key)] = "<redacted>"
            else:
                redacted[str(key)] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _redact_text(text: str) -> str:
    return _SECRET_RE.sub("<redacted>", text)


__all__ = [
    "SupportBundleResult",
    "csv_choice_rows",
    "paid_run_readiness_view",
    "setup_readiness_view",
    "setup_readiness_text",
    "support_bundle_payload",
    "support_bundle_preview",
    "support_bundle_preview_text",
    "export_support_bundle",
    "support_bundle_summary_text",
    "cli_setup",
    "cli_support_bundle",
]
