# tech_stock — Architecture

This document is for people reading the code: contributors, forkers,
and auditors. End-users should start with [the README](../README.md) or
the [User Guide](USER_GUIDE.md).

## Bird's-eye view

```
                          ┌──────────────────────────┐
                          │   Wealthsimple CSV(s)    │  (or sample data in demo mode)
                          └────────────┬─────────────┘
                                       │
                            ┌──────────▼──────────┐
                            │ portfolio_loader.py │
                            └──────────┬──────────┘
                                       │ holdings dict
        ┌──────────────────────────────┼──────────────────────────────┐
        │                              │                              │
   ┌────▼────┐               ┌─────────▼─────────┐            ┌───────▼────────┐
   │ market_ │               │   enriched_data   │            │  thesis_log /  │
   │ data.py │               │ (Phase 1 parallel,│            │  decision_     │
   └────┬────┘               │  Phase 2 serial)  │            │  journal       │
        │                    └─────────┬─────────┘            └───────┬────────┘
        │ prices, sectors, technicals  │ news, calendars, macro, FX   │
        └──────────────┬───────────────┴──────────────────────────────┘
                       │
              ┌────────▼────────┐
              │ report_pipeline │ ◄── shared CLI/UI run boundary
              └────────┬────────┘
                       │
              ┌────────▼────────┐
              │ claude_analyst  │ ◄── prompt builder + two-pass Claude review
              └────────┬────────┘
                       │ recommendation dict
              ┌────────▼────────┐
              │ report_quality  │ ◄── 7-layer quality gate
              └────────┬────────┘
                       │
              ┌────────▼────────┐
              │ report_generator│ ◄── markdown + CSV + log JSON
              └────────┬────────┘
                       │
   ┌───────────────────┼───────────────────┐
   ▼                   ▼                   ▼
Streamlit          Desktop (Tk)      Textual TUI
ui/streamlit_app   src/desktop_app.py ui/textual_app
```

Each box maps to one module under `src/`. Every transformation is a
pure function that takes a dict and returns a dict — except for the
side-effecting layers at the edges (Wealthsimple CSV read; report
write; Claude API call).

## Module map

| Module | Purpose |
|---|---|
| **Pipeline core** | |
| `src/report_pipeline.py` | Canonical report run service used by CLI-adjacent UIs; returns structured artifacts |
| `src/main.py` | CLI entry point and compatibility wrapper around the report pipeline |
| `src/portfolio_loader.py` | Wealthsimple CSV → portfolio dict (handles fractional shares, multi-currency, CDR cross-listings) |
| `src/market_data.py` | yfinance prices, sector lookup, technical indicators |
| `src/enriched_data.py` | Phase 1 (parallel) + Phase 2 (sequential) external enrichment dispatcher |
| `src/claude_analyst.py` | Prompt construction, two-pass Claude review, JSON parsing, recommendation normalisation |
| `src/report_quality.py` | The 7-layer quality gate (catalyst, stale-position, thesis decay, trailing stop, VIX regime, conviction sizing, drawdown) |
| `src/data_confidence.py` | Shared quote/source/catalyst/readiness trust summary for reports and UIs |
| `src/report_generator.py` | Markdown + CSV + JSON log output |
| `src/recommendation_sizing.py` | Deterministic share/fraction sizing for SELL/TRIM |
| **API clients (all observability-logged)** | |
| `src/finnhub_client.py` | Earnings calendar, analyst recommendations, news sentiment |
| `src/polygon_client.py` | Stock snapshot, prev-day OHLCV + VWAP |
| `src/alpha_vantage_client.py` | News sentiment, earnings calendar (rate-limited) |
| `src/twelve_data_client.py` | Real-time quotes (esp. Canadian tickers) |
| `src/fred_client.py` | Rates, yield curve, CPI, VIX, CAD/USD spot |
| `src/coingecko_client.py` | BTC/ETH, Fear & Greed Index |
| `src/cache.py` | Pickle-based on-disk cache (with structured-log degradations) |
| **Learning loop (v1.16)** | |
| `src/backtester.py` | Past-recommendation evaluation, `reliability_diagram`, walk-forward windows (v1.18), conviction-stratified sizing multipliers |
| `src/decision_journal.py` | User-decision recording + scorecard with per-horizon edge (v1.16) |
| `src/drift_tracker.py` | Action / conviction / thesis-text drift detection between sessions |
| `src/thesis_tracker.py` | Thesis verdict evaluation (materialized / partial / not_yet / invalidated) |
| `src/position_aging.py` | Position-age buckets (fresh / core / mature / aged / stale) |
| `src/trailing_stops.py` | Trailing-stop trigger logic |
| **Observability (v1.17)** | |
| `src/observability.py` | Structured JSON-lines log with redaction + rotation |
| `src/performance_history.py` | Portfolio time-series from recommendation logs (Sharpe, max-DD, beta/alpha vs SPY) |
| **Productisation (v1.19)** | |
| `src/onboarding.py` | First-run wizard state machine |
| `src/cost_tracker.py` | Anthropic spend log + monthly budget enforcement |
| `src/preflight.py` | Doctor command, update/API/CSV/budget/release checks, and no-spend demo smoke test |
| `src/workspace_export.py` | Sanitised zip export of the user's workspace |
| `src/notifications.py` | Cross-platform desktop notifications (macOS osascript / Linux notify-send / Windows BurntToast) |
| `src/scheduling.py` | Per-user launchd / Task Scheduler / cron installer |
| **UI** | |
| `ui/streamlit_app.py` | Web dashboard for Dashboard, Buy Signals, reports, runs, history, performance, backtesting, journal, learning, diagnostics, scheduling, and editing |
| `src/desktop_app.py` | Embedded Tkinter dashboard implementation with native menu bar |
| `ui/textual_app.py` | Terminal UI |
| `src/app_gui.py` | Native launcher (PyInstaller entry) |
| `src/ui_launcher.py` | Shell launcher used by `./run.sh` |
| `src/ui_theme.py` | Shared palette + HTML helpers + Streamlit CSS bundle |
| `src/ui_support.py` | UI-facing data aggregators (`learning_view`, `diagnostics_view`, `decision_scorecard_summary`, preflight surfaces, etc.) |
| **Infra** | |
| `src/updater.py` | GitHub Releases auto-update + checksum verification |
| `src/changelog_utils.py` | CHANGELOG section parser (used by CI release workflow) |

## Data flow per session

1. **Load** — `portfolio_loader.parse_holdings_csv` reads the CSV (or
   bundled sample in demo mode), normalises ticker symbols, infers CDR
   cross-listings, computes sector/exposure aggregates.
2. **Enrich** — `enriched_data.fetch` dispatches to:
   - **Phase 1** (parallel): yfinance prices, fee snapshot, Polygon
     snapshot, Twelve Data quotes, fast Finnhub calls
   - **Phase 2** (sequential, rate-limited): Alpha Vantage news +
     earnings calendar, CoinGecko risk signal, FRED macro context
3. **Score** — `backtester.run_backtest` reads
   `data/recommendations_log/*.json`, replays past recommendations
   against actual prices, produces hit rates, Sharpe, max-DD, reliability
   diagram, walk-forward windows, and conviction-stratified sizing
   multipliers.
4. **Drift** — `drift_tracker.compute_drift` compares this session's
   recommendations to the previous session's: action flips, conviction
   jumps, sign flips, thesis-text drift.
5. **Prompt** — `claude_analyst.build_prompt` assembles a single user
   message with: portfolio, market data, news, fee snapshot, backtest
   track record, decision-journal scorecard, drift block, thesis
   verdicts. Cached with prompt caching (1-hour TTL on system prompt).
6. **Two-pass review** — `claude_analyst.call_claude`:
   - **Pass 1** — generate raw recommendation
   - **Quality gate** — `report_quality.apply_quality_gates` (7 layers)
   - **Pass 2** — Claude reviews its own output with the quality
     warnings + drift surfaced, can revise actions
7. **Normalise** — `claude_analyst.normalize_recommendation` snaps
   `time_horizon` to canonical Rule-20 values, swaps inverted price
   targets, auto-fills missing entry/exit plans, validates actions.
8. **Size** — `recommendation_sizing.apply_trade_sizes` computes
   deterministic share counts for SELL/TRIM (the Claude prompt deals in
   percentages; we materialise them).
9. **Confidence** — `data_confidence.build_data_confidence` summarizes
   quote freshness, source coverage, catalyst coverage, warning counts,
   and readiness so reports and UIs can show the same trust signal.
10. **Render** — `report_generator.generate_markdown` writes the
   user-facing report; `save_report` puts it in `reports/`;
   `save_recommendations_csv` writes the structured CSV.
11. **Record** — write the JSON log to
    `data/recommendations_log/`, seed new entries into the decision
    journal, append the cost record to `data/cost_log.jsonl`, fire any
    matching notification channels.

## The 7-layer quality gate

`report_quality.apply_quality_gates` runs after the model's first pass:

1. **Catalyst** — downgrade BUY/ADD that lacks a verified catalyst to
   HOLD-watch.
2. **Stale position** — force TRIM on positions ≥ 2y old not already
   SELL/TRIM.
3. **Thesis decay** — force SELL on positions with 4+ consecutive
   `not_yet` thesis reviews.
4. **Trailing stop breach** — force TRIM and tighten `stop_loss_pct`
   when the stop is breached.
5. **VIX regime sizing** — scale `invest_amount_usd` by a
   VIX-derived multiplier.
6. **Conviction-stratified sizing** — apply the per-conviction
   multipliers learned by the backtester (Sharpe-dampened in v1.16).
7. **Drawdown circuit breaker** — halve sizing when the portfolio is in
   a deep drawdown.

Each gate is independent and accumulates a `quality_warnings` list that
the model sees in pass 2.

## The learning loop

```
                Past recommendations
                        │
                        ▼
            ┌───────────────────────────┐
            │     backtester.run_       │
            │  Sharpe-dampened sizing,  │
            │  reliability diagram,     │
            │  walk-forward windows     │
            └─────────────┬─────────────┘
                          │ sizing_multipliers_by_conviction
                          │ reliability + walk_forward
                          ▼
            ┌───────────────────────────┐
            │  claude_analyst (next     │
            │  session): track-record   │
            │  block in the prompt,     │
            │  calibration nudges,      │
            │  walk-forward stability   │
            └─────────────┬─────────────┘
                          │
                          ▼
                   New recommendations
                          │
                          ▼
            ┌───────────────────────────┐
            │ decision_journal: seeded  │
            │ from this run, user marks │
            │ executed / ignored later  │
            └─────────────┬─────────────┘
                          │
                          ▼
            ┌───────────────────────────┐
            │  scorecard: per-horizon   │
            │  user vs model edge       │
            └─────────────┬─────────────┘
                          │ by_horizon block
                          ▼
                  Back into the prompt
```

The flow is closed: every report informs the next, both via the
backtester (objective track-record) and the decision journal (user's
actual edge per holding period). The Learning tab visualises this
state.

## Storage layout

```
.
├── config/
│   ├── settings.json           # User-editable: model, budgets, FX, notifications
│   ├── watchlist.json          # Tickers to track without holding
│   ├── portfolio.json          # Fallback portfolio when no CSV is uploaded
│   └── .env                    # API keys (never logged, never zipped)
├── data/
│   ├── recommendations_log/    # One JSON per session — the system's memory
│   ├── samples/                # Bundled demo data (CSV + cached Claude response)
│   ├── decision_journal.json   # User decisions vs model recommendations
│   ├── thesis_log.json         # Thesis verdicts per position
│   ├── cost_log.jsonl          # Per-run Anthropic spend
│   └── .cache/                 # Pickle cache for yfinance/news
├── reports/                    # Markdown reports + recommendation CSVs
├── exports/                    # User-triggered workspace zips
├── logs/diagnostics.jsonl      # Structured-log API degradations (v1.17)
└── temporary_upload/           # User-dropped Wealthsimple CSVs
```

## Design tenets

These show up in every commit message and PR review:

1. **Never silently swallow.** Every `except Exception:` either
   recovers explicitly OR logs a structured event via `observability`.
2. **Additive schema.** Adding a field is fine; renaming or removing
   one breaks downstream consumers (reports, CSVs, the Learning tab,
   the Claude prompt). Bump a major version for breaking changes.
3. **Tests with every feature.** Every new module ships with a test
   file. The default verdict is "if it isn't tested, it doesn't ship".
4. **Production = default-safe.** New behaviour is opt-in until proven
   (budget cap defaults to 0; notifications default channels-on but
   gracefully no-op when the OS backend is missing).
5. **Tools, not toys.** Every UI surface should answer a real
   user question (`Diagnostics` answers "why is this slow?",
   `Performance` answers "how am I doing?", `Learning` answers "is my
   conviction calibrated?"). Avoid features that look impressive but
   don't change a decision.
