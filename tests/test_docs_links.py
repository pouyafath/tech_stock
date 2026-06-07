"""Validate internal markdown links in the project's maintained documentation.

CI fails if a docs link points at a file that doesn't exist — useful when
we move docs around or rename them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")

# Validate the user-facing and maintainer documentation that we own.
_TARGETS = [
    ROOT / "README.md",
    ROOT / "QUICKSTART.md",
    ROOT / "ANALYSIS_AND_SIGNALS.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "CHANGELOG.md",
    ROOT / "docs" / "ARCHITECTURE.md",
    ROOT / "docs" / "COOKBOOK.md",
    ROOT / "docs" / "RELEASE_PROCESS.md",
    ROOT / "docs" / "USER_GUIDE.md",
    ROOT / "docs" / "TROUBLESHOOTING.md",
    ROOT / "temporary_upload" / "README.md",
]


def _internal_links(text: str) -> list[str]:
    """Return non-external links: relative paths, not URLs."""
    out = []
    for href in _MARKDOWN_LINK_RE.findall(text):
        href = href.split("#", 1)[0].strip()  # drop anchor fragments
        if not href:
            continue
        if href.startswith(("http://", "https://", "mailto:")):
            continue
        out.append(href)
    return out


@pytest.mark.parametrize("path", _TARGETS, ids=lambda p: p.name)
def test_docs_file_exists(path):
    """Every docs path advertised by v1.20 must exist."""
    assert path.exists(), f"{path} should exist after the v1.20 docs split"


@pytest.mark.parametrize("path", _TARGETS, ids=lambda p: p.name)
def test_docs_internal_links_resolve(path):
    """Every internal markdown link in this file must point at a real file."""
    if not path.exists():
        pytest.skip(f"{path} missing — covered by another test")
    text = path.read_text(encoding="utf-8")
    for link in _internal_links(text):
        target = (path.parent / link).resolve()
        # Skip relative anchors handled by docs renderers, and ignore links
        # to directories (e.g. ``data/recommendations_log/``).
        if not target.exists():
            pytest.fail(f"{path.name}: broken link → {link} (resolved to {target})")


def test_readme_advertises_all_docs():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for advertised in (
        "QUICKSTART.md",
        "docs/USER_GUIDE.md",
        "docs/TROUBLESHOOTING.md",
        "ANALYSIS_AND_SIGNALS.md",
        "docs/ARCHITECTURE.md",
        "docs/COOKBOOK.md",
        "docs/RELEASE_PROCESS.md",
        "CONTRIBUTING.md",
        "CHANGELOG.md",
    ):
        assert advertised in text, f"README should advertise {advertised}"


def test_release_process_doc_references_changelog_parser():
    text = (ROOT / "docs" / "RELEASE_PROCESS.md").read_text(encoding="utf-8")
    assert "changelog_utils" in text


def test_architecture_doc_lists_v17_v18_v19_modules():
    text = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    # Names of modules introduced across v1.17-v1.19 that the architecture
    # doc must mention to be useful.
    expected_modules = [
        "src/observability.py",
        "src/performance_history.py",
        "src/backtester.py",
        "src/notifications.py",
        "src/scheduling.py",
        "src/onboarding.py",
        "src/cost_tracker.py",
        "src/preflight.py",
        "src/data_confidence.py",
        "src/workspace_export.py",
    ]
    missing = [m for m in expected_modules if m not in text]
    assert not missing, f"ARCHITECTURE.md doesn't reference: {missing}"


def test_contributing_doc_carries_design_tenets():
    text = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "Never silently swallow" in text
    assert "Additive schema" in text
    assert "Tests with every feature" in text


def test_cookbook_doc_covers_the_main_workflows():
    text = (ROOT / "docs" / "COOKBOOK.md").read_text(encoding="utf-8")
    for topic in ("demo", "Schedule", "budget", "Privacy"):
        assert topic in text, f"COOKBOOK.md should cover '{topic}'"
