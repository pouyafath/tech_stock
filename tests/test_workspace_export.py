"""Coverage for src.workspace_export (v1.19.1 zip-export helper)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest


@pytest.fixture
def isolated_workspace(monkeypatch, tmp_path):
    """Redirect the workspace root to a tmp_path with a realistic layout."""
    from src import workspace_export

    # Build a tiny fake workspace
    (tmp_path / "data" / "recommendations_log").mkdir(parents=True)
    (tmp_path / "data" / "recommendations_log" / "20260101_0930_morning.json").write_text("{}", encoding="utf-8")
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "20260101_morning.md").write_text("# report", encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "config" / ".env").write_text("ANTHROPIC_API_KEY=sk-secret", encoding="utf-8")
    (tmp_path / "data" / "thesis_log.json").write_text("{}", encoding="utf-8")
    (tmp_path / "data" / "cost_log.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "temporary_upload").mkdir(parents=True)
    (tmp_path / "temporary_upload" / "user-holdings.csv").write_text("ticker,qty\nNVDA,1", encoding="utf-8")
    (tmp_path / "API_KEYS.txt").write_text("secret", encoding="utf-8")

    monkeypatch.setattr(workspace_export, "ROOT", tmp_path)
    yield tmp_path


def test_export_workspace_produces_zip(isolated_workspace):
    from src.workspace_export import export_workspace

    result = export_workspace(output_dir=isolated_workspace / "exports")
    assert result.ok
    assert result.output_path is not None and result.output_path.exists()
    assert result.bytes_written > 0
    assert result.file_count >= 1


def test_export_excludes_env_file(isolated_workspace):
    from src.workspace_export import export_workspace

    result = export_workspace(output_dir=isolated_workspace / "exports")
    with zipfile.ZipFile(result.output_path) as zf:
        names = set(zf.namelist())
    # No secret should be in the zip
    assert "config/.env" not in names
    assert "API_KEYS.txt" not in names
    # But the harmless settings.json should be
    assert "config/settings.json" in names


def test_export_excludes_temporary_upload(isolated_workspace):
    from src.workspace_export import export_workspace

    result = export_workspace(output_dir=isolated_workspace / "exports")
    with zipfile.ZipFile(result.output_path) as zf:
        names = list(zf.namelist())
    # User CSV under temporary_upload must not appear
    assert all("temporary_upload" not in name for name in names)


def test_export_includes_recommendation_log(isolated_workspace):
    from src.workspace_export import export_workspace

    result = export_workspace(output_dir=isolated_workspace / "exports")
    with zipfile.ZipFile(result.output_path) as zf:
        assert "data/recommendations_log/20260101_0930_morning.json" in zf.namelist()


def test_export_includes_top_level_files(isolated_workspace):
    from src.workspace_export import export_workspace

    result = export_workspace(output_dir=isolated_workspace / "exports")
    with zipfile.ZipFile(result.output_path) as zf:
        names = zf.namelist()
    assert "data/thesis_log.json" in names
    assert "data/cost_log.jsonl" in names


def test_export_summary_text_well_formed(isolated_workspace):
    from src.workspace_export import export_summary_text, export_workspace

    result = export_workspace(output_dir=isolated_workspace / "exports")
    text = export_summary_text(result)
    assert "Exported" in text
    assert "files" in text
    assert "Excluded" in text


def test_export_failure_returns_useful_message(monkeypatch, tmp_path):
    """If the destination is unwritable, the function reports an error
    rather than raising."""
    from src import workspace_export

    monkeypatch.setattr(workspace_export, "ROOT", tmp_path)

    # Point output_dir at something that can't be created (a file masquerading
    # as a directory).  A pre-existing regular file at the dest path forces a
    # FileExistsError from mkdir.
    fake_dir = tmp_path / "blocking_file"
    fake_dir.write_text("not a directory", encoding="utf-8")

    # When export tries to mkdir the fake "blocking_file" path it will fail
    # because there's a regular file there.
    result = workspace_export.export_workspace(output_dir=fake_dir)
    assert result.ok is False
    assert result.error  # populated


def test_export_handles_missing_workspace_entirely(monkeypatch, tmp_path):
    from src import workspace_export

    # Brand-new empty workspace (no data/, no reports/, no config/) — must
    # still produce a valid (empty-ish) zip.
    monkeypatch.setattr(workspace_export, "ROOT", tmp_path)
    result = workspace_export.export_workspace(output_dir=tmp_path / "exports")
    assert result.ok
    # File count may be 0 but the zip itself exists.
    assert result.output_path is not None
    with zipfile.ZipFile(result.output_path) as zf:
        # No useful files, but the archive is well-formed.
        assert zf.testzip() is None
