from pathlib import Path

from src import ui_support


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

    monkeypatch.setattr(ui_support, "run_cli_report", fake_run)

    result = ui_support.run_report_from_ui(
        session_type="morning",
        holdings_csv=str(holdings),
        model_choice="sonnet",
    )

    assert result.ok is True
    assert result.report_path == report
    assert "runner output" in result.console
    assert capsys.readouterr().out == ""


def test_list_reports_returns_newest_first(monkeypatch, tmp_path):
    older = tmp_path / "20260101_0900_morning.md"
    newer = tmp_path / "20260102_0900_morning.md"
    older.write_text("older")
    newer.write_text("newer")
    monkeypatch.setattr(ui_support, "REPORTS_DIR", tmp_path)

    reports = ui_support.list_reports()

    assert reports == [newer, older]


def test_write_editable_json_validates_and_formats(monkeypatch, tmp_path):
    settings = tmp_path / "settings.json"
    monkeypatch.setitem(ui_support.EDITABLE_JSON_FILES, "Settings", settings)

    saved = ui_support.write_editable_json("Settings", '{"budget_cad":3000}')

    assert saved == settings
    assert settings.read_text() == '{\n  "budget_cad": 3000\n}\n'


def test_default_run_settings_reads_budget_and_model(monkeypatch, tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "settings.json").write_text(
        '{"budget_usd": 500, "budget_cad": 3000, "claude_model": "claude-opus-4-7"}'
    )
    monkeypatch.setattr(ui_support, "CONFIG_DIR", config_dir)

    defaults = ui_support.default_run_settings()

    assert defaults == {"budget_usd": 500.0, "budget_cad": 3000.0, "model_choice": "opus"}
