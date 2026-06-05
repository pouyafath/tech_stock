"""First-run onboarding state machine (v1.19).

Why this exists
---------------
Pre-v1.19, getting started required:
  * cloning the repo
  * installing Python + .venv
  * obtaining an Anthropic API key (no in-product guidance)
  * understanding the Wealthsimple CSV export workflow
  * editing JSON files in config/

A user with a Wealthsimple account but no developer background couldn't
make it past step two. v1.19 introduces a state-machine driven wizard
that walks through every required step inside the UI itself, plus a
"demo mode" that runs against bundled sample data with cached Claude
responses so new users can see what they'd get before they pay a cent.

Design
------
* **Stateless module, stateful settings.** This file owns the state-
  machine logic; the actual "where are we in the wizard?" lives in
  ``config/settings.json`` under an ``onboarding`` block. That way the
  state survives app restarts and crashes mid-wizard.
* **Idempotent.** ``current_state()`` can be called any number of times
  and is cheap. Every transition is explicit.
* **UI-agnostic.** Returns dataclasses describing what to render — the
  Streamlit and Tk wizards both consume them. No UI code here.
* **Never raises.** Settings load failures, missing samples, or partial
  state all degrade gracefully so the wizard can't lock the user out.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "settings.json"
SAMPLES_DIR = ROOT / "data" / "samples"


# ── Stages ─────────────────────────────────────────────────────────────────

# Ordered. The wizard walks them in sequence; once the final ``done`` stamp
# is recorded, subsequent launches skip the wizard entirely.
STAGES: tuple[str, ...] = (
    "welcome",
    "api_key",
    "budgets",
    "csv_walkthrough",
    "first_run",
    "done",
)


@dataclass(frozen=True)
class OnboardingState:
    """Snapshot of the user's progress through the wizard."""

    stage: str
    completed: list[str] = field(default_factory=list)
    stamped_at: str | None = None  # ISO timestamp recorded once stage=="done"
    skipped_demo: bool = False

    @property
    def is_complete(self) -> bool:
        return self.stage == "done" and self.stamped_at is not None

    @property
    def next_stage(self) -> str | None:
        """Stage the wizard should render right now (None when done)."""
        if self.is_complete:
            return None
        return self.stage


@dataclass(frozen=True)
class StageGuidance:
    """Render-data for a single wizard stage. UI consumes; doesn't construct."""

    stage: str
    title: str
    body: str
    primary_action: str  # button label
    secondary_action: str | None = None  # 'Skip' / 'Use demo' etc.
    external_url: str | None = None  # e.g. console.anthropic.com link
    helper_text: str = ""


_GUIDANCE: dict[str, StageGuidance] = {
    "welcome": StageGuidance(
        stage="welcome",
        title="Welcome to tech_stock",
        body=(
            "tech_stock is an AI-powered portfolio advisor built on Claude. "
            "It reads your Wealthsimple holdings, runs a deterministic enrichment "
            "pipeline, asks Claude for a two-pass review, and produces a markdown "
            "report with priority actions, risk metrics, and a full audit trail.\n\n"
            "This setup takes about three minutes. You'll need:\n"
            "  • An Anthropic API key (we'll show you where to get one)\n"
            "  • Your Wealthsimple holdings CSV (we'll show you how to download it)\n"
            "  • About $5 USD for the first month of daily reports"
        ),
        primary_action="Get started",
        secondary_action="Try a demo (no setup, no API key)",
        helper_text="All data stays local on your machine. Only ticker symbols + thesis text are sent to Anthropic.",
    ),
    "api_key": StageGuidance(
        stage="api_key",
        title="Get your Anthropic API key",
        body=(
            "tech_stock uses Claude (made by Anthropic) for the recommendations.\n\n"
            "1. Click the link below — it opens console.anthropic.com in your browser\n"
            "2. Sign in or create an Anthropic account\n"
            "3. Click 'Create Key'\n"
            "4. Copy the key (starts with `sk-ant-…`) and paste it below\n\n"
            "Typical cost: $0.22 per report with Sonnet. A daily morning + afternoon "
            "run for a month is under $14."
        ),
        primary_action="I've pasted my key — continue",
        secondary_action="Skip for now (demo mode only)",
        external_url="https://console.anthropic.com/settings/keys",
        helper_text="The key is stored on your machine in config/.env — never uploaded anywhere.",
    ),
    "budgets": StageGuidance(
        stage="budgets",
        title="Set your monthly budget",
        body=(
            "How much are you willing to spend on Claude per month?\n\n"
            "We'll warn you when you hit 80% of this number, and pause runs "
            "when you hit 100% (you can always override). Default is $10 USD/month, "
            "which covers ~45 reports.\n\n"
            "Optionally: USD and CAD currency budgets per recommendation — these "
            "feed into the position-sizing engine, not the Claude cost."
        ),
        primary_action="Save & continue",
        helper_text="You can change these later in the Editor tab.",
    ),
    "csv_walkthrough": StageGuidance(
        stage="csv_walkthrough",
        title="Download your Wealthsimple holdings",
        body=(
            "We need your Wealthsimple holdings CSV. Here's the path:\n\n"
            "1. Open Wealthsimple (web or mobile)\n"
            "2. Tap your profile → Account details → Activity & statements\n"
            "3. Tap 'Generate report' → choose 'Holdings' and today's date\n"
            "4. Save the resulting CSV (named `holdings-report-YYYY-MM-DD.csv`)\n\n"
            "Drop it in your ~/Downloads folder and we'll find it automatically. "
            "Or upload it on the next screen."
        ),
        primary_action="I've got the file — continue",
        secondary_action="I'll do this later",
        external_url="https://help.wealthsimple.com/hc/en-ca/articles/4407454213275",
        helper_text="Optionally also grab activities-export-YYYY-MM-DD.csv for richer reports.",
    ),
    "first_run": StageGuidance(
        stage="first_run",
        title="Ready to run your first report",
        body=(
            "Everything's set. Choose one of these to finish setup:\n\n"
            "  • Run on my real holdings → ~$0.22, ~90 seconds\n"
            "  • Try the demo first → free, instant, uses bundled sample data\n\n"
            "After this you'll land on the dashboard with full results."
        ),
        primary_action="Run on my real holdings",
        secondary_action="Try the demo first",
    ),
    "done": StageGuidance(
        stage="done",
        title="You're all set",
        body="Setup is complete. Welcome to tech_stock.",
        primary_action="Open dashboard",
    ),
}


# ── State load / save ─────────────────────────────────────────────────────


def _load_settings() -> dict[str, Any]:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_settings(settings: dict[str, Any]) -> bool:
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        return True
    except OSError:
        return False


def current_state() -> OnboardingState:
    """Return the user's current wizard progress.

    A missing settings file or missing ``onboarding`` block means we've
    never run before → start at ``welcome``.
    """
    block = (_load_settings().get("onboarding") or {}) if CONFIG_PATH.exists() else {}
    stage = block.get("stage")
    if stage not in STAGES:
        stage = "welcome"
    completed = [s for s in (block.get("completed") or []) if s in STAGES]
    return OnboardingState(
        stage=stage,
        completed=completed,
        stamped_at=block.get("stamped_at"),
        skipped_demo=bool(block.get("skipped_demo", False)),
    )


def advance(*, current: str | None = None, skip_demo: bool = False) -> OnboardingState:
    """Mark the current stage complete and advance to the next.

    Caller usually passes ``current=None`` which defaults to the live
    state; pass an explicit value when re-entering a stage out of order.
    """
    state = current_state()
    current_stage = current or state.stage
    if current_stage not in STAGES:
        current_stage = "welcome"
    idx = STAGES.index(current_stage)
    next_stage = STAGES[idx + 1] if idx + 1 < len(STAGES) else "done"

    settings = _load_settings()
    block = dict(settings.get("onboarding") or {})
    completed = list(block.get("completed") or [])
    if current_stage not in completed:
        completed.append(current_stage)
    block["completed"] = completed
    block["stage"] = next_stage
    if skip_demo:
        block["skipped_demo"] = True
    if next_stage == "done" and not block.get("stamped_at"):
        block["stamped_at"] = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    settings["onboarding"] = block
    _save_settings(settings)

    return OnboardingState(
        stage=block["stage"],
        completed=completed,
        stamped_at=block.get("stamped_at"),
        skipped_demo=bool(block.get("skipped_demo", False)),
    )


def reset_onboarding() -> None:
    """Clear the wizard state so the user can rerun it.  Used by tests + the
    'Reset onboarding' debug action in the Editor tab.
    """
    settings = _load_settings()
    settings.pop("onboarding", None)
    _save_settings(settings)


def needs_onboarding() -> bool:
    """True iff the wizard hasn't been completed.

    Override via env var ``TECH_STOCK_SKIP_ONBOARDING=1`` — useful for CI,
    headless runs, and the existing-user upgrade path where forcing a
    wizard would be hostile.
    """
    if os.environ.get("TECH_STOCK_SKIP_ONBOARDING") == "1":
        return False
    return not current_state().is_complete


def stage_guidance(stage: str) -> StageGuidance:
    """Render-data for one stage. Falls back to the welcome card on unknown input."""
    return _GUIDANCE.get(stage, _GUIDANCE["welcome"])


# ── Demo mode ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DemoSnapshot:
    """The bundled-sample data the demo mode hands the UI."""

    holdings_csv: Path | None
    activities_csv: Path | None
    recommendation_json: Path | None
    available: bool


def demo_snapshot() -> DemoSnapshot:
    """Locate the bundled sample files. Missing files → ``available=False``."""
    holdings = SAMPLES_DIR / "holdings-report-sample.csv"
    activities = SAMPLES_DIR / "activities-export-sample.csv"
    recommendation = SAMPLES_DIR / "recommendation_log_sample.json"
    return DemoSnapshot(
        holdings_csv=holdings if holdings.exists() else None,
        activities_csv=activities if activities.exists() else None,
        recommendation_json=recommendation if recommendation.exists() else None,
        available=holdings.exists() and recommendation.exists(),
    )


def is_demo_mode_active() -> bool:
    """The Streamlit app sets this env-var when the user picks 'Try demo'."""
    return os.environ.get("TECH_STOCK_DEMO_MODE") == "1"


__all__ = [
    "STAGES",
    "OnboardingState",
    "StageGuidance",
    "DemoSnapshot",
    "current_state",
    "advance",
    "reset_onboarding",
    "needs_onboarding",
    "stage_guidance",
    "demo_snapshot",
    "is_demo_mode_active",
]
