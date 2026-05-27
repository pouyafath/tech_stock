"""Coverage for src.onboarding (v1.19 first-run wizard)."""

from __future__ import annotations

import json

import pytest


@pytest.fixture(autouse=True)
def _isolate_onboarding(monkeypatch, tmp_path):
    """Redirect onboarding state to a tmp_path settings file."""
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("src.onboarding.CONFIG_PATH", settings_path)
    monkeypatch.delenv("TECH_STOCK_SKIP_ONBOARDING", raising=False)
    monkeypatch.delenv("TECH_STOCK_DEMO_MODE", raising=False)
    yield settings_path


# ── State machine ──────────────────────────────────────────────────────────


def test_initial_state_is_welcome(_isolate_onboarding):
    from src.onboarding import current_state

    state = current_state()
    assert state.stage == "welcome"
    assert state.is_complete is False
    assert state.completed == []


def test_advance_walks_stages_in_order(_isolate_onboarding):
    from src.onboarding import STAGES, advance, current_state

    # Walk the wizard.
    for stage in STAGES[:-1]:  # everything except 'done'
        next_state = advance(current=stage)
        # The new stage should be exactly the next index in STAGES.
        assert next_state.stage == STAGES[STAGES.index(stage) + 1]
    final = current_state()
    assert final.stage == "done"
    assert final.is_complete is True
    assert final.stamped_at is not None


def test_needs_onboarding_before_done(_isolate_onboarding):
    from src.onboarding import needs_onboarding

    assert needs_onboarding() is True


def test_needs_onboarding_false_after_completion(_isolate_onboarding):
    from src.onboarding import advance, current_state, needs_onboarding

    while current_state().stage != "done":
        advance()
    assert needs_onboarding() is False


def test_needs_onboarding_respects_env_skip(_isolate_onboarding, monkeypatch):
    from src.onboarding import needs_onboarding

    monkeypatch.setenv("TECH_STOCK_SKIP_ONBOARDING", "1")
    assert needs_onboarding() is False


def test_reset_onboarding_returns_to_welcome(_isolate_onboarding):
    from src.onboarding import advance, current_state, reset_onboarding

    advance()
    advance()
    reset_onboarding()
    assert current_state().stage == "welcome"
    assert current_state().is_complete is False


def test_advance_records_skipped_demo_flag(_isolate_onboarding):
    from src.onboarding import advance, current_state

    advance(current="welcome", skip_demo=True)
    assert current_state().skipped_demo is True


def test_advance_is_idempotent_per_stage(_isolate_onboarding):
    from src.onboarding import advance, current_state

    advance(current="welcome")
    advance(current="welcome")  # repeat — should still go to next
    state = current_state()
    # We've advanced past welcome, but "welcome" only appears once in completed
    assert state.completed.count("welcome") == 1


# ── Stage guidance render-data ─────────────────────────────────────────────


@pytest.mark.parametrize("stage", ["welcome", "api_key", "budgets", "csv_walkthrough", "first_run", "done"])
def test_stage_guidance_returns_well_formed_record(stage):
    from src.onboarding import stage_guidance

    guide = stage_guidance(stage)
    assert guide.stage == stage
    assert guide.title  # non-empty
    assert guide.body
    assert guide.primary_action


def test_unknown_stage_falls_back_to_welcome():
    from src.onboarding import stage_guidance

    guide = stage_guidance("never-existed")
    assert guide.stage == "welcome"


def test_api_key_stage_advertises_external_url():
    from src.onboarding import stage_guidance

    guide = stage_guidance("api_key")
    assert "anthropic" in (guide.external_url or "").lower()


def test_csv_walkthrough_stage_points_at_wealthsimple():
    from src.onboarding import stage_guidance

    guide = stage_guidance("csv_walkthrough")
    assert "wealthsimple" in (guide.external_url or "").lower()


# ── Demo mode ──────────────────────────────────────────────────────────────


def test_demo_snapshot_finds_bundled_samples():
    from src.onboarding import demo_snapshot

    snap = demo_snapshot()
    assert snap.available is True
    assert snap.holdings_csv is not None and snap.holdings_csv.exists()
    assert snap.recommendation_json is not None and snap.recommendation_json.exists()


def test_is_demo_mode_active_reads_env(monkeypatch):
    from src.onboarding import is_demo_mode_active

    monkeypatch.delenv("TECH_STOCK_DEMO_MODE", raising=False)
    assert is_demo_mode_active() is False
    monkeypatch.setenv("TECH_STOCK_DEMO_MODE", "1")
    assert is_demo_mode_active() is True


def test_sample_holdings_csv_has_expected_columns():
    from src.onboarding import demo_snapshot

    snap = demo_snapshot()
    body = snap.holdings_csv.read_text(encoding="utf-8")
    # Must look like a Wealthsimple-format holdings export so the existing
    # portfolio_loader can parse it.
    for required in ("Symbol", "Quantity", "Market Price", "Market Value"):
        assert required in body, f"sample CSV missing column: {required}"


def test_sample_recommendation_json_is_well_formed():
    from src.onboarding import demo_snapshot

    snap = demo_snapshot()
    payload = json.loads(snap.recommendation_json.read_text(encoding="utf-8"))
    assert payload.get("_demo") is True
    assert "recommendations" in payload
    assert isinstance(payload["recommendations"], list)
    assert len(payload["recommendations"]) >= 3
