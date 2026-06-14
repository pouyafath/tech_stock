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


def test_write_editable_json_validates_and_formats(monkeypatch, tmp_path):
    settings = tmp_path / "settings.json"
    monkeypatch.setitem(ui_support.EDITABLE_JSON_FILES, "Settings", settings)

    saved = ui_support.write_editable_json("Settings", '{"budget_cad":3000}')

    assert saved == settings
    assert settings.read_text() == '{\n  "budget_cad": 3000\n}\n'


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
