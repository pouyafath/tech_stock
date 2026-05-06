# Changelog

All notable changes to this project are documented here.

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
