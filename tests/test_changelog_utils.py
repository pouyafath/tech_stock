"""Coverage for src.changelog_utils (v1.20 CHANGELOG parser)."""

from __future__ import annotations

import re

import pytest

from src import changelog_utils
from src.changelog_utils import (
    ChangelogSection,
    all_versions,
    latest_section,
    parse_section,
)


def _write_changelog(tmp_path, body: str):
    path = tmp_path / "CHANGELOG.md"
    path.write_text(body, encoding="utf-8")
    return path


# ── parse_section ──────────────────────────────────────────────────────────


def test_parse_section_returns_body_for_known_version(tmp_path):
    path = _write_changelog(
        tmp_path,
        """# Changelog

---

## [1.20.0] — 2026-05-27

### Added

- Thing one
- Thing two

---

## [1.19.0] — 2026-05-27

Old content.

---
""",
    )
    section = parse_section("1.20.0", path)
    assert section is not None
    assert section.version == "1.20.0"
    assert section.date == "2026-05-27"
    assert "Thing one" in section.body
    assert "Thing two" in section.body
    # The body must not bleed into the next section's header.
    assert "1.19.0" not in section.body


def test_parse_section_returns_none_for_unknown(tmp_path):
    path = _write_changelog(tmp_path, "# Changelog\n\n## [1.0.0] — 2026-01-01\n\nBody.\n")
    assert parse_section("9.9.9", path) is None


def test_parse_section_trims_trailing_separator(tmp_path):
    path = _write_changelog(
        tmp_path,
        """## [1.0.0] — 2026-01-01

Body.

---
""",
    )
    section = parse_section("1.0.0", path)
    assert section is not None
    # No trailing ``---`` in the parsed body
    assert not section.body.rstrip().endswith("---")


def test_parse_section_handles_hyphen_separator(tmp_path):
    path = _write_changelog(tmp_path, "## [1.0.0] - 2026-01-01\n\nHyphen body.\n")
    section = parse_section("1.0.0", path)
    assert section is not None
    assert "Hyphen" in section.body


def test_parse_section_recognises_prerelease_versions(tmp_path):
    path = _write_changelog(
        tmp_path,
        "## [1.20.0-rc.1] — 2026-05-27\n\nRelease candidate.\n",
    )
    section = parse_section("1.20.0-rc.1", path)
    assert section is not None
    assert "Release candidate" in section.body


# ── latest_section ──────────────────────────────────────────────────────────


def test_latest_section_returns_topmost(tmp_path):
    path = _write_changelog(
        tmp_path,
        """## [1.20.0] — 2026-05-27

Top.

## [1.19.0] — 2026-05-27

Older.
""",
    )
    section = latest_section(path)
    assert section is not None
    assert section.version == "1.20.0"
    assert "Top" in section.body


def test_latest_section_returns_none_for_empty_changelog(tmp_path):
    path = _write_changelog(tmp_path, "# Changelog\n\nNo entries yet.\n")
    assert latest_section(path) is None


# ── all_versions ───────────────────────────────────────────────────────────


def test_all_versions_returns_newest_first(tmp_path):
    path = _write_changelog(
        tmp_path,
        """## [1.20.0] — 2026-05-27
top.
## [1.19.1] — 2026-05-27
middle.
## [1.19.0] — 2026-05-27
bottom.
""",
    )
    versions = all_versions(path)
    assert versions == ["1.20.0", "1.19.1", "1.19.0"]


def test_all_versions_for_real_repo_changelog():
    """Smoke: the repo's actual CHANGELOG should round-trip."""
    versions = all_versions()
    assert len(versions) > 5
    # Versions must be sorted-newest first by appearance (we don't enforce
    # semver order — just that the parser found them in file order).
    assert all(re.match(r"^\d+\.\d+", v) for v in versions)


def test_parse_section_on_real_repo_changelog():
    section = parse_section("1.19.1")
    assert section is not None
    assert section.version == "1.19.1"
    assert section.body  # non-empty


# ── CLI surface (used by the release workflow) ────────────────────────────


def test_cli_main_returns_non_zero_for_unknown_version(monkeypatch):
    rc = changelog_utils._main(["never-existed-9.9.9"])
    assert rc == 1


def test_cli_main_returns_two_for_missing_args():
    rc = changelog_utils._main([])
    assert rc == 2


def test_cli_main_list_emits_one_version_per_line(capsys):
    rc = changelog_utils._main(["--list"])
    assert rc == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) > 0
    assert all(re.match(r"\d+\.\d+", line) for line in out)
