# tech_stock 📈

> A Claude-powered portfolio advisor for Wealthsimple Premium USD accounts with twice-daily trading recommendations, fee-aware analysis, and conviction scoring.

[![GitHub](https://img.shields.io/badge/GitHub-tech--stock-blue)](https://github.com/pouyafath/tech_stock)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-green)]()
[![Claude API](https://img.shields.io/badge/API-Sonnet%204.6%20%26%20Opus%204.7-orange)]()
[![License](https://img.shields.io/badge/License-MIT-lightgrey)]()

---

## 🎯 Overview

**tech_stock** is an intelligent portfolio advisor that analyzes your Wealthsimple holdings and provides structured trading recommendations twice daily (morning/afternoon sessions). The original CLI remains the canonical workflow, with optional Streamlit and Textual interfaces layered on top of the same report pipeline. It leverages Claude AI to:

- **Analyze** your portfolio in real-time with live market data
- **Score** each trade idea by conviction (1-10) and net expected return after fees
- **Recommend** specific actions: BUY, ADD, HOLD, TRIM, SELL with thesis statements
- **Calculate** realistic fees (Wealthsimple Premium + USD account bid-ask spreads)
- **Export** recommendations as both markdown reports and CSV tables for easy tracking

### Key Features

- ✅ **Trader Action Plan** — Review-before-trading execution table ordered by urgency
- ✅ **Critical Actions Block** — Consolidates quality warnings, manual-review gates, drift, and leveraged ETF risks near the top
- ✅ **Report Quality Gates** — Deterministic warnings for stale quotes, missing catalysts, range errors, and sizing risk
- ✅ **Two-Pass Claude Review** — First-pass JSON is critiqued against quality warnings and drift, then revised before rendering
- ✅ **Deterministic Exit Sizing** — SELL/TRIM rows show exact shares, position fraction, and estimated proceeds when holdings data is available
- ✅ **Intelligent Sizing** — Investment amounts ($50–$700 per session) based on conviction and budget
- ✅ **Hold Tiers** — HOLD recommendations labeled as watch / keep / add-on-dip for clarity
- ✅ **Earnings Alerts** — Flags tickers with earnings within 7 days; adjusts risk profile
- ✅ **Risk Controls** — Entry zones, stop-loss, take-profit, catalyst verification, and manual-review flags per recommendation
- ✅ **Exit Planning** — Target exit dates and Bear Case / Bull Case ranges for every trade
- ✅ **Portfolio Risk Dashboard** — Beta, volatility, drawdown estimate, company exposure rollups, and hedge suggestions
- ✅ **Buy Signals View** — Source-backed BUY/ADD and add-on-dip snapshots with analyst consensus, targets, catalysts, quality warnings, and data-source notes
- ✅ **Trade Readiness Badges** — Buy Signals are classified as Trade Ready / Review First / Blocked using deterministic quote, catalyst, quality-gate, and source checks
- ✅ **Data Confidence** — Reports and dashboards show quote freshness, source coverage, catalyst coverage, warning counts, and readiness status before trade details
- ✅ **Actionability Check** — Reports now summarize Trade Ready / Review First / Blocked status near the top before the audit sections
- ✅ **Report Review + Feedback** — Every UI can review the latest report's gates, drift, source degradation, readiness, and pending decision-journal rows
- ✅ **Recommendation Outcomes** — Fixed 1/5/20-day outcome tracking with stable recommendation IDs, benchmark alpha, stop/take-profit checks, and cost-per-useful-outcome stats
- ✅ **Doctor / Preflight** — `python src/main.py doctor --json` checks version, update cache, API keys, CSV Health, budget status, release assets, and demo smoke readiness
- ✅ **No-Spend App Self-Test** — Diagnostics can validate setup readiness, bundled demo smoke, report-review loading, and support-bundle availability without Claude spend
- ✅ **CSV Health** — Detects Wealthsimple holdings vs activities schemas, swapped files, stale exports, and sample/demo CSVs before paid runs
- ✅ **Data Files / Workspace** — Every UI can show and save the exact CSV, API key, report, log, upload, and workspace paths the app will use
- ✅ **Ready To Run + Pre-run Checklist** — Paid runs show a READY / REVIEW_FIRST / BLOCKED verdict and stop before Claude spend if API keys, CSV schemas, sample files, or budget checks are blocking
- ✅ **Setup Readiness** — `python src/main.py setup --json` and all UIs show first-run status, recommended CSVs, workspace readiness, and the next setup action
- ✅ **Redacted Support Bundle** — `python src/main.py support-bundle --preview` shows included/excluded files, and `support-bundle` exports doctor/setup/data-file summaries and diagnostics logs without raw API keys or CSV contents
- ✅ **Package Smoke Checks** — CI verifies source, macOS, Windows, and Linux package structure/version metadata before release artifacts are uploaded
- ✅ **Verified Updates** — Release downloads are checked against published SHA256 checksums when available
- ✅ **8 Time Horizons** — Intraday / next session / 1-3 trading days / 1-2 weeks / 1-3 months / 3-6 months / 6-12 months / 12-36 months
- ✅ **6 Enrichment APIs** — Parallel data from Finnhub, Polygon, Twelve Data, FRED, CoinGecko (+ optional Alpha Vantage)
- ✅ **Fee-Aware** — Refuses to recommend trades below the fee hurdle (default 0.5% net expected return)
- ✅ **Conviction Scoring** — 1-10 scale; scores < 6 automatically become HOLD recommendations
- ✅ **Live Market Data** — Quote timestamp, previous close, pre/after-market moves, day range, quote source, 10-month history, PE ratios, FCF yield, margins, dividends, 52-week highs/lows via yfinance
- ✅ **Recent News** — Pulls last 7 days of headlines per ticker from Yahoo Finance
- ✅ **Trade History Context** — Loads your recent Wealthsimple trades to avoid whipsawing
- ✅ **Decision Journal & Outcome Scoring** — Records accepted/ignored/modified recommendations and measures your results against the model
- ✅ **Triple Output** — Markdown report + CSV table + JSON log for backtesting
- ✅ **Four Interface Options** — Original CLI remains default, with embedded Desktop App, Streamlit dashboard, and Textual terminal UI
- ✅ **Model Choice** — Pick Sonnet 4.6 (~$0.30-$0.70/run typical two-pass range) or Opus 4.7 (higher cost, deeper analysis) per session
- ✅ **Fast Parallel Fetching** — Concurrent API requests with caching and graceful degradation

---

## ✨ What's New in v1.34.0 (June 17, 2026)

**Recommendation outcome tracking release.**

- **Outcomes tab everywhere** — Desktop, Streamlit, and Textual now show fixed
  1/5/20-day results for every actionable recommendation from saved JSON logs.
- **Stable recommendation IDs** — outcome rows use IDs like
  `20260616_morning_NVDA_ADD_001`, making it easier to discuss, compare, and
  debug individual calls.
- **Benchmark-aware scoring** — BUY/ADD rows compare stock follow-through with
  QQQ/SMH where relevant; TRIM/SELL rows measure saved drawdown and alpha
  versus the relevant benchmark.
- **Closed feedback loop** — future paid runs receive a compact outcome summary
  through the existing calibration context, and generated reports show a
  fixed-window Track Record block when mature outcomes exist.

## ✨ What's New in v1.33.0 (June 16, 2026)

**Report review and feedback-loop release.**

- **Report Review everywhere** — Desktop, Streamlit, and Textual now show the
  latest report's review gates, Data Confidence, quality warnings, source
  degradation, drift versus the previous report, and recommendation readiness
  from one shared view model.
- **Decision feedback from the report** — Desktop and Streamlit can record
  accepted / ignored / modified / delayed / watch / executed feedback directly
  beside the report, updating `data/decision_journal.json`.
- **No-spend app self-test** — Diagnostics now checks version metadata, setup
  readiness, bundled demo smoke, report-review loading, and support-bundle
  availability without Claude spend.
- **Copyable review summaries** — Report Review and Diagnostics include compact
  support text that can be pasted into a bug report without exposing API keys or
  raw Wealthsimple CSV contents.

## ✨ What's New in v1.32.0 (June 14, 2026)

**Packaged-app confidence and paid-run clarity release.**

- **Ready To Run view** — Desktop, Streamlit, and Textual now show a compact
  `READY` / `REVIEW_FIRST` / `BLOCKED` verdict before paid Claude runs.
- **Support-bundle preview** — CLI and UIs list every included support file and
  every excluded sensitive artifact before creating a zip.
- **Actionability Check in reports** — generated reports now show
  data-confidence verdict, quote freshness, source coverage, catalyst coverage,
  warning count, and top review reason near the top.
- **Package smoke checks** — CI and release builds validate source checkout,
  macOS app bundle, Windows app folder, and Linux artifacts before upload.

## ✨ What's New in v1.31.0 (June 14, 2026)

**Setup and supportability release: make first-run troubleshooting explicit.**

- **Setup readiness everywhere** — CLI, Desktop, Streamlit, and Textual now
  show onboarding state, workspace writability, API key status, paid-run
  blockers, update status, demo availability, and one next action.
- **CSV candidate confirmation** — Data Files views show the holdings and
  activities CSVs found on disk, mark the recommended choice, and explain
  sample/demo, stale, swapped, or incomplete exports.
- **Redacted support bundle zip** — export a support zip from CLI or UI with
  doctor/setup/data-file summaries and diagnostics logs. It excludes raw API
  keys, `.env`, `.env.zip`, and raw Wealthsimple CSV contents.
- **New CLI commands** — use `python src/main.py setup --json` for setup
  readiness and `python src/main.py support-bundle` for support export.

## ✨ What's New in v1.30.0 (June 13, 2026)

**Usability release: make setup and inputs hard to get wrong.**

- **Data Files / Workspace** — Desktop, Streamlit, and Textual now show the
  current holdings CSV, activities CSV, API key file, reports folder, logs
  folder, uploads folder, and workspace status in one place.
- **Saved CSV defaults** — save selected holdings/activities paths to
  `config/data_files.json` so the app reuses the correct files on the next
  launch.
- **Shared pre-run checklist** — all UIs validate Anthropic key, CSV schemas,
  sample/demo files, budget status, optional API coverage, and update status
  before a paid report run.
- **Demo smoke buttons** — all UIs can validate bundled sample data and view
  models without API keys or Claude spend.
- **History context** — report history now shows input CSV names, action counts,
  warning counts, and data-confidence labels when JSON logs are available.

## ✨ What's New in v1.29.0 (June 13, 2026)

**CSV import reliability and safer paid runs.**

- **CSV Health diagnostics** — Doctor, Desktop Diagnostics, and Streamlit
  Diagnostics now show detected CSV type, schema status, age, path, and the
  recommended fix.
- **Swapped-file protection** — If holdings and activities CSVs are selected in
  the wrong fields, report runs auto-correct them when both files are present;
  one-file mistakes fail early with a clear action.
- **Sample-data blocking** — sample/demo holdings CSVs are blocked for paid
  runs unless demo mode is explicitly active.

## ✨ What's New in v1.28.0 (June 11, 2026)

**Release-health diagnostics for safer updates.**

- **Updater simulation in Doctor** — `python src/main.py doctor --simulate-current-version 1.27.2 --force-refresh`
  checks GitHub Releases as if the installed app were an older version. This
  verifies that a published update is visible without editing source files or
  applying the update.
- **Clearer release verification** — the doctor payload now records the
  simulated current version and shows it in the Version summary row.
- **Backward compatible** — existing CLI, Desktop, Streamlit, Textual, updater,
  and report workflows continue to work unchanged.

## ✨ What's New in v1.27.2 (June 10, 2026)

**Desktop consolidation and release hardening.**

- **One canonical desktop implementation** — `src/desktop/app.py` now owns the
  embedded Tkinter app, while `src/desktop_app.py` is a thin compatibility
  launcher for existing commands and imports.
- **CI green path restored** — fixed the desktop alias regression and removed
  duplicated GUI coverage from the headless coverage gate.
- **Higher coverage floor** — CI now enforces 55% minimum coverage, with local
  validation at 66%.
- **Release gate hardened** — tag-triggered release builds now run
  `pip-audit` before packaging and opt GitHub Actions into the Node 24 runtime
  ahead of GitHub's Node 20 deprecation.

## ✨ What's New in v1.24.0 (June 4, 2026)

**Quality, resilience & analytics improvements.**

- **Expanded risk metrics** — Sortino ratio, Calmar ratio, VaR 95%, and CVaR 95% added to the risk dashboard and the desktop Performance tab (with tooltips). Derived from existing price history, no new API dependencies.
- **Live FX rate** — USD/CAD conversion now fetches a live rate via a keyless source (exchangerate-api.com with FRED public-CSV fallback), cached 4 hours, wired into the report pipeline as the fallback when no FRED key is set. Static 1.37 fallback preserved for offline runs.
- **Claude API resilience** — Automatic retry on rate limit errors (429/529/503) with exponential backoff (5s/15s/45s). Pass 2 quality review now has a graceful fallback to Pass 1 if it fails, instead of crashing the run.
- **Sector rotation conflict gate** — New quality gate flags contradictions between sector warnings ("reduce tech") and BUY/ADD recommendations on tech tickers.
- **Journal filters + CSV export** — Streamlit Journal tab has ticker filter, date range filter, and outcome filter. CSV export button added.
- **Schedule time picker** — Replaced hour/minute number inputs with native `st.time_input` widgets.
- **Backtest equity curve** — Cumulative portfolio index chart rendered from realized examples.
- **Degradation health surfaced** — `degradation_health()` now displays in the Streamlit Diagnostics tab.
- **Claude analyst unit tests** — New test file with 14 tests covering normalization, schema validation, and Pass 2 fallback behavior.

Current local suite: `pytest -q` passes with 637 tests.

## ✨ What's New in v1.23.0 (June 3, 2026)

**B2C user-friendliness overhaul — consumer-ready desktop experience.**

- **Simplified navigation** — 12 tabs reduced to 7 with sub-notebooks. Reports tab groups Run/Latest/History. Settings tab groups Preferences/API Keys/Schedule/Advanced Editor/Updates. Dashboard renamed to "Home".
- **Native onboarding wizard** — 6-stage setup wizard built into the desktop app (Welcome → API Key → Budget → CSV → First Run → Done). No more redirect to Streamlit.
- **Tooltips everywhere** — Hover tooltips on ~35 widgets explaining financial terms (beta, volatility, conviction) and button actions in plain English.
- **Progress indicators** — Animated progress bar with elapsed timer during report generation. Visual feedback replaces the old silent "Running report..." text.
- **Status bar** — Persistent bottom bar showing connection status, last report time, session cost, and version.
- **Friendly settings** — New Preferences panel with form-based controls for budget, risk tolerance, model choice, and feature toggles. Raw JSON editor preserved as "Advanced Editor".
- **Consumer-friendly labels** — "Run Report" → "Generate Report", "Quality Gates" → "Risk Alerts", "Stops & Breaches" → "Price Alerts", etc.

Current local suite: `pytest -q` passes with 587 tests (4 desktop-specific tests require tkinter display).

## ✨ What's New in v1.22.0 (June 3, 2026)

**macOS desktop UI overhaul — professional, consistent, dark-themed.**

- **Consistent font ladder** — Every label, metric, card, and text widget now uses the platform-aware font stack (`SF Pro` on macOS, `Segoe UI` on Windows). No more hardcoded `Helvetica`.
- **Unified dark theme** — Report viewer and history switched from jarring light background to the shared dark PALETTE. Markdown rendering, search highlights, and all text widgets now match the rest of the app.
- **PALETTE token consistency** — Eliminated ~30 hardcoded hex colour literals. Every surface traces back to shared design tokens.
- **Refined panels & cards** — Uppercase muted section labels with separator lines. Metric cards with proper typographic hierarchy. Cleaner tab labels.
- **Polished chrome** — Improved header, styled comboboxes/entries/scrollbars, clam theme for full dark-mode control.

> **V2 note:** do not call the next update `v2.0.1`. V2 should wait until public releases match repo version, updater flow works from older installs, demo mode works without keys, installers pass smoke tests on macOS/Windows/Linux, user-data migration rules are documented, and production installers are signed/notarized.

## ✨ What's New in v1.21.0 (May 29, 2026)

**Stabilization, supportability, and V2 readiness gate.**

- **Doctor / Preflight** — `python src/main.py doctor --json` reports installed version, latest GitHub release, update-cache age/source, workspace paths, API-key discovery, CSV freshness, budget status, and release asset availability.
- **Diagnostics Preflight** — Desktop and Streamlit Diagnostics show the same preflight table before paid runs.
- **Force-refresh updates** — manual checks bypass the 6-hour cache and show whether the result came from cache or live GitHub Releases.
- **Demo smoke test** — validates bundled samples, markdown rendering, Dashboard and Buy Signals view models with no network spend.
- **Data Confidence** — reports and dashboards surface quote freshness, source coverage, catalyst coverage, warning counts, and readiness status.

Current local suite at that release: `pytest -q` passed with 588 tests.

## ✨ What's New in v1.20.0 (May 27, 2026)

**Release engineering + docs refactor — one tag = one release.**

- **CI release pipeline** — push a `v*.*.*` tag and GitHub Actions handles the rest: a three-OS test gate (`macos-14`, `windows-latest`, `ubuntu-22.04` run `pytest + ruff` in parallel), three platform-specific build jobs (`.dmg`, Windows `.exe` + Inno Setup installer, Linux AppImage + tarball), and a final `release` job that generates `SHA256SUMS.txt`, parses the matching CHANGELOG section, and publishes a draft GitHub Release with everything attached.
- **New `src/changelog_utils.py`** — `python -m src.changelog_utils 1.20.0` extracts the release notes for a tag; used by the CI to populate the Release body.
- **Docs refactor** — README went from 1583 → 1128 lines. New `docs/` directory: `ARCHITECTURE.md` (module map, data flow, learning loop, 7 quality gates, 5 design tenets), `COOKBOOK.md` (12 common workflows), `RELEASE_PROCESS.md` (CI flow). `CONTRIBUTING.md` rewritten with design tenets, commit-message style, and "adding a new X" pattern guides.
- **533 → 579 tests** — `test_changelog_utils.py` (13), `test_release_workflow.py` (15), `test_docs_links.py` (18).

Current local suite at that release: `pytest -q` passed with 579 tests.

## ✨ What's New in v1.19.1 (May 27, 2026)

**Patch: close the v1.19 loose ends.**

- **5 new CLI flags** the installer / scheduler already invoked: `--demo`, `--import-csv PATH`, `--session-type`, `--non-interactive`, `--force`. With `--non-interactive` and no session given, the CLI auto-picks `morning` (before noon) or `afternoon` based on local time, so headless launchd / Task Scheduler / cron runs no longer hang.
- **Workspace export-as-zip** (`src/workspace_export.py`) — wired into the Privacy card's previously-stubbed "Export workspace" button. Secrets (`.env`, `API_KEYS.txt`, the temporary upload folder, anything looking like a key/PEM) are scrubbed automatically; reports / logs / journal / thesis log / cost log / settings.json are included.
- **Desktop wizard hook** — the Tk desktop app now shows a one-time dialog on first launch pointing at the Streamlit wizard (where the full step-by-step flow lives).
- **515 → 533 tests**. Two new test files: `test_cli_flags.py` (10) and `test_workspace_export.py` (8).

Current local suite: `pytest -q` passes with 533 tests in ~3 s.

## ✨ What's New in v1.19.0 (May 27, 2026)

**Productisation — any Wealthsimple account holder can now install + use this, not just developers.**

- **🚀 First-run wizard** — six guided stages (Welcome → Anthropic API key → budgets → Wealthsimple CSV walkthrough → first run / demo → done). State is stamped to `config/settings.json` so a mid-wizard crash resumes where you left off. Streamlit short-circuits the dashboard until setup is complete; existing users are bypassed automatically (the `onboarding` block isn't present in their settings.json).
- **🎬 Demo mode** — bundled `data/samples/` ships a realistic 5-position Wealthsimple holdings CSV + a cached Claude recommendation log. New users click "Try demo" on the launcher (or skip the wizard) to see a full report instantly with **zero setup, zero API key, zero cost**.
- **💰 Spend tracker + monthly budget cap** — every run appends to `data/cost_log.jsonl`. New Spend sub-section in the Diagnostics tab shows total / MTD / projected monthly + a 30-day chart. `settings.json → monthly_budget_usd` soft-warns at 80%, hard-blocks at 100% (override via `ALLOW_OVERAGE=1`). Default is 0 (no cap) — opt-in.
- **🔒 Privacy card** — clear explainer of what gets sent to Anthropic vs what stays local. Confirmation-gated "Delete all local data" button wipes reports / logs / journal / cache / thesis log / cost log in one go.
- **🪟 Windows installer parity** — `installer_windows.iss` now consumes a real version from `src/version.py`, registers a per-user CSV file association so double-clicking a holdings export opens the app, adds a Start-Menu group with a separate "tech_stock (Demo mode)" shortcut, ships the samples component, includes optional Authenticode signing.
- **🐧 Linux AppImage** — new `build_linux.sh` produces a portable AppImage (or tarball fallback) with a proper `.desktop` entry under `Categories=Finance;Office;`.
- **467 → 515 tests**. Three new test files cover the wizard state machine, the cost tracker + budget enforcement, and static checks on the Windows / Linux installer artefacts.

Current local suite: `pytest -q` passes with 515 tests in ~2 s.

> **Older release notes** — see [`CHANGELOG.md`](CHANGELOG.md) for the full history (v1.0 → v1.19).

---

## 📖 Documentation

- **[`QUICKSTART.md`](QUICKSTART.md)** — five-minute setup guide.
- **[`docs/USER_GUIDE.md`](docs/USER_GUIDE.md)** — complete user guide.
- **[`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)** — troubleshooting common issues.
- **[`ANALYSIS_AND_SIGNALS.md`](ANALYSIS_AND_SIGNALS.md)** — methodology and signal definitions.
- **[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)** — module map, data flow, the 7 quality gates, the learning loop, storage layout.
- **[`docs/COOKBOOK.md`](docs/COOKBOOK.md)** — common workflows: demo mode, scheduling, budget caps, replaying old sessions, custom notifications.
- **[`docs/RELEASE_PROCESS.md`](docs/RELEASE_PROCESS.md)** — how a `v*.*.*` tag triggers the three-platform CI build.
- **[`CONTRIBUTING.md`](CONTRIBUTING.md)** — design tenets, daily workflow, commit-message style, where contributions are most welcome.
- **[`CHANGELOG.md`](CHANGELOG.md)** — full release history.

---

## 🚀 Getting Started

### Prerequisites

- **Python 3.11+** (via Homebrew on macOS: `brew install python@3.11`)
- **Anthropic API key** (from https://console.anthropic.com/)
- **Wealthsimple Premium account** with a USD trading account
- **Optional UI dependencies** are included in `requirements.txt` (`streamlit` and `textual`)

### Installation — Choose Your OS

Each operating system has two supported ways to use tech_stock:

| OS | App-based option | Terminal-based option |
|---|---|---|
| macOS | Native `.dmg` / `.app` launcher with embedded Desktop App, or Streamlit browser dashboard | `./run.sh` or `python src/main.py` |
| Windows | Native `.exe` launcher with embedded Desktop App, or Streamlit browser dashboard | PowerShell / Command Prompt with `python src/main.py` |
| Linux | Embedded Desktop App from source, or Streamlit browser dashboard | `./run.sh` or `python src/main.py` |

The terminal workflow is the most reliable for development and automation. The app-based workflow is better for users who prefer buttons, upload widgets, report history, and a dashboard.

### Step 1 — Download Or Clone

**Option A: Download a prebuilt app**

Use this if you want the app-based macOS or Windows launcher:

1. Open the [Releases page](https://github.com/pouyafath/tech_stock/releases).
2. Download the latest macOS `.dmg` or Windows `.exe` / zipped app artifact.
3. Put `API_KEYS.txt` beside the app, or in the project folder if you are running from source.

Linux release builds provide an AppImage when `appimagetool` succeeds, with a tarball fallback. There is not currently a `.deb` or `.rpm`.

**Option B: Clone the source**

Use this for terminal mode, Streamlit, Textual, local development, or building the native app yourself:

```bash
git clone https://github.com/pouyafath/tech_stock.git
cd tech_stock
```

### Step 2 — Set Up API Keys

Anthropic is required. Enrichment keys are optional but improve report quality.

**Easy method, recommended:**

```bash
cp API_KEYS.template.txt API_KEYS.txt
```

Open `API_KEYS.txt` and paste your keys:

```bash
# macOS
open API_KEYS.txt

# Linux
nano API_KEYS.txt

# Windows PowerShell
notepad API_KEYS.txt
```

**Advanced method:**

```bash
cp .env.example .env
# Edit .env in your editor
```

### macOS

#### macOS Option 1 — App-Based

Use the prebuilt `.dmg` from the [Releases page](https://github.com/pouyafath/tech_stock/releases), or build it locally:

```bash
chmod +x build_macos.sh
./build_macos.sh
```

Then open `dist/tech_stock.dmg`, drag `tech_stock.app` to Applications, and launch it. The launcher gives you buttons for:

- Desktop App
- Streamlit Web UI
- Textual Terminal UI
- Original CLI
- Check Updates

The **Desktop App** is fully embedded in the native application and does not need a browser. It includes Dashboard, Buy Signals, Run Report, Report Viewer with Report Review, History, Config Editor, API Checks, Diagnostics, Data Files, and Updates tabs.

The **Streamlit Web UI** remains available for users who prefer a browser dashboard. It starts a local server and opens your default browser at a local URL such as `http://localhost:8501`. If your browser does not open automatically, the launcher shows the URL so you can paste it manually.

**First launch on macOS:** current public builds are ad-hoc signed, not Apple-notarized. macOS may show `"tech_stock" Not Opened` or `Apple could not verify "tech_stock" is free of malware`. This is expected for unsigned/non-notarized open-source builds.

To open it:

1. Click **Done** on the warning.
2. Open **System Settings → Privacy & Security**.
3. Scroll to **Security**.
4. Find `"tech_stock" was blocked to protect your Mac`.
5. Click **Open Anyway**, then confirm.

You only need to do this once per downloaded build. To avoid this warning for every user, the app must be signed with an Apple Developer ID certificate, submitted to Apple notarization, and stapled before release.

#### macOS Option 2 — Terminal-Based

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
chmod +x run.sh run-ui.sh

# Interactive launcher: CLI / Streamlit / Textual / Desktop / Update
./run.sh

# Direct CLI
./run.sh morning
./run.sh afternoon --model opus
./run.sh 5

# Original Python entrypoint
python src/main.py
python src/main.py check-update
python src/main.py update
```

### Linux

#### Linux Option 1 — App-Based Browser Dashboard

Linux currently uses the Streamlit browser dashboard as its app-based interface:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

.venv/bin/python -m streamlit run ui/streamlit_app.py
```

Open the local URL printed by Streamlit, normally `http://localhost:8501`.

#### Linux Option 2 — Terminal-Based

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
chmod +x run.sh run-ui.sh

# Interactive launcher: CLI / Streamlit / Textual / Desktop / Update
./run.sh

# Direct CLI
./run.sh morning
./run.sh afternoon --model opus
./run.sh 5

# Original Python entrypoint
python src/main.py
python src/main.py check-update
python src/main.py update
```

### Windows

#### Windows Option 1 — App-Based

Use the prebuilt Windows artifact from the [Releases page](https://github.com/pouyafath/tech_stock/releases), or build it locally from PowerShell / Command Prompt:

```bat
build_windows.bat
```

Then run:

```bat
dist\tech_stock\tech_stock.exe
```

The Windows launcher offers Desktop App, Streamlit Web UI, Textual Terminal UI, Command-Line mode, and Check Updates. The embedded Desktop App also has an Updates tab.

If you want an installer-style package, use `installer_windows.iss` with Inno Setup after building.

#### Windows Option 2 — Terminal-Based

PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

# Interactive CLI
python src\main.py

# Direct CLI
python src\main.py morning --holdings "$HOME\Downloads\holdings-report-YYYY-MM-DD.csv"
python src\main.py afternoon --model opus --holdings "$HOME\Downloads\holdings-report-YYYY-MM-DD.csv"

# Updates
python src\main.py check-update
python src\main.py update

# Browser dashboard
python -m streamlit run ui\streamlit_app.py

# Terminal dashboard
python ui\textual_app.py
```

If PowerShell blocks activation, run:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then run `.\.venv\Scripts\Activate.ps1` again.

### First Run — What To Expect

In CLI mode, you will be walked through 5 questions:

```
Session type (morning/afternoon) [Enter = morning]:
1. How much USD would you like to invest today? $500
2. How much CAD would you like to invest today? $1000
3. Holdings CSV detected: /Users/you/Downloads/holdings-report-2026-04-24.csv
   Is this correct? (Y/N): Y
4. Activities CSV detected: /Users/you/Downloads/activities-export-2026-04-24.csv
   Is this correct? (Y/N, or Enter to skip): Y
5. Which model would you like to use?
   [1] Sonnet 4.6 — ~$0.30-$0.70/run typical two-pass range (recommended for daily use)
   [2] Opus 4.7   — higher cost, deeper analysis, better for complex portfolios
   Choose (1/2) [Enter = 1]:
```

Done! The app will:
- Auto-detect your latest CSV files from `~/Downloads/`
- Fetch live market data for portfolio/watchlist tickers, benchmark risk tickers, and sector/cross-asset context
- Run deterministic quality checks and two Claude passes
- Compare previous actionable recommendations with recent activities when an activities CSV is provided
- Generate reports in `reports/` directory

---

## 📊 Usage

### Interactive Mode (Recommended)

```bash
python src/main.py
```

Perfect for one-off analysis. The app remembers nothing between runs, so each session is fresh.

**Typical flow:**
1. Export Holdings CSV from Wealthsimple (Account → Activity → Export)
2. Save to Downloads (or any location)
3. Run the command above
4. Answer 5 quick questions
5. Get recommendations + markdown report + CSV export

### CLI Mode (For Scripting)

If you want to automate or use in cron jobs:

```bash
# Morning session with fresh holdings
python src/main.py morning --holdings ~/Downloads/holdings-report-2026-04-24.csv

# With trade history (once per week)
python src/main.py morning \
  --holdings ~/Downloads/holdings-report-2026-04-24.csv \
  --activities ~/Downloads/activities-export-2026-04-24.csv

# Afternoon session
python src/main.py afternoon --holdings ~/Downloads/holdings-report-2026-04-24.csv

# Force Opus model (default is Sonnet)
python src/main.py morning --holdings ~/Holdings.csv --model opus
```

### Running the Application

**macOS / Linux:**

| Command | What happens |
|---------|-------------|
| `./run.sh` | Interactive menu — pick CLI / Streamlit / Textual / Desktop / Update |
| `./run.sh morning` | Skip menu → CLI, morning session |
| `./run.sh afternoon --model opus` | Skip menu → CLI, Opus model |
| `./run.sh 2` | Skip menu → Streamlit (browser opens automatically) |
| `./run.sh 3` | Skip menu → Textual TUI |
| `./run.sh 4` | Skip menu → embedded Desktop App |
| `./run.sh 5` | Skip menu → check for updates |
| `python src/main.py check-update` | Check GitHub Releases for a newer version |
| `python src/main.py update` | Update a source checkout with `git pull --ff-only` or stage a packaged update |
| `python src/main.py doctor --json` | Run preflight diagnostics: version, updater cache, API keys, CSV Health, budget, release assets |
| `python src/main.py doctor --json --force-refresh --simulate-current-version 1.27.2` | Verify whether an older installed version would see the latest published release |
| `python src/main.py setup --json` | Show first-run/setup readiness, selected files, CSV candidates, and next action |
| `python src/main.py support-bundle` | Export a redacted support zip under `exports/` |
| `python src/main.py support-bundle --preview` | Preview support zip contents and exclusions without writing a file |

**Windows PowerShell / Command Prompt:**

| Command | What happens |
|---------|-------------|
| `python src\main.py` | Interactive CLI |
| `python src\main.py morning --holdings "%USERPROFILE%\Downloads\holdings-report-YYYY-MM-DD.csv"` | Direct morning CLI run |
| `python src\main.py afternoon --model opus --holdings "%USERPROFILE%\Downloads\holdings-report-YYYY-MM-DD.csv"` | Direct afternoon CLI run with Opus |
| `python src\main.py check-update` | Check GitHub Releases for a newer version |
| `python src\main.py update` | Update a source checkout with `git pull --ff-only` or stage a packaged update |
| `python src\main.py doctor --json` | Run preflight diagnostics: version, updater cache, API keys, CSV Health, budget, release assets |
| `python src\main.py doctor --json --force-refresh --simulate-current-version 1.27.2` | Verify whether an older installed version would see the latest published release |
| `python src\main.py setup --json` | Show first-run/setup readiness, selected files, CSV candidates, and next action |
| `python src\main.py support-bundle` | Export a redacted support zip under `exports\` |
| `python src\main.py support-bundle --preview` | Preview support zip contents and exclusions without writing a file |
| `python -m streamlit run ui\streamlit_app.py` | Streamlit browser dashboard |
| `python ui\textual_app.py` | Textual terminal dashboard |
| `python src\desktop_app.py` | Embedded desktop dashboard |

All four interface options call the **same report engine** through the shared `ReportPipeline` facade. UI runs disable automatic file opening and return the generated markdown/CSV/JSON paths inside the interface.

### Embedded Desktop App

```bash
python src/desktop_app.py
# or
./run.sh 4
```

The Desktop App is a native Tkinter dashboard that runs inside the application window. It does not start Streamlit and does not need a browser.

Tabs:
- **Dashboard** — Shows the next action, portfolio/risk metric cards, Data Confidence, priority action queue, quality gates, stop breaches, drift, hedge ideas, market context, watchlist signals, and Claude cost
- **Buy Signals** — Shows source-backed BUY/ADD and add-on-dip snapshots with readiness badges, Data Confidence, filters, overview cards, consensus/targets, catalysts/risks, and source notes
- **Run Report** — Select session/model/budgets, confirm Wealthsimple CSV paths, preview holdings, see the Ready To Run verdict, check setup, run no-spend demo smoke, and run the same report pipeline as CLI mode with live progress
- **Report Viewer** — Opens the latest generated markdown report with styled headings, readable paragraph spacing, aligned table blocks, native word search, highlighted matches, Next/Previous controls, search paths behind **Show Search Paths**, and a Report Review panel for gates/drift/decision feedback
- **History** — Browse previous markdown reports with input CSV names, action counts, warning counts, data-confidence labels, and the same styled markdown renderer
- **Config Editor** — Edit `config/settings.json`, `config/watchlist.json`, or fallback `config/portfolio.json` with JSON validation
- **Data Files** — Show setup readiness, recommended CSV candidates, saved holdings/activities defaults, API key file, reports folder, recommendation logs folder, uploads folder, and workspace path
- **API Checks** — Check Anthropic, yfinance, Finnhub, Polygon, Twelve Data, FRED, CoinGecko, and Alpha Vantage connectivity; show every API-key file path and active storage mode; add/update/delete API keys from the app
- **Diagnostics** — Shows Preflight/doctor status, no-spend app self-test, source degradation health, recent errors, copyable diagnostics, support-bundle contents preview, and a redacted support-bundle zip export
- **Updates** — Check GitHub Releases, force-refresh the update cache, download/apply newer versions, verify release checksums when present, and view update logs

The embedded viewer is a native styled markdown reader. Use Streamlit if you specifically want browser-rendered markdown, side-by-side history comparison, and download buttons.

Default file locations:
- **Source checkout:** app data is saved inside the project folder, for example `<project>/data/`, `<project>/reports/`, `<project>/temporary_upload/`, and `<project>/config/`.
- **Packaged desktop app:** app data is saved in `~/Documents/tech_stock/` by default, because `/Applications/tech_stock.app` is not a good writable data folder.
- **Override:** set `TECH_STOCK_HOME=/your/path` before launching to force a different writable workspace.
- **Uploaded/copied CSVs:** `temporary_upload/` under the active workspace
- **Markdown/CSV reports:** `reports/` under the active workspace
- **Recommendation JSON logs:** `data/recommendations_log/` under the active workspace
- **Decision journal:** `data/decision_journal.json` under the active workspace

Report search order for Report Viewer and History:
1. Active workspace `reports/` folder
2. Current working folder `reports/`
3. `~/Documents/tech_stock/reports/`
4. `~/Desktop/tech_stock/reports/`
5. `~/Downloads/tech_stock/reports/`
6. Source checkout `reports/` folder

The Desktop App shows this exact list, with found/missing status and report counts, in History and behind **Show Search Paths** in Report Viewer.

### Updating

All interactive interfaces check GitHub Releases on startup and ask before applying a newer version. You can also check manually:

- **Native launcher:** click **Check Updates**.
- **Desktop App:** open the **Updates** tab.
- **Streamlit:** use the **Updates** section in the sidebar.
- **Textual:** open the **Updates** tab; startup checks show an Update now / Later prompt.
- **Terminal:** run `python src/main.py check-update`, `python src/main.py update`, or `python src/main.py doctor --json`. For release-health testing, add `--force-refresh --simulate-current-version <old-version>`.
- **Unified launcher:** run `./run.sh 5`.

Data is stored separately from the app binary, so updating does not remove your `reports/`, `data/recommendations_log/`, `temporary_upload/`, `config/`, `decision_journal.json`, `API_KEYS.txt`, or `.env` files. Update logs are written under the app workspace in `logs/update.log`.

Packaged macOS and Windows builds download the correct asset from the latest GitHub Release and verify it against `SHA256SUMS.txt` when the release provides checksums. Source checkouts update with `git pull --ff-only`. Startup checks may use a short-lived cache; manual checks in the app force-refresh GitHub Releases and show whether the result came from cache or live GitHub.

API key search order:
1. `~/Documents/tech_stock/API_KEYS.txt` or `.env` in packaged app mode
2. The current working folder
3. `~/Desktop/tech_stock/API_KEYS.txt` or `.env`
4. `~/Downloads/tech_stock/API_KEYS.txt` or `.env`
5. The source checkout folder

Current API-key storage mode is file-based: `API_KEYS.txt` and `.env`. The API Checks tab shows this active storage mode plus the exact discovered key paths. OS credential stores such as macOS Keychain, Windows Credential Manager, and Linux Secret Service are planned as an optional future storage mode; the file-based mode remains the simple default.

### Streamlit Dashboard

```bash
streamlit run ui/streamlit_app.py
```

Then open the local URL Streamlit prints, normally `http://localhost:8501`.

Tabs:
- **Dashboard** — Shows latest JSON-log metrics for risk, priority actions, quality warnings, hedge suggestions, drift, cost/tokens, and API connectivity
- **Today's Report** — Renders the latest markdown report with `st.markdown` and a Report Review panel for gates, drift, readiness, and decision feedback
- **Run Report** — Select session/model/budgets, upload or point to Wealthsimple CSVs, preview holdings before spending Claude tokens, and trigger the same report pipeline as CLI mode with live progress
- **History** — Browse previous markdown reports from `reports/`, filter/search by filename, compare two reports side by side, and review/report feedback for older sessions
- **Backtest** — View metrics, action/conviction/ticker buckets, bar charts, and recent realized examples
- **Outcomes** — Score every actionable recommendation over fixed 1/5/20-day windows with hit rate, alpha, best/worst calls, source buckets, stop/take-profit checks, and cost-per-useful-outcome stats
- **Decision Journal** — Record whether you accepted, ignored, modified, delayed, watched, or executed each actionable recommendation; run the model-vs-user scorecard. Report Review can also record this feedback in context.
- **Portfolio Editor** — Edit `config/settings.json`, `config/watchlist.json`, or fallback `config/portfolio.json` with live JSON validation

Defaults:
- Budget/model fields are read from `config/settings.json`
- Uploaded CSVs are copied into `temporary_upload/` and remain git-ignored
- If no holdings CSV is selected, you can explicitly use fallback `config/portfolio.json`
- Generated markdown, CSV, and JSON files get download buttons after a successful Streamlit run

### Textual Terminal UI

```bash
python ui/textual_app.py
```

The Textual app runs fully in the terminal and provides the same workflow tabs as the Streamlit dashboard, including Report Review and Outcomes. Long reports are shown in scrollable terminal panes, which is more reliable for very large markdown reports than terminal markdown rendering in the currently pinned Textual version.

Useful keyboard shortcuts:
- `r` refreshes the active tab
- `Ctrl+R` starts a report run
- `Ctrl+S` saves the JSON editor when the content is valid

### Decision Journal

After every report, actionable BUY/ADD/TRIM/SELL recommendations are added to local `data/decision_journal.json` as pending rows. Use Report Review in Desktop/Streamlit or the Streamlit **Decision Journal** tab to record what you actually did.

CLI helpers are also available:

```bash
# Show journal status and outcome scorecard
python -m src.decision_journal --score

# Record one row manually
python -m src.decision_journal \
  --record-id 20260510_2011_afternoon.json:SOXL \
  --decision accepted \
  --actual-action SELL \
  --shares 2.2292 \
  --price 117.97 \
  --reason "Accepted leveraged ETF exit"
```

The next paid run feeds the scorecard back into Claude so recommendations can calibrate against your real follow-through pattern.

### Schedule Recurring Sessions

**Linux / macOS (cron):**
```bash
crontab -e
# Morning 9:30 AM ET weekdays:
30 9 * * 1-5 /path/to/tech_stock/run.sh morning --holdings ~/Downloads/latest_holdings.csv
```

**macOS (launchd — more reliable than cron):**

Save as `~/Library/LaunchAgents/com.techstock.morning.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>         <string>com.techstock.morning</string>
  <key>ProgramArguments</key>
  <array>
    <string>/path/to/tech_stock/run.sh</string>
    <string>morning</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardOutPath</key> <string>/tmp/tech_stock_morning.log</string>
  <key>StandardErrorPath</key><string>/tmp/tech_stock_morning.log</string>
</dict>
</plist>
```
```bash
launchctl load ~/Library/LaunchAgents/com.techstock.morning.plist
```

**Windows (Task Scheduler):**
```bat
schtasks /create /tn "tech_stock morning" /tr "C:\path\to\tech_stock\build_windows.bat" /sc WEEKLY /d MON,TUE,WED,THU,FRI /st 09:30
```

---

## 🖥️ Native App (macOS .dmg / Windows .exe)

For users who don't want a terminal, tech_stock ships as a native desktop application.

### Building Locally

**macOS:**
```bash
./build_macos.sh          # installs PyInstaller, builds dist/tech_stock.dmg
```
Double-click `tech_stock.dmg` → drag `tech_stock.app` to Applications → double-click.

The local build uses ad-hoc signing. macOS Gatekeeper may block the first launch with `Apple could not verify "tech_stock" is free of malware`. Open **System Settings → Privacy & Security → Security** and click **Open Anyway** for `tech_stock`. This trust approval is normally needed once per build.

**Windows:**
```bat
build_windows.bat         :: builds dist\tech_stock\tech_stock.exe
```
Distribute the entire `dist\tech_stock\` folder. Users double-click `tech_stock.exe`.

### Pre-built Releases (GitHub Actions)

Push a version tag to trigger automatic builds:
```bash
git tag v1.21.0 && git push --tags
```
GitHub Actions runs the three-OS test gate first, then builds macOS `.dmg`, Windows installer/zip artifacts, Linux AppImage/tarball artifacts, and `SHA256SUMS.txt`. Each platform build runs `python tools/package_smoke.py` before upload to confirm the executable, version metadata, and bundled UI/support modules are present. The workflow creates a **draft** GitHub Release. Download artifacts, smoke-open them, verify checksums, then publish the draft from the [Releases page](https://github.com/pouyafath/tech_stock/releases).

Current macOS release artifacts are ad-hoc signed but not notarized. That means Apple Gatekeeper can block first launch until the user approves it in **System Settings → Privacy & Security → Open Anyway**. A warning-free macOS release requires an Apple Developer Program account, Developer ID signing, notarization, and stapling in the release workflow.

### What the App Does

On launch the native app shows a dark-themed launcher window (built with tkinter — no extra dependency):
- **Desktop App** — opens the embedded browser-free dashboard inside a native app window
- **Streamlit Web UI** — starts the Streamlit server, opens your default browser, and shows the local URL if the browser does not open automatically
- **Textual Terminal UI** — opens the keyboard-driven terminal dashboard in Terminal / Command Prompt
- **Command-Line (CLI)** — opens Terminal / Command Prompt and runs the original CLI

Your `.env` / `API_KEYS.txt` must exist in the same directory as the app or its parent.

---

## 📁 Understanding CSV Exports

### Holdings Report (Wealthsimple)

**When to export:** Every run (takes 30 seconds)
**Where:** Account → Activity → Export Holdings Report (CSV)

Contains your current positions:
- Ticker, quantity, average cost, market price
- Current market value, unrealized P&L
- Currency (USD or CAD), account type

The app reads this to:
- Calculate current portfolio concentration
- Determine available capital for new positions
- Track P&L on existing holdings

### Activities Export (Wealthsimple)

**When to export:** Once per week (optional but recommended)
**Where:** Account → Activity → Export Activities Export (CSV)
**Period:** Export the **full available history** when Wealthsimple allows it. The app still uses only the recent 90-day slice for prompt context, but it uses the full file for FIFO holding-age calculations.

Contains your trade history:
- Dates, tickers, BUY/SELL, quantity, price
- Commissions, net cash

The app reads this to:
- Understand recent trading patterns
- Avoid "whipsawing" (recommend reversing a recent trade without new catalyst)
- Provide context on conviction changes since your last trade
- Calculate exact holding days when the export includes the original open-lot buys; otherwise the report shows a conservative lower bound

---

## 📈 Output Files

After each run, you get **three files**:

### 1. Markdown Report
**Path:** `reports/YYYYMMDD_HHMM_morning.md`

Human-readable with:
- Session summary (market context)
- Report Quality Warnings and Critical Actions before the detailed audit sections
- Previous Session Execution Check when an activities CSV is provided
- Numbered recommendations with emoji indicators 🟢🟡⚪🟠🔴
- Conviction scores and net expected returns
- Full thesis for each trade
- Quote & Data Quality footnotes explaining live/provider quote vs daily-close fallback behavior
- Risk dashboard, company exposure rollup, hedge suggestions, and leveraged ETF decay estimates
- Watchlist flags (unwatched stocks worth monitoring)
- Warnings (concentration risk, leverage decay, etc.)

**Use this for:** Reading before market open, sharing with others

### 2. CSV Table
**Path:** `reports/YYYYMMDD_HHMM_morning_recommendations.csv`

Structured table with trader-facing columns:
- **Ticker** — Stock symbol
- **Action** — BUY, ADD, HOLD, TRIM, or SELL
- **Conviction** — 1–10 score
- **Expected Stock Move %** — Expected move of the underlying security
- **Expected Benefit of Action %** — For SELL/TRIM, avoided drawdown or protected gain; for BUY/ADD, upside after fees
- **Net Expected %** — Backward-compatible net expected field
- **Time Horizon** — Intraday / next session / 1-3 trading days / 1-2 weeks / 1-3 months / 3-6 months / 6-12 months / 12-36 months
- **Hold Tier** — For HOLD only: watch (conviction ≤5) / keep (6–7) / add_on_dip (≥8)
- **Invest USD** — Amount to invest (for BUY/ADD only)
- **Action Shares / Action Fraction / Action Amount** — Deterministic SELL/TRIM size and approximate proceeds when holdings data is available
- **Exit Target** — Target exit date (e.g., "Jul 2026")
- **Bear Case %** — Conservative expected move from now
- **Bull Case %** — Optimistic expected move from now
- **Stop Loss % / Take Profit %** — Risk controls relative to current price
- **Catalyst Verified / Catalyst Source / Manual Review** — Catalyst gate fields for large movers and near-earnings names
- **Quote / Previous Close / Quote Time UTC / Quote Source** — Quote audit fields for execution review
- **Earnings Alert** — ⚠️ if earnings within 7 days
- **Thesis** — Text summary

**Use this for:** Importing into Excel/Sheets, tracking decisions, backtesting, position sizing

**Example:**
```csv
Ticker,Action,Hold Tier,Conviction,Invest USD,Action Shares,Action Fraction,Action Amount,Expected Stock Move %,Expected Benefit of Action %,Net Expected %,Time Horizon,Exit Target,Bear Case %,Bull Case %,Stop Loss %,Take Profit %,Catalyst Verified,Catalyst Source,Manual Review,Quote,Previous Close,Quote Time UTC,Quote Source,Earnings Alert,Thesis
NVDA,ADD,,8,$500,,,,+15.00%,+14.89%,+14.89%,3-6 months,Jul 2026,-8%,+18%,-7%,+18%,YES,Finnhub earnings/news,NO,210.50 USD,205.12 USD,2026-04-29T20:00:01+00:00,yfinance:regularMarketPrice,,Core AI infrastructure play...
SOXL,SELL,,9,,2.2292,100%,$263 USD,-20.00%,+19.70%,+19.70%,next session,Apr 2026,-30%,-10%,-6%,+0%,NO,,YES,117.97 USD,109.56 USD,2026-04-29T20:00:00+00:00,yfinance:regularMarketPrice,,Leveraged ETF decay risk...
```

### 3. JSON Log
**Path:** `data/recommendations_log/YYYYMMDD_HHMM_morning.json`

Raw machine-readable format for:
- Backtesting frameworks
- Custom analysis pipelines
- Archival/audit trails
- Model evaluation

---

## ⚙️ Configuration

### `config/settings.json`

```json
{
  "budget_cad": 3000,
  "cad_per_usd_assumption": 1.37,
  "risk_tolerance": "aggressive",
  "account_type": "wealthsimple_premium_usd",
  "claude_model": "claude-sonnet-4-6",
  "claude_max_tokens": 24000,
  "claude_timeout_seconds": 480,
  "enable_two_pass_review": true,
  "enable_opus_extended_thinking": true,
  "opus_thinking_budget_tokens": 4096,
  "min_net_expected_return_pct": 0.5,
  "max_position_pct": 25,
  "quote_reconciliation_threshold_pct": 1.5,
  "risk_benchmark_tickers": ["SPY", "QQQ", "SMH"],
  "sector_rotation_tickers": ["XLK", "XLV", "XLF", "XLE", "XLY", "XLP", "XLU", "XLI"],
  "cross_asset_tickers": ["UUP", "TLT", "GLD", "HYG"],
  "enable_options_implied_move_for_earnings": false,
  "enable_enrichment": true,
  "alpha_vantage_enabled": false,
  "recent_activity_days": 90,
  "holding_days_activity_days": null,
  "enable_decision_journal": true,
  "decision_journal_score_horizons": [1, 5, 20, 60],
  "decision_journal_max_scored_decisions": 200,
  "decision_journal_include_holds": false,
  "news_lookback_days": 7,
  "news_prompt_max_articles": 2,
  "history_months": 10
}
```

**Key settings:**

| Key | Default | Purpose |
|-----|---------|---------|
| `budget_cad` | 3000 | Available CAD to deploy (overridden per run) |
| `risk_tolerance` | "aggressive" | "moderate" for conservative recommendations |
| `claude_model` | "claude-sonnet-4-6" | "claude-sonnet-4-6" (fast) or "claude-opus-4-7" (thorough) |
| `claude_max_tokens` | 24000 | Max output tokens for structured JSON; paired with compact string caps and one retry to prevent truncation |
| `claude_timeout_seconds` | 480 | Hard timeout for each Claude API call |
| `enable_two_pass_review` | true | Always run the second Claude critique/revision pass |
| `enable_opus_extended_thinking` | true | Enables extended thinking only when the selected model is Opus |
| `opus_thinking_budget_tokens` | 4096 | Token budget reserved for Opus extended thinking |
| `min_net_expected_return_pct` | 0.5 | Hurdle rate — trades below this are refused |
| `max_position_pct` | 25 | Single position size cap (% of portfolio) |
| `quote_reconciliation_threshold_pct` | 1.5 | Warn when holdings CSV prices differ materially from quote data |
| `risk_benchmark_tickers` | SPY, QQQ, SMH | Benchmarks used for beta/risk estimates |
| `sector_rotation_tickers` | XLK, XLV, XLF, XLE, XLY, XLP, XLU, XLI | Sector context shown to Claude and the report |
| `cross_asset_tickers` | UUP, TLT, GLD, HYG | Dollar/rates/gold/credit context shown to Claude and the report |
| `enable_enrichment` | true | Enable/disable all enrichment APIs |
| `alpha_vantage_enabled` | false | Alpha Vantage free tier limited to 25 req/day; set true only with paid plan |
| `enable_options_implied_move_for_earnings` | false | Optional yfinance options implied move lookup; disabled by default because option-chain calls can be slow |
| `recent_activity_days` | 90 | Recent activity slice sent to Claude and used for previous-session execution checks |
| `holding_days_activity_days` | null | Activity window used for FIFO holding-day calculation; `null` means parse the full export |
| `enable_decision_journal` | true | Seed actionable recommendations into the local decision journal and render the scorecard |
| `decision_journal_score_horizons` | 1, 5, 20, 60 | Calendar-day windows used to score model-vs-user outcomes |
| `decision_journal_max_scored_decisions` | 200 | Max recorded decisions scored per run to keep historical price fetches bounded |
| `decision_journal_include_holds` | false | Whether HOLD rows should be seeded into the journal; default keeps the journal action-focused |
| `news_lookback_days` | 7 | How far back to fetch news headlines |
| `news_prompt_max_articles` | 2 | Max articles per ticker included in the Claude prompt; report output can still show catalyst headlines |
| `history_months` | 10 | Months of historical price data to fetch |

### Enrichment APIs (Professional-Grade Market Intelligence)

The app integrates **6 financial data sources** to enrich Claude's analysis with professional-grade signals. All sources run in parallel in Phase 1; optional Alpha Vantage runs sequentially in Phase 2.

| API | Data | Rate Limit | Status |
|-----|------|-----------|--------|
| **Finnhub** | Analyst consensus, analyst upgrades/downgrades, earnings calendar, insider activity, news sentiment | Free tier: unlimited | Phase 1 (parallel) |
| **Polygon** | Previous-day OHLCV + VWAP signals; optional current snapshot if the API plan allows it | Free tier varies by endpoint | Phase 1 (parallel) |
| **Twelve Data** | Real-time quotes, earnings dates (better for Canadian tickers) | Free tier: 5/min | Phase 1 (parallel) |
| **FRED** (Federal Reserve) | Macro context: Fed Funds Rate, CPI inflation, yield curve, VIX, plus macro-calendar estimates | Free tier: unlimited | Phase 1 (parallel) |
| **CoinGecko** | BTC price, 7d change, Fear & Greed Index, macro risk signal | Free tier: 10-50/min | Phase 1 (parallel) |
| **Alpha Vantage** (optional) | News sentiment analysis | **Free tier: 25/day** ⚠️ | Phase 2 (sequential) |

**To enable Alpha Vantage** (only if you have a paid plan):
- Set `"alpha_vantage_enabled": true` in `config/settings.json`
- Get your API key from https://www.alphavantage.co/

**API Key Setup:**

Create `API_KEYS.txt` from the template:
```
ANTHROPIC_API_KEY=sk-ant-...
FINNHUB_API_KEY=cxxxxxxxxxxx
ALPHA_VANTAGE_API_KEY=demo
TWELVE_DATA_API_KEY=demo_api_key
POLYGON_API_KEY=your_key_here
FRED_API_KEY=your_key_here
COINGECKO_API_KEY=your_key_here
```

`ANTHROPIC_API_KEY` is required. The enrichment keys are optional; any missing or failing enrichment source is skipped and recorded in the report's data coverage notes.

---

### `config/watchlist.json`

Tickers to monitor (not yet held). Each entry can include target entry/exit prices for alerts:

```json
{
  "_comment": "Each entry: ticker, optional category, optional target prices.",
  "entries": [
    {"ticker": "MSFT",    "category": "megacaps",      "target_entry_price": 380.0,  "target_exit_price": null},
    {"ticker": "AMD",     "category": "growth",        "target_entry_price": 250.0,  "target_exit_price": 320.0},
    {"ticker": "PLTR",    "category": "aggressive",    "target_entry_price": 125.0,  "target_exit_price": null}
  ]
}
```

---

## 💰 Fee Model (Wealthsimple Premium + USD Account)

The app models realistic trading costs:

| Fee Component | Amount | One-Way Cost |
|---|---|---|
| Commission | $0 | 0% |
| FX Spread (USD account) | $0 | 0% |
| Bid-ask (megacap: AAPL, MSFT, NVDA, GOOGL, TSLA) | ~0.05% | 0.05% |
| Bid-ask (large-cap: AMD, CRM, AVGO) | ~0.15% | 0.15% |
| Bid-ask (mid-cap: PLTR, ARM, SMCI) | ~0.40% | 0.40% |
| SEC regulatory fee (US stocks) | ~$0.03/trade | ~0.005% for $5k trade |

**Round-trip cost (buy + sell):** 2 × one-way bid-ask

**Example:**
- Buy 10 shares of NVDA at $118: ~$0.12 cost (0.05% × 2)
- Expected move must exceed 0.12% just to break even

Claude **refuses to recommend BUY/ADD** if `net_expected_pct < min_net_expected_return_pct`.

---

## 📋 Logging Your Trades

After you execute a trade in Wealthsimple, log it in `data/trade_history.csv`:

```csv
date,ticker,action,shares,price_cad,followed_recommendation,notes
2026-04-24,NVDA,BUY,5,118.50,yes,morning recommendation 4/24
2026-04-24,LULU,SELL,10,17.25,yes,exit on conviction 8/10
2026-04-25,PLTR,HOLD,0,24.60,no,waiting for better entry
```

After 4–6 weeks, analyze:
- How many recommendations did you follow? (`followed_recommendation = yes`)
- What's your P&L on followed vs non-followed trades?
- Is the agent beating "just buy and hold QQQ"?

---

## 🏗️ Architecture

The deep architecture map — module-by-module purpose, data flow, the 7-layer quality gate, the learning loop, storage layout, and the five design tenets — now lives in **[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)**.

A one-paragraph summary: tech_stock reads your Wealthsimple holdings CSV, fans out to ~7 external data sources in parallel, runs a deterministic enrichment + drift + thesis-tracking pipeline, sends a single richly-contextualised user message to Claude (with prompt caching), runs a 7-layer quality gate, lets Claude review its own first pass with the warnings + drift surfaced, normalises the recommendation, sizes the trades deterministically, and writes a markdown report + CSV + JSON log. Past recommendations feed back via the backtester (Sharpe-dampened sizing multipliers + reliability diagram + walk-forward stability) and the Outcomes engine (fixed 1/5/20-day hit rate, alpha, and saved drawdown). User decisions feed back via the decision journal (per-horizon edge). The Learning and Outcomes tabs visualise this loop.

## 🤔 FAQ

### Q: Sonnet vs Opus — which should I use?

**A:** Sonnet 4.6 covers ~90% of use cases at roughly 20% of the cost. Use **Opus 4.7** when:
- Your portfolio has many positions and the conviction scores feel too uniform
- You want extended thinking enabled (deeper chain-of-thought reasoning)
- You're analysing an unusual macro environment (yield curve inversion, crypto correlation)

Typical costs: Sonnet two-pass ≈ $0.30–$0.70 · Opus two-pass ≈ $1.50–$3.00+ depending on portfolio size and output length.

### Q: What if an enrichment API is down?

**A:** The app degrades gracefully. Each enrichment source (Finnhub, Polygon, Twelve Data, FRED, CoinGecko) is fetched in parallel inside a try/except block. A failed source is recorded in the report's "Data Coverage" section but does not stop the run. Claude still receives all available data and generates a full recommendation. You'll see something like `[Finnhub: ERROR — rate limit]` in the report header.

### Q: How does two-pass review work?

**A:** After Pass 1, the app runs deterministic quality checks (13 warning codes: stale quotes, missing catalyst, reversed price ranges, etc.) and compares this session's actions against the previous session's drift. Pass 2 sends Claude the Pass 1 JSON *plus* all quality warnings and drift data, and asks it to revise. This is why BUY recommendations on names that moved 7% overnight with no verified news typically get downgraded to HOLD — the quality gate is deterministic, but Claude also sees the warning in Pass 2 and adjusts its thesis.

### Q: What's the "invest_amount_usd" in the CSV?

**A:** The amount Claude recommends to invest for each BUY/ADD trade, based on your session budget ($50–$700) and conviction. Higher conviction = larger allocation (up to 40% of budget). For example, with a $500 budget and conviction 8, you might invest $200. This lets you buy fractional shares proportional to your thesis strength.

### Q: What do the hold tiers mean?

**A:** For HOLD recommendations, Claude assigns a tier:
- **watch** (conviction ≤5): Low conviction; reassess next session
- **keep** (6–7): Medium conviction; hold but don't add
- **add_on_dip** (≥8): High conviction; add more if price pulls back 2–5%

This helps you prioritize which HOLDs to monitor for entry opportunities.

### Q: Why does some recommendations show "⚠️ EARNINGS THIS WEEK"?

**A:** The app flags tickers with earnings within 7 days and adjusts the risk profile. Volatility often spikes around earnings, so the recommendation may suggest a shorter time horizon or smaller position size. Check your CSV for the `earnings_alert` column.

### Q: What's the "Exit Target" and "Bear/Bull Case"?

**A:** Every recommendation includes:
- **Exit Target Date** (e.g., "Jul 2026") — when Claude expects you to close the position
- **Bear Case % / Bull Case %** — conservative and optimistic expected moves from entry (e.g., -8% to +18%)
- **Stop Loss % / Take Profit %** — risk-control levels relative to current price

Use these to set stop-loss and take-profit orders in Wealthsimple.

### Q: How do I set up the enrichment APIs?

**A:** Copy `API_KEYS.template.txt` to `API_KEYS.txt` and fill in your Anthropic key plus any enrichment keys you have. Anthropic is required for recommendations. Enrichment keys are optional; missing APIs are skipped and listed as coverage gaps where applicable. To disable all enrichment, set `"enable_enrichment": false` in `config/settings.json`.

### Q: Why is Alpha Vantage disabled by default?

**A:** Alpha Vantage's free tier is limited to 25 requests per day (you'd hit that in one morning run with 25+ tickers). It's optional and runs sequentially in Phase 2 only if enabled. Enable it only if you have a paid plan.

### Q: Do I have to follow the recommendations?

**A:** No. This tool is advisory only. You execute all trades manually in Wealthsimple. Log your actual trades in `trade_history.csv` to measure the agent's performance.

### Q: How often should I run it?

**A:** Twice daily is the design pattern:
- **Morning (~9:30 AM ET):** Pre-open setup, overnight catalysts, premarket moves
- **Afternoon (~3 PM ET):** Intraday action, EOD positioning, swing trade entries

But you can run it as often as you like. Use `min_net_expected_return_pct` (default 0.5%) to avoid churn.

### Q: Can I use this with a CAD account or non-Wealthsimple broker?

**A:** The fee model is hard-coded for Wealthsimple Premium USD accounts. For other brokers, you'd need to modify `fee_calculator.py`. CAD accounts are handled but fees will be inaccurate.

### Q: What's the cost per run?

**A:** With Sonnet two-pass review, expect roughly `$0.30-$0.70` for a full portfolio run. The latest full run with 31 tracked tickers, enrichment enabled, 12 recommendation rows, and two Claude passes used 50,105 tokens and cost `$0.6341`.
With Opus two-pass review, expect higher cost depending on output length and extended-thinking budget.
**Note:** Enrichment APIs have no cost (all free tiers).

### Q: Can I schedule this automatically?

**A:** Yes. Use cron (Linux/macOS) or Task Scheduler (Windows) to call the CLI mode at 9:30 AM and 3 PM. You'll need to:
1. Store your API key in `API_KEYS.txt` or `.env` (make sure `.gitignore` excludes both)
2. Have your Holdings CSV auto-exported or manually placed in `~/Downloads/`
3. Use a wrapper script to activate venv and run the command

### Q: How do I backtest the recommendations?

**A:** Use `data/trade_history.csv` to track execution, and `data/recommendations_log/` for raw JSON. Compare:
- Recommendations you followed vs didn't follow
- Your P&L vs QQQ buy-and-hold benchmark
- Win rate by sector, action type (ADD vs SELL), conviction score
- Correlation between exit targets and actual outcomes

---

## 🛠️ Troubleshooting

### "API key not found"
Make sure `API_KEYS.txt` or `.env` contains `ANTHROPIC_API_KEY=your_key_here`. The app loads `API_KEYS.txt` first and then `.env`.

### "Holdings CSV not found"
The app looks for `holdings-report-*.csv` in `~/Downloads/`. Either:
1. Answer "N" to the auto-detected path and provide the full path
2. Move your CSV to Downloads
3. Export a fresh Holdings report from Wealthsimple

### "No recent news available"
This can be normal for some tickers because yfinance news availability varies by ticker and day. If every ticker shows no news, clear `data/.cache/news/` and rerun; v1.10 parses the current `content.pubDate` news format and avoids caching empty headline responses.

### "Claude response parsing failed"
The response was truncated or not valid JSON. The current default `claude_max_tokens` is `24000`, Rule 32 enforces compact JSON, and the app retries once with emergency caps if truncation is detected. If this still happens with a very large portfolio or news-heavy run, reduce watchlist scope or disable optional enrichment before raising the token cap further. Higher token caps can raise cost and make non-streamed Claude responses slower.

### "GitHub Actions cannot import src"
The workflow sets `PYTHONPATH: ${{ github.workspace }}` for pytest. If you create another workflow, include the same environment variable or install the project as a package before running tests.

---

## 🧪 Testing And CI

Run the local test suite:

```bash
source .venv/bin/activate
PYTHONPATH="$(pwd)" python -m pytest -q
```

The repository includes a GitHub Actions workflow at `.github/workflows/tests.yml` that installs `requirements.txt` and runs `pytest -q` on push and pull requests. The workflow sets `PYTHONPATH` to the repository root so tests can import the local `src` package.

Current focused coverage includes:
- Holdings parsing, CDR detection, `.TO` normalization, CASH handling, and required-column failures
- Sector/company exposure rollups, share-class aliasing, hedge suggestions, and risk dashboard behavior
- Drift tracking for latest-session lookup, action flips, and conviction jumps
- Schema normalization for risk controls, catalyst fields, and Bear/Bull ranges
- Market-data indicators and mocked options implied-move helper
- Report quality gates, normalized range warnings, decision-tree checks, near-earnings catalyst gating, and hard catalyst downgrades
- Markdown rendering for quality warnings, critical actions, data freshness footnotes, risk dashboard, hedge suggestions, Bear/Bull labels, and cost footer
- UI support helpers for canonical runner invocation, progress streaming, latest JSON-log dashboard summaries, report history ordering, JSON config validation, and default budget/model loading

---

## 📚 Project Structure

```
tech_stock/
├── .github/
│   └── workflows/tests.yml      ← GitHub Actions pytest workflow
├── config/
│   ├── portfolio.json           ← Fallback portfolio (used if no CSV provided)
│   ├── watchlist.json           ← Tickers to monitor
│   └── settings.json            ← Budget, risk, model, fee settings
├── data/
│   ├── trade_history.csv        ← YOUR TRADE LOG (manually maintained)
│   └── recommendations_log/     ← JSON recommendations (per session)
├── reports/
│   ├── YYYYMMDD_HHMM_morning.md ← Markdown report
│   └── YYYYMMDD_HHMM_morning_recommendations.csv ← CSV table
├── tests/                       ← Pytest suite for parsers, quality gates, rendering, drift, and analytics
├── src/
│   ├── __init__.py
│   ├── main.py                  ← Entry point (CLI + interactive, API key loading)
│   ├── report_pipeline.py       ← ReportPipeline facade for shared UI runs
│   ├── config.py                ← Load settings (single source of truth)
│   ├── constants.py             ← Shared constants, company aliases, leveraged ETF leverage
│   ├── _utils.py                ← Helper functions (safe_float, clean_csv_row, etc.)
│   ├── portfolio_loader.py      ← Parse Holdings CSV
│   ├── activity_loader.py       ← Parse Activities CSV
│   ├── portfolio_analytics.py   ← Risk dashboard, company rollups, hedge suggestions
│   ├── market_data.py           ← Fetch prices, pre/after-market fields, fundamentals, indicators
│   ├── news_fetcher.py          ← Fetch headlines (parallel)
│   ├── fee_calculator.py        ← Wealthsimple fee model
│   ├── enriched_data.py         ← Orchestrate 6 enrichment APIs (Phase 1 parallel, Phase 2 sequential)
│   ├── finnhub_client.py        ← Analyst consensus, upgrades/downgrades, earnings, insider activity, sentiment
│   ├── polygon_client.py        ← Previous-day OHLCV + VWAP signals, optional current snapshot
│   ├── twelve_data_client.py    ← Real-time quotes, earnings dates (better Canadian coverage)
│   ├── fred_client.py           ← Macro context plus calendar estimates
│   ├── coingecko_client.py      ← BTC price, 7d change, Fear & Greed, macro risk signal
│   ├── alpha_vantage_client.py  ← News sentiment (thread-safe rate limiter; optional)
│   ├── backtester.py            ← Historical recommendation calibration
│   ├── report_quality.py        ← Deterministic quality gates and warnings
│   ├── data_confidence.py       ← Shared quote/source/catalyst/readiness trust summary
│   ├── claude_analyst.py        ← 40-rule prompt, two-pass Claude review, JSON retry/parsing
│   ├── report_generator.py      ← Priority actions table, hold tiers, earnings badges, markdown + CSV
│   ├── view_models.py           ← Shared dashboard, Buy Signals, API health, journal view models
│   ├── ui_support.py            ← Shared helpers for UI progress, dashboards, previews, validation, and connectivity
│   ├── preflight.py             ← Doctor command, release/update/API/CSV/budget/demo smoke checks
│   ├── updater.py               ← GitHub Releases checks, downloads, checksums, update logs
│   ├── version.py               ← App version for CLI, UIs, packaging, updater
│   ├── desktop/                 ← Embedded no-browser dashboard implementation
│   ├── desktop_app.py           ← Backward-compatible desktop launcher/import wrapper
│   ├── app_gui.py               ← Native tkinter launcher (used by .app/.exe bundle)
│   └── ui_launcher.py           ← Shell menu wrapper (CLI / Streamlit / Textual / Desktop / Update)
├── ui/
│   ├── streamlit_app.py         ← Optional browser dashboard
│   └── textual_app.py           ← Optional terminal dashboard
├── assets/
│   ├── icon.png                 ← App icon source
│   └── icon.icns                ← macOS icon (generated by build_macos.sh)
├── pyinstaller_hooks/
│   └── hook-streamlit.py        ← Ensures Streamlit static assets are bundled
├── run.sh                       ← Unified entry point (menu when no args, CLI passthrough with args)
├── run-ui.sh                    ← Alias for run.sh (backward compat)
├── build_macos.sh               ← macOS build: → dist/tech_stock.dmg
├── build_windows.bat            ← Windows build: → dist/tech_stock/tech_stock.exe
├── installer_windows.iss        ← Optional Inno Setup installer script
├── tech_stock.spec              ← PyInstaller build specification
├── requirements.txt             ← Python runtime + UI dependencies
├── .env.example                 ← Template for API keys
├── .gitignore                   ← Excludes .env, .venv, reports/, dist/, build/
├── README.md                    ← This file
└── LICENSE                      ← MIT
```

---

## 🤝 Contributing

Contribution guidelines, design tenets, the commit-message style we use, where contributions are most welcome, and the daily test/lint/format flow all live in **[`CONTRIBUTING.md`](CONTRIBUTING.md)**.

---

## ⚖️ License

MIT License — see LICENSE file for details.

---

## 📞 Support

For issues or questions:
- Check the [FAQ](#-faq) above
- Review the [Troubleshooting](#-troubleshooting) section
- Open a GitHub issue with details about your setup and error message

---

## 🙏 Acknowledgments

- **Wealthsimple** for the CSV export API and USD account zero-FX model
- **Claude/Anthropic** for the underlying AI reasoning
- **yfinance** for free real-time market data
- Community feedback and real-world portfolio testing

---

**Last updated:** June 17, 2026 — v1.34.0 recommendation outcome tracking,
stable recommendation IDs, fixed 1/5/20-day alpha scoring, Outcomes tab,
fixed-window report Track Record, v1.33.0 Report Review, contextual decision
feedback, no-spend app self-test, copyable review summaries, v1.32.0 Ready To
Run paid-run verdicts, support-bundle preview, report Actionability Check,
package smoke checks, v1.31.0 setup readiness, recommended CSV candidate
confirmation, redacted support-bundle zip export, v1.30.0 Data Files workspace,
pre-run checklists, saved CSV defaults, no-spend demo smoke buttons, richer
history, v1.29.0 CSV Health diagnostics, swapped-file protection, sample-data
paid-run blocking, v1.28.0 release-health diagnostics, updater simulation,
v1.27.2 desktop consolidation, CI coverage stabilization, release-gate
dependency auditing, Node 24 workflow readiness, macro-regime gates,
concentration alerts, and v1 release-line cleanup.
**Version:** 1.34.0
**Status:** Production-ready v1 line — deterministic quality gates,
trade-readiness classifier, Data Confidence, source-backed Buy Signals,
doctor/preflight diagnostics, setup readiness, redacted support bundle export,
in-app updater with SHA-256 verification, API key manager, four interface
options (CLI, Streamlit, Textual, native desktop), paper-trading mode,
decision-journal scorecard, macro-regime controls, and concentration alerts.
667 tests pass locally.

See [CHANGELOG.md](CHANGELOG.md) for the per-release history.
