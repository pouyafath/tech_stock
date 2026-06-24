from datetime import datetime

from src.decision_journal import (
    execution_checklist_status,
    format_for_report,
    load_journal,
    record_decision,
    record_execution_checklist,
    run_scorecard,
    seed_from_recommendation_log,
)


def test_seed_from_recommendation_log_creates_pending_action_rows(tmp_path):
    log = tmp_path / "20260501_0900_morning.json"
    log.write_text(
        """
        {
          "recommendations": [
            {"ticker": "NVDA", "action": "BUY", "conviction": 8, "invest_amount_usd": 500, "net_expected_pct": 8.5},
            {"ticker": "MSFT", "action": "HOLD", "conviction": 6},
            {"ticker": "SOXL", "action": "SELL", "conviction": 9, "shares": 2}
          ]
        }
        """
    )
    journal = tmp_path / "decision_journal.json"

    created = seed_from_recommendation_log(log, journal)
    created_again = seed_from_recommendation_log(log, journal)
    rows = load_journal(journal)["decisions"]

    assert len(created) == 2
    assert created_again == []
    assert len(rows) == 2
    assert rows[0]["user_decision"] == "pending"
    assert rows[0]["execution_checklist"]["quote_confirmed"] is False
    assert {row["ticker"] for row in rows} == {"NVDA", "SOXL"}


def test_record_execution_checklist_persists_review_state(tmp_path):
    log = tmp_path / "20260501_0900_morning.json"
    log.write_text(
        """
        {
          "recommendations": [
            {"ticker": "NVDA", "action": "BUY", "conviction": 8, "invest_amount_usd": 500}
          ]
        }
        """
    )
    journal = tmp_path / "decision_journal.json"
    seed_from_recommendation_log(log, journal)

    row = record_execution_checklist(
        journal,
        "20260501_0900_morning.json:NVDA",
        checklist={"quote_confirmed": True, "catalyst_checked": True},
        notes="Checked quote and catalyst.",
    )
    status = execution_checklist_status(row)

    assert status["status"] == "PENDING"
    assert status["done"] == 2
    assert row["execution_checklist"]["quote_confirmed"] is True
    assert row["execution_checklist_notes"] == "Checked quote and catalyst."


def test_record_decision_and_scorecard_compare_user_vs_model(tmp_path):
    log = tmp_path / "20260501_0900_morning.json"
    log.write_text(
        """
        {
          "recommendations": [
            {"ticker": "NVDA", "action": "BUY", "conviction": 8, "net_expected_pct": 8},
            {"ticker": "SOXL", "action": "SELL", "conviction": 9, "net_expected_pct": 6}
          ]
        }
        """
    )
    journal = tmp_path / "decision_journal.json"
    seed_from_recommendation_log(log, journal)

    record_decision(journal, "20260501_0900_morning.json:NVDA", user_decision="accepted")
    record_decision(journal, "20260501_0900_morning.json:SOXL", user_decision="ignored")

    prices = {
        ("NVDA", "2026-05-01"): 100,
        ("NVDA", "2026-05-06"): 110,
        ("SOXL", "2026-05-01"): 100,
        ("SOXL", "2026-05-06"): 90,
    }

    def lookup(ticker, date_text):
        return prices[(ticker, date_text)]

    card = run_scorecard(
        journal,
        as_of=datetime(2026, 5, 10),
        horizons=(5,),
        price_lookup=lookup,
    )

    assert card["n_scored_windows"] == 2
    assert card["overall"]["model_avg_return_pct"] == 10.0
    assert card["overall"]["user_avg_return_pct"] == 0.0
    assert card["overall"]["avg_decision_delta_pct"] == -10.0
    assert card["by_user_decision"]["accepted"]["avg_decision_delta_pct"] == 0.0
    assert card["by_user_decision"]["ignored"]["avg_decision_delta_pct"] == -20.0
    assert card["worst_user_overrides"][0]["ticker"] == "SOXL"


def test_format_for_report_renders_pending_and_scorecard():
    scorecard = {
        "journal": {"total": 2, "pending": 1, "recorded": 1},
        "n_scored_windows": 1,
        "overall": {
            "model_avg_return_pct": 5,
            "user_avg_return_pct": 2,
            "avg_decision_delta_pct": -3,
            "model_hit_rate": 1,
            "user_hit_rate": 1,
        },
        "by_user_decision": {
            "ignored": {
                "n": 1,
                "model_avg_return_pct": 5,
                "user_avg_return_pct": 2,
                "avg_decision_delta_pct": -3,
            }
        },
        "worst_user_overrides": [],
    }

    text = "\n".join(format_for_report(scorecard))

    assert "Decision Journal" in text
    assert "Pending decisions" in text
    assert "Avg discretion delta" in text
