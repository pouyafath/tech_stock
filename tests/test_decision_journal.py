from datetime import datetime

from src.decision_journal import (
    format_for_report,
    load_journal,
    record_decision,
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
    assert {row["ticker"] for row in rows} == {"NVDA", "SOXL"}


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


def test_journal_status_counts_correctly():
    from src.decision_journal import journal_status

    journal = {
        "decisions": [
            {"id": "a", "user_decision": "pending"},
            {"id": "b", "user_decision": "accepted"},
            {"id": "c", "user_decision": "ignored"},
        ]
    }
    status = journal_status(journal)
    assert status["total"] == 3
    assert status["pending"] == 1
    assert status["recorded"] == 2


def test_load_journal_missing_file(tmp_path):
    from src.decision_journal import load_journal

    result = load_journal(tmp_path / "missing.json")
    assert result["decisions"] == []


def test_record_decision_missing_id(tmp_path):
    from src.decision_journal import load_journal, record_decision, seed_from_recommendation_log

    log = tmp_path / "20260501_0900_morning.json"
    log.write_text('{"recommendations": [{"ticker": "AMD", "action": "BUY", "conviction": 7}]}')
    journal = tmp_path / "decision_journal.json"
    seed_from_recommendation_log(log, journal)

    # Try to record decision for non-existent id — raises ValueError
    import pytest

    with pytest.raises(ValueError, match="not found"):
        record_decision(journal, "nonexistent_id:AMD", user_decision="accepted")


def test_format_for_report_worst_overrides(tmp_path):
    from src.decision_journal import format_for_report

    scorecard = {
        "journal": {"total": 1, "pending": 0, "recorded": 1},
        "n_scored_windows": 1,
        "overall": {
            "model_avg_return_pct": 10.0,
            "user_avg_return_pct": 0.0,
            "avg_decision_delta_pct": -10.0,
            "model_hit_rate": 1,
            "user_hit_rate": 0,
        },
        "by_user_decision": {},
        "worst_user_overrides": [
            {
                "ticker": "NVDA",
                "session_date": "2026-05-01",
                "recommended_action": "BUY",
                "user_decision": "ignored",
                "horizon_days": 60,
                "decision_delta_pct": -15.0,
            }
        ],
    }
    text = "\n".join(format_for_report(scorecard))
    assert "NVDA" in text
    assert "Overrides that hurt most" in text


def test_default_actual_action_variants():
    from src.decision_journal import _default_actual_action

    row = {"recommended_action": "BUY"}
    assert _default_actual_action(row, "SELL") == "SELL"
    assert _default_actual_action({"user_decision": "accepted", "recommended_action": "BUY"}, None) == "BUY"
    assert _default_actual_action({"user_decision": "ignored", "recommended_action": "BUY"}, None) == "NONE"
    assert _default_actual_action({"user_decision": "ignored", "recommended_action": "SELL"}, None) == "HOLD"
    assert _default_actual_action({"user_decision": "modified", "recommended_action": "ADD"}, None) == "ADD"
    assert _default_actual_action({"user_decision": "watch", "recommended_action": "BUY"}, None) == "NONE"
