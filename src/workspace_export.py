"""Workspace-export-as-zip helper (v1.19.1).

Promised by the v1.19 Privacy card. Lets the user produce a single zip
containing everything tech_stock has written under the project root —
useful for migrating to a new machine, sharing with support, or just
auditing what the app stores.

Design choices
--------------
* **Strip secrets.** API keys live in ``config/.env`` and inside any
  ``API_KEYS.txt`` files. We drop those entirely from the zip. Same for
  the temporary upload folder (which may contain Wealthsimple CSVs the
  user doesn't want to share).
* **Pure read.** Never raises; missing source files are silently skipped.
* **Deterministic structure.** All paths inside the zip are relative to
  the workspace root so the user can extract anywhere and the relative
  layout still works.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from pathlib import Path

from src.observability import _redact

ROOT = Path(__file__).resolve().parents[1]


# Paths to include verbatim if they exist.
_INCLUDE_TREES: tuple[str, ...] = (
    "data/recommendations_log",
    "data/samples",
    "reports",
    "config",
    "logs",
)

_INCLUDE_FILES: tuple[str, ...] = (
    "data/thesis_log.json",
    "data/decision_journal.json",
    "data/paper_portfolio.json",
    "data/cost_log.jsonl",
    "CHANGELOG.md",
    "README.md",
)

# Paths to skip even when they sit inside an _INCLUDE_TREES entry.
_EXCLUDE_NAMES: frozenset[str] = frozenset(
    {
        # Secrets
        ".env",
        ".env.example",
        ".env.zip",
        "API_KEYS.txt",
        "API_KEYS.template.txt",
        # User CSVs
        "temporary_upload",
        # Caches
        ".cache",
        "__pycache__",
    }
)


@dataclass(frozen=True)
class ExportResult:
    ok: bool
    bytes_written: int
    file_count: int
    excluded: int
    output_path: Path | None
    error: str | None = None


def export_workspace(*, output_dir: Path | None = None) -> ExportResult:
    """Write a zip of the user's workspace to ``output_dir``.

    Default destination is ``<workspace>/exports/`` so the user can find
    the zip via Open Workspace. Returns an ``ExportResult`` summary; never
    raises.
    """
    dest_dir = output_dir or (ROOT / "exports")
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return ExportResult(ok=False, bytes_written=0, file_count=0, excluded=0, output_path=None, error=str(exc))

    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    output = dest_dir / f"tech_stock_workspace_{stamp}.zip"

    file_count = 0
    excluded = 0
    try:
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
            for tree in _INCLUDE_TREES:
                src = ROOT / tree
                if not src.exists():
                    continue
                for path in src.rglob("*"):
                    if not path.is_file():
                        continue
                    if _is_excluded(path):
                        excluded += 1
                        continue
                    if _looks_like_secret(path):
                        excluded += 1
                        continue
                    arcname = path.relative_to(ROOT).as_posix()
                    _write_scrubbed(zf, path, arcname)
                    file_count += 1
            for filename in _INCLUDE_FILES:
                src = ROOT / filename
                if not src.exists() or not src.is_file():
                    continue
                if _looks_like_secret(src):
                    excluded += 1
                    continue
                _write_scrubbed(zf, src, src.relative_to(ROOT).as_posix())
                file_count += 1
    except (OSError, zipfile.BadZipFile) as exc:
        return ExportResult(ok=False, bytes_written=0, file_count=0, excluded=excluded, output_path=None, error=str(exc))

    return ExportResult(
        ok=True,
        bytes_written=output.stat().st_size,
        file_count=file_count,
        excluded=excluded,
        output_path=output,
    )


def _is_excluded(path: Path) -> bool:
    """Return True if any path component is in the exclusion set."""
    parts = path.relative_to(ROOT).parts
    return any(part in _EXCLUDE_NAMES for part in parts)


def _looks_like_secret(path: Path) -> bool:
    """Best-effort secret detector — names that look key-ish are skipped.

    Matches by prefix/substring rather than exact name so renamed/variant key
    files (.env.local, .env.production, API_KEYS.backup.txt, my_secrets.json)
    are also dropped, not just the canonical names.
    """
    name = path.name.lower()
    if name.startswith(".env") or name.startswith("api_keys") or name.startswith("api-keys"):
        return True
    if any(token in name for token in ("secret", "credential", "password")):
        return True
    if name.endswith(".pem") or name.endswith(".key"):
        return True
    return False


# Text file types we scrub line-by-line for pasted secrets before zipping.
_TEXT_SUFFIXES: frozenset[str] = frozenset({".json", ".jsonl", ".txt", ".md", ".csv", ".yaml", ".yml", ".ini", ".cfg", ".log", ".env"})


def _write_scrubbed(zf: zipfile.ZipFile, path: Path, arcname: str) -> None:
    """Write a file into the zip, redacting key-shaped strings from text files.

    A user may paste an API key into an otherwise-innocent config/notes file
    (e.g. config/settings.json). Name-based exclusion can't catch that, so text
    files are content-scrubbed via the shared redactor. Non-text/binary files
    and any that can't be decoded are written verbatim.
    """
    if path.suffix.lower() in _TEXT_SUFFIXES:
        try:
            text = path.read_text(encoding="utf-8")
            zf.writestr(arcname, _redact(text))
            return
        except (OSError, UnicodeDecodeError):
            pass
    zf.write(path, arcname)


def export_summary_text(result: ExportResult) -> str:
    """Human-friendly one-paragraph summary for UI status lines."""
    if not result.ok:
        return f"Export failed: {result.error or 'unknown error'}"
    size_kb = result.bytes_written / 1024
    return f"✓ Exported {result.file_count} files ({size_kb:,.1f} KB) → {result.output_path}. Excluded {result.excluded} secret/transient files."


__all__ = [
    "ExportResult",
    "export_workspace",
    "export_summary_text",
]
