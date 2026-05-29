"""Coverage for src.ui_support.learning_view aggregator."""

from __future__ import annotations

from src.ui_support import learning_view


def test_learning_view_returns_required_top_level_keys():
    view = learning_view()
    for key in (
        "thesis_verdicts",
        "edge_by_horizon",
        "sharpe_by_conviction",
        "thesis_text_drift_alerts",
        "errors",
    ):
        assert key in view, f"learning_view missing top-level key: {key}"


def test_learning_view_never_raises_on_soft_errors():
    """Every section is wrapped — errors append to the errors list, not raise."""
    view = learning_view()
    assert isinstance(view["errors"], list)


def test_learning_view_thesis_verdicts_are_well_formed_dicts():
    view = learning_view()
    for v in view["thesis_verdicts"]:
        assert isinstance(v, dict)
        # required minimal shape — used by Streamlit + Desktop renderers
        assert "ticker" in v
        assert "verdict_history" in v
        assert isinstance(v["verdict_history"], list)


def test_learning_view_edge_by_horizon_keys_are_ints_or_int_strings():
    view = learning_view()
    for key in view["edge_by_horizon"]:
        # Decision-journal stores int keys, but the JSON round-trip can
        # turn them into strings — accept both so renderers don't crash.
        assert isinstance(key, int) or (isinstance(key, str) and key.lstrip("-").isdigit())


def test_learning_view_sharpe_buckets_carry_sizing_multiplier():
    view = learning_view()
    for conv, stats in view["sharpe_by_conviction"].items():
        assert "sizing_multiplier" in stats
        # Multiplier must stay within the backtester's published clamp.
        assert 0.4 <= float(stats["sizing_multiplier"]) <= 1.4
        for k in ("n", "avg_return_pct", "hit_rate", "sharpe", "max_drawdown_pct"):
            assert k in stats


def test_learning_view_drift_alerts_have_similarity_and_thesis_fields():
    view = learning_view()
    for alert in view["thesis_text_drift_alerts"]:
        assert "ticker" in alert
        assert "similarity" in alert
        # ``was_thesis`` and ``now_thesis`` may be None for legacy rows;
        # they just have to exist as keys for the renderer.
        assert "was_thesis" in alert
        assert "now_thesis" in alert
