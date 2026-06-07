"""Tiny CHANGELOG.md parser used by the v1.20 release workflow.

The repo's CHANGELOG follows a strict Keep-a-Changelog-ish format:

    # Changelog

    All notable changes to this project are documented here.

    ---

    ## [1.19.1] — 2026-05-27

    ### ...
    ### ...

    ---

    ## [1.19.0] — 2026-05-27

    ...

This module extracts the body for a given version so the GitHub Release
workflow can publish accurate notes. Also exposes a tiny CLI:

    python -m src.changelog_utils 1.19.1
    python -m src.changelog_utils --latest

so the workflow can invoke it with a single line of bash.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHANGELOG = ROOT / "CHANGELOG.md"

# Matches a section header line, e.g. ``## [1.19.1] — 2026-05-27``.  The
# en-dash and hyphen are both accepted because earlier entries used `-`.
_HEADER_RE = re.compile(r"^##\s+\[(?P<version>[0-9][0-9a-zA-Z.\-+]*)\]\s*[—\-]\s*(?P<date>\S+)")


@dataclass(frozen=True)
class ChangelogSection:
    version: str
    date: str
    body: str  # markdown body, without the leading ``## [version] — date`` header

    @property
    def header(self) -> str:
        return f"## [{self.version}] — {self.date}"


def _load_lines(path: Path | None = None) -> list[str]:
    path = path or DEFAULT_CHANGELOG
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def _iter_sections(lines: list[str]):
    """Yield ``(version, date, start_idx, end_idx)`` for each ``##`` section.

    ``end_idx`` is exclusive — the index of the line *after* the section
    body, where the next ``##`` header or EOF begins.
    """
    headers: list[tuple[str, str, int]] = []
    for idx, line in enumerate(lines):
        match = _HEADER_RE.match(line)
        if match:
            headers.append((match.group("version"), match.group("date"), idx))
    for i, (version, date, start) in enumerate(headers):
        end = headers[i + 1][2] if i + 1 < len(headers) else len(lines)
        yield version, date, start, end


def parse_section(version: str, path: Path | None = None) -> ChangelogSection | None:
    """Return the body for ``version``. ``None`` if not found."""
    lines = _load_lines(path)
    for v, date, start, end in _iter_sections(lines):
        if v == version:
            body = "\n".join(lines[start + 1 : end]).strip()
            # Trim trailing "---" separator if present
            if body.endswith("---"):
                body = body.rsplit("---", 1)[0].rstrip()
            return ChangelogSection(version=v, date=date, body=body)
    return None


def latest_section(path: Path | None = None) -> ChangelogSection | None:
    """Return the topmost (most recent) entry in the file."""
    lines = _load_lines(path)
    for v, date, start, end in _iter_sections(lines):
        body = "\n".join(lines[start + 1 : end]).strip()
        if body.endswith("---"):
            body = body.rsplit("---", 1)[0].rstrip()
        return ChangelogSection(version=v, date=date, body=body)
    return None


def all_versions(path: Path | None = None) -> list[str]:
    """Return every version listed in the CHANGELOG, newest first."""
    return [v for v, _, _, _ in _iter_sections(_load_lines(path))]


# ── CLI used by the release workflow ──────────────────────────────────────


def _main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print("Usage: python -m src.changelog_utils <version> | --latest | --list", file=sys.stderr)
        return 2
    if argv[0] == "--list":
        for v in all_versions():
            print(v)
        return 0
    if argv[0] == "--latest":
        section = latest_section()
    else:
        section = parse_section(argv[0])
    if section is None:
        print(f"version not found: {argv[0]}", file=sys.stderr)
        return 1
    sys.stdout.write(section.body + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))


__all__ = ["ChangelogSection", "parse_section", "latest_section", "all_versions"]
