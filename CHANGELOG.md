# Changelog

All notable changes to this project are documented here.

---

## [1.40.0] — 2026-07-01

### Tests & tooling
- **CI coverage floor raised 55% → 70%.** Actual coverage sat ~76% while the
  gate was 55%, so real regressions could land silently.
- **Strengthened the weakest mockable modules** with error/pure-path tests:
  `news_fetcher` 39→90%, `market_data` 49→73%, `enriched_data` 30→80%. Total
  coverage now ~78%.

### Spend cap / cost observability
- **Month-to-date Claude spend is now surfaced on every CLI run** (spent vs.
  cap, % used, remaining — or a nudge to set a cap when none is configured), so
  the guardrail isn't opt-in-by-silence.
- **Interactive CLI setup seeds a $25/month cap** for new users
  (`set_setting_if_absent` never overwrites an existing value, so current users
  and scheduled runs are unaffected).

---

## [1.39.0] — 2026-06-30

Desktop UI production-readiness, merged on top of main's v1.38. Everything this
branch added (the desktop work below plus the security/resilience hardening that
follows) ships as 1.39.0. All desktop changes land on the canonical
`src/desktop/app.py`; pure helpers have headless tests and the GUI is exercised
by a real xvfb test suite.

### Desktop app
- **Mouse-wheel / trackpad scrolling** now works in the Home dashboard and
  Preferences panes. Previously the only way to scroll was dragging the
  scrollbar by hand. The binding activates on pointer-enter and tears down on
  leave (with a `NotifyInferior` guard for child-widget crossings) so several
  scrollable panes and Treeviews never fight over the wheel; wheel input is
  normalized across Linux (`Button-4`/`5`), Windows (±120 deltas), and macOS
  (small deltas).
- **Zebra-striped data tables.** Every table alternates row backgrounds for
  readability. The stripe tags set *background only*, so they stack cleanly
  with the existing semantic *foreground* tags (BUY/SELL/severity).
- **The window remembers its size** between launches. The saved size is
  validated and clamped onto the current screen (and to the minimum), so a
  size saved on a now-disconnected monitor can't reopen off-screen. Only the
  size is restored — never the position — to avoid the multi-monitor
  off-screen trap. Stored in `config/window_state.json` (git-ignored).
- **Busy state on Refresh buttons.** Now that the Performance/Learning/Outcomes/
  Diagnostics tabs load asynchronously, their Refresh button disables while work
  is in flight and re-enables when the latest request settles, so rapid clicks
  don't pile up redundant loads. A real GUI test guarantees the button never
  gets stuck disabled.
- **Monthly spend-cap guardrail.** New installs now seed a $25/month Claude
  spend cap (existing users keep whatever they saved — no surprise blocks). The
  Run tab surfaces month-to-date spend vs. the cap, and a run that would exceed
  it now prompts before spending ~90s and money; choosing to override is scoped
  to that single run (the `ALLOW_OVERAGE` flag is cleared when it finishes).
- **More visible table selection** — selected rows use the stronger border
  tone for clearer contrast against the striped background.
- **Tabs no longer freeze the window while loading.** The Performance,
  Learning, Outcomes, and Diagnostics tabs do network/disk I/O (SPY fetch, log
  scans, support-bundle reads) that previously ran on the Tk thread and locked
  the UI for seconds. That work now runs on a daemon worker and renders back on
  the main thread through the existing progress queue, so the window stays
  responsive. A per-tab "latest wins" guard drops stale results — on both the
  success and the error path — when a tab is refreshed faster than its work
  finishes, so an obsolete request can neither overwrite fresh data nor flash a
  stale "Failed…" status over it. A render that hits malformed data is surfaced
  on the tab's status line instead of being silently swallowed, and the
  progress-queue drain loop is hardened so one failing handler can't stop it
  (it also pumps report-run completion). The schedule install/uninstall (which
  shell out to launchctl/schtasks), the test-notification send, the holdings-CSV
  preview, and the API-key inventory scan run off the UI thread for the same
  reason.
- **Real headless GUI tests.** A new xvfb-backed test suite actually
  instantiates `DesktopApp` and exercises construction, the background
  worker → queue → main-thread render round-trip, an async refresh, and clean
  shutdown — so desktop changes are verified by running the app, not just by
  inspecting source. Skips cleanly where no display is available.

---

### Security, data-integrity & resilience hardening (also new in 1.39.0)

Brought across from the parallel hardening/coverage line.

### Security
- **Auto-updater refuses to install unverified binaries.** When a release
  asset can't be checksum-verified against `SHA256SUMS.txt`, the updater
  reveals the download for manual verification instead of installing it.
- **CSV formula injection neutralized** in exported recommendations
  (`=`/`+`/`-`/`@`/tab/CR-leading cells escaped).
- **Cache moved from pickle to JSON**, removing the deserialization
  code-execution risk; legacy `.pkl` files are cleaned up.
- **Zip-slip-safe** Windows update extraction.
- **Workspace export scrubs pasted secrets** from text files and drops
  variant-named key files (`.env.local`, `API_KEYS.backup.txt`, …).

### Data integrity & resilience
- **Bitcoin 7-day risk signal revived** — switched CoinGecko to
  `/coins/markets` (the `/simple/price` endpoint never supported a 7d param).
- **No cache poisoning on transient failures** — error/empty results from
  market data, historical prices, FRED macro/FX, and Polygon are no longer
  cached as fresh for the full TTL.
- **yfinance retries actually fire** (`requests.RequestException` added to the
  retry filter); **Twelve Data throttle is now thread-safe**.
- **Annualized metrics no longer explode** on short/dense histories (bounded
  annualisation factor).
- **Holdings CSV size bound** (10 MB) guards against OOM on malformed input.

### Tests & tooling
- **API-client error-path coverage** raised across the six paid-data clients
  (alpha_vantage/coingecko/finnhub/fred/polygon/twelve_data) from 15–39% to
  81–94%.
- **Single source of truth for per-run cost estimates** via
  `claude_analyst.typical_run_cost()`, replacing duplicated `$0.22`/`$0.45`
  magic numbers in `main.py`.
- **Demo smoke test** in CI now actually fails the build if the no-network
  demo path breaks (was a `grep ... || true` no-op).

### Desktop app (applied to `src/desktop/app.py`)
- **Window/taskbar icon** set on the live Tk window when run from source.
- **"Reveal in file manager" surfaces failures** instead of silently no-oping.
- **Schedule picker no longer crashes** on non-numeric/out-of-range Spinbox
  input (slots are validated and skipped).
- **Preferences refuse to claim "saved"** while silently dropping invalid
  numeric fields — the offending fields are named.
- **Onboarding persists all three budgets** (`monthly_budget_usd`,
  `budget_usd`, `budget_cad`) — the spend cap was previously dropped.
- **Report-history selection is bounds-checked**; **clean shutdown** cancels
  repeating `after()` loops to avoid `TclError` on quit.
- **Advanced Editor backs up config JSON** to `.bak` before overwriting.
- **Fixed a config-path regression** from the `src/desktop/` move: Preferences
  and the onboarding budget stage wrote to `src/config/settings.json`
  (`parents[1]`) instead of the real repo-root `config/settings.json`, so
  saved settings were never read back. All three sites now use the module
  `ROOT`.

---

## [1.38.0] — 2026-06-24

### Added
- Added ordered setup recovery steps and quick actions to the shared setup
  readiness payload. Desktop, Streamlit, and Textual now show the next concrete
  fix before a paid run: add API key, confirm Holdings CSV, fix swapped
  Activities CSV, run demo smoke, or run the report.
- Added an execution checklist to Report Review. Each actionable
  recommendation can now track quote confirmation, catalyst check, sizing
  check, fee/FX check, and manual review acceptance in the decision journal.
- Added source-provenance filters for status, source, and ticker in shared UI
  support and Streamlit Diagnostics. Desktop Diagnostics now exposes equivalent
  filters and defaults to problem rows.

### Changed
- Textual Data Files now shows setup recovery steps and defaults Source
  Provenance to problem rows to reduce noise.
- Report Review now includes an execution-checklist metric so pending manual
  checks are visible before acting on a recommendation.

---

## [1.37.0] — 2026-06-24

### Added
- Added deterministic recommendation explainability in reports and Buy Signals:
  every recommendation can now show source-backed bullish evidence, bearish
  evidence, missing data, readiness reason, and "what changes my mind" text.
- Added ticker-level Source Provenance rows in generated reports, shared UI
  support, Desktop Diagnostics, Streamlit Diagnostics, and Textual Data Files.
  Rows show ticker, source family, provider, timestamp/field, status, evidence,
  and required user action.
- Added outcome-learning lessons. Outcomes now derive compact positive/negative
  lessons by readiness, source coverage, catalyst verification, action, and
  market regime when enough matured samples exist.
- Added paid-run confirmation metadata to readiness payloads and UI run screens,
  plus `--yes` / `--no-confirm` for scheduled non-interactive terminal runs.
- Added release-check metadata to redacted support bundles so support zips show
  packaging/checksum readiness without exposing secrets or raw user data.

### Changed
- Non-interactive scheduled paid runs now stop on warning-confirmation
  requirements unless `--yes` is supplied after review.
- Support bundle previews now include `support/release_check.json` by default;
  use `support-bundle --skip-release-check` to omit it.

---

## [1.36.0] — 2026-06-24

### Added
- Added per-ticker Source Confidence for Buy Signals. Each candidate now shows
  quote, catalyst/news, analyst, fundamentals, and options coverage, with
  blockers/review reasons derived from deterministic source fields.
- Added Buy Signals source filters for missing catalyst, missing analyst data,
  unstamped quotes, and degraded sources across Desktop, Streamlit, and Textual.
- Added a top-level **Can I Act On This?** report section that summarizes each
  recommendation's deterministic verdict, reason, and next check before the
  detailed audit sections.
- Added release workflow enforcement for `python src/main.py release-check
  --dist release --strict` before draft GitHub Releases are created.

### Changed
- Trade readiness now incorporates Source Confidence and is persisted onto
  recommendations after deterministic quality gates run.
- Report quality gates now flag high-conviction BUY/ADD recommendations that
  lack analyst/target source coverage, near-earnings BUY/ADD recommendations
  without options-implied move data, stale catalyst/news references, and
  source-dependent thesis language without matching source data.
- Recommendation outcomes now bucket historical results by Source Coverage
  status so future calibration can compare source-backed versus partial-source
  calls.
- Dashboard view models now include Source Coverage status as a metric card.

---

## [1.35.0] — 2026-06-24

### Added
- Added `python src/main.py release-check` for local and CI release readiness
  checks. It verifies draft-release settings, checksum publishing, Linux
  AppImage/tarball workflow coverage, and optional flattened release assets.
- Added deterministic Source Coverage summaries in generated reports, saved
  recommendation logs, shared UI support, and diagnostics. New reports now show
  quote, Claude recommendation, catalyst/news, analyst, fundamentals, options,
  macro, and insider-data coverage with user actions for missing/degraded
  sources.
- Expanded recommendation outcome learning with trade-readiness, catalyst
  verification, manual-review, and market-regime buckets, giving future prompt
  calibration more context than action/ticker alone.

### Changed
- Linux builds now always produce
  `tech_stock-<version>-linux-x86_64.tar.gz`. AppImage remains available when
  `appimagetool` works, but tarball publishing is no longer a fallback-only
  path.
- The release workflow now treats the Linux tarball as a required artifact while
  keeping AppImage upload best-effort.

---

## [1.34.0] — 2026-06-17

### Added
- Added deterministic recommendation outcome tracking in
  `src/recommendation_outcomes.py`. It assigns stable user-readable
  recommendation IDs, scores fixed 1/5/20-day windows, compares each outcome
  with SPY/QQQ/SMH benchmarks, and records close-to-close stop-loss /
  take-profit triggers.
- Added shared Outcomes views to Desktop, Streamlit, and Textual. The views
  show hit rate, average action return, alpha versus benchmark, BUY/ADD success
  rate, TRIM/SELL saved drawdown, best/worst recommendations, source buckets,
  and estimated Claude cost per useful outcome.
- Added fixed-window outcome summaries to the Track Record section in generated
  reports when matured recommendation windows exist.

### Changed
- Future paid runs now feed the compact outcome summary into Claude through the
  existing backtest calibration context, so recommendations can reflect actual
  historical follow-through.
- The Streamlit, Textual, and embedded Desktop UIs now separate portfolio
  performance, backtesting, user decision scoring, and recommendation outcomes
  into clearer surfaces.

---

## [1.33.0] — 2026-06-16

### Added
- Added a shared `src/report_review.py` view model that reviews a generated
  recommendation JSON log, quality warnings, Data Confidence, source
  degradation, drift versus the previous report, and matching decision-journal
  rows without live API calls or Claude spend.
- Added Report Review surfaces to Desktop, Streamlit, and Textual. Users can
  inspect review gates, top reasons to verify, recommendation readiness, drift,
  source degradation, and pending feedback from the same UI payload.
- Added contextual decision feedback from the report view. Desktop and
  Streamlit can now mark a recommendation as accepted, ignored, modified,
  delayed, watched, or executed directly from the report review flow.
- Added a no-spend app self-test payload surfaced in Desktop Diagnostics,
  Streamlit Diagnostics, and Textual Data Files. It checks version metadata,
  setup readiness, bundled demo smoke, report-review loading, and support-bundle
  availability.

### Changed
- Report Viewer / Today's Report now pairs the rendered markdown with a compact
  review summary so users do not need to manually cross-check the JSON log,
  History, Diagnostics, and Decision Journal after every run.
- Diagnostics now includes a copyable app self-test summary suitable for support
  requests without exposing API keys or raw Wealthsimple CSV contents.

---

## [1.32.0] — 2026-06-14

### Added
- Added a shared paid-run readiness view used by Desktop, Streamlit, and
  Textual. It converts the pre-run checklist into `READY`, `REVIEW_FIRST`, or
  `BLOCKED`, shows the primary next action, and makes warning-confirmation
  requirements explicit before Claude spend.
- Added support-bundle previews in the UI and `python src/main.py
  support-bundle --preview`, listing every file that will be included and every
  sensitive artifact that is excluded before writing a zip.
- Added a top-level **Actionability Check** section near the top of generated
  reports with data-confidence verdict, quote freshness, source coverage,
  catalyst coverage, warning count, buy-signal readiness, and the top reason to
  review or block.
- Added `tools/package_smoke.py` and CI/release workflow hooks to verify source
  checkout health plus macOS, Windows, and Linux package structure/version
  metadata before artifacts are uploaded.

### Changed
- Desktop Run Report now shows a clearer **Ready To Run** panel above the raw
  pre-run checklist.
- Desktop Diagnostics, Streamlit Diagnostics/Data Files, and Textual Data Files
  now show support-bundle contents before export.
- Build & Release now fails platform builds before upload if package smoke
  checks detect missing executables, version metadata, or bundled UI/support
  modules.

---

## [1.31.0] — 2026-06-14

### Added
- Added shared setup-readiness diagnostics used by CLI, Desktop, Streamlit,
  and Textual. The view reports onboarding stage, workspace writability, API
  key status, paid-run blockers, update status, demo availability, and a single
  next action.
- Added CSV candidate confirmation rows for holdings and activities exports,
  including recommended file, schema confidence, sample/demo detection,
  freshness, row count, and correction text.
- Added `python src/main.py setup --json` for first-run/setup preflight and
  `python src/main.py support-bundle` for creating a redacted support zip.
- Added redacted support-bundle zip export from Desktop, Streamlit, and
  Textual. The zip contains doctor/setup/data-file summaries and diagnostics
  logs, but excludes raw API keys and raw Wealthsimple CSV contents.

### Changed
- Desktop Data Files now shows setup readiness and CSV candidates to confirm.
- Streamlit Data Files now shows setup readiness and recommended CSV choices.
- Textual Data Files now shows setup readiness, CSV candidates, and support
  export status.

---

## [1.30.0] — 2026-06-13

### Added
- Added a shared Data Files / Workspace view model showing the current
  holdings CSV, activities CSV, API key file, reports folder, recommendation
  logs folder, uploads folder, and workspace status.
- Added persistent CSV path defaults in `config/data_files.json`, with save
  controls in Desktop, Streamlit, and Textual.
- Added a shared pre-run checklist for paid report runs covering required
  Anthropic key, holdings schema, activities schema, sample/demo files,
  monthly budget, optional API coverage, and update status.
- Added one-click demo smoke actions to Desktop, Streamlit, and Textual so a
  user can validate bundled sample data and UI view models without Anthropic
  spend.
- Added enriched report-history metadata with input CSV paths, BUY/ADD counts,
  TRIM/SELL counts, warning counts, and data-confidence labels.

### Changed
- Desktop, Streamlit, and Textual now use the same selected CSV defaults and
  the same pre-run blocking logic before launching the paid pipeline.
- New recommendation JSON logs include an `input_files` block recording the
  holdings CSV, activities CSV, and portfolio source used for the run.

---

## [1.29.0] — 2026-06-13

### Added
- Added shared Wealthsimple CSV inspection for holdings and activities exports,
  including schema kind, confidence, missing columns, sample/demo detection,
  and actionable correction text.
- Added CSV Health output to doctor/preflight diagnostics and surfaced the same
  health payload in Desktop and Streamlit Diagnostics.
- Added run-level CSV pair validation that automatically corrects swapped
  holdings/activities paths when both files are provided in the wrong fields.

### Fixed
- Blocked accidental paid runs on `holdings-report-sample.csv` unless demo mode
  is explicitly active.
- Reused the same swapped-file detection in both holdings and activities
  parsers for consistent error messages.

---

## [1.28.0] — 2026-06-11

### Added
- Added `python src/main.py doctor --simulate-current-version VERSION` so
  release checks can confirm that an older installed app sees the newest
  published GitHub Release without editing `src/version.py` or applying an
  update.

### Docs
- Documented the release-health command for validating updater detection after
  publishing a release.

---

## [1.27.2] — 2026-06-10

### CI
- Opt GitHub Actions workflows into the Node 24 JavaScript runtime ahead
  of GitHub's Node 20 runner deprecation.
- Add `pip-audit` to the tag-triggered release test gate before packaging
  artifacts.

### Docs
- Update release-process documentation to show the release audit gate and
  move future security tightening toward SBOM generation.

---

## [1.27.1] — 2026-06-10

### Fixed
- Restored `src/desktop_app.py` to a thin compatibility launcher that aliases
  the canonical `src.desktop.app` implementation.
- Consolidated the duplicated Tkinter desktop implementation into
  `src/desktop/app.py`, preserving `python src/desktop_app.py` and legacy
  imports while removing the duplicate coverage burden.

### CI
- Added coverage configuration that omits full GUI window modules from the
  headless coverage gate while keeping import/helper tests active.
- Raised the CI coverage floor from 45% to 55%; local validation reaches 66%.

### Version bumped: 1.27.0 → 1.27.1

---

## [1.27.0] — 2026-06-07

### Bug Fixes
- Fixed macro-regime conviction gate using wrong key `market_context` — now reads `recommendation["macro_regime"]` directly
- Fixed conviction gate comparing against non-existent `conviction_score` field — now uses the correct `conviction` field

### Features
- Wired `macro_regime.classify_regime()` into main pipeline: fetches FRED series from `enriched["macro"]["series"]` and stores result in `recommendation["macro_regime"]`
- Wired `concentration_alerts()` into `evaluate()` quality gates: appends `CONCENTRATION` warnings for highly-correlated position pairs exceeding weight threshold
- Added "Concentration Alerts" subsection to markdown report rendered by `report_generator.py`
- Fixed `macro_regime.classify_regime()` to read VIX from `fred_data["VIXCLS"]["value"]` and yield curve from `fred_data["T10Y2Y"]["value"]`

### Cleanup
- Consolidated `safe_float` duplicates: merged NaN/inf handling into `src._utils.safe_float()`; removed private `_safe_float` from `market_data.py` and `sector_rotation.py`
- Added `CAD_PER_USD_DEFAULT = 1.37` constant to `src/constants.py`
- Moved inline `import time as _time` and `import logging as _logging` in `claude_analyst.py` to top-level imports
- Added `logger.debug(..., exc_info=True)` to previously-silent `except Exception: pass` blocks in `desktop_app.py`
- Added `.coverage`, `.coverage.*`, `htmlcov/`, `.pytest_cache/` to `.gitignore`
- Added `pytest.importorskip("tkinter")` to `tests/test_desktop_app_macos.py`
- Expanded CI ruff format check scope to include `ui/` and `tools/` directories
- Added tests for macro-regime conviction gate (correct key fires, wrong key does not) and concentration alerts rendering

---

## [1.26.0] — 2026-06-07

### Added
- Dry-run mode: validate CSV/portfolio without calling Claude (Run tab checkbox + `run_report_from_ui(dry_run=True)`)
- Risk controls table in markdown report: entry zones, stop-loss, take-profit per recommendation
- Trailing stops section in report: active trailing stops with breach alerts for positions with >10% gain
- Paper trading UI in Performance tab: cumulative value chart, P&L, trade count from `paper_trading.py`
- Improved Run tab error panel: stage-by-stage failure info and retry button
- Integration test (`tests/test_integration_sample.py`) validating pipeline with bundled sample data

---

## [1.25.0] — 2026-06-05

### Added
- Macro regime classifier (`src/macro_regime.py`): auto-detects Bull / Correction / Bear / Transition from VIX, yield curve, and SPY SMA cross; conviction cap enforced by quality gate
- Correlation matrix + concentration alerts in `portfolio_analytics.py`: warns when two >0.85-correlated positions combine to >15% of portfolio
- Integration test with bundled sample data validates end-to-end report pipeline
- Unit tests for `alpha_vantage_client`, `coingecko_client`, `finnhub_client`, `polygon_client`, `twelve_data_client`
- `requests` added as explicit dependency; upper bounds on `anthropic` and `yfinance`
- CI now tracks test coverage with `--cov-fail-under=55` floor
- Expanded ruff lint rules (import sorting, pyupgrade, pycodestyle warnings)

### Fixed
- `tests/test_desktop_search.py` now skips gracefully on headless systems (no `tkinter`)

---

## [1.24.0] — 2026-06-04

### Changed — Quality, resilience & analytics improvements

- **Sortino, Calmar, VaR/CVaR metrics** — Four additional risk metrics added to both `compute_risk_dashboard()` and the Performance tab summary: Sortino ratio (downside-only volatility), Calmar ratio (return vs max drawdown), VaR 95% (worst 5th-percentile session loss), and CVaR 95% (expected loss beyond VaR). The desktop **Performance tab** now displays all four as metric cards with explanatory tooltips. All derived from existing historical data, no new API calls.
- **Live USD/CAD FX rate** — New keyless `get_usd_cad_rate()` in `portfolio_analytics.py` fetches the live rate from exchangerate-api.com (FRED public CSV as fallback), cached in-memory for 4 hours, with a 1.37 fallback on any network error. Wired into the report pipeline (`main.py`) as the fallback when no FRED API key is configured — so users without a FRED key still get an accurate live rate instead of the static assumption.
- **Claude API retry on rate limits** — `_create_message()` now retries up to 3 times on HTTP 429/529/503 errors (RateLimitError, APIStatusError) with exponential backoff: 5s → 15s → 45s. Logs each retry attempt.
- **Pass 2 fallback** — If the second-pass quality review fails (timeout, refusal, malformed JSON), the system now falls back gracefully to the Pass 1 result instead of crashing the entire run. A warning is appended to the recommendation and `pass2_fallback=True` is set in the output.
- **Sector rotation conflict gate** — New quality gate in `report_quality.py` detects when sector warnings call for reducing tech exposure but a BUY/ADD is recommended on a tech/semiconductor ticker. Appends a `medium`-severity warning.
- **Journal tab filters + CSV export** — Streamlit Journal tab now has ticker multiselect, 30-day date range filter, and outcome filter (Win/Loss/Open). A "Export to CSV" download button is available whenever entries are shown.
- **Schedule tab time picker** — Replaced hour/minute number inputs in the Schedule tab with native `st.time_input` widgets for a cleaner, less error-prone UI.
- **Backtest equity curve** — Backtest tab now renders a cumulative portfolio index chart from recent realized examples, starting at 100.
- **Degradation health wired** — `degradation_health()` (previously defined but unused) is now called at the top of the Streamlit Diagnostics tab and surfaces any data quality issues as `st.warning()` items.
- **Unit tests for claude_analyst** — New `tests/test_claude_analyst.py` covers `normalize_recommendation`, `_normalize_time_horizon`, `_parse_validate_recommendation`, and the Pass 2 fallback path. 14 tests, no live API calls.

### Version bumped: 1.23.0 → 1.24.0

---

## [1.23.0] — 2026-06-03

### Changed — B2C user-friendliness overhaul

Major UX improvements to make the desktop app consumer-ready.

- **Tab reorganization (12 to 7)** — Reduced from 12 flat tabs to 7 primary tabs. Reports tab combines Run/Latest/History as sub-tabs. Settings tab combines Preferences/API Keys/Schedule/Advanced Editor/Updates as sub-tabs. Dashboard renamed to "Home". Less overwhelming for new users.
- **Native onboarding wizard** — New 6-stage setup wizard built directly in the desktop app using the existing `onboarding.py` state machine. Walks through Welcome, API Key, Budget, CSV, First Run, and Done stages with progress dots and inline inputs. Replaces the old redirect-to-Streamlit dialog.
- **Tooltip system** — New `_Tooltip` class provides hover tooltips throughout the app. Applied to ~35 widgets: dashboard metric cards, run tab fields, toolbar buttons, settings form fields, and the header status pill. Explains financial terms like beta, volatility, and conviction in plain English.
- **Progress indicators** — Indeterminate progress bar with elapsed timer during report generation. Shows "Elapsed: 42s" and animates while Claude analyzes. Progress bar hides when complete.
- **Status bar** — Persistent bottom bar showing connection status, last report timestamp, session cost, and app version. Updates on report completion and operation changes. Color-coded status dot (green/amber/red).
- **Friendly settings panel** — New Preferences sub-tab with form-based settings for common options: investment budget, risk tolerance, AI model choice, two-pass review toggle, max position size, min expected return, and feature flags (decision journal, sentiment, enrichment). Replaces raw JSON editing for everyday settings.
- **Consumer-friendly labels** — "Run Report" → "Generate Report", "Preview Holdings" → "Preview My Holdings", "Check APIs" → "Test Connections", "Refresh Buy Signals" → "Check for Opportunities". Section headers: "Action Queue" → "Recommended Actions", "Quality Gates" → "Risk Alerts", "Stops & Breaches" → "Price Alerts".
- **Welcome-back greeting** — Returning users see "Welcome back!" in the status bar for 3 seconds before normal status.
- **Friendlier empty states** — "No recommendation JSON logs found yet" → "Welcome! Generate your first report to see your portfolio analysis here."
- **Better status messages** — "Running report..." → "Generating your portfolio report... usually takes about 90 seconds." "Report completed." → "Report ready! Switch to Reports > Latest to read your recommendations."

### Version bumped: 1.22.0 → 1.23.0

---

## [1.22.0] — 2026-06-03

### Changed — macOS desktop UI overhaul

Visual quality and consistency pass for the embedded desktop application. Every surface now speaks the same design language.

- **Consistent font ladder** — Replaced all hardcoded `("Helvetica", N)` font tuples throughout the desktop app with the platform-aware font ladder (`SF Pro` on macOS, `Segoe UI` on Windows, system default on Linux). Every label, card, metric, and text widget now uses `self.fonts[...]` for a uniform typographic hierarchy.
- **Unified dark theme** — The report viewer and history panes were light-themed (`#f8fafc` background, dark text) while everything else was dark. Now the entire app uses the shared PALETTE dark surface for all text widgets, report rendering, and markdown tags. Search highlights adjusted for dark backgrounds.
- **PALETTE token consistency** — Eliminated ~30 hardcoded hex colour literals (`#171827`, `#0f172a`, `#0b1020`, `#e5e7eb`, `#2b2d42`, `#303044`, `#64748b`, etc.) across dashboard cards, signal banners, metric boxes, panels, editors, console, diagnostics, schedule, and update views. Every colour now traces back to `PALETTE` tokens or `self.*` aliases.
- **Refined panel headers** — Section panels now use uppercase muted labels with separator lines instead of bold inline titles, matching professional dashboard conventions.
- **Polished metric cards** — Dashboard and performance metric cards use the `subtle` token for labels and `text_strong` for values, with consistent border and padding.
- **Better tab bar** — Tab labels shortened and padded (`Dashboard`, `Signals`, `New Report`, `Viewer`, `History`, `Performance`, `Learning`, `Diagnostics`, `Schedule`, `Config`, `APIs`, `Updates`) for cleaner scanning.
- **Improved header** — Title uses `text_strong` instead of accent green, version pill in accent, right-aligned status. Thin separator line below header.
- **Better widget styling** — Treeview headings use muted uppercase text with flat backgrounds. Comboboxes, entries, checkbuttons, spinboxes, scrollbars, and paned windows all receive PALETTE-derived styling via `_configure_style`. Selected treeview rows use `border` background.
- **Larger default window** — 1280×880 default (was 1200×840), 1024×720 minimum (was 980×680).
- **clam theme on all platforms** — Switched from macOS `aqua` to `clam` everywhere for full control over the dark theme. The aqua theme conflicted with custom dark styling.

### Version bumped: 1.21.2 → 1.22.0

---

## [1.21.2] — 2026-06-02

### Fixed

- **Opus extended thinking** — Updated to the new `thinking.type="adaptive"` + `output_config.effort` API; the previous `thinking.type="enabled"` with `budget_tokens` is no longer accepted by Opus 4.x and raised a 400 error.

### Version bumped: 1.21.1 → 1.21.2

---

## [1.21.1] — 2026-06-01

### Fixed

- **CSV input diagnostics** — Detect when a Wealthsimple `activities-export` CSV is accidentally selected as the Holdings CSV and show a direct "put this in Activities instead" message instead of a generic missing-columns schema error.
- **Symmetric swapped-file guard** — Detect when a `holdings-report` CSV is selected as the Activities CSV and point the user back to the correct field.

### Tests

- **590 passing expected** after this patch: added regression coverage for swapped holdings/activities CSV detection.

### Version bumped: 1.21.0 → 1.21.1

---

## [1.21.0] — 2026-05-29

### Added — Stabilization, doctor, and V2 readiness gate

Focused supportability release for the v1 line. This is intentionally **not** `v2.0.1`: V2 remains a readiness milestone until public releases, updater flow, demo mode, installer smoke tests, and migration rules are proven end-to-end.

- **CLI doctor command** — `python src/main.py doctor --json` returns a structured preflight payload with installed version, latest GitHub release, update-cache metadata, workspace paths, API-key discovery, required/optional API status, CSV freshness, monthly budget status, release asset/checksum availability, and optional demo smoke results.
- **Preflight surfaced in Diagnostics** — Desktop and Streamlit Diagnostics now show the same doctor summary as a Preflight card/table before paid runs.
- **Force-refresh update checks** — manual UI checks bypass the update cache and explicitly show whether the result came from cached data or live GitHub Releases, plus asset/checksum coverage.
- **No-spend demo smoke test** — validates bundled sample CSVs, sample recommendation JSON, markdown rendering, Dashboard view-model loading, and Buy Signals view-model loading without Anthropic calls.
- **Data Confidence block** — reports, Dashboard, and Buy Signals now surface quote freshness, source coverage, catalyst coverage, warning counts, and readiness state as a top-level trust signal.

### Fixed

- **Release CI flake** — report history sorting now uses filename as a deterministic tie-breaker when filesystem mtimes are identical, fixing an Ubuntu-only `test_list_reports_returns_newest_first` failure that blocked the `v1.20.0` draft release.

### Tests

- **588 passing expected** after this release (579 → 588): new coverage for data confidence, doctor/preflight payloads, update-cache metadata, demo smoke, Diagnostics preflight, and report rendering.

### Version bumped: 1.20.0 → 1.21.0

---

## [1.20.0] — 2026-05-27

### Added — Release engineering + docs

A release-engineering pass that turns shipping into a one-tag-push operation, plus a full docs refactor.

#### Release engineering

- **`.github/workflows/build_release.yml` rewritten end-to-end**. On a `v*.*.*` tag push: a three-OS test gate (`macos-14`, `windows-latest`, `ubuntu-22.04`) runs `pytest -q` + `ruff check` + `ruff format --check` in parallel. If any platform fails the gate, the build jobs do NOT run — silent abort. Otherwise three parallel build jobs produce the macOS `.dmg`, the Windows folder + Inno Setup installer (Chocolatey-installed `iscc`, version injected from `src/version.py`), and the Linux AppImage (or tarball fallback). A final `release` job downloads every artefact, generates `SHA256SUMS.txt`, parses the matching CHANGELOG section, and publishes a draft GitHub Release with the parsed body + every artefact attached.
- **New `src/changelog_utils.py`** — CLI-callable parser (`python -m src.changelog_utils 1.20.0`, `--latest`, `--list`) that the workflow uses to populate the GitHub Release body. Also exposed programmatically: `parse_section()`, `latest_section()`, `all_versions()`.

#### Docs refactor

- **`README.md` trimmed from 1583 → 1128 lines** (~29% smaller). Older "What's New" history (v1.18.0 → v1.3.0) replaced with a one-line pointer to `CHANGELOG.md`. The giant inline Architecture section replaced with a one-paragraph summary pointing at `docs/ARCHITECTURE.md`. New "📖 Documentation" index linking to every new doc file.
- **New `docs/ARCHITECTURE.md`** — module map (with one-line purpose per file), data flow per session (10 steps), the 7-layer quality-gate reference, the learning-loop diagram, storage layout, and five explicit design tenets (never silently swallow, additive schema, tests with every feature, production = default-safe, tools not toys).
- **New `docs/COOKBOOK.md`** — 12 common workflows: demo mode without setup, single CLI report, scheduled runs, monthly budget caps, replaying old sessions, editing settings, wiping data, exporting the workspace, backtesting past recommendations, hooking custom notifications, running tests, building bundles.
- **New `docs/RELEASE_PROCESS.md`** — exact tag-to-release flow, what each CI job does, how to hot-fix a botched release, future tightening (notarisation, signtool, pip-audit gate).
- **`CONTRIBUTING.md` rewritten** — design tenets, daily workflow, commit-message style with real examples, three "adding a new X" pattern guides (UI tab, API source, CLI flag), files-you-shouldn't-commit reference, areas where contributions are most welcome.

### Tests

- **579 passing** (was 533). 46 new tests:
  - `tests/test_changelog_utils.py` (13): section parsing, body trimming, hyphen/en-dash separator support, pre-release versions, latest extraction, CLI exit codes, real-repo round-trip.
  - `tests/test_release_workflow.py` (15): YAML schema validity, three-OS matrix coverage, test-gate-before-builds dependency, release-only-on-tag gate, contents:write permission, CHANGELOG parser invocation, SHA256 generation, draft Release publication, macOS hdiutil step, Windows `iscc /DAppVersion`, Linux `build_linux.sh` invocation.
  - `tests/test_docs_links.py` (18): every docs file exists, every internal markdown link in `README.md` / `CONTRIBUTING.md` / `CHANGELOG.md` / `docs/*.md` resolves, README advertises every doc, RELEASE_PROCESS references the parser, ARCHITECTURE lists every v1.17-v1.19 module, CONTRIBUTING carries the design tenets, COOKBOOK covers the main workflows.

### Version bumped: 1.19.1 → 1.20.0

---

## [1.19.1] — 2026-05-27

### Fixed — Close the v1.19 loose ends

v1.19 promised several CLI flags and a workspace-export action via the installer scripts, Privacy card, and scheduler, but the actual code for them wasn't all wired up yet. This patch closes those gaps so the productisation surface matches what users see in the UI / shortcuts.

- **Five new CLI flags in `main.py`** that the Windows installer + launchd / Task Scheduler / cron scripts already invoke:
  - `--demo` — sets `TECH_STOCK_DEMO_MODE=1` + bypasses onboarding and launches the Streamlit UI on bundled sample data.
  - `--import-csv PATH` — stages a CSV into `temporary_upload/` (this is the open command bound to Wealthsimple `holdings-report-*.csv` files by the installer's HKCU registry entries).
  - `--session-type {morning,afternoon}` — alias for the positional `session` arg; scheduler invocations prefer this form.
  - `--non-interactive` — skips all interactive prompts. With no `session`, auto-picks `morning` before 12:00 / `afternoon` after, so headless launchd / Task Scheduler / cron runs don't hang.
  - `--force` — surfaces `ALLOW_OVERAGE=1` for the v1.19 monthly-budget gate.
- **New `src/workspace_export.py`** — wired to the Privacy card's previously-stubbed "Export workspace" button. Produces a zip under `exports/` containing reports, recommendation logs, the journal, thesis log, cost log, samples, and (sanitised) config. Excludes `.env`, `API_KEYS.txt`, the temporary upload folder, and anything matching the secret-file heuristic.
- **Desktop wizard hook** — `DesktopApp` now checks `needs_onboarding()` on first launch and offers a one-time dialog that opens the Streamlit wizard (which is where the full step-by-step flow lives). The user's choice is stamped to settings.json so the dialog never fires twice.

### Tests

- **533 passing** (was 515). 18 new tests:
  - `tests/test_cli_flags.py` (10): every new flag is advertised in `--help`; `--version` still short-circuits; `--import-csv` with a missing file exits non-zero; with a valid file stages-and-exits 0.
  - `tests/test_workspace_export.py` (8): zip is produced, .env / API_KEYS.txt / temporary_upload are excluded, recommendation log + thesis log + cost log + settings.json ARE included, missing-workspace path produces a valid empty-ish zip, unwritable destination reports a clean error.

### Version bumped: 1.19.0 → 1.19.1

---

## [1.19.0] — 2026-05-27

### Added — Productisation

The app is now installable + usable by any Wealthsimple account holder, not just developers.

#### First-run wizard + demo mode

- **New `src/onboarding.py`** — state machine over six stages (`welcome` → `api_key` → `budgets` → `csv_walkthrough` → `first_run` → `done`). State stamped into `config/settings.json` under an `onboarding` block, so it survives restarts mid-wizard. Public API: `current_state()`, `advance()`, `reset_onboarding()`, `needs_onboarding()`, `stage_guidance()`, `demo_snapshot()`, `is_demo_mode_active()`. `TECH_STOCK_SKIP_ONBOARDING=1` env var bypasses for headless / existing-user runs.
- **Inline wizard in `ui/streamlit_app.py`** — short-circuits the page render when `needs_onboarding()` is True. Steps render with title / body / external link / primary + secondary action. API-key paste flow drops the key into `config/.env`; budget step persists to `settings.json`.
- **Demo mode** — `data/samples/holdings-report-sample.csv` (5 realistic Wealthsimple-style positions), `activities-export-sample.csv`, and `recommendation_log_sample.json` (cached Claude response with `_demo: true` flag). The launcher's new "🎬 Try demo" link fires Streamlit with `TECH_STOCK_DEMO_MODE=1` so a brand-new user sees a complete report without an API key, without a CSV, without spending a cent.

#### Cost transparency + monthly budget caps

- **New `src/cost_tracker.py`** — JSONL log at `data/cost_log.jsonl`, one record per run. Public API: `record_run()`, `spend_summary()`, `check_budget()`, `is_overage_allowed()`, `clear_cost_log()`. Aggregates total / last-7-day / last-30-day / month-to-date / projected-monthly. Daily series for the Spend chart.
- **`main.run()` enforces the budget** — pre-run `check_budget` reads `monthly_budget_usd` from settings; soft-warns at 80%, hard-blocks at 100% unless `ALLOW_OVERAGE=1`. Default is 0 (no cap) so existing users see no change until they opt in.
- **`main.run()` records every run** — post-run hook appends model, cost, tokens, session_type, report filename to the cost log.
- **Spend sub-section in the Diagnostics tab** — total / MTD / projected / runs metrics, a 30-day daily-spend line chart, and a budget-usage bar with colour-coded threshold tone (green < 80%, amber 80-100%, red ≥ 100%).
- **Privacy card in the Diagnostics tab** — explains what gets sent to Anthropic vs what stays local, lists each enrichment source, and a confirmation-gated "🗑 Delete all local data" button that wipes reports / logs / journal / cache / thesis-log / cost log atomically.

#### Bundled installer parity (Windows + Linux)

- **`installer_windows.iss` v1.19** — the hard-coded `AppVersion=1.0.0` is gone; the script now consumes `#define AppVersion` injected at build time. Adds: per-user CSV file association (HKCU registry entries with a `tech_stock.holdings_csv` ProgId + `--import-csv "%1"` open command), Start-Menu group with a separate "tech_stock (Demo mode)" shortcut (`--demo`), optional desktop shortcut task, optional CSV-association task, samples component, full version metadata, AppId GUID so Windows treats upgrades as upgrades rather than fresh installs.
- **`build_windows.bat`** — now parses `APP_VERSION` from `src/version.py` and passes it to `iscc /DAppVersion=…`, so the installer always carries the real version. Adds a `SIGN_PFX_PATH` / `SIGN_PFX_PASSWORD` code-signing hook that fires `signtool` against the produced `tech_stock_setup.exe` when credentials are present.
- **New `build_linux.sh`** — composes a freedesktop AppDir layout (`AppRun` script, `tech_stock.desktop` with `Categories=Finance;Office;`, 256×256 icon), runs `appimagetool` to produce `dist/tech_stock-x86_64.AppImage` when available, falls back to a tarball when not. Reads the version from `src/version.py` like the other build scripts.

### Tests

- **515 passing** (was 467). 48 new tests across:
  - `tests/test_onboarding.py` (16): state machine progression, env-skip override, stage-guidance shape, demo-snapshot file presence, sample CSV column validation, sample JSON shape.
  - `tests/test_cost_tracker.py` (13): round-trip, aggregation, corrupt-line tolerance, budget no-cap / soft-warn / hard-block, overage env-var, clear path, projection math, daily-series grouping.
  - `tests/test_installer_artefacts.py` (13): Inno Setup version-macro plumbing, CSV registry plumbing, Start-Menu + demo-mode + samples components, version-injection from the .bat, `signtool` hook, build_linux.sh executable + reads version + emits AppImage / tarball / desktop entry + macOS spec regression guard.

### Version bumped: 1.18.0 → 1.19.0

---

## [1.18.0] — 2026-05-27

### Added — Calibration & walk-forward backtest

- **`reliability_diagram()` in `src/backtester.py`** — bins evaluated recommendations by conviction (6–10) and compares the *stated* probability (`conviction × 10%`) against the *realized* hit rate. Returns `{conviction: {n, stated_pct, realized_hit_rate, error_pp, overconfident, avg_actual_pct}}` for any bucket with ≥ 3 samples.
- **`evaluate_rolling_window()` in `src/backtester.py`** — walk-forward stability check. Slides a window over the time-sorted results and emits per-window dicts with hit rate, average return, Sharpe, max-DD, stdev, and an in-window sizing multiplier. Window/step user-tunable; gracefully returns `[]` for thin datasets.
- **`summarize()` now exposes `reliability` + `walk_forward` keys** — additive; existing consumers unaffected.
- **Claude prompt enrichment (`src/claude_analyst.py`)** — track-record block adds a `Conviction calibration` section for any decile where `abs(error_pp) ≥ 10`, with a per-bucket dampening hint (`conv 8: stated 80% / realized 60% (-20pp, over-confident) → dampen by ~0.85×`), plus a one-line walk-forward stability summary.
- **Learning tab Calibration sub-section** — Streamlit gets an Altair scatter (stated vs realized hit-rate with a 45° reference) plus a rolling-window hit-rate line chart. Desktop gets a Treeview Calibration row group + one-line stability summary.

### Added — Native notifications

- **New `src/notifications.py`** — cross-platform `send(title, message, channel)`. macOS via `osascript`, Linux via `notify-send`, Windows via PowerShell BurntToast (with MessageBox fallback). Zero new pip deps. Settings-gated (`config/settings.json → notifications.channels.{report_complete, trailing_stop_breach, thesis_force_exit, high_priority_action}`). 5-second dedup window. Every send logs via observability.
- **`send_many()`** collapses long batches (> 5) into 3 individuals + a single summary line so the user isn't flooded.
- **Wired into `main.run()`** — every report completion fires a `report_complete` notification; trailing-stop breaches fire `trailing_stop_breach`; ≥ 3 priority-≤2 actions fire `high_priority_action`. Each call is wrapped so a backend failure never breaks the report run.

### Added — Schedule installer

- **New `src/scheduling.py`** — per-user scheduled-run installer. `install_schedule(times)` writes a launchd plist (macOS), Task Scheduler XML (Windows), or crontab line (Linux). `uninstall_schedule()` removes it cleanly. `current_schedule()` parses the installed artefact back into `ScheduleTime` objects so the UI shows live state. `preview_schedule()` returns the artefact body without writing.
- **No `sudo`, no root crontab** — macOS uses `~/Library/LaunchAgents/com.techstock.daily.plist`, Linux edits the user crontab, Windows uses `schtasks` per-user.
- **⏰ Schedule tab in Streamlit + Desktop** — three slot pickers (morning / midday / afternoon), live preview pane, install / uninstall / test-notification buttons, current-state table.

### Fixed

- **`main.api_key_search_paths()` was returning 12 paths with 6 duplicates** — when invoked from inside the project root, `ROOT`, `Path.cwd()`, and `SOURCE_ROOT` all resolve to the same directory. Now wraps the raw list with the existing `_dedupe_paths()` helper.
- **`normalize_recommendation` no longer leaves empty-string tickers** — empty string was bypassing both `upper()` and the `setdefault("ticker", "UNKNOWN")` fallback. Empty / None now collapse to the `UNKNOWN` sentinel.
- **`_maybe_fire_notifications` no longer propagates notification backend errors** — every `send()` call inside the post-report flow is wrapped so a buggy PowerShell host or AppleScript permission denial can't break a report run that already succeeded.

### Tests

- **467 passing** (was 388). 79 new tests across:
  - `tests/test_backtester_calibration.py` (13): reliability mapping, walk-forward windowing, edge cases.
  - `tests/test_notifications.py` (16): argv escaping, dispatch routing, dedup window, settings gating, subprocess-error handling, batch collapsing.
  - `tests/test_scheduling.py` (16): launchd plist / task scheduler XML / cron line builders, round-trip parse, install→inspect→uninstall, no-op + idempotent paths, quoting helpers.
  - `tests/test_app_gui.py` (13): `_self_command` dev vs frozen, `_find_free_port` walk, `_tail`, `_open_path_in_finder` per-platform, `_latest_report_summary` empty + populated, PALETTE wiring.
  - `tests/test_main_pipeline.py` (12): bounded `find_csv_by_date`, `_dedupe_paths`-aware `api_key_search_paths`, `ensure_workspace` idempotence, `validate_environment` exit codes, `_maybe_fire_notifications` channel routing + error swallowing.
  - `tests/test_claude_analyst_passes.py` (22): ticker normalisation, action fallback, risk-controls dict shape, price-target swap, time-horizon canonicalisation, HOLD-tier defaults, entry/exit-plan auto-fill.

### Version bumped: 1.17.0 → 1.18.0

---

## [1.17.0] — 2026-05-27

### Added — Observability

- **New `src/observability.py`** — structured-log layer. Public API: `log_event(source, level, code, message, context=None)`, `success_rate(source, hours=24)`, `recent_errors(limit=50)`, `source_summary(hours=24)`, `support_bundle(limit=500)`, `clear_diagnostics()`. JSON-lines on disk at `user_workspace()/logs/diagnostics.jsonl`. Thread-safe writer. Size-based rotation to `.jsonl.1` at 5 MB. Never raises — observability must not break the caller.
- **Redaction** — API keys (`sk-…`), hex tokens (32+ chars), `Authorization: Bearer …`, and email addresses are scrubbed from every record before write. Support bundles are safe to paste into public bug reports.
- **API clients now log instead of swallowing** — replaced 17 silent `except Exception:` blocks in `finnhub_client.py`, `polygon_client.py`, `alpha_vantage_client.py`, `twelve_data_client.py`, `fred_client.py`, `coingecko_client.py`, and `cache.py` with `log_event()` calls. Graceful degradation (callers still get `None`) is preserved.
- **🩺 Diagnostics tab in Streamlit + Desktop** — per-source health table (ok / degraded / down / idle based on success rate over the selected time window), recent error events, redacted support bundle with copy-to-clipboard, log-file path, "Open log folder" reveal-in-Finder action.
- **`HEALTH_META` + `health_badge()` + `degradation_pill()` in `ui_theme.py`** — colour-coded health pills using the same palette as everything else; safe to interpolate inline (XSS-escaped).
- **`diagnostics_view()` + `diagnostics_support_bundle()` + `degradation_health()` in `ui_support.py`** — UI-facing aggregators.

### Added — Portfolio Performance

- **New `src/performance_history.py`** — rebuilds a portfolio time-series from `data/recommendations_log/*.json` snapshots. Computes cumulative return, annualized return, annualized volatility, Sharpe (rf=0), max drawdown, rolling 30-session Sharpe, rolling drawdown from peak, sector contribution waterfall (start_usd → end_usd → delta_usd), and a 0.5%-bucketed return distribution histogram. SPY benchmark fetched from yfinance (cached 4h) with OLS-derived beta and annualised alpha.
- **💹 Performance tab in Streamlit + Desktop** — headline metric strip, portfolio-vs-SPY rebased line chart, rolling Sharpe + drawdown panels, sector waterfall, return distribution. Streamlit uses `st.line_chart` / `st.area_chart` / `st.bar_chart` with palette colours. Desktop draws a sparkline on a Tk Canvas (matplotlib is intentionally excluded from the PyInstaller bundle) plus Treeview tables. Lookback selector (All time / 30 / 90 / 365 days). Optional SPY toggle so users without yfinance can still use the tab.

### Tests

- **375 passing** (was 333). 42 new tests:
  - `tests/test_observability.py` (15): round-trip, level normalisation, redaction patterns (API keys, hex tokens, Bearer tokens, emails), context recursion, source/level filters, success-rate fractions, code bucketing, support bundle JSON validity, rotation, clear.
  - `tests/test_performance_history.py` (16): pure math helpers (`_pct_changes`, `_max_drawdown_pct`, `_linear_regression`), snapshot loader filename parsing and ordering, value/zero filtering, sector buckets, `not_ready` states, cumulative return, SPY-disabled path, lookback window filter, sector waterfall, return-distribution bucketing.
  - `tests/test_diagnostics_view.py` (11): view shape, health threshold mapping (ok ≥ 0.95, degraded 0.50–0.94, down < 0.50, idle = no traffic), `degradation_health` healthy/unhealthy/idle, redacted support bundle, `health_badge` palette wiring, `degradation_pill` empty-when-ok, XSS escaping.

### Version bumped: 1.16.0 → 1.17.0

---

## [1.16.0] — 2026-05-26

### Added — Close the learning loop

The app already collected a lot of introspective data (thesis verdicts, decision-journal scorecard, backtester); v1.16 surfaces it and feeds the high-leverage signals back into the next Claude run.

- **Per-horizon edge in `decision_journal`** — `summarize_outcomes` now emits a `by_horizon` block (`{1: {...}, 5: {...}, 20: {...}, 60: {...}}`) computed from the same scored windows the dashboard already displays. Additive; existing keys unchanged.
- **Risk-adjusted sizing in `backtester`** — `_avg_and_hit_rate` now returns `stdev_pct`, `sharpe` (rf=0, `mean/stdev × √N`), and `max_drawdown_pct` per bucket. The conviction-stratified sizing multiplier formula is now **Sharpe-dampened** — high-variance buckets no longer get the same size as low-variance buckets with the same expectation. Clamp range `[0.4, 1.4]` preserved.
- **Thesis-text drift in `drift_tracker`** — new `thesis_text_drift` event fires when action / conviction / sign all stayed the same but the rationale was substantially rewritten (token-set Jaccard < 0.55 after stop-word filtering). Catches the "moving goalposts" smell. Pure-Python — no new hard dependency.
- **Claude prompt enrichment (`src/claude_analyst.py`)** — track-record block now lists `Sharpe / max_dd` per conviction bucket; scorecard block now lists `Your edge by horizon: 1d ±X% | 5d ±Y% | 20d ±Z% | 60d ±W%` plus a tuning hint pointing to the user's strongest horizon; drift section has a dedicated `Thesis-text drift` mini-section.
- **`learning_view()` in `ui_support.py`** — single aggregator returning `{thesis_verdicts, edge_by_horizon, sharpe_by_conviction, thesis_text_drift_alerts, errors}`. Lazy and read-only; never triggers a Claude run.
- **`VERDICT_META` + `verdict_badge()` in `ui_theme.py`** — colour map for the thesis-tracker verdicts (materialized / partial / not_yet / invalidated), matching the existing badge family.
- **🧠 Learning tab in Streamlit (`ui/streamlit_app.py`)** — per-horizon edge metrics + bar chart, Sharpe-by-conviction table, thesis-verdict heat-map with history dots, thesis-text drift alerts.
- **Learning tab in the embedded Tk desktop (`src/desktop_app.py`)** — same data via Treeviews, registered between History and Config Editor, wired into the lazy `_on_tab_changed` warm-up so it doesn't fire on cold start.
- **One-line per-horizon edge in the Textual TUI Dashboard** — surfaces the same signal without adding a new pane.

### Fixed

- `summarize_outcomes` no longer raises `TypeError` when a legacy outcome row has `horizon_days=None` — bad rows are silently dropped from the new `by_horizon` block.

### Tests

- Total: **333 passing** (was 288) — `pytest -q` runs in ~2 s.
- New: `test_decision_journal_horizon.py` (8), `test_backtester_risk_metrics.py` (10), `test_drift_tracker_thesis_text.py` (10), `test_learning_view.py` (6), plus 5 added to `test_ui_theme.py` for `verdict_badge`.

---

## [1.15.1] — 2026-05-26

### Added — macOS native-app polish

- **Shared `PALETTE` adopted by `src/desktop_app.py`** — the embedded Tkinter dashboard now reads the same colour tokens as Streamlit and the Textual TUI, so a tweak in `src/ui_theme.py` propagates to every UI.
- **Native macOS menu bar with keyboard shortcuts** — File (New Report ⌘N, Open Latest ⌘L, Reveal Workspace, Reveal Latest Report), View (Dashboard / Buy Signals / Report / History / Config Editor ⌘,), Refresh Current Tab ⌘R, Find ⌘F, Help (Check for Updates, Open Repository, Report a Bug, About). On macOS the standard About / Preferences / Quit slots are wired into the application menu via `tk::mac::ShowPreferences` and `tk::mac::Quit`.
- **Status pill in the header** — top-right indicator shows `⚡ cost · ⚠️ warnings` (or `⛔` for high-severity) once the dashboard warms up; auto-refreshes when the dashboard refreshes.
- **Platform-aware font ladder (`_platform_fonts`)** — SF Pro Display / SF Pro Text / SF Mono on macOS, Segoe UI on Windows, TkDefault elsewhere; pushed through TFrame, Treeview, and TNotebook styles so every widget reads from the same family.
- **PyInstaller spec hardening** — `tech_stock.spec` now ships the macOS-recommended `Info.plist` keys: `LSApplicationCategoryType=public.app-category.finance`, `LSUIElement=False`, `NSPrincipalClass=NSApplication`, `NSSupportsAutomaticGraphicsSwitching`, `NSAppTransportSecurity`, plus user-friendly explanations for `NSAppleEventsUsageDescription`, `NSDocumentsFolderUsageDescription`, `NSDownloadsFolderUsageDescription`, and `NSDesktopFolderUsageDescription`. Added `CFBundleDocumentTypes` so double-clicking a CSV opens tech_stock.

### Fixed — Startup cost

- **Cold-start tax removed from `DesktopApp.__init__`**. Previously the constructor synchronously called `latest_report()`, `refresh_dashboard()`, `refresh_history()`, `load_report(...)`, a CSV-detection toast, an update probe, and a buy-signal refresh — the window paint was blocked for ~1–2 s on first launch. All of that now runs via `self.after_idle(self._post_paint_warmup)`, and `start_buy_signal_refresh` is deferred until the user actually opens the Buy Signals tab (saves the yfinance hits when they don't).
- **`aqua` ttk theme** preferred over `clam` on macOS so widgets honour the system dark-mode appearance.

### Tests

- New `tests/test_desktop_app_macos.py` (10 tests): font ladder, palette wiring, Info.plist keys, file-association, menu-factory presence, post-paint warm-up presence, no hard-coded hex.
- Total: **288 tests passing** (was 278).

---

## [1.15.0] — 2026-05-25

### Added — Production-grade UI overhaul

- **`src/ui_theme.py`** — single source of truth for visual language used by every front-end. Exports a colour `PALETTE`, `STREAMLIT_CSS` bundle, and HTML-escaped helpers for badges (`action_badge`, `severity_badge`, `readiness_badge`), conviction bars, status dots, metric cards, action cards, warning rows, hero banners, and empty-state placeholders. The Streamlit dashboard, Tkinter launcher and Textual TUI all consume the same tokens so a colour tweak only needs to happen in one place.
- **Streamlit dashboard rebuild (`ui/streamlit_app.py`)** — custom dark theme injected via CSS, polished sidebar (run settings · live API/update status · workspace info · refresh action), hero banner with latest-run context (date, portfolio value, β, run cost, warning count), 8 colour-coded tabs (📊 📝 🎯 ▶️ 📚 📈 📓 ⚙️), live status pills for Trade-Ready / Review-First / Blocked, conviction bars rendered inline, toast notifications for every state-changing action, friendly empty states for every section that can be empty, and contextual help tooltips on every model/budget/source control.
- **Native launcher polish (`src/app_gui.py`)** — switched to the shared palette, added per-mode icons (🖥 🌐 ⌨ ▶), hover affordance now lifts the whole card, footer renamed/repositioned, version pill in the header, and a new “Recent activity” panel with quick links to open the workspace folder or the latest report in Finder/Explorer.
- **Textual TUI polish (`ui/textual_app.py`)** — `rich.text.Text` cells colourise the action / severity / readiness columns in every table using the shared palette; placeholder screens for Buy Signals / Backtest are now multi-line with icons; the update-prompt modal got a centred layout, accent border, and a subtle “what is kept” line.
- **Theme + Streamlit smoke tests** — `tests/test_ui_theme.py` (40 tests covering XSS escaping, palette wiring, badge/card/conviction output, CSS bundle integrity) and `tests/test_streamlit_smoke.py` (mocks `streamlit` so the module runs end-to-end during pytest to catch import/template errors in CI).

### Fixed

- **`find_csv_by_date` no longer recurses the entire home directory.** Previously the fallback step ran `Path.home().glob("**/*.csv")` which could take 2+ minutes on disks with deep dot-trees (node_modules, IDE caches), and was paid on every UI startup whose CSV was missing. Now we look at a bounded list of common roots (Desktop, Documents, iCloud Drive Desktop/Documents) without recursion — observed boot time went from **117 s** to **<1 ms**.

### Tests

- Total: **278 tests passing** (was 236) — `pytest -q` runs in ~2 s.
- New: `test_ui_theme.py` (40), `test_streamlit_smoke.py` (2).

---

## [1.14.2] — 2026-05-24

### Added — Audit-driven hardening
- **`--version` flag** on both `python src/main.py` and the `./run.sh` launcher (short-circuits without hitting the update API).
- **`time_horizon` normalization** in `normalize_recommendation`: Claude variants like `3 months`, `1 year`, `long-term`, `next quarter` now snap to the canonical Rule 20 strings before logging/rendering, with the original preserved as `time_horizon_original` when changed.
- **Update-check disk cache**: `check_for_update(use_cache=True)` reads the last successful result from `user_workspace()/cache/update_check.json` (default TTL 6 hours). Background probes in `app_gui`, `ui_launcher`, Streamlit, Textual, and Desktop now use the cache; CLI `check-update` and explicit “Check now” buttons force a refresh. Failed lookups never cache; bumps to `APP_VERSION` invalidate stale entries automatically.
- **`unknown_with_lower_bound`** field in `aging_summary` and corresponding block in the prompt + markdown report: positions whose entry pre-dates the activities window now surface their `lower_bound_days` so Claude can reason about long-untouched holdings.

### Fixed
- **`apply_quality_gates` docstring** updated to reflect the seven actual layers (catalyst, stale, thesis decay, trailing stop, VIX, conviction sizing, drawdown) instead of the four documented when the gate was simpler.
- **README staleness** — version footer and recap pointer now match the v1.14 line.

### Changed — Code hygiene
- **Repo-wide `ruff format` baseline** applied to all source and test files. CI’s ruff-format step now checks `src/` and `tests/` instead of four hand-picked files, so future drift is caught at PR time.

### Tests
- Added `test_main_cli.py` (3 tests), `test_horizon_normalization.py` (29 tests), updater cache coverage (5 tests), and 3 new position-aging tests for `unknown_with_lower_bound`.
- Full local suite: **236 tests passing** (was 196).

---

## [1.14.1] — 2026-05-24

### Fixed — Security and updater hardening
- Raised `pyarrow` to the fixed `23.0.1+` range after `pip-audit` flagged `PYSEC-2026-113` in the previous pinned range.
- The updater now records whether checksum verification succeeded, was skipped, or failed in the `UpdateResult` path instead of discarding that result.

### Tests
- Added updater coverage for checksum reporting during update application.
- Full local suite: 196 tests passing.

---

## [1.14.0] — 2026-05-18

### Added — Roadmap hardening
- **Trade readiness view models** classify Buy Signals as Trade Ready, Review First, or Blocked from quote freshness, quality warnings, catalyst gates, and source coverage.
- **Buy Signal filters** added across Desktop, Streamlit, and Textual for BUY/ADD, add-on-dip, and readiness status.
- **ReportPipeline facade** returns structured report artifacts for UI callers while preserving the existing CLI workflow.
- **Release checksums** are published as `SHA256SUMS.txt`, and the updater verifies downloaded assets when checksums are available.
- **CI hardening** adds ruff, pip-audit, and PyInstaller smoke jobs alongside pytest.

### Tests
- Added shared view-model, pipeline facade, checksum, and mocked end-to-end pipeline coverage.
- Full local suite: 195 tests passing.

---

## [1.13.7] — 2026-05-18

### Added — Source-backed Buy Signals
- **Buy Signals tab** added to Desktop, Streamlit, and Textual for BUY/ADD and add-on-dip candidates from the latest recommendation log.
- **Consensus and target snapshots** show Finnhub analyst buy/hold/sell consensus and Yahoo/yfinance analyst target fields when available.
- **Catalyst and risk detail** separates catalyst source, manual-review flag, recent news, technicals, insider activity, earnings, quality warnings, and invalidation notes.
- **Source transparency** lists the data feed behind each signal so the UI does not present unsourced visual claims.

### Changed
- Market data now stores Yahoo/yfinance analyst target fields and uses cache version 5 for the expanded schema.

### Tests
- Full local suite: 186 tests passing.

---

## [1.13.6] — 2026-05-18

### Added — API health and key management
- **Complete API health checks** now cover Anthropic, yfinance, Finnhub, Polygon, Twelve Data, FRED, CoinGecko, and Alpha Vantage.
- **Desktop API Key Manager** lets users add/update/delete supported API keys from the API Checks tab.
- **Streamlit API Key Manager** exposes the same masked key inventory and save/delete flow in the browser dashboard.
- **Secret-safe display** masks configured key values and shows the source file path without printing full secrets.

### Tests
- Added focused API key manager tests.
- Full local suite: 183 tests passing.

---

## [1.13.5] — 2026-05-18

### Fixed — Native Tk search crash
- **Desktop report search no longer calls Tk `Text.search`**, avoiding the macOS packaged-app crash path seen in `Tcl_UtfToLower` / `TextSearchAddNextLine`.
- **Search now computes match offsets in Python** and uses Tk only to highlight the resulting ranges.

### Tests
- Added focused desktop search offset tests.
- Full local suite: 179 tests passing.

---

## [1.13.4] — 2026-05-18

### Fixed — Desktop report search crash
- **Search typing no longer runs live whole-report highlighting** on every keypress, preventing packaged Tk crashes when entering common letters.
- **Find button added** so users can type a full word first, then search with **Find**, `Enter`, **Next**, or **Previous**.
- **Match highlight cap** limits very broad searches to the first 500 visible matches and marks the count with `+`.

### Tests
- Full local suite: 176 tests passing.

---

## [1.13.3] — 2026-05-18

### Added — Desktop report search
- **Report Viewer search** adds a native search field with highlighted matches, current-match focus, match counts, Find, Next/Previous navigation, and Clear.
- **History report search** adds the same search controls to the selected historical report preview.
- **Keyboard shortcut** supports `Cmd+F` on macOS and `Ctrl+F` on Windows/Linux to focus report search.

### Tests
- Full local suite: 176 tests passing.

---

## [1.13.2] — 2026-05-17

### Improved — Desktop dashboard
- **Action cockpit layout** replaces the dense dashboard tables with wrapped action cards, severity-colored quality gate cards, and stop-breach cards.
- **Metric cards** now include secondary context such as benchmark beta, drawdown estimate, concentration risk, warning totals, and token count.
- **Next-action panel** now carries a colored urgency stripe and summarizes priority actions, quality gates, and stop breaches at a glance.

### Tests
- Full local suite: 176 tests passing.

---

## [1.13.1] — 2026-05-16

### Fixed — Packaged updater HTTPS certificates
- **macOS/Windows update checks** now use the bundled `certifi` CA certificate bundle instead of relying on Python's default certificate lookup inside the packaged app.
- **Packaging** now explicitly includes `certifi` data files so GitHub Release checks and downloads can verify HTTPS certificates.
- **Error text** for certificate failures now explains the update-check problem instead of showing a raw `urlopen` SSL exception.

### Tests
- Full local suite: 176 tests passing.

---

## [1.13.0] — 2026-05-16

### Added — In-app updates
- **Shared updater** (`src/updater.py`) — checks GitHub Releases, compares semantic versions, selects the correct platform asset, downloads updates into the app workspace, and writes `logs/update.log`.
- **Startup update checks** — interactive Desktop, Streamlit, Textual, and native launcher sessions check for newer releases and ask before applying an update.
- **Manual update controls** — Desktop App adds an Updates tab, Streamlit adds an Updates sidebar section, Textual adds an Updates tab, the native launcher adds a Check Updates button, and terminal users can run `python src/main.py check-update` or `python src/main.py update`.
- **Data preservation** — updates keep reports, recommendation logs, uploaded CSVs, config files, decision journals, and API key files in the durable app workspace.
- **Version metadata** — app version now lives in `src/version.py`, and macOS bundle metadata reads that version during packaging.

### Tests
- Full local suite: 175 tests passing.

---

## [1.12.3] — 2026-05-14

### Added — Desktop dashboard and report readability
- **Action dashboard** — the embedded Desktop App Dashboard now surfaces the next action, portfolio/risk cards, priority action queue, quality gates, stop breaches, drift, hedge ideas, market context, and watchlist signals.
- **Styled report reader** — Report Viewer and History now render markdown with styled headings, paragraph spacing, bold text, and aligned table blocks instead of raw markdown.
- **Compact report paths** — Report Viewer keeps search paths available behind a Show/Hide control so the report content starts higher on the screen.
- **Richer UI summaries** — UI summary helpers now expose session summary, market context, watchlist flags, trailing-stop breaches, sector warnings, and general warnings from the latest JSON log.

### Tests
- Full local suite: 171 tests passing.

---

## [1.12.2] — 2026-05-14

### Fixed — Desktop report discovery visibility
- **Report Viewer search paths** — the embedded Desktop App now shows every markdown report folder it checks, with found/missing status and report counts.
- **History search paths** — the History tab now uses and displays the same multi-folder report discovery list.
- **Cross-mode report discovery** — source runs and packaged-app runs can now find reports from the active workspace, current folder, `~/Documents/tech_stock/`, `~/Desktop/tech_stock/`, `~/Downloads/tech_stock/`, and the source checkout.
- **README locations** — documentation now explains where source and packaged app runs save reports, logs, uploads, and config.

### Tests
- Full local suite: 171 tests passing.

---

## [1.12.1] — 2026-05-14

### Fixed — Desktop app file discovery
- **Packaged-app workspace** — native builds now use a writable `~/Documents/tech_stock/` workspace for config, reports, uploads, and logs instead of relying on the temporary PyInstaller extraction directory.
- **API key discovery** — `API_KEYS.txt` and `.env` are searched in the writable workspace, current folder, `~/Desktop/tech_stock/`, `~/Downloads/tech_stock/`, and the source checkout.
- **Desktop API Checks tab** — now displays every API-key file path checked, with found/missing status.
- **Detected CSV confirmation** — the embedded Desktop App now asks users to confirm auto-detected Holdings and Activities CSV paths before using them.
- **Release packaging** — bundled builds now include `API_KEYS.template.txt` and `.env.example` so the packaged workspace can seed user-facing setup files.

### Tests
- Full local suite: 171 tests passing.

---

## [1.12.0] — 2026-05-14

### Added — Embedded desktop application
- **Embedded Desktop App** (`src/desktop_app.py`) — native Tkinter dashboard that runs inside the application window with no browser dependency.
- **Desktop tabs** — Dashboard, Run Report, Report Viewer, History, Config Editor, and API Checks.
- **Live report progress** — desktop runs stream CLI progress into the app while calling the same `src.ui_support.run_report_from_ui()` pipeline as Streamlit/Textual.
- **Native launcher update** (`src/app_gui.py`) — adds **Desktop App** as the first option while keeping Streamlit Web UI, Textual Terminal UI, and CLI available.
- **Source launcher update** (`src/ui_launcher.py`, `run.sh`) — `./run.sh 4` launches the embedded Desktop App from source.
- **Packaging update** (`tech_stock.spec`) — includes the new desktop module and Tkinter submodules in PyInstaller builds.

### Fixed
- **Streamlit startup observability** — the native launcher now starts Streamlit as a child process, opens the default browser, and reports startup failures with a log path instead of silently closing.
- **Streamlit/PyArrow compatibility** — requirements now pin `numpy<2` and include a compatible PyArrow range to avoid compiled-extension import crashes.

### Tests
- Full local suite: 171 tests passing.

---

## [1.11.0] — 2026-05-13

### Added — Decision journal + outcome scoring
- **Decision journal** (`src/decision_journal.py`) — every actionable BUY/ADD/TRIM/SELL recommendation is seeded into a local `data/decision_journal.json` as a pending decision. The file is git-ignored because it contains personal execution notes.
- **Actual decision capture** — users can record whether they accepted, ignored, modified, delayed, watched, or executed each recommendation, plus actual action, shares, execution price, reason, and notes.
- **Outcome scorecard** — recorded decisions are scored over configurable 1/5/20/60-day windows, comparing model action return, user action return, hit rates, and discretion delta.
- **Prompt feedback loop** — the decision scorecard is fed into Claude alongside the existing recommendation backtest so future reports can calibrate around the user's real follow-through pattern.
- **Report/UI visibility** — markdown reports include a Decision Journal section; Streamlit adds a full Decision Journal tab; Textual shows journal status and scorecard summaries in dashboard/backtest views.

### Tests
- Added focused coverage for journal seeding, user-decision recording, outcome scoring, and report rendering.

---

## [1.10.0] — 2026-05-10

### Fixed — Live-run report reliability
- **Yahoo/yfinance news parsing restored** (`src/news_fetcher.py`) — current yfinance news items publish timestamps under `content.pubDate`; the app now parses that shape correctly, so large-move catalyst checks can cite current headlines again.
- **Empty news responses are not cached** (`src/cache.py`, `src/news_fetcher.py`) — transient empty headline fetches no longer suppress news for the rest of the cache window.
- **Claude JSON truncation hardening** (`src/claude_analyst.py`) — default `claude_max_tokens` raised to `24000`, prompt news payload reduced to two articles per ticker, Rule 32 now includes field-length caps, and the app retries once with emergency compact JSON caps when a response is truncated or invalid JSON.
- **Leveraged ETF holding-duration wording** (`src/activity_loader.py`, `src/report_generator.py`, `src/claude_analyst.py`) — when the original buy predates the Activities export, reports now show a lower bound such as `held at least 41 days` instead of misleading `>90d` or only `duration unknown`.
- **Position Aging wording** (`src/report_sections.py`) — reports disclose unknown entry dates instead of saying every open position is fresh/core.
- **Cost footer visibility** (`src/main.py`, `src/report_generator.py`) — JSON retry count is included in CLI/report cost summaries when a retry occurs.
- **Deterministic SELL/TRIM sizing** (`src/recommendation_sizing.py`) — action rows now include exact shares, position fraction, and estimated proceeds from the holdings snapshot when available.
- **Grouped Critical Actions** (`src/report_generator.py`) — quote-source mismatches are consolidated into one high-signal action item instead of repeating the same instruction for many tickers.
- **Full-export holding ages** (`src/main.py`, `src/activity_loader.py`) — Activities CSVs are parsed as a recent slice for prompt context and as a full export for FIFO holding-day calculations.

### Validation
- Full paid Sonnet live run on May 10, 2026 using April 29 holdings/activities CSVs: 31 tracked tickers, two Claude passes, 50,105 tokens, estimated cost `$0.6341`, cache hit, no JSON retry required.
- The run produced `reports/20260510_2011_afternoon.md` locally; generated reports remain git-ignored and are not committed.

### Tests
- Added focused coverage for news timestamp parsing, no-cache empty values, activity lower-bound durations, truncated Claude retry, cost footer retry display, and unknown Position Aging wording.

## [1.9.0] — 2026-05-06

### Added — Report visibility + P3 strategy infrastructure
- **All v1.7+ strategy gates now visible in the markdown report** (`src/report_sections.py`):
  - **Active Risk Modifiers banner** at top of report — shows drawdown circuit breaker status and VIX-regime sizing multiplier when active
  - **Position Aging table** — counts per tier (fresh/core/mature/aged/stale) plus actionable ticker lists
  - **Trailing Stops section** — breached stops in their own callout block; active trails as informational table
  - **Sector Rotation table** — leaders, laggards, and rotating-in/out arrows with trade bias guidance
  - **Tranched Entry/Exit Plan** sub-table inside each recommendation showing the 3-step execution plan
  - CSV export now includes `Tranche 1 (now) / Tranche 2 (pullback) / Tranche 3 (confirmation)` columns
- **Thesis-decay tracker** (`src/thesis_tracker.py`) — every BUY records its original thesis to `data/thesis_log.json`. After 90 days, an automatic verdict (`materialized` / `partial` / `not_yet` / `invalidated`) is appended. After 4 consecutive `not_yet` reviews (~12 months), the position is added to `force_exit_candidates` and `apply_quality_gates` converts it to SELL — even if Claude tries to keep it.
- **Paper-trading mode** (`src/paper_trading.py`, `--paper` flag) — applies every Claude recommendation to a parallel simulated portfolio in `data/paper_portfolio.json`. Tracks cash, fractional shares, fees, and value history. Lets you quantify the **discretion penalty** — the gap between recommendations and what you actually traded. Summary appears at the top of the markdown report.
- **2 new SYSTEM_PROMPT rules (40)** for thesis decay + clarification of forced exits.

### Tests
- 21 new tests across `test_report_sections.py`, `test_thesis_tracker.py`, `test_paper_trading.py`. Total suite now 147 tests, all passing.

---

## [1.8.0] — 2026-05-06

### Added — P2 strategy polish
- **Trailing stops** (`src/trailing_stops.py`) — stops auto-tighten as positions appreciate: +10% gain → breakeven; +20% → trail by 8% from peak; +40% → trail by 12% from peak. Schedule configurable via `trailing_stop_schedule`. Breached stops auto-generate TRIM via `apply_quality_gates`.
- **Sector rotation rhythm** (`src/sector_rotation.py`) — ranks sector ETFs by 1-month relative strength, identifies leaders/laggards, and detects "rotating in" / "rotating out" tickers vs the previous session (uses persisted `market_context_snapshot`). Rotating-in sectors get add bias; rotating-out get trim bias.
- **Tranched entry/exit plans** — `normalize_recommendation` backfills a 3-step `entry_plan` (40% now / 30% on pullback / 30% on confirmation) for every BUY/ADD and a 3-step `exit_plan` for every TRIM/SELL when Claude omits them. Lowers average entry by ~0.5–1% historically and produces 3 weekly small actions per trade idea.
- **Live FX rate** (`fred_client.live_cad_per_usd`) — fetches USD→CAD daily from FRED `DEXCAUS`, cached 24h, with 1.20–1.55 sanity range. Falls back to static `cad_per_usd_assumption` on failure. Replaces ±3% pricing error on CAD-denominated holdings.
- **3 new SYSTEM_PROMPT rules (37–39)**: trailing stops, sector rotation, tranched plans.

### Fixed
- **News cache returned stale headlines on second daily run** — cache key now includes `YYYYMMDD`, so a Friday-afternoon run after a Friday-morning run no longer returns morning's headlines.
- **Drift tracker self-compared on quick re-runs** — `get_previous_session` now skips files newer than `min_age_hours` (default 4h) and prefers the same session-type from the previous trading day. Keeps drift signal meaningful when you re-run morning at 9:35am after running at 9:30am.

### Tests
- 31 new tests across `test_trailing_stops.py`, `test_sector_rotation.py`, `test_p2_polish.py`. Total suite now 111 tests, all passing.

---

## [1.7.0] — 2026-05-06

### Added — Strategy alignment (3-6 month sweet spot, weekly small actions, 2-year hard cap)
- **Position-aging tiers** (`src/position_aging.py`) — every holding is classified as `fresh` (0-90d), `core` (91-180d), `mature` (181-365d), `aged` (366-730d), or `stale` (>730d). Tags appear in the prompt and drive deterministic actions.
- **2-year hard cap enforcement** — `apply_quality_gates` automatically converts any non-SELL/TRIM action on a `stale` ticker to TRIM, and appends an auto-generated TRIM for stale holdings Claude omitted. Implements the user's explicit "no permanent holds" rule.
- **VIX-regime sizing** (`vix_size_multiplier`) — invest_amount_usd scaled by VIX level: <15 = 1.0×, 15-25 = 0.85×, 25-35 = 0.6×, >35 = 0.4×. Configurable via `vix_size_thresholds` in settings.json.
- **Drawdown circuit breaker** (`portfolio_analytics.detect_drawdown`) — when portfolio is ≥6% off its 30-day rolling peak (configurable), `apply_quality_gates` halves all ADD sizes, converts BUYs to HOLD-watch, and forces HOLD-watch on conviction <7. Threshold configurable via `drawdown_circuit_breaker_pct`.
- **Conviction-stratified sizing from actual hit rates** (`backtester.summarize`) — each conviction bucket with ≥3 mature samples gets a Kelly-lite sizing multiplier `clamp(0.4, hit_rate × (1 + avg_return/10), 1.4)`. Applied automatically in `apply_quality_gates` so position sizes follow your real edge, not just your conviction.
- **Catalyst-window classifier** (`src/catalyst_windows.py`) — annotates each ticker by earnings proximity:
  - `setup` (T-30 to T-6): entries OK if conviction ≥7
  - `lockdown` (T-5 to T+0): no new BUY/ADD (IV crush risk)
  - `drift` (T+1 to T+3): post-earnings adds OK if direction confirmed
  - Plus session-level macro tags: `FOMC_TODAY`, `FOMC_IN_2D`, `CPI_WEEK`, `NFP_DAY`. Auto-detected from FRED calendar and date math; piped into the prompt as constraints.
- **Position aging exposed in prompt** — `holding_days_by_ticker` output (already computed) is now threaded into Claude's user message. Each holding gets a `held 200d [mature]` tag inline, plus a top-level POSITION AGING summary block when any positions need re-validation.
- **4 new system prompt rules** (33-36): position aging, VIX sizing, drawdown mode, catalyst windows. Each with explicit thresholds and required actions.

### Fixed
- **`MODEL_PRICING` was using 5-minute cache write rates** (1.25× input) for code that actually uses 1-hour cache (`ttl: "1h"` → 2× input rate). Costs were under-reported by ~25% per session. New `cache_write_5m` and `cache_write_1h` keys; `estimate_cost` reads the right one based on `_CACHE_TTL` constant.

### Tests
- 41 new tests across `test_position_aging.py`, `test_catalyst_windows.py`, `test_strategy_gates.py`, `test_pricing_and_drawdown.py`, `test_backtester_fees.py`. Total suite now 80 tests, all passing.

---

## [1.6.0] — 2026-05-06

### Added
- **Native macOS `.app` + `.dmg`** via PyInstaller (`build_macos.sh`) — double-click to install, no terminal required
- **Native Windows `.exe`** via PyInstaller (`build_windows.bat`); optional Inno Setup installer (`installer_windows.iss`)
- **GitHub Actions release workflow** (`.github/workflows/build_release.yml`) — push a version tag → both `.dmg` and `.exe` built and uploaded as release artifacts automatically
- **tkinter GUI launcher** (`src/app_gui.py`) — dark-themed window with three one-click cards (Streamlit / Textual / CLI); used by the packaged app bundle
- **Unified `./run.sh` entry point** — with no args shows the interface choice menu; existing callers with `morning`/`afternoon`/`--model` args are forwarded unchanged (fully backward-compatible)
- **PyInstaller spec** (`tech_stock.spec`) with full Streamlit static asset collection, Textual CSS, and all hidden imports
- **App icon** (`assets/icon.png`, `assets/icon.icns`)

### Fixed
- **Backtest tab blocked app startup** — `run_backtest_summary()` was called on every Streamlit page load, triggering live yfinance price fetches for all past recommendations and freezing the UI. It is now on-demand only (click "Run backtest").
- **Textual `RichLog` rendered markdown as plain text** — Today's Report and History tabs now use the Textual `Markdown` widget; headings, tables, and bold text render correctly.
- **Backtest button in Textual was synchronous** — now runs in `asyncio.to_thread` so the UI stays responsive during the yfinance fetch.
- **`run-ui.sh` was missing `.env` loading and API key check** — simplified to `exec ./run.sh "$@"` so all env setup is in one place.
- **`preview_holdings_csv` always returned `None` for the value column** — `market_value_usd` key does not exist; fixed to use `market_value` + `currency`.
- **Upload fingerprinting used file size** — two different files of identical byte size were treated as the same upload; fixed to use `hashlib.md5(data).hexdigest()`.
- **ANSI escape regex too narrow** — `r"\x1b\[[0-9;]*m"` missed non-SGR sequences (e.g. charset switches); broadened to cover all standard ANSI escape sequences in both UIs.

---

## [1.5.0] — 2026-04-30

### Added
- **Streamlit web dashboard** (`ui/streamlit_app.py`) — Dashboard, Run Report, Today's Report, History, Backtest, Portfolio Editor tabs
- **Textual terminal UI** (`ui/textual_app.py`) — same workflow, keyboard-driven, no browser needed
- **Shared UI helpers** (`src/ui_support.py`) — `run_report_from_ui()`, `TeeProgressIO` for live progress streaming, `latest_log_summary()`, `check_connectivity()`, holdings preview, JSON validation
- **Live progress streaming** during report run — `TeeProgressIO` tees stdout/stderr to the UI in real time so users see each phase as it runs
- **Dashboard tab** — surfaces `risk_dashboard`, `quality_warnings`, `priority_actions`, `hedge_suggestions`, `drift_vs_previous`, and Claude cost/tokens from the latest JSON log without scrolling a 700-line report
- **Holdings CSV preview** — parse and display a dataframe before spending Claude tokens
- **JSON editor with live validation** — settings, watchlist, and fallback portfolio editable in-browser with per-keystroke parse errors
- **Connectivity check** — one-click health check for Anthropic, yfinance, Finnhub, and Polygon with latency display
- **Download buttons** for markdown report, CSV, and JSON log after a successful Streamlit run
- **History tab compare** — side-by-side markdown diff of two historical reports
- **Keyboard shortcuts in Textual** — `Ctrl+R` run, `Ctrl+S` save editor, `r` refresh current tab
- `run-ui.sh` launcher script

---

## [1.4.0] — 2026-04-30

### Added
- **Two-pass Claude review** — Pass 1 generates initial JSON; Pass 2 receives quality warnings + drift and revises. Prevents stale-catalyst and overbought-entry recommendations from slipping through.
- **Prompt caching** — system prompt cached for 1 hour (Anthropic `cache_control: ephemeral, ttl: 1h`); user message also cached on Pass 2. Reduces typical run cost ~40%.
- **Opus extended thinking** — configurable via `enable_opus_extended_thinking` + `opus_thinking_budget_tokens`; activates only when Opus is selected
- **Drift tracker** — detects action flips (BUY→SELL) and conviction changes between consecutive sessions; fed into Pass 2 prompt
- **Critical Actions section** — top-of-report checklist consolidates high/medium quality warnings, manual catalyst reviews, leveraged ETF duration risk, and major drift items
- **Richer market data** — premarket/after-hours moves, FCF yield, gross/operating margins, dividend yield, ex-dividend dates
- **Enrichment signals** — Finnhub analyst upgrade/downgrade events; deterministic macro calendar estimates for NFP/CPI/FOMC verification; optional Polygon current snapshot
- **Leveraged ETF decay estimate** — includes holding days + estimated volatility-decay drag when 20-day vol is available
- **Previous session execution check** — compares prior actionable recommendations against recent activities CSV rows
- **Data freshness footnotes** — quote-quality section explains provider quote vs daily-close fallback semantics

---

## [1.3.0] — 2026-04-30

### Added
- **Report quality warnings** — 13 deterministic warning codes: `stale_or_unstamped_quote`, `missing_catalyst_verification`, `missing_decision_tree`, `oversized_company_exposure`, `reversed_price_range`, and more
- **Hard quality gates** — `apply_quality_gates()` auto-downgrades BUY/ADD to HOLD-watch and caps conviction ≤5 when catalyst is unverified for large movers or near-earnings names
- **Portfolio risk dashboard** — `compute_risk_dashboard()`: annualized volatility, max drawdown estimate, beta vs SPY/QQQ/SMH, correlated pairs, top-3 concentration
- **Company exposure rollup** — `aggregate_company_exposure()` groups tickers by economic entity (e.g. GOOGL + GOOG + GOOGL.TO) via `COMPANY_GROUPS` in `constants.py`
- **Hedge suggestions** — `build_hedge_suggestions()`: trim-first recommendations + capped PSQ hedge when beta or concentration is high
- **Priority actions** — "Do This Today" ranked list by urgency, fed from Claude's structured `priority_actions` array
- **Investment sizing** — exact USD amounts per trade scaled by conviction (8–10 = 40% of budget, 7 = 25%, 6 = 15%)
- **Hold tiers** — HOLD labeled as watch / keep / add_on_dip for clear next steps
- **Earnings alerts** — flags tickers with earnings within 7 days; independently verified from enrichment data (not only from Claude's flag)
- **Exit planning** — every recommendation includes target exit date and Bear Case / Bull Case ranges
- **6 enrichment APIs** — Finnhub, Polygon, Twelve Data, FRED, CoinGecko, optional Alpha Vantage
- **`src/report_quality.py`**, **`src/portfolio_analytics.py`**, **`src/fred_client.py`** — new modules
- **Test suite + CI** — pytest coverage for parsers, quality gates, rendering, drift, analytics; GitHub Actions workflow

### Fixed
- **Decision-tree regex false negatives** — `_has_decision_tree` now handles "action if condition" form (e.g. "Trim 20% if RSI exceeds 78") in addition to "if condition, action"
- **FRED `_macro_summary` operator-precedence bug** — adjacent f-string concatenation silently dropped CPI and VIX from the summary string; fixed with explicit `list.append()` pattern
- **`reversed_price_range` quality warning was dead code** — `normalize_recommendation()` now sets `range_was_normalized = True` before `evaluate()` runs, so the check fires correctly

---

## [1.2.0] — 2026-01

### Added
- **FRED macro context client** (`src/fred_client.py`) — Fed Funds Rate, CPI inflation (YoY), yield curve (T10Y2Y), VIX; derives regime labels (INVERTED, HIGH, ELEVATED, etc.)
- **Economic calendar estimates** — deterministic NFP/CPI/FOMC window estimates (no live source required)
- **Enrichment pipeline** — Phase 1 parallel dispatch (Finnhub, Polygon, Twelve Data, FRED, CoinGecko); Phase 2 sequential optional (Alpha Vantage)
- **Backtester** (`src/backtester.py`) — loads all past recommendation JSON logs, compares expected vs actual price moves via yfinance historical data, aggregates by action/conviction/ticker; summary fed into Claude prompt for conviction calibration

---

## [1.1.0] — 2026-04-24

### 🎯 Summary

Major cleanup & optimization pass (Phases A-D). Eliminated code duplication, established single sources of truth for config and constants, simplified watchlist schema, and achieved 6× speedup on market data fetching through parallelization.

### ✨ Phase A: Shared Modules (New)

Created three new centralized modules to eliminate copy-paste vulnerabilities and establish single sources of truth:

- **`src/config.py`** (17 lines)
  - Centralized `load_settings()` function
  - Replaces 5 identical copies scattered across claude_analyst.py, market_data.py, news_fetcher.py, fee_calculator.py
  - Loads `config/settings.json`
  - Future home for env-override validation

- **`src/constants.py`** (31 lines)
  - `LEVERAGED_ETFS` — 21 ETF tickers (SOXL, SOXS, TQQQ, SQQQ, UPRO, UVXY, TMF, TZA, SPXL, LABU, LABD, TSLL, NVDL, TMV, UDOW, SDOW, FAS, FAZ, TNA, YINN, YANG)
  - `DEDUP_PAIRS` — ticker pairs to deduplicate (GOOGL/GOOG, BRK.A/BRK.B)
  - `SKIP_MARKET_DATA` — tickers to skip market data fetching (CASH)
  - `CDR_EXCHANGES` — Canadian exchange codes (XTSE, TSX)

- **`src/_utils.py`** (50 lines)
  - `safe_float(v)` — converts possibly-blank/quoted strings to float, returns None on failure
  - `clean_csv_row(row)` — strips surrounding whitespace and quotes from every key+value
  - `parse_session_filename(name)` — parses "YYYYMMDD_HHMM_{morning|afternoon}.json" format

### 🧹 Phase B: Deduplication (Modified)

Replaced per-file copies with centralized imports across all modules:

**Modules Updated:**
- `src/claude_analyst.py` — removed local `load_settings()`; removed dead `base` variable block
- `src/market_data.py` — removed local `load_settings()`
- `src/news_fetcher.py` — removed local `load_settings()`
- `src/fee_calculator.py` — removed local `load_settings()`; now reads `smallcap_tickers` from settings
- `src/portfolio_loader.py` — removed local `_safe_float()`, `CDR_EXCHANGES`; replaced CSV cleanup with `clean_csv_row()`
- `src/activity_loader.py` — removed local `_safe_float()`; replaced CSV cleanup with `clean_csv_row()`
- `src/backtester.py` — removed local `_FILENAME_RE` regex; uses `parse_session_filename()` instead
- `src/drift_tracker.py` — removed local `_FILENAME_RE` regex; uses `parse_session_filename()` instead
- `src/report_generator.py` — removed local `LEVERAGED_ETFS`; imports from constants
- `src/main.py` — removed local `SKIP_MARKET_DATA`, `DEDUP_PAIRS`; imports from constants

**Config Updates:**
- `config/settings.json` — added `"smallcap_tickers"` array for fee calculator

**Result:** ~80 net lines deleted

### 📋 Phase C: Watchlist Schema Collapse (Modified)

Unified watchlist representation from dual-schema to single source of truth:

**Before:** `config/watchlist.json` carried both old keys ("all", "megacaps", "growth", "aggressive", "canadian_tech") AND new "entries" array

**After:** Single clean schema with only "entries" array:
```json
{
  "_comment": "Each entry: ticker, optional category, optional target prices.",
  "entries": [
    {"ticker": "MSFT",    "category": "megacaps",      "target_entry_price": 380.0,  "target_exit_price": null},
    {"ticker": "AMD",     "category": "growth",        "target_entry_price": 250.0,  "target_exit_price": 320.0},
    ...
  ]
}
```

**Modified:**
- `src/main.py:watchlist_tickers()` — simplified from ~17 lines to 1 line; removed dual-schema fallback

### ⚡ Phase D: Parallel Fetching (Modified)

Replaced serial yfinance fetching with `ThreadPoolExecutor` for 6× speedup:

**Before:** Sequential loop fetching 18 tickers one-by-one = ~60 seconds on cold cache

**After:** Parallel fetching with max_workers=8 = ~10 seconds on cold cache

**Modified:**
- `src/market_data.py:get_market_data()` — uses `ThreadPoolExecutor` with `as_completed()` loop
- `src/news_fetcher.py:get_news_for_tickers()` — same parallelization pattern
- Max workers capped at 8 to stay polite to yfinance rate limits
- Retry logic already in place, so this is safe

### 🎨 Additional Polish: Interactive Setup

Extracted 3 helper functions to eliminate duplicate input validation loops:

- `_prompt_positive_float(label, example)` — unified USD/CAD budget prompts
- `_prompt_for_existing_path(prompt_label)` — unified CSV path validation
- `_prompt_yes_no(prompt)` — unified Y/N confirmation loops

**Result:** `interactive_setup()` reduced from ~140 to ~95 lines

### 📊 Architecture Improvements

**Single Sources of Truth Established:**
1. Settings loading — one `config.py` (was 5 copies)
2. Leveraged ETF list — one `constants.py` (was in report_generator.py + prompt text)
3. Smallcap tickers — one `settings.json` array (was hardcoded inline)
4. CDR exchanges — one `constants.py` (was in portfolio_loader.py)
5. Dedup pairs — one `constants.py` (was in main.py)
6. Watchlist — one schema in `config/watchlist.json` (was dual-schema)
7. Session filename parsing — one regex in `_utils.py` (was in backtester.py + drift_tracker.py)
8. CSV cleanup — one function `clean_csv_row()` (was duplicated in 2 loaders)
9. Safe float conversion — one function `safe_float()` (was duplicated in 3 modules)

**Performance:**
- Market data + news fetch: ~60s → ~10s (18 tickers, cold cache)
- No change to recommendation quality or user-facing API

### 📝 Documentation Updates

- **README.md** — updated module overview, data flow diagram, project structure, version to 1.1.0
- **QUICKSTART.md** — updated model choice section to include Opus 4.7 details
- **CHANGELOG.md** — this file (new)

### ✅ Testing & Verification

- All imports verified via syntax checks
- Live market data tested against real Yahoo Finance API
- Verified parallel fetching works correctly (tickers fetch concurrently)
- Backward compatibility maintained for existing `data/recommendations_log/` format
- Cache namespace unchanged (cache from v1.0.0 still works)

### 🔄 Migration Notes

**For existing users:**
- If running this version on an old `config/watchlist.json` with the flat schema, the app will still work but won't read the legacy keys
- Recommendation: pull the updated `config/watchlist.json` from this commit
- All your existing trade logs, recommendations, and cached data remain compatible

---

## [1.0.0] — 2026-04-10

### Initial Release

- Claude-powered portfolio advisor for Wealthsimple Premium USD accounts
- Twice-daily trading recommendations with conviction scoring
- Fee-aware analysis (Wealthsimple + bid-ask spreads)
- Live market data via yfinance
- Recent news headlines for context
- Markdown + CSV + JSON output formats
- Interactive setup flow
- Trade history tracking for backtesting
- Dual model support (Sonnet 4.6 for speed, Opus 4.7 for depth)

---

## Upgrade Path

### From 1.0.0 → 1.1.0

**No breaking changes.** All existing features work identically:

1. Recommendation format unchanged
2. Cache format unchanged
3. CLI arguments unchanged
4. Output paths unchanged
5. Configuration keys unchanged (except new `smallcap_tickers` in settings.json)

**To upgrade:**
```bash
git pull origin main
# No re-setup needed; existing .env, config/, and data/ directories continue to work
```

**Optional improvements (not required):**
- Pull updated `config/watchlist.json` to benefit from cleaner schema
- Run a fresh market data fetch to benefit from parallel fetching speedup

---

## Performance Benchmarks

| Metric | v1.0.0 | v1.1.0 | Improvement |
|--------|--------|--------|-------------|
| Market data fetch (18 tickers, cold cache) | ~60s | ~10s | 6× faster |
| Code duplication (modules with copy-paste) | 9 | 0 | 100% eliminated |
| Lines deleted (net) | — | ~80 | Cleaner codebase |
| Single sources of truth | 3 | 12 | 4× more robust |

---

## Code Quality Metrics

**Before (v1.0.0):**
- 5 identical `load_settings()` implementations
- 2 versions of `_safe_float()`
- 2 versions of filename regex parsing
- Duplicate CSV cleanup logic in 2 loaders
- Dual-schema watchlist (confusing maintenance burden)

**After (v1.1.0):**
- 1 `load_settings()` in config.py
- 1 `safe_float()` in _utils.py
- 1 `parse_session_filename()` in _utils.py
- 1 `clean_csv_row()` in _utils.py
- Single clean watchlist schema
- All constants in one `constants.py` file

---

**Last Updated:** 2026-04-24  
**Prepared By:** Claude Code + Pouya
