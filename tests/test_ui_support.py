import json
from pathlib import Path

from src import ui_support
from src.report_pipeline import ReportPipeline


def test_run_report_from_ui_calls_canonical_runner(monkeypatch, tmp_path, capsys):
    report = tmp_path / "report.md"
    csv = tmp_path / "report.csv"
    log = tmp_path / "report.json"
    holdings = tmp_path / "holdings.csv"
    holdings.write_text("Ticker\nNVDA\n")

    def fake_run(**kwargs):
        assert kwargs["session_type"] == "morning"
        assert kwargs["holdings_csv"] == holdings
        assert kwargs["model_id"] == "claude-sonnet-4-6"
        assert kwargs["open_report"] is False
        print("runner output")
        return {"report_path": report, "csv_path": csv, "log_path": log}

    monkeypatch.setattr(ui_support, "ReportPipeline", lambda: ReportPipeline(runner=fake_run))
    monkeypatch.setattr(
        ui_support,
        "build_pre_run_checklist",
        lambda **_kwargs: {"can_run": True, "warning_count": 0, "rows": []},
    )
    monkeypatch.setattr(ui_support, "format_pre_run_checklist", lambda _checklist: "Pre-run checklist: OK")
    monkeypatch.setattr(ui_support, "save_data_file_defaults", lambda **_kwargs: None)

    result = ui_support.run_report_from_ui(
        session_type="morning",
        holdings_csv=str(holdings),
        model_choice="sonnet",
    )

    assert result.ok is True
    assert result.report_path == report
    assert "runner output" in result.console
    assert capsys.readouterr().out == ""


def test_run_report_from_ui_streams_progress(monkeypatch, tmp_path):
    report = tmp_path / "report.md"
    csv = tmp_path / "report.csv"
    log = tmp_path / "report.json"
    progress = []

    def fake_run(**kwargs):
        print("phase one")
        print("phase two")
        return {"report_path": report, "csv_path": csv, "log_path": log}

    monkeypatch.setattr(ui_support, "ReportPipeline", lambda: ReportPipeline(runner=fake_run))
    monkeypatch.setattr(
        ui_support,
        "build_pre_run_checklist",
        lambda **_kwargs: {"can_run": True, "warning_count": 0, "rows": []},
    )
    monkeypatch.setattr(ui_support, "format_pre_run_checklist", lambda _checklist: "Pre-run checklist: OK")
    monkeypatch.setattr(ui_support, "save_data_file_defaults", lambda **_kwargs: None)

    result = ui_support.run_report_from_ui(
        session_type="morning",
        model_choice="sonnet",
        on_progress=progress.append,
    )

    assert result.ok is True
    assert progress == ["phase one", "phase two"]


def test_run_report_from_ui_blocks_failed_preflight(monkeypatch):
    monkeypatch.setattr(
        ui_support,
        "build_pre_run_checklist",
        lambda **_kwargs: {
            "can_run": False,
            "next_action": "Add ANTHROPIC_API_KEY.",
            "blocking_count": 1,
            "rows": [{"check": "Anthropic API key", "blocking": True}],
        },
    )
    monkeypatch.setattr(ui_support, "format_pre_run_checklist", lambda _checklist: "blocked")

    result = ui_support.run_report_from_ui(session_type="morning", model_choice="sonnet")

    assert result.ok is False
    assert result.error == "Add ANTHROPIC_API_KEY."
    assert result.console == "blocked"


def test_ui_support_paid_readiness_and_support_preview_wrappers(monkeypatch):
    monkeypatch.setattr(
        ui_support,
        "build_paid_run_readiness_view",
        lambda **kwargs: {"status": "READY", "holdings": str(kwargs["holdings_csv"])},
    )
    monkeypatch.setattr(
        ui_support,
        "build_support_bundle_preview",
        lambda include_demo_smoke=False: {"file_count": 5, "include_demo_smoke": include_demo_smoke},
    )

    readiness = ui_support.paid_run_readiness_view(holdings_csv="~/holdings.csv")
    preview = ui_support.support_bundle_preview(include_demo_smoke=True)

    assert readiness["status"] == "READY"
    assert readiness["holdings"].endswith("holdings.csv")
    assert preview == {"file_count": 5, "include_demo_smoke": True}


def test_list_reports_returns_newest_first(monkeypatch, tmp_path):
    older = tmp_path / "20260101_0900_morning.md"
    newer = tmp_path / "20260102_0900_morning.md"
    older.write_text("older")
    newer.write_text("newer")
    monkeypatch.setattr(ui_support, "REPORTS_DIR", tmp_path)

    reports = ui_support.list_reports()

    assert reports == [newer, older]


def test_latest_log_summary_reads_current_dashboard_fields(monkeypatch, tmp_path):
    log_dir = tmp_path / "recommendations_log"
    log_dir.mkdir()
    payload = {
        "portfolio_health": {"risk_dashboard": {"annualized_volatility_pct": 24.0}},
        "quality_warnings": [{"severity": "medium"}],
        "hedge_suggestions": [{"instrument": "PSQ"}],
        "drift_vs_previous": [{"ticker": "AMD"}],
        "priority_actions": [{"ticker": "SOXL"}],
        "trailing_stop_breaches": [{"ticker": "SPOT"}],
        "watchlist_flags": [{"ticker": "CRM"}],
        "sector_warnings": ["tech concentration"],
        "warnings": ["general warning"],
        "market_context_snapshot": {"XLK": {"change_pct_21d": 5.0}},
        "session_summary": "summary",
        "usage_summary": {"cost_usd": 0.5},
        "recommendations": [{"ticker": "NVDA"}],
        "source_coverage": {"status": "PARTIAL", "rows": [{"source": "Quotes", "status": "PARTIAL"}]},
    }
    path = log_dir / "20260430_0900_morning.json"
    path.write_text(json.dumps(payload))
    monkeypatch.setattr(ui_support, "RECS_LOG_DIR", log_dir)

    summary = ui_support.latest_log_summary()

    assert summary["session_file"] == path.name
    assert summary["risk_dashboard"]["annualized_volatility_pct"] == 24.0
    assert summary["usage"]["cost_usd"] == 0.5
    assert summary["priority_actions"][0]["ticker"] == "SOXL"
    assert summary["trailing_stop_breaches"][0]["ticker"] == "SPOT"
    assert summary["watchlist_flags"][0]["ticker"] == "CRM"
    assert summary["sector_warnings"] == ["tech concentration"]
    assert summary["session_summary"] == "summary"
    assert summary["source_coverage"]["status"] == "PARTIAL"


def test_report_history_view_includes_input_files_and_signal_counts(monkeypatch, tmp_path):
    report_dir = tmp_path / "reports"
    log_dir = tmp_path / "recommendations_log"
    report_dir.mkdir()
    log_dir.mkdir()
    report = report_dir / "20260613_0900_morning.md"
    report.write_text("# Report", encoding="utf-8")
    log = log_dir / "20260613_0900_morning.json"
    log.write_text(
        json.dumps(
            {
                "input_files": {
                    "holdings_csv": "/tmp/holdings-report-2026-06-13.csv",
                    "activities_csv": "/tmp/activities-export-2026-06-13.csv",
                },
                "recommendations": [{"action": "BUY"}, {"action": "TRIM"}],
                "quality_warnings": [{"severity": "medium"}],
                "data_confidence": {"label": "Review First"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ui_support, "REPORTS_DIR", report_dir)
    monkeypatch.setattr(ui_support, "RECS_LOG_DIR", log_dir)

    view = ui_support.report_history_view()
    row = view["rows"][0]

    assert row["holdings_csv"].endswith("holdings-report-2026-06-13.csv")
    assert row["buy_add_count"] == 1
    assert row["trim_sell_count"] == 1
    assert row["warning_count"] == 1


def test_report_review_view_matches_report_to_log_and_seeds_journal(monkeypatch, tmp_path):
    report_dir = tmp_path / "reports"
    log_dir = tmp_path / "recommendations_log"
    data_dir = tmp_path / "data"
    report_dir.mkdir()
    log_dir.mkdir()
    data_dir.mkdir()
    report = report_dir / "20260616_0900_morning.md"
    report.write_text("# Report", encoding="utf-8")
    log = log_dir / "20260616_0900_morning.json"
    log.write_text(
        json.dumps(
            {
                "recommendations": [{"ticker": "AMD", "action": "TRIM", "conviction": 8}],
                "quality_warnings": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ui_support, "REPORTS_DIR", report_dir)
    monkeypatch.setattr(ui_support, "RECS_LOG_DIR", log_dir)
    monkeypatch.setattr(ui_support, "DECISION_JOURNAL_PATH", data_dir / "decision_journal.json")

    view = ui_support.report_review_view(report_path=report)

    assert view["ok"] is True
    assert view["log_path"] == log
    assert view["decision_rows"][0]["ticker"] == "AMD"
    assert (data_dir / "decision_journal.json").exists()


def test_source_provenance_view_filters_status_source_and_ticker(monkeypatch, tmp_path):
    log_dir = tmp_path / "recommendations_log"
    log_dir.mkdir()
    log = log_dir / "20260624_0900_morning.json"
    log.write_text(
        json.dumps(
            {
                "source_provenance": {
                    "status": "PARTIAL",
                    "rows": [
                        {"ticker": "NVDA", "source": "Quote", "status": "OK", "provider": "yfinance"},
                        {"ticker": "AMD", "source": "Catalyst", "status": "MISSING", "provider": ""},
                        {"ticker": "AMD", "source": "Analyst", "status": "PARTIAL", "provider": "finnhub"},
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ui_support, "RECS_LOG_DIR", log_dir)

    problem = ui_support.source_provenance_view(status_filter="problem")
    analyst = ui_support.source_provenance_view(status_filter="all", source_filter="Analyst", ticker_filter="am")

    assert problem["unfiltered_count"] == 3
    assert problem["filtered_count"] == 2
    assert {row["source"] for row in problem["rows"]} == {"Catalyst", "Analyst"}
    assert analyst["filtered_count"] == 1
    assert analyst["rows"][0]["provider"] == "finnhub"


def test_outcomes_view_uses_shared_recommendation_outcome_model(monkeypatch, tmp_path):
    log_dir = tmp_path / "recommendations_log"
    log_dir.mkdir()
    monkeypatch.setattr(ui_support, "RECS_LOG_DIR", log_dir)
    monkeypatch.setattr(
        ui_support,
        "build_recommendation_outcomes_view",
        lambda path, max_logs=250: {"status": "READY", "path": path, "max_logs": max_logs},
    )

    view = ui_support.outcomes_view(max_logs=12)

    assert view == {"status": "READY", "path": log_dir, "max_logs": 12}


def test_app_self_test_view_returns_rows(monkeypatch):
    monkeypatch.setattr(ui_support, "setup_readiness_view", lambda **_kwargs: {"status": "READY", "next_action": ""})
    monkeypatch.setattr(ui_support, "demo_smoke_view", lambda: {"ok": True, "message": "demo passed"})
    monkeypatch.setattr(
        ui_support, "report_review_view", lambda **_kwargs: {"ok": True, "status_label": "Trade Ready", "session_file": "x.json"}
    )
    monkeypatch.setattr(
        ui_support,
        "support_bundle_preview",
        lambda **_kwargs: {"safe_to_share": True, "file_count": 3, "privacy_note": "redacted"},
    )

    view = ui_support.app_self_test_view()

    assert view["status"] == "READY"
    assert len(view["rows"]) == 5
    assert "tech_stock app self-test" in view["support_summary"]


def test_write_editable_json_validates_and_formats(monkeypatch, tmp_path):
    settings = tmp_path / "settings.json"
    monkeypatch.setitem(ui_support.EDITABLE_JSON_FILES, "Settings", settings)

    saved = ui_support.write_editable_json("Settings", '{"budget_cad":3000}')

    assert saved == settings
    assert settings.read_text() == '{\n  "budget_cad": 3000\n}\n'


def test_write_editable_json_backs_up_prior_contents(monkeypatch, tmp_path):
    """Overwriting an existing config file must leave a .bak with the old data
    so a bad edit in the Advanced Editor is recoverable."""
    settings = tmp_path / "settings.json"
    settings.write_text('{"budget_cad": 1000}\n', encoding="utf-8")
    monkeypatch.setitem(ui_support.EDITABLE_JSON_FILES, "Settings", settings)

    ui_support.write_editable_json("Settings", '{"budget_cad": 5000}')

    backup = settings.with_suffix(settings.suffix + ".bak")
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == '{"budget_cad": 1000}\n'
    assert '"budget_cad": 5000' in settings.read_text(encoding="utf-8")


def test_write_editable_json_no_backup_for_new_file(monkeypatch, tmp_path):
    """A brand-new file has nothing to back up — no spurious .bak created."""
    settings = tmp_path / "settings.json"
    monkeypatch.setitem(ui_support.EDITABLE_JSON_FILES, "Settings", settings)

    ui_support.write_editable_json("Settings", '{"budget_cad": 5000}')

    assert not settings.with_suffix(settings.suffix + ".bak").exists()


def test_validate_json_text_reports_line_and_column():
    ok, message = ui_support.validate_json_text('{"budget": }')

    assert ok is False
    assert "line 1" in message
    assert "column" in message

    assert ui_support.validate_json_text('{"budget": 1}') == (True, "Valid JSON.")


def test_default_run_settings_reads_budget_and_model(monkeypatch, tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "settings.json").write_text('{"budget_usd": 500, "budget_cad": 3000, "claude_model": "claude-opus-4-7"}')
    monkeypatch.setattr(ui_support, "CONFIG_DIR", config_dir)

    defaults = ui_support.default_run_settings()

    assert defaults == {"budget_usd": 500.0, "budget_cad": 3000.0, "model_choice": "opus"}
