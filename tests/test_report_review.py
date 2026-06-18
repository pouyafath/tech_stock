import json

from src.decision_journal import seed_from_recommendation_log
from src.report_review import build_report_review
from src.view_models import BLOCKED, REVIEW_FIRST


def _write_log(path):
    payload = {
        "session_summary": "Tech risk is elevated.",
        "recommendations": [
            {
                "ticker": "NVDA",
                "action": "ADD",
                "conviction": 8,
                "action_amount": 200,
                "risk_controls": {"stop_loss_pct": -7, "take_profit_pct": 12},
                "catalyst_verified": True,
                "catalyst_source": "earnings call",
            },
            {
                "ticker": "SOXL",
                "action": "TRIM",
                "conviction": 7,
                "shares": 1,
                "manual_review_required": True,
            },
        ],
        "quality_warnings": [
            {
                "severity": "medium",
                "code": "quote_source_mismatch",
                "ticker": "SOXL",
                "message": "CSV quote differs from market quote.",
                "action_required": "Verify price before trading.",
            }
        ],
        "source_degradation": [{"source": "finnhub", "message": "rate limited"}],
        "drift_vs_previous": [
            {
                "ticker": "SOXL",
                "drift_type": "action_flip",
                "was": {"action": "SELL", "conviction": 9},
                "now": {"action": "TRIM", "conviction": 7},
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def test_report_review_summarizes_warnings_drift_and_journal(tmp_path):
    log = tmp_path / "20260616_0900_morning.json"
    report = tmp_path / "20260616_0900_morning.md"
    journal = tmp_path / "decision_journal.json"
    _write_log(log)
    report.write_text("# Report", encoding="utf-8")
    seed_from_recommendation_log(log, journal)

    view = build_report_review(log_path=log, report_path=report, journal_path=journal)

    assert view["ok"] is True
    assert view["status"] == REVIEW_FIRST
    assert view["metric_rows"][1]["metric"] == "Quality warnings"
    assert view["warning_counts"]["code"]["quote_source_mismatch"] == 1
    assert view["readiness_counts"][REVIEW_FIRST] == 1
    assert view["recommendation_rows"][0]["ticker"] == "NVDA"
    assert view["decision_rows"][0]["user_decision"] == "pending"
    assert view["change_rows"][0]["ticker"] == "SOXL"
    assert "tech_stock report review" in view["support_summary"]


def test_report_review_blocks_unreadable_payload(tmp_path):
    view = build_report_review(
        log_path=tmp_path / "missing.json",
        report_path=None,
        journal_path=tmp_path / "decision_journal.json",
        payload={"error": "bad json"},
    )

    assert view["ok"] is False
    assert view["status"] == BLOCKED
    assert view["metric_rows"][0]["status"] == "FAIL"
