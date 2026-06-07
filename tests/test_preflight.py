from types import SimpleNamespace

from src import preflight
from src.updater import UpdateInfo


def test_build_preflight_reports_missing_required_key(monkeypatch, tmp_path):
    from src import main

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(main, "api_key_search_paths", lambda: [tmp_path / "API_KEYS.txt"])
    monkeypatch.setattr(main, "_load_api_keys_from_file", lambda: None)
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path / "temporary_upload")
    monkeypatch.setattr(main, "runtime_locations", lambda: {"workspace": tmp_path, "reports": tmp_path / "reports"})
    monkeypatch.setattr(
        preflight,
        "check_for_update",
        lambda **_kwargs: UpdateInfo(
            current_version="1.21.0",
            latest_version="1.21.0",
            asset_name="tech_stock.dmg",
            asset_available=True,
            checksum_available=True,
            asset_names=["tech_stock.dmg", "SHA256SUMS.txt"],
        ),
    )

    payload = preflight.build_preflight(timeout=0.1)

    assert payload["api_keys"]["required_missing"] == 1
    assert any(row["check"] == "API keys" and row["status"] == "FAIL" for row in payload["summary_rows"])
    assert payload["update"]["asset_available"] is True


def test_build_preflight_flags_stale_csv(monkeypatch, tmp_path):
    from src import main

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "holdings-report-2026-01-01.csv").write_text("Symbol,Quantity\nNVDA,1\n", encoding="utf-8")
    monkeypatch.setattr(main, "UPLOAD_DIR", uploads)
    monkeypatch.setattr(preflight.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(main, "api_key_search_paths", lambda: [])
    monkeypatch.setattr(main, "_load_api_keys_from_file", lambda: None)
    monkeypatch.setattr(main, "runtime_locations", lambda: {"workspace": tmp_path})
    monkeypatch.setattr(preflight, "check_for_update", lambda **_kwargs: UpdateInfo(current_version="1.21.0"))

    payload = preflight.build_preflight(timeout=0.1)

    assert payload["csv_freshness"]["holdings"]["stale"] is False
    assert payload["csv_freshness"]["holdings"]["candidate_count"] == 1


def test_build_preflight_surfaces_budget_state(monkeypatch, tmp_path):
    from src import main

    monkeypatch.setattr(main, "api_key_search_paths", lambda: [])
    monkeypatch.setattr(main, "_load_api_keys_from_file", lambda: None)
    monkeypatch.setattr(main, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(main, "runtime_locations", lambda: {"workspace": tmp_path})
    monkeypatch.setattr(preflight, "check_for_update", lambda **_kwargs: UpdateInfo(current_version="1.21.0"))
    monkeypatch.setattr(
        preflight,
        "check_budget",
        lambda expected_cost_usd=0.0: SimpleNamespace(
            budget_usd=5.0,
            month_to_date_usd=5.0,
            projected_monthly_usd=5.0,
            ok=False,
            soft_warn=False,
            hard_block=True,
            message="Monthly cap reached.",
        ),
    )
    monkeypatch.setattr(
        preflight,
        "spend_summary",
        lambda lookback_days=30: SimpleNamespace(last_30d_runs=3, log_path=str(tmp_path / "cost_log.jsonl")),
    )

    payload = preflight.build_preflight(timeout=0.1)

    assert payload["budget"]["hard_block"] is True
    assert any(row["check"] == "Monthly budget" and row["status"] == "FAIL" for row in payload["summary_rows"])


def test_demo_smoke_test_uses_bundled_samples_without_paid_calls():
    result = preflight.run_demo_smoke_test()

    assert result["ok"] is True
    assert {row["name"] for row in result["checks"]} >= {
        "holdings_parse",
        "dashboard_view_model",
        "buy_signals_view_model",
        "markdown_render",
    }


def test_cli_doctor_json_outputs_payload(monkeypatch, capsys):
    monkeypatch.setattr(
        preflight,
        "build_preflight",
        lambda **_kwargs: {"app_version": "1.21.0", "summary_rows": [], "next_action": "Ready for a report run."},
    )

    code = preflight.cli_doctor(["--json"])

    assert code == 0
    assert '"app_version": "1.21.0"' in capsys.readouterr().out


def test_doctor_text_includes_next_action():
    text = preflight.doctor_text(
        {
            "app_version": "1.23.0",
            "summary_rows": [{"check": "API keys", "status": "FAIL", "detail": "missing"}],
            "next_action": "Add ANTHROPIC_API_KEY in API_KEYS.txt or .env, then run API Checks again.",
        }
    )

    assert "Next action: Add ANTHROPIC_API_KEY" in text
