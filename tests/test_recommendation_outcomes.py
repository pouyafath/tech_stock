import json
from datetime import datetime

from src.recommendation_outcomes import (
    benchmark_for_ticker,
    build_outcomes_view,
    load_recommendation_events,
    stable_recommendation_id,
)


def _write_log(path, recommendations, *, cost=0.22):
    path.write_text(
        json.dumps(
            {
                "recommendations": recommendations,
                "quality_warnings": [{"ticker": "AMD", "code": "missing_decision_tree"}],
                "usage_summary": {"cost_usd": cost},
            }
        ),
        encoding="utf-8",
    )


def test_stable_recommendation_id_matches_user_readable_shape():
    assert stable_recommendation_id("20260616_0900_morning.json", "nvda", "add", 1) == "20260616_morning_NVDA_ADD_001"


def test_benchmark_for_ticker_uses_sector_proxy_where_possible():
    assert benchmark_for_ticker("NVDA") == "SMH"
    assert benchmark_for_ticker("TQQQ") == "QQQ"
    assert benchmark_for_ticker("VOO") == "SPY"


def test_load_recommendation_events_prefers_persisted_recommendation_id(tmp_path):
    log_dir = tmp_path / "recommendations_log"
    log_dir.mkdir()
    _write_log(
        log_dir / "20260601_0900_morning.json",
        [{"ticker": "NVDA", "action": "ADD", "recommendation_id": "custom-id"}],
    )

    events = load_recommendation_events(log_dir)

    assert events[0]["id"] == "custom-id"


def test_outcomes_view_scores_fixed_windows_and_benchmark_alpha(tmp_path):
    log_dir = tmp_path / "recommendations_log"
    log_dir.mkdir()
    _write_log(
        log_dir / "20260601_0900_morning.json",
        [
            {
                "ticker": "AMD",
                "action": "ADD",
                "conviction": 8,
                "time_horizon": "1-3 trading days",
                "net_expected_pct": 4.5,
                "risk_controls": {"stop_loss_pct": -5, "take_profit_pct": 10},
                "catalyst_verified": True,
            },
            {
                "ticker": "GOOG",
                "action": "TRIM",
                "conviction": 7,
                "risk_controls": {"stop_loss_pct": -5, "take_profit_pct": 8},
            },
        ],
    )

    prices = {
        ("AMD", "2026-06-01"): 100.0,
        ("AMD", "2026-06-02"): 112.0,
        ("SMH", "2026-06-01"): 200.0,
        ("SMH", "2026-06-02"): 210.0,
        ("GOOG", "2026-06-01"): 100.0,
        ("GOOG", "2026-06-02"): 95.0,
        ("QQQ", "2026-06-01"): 500.0,
        ("QQQ", "2026-06-02"): 505.0,
    }

    def price_lookup(ticker, iso_date):
        return prices.get((ticker, iso_date))

    view = build_outcomes_view(
        log_dir,
        as_of=datetime(2026, 6, 3),
        horizons=(1,),
        price_lookup=price_lookup,
    )

    assert view["status"] == "READY"
    assert view["summary"]["scored_windows"] == 2
    assert view["summary"]["scored_recommendations"] == 2
    assert view["summary"]["buy_add_success_rate"] == 1.0
    assert view["summary"]["trim_sell_saved_drawdown_count"] == 1
    assert view["summary"]["estimated_claude_cost_usd"] == 0.22

    amd = next(row for row in view["rows"] if row["ticker"] == "AMD")
    assert amd["id"] == "20260601_morning_AMD_ADD_001"
    assert amd["stock_move_pct"] == 12.0
    assert amd["benchmark"] == "SMH"
    assert amd["alpha_vs_benchmark_pct"] == 7.0
    assert amd["take_profit_triggered"] is True
    assert amd["source_bucket"] == "verified_catalyst"

    goog = next(row for row in view["rows"] if row["ticker"] == "GOOG")
    assert goog["action_return_pct"] == 5.0
    assert goog["hit"] is True
    assert goog["alpha_vs_benchmark_pct"] == 6.0


def test_outcomes_view_reports_pending_and_missing_prices(tmp_path):
    log_dir = tmp_path / "recommendations_log"
    log_dir.mkdir()
    _write_log(log_dir / "20260615_0900_morning.json", [{"ticker": "NVDA", "action": "BUY"}])
    _write_log(log_dir / "20260601_0900_morning.json", [{"ticker": "MSFT", "action": "ADD"}])

    def price_lookup(ticker, iso_date):
        if ticker == "NVDA" and iso_date == "2026-06-15":
            return 100.0
        return None

    view = build_outcomes_view(
        log_dir,
        as_of=datetime(2026, 6, 16),
        horizons=(5,),
        price_lookup=price_lookup,
    )

    assert view["summary"]["scored_windows"] == 0
    assert view["summary"]["pending_windows"] == 1
    assert view["summary"]["error_count"] == 1
    assert view["pending"][0]["ticker"] == "NVDA"
    assert view["errors"][0]["ticker"] == "MSFT"
