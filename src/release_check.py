"""Release readiness checks for packaged tech_stock builds."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.version import APP_VERSION

ROOT = Path(__file__).resolve().parents[1]


EXPECTED_ASSETS = (
    {"name": "macOS DMG", "pattern": "tech_stock.dmg", "required": True},
    {"name": "Windows portable zip", "pattern": "tech_stock-windows.zip", "required": True},
    {"name": "Windows installer", "pattern": "tech_stock_setup.exe", "required": True},
    {"name": "Linux tarball", "pattern": f"tech_stock-{APP_VERSION}-linux-x86_64.tar.gz", "required": True},
    {"name": "Linux AppImage", "pattern": "tech_stock-*.AppImage", "required": False},
    {"name": "SHA256 checksums", "pattern": "SHA256SUMS.txt", "required": True},
)


def build_release_check(repo_root: str | Path | None = None, *, dist_dir: str | Path | None = None) -> dict[str, Any]:
    """Return a structured release-readiness report.

    Without ``dist_dir`` this performs static checks on release scripts.  With
    ``dist_dir`` it also verifies that packaged release assets exist and are
    non-empty.
    """
    root = Path(repo_root or ROOT)
    workflow_path = root / ".github" / "workflows" / "build_release.yml"
    linux_script_path = root / "build_linux.sh"
    workflow = _read(workflow_path)
    linux_script = _read(linux_script_path)

    static_checks = [
        _check(
            "release workflow creates draft releases",
            "draft: true" in workflow and "softprops/action-gh-release" in workflow,
            "Keep releases draft until artifacts are smoke-opened and checksums are verified.",
        ),
        _check(
            "release workflow publishes checksums",
            "SHA256SUMS.txt" in workflow and "sha256sum" in workflow,
            "Generate SHA256SUMS.txt before publishing release assets.",
        ),
        _check(
            "release workflow uploads Linux tarball",
            "tech_stock-linux-tarball" in workflow and "*.tar.gz" in workflow,
            "Upload the required Linux tarball artifact.",
        ),
        _check(
            "release workflow uploads AppImage when available",
            "tech_stock-linux" in workflow and "*.AppImage" in workflow,
            "Upload AppImage as an optional convenience artifact.",
        ),
        _check(
            "Linux build always creates tarball",
            "Packaging Linux tarball" in linux_script and "tar -C" in linux_script,
            "Create the Linux tarball independently from appimagetool availability.",
        ),
        _check(
            "Linux build keeps AppImage optional",
            "appimagetool" in linux_script and "skipping AppImage" in linux_script,
            "AppImage should not block the required tarball artifact.",
        ),
    ]

    asset_rows = []
    dist_checked = dist_dir is not None
    if dist_checked:
        dist = Path(dist_dir).expanduser()
        asset_rows = [_asset_row(dist, spec) for spec in EXPECTED_ASSETS]

    static_ok = all(row["ok"] for row in static_checks)
    required_assets_ok = True
    if dist_checked:
        required_assets_ok = all(row["ok"] for row in asset_rows if row["required"])
    ok = static_ok and required_assets_ok
    if not static_ok:
        next_action = "Fix the failing static release-script checks before tagging."
    elif dist_checked and not required_assets_ok:
        next_action = "Rebuild packages, then rerun release-check against the release directory."
    elif not dist_checked:
        next_action = "Run release-check --dist release/ after the workflow downloads and flattens artifacts."
    else:
        next_action = "Release checks passed. Smoke-open packages before publishing the draft release."

    return {
        "ok": ok,
        "version": APP_VERSION,
        "tag": f"v{APP_VERSION}",
        "repo_root": str(root),
        "dist_checked": dist_checked,
        "dist_dir": str(Path(dist_dir).expanduser()) if dist_dir else "",
        "static_checks": static_checks,
        "assets": asset_rows,
        "next_action": next_action,
    }


def cli_release_check(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check release packaging readiness.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--dist", type=Path, help="Optional release directory containing flattened artifacts.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if --dist required assets are missing.")
    args = parser.parse_args(argv)

    payload = build_release_check(dist_dir=args.dist)
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        _print_text(payload)

    if not payload["ok"] and (args.strict or not payload["dist_checked"]):
        return 1
    if args.strict and payload["dist_checked"] and not payload["ok"]:
        return 1
    return 0


def _print_text(payload: dict[str, Any]) -> None:
    verdict = "OK" if payload["ok"] else "REVIEW"
    print(f"tech_stock release check {payload['tag']} — {verdict}")
    print("")
    print("Static checks:")
    for row in payload["static_checks"]:
        print(f"- {'OK' if row['ok'] else 'FAIL'}: {row['name']}")
        if not row["ok"]:
            print(f"  Action: {row['action']}")
    if payload["dist_checked"]:
        print("")
        print("Assets:")
        for row in payload["assets"]:
            status = "OK" if row["ok"] else ("OPTIONAL" if not row["required"] else "MISSING")
            detail = row["path"] or row["pattern"]
            print(f"- {status}: {row['name']} ({detail})")
    print("")
    print(f"Next action: {payload['next_action']}")


def _asset_row(dist: Path, spec: dict[str, Any]) -> dict[str, Any]:
    matches = sorted(dist.glob(spec["pattern"]))
    path = next((item for item in matches if item.is_file() and item.stat().st_size > 0), None)
    return {
        "name": spec["name"],
        "pattern": spec["pattern"],
        "required": bool(spec["required"]),
        "ok": path is not None or not spec["required"],
        "path": str(path) if path else "",
        "size_bytes": path.stat().st_size if path else 0,
    }


def _check(name: str, ok: bool, action: str) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "action": "" if ok else action}


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


if __name__ == "__main__":
    raise SystemExit(cli_release_check())
