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

    result = ui_support.run_report_from_ui(
        session_type="morning",
        model_choice="sonnet",
        on_progress=progress.append,
    )

    assert result.ok is True
    assert progress == ["phase one", "phase two"]


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


def test_run_report_from_ui_dry_run_no_holdings(monkeypatch):
    """dry_run=True with no CSV should return dry_run=True in result."""
    from src import ui_support

    # Patch market data to return empty dict immediately
    monkeypatch.setattr(ui_support, "get_market_data", lambda tickers: {})

    result = ui_support.run_report_from_ui(
        session_type="morning",
        holdings_csv=None,
        model_choice="sonnet",
        dry_run=True,
    )

    assert result.dry_run is True
    assert result.ok is True
    assert result.dry_run_data is not None
    assert result.dry_run_data["dry_run"] is True


def test_run_report_from_ui_dry_run_with_holdings(monkeypatch, tmp_path):
    """dry_run=True with a valid CSV parses holdings and fetches market data."""
    from src import ui_support

    holdings_csv = tmp_path / "holdings.csv"
    holdings_csv.write_text("Ticker\nNVDA\n")

    monkeypatch.setattr(
        ui_support,
        "parse_holdings_csv",
        lambda path: {"holdings": [{"ticker": "NVDA", "market_value": 1000, "market_value_currency": "USD"}]},
    )
    monkeypatch.setattr(ui_support, "get_market_data", lambda tickers: {"NVDA": {"current_price": 900}})

    result = ui_support.run_report_from_ui(
        session_type="morning",
        holdings_csv=str(holdings_csv),
        model_choice="sonnet",
        dry_run=True,
    )

    assert result.dry_run is True
    assert result.ok is True
    assert result.dry_run_data["position_count"] == 1
    assert result.dry_run_data["market_data_fetched"] == 1


def test_resolve_model():
    from src.ui_support import resolve_model

    model_id, model_name = resolve_model("sonnet")
    assert model_id is not None

    none_id, none_name = resolve_model(None)
    assert none_id is None


def test_normalize_optional_path_none():
    from src.ui_support import normalize_optional_path

    assert normalize_optional_path(None) is None
    assert normalize_optional_path("") is None


def test_save_uploaded_bytes(tmp_path, monkeypatch):
    from src import ui_support

    monkeypatch.setattr(ui_support, "UPLOAD_DIR", tmp_path)
    path = ui_support.save_uploaded_bytes("holdings.csv", b"Ticker\nNVDA\n")
    assert path.exists()
    assert path.read_bytes() == b"Ticker\nNVDA\n"


def test_preview_holdings_csv_not_found(tmp_path):
    from src import ui_support

    result = ui_support.preview_holdings_csv(tmp_path / "nonexistent.csv")
    assert result["ok"] is False


def test_find_default_csvs(monkeypatch, tmp_path):
    import re

    from src import ui_support

    # Patch find_csv_by_date to return None (no CSVs found)
    monkeypatch.setattr(ui_support, "find_csv_by_date", lambda prefix: None)
    result = ui_support.find_default_csvs()
    assert result == {"holdings": None, "activities": None}
