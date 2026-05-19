from pathlib import Path

from src.report_pipeline import ReportPipeline


def test_report_pipeline_returns_structured_artifacts(tmp_path):
    report = tmp_path / "report.md"
    csv = tmp_path / "report.csv"
    log = tmp_path / "session.json"

    def fake_runner(**kwargs):
        assert kwargs["session_type"] == "morning"
        return {
            "recommendation": {"quality_warnings": [{"code": "x"}]},
            "usage": {"cost_usd": 0.2},
            "report_path": report,
            "csv_path": csv,
            "log_path": log,
            "session_type": "morning",
            "model_name": "Sonnet 4.6",
            "source_degradation": [{"source": "Finnhub"}],
        }

    artifacts = ReportPipeline(runner=fake_runner).run(session_type="morning")

    assert artifacts.report_path == report
    assert artifacts.csv_path == csv
    assert artifacts.log_path == log
    assert artifacts.usage["cost_usd"] == 0.2
    assert artifacts.quality_warnings == [{"code": "x"}]
    assert artifacts.source_degradation == [{"source": "Finnhub"}]
    assert isinstance(artifacts.report_path, Path)
