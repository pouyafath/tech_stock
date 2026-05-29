"""Static validation of the v1.20 release workflow YAML.

We can't actually run GitHub Actions in pytest, so these tests parse the
YAML and assert structural properties: the test gate exists, the build
matrix has all three platforms, the release job depends on every build
job, etc.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "build_release.yml"


@pytest.fixture
def data():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


# ── Trigger ────────────────────────────────────────────────────────────────


def test_workflow_triggers_on_tag_push(data):
    # YAML's reserved `on` key parses to True in PyYAML's safe_load by default.
    triggers = data.get("on") or data.get(True)
    assert triggers is not None
    assert "push" in triggers
    assert "v*.*.*" in triggers["push"]["tags"]


def test_workflow_supports_workflow_dispatch(data):
    triggers = data.get("on") or data.get(True)
    # workflow_dispatch may parse to None when no inputs are listed.
    assert "workflow_dispatch" in triggers


# ── Jobs ──────────────────────────────────────────────────────────────────


def test_workflow_has_required_jobs(data):
    expected = {"test-gate", "build-macos", "build-windows", "build-linux", "release"}
    assert expected.issubset(set(data["jobs"].keys()))


def test_test_gate_matrix_covers_three_platforms(data):
    matrix = data["jobs"]["test-gate"]["strategy"]["matrix"]
    oses = set(matrix["os"])
    assert "macos-14" in oses
    assert "windows-latest" in oses
    assert "ubuntu-22.04" in oses


def test_test_gate_runs_pytest_and_ruff(data):
    steps = data["jobs"]["test-gate"]["steps"]
    step_names = [s.get("name", "") for s in steps]
    assert any("Pytest" in name or "pytest" in name for name in step_names)
    assert any("Ruff lint" in name for name in step_names)
    assert any("Ruff format" in name for name in step_names)


def test_build_jobs_depend_on_test_gate(data):
    for job in ("build-macos", "build-windows", "build-linux"):
        needs = data["jobs"][job].get("needs")
        assert needs == "test-gate", f"{job} should require test-gate, got {needs}"


def test_release_job_depends_on_every_build(data):
    needs = data["jobs"]["release"]["needs"]
    assert set(needs) == {"build-macos", "build-windows", "build-linux"}


def test_release_job_only_runs_on_tag_push(data):
    if_clause = data["jobs"]["release"].get("if", "")
    assert "refs/tags/" in if_clause


def test_release_job_has_contents_write_permission(data):
    permissions = data["jobs"]["release"].get("permissions") or {}
    assert permissions.get("contents") == "write"


# ── Step-level checks ──────────────────────────────────────────────────────


def test_release_step_uses_changelog_parser(data):
    steps = data["jobs"]["release"]["steps"]
    run_scripts = " ".join(step.get("run", "") for step in steps if step.get("run"))
    assert "src.changelog_utils" in run_scripts


def test_release_step_generates_checksums(data):
    steps = data["jobs"]["release"]["steps"]
    run_scripts = " ".join(step.get("run", "") for step in steps if step.get("run"))
    assert "sha256sum" in run_scripts
    assert "SHA256SUMS.txt" in run_scripts


def test_release_uses_action_gh_release_v2(data):
    steps = data["jobs"]["release"]["steps"]
    actions = [step.get("uses", "") for step in steps if step.get("uses")]
    assert any("softprops/action-gh-release@v2" in use for use in actions)


def test_release_publishes_as_draft(data):
    steps = data["jobs"]["release"]["steps"]
    for step in steps:
        if step.get("uses", "").startswith("softprops/action-gh-release"):
            with_block = step.get("with") or {}
            assert with_block.get("draft") is True
            break
    else:
        pytest.fail("No softprops/action-gh-release step found")


def test_release_uploads_platform_artifacts_and_checksums(data):
    steps = data["jobs"]["release"]["steps"]
    for step in steps:
        if step.get("uses", "").startswith("softprops/action-gh-release"):
            files = (step.get("with") or {}).get("files", "")
            assert "*.dmg" in files
            assert "*.zip" in files
            assert "*.exe" in files
            assert "*.AppImage" in files
            assert "*.tar.gz" in files
            assert "SHA256SUMS.txt" in files
            break
    else:
        pytest.fail("No softprops/action-gh-release step found")


def test_macos_step_packages_dmg(data):
    macos_steps = data["jobs"]["build-macos"]["steps"]
    run_block = " ".join(step.get("run", "") for step in macos_steps if step.get("run"))
    assert "hdiutil" in run_block
    assert ".dmg" in run_block


def test_windows_step_runs_inno_setup(data):
    win_steps = data["jobs"]["build-windows"]["steps"]
    run_block = " ".join(step.get("run", "") for step in win_steps if step.get("run"))
    assert "iscc" in run_block
    assert "/DAppVersion" in run_block


def test_linux_step_runs_build_linux_sh(data):
    linux_steps = data["jobs"]["build-linux"]["steps"]
    run_block = " ".join(step.get("run", "") for step in linux_steps if step.get("run"))
    assert "build_linux.sh" in run_block
