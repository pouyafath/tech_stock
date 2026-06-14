import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

from src import setup_readiness

HOLDINGS_HEADER = "Symbol,Quantity,Market Price,Market Price Currency,Book Value (Market),Market Value,Market Unrealized Returns"


def test_csv_choice_rows_recommends_valid_non_sample_candidate(monkeypatch, tmp_path):
    stale = tmp_path / "holdings-report-2026-01-01.csv"
    fresh = tmp_path / "holdings-report-2026-06-14.csv"
    sample = tmp_path / "holdings-report-sample.csv"
    for path in (stale, fresh, sample):
        path.write_text(f"{HOLDINGS_HEADER}\nNVDA,1,100,USD,90,100,10\n", encoding="utf-8")
    old_mtime = 1_704_067_200
    stale.touch()
    sample.touch()
    fresh.touch()
    import os

    os.utime(stale, (old_mtime, old_mtime))

    monkeypatch.setattr(setup_readiness, "selected_data_files", lambda: {"holdings": stale, "activities": None})
    monkeypatch.setattr(setup_readiness, "discover_csv_candidates", lambda kind, limit=12: [sample, fresh, stale])

    rows = setup_readiness.csv_choice_rows("holdings")

    recommended = [row for row in rows if row["recommended"]]
    assert len(recommended) == 1
    assert recommended[0]["path"] == str(fresh)
    assert recommended[0]["status"] == "READY"
    assert any(row["status"] == "DEMO_ONLY" for row in rows if row["path"] == str(sample))


def test_setup_readiness_view_reports_blocking_next_action(monkeypatch, tmp_path):
    from src.onboarding import OnboardingState

    holdings = tmp_path / "holdings-report-2026-06-14.csv"
    monkeypatch.setattr(setup_readiness, "current_state", lambda: OnboardingState(stage="api_key"))
    monkeypatch.setattr(setup_readiness, "selected_data_files", lambda: {"holdings": holdings, "activities": None})
    monkeypatch.setattr(setup_readiness, "csv_choice_rows", lambda kind: [])
    monkeypatch.setattr(setup_readiness, "demo_snapshot", lambda: SimpleNamespace(available=True))
    monkeypatch.setattr(
        setup_readiness,
        "build_pre_run_checklist",
        lambda **_kwargs: {
            "can_run": False,
            "rows": [
                {
                    "check": "Anthropic API key",
                    "status": "BLOCKED",
                    "blocking": True,
                    "detail": "ANTHROPIC_API_KEY is missing.",
                    "action": "Add ANTHROPIC_API_KEY in API_KEYS.txt or .env.",
                }
            ],
        },
    )
    monkeypatch.setattr(
        setup_readiness,
        "build_preflight",
        lambda **_kwargs: {
            "api_keys": {"required_missing": 1, "optional_missing": 0, "configured_count": 0},
            "workspace": {"locations": {"workspace": str(tmp_path)}, "writable": {"workspace": True}},
            "summary_rows": [],
            "next_action": "Add ANTHROPIC_API_KEY in API_KEYS.txt or .env.",
        },
    )

    view = setup_readiness.setup_readiness_view()

    assert view["status"] == "BLOCKED"
    assert view["next_action"] == "Add ANTHROPIC_API_KEY in API_KEYS.txt or .env."
    assert any(row["check"] == "Anthropic API key" and row["status"] == "FAIL" for row in view["rows"])


def test_export_support_bundle_redacts_secret_text(monkeypatch, tmp_path):
    monkeypatch.setattr(
        setup_readiness,
        "support_bundle_payload",
        lambda include_demo_smoke=False: {
            "doctor": {"api_key": "sk-ant-test-secret"},
            "setup_readiness": {"rows": [{"detail": "sk-ant-test-secret"}]},
            "data_files": {"rows": []},
            "diagnostics_jsonl": json.dumps({"message": "token sk-ant-test-secret"}),
            "notes": ["no raw secrets"],
        },
    )

    result = setup_readiness.export_support_bundle(output_dir=tmp_path)

    assert result.ok is True
    assert result.output_path is not None
    with zipfile.ZipFile(result.output_path) as zf:
        names = set(zf.namelist())
        assert names == {
            "support/doctor.json",
            "support/setup_readiness.json",
            "support/data_files.json",
            "support/diagnostics.jsonl",
            "support/README.txt",
        }
        all_text = "\n".join(zf.read(name).decode("utf-8") for name in names)
    assert "sk-ant-test-secret" not in all_text
    assert "<redacted>" in all_text


def test_paid_run_readiness_blocks_on_checklist(monkeypatch):
    monkeypatch.setattr(
        setup_readiness,
        "build_pre_run_checklist",
        lambda **_kwargs: {
            "can_run": False,
            "blocking_count": 1,
            "warning_count": 0,
            "next_action": "Add ANTHROPIC_API_KEY.",
            "rows": [
                {
                    "check": "Anthropic API key",
                    "status": "BLOCKED",
                    "blocking": True,
                    "detail": "missing",
                    "action": "Add ANTHROPIC_API_KEY.",
                }
            ],
        },
    )

    view = setup_readiness.paid_run_readiness_view(holdings_csv="holdings.csv")

    assert view["status"] == "BLOCKED"
    assert view["can_run"] is False
    assert view["primary_action"] == "Add ANTHROPIC_API_KEY."
    assert any(row["step"] == "Anthropic API key" and row["status"] == "BLOCKED" for row in view["steps"])


def test_paid_run_readiness_requires_warning_confirmation(monkeypatch):
    monkeypatch.setattr(
        setup_readiness,
        "build_pre_run_checklist",
        lambda **_kwargs: {
            "can_run": True,
            "blocking_count": 0,
            "warning_count": 1,
            "next_action": "Ready to run.",
            "rows": [{"check": "Optional data APIs", "status": "WARN", "detail": "missing", "action": "coverage reduced"}],
        },
    )

    view = setup_readiness.paid_run_readiness_view(holdings_csv="holdings.csv")

    assert view["status"] == "REVIEW_FIRST"
    assert view["can_run"] is True
    assert view["requires_warning_confirmation"] is True


def test_support_bundle_preview_lists_included_and_excluded_files():
    preview = setup_readiness.support_bundle_preview()

    assert preview["safe_to_share"] is True
    assert preview["file_count"] == 5
    assert "support/doctor.json" in {row["path"] for row in preview["files"]}
    assert "API_KEYS.txt" in preview["excluded"]
