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
            "source_provenance": {"status": "OK"},
            "data_confidence": {"overall": "review_first"},
            "errors": [{"code": "optional_source"}],
        }

    artifacts = ReportPipeline(runner=fake_runner).run(session_type="morning")

    assert artifacts.report_path == report
    assert artifacts.csv_path == csv
    assert artifacts.log_path == log
    assert artifacts.usage["cost_usd"] == 0.2
    assert artifacts.quality_warnings == [{"code": "x"}]
    assert artifacts.source_degradation == [{"source": "Finnhub"}]
    assert artifacts.source_provenance == {"status": "OK"}
    assert artifacts.data_confidence == {"overall": "review_first"}
    assert artifacts.errors == [{"code": "optional_source"}]
    assert artifacts.timings["elapsed_seconds"] >= 0
    assert isinstance(artifacts.report_path, Path)


def test_report_pipeline_legacy_mapping_includes_additive_metadata(tmp_path):
    report = tmp_path / "report.md"

    artifacts = ReportPipeline(
        runner=lambda **_kwargs: {
            "report_path": str(report),
            "recommendation": {"data_confidence": {"quote_freshness": "fresh"}},
            "session_type": "afternoon",
        }
    ).run(session_type="afternoon")

    mapping = artifacts.to_mapping()

    assert mapping["report_path"] == report
    assert mapping["data_confidence"] == {"quote_freshness": "fresh"}
    assert mapping["source_provenance"] == {}
    assert "elapsed_seconds" in mapping["timings"]
    assert mapping["errors"] == []
