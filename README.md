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
- ✅ **Intelligent Sizing** — Investment amounts ($50–$700 per session) based on conviction and budget
- ✅ **Hold Tiers** — HOLD recommendations labeled as watch / keep / add-on-dip for clarity
- ✅ **Earnings Alerts** — Flags tickers with earnings within 7 days; adjusts risk profile
- ✅ **Risk Controls** — Entry zones, stop-loss, take-profit, catalyst verification, and manual-review flags per recommendation
- ✅ **Exit Planning** — Target exit dates and Bear Case / Bull Case ranges for every trade
- ✅ **Portfolio Risk Dashboard** — Beta, volatility, drawdown estimate, company exposure rollups, and hedge suggestions
- ✅ **8 Time Horizons** — Intraday / next session / 1-3 trading days / 1-2 weeks / 1-3 months / 3-6 months / 6-12 months / 12-36 months
- ✅ **6 Enrichment APIs** — Parallel data from Finnhub, Polygon, Twelve Data, FRED, CoinGecko (+ optional Alpha Vantage)
- ✅ **Fee-Aware** — Refuses to recommend trades below the fee hurdle (default 0.5% net expected return)
- ✅ **Conviction Scoring** — 1-10 scale; scores < 6 automatically become HOLD recommendations
- ✅ **Live Market Data** — Quote timestamp, previous close, pre/after-market moves, day range, quote source, 10-month history, PE ratios, FCF yield, margins, dividends, 52-week highs/lows via yfinance
- ✅ **Recent News** — Pulls last 7 days of headlines per ticker from Yahoo Finance
- ✅ **Trade History Context** — Loads your recent Wealthsimple trades to avoid whipsawing
- ✅ **Triple Output** — Markdown report + CSV table + JSON log for backtesting
- ✅ **Three Interface Options** — Original CLI remains default, with optional Streamlit dashboard and Textual terminal UI
- ✅ **Model Choice** — Pick Sonnet 4.6 (~$0.30-$0.55/run typical two-pass range) or Opus 4.7 (higher cost, deeper analysis) per session
- ✅ **Fast Parallel Fetching** — Concurrent API requests with caching and graceful degradation

---

## ✨ What's New in v1.8.0 (May 6, 2026)

**P2 polish — execution quality and weekly action density.**

- **Trailing stops** — stops automatically tighten as positions appreciate (+10% → breakeven, +20% → 8% trail, +40% → 12% trail). Breached stops auto-generate TRIM regardless of Claude's output. Locks in gains without manual intervention.
- **Sector rotation rhythm** — sector ETFs ranked by 1-month relative strength. Detects leadership shifts vs the previous session ("rotating in" / "rotating out"). Generates timely rotation trades aligned with your weekly cadence.
- **Tranched entry/exit plans** — every BUY/ADD now ships with a 3-step entry plan (40% now / 30% on pullback / 30% on confirmation). Same for SELL/TRIM exits. Lowers average entry by ~0.5–1% historically and turns each trade idea into 3 weekly small actions.
- **Live USD→CAD FX rate** from FRED DEXCAUS — replaces the static 1.37 assumption (real range: 1.32–1.42). CAD-denominated holdings now valued accurately.
- **Fixed:** News cache now date-keyed (no more stale headlines on the afternoon run); drift tracker now skips quick re-runs and prefers same-session-type from the previous trading day.

31 new tests, 111 total, all passing.

## ✨ What's New in v1.7.0 (May 6, 2026)

**Strategy alignment — every recommendation now respects your trading rules deterministically.**

- **Position aging** — Every holding is classified `fresh`/`core`/`mature`/`aged`/`stale`. Mature positions (6-12 months without a fresh catalyst) auto-drop conviction by 1; stale (>2 years) are force-converted to TRIM regardless of Claude's output.
- **VIX-regime sizing** — `invest_amount_usd` automatically scales by VIX: 0.85× when 15–25, 0.6× when 25–35, 0.4× above 35.
- **Drawdown circuit breaker** — When portfolio is ≥6% off its 30-day peak: ADDs halve, BUYs become HOLD-watch, and weak HOLDs (conviction <7) get forced to watch.
- **Conviction sizing from your actual hit rates** — After 3+ mature trades per conviction bucket, position sizes follow your real edge, not just Claude's conviction prior.
- **Catalyst windows** — Earnings ±5 days = lockdown; T-30 to T-5 = setup window; T+1 to T+3 = post-earnings drift. Plus session-level FOMC/CPI/NFP tags pre-position you 1-2 days before macro events.
- **Cache pricing fixed** — Code uses 1-hour cache TTL; pricing table was billing at 5-minute rates (under-reported costs by ~25%).

41 new tests, 80 total, all passing.

## ✨ What's New in v1.6.0 (May 2026)

**Native App Packaging + Unified Launcher:** Run tech_stock as a native macOS or Windows application — no terminal required.

- **`./run.sh` Unified Entry Point** — Running `./run.sh` with no arguments now shows an interactive menu (CLI / Streamlit / Textual). Existing callers with arguments (e.g. `./run.sh morning`) still work unchanged.
- **Native macOS App** — `build_macos.sh` builds `dist/tech_stock.dmg` using PyInstaller. Double-click to install; dark-themed tkinter launcher window opens with three one-click buttons.
- **Native Windows App** — `build_windows.bat` builds `dist\tech_stock\tech_stock.exe`. Optionally wrap in an Inno Setup installer via `installer_windows.iss`.
- **GitHub Actions Release CI** — Push a version tag (`git tag v1.0.0 && git push --tags`) and GitHub Actions automatically builds both the `.dmg` and Windows `.exe`, then uploads them as release artifacts.
- **Backtest On-Demand** — Backtest tab no longer blocks app startup; yfinance price fetches now happen only when you click "Run backtest".
- **Report Rendering Fixed (Textual)** — Today's Report and History tabs now use the Textual `Markdown` widget (was `RichLog` — headings and tables previously appeared as raw text).

## ✨ What's New in v1.5.1 (April 30, 2026)

**Optional UI Layer:** Added and upgraded two extra interfaces without changing the original way to run the program.

- **Original CLI Preserved** — `python src/main.py` and `./run.sh` still behave as before
- **Streamlit Dashboard** — Run reports from a browser UI with live progress, CSV upload/preview, first-class dashboard metrics, markdown history/compare, structured backtests, downloads, connectivity checks, and config JSON validation
- **Textual TUI** — Run reports from a terminal dashboard with live progress, dashboard tables, history, structured backtest tables, CSV discovery helpers, keyboard shortcuts, connectivity checks, and portfolio/config editing
- **UI Launcher** — `./run.sh` (or `./run-ui.sh`) lets you choose CLI, Streamlit, or Textual from one menu
- **Shared UI Runtime** — Both UIs call the same `src.main.run()` pipeline as the CLI, with auto-open disabled and generated artifact paths returned to the UI
- **Latest JSON Dashboard** — Optional UIs surface `risk_dashboard`, `quality_warnings`, `priority_actions`, `hedge_suggestions`, `drift_vs_previous`, and Claude cost/tokens without requiring a long markdown scroll

## ✨ What's New in v1.4.1 (April 30, 2026)

**Runtime Stabilization:** Updated after a successful full portfolio run using the April 29 holdings and activities CSVs.

- **Claude Output Budget** — Default `claude_max_tokens` is now `16000`, which avoided JSON truncation while keeping the two-pass report feasible.
- **Compact Recommendation Contract** — Rule 32 caps Claude at 12 recommendation rows focused on actionable trades and material risks; lower-signal tickers move to watchlist/warnings.
- **Schema Resilience** — Missing required per-recommendation fields from Claude are normalized to safe defaults before schema validation, so one incomplete row does not kill the run.
- **Correct Market Phase** — Overnight runs now label the context as "outside regular market hours — before next open" instead of pre-close.
- **Observed Full-Run Cost** — Latest successful Sonnet two-pass run used 43,079 tokens and cost about `$0.50`; smaller portfolios or cached/shorter outputs may cost less.

## ✨ What's New in v1.4.0 (April 30, 2026)

**Unified Plan Follow-Through:** Applied the remaining quality-plan items around calibration, data enrichment, report UX, and Claude cost/performance behavior.

- **Critical Actions Section** — Top-of-report checklist now consolidates high/medium quality warnings, manual catalyst reviews, leveraged ETF duration risk, and major drift items
- **Stronger Quality Gates** — Catalyst gating now independently detects near-term earnings from enrichment data; hard downgrades force HOLD-watch and cap conviction at 5
- **Range And Decision Checks** — Reversed Bear/Bull ranges remain visible as warnings after normalization, near-term range mismatches check both sides, and missing decision-tree language is flagged
- **Sharper Track-Record Calibration** — Prompt now caps high conviction when historical conviction/action buckets have weak hit rates, and the backtest summary includes per-ticker stats plus recent realized examples
- **Richer Market Data** — Adds premarket/after-hours moves, FCF yield, gross/operating margins, dividend yield, and ex-dividend dates where yfinance provides them
- **More Enrichment Signals** — Finnhub analyst upgrade/downgrade events, deterministic macro calendar estimates for NFP/CPI/FOMC verification, and optional Polygon current snapshot fields
- **Leveraged ETF Decay Estimate** — Daily-reset ETF warnings now include holding days plus an estimated volatility-decay drag when 20-day volatility is available
- **Previous Session Execution Check** — The report compares prior actionable recommendations with recent activities CSV rows so you can see what was or was not executed
- **Data Freshness Footnotes** — Quote-quality section explains provider quote vs daily-close fallback semantics before order entry
- **Claude Cost/Performance** — Repeated user context is cache-marked for the second pass, and Opus can use extended thinking via `enable_opus_extended_thinking`

## ✨ What's New in v1.3.0 (April 30, 2026)

**Major Upgrade:** Deterministic quality gates, two-pass review, portfolio risk analytics, richer report structure, and CI coverage

- **Report Quality Warnings** — Stale quotes, quote mismatches, missing catalysts, invalid horizons, and oversized exposures are surfaced near the top of the report
- **Always-On Second Pass** — Claude revises its first JSON using quality warnings, drift, and previous-session context before final output
- **Risk Controls** — Each recommendation now carries entry zone, stop-loss, take-profit, catalyst verification, catalyst source, and manual-review fields
- **Portfolio Risk Dashboard** — Adds beta, volatility, drawdown estimate, top-3 concentration, correlated pairs, company-level exposure rollups, and hedge suggestions
- **Richer Deterministic Market Data** — Adds SMA cross, ATR(14), 5/20-day volatility, fundamentals, benchmark beta inputs, and sector/cross-asset context
- **Structured Enrichment Degradation** — External API failures are recorded and rendered instead of silently disappearing
- **Priority Actions** — "Do This Today" ranked list replaces guesswork about order of execution
- **Investment Sizing** — Exact USD amounts per trade ($50–$700 range), scaled by conviction
- **Hold Tiers** — HOLD recommendations now labeled (watch / keep / add_on_dip) for clarity on next steps
- **Earnings Alerts** — ⚠️ Automatically flags tickers with earnings within 7 days
- **Exit Planning** — Every trade includes target exit date and Bear Case / Bull Case expected ranges
- **6 Enrichment APIs** — Analyst consensus, insider activity, macro signals, crypto context, and previous-session Polygon VWAP context
- **Extended Time Horizons** — Now supports 3-6 months, 6-12 months, 12-36 months for medium-term thesis
- **Improved Setup** — `API_KEYS.txt` as the easy-to-find alternative to `.env` for new users
- **Better CSV Export** — Trader-facing columns for Hold Tier, Invest USD, Bear/Bull Case, risk controls, catalyst gate, and quote audit fields
- **Optional Slow Data Paths** — Alpha Vantage and options implied-move lookups are disabled by default; enable them only when needed
- **Test Suite + CI** — Pytest coverage and GitHub Actions now run on push and pull requests

---

## 🚀 Getting Started

### Prerequisites

- **Python 3.11+** (via Homebrew on macOS: `brew install python@3.11`)
- **Anthropic API key** (from https://console.anthropic.com/)
- **Wealthsimple Premium account** with a USD trading account
- **Optional UI dependencies** are included in `requirements.txt` (`streamlit` and `textual`)

### Installation

```bash
# Clone or navigate to the project
cd tech_stock

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
# This installs the CLI/runtime dependencies plus optional Streamlit/Textual UI packages

# Set up API keys (two options below)
```

**Option A: Easy Way (Recommended for new users)**
```bash
cp API_KEYS.template.txt API_KEYS.txt
# Open API_KEYS.txt in your editor and paste your API keys
# (See signup links inside for each service)
```

**Option B: Advanced Way (.env file)**
```bash
cp .env.example .env
# Edit .env and paste all your API keys
```

### First Run — Choose Your Interface

```bash
source .venv/bin/activate
chmod +x run.sh run-ui.sh   # make executable (first time only)
./run.sh
```

You'll see a menu:
```
  [1]  CLI             — Terminal, fastest, pass session flags directly
  [2]  Streamlit UI    — Web dashboard, open in browser, full feature set
  [3]  Textual TUI     — Rich terminal UI, keyboard-driven, no browser needed

  Choose [1/2/3, Enter = 1]:
```

**No terminal?** Download `tech_stock.dmg` from the [Releases page](https://github.com/pouyafath/tech_stock/releases) and double-click — a native launcher window opens with the same three choices.

**Shortcut — skip the menu:**
```bash
./run.sh morning          # → CLI, morning session
./run.sh 2                # → Streamlit (opens browser automatically)
./run.sh 3                # → Textual TUI
```

**Original interactive CLI (unchanged from before):**
```bash
python src/main.py
```

You'll be walked through 5 questions:

```
Session type (morning/afternoon) [Enter = morning]:
1. How much USD would you like to invest today? $500
2. How much CAD would you like to invest today? $1000
3. Holdings CSV detected: /Users/you/Downloads/holdings-report-2026-04-24.csv
   Is this correct? (Y/N): Y
4. Activities CSV detected: /Users/you/Downloads/activities-export-2026-04-24.csv
   Is this correct? (Y/N, or Enter to skip): Y
5. Which model would you like to use?
   [1] Sonnet 4.6 — ~$0.30-$0.55/run typical two-pass range (recommended for daily use)
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

| Command | What happens |
|---------|-------------|
| `./run.sh` | Interactive menu — pick CLI / Streamlit / Textual |
| `./run.sh morning` | Skip menu → CLI, morning session |
| `./run.sh afternoon --model opus` | Skip menu → CLI, Opus model |
| `./run.sh 2` | Skip menu → Streamlit (browser opens automatically) |
| `./run.sh 3` | Skip menu → Textual TUI |

All three interface options call the **same report engine** (`src/main.run()`). UI runs disable automatic file opening and return the generated markdown/CSV/JSON paths inside the interface.

### Streamlit Dashboard

```bash
streamlit run ui/streamlit_app.py
```

Then open the local URL Streamlit prints, normally `http://localhost:8501`.

Tabs:
- **Dashboard** — Shows latest JSON-log metrics for risk, priority actions, quality warnings, hedge suggestions, drift, cost/tokens, and API connectivity
- **Today's Report** — Renders the latest markdown report with `st.markdown`
- **Run Report** — Select session/model/budgets, upload or point to Wealthsimple CSVs, preview holdings before spending Claude tokens, and trigger the same report pipeline as CLI mode with live progress
- **History** — Browse previous markdown reports from `reports/`, filter/search by filename, and compare two reports side by side
- **Backtest** — View metrics, action/conviction/ticker buckets, bar charts, and recent realized examples
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

The Textual app runs fully in the terminal and provides the same workflow tabs as the Streamlit dashboard. Long reports are shown in scrollable terminal panes, which is more reliable for very large markdown reports than terminal markdown rendering in the currently pinned Textual version.

Useful keyboard shortcuts:
- `r` refreshes the active tab
- `Ctrl+R` starts a report run
- `Ctrl+S` saves the JSON editor when the content is valid

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

**Windows:**
```bat
build_windows.bat         :: builds dist\tech_stock\tech_stock.exe
```
Distribute the entire `dist\tech_stock\` folder. Users double-click `tech_stock.exe`.

### Pre-built Releases (GitHub Actions)

Push a version tag to trigger automatic builds for both platforms:
```bash
git tag v1.0.0 && git push --tags
```
GitHub Actions builds `.dmg` (macOS runner) and `.exe` (Windows runner) and attaches them to a GitHub Release. Download from the [Releases page](https://github.com/pouyafath/tech_stock/releases).

### What the App Does

On launch the native app shows a dark-themed launcher window (built with tkinter — no extra dependency):
- **Streamlit Web UI** — starts the Streamlit server and opens your browser
- **Textual Terminal UI** — opens the keyboard-driven terminal dashboard
- **Command-Line (CLI)** — opens a terminal and runs the original CLI

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
**Period:** Select last **3 months**

Contains your trade history:
- Dates, tickers, BUY/SELL, quantity, price
- Commissions, net cash

The app reads this to:
- Understand recent trading patterns
- Avoid "whipsawing" (recommend reversing a recent trade without new catalyst)
- Provide context on conviction changes since your last trade

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
Ticker,Action,Hold Tier,Conviction,Invest USD,Expected Stock Move %,Expected Benefit of Action %,Net Expected %,Time Horizon,Exit Target,Bear Case %,Bull Case %,Stop Loss %,Take Profit %,Catalyst Verified,Catalyst Source,Manual Review,Quote,Previous Close,Quote Time UTC,Quote Source,Earnings Alert,Thesis
NVDA,ADD,,8,$500,+15.00%,+14.89%,+14.89%,3-6 months,Jul 2026,-8%,+18%,-7%,+18%,YES,Finnhub earnings/news,NO,210.50 USD,205.12 USD,2026-04-29T20:00:01+00:00,yfinance:regularMarketPrice,,Core AI infrastructure play...
SOXL,SELL,,9,,-20.00%,+19.70%,+19.70%,next session,Apr 2026,-30%,-10%,-6%,+0%,NO,,YES,117.97 USD,109.56 USD,2026-04-29T20:00:00+00:00,yfinance:regularMarketPrice,,Leveraged ETF decay risk...
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
  "claude_max_tokens": 16000,
  "claude_timeout_seconds": 240,
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
  "news_lookback_days": 7,
  "history_months": 10
}
```

**Key settings:**

| Key | Default | Purpose |
|-----|---------|---------|
| `budget_cad` | 3000 | Available CAD to deploy (overridden per run) |
| `risk_tolerance` | "aggressive" | "moderate" for conservative recommendations |
| `claude_model` | "claude-sonnet-4-6" | "claude-sonnet-4-6" (fast) or "claude-opus-4-7" (thorough) |
| `claude_max_tokens` | 16000 | Max output tokens for the structured JSON response; current default balances avoiding truncation with run time/cost |
| `claude_timeout_seconds` | 240 | Hard timeout for each Claude API call |
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
| `news_lookback_days` | 7 | How far back to fetch news headlines |
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

### Data Flow

```
Wealthsimple CSVs
    ↓
[Portfolio Loader] → Holdings dict
[Activity Loader] → Recent trades
    ↓
[Market Data]      ┐ (parallel fetching via ThreadPoolExecutor)
[News Fetcher]     ├→ yfinance → prices, history, PE, headlines, news
[Fee Calculator]   ┘
    ↓
[Portfolio Analytics] → risk dashboard, company exposure, hedge suggestions
    ↓
[Claude Analyst] → first-pass JSON → quality gates + drift → second-pass JSON
    ↓
[Report Generator] → markdown + CSV + JSON log
    ↓
[Optional UIs] → Streamlit browser dashboard / Textual terminal dashboard
```

**Performance:** Market data, news, and enrichment calls run in parallel where possible. Runtime depends on portfolio size, API coverage, cache state, and the two Claude passes. Slow optional sources such as options implied-move lookup are disabled by default.

### Module Overview

**Shared Utilities** (centralized, single source of truth):

| Module | Purpose |
|--------|---------|
| `config.py` | Load and manage settings from `config/settings.json` |
| `constants.py` | Shared constants: leveraged ETF leverage map, company/share-class groups, DEDUP_PAIRS, SKIP_MARKET_DATA, CDR_EXCHANGES |
| `_utils.py` | Helper functions: `safe_float()`, `clean_csv_row()`, `parse_session_filename()` |

**Data Loading & Calculation**:

| Module | Purpose |
|--------|---------|
| `portfolio_loader.py` | Parse Wealthsimple Holdings CSV |
| `activity_loader.py` | Parse Wealthsimple Activities CSV (trade history) |
| `market_data.py` | Fetch live prices, pre/after-market fields, history, fundamentals, dividends, and indicators via yfinance |
| `news_fetcher.py` | Fetch recent news headlines (parallel fetching with ThreadPoolExecutor) |
| `fee_calculator.py` | Model Wealthsimple fees + bid-ask spreads |
| `portfolio_analytics.py` | Company exposure rollups, volatility, beta, drawdown, correlation, and hedge suggestions |

**Enrichment & Analysis**:

| Module | Purpose |
|--------|---------|
| `enriched_data.py` | Orchestrate 6 enrichment APIs in parallel (Finnhub, Polygon, Twelve Data, FRED, CoinGecko) + optional sequential Alpha Vantage |
| `finnhub_client.py` | Fetch analyst consensus, upgrade/downgrade events, earnings calendar, insider activity, news sentiment |
| `polygon_client.py` | Fetch previous-day OHLCV + VWAP signals, plus optional current snapshot fields |
| `twelve_data_client.py` | Fetch real-time quotes + earnings dates |
| `fred_client.py` | Fetch macro context (Fed Funds, inflation, yield curve, VIX regime) and deterministic event-calendar estimates |
| `coingecko_client.py` | Fetch BTC price, Fear & Greed Index, macro risk signal |
| `alpha_vantage_client.py` | Fetch news sentiment (thread-safe rate limiter; optional, disabled by default) |

**Analysis & Output**:

| Module | Purpose |
|--------|---------|
| `claude_analyst.py` | 32-rule system prompt, build enriched prompt, run two Claude passes, parse JSON response with sizing, catalyst, risk-control, hedge, and priority-action fields |
| `report_quality.py` | Deterministic quality warnings and hard gates for stale quotes, missing catalysts, risk controls, and sizing issues |
| `backtester.py` | Evaluate mature recommendations by action, conviction, ticker, and recent realized examples for calibration |
| `report_generator.py` | Format markdown + CSV with priority actions, quality warnings, risk dashboard, hold tiers, earnings badges, risk controls, and Bear/Bull ranges |
| `main.py` | CLI entry point, interactive setup, API key loading (API_KEYS.txt first, then .env), enrichment orchestration, risk analytics, and CSV export |
| `ui_launcher.py` | Shell menu for choosing the original CLI, Streamlit, or Textual; called by `run.sh` |
| `ui_support.py` | Shared helpers for UI progress streaming, report/log discovery, latest-log dashboards, holdings preview, JSON validation, connectivity checks, and canonical report runs |
| `app_gui.py` | Native tkinter launcher window used by the PyInstaller `.app`/`.exe` bundle |

**Optional UI Entry Points**:

| File | Purpose |
|------|---------|
| `ui/streamlit_app.py` | Browser dashboard for CSV upload, report generation, markdown viewing, history, backtest, and JSON config editing |
| `ui/textual_app.py` | Terminal dashboard for the same workflow using Textual widgets and scrollable panes |

**Packaging**:

| File | Purpose |
|------|---------|
| `tech_stock.spec` | PyInstaller build specification (data files, hidden imports, macOS `.app` bundle) |
| `build_macos.sh` | One-command macOS build: installs deps → PyInstaller → `.app` → `.dmg` |
| `build_windows.bat` | One-command Windows build: installs deps → PyInstaller → `.exe` |
| `installer_windows.iss` | Optional Inno Setup script for a polished Windows installer |
| `pyinstaller_hooks/` | Custom hooks to ensure Streamlit static assets are bundled |
| `.github/workflows/build_release.yml` | CI release workflow: tags trigger `.dmg` + `.exe` builds |

### Claude System Prompt (32 Rules)

Claude receives a detailed system prompt with **32 strategic rules** governing analysis and output structure:

**Input Data Claude Gets:**
1. Portfolio snapshot — all holdings with cost basis, current value, P&L, unrealized gains (from portfolio_loader)
2. Market data — current price, pre/after-market moves, 1d/5d/1mo changes, PE, FCF yield, margins, dividends, 52w highs/lows, last 5 closes (parallel fetch from market_data)
3. Recent news — last 7 days of headlines per ticker (parallel fetch from news_fetcher)
4. **Enriched intelligence** — analyst consensus, earnings calendars, insider activity, sentiment, macro context (from enriched_data.py)
5. Fee snapshot — one-way and round-trip costs per ticker (from fee_calculator)
6. Recent trades — your trading activity last 90 days (from activity_loader, if provided)
7. Session type — "morning" (pre-open) or "afternoon" (intraday + EOD positioning)
8. Watchlist alerts — target entry/exit prices for monitored tickers (from config/watchlist.json)
9. Quality warnings, previous-session drift/execution context, risk dashboard, company exposure rollup, and track-record calibration stats

**Output Rules (Examples from the 32):**
- **Rule 14 (Track Record Calibration):** Cap or reduce conviction when similar historical action/conviction buckets have weak returns or hit rates
- **Rule 15 (Earnings Alert):** If earnings within 7 days, set `earnings_alert=true` and lead with "⚠️ EARNINGS [DATE]"
- **Rule 17 (Enrichment Citation):** Cite analyst consensus, EPS beat streaks, insider activity in thesis statements
- **Rule 18 (Investment Sizing):** Set `invest_amount_usd` based on conviction: 8–10 = 40% of session budget, 7 = 25%, 6 = 15%
- **Rule 19 (Hold Tiers):** Every HOLD gets `hold_tier`: "watch" (conviction ≤5), "keep" (6–7), "add_on_dip" (≥8)
- **Rule 20 (Time Horizons):** Exactly one of: intraday / next session / 1-3 trading days / 1-2 weeks / 1-3 months / 3-6 months / 6-12 months / 12-36 months
- **Rule 21 (Exit Plan):** Every recommendation includes `target_exit_date` (e.g., "Jul 2026") and Bear/Bull range
- **Rule 22 (Buy Signals):** Actively look for BUY opportunities — not just existing portfolio
- **Rule 23 (Priority Actions):** Output `priority_actions` array — ordered "do this today" list by urgency
- **Rule 27 (Risk Controls):** Include entry zone, stop-loss, and take-profit percentages
- **Rule 28 (Catalyst Gate):** BUY/ADD on >5% movers or near-earnings names requires verified catalyst or manual review
- **Rule 31 (Hedge Suggestions):** Include trim/rebalance and optional small inverse-ETF hedges when concentration or beta is high
- **Rule 32 (Compact JSON):** Return at most 12 recommendation rows focused on actionable trades and material risks

The parser also normalizes missing per-row fields such as `action`, `conviction`, `net_expected_pct`, `fee_hurdle_pct`, and `time_horizon` to safe defaults before schema validation. Deterministic quality gates still flag unsupported recommendations after normalization.

**Output JSON Structure:**
```json
{
  "recommendations": [
    {
      "ticker": "NVDA",
      "action": "ADD",
      "conviction": 8,
      "net_expected_pct": 14.89,
      "invest_amount_usd": 500,
      "time_horizon": "3-6 months",
      "hold_tier": null,
      "earnings_alert": false,
      "target_exit_date": "Jul 2026",
      "price_target_low_pct": -8.0,
      "price_target_high_pct": 18.0,
      "risk_controls": {
        "entry_zone_low_pct": -3.0,
        "entry_zone_high_pct": 1.0,
        "stop_loss_pct": -7.0,
        "take_profit_pct": 18.0
      },
      "catalyst_verified": true,
      "catalyst_source": "Finnhub analyst consensus + earnings history",
      "manual_review_required": false,
      "thesis": "Core AI infrastructure. Analyst consensus: 66 analysts STRONG BUY. Beat estimates 4 quarters in a row. Insider buying strong."
    }
  ],
  "priority_actions": [
    {"order": 1, "ticker": "NVDA", "action": "ADD", "rationale": "Core position, good entry"},
    {"order": 2, "ticker": "SOXL", "action": "SELL", "rationale": "Leveraged ETF decay and concentration risk"}
  ],
  "summary": "..."
}
```

---

## 🤔 FAQ

### Q: Sonnet vs Opus — which should I use?

**A:** Sonnet 4.6 covers ~90% of use cases at roughly 20% of the cost. Use **Opus 4.7** when:
- Your portfolio has many positions and the conviction scores feel too uniform
- You want extended thinking enabled (deeper chain-of-thought reasoning)
- You're analysing an unusual macro environment (yield curve inversion, crypto correlation)

Typical costs: Sonnet two-pass ≈ $0.30–$0.55 · Opus two-pass ≈ $1.50–$3.00 depending on portfolio size.

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

**A:** With Sonnet two-pass review, expect roughly `$0.30-$0.55` for a full portfolio run. The latest full run with 31 tracked tickers, enrichment enabled, 12 recommendation rows, and two Claude passes used 43,079 tokens and cost about `$0.50`.
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
This is normal. yfinance news availability varies by ticker and day. The app still generates recommendations based on price action and fundamentals.

### "Claude response parsing failed"
The response was truncated or not valid JSON. The current default `claude_max_tokens` is `16000` and Rule 32 asks Claude to keep recommendations to 12 rows. If this still happens with a very large portfolio or news-heavy run, reduce watchlist scope, disable optional enrichment, or increase `claude_max_tokens` carefully. Higher token caps can raise cost and may make non-streamed Claude responses slower.

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
│   ├── claude_analyst.py        ← 32-rule prompt, two-pass Claude review, JSON parsing
│   ├── report_generator.py      ← Priority actions table, hold tiers, earnings badges, markdown + CSV
│   ├── ui_support.py            ← Shared helpers for UI progress, dashboards, previews, validation, and connectivity
│   └── ui_launcher.py           ← Interface chooser for CLI, Streamlit, and Textual
├── ui/
│   ├── streamlit_app.py         ← Optional browser dashboard
│   └── textual_app.py           ← Optional terminal dashboard
├── src/
│   ├── app_gui.py               ← Native tkinter launcher (used by .app/.exe bundle)
│   └── ui_launcher.py           ← Shell menu wrapper (used by run.sh)
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

This is a personal tool but contributions are welcome. To contribute:

1. Fork the repo
2. Create a feature branch: `git checkout -b feature/your-idea`
3. Make your changes
4. Test thoroughly with your own Wealthsimple account (paper trading recommended)
5. Commit with clear messages: `git commit -m "Add/fix: description"`
6. Push and open a pull request

**Areas for contribution:**
- Support for other brokers (add new fee models)
- Additional output formats (Excel, HTML, Discord webhooks)
- Backtesting framework
- Risk metrics (Sharpe ratio, max drawdown, volatility)
- Mobile notifications

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

**Last updated:** May 2026 — strategy-aligned gates (aging/VIX/drawdown/catalysts/conviction sizing in v1.7.0), then trailing stops + sector rotation + tranched plans + live FX in v1.8.0
**Version:** 1.8.0
**Status:** Production-ready with 13 deterministic quality gates, three interface options, and native app distribution
