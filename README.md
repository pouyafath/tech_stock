# tech_stock 📈

> A Claude-powered portfolio advisor for Wealthsimple Premium USD accounts with twice-daily trading recommendations, fee-aware analysis, and conviction scoring.

[![GitHub](https://img.shields.io/badge/GitHub-tech--stock-blue)](https://github.com/pouyafath/tech_stock)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-green)]()
[![Claude API](https://img.shields.io/badge/API-Sonnet%204.6%20%26%20Opus%204.7-orange)]()
[![License](https://img.shields.io/badge/License-MIT-lightgrey)]()

---

## 🎯 Overview

**tech_stock** is an intelligent portfolio advisor that analyzes your Wealthsimple holdings and provides structured trading recommendations twice daily (morning/afternoon sessions). It leverages Claude AI to:

- **Analyze** your portfolio in real-time with live market data
- **Score** each trade idea by conviction (1-10) and net expected return after fees
- **Recommend** specific actions: BUY, ADD, HOLD, TRIM, SELL with thesis statements
- **Calculate** realistic fees (Wealthsimple Premium + USD account bid-ask spreads)
- **Export** recommendations as both markdown reports and CSV tables for easy tracking

### Key Features

✅ **Priority Actions** — "Do This Today" list ordered by urgency (intraday trades first, then short-term)  
✅ **Intelligent Sizing** — Investment amounts ($50–$700 per session) based on conviction and budget  
✅ **Hold Tiers** — HOLD recommendations labeled as watch / keep / add-on-dip for clarity  
✅ **Earnings Alerts** — ⚠️ Flags tickers with earnings within 7 days; adjusts risk profile  
✅ **Exit Planning** — Target exit dates and expected price ranges (low % / high %) for every trade  
✅ **6 Time Horizons** — Intraday / 1-2 weeks / 1-3 months / 3-6 months / 6-12 months / 12-36 months  
✅ **6 Enrichment APIs** — Parallel data from Finnhub, Polygon, Twelve Data, FRED, CoinGecko (+ optional Alpha Vantage)  
✅ **Fee-Aware** — Refuses to recommend trades below the fee hurdle (default 0.5% net expected return)  
✅ **Conviction Scoring** — 1-10 scale; scores < 6 automatically become HOLD recommendations  
✅ **Live Market Data** — Real-time prices, 3-month history, PE ratios, 52-week highs/lows via yfinance  
✅ **Recent News** — Pulls last 7 days of headlines per ticker from Yahoo Finance  
✅ **Trade History Context** — Loads your recent Wealthsimple trades to avoid whipsawing  
✅ **Triple Output** — Markdown report + CSV table + JSON log for backtesting  
✅ **Model Choice** — Pick Sonnet 4.6 (~$0.09/run, fast) or Opus 4.7 (~$0.45/run, deeper analysis) per session  
✅ **Fast Parallel Fetching** — Concurrent API requests (18 tickers + enrichment in ~15s vs ~120s serial)  

---

## ✨ What's New in v1.2.0 (April 29, 2026)

**Major Upgrade:** Professional-grade signals, actionable sizing, and clear exit plans

- **Priority Actions** — "Do This Today" ranked list replaces guesswork about order of execution
- **Investment Sizing** — Exact USD amounts per trade ($50–$700 range), scaled by conviction
- **Hold Tiers** — HOLD recommendations now labeled (watch / keep / add_on_dip) for clarity on next steps
- **Earnings Alerts** — ⚠️ Automatically flags tickers with earnings within 7 days
- **Exit Planning** — Every trade includes target exit date and expected price range (low % / high %)
- **6 Enrichment APIs** — Analyst consensus, insider activity, macro signals, crypto context (fast parallel phase)
- **Extended Time Horizons** — Now supports 3-6 months, 6-12 months, 12-36 months for medium-term thesis
- **Improved Setup** — `API_KEYS.txt` as the easy-to-find alternative to `.env` for new users
- **Better CSV Export** — 12 columns including Hold Tier, Invest USD, Exit Target, Price Range, Earnings Alert
- **Optional Alpha Vantage** — Now disabled by default (free tier only 25 req/day); enable in settings if you have paid plan

---

## 🚀 Getting Started

### Prerequisites

- **Python 3.11+** (via Homebrew on macOS: `brew install python@3.11`)
- **Anthropic API key** (from https://console.anthropic.com/)
- **Wealthsimple Premium account** with a USD trading account

### Installation

```bash
# Clone or navigate to the project
cd tech_stock

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

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

### First Run (Interactive Mode — Recommended)

```bash
source .venv/bin/activate
ANTHROPIC_API_KEY=your_key_here python src/main.py
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
   [1] Sonnet 4.6 — ~$0.09/run (recommended for daily use)
   [2] Opus 4.7   — ~$0.45/run (deeper analysis, better for complex portfolios)
   Choose (1/2) [Enter = 1]:
```

Done! The app will:
- Auto-detect your latest CSV files from `~/Downloads/`
- Fetch live market data for 36+ tracked tickers
- Call Claude for analysis
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

### Schedule Recurring Sessions

To run every Wednesday at 10:00 AM:

```bash
# Create a launchd plist or use cron:
# (0 10 * * 3) = Wednesday 10:00 AM

# Or use a simple shell script wrapper:
#!/bin/bash
cd /path/to/tech_stock
source .venv/bin/activate
ANTHROPIC_API_KEY=your_key python src/main.py morning --holdings ~/Downloads/latest_holdings.csv
```

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
- Numbered recommendations with emoji indicators 🟢🟡⚪🟠🔴
- Conviction scores and net expected returns
- Full thesis for each trade
- Watchlist flags (unwatched stocks worth monitoring)
- Warnings (concentration risk, leverage decay, etc.)

**Use this for:** Reading before market open, sharing with others

### 2. CSV Table
**Path:** `reports/YYYYMMDD_HHMM_morning_recommendations.csv`

Structured table with 12 columns:
- **Ticker** — Stock symbol
- **Action** — BUY, ADD, HOLD, TRIM, or SELL
- **Conviction** — 1–10 score
- **Net Expected %** — Expected return after fees
- **Time Horizon** — Intraday / 1-2 weeks / 1-3 months / 3-6 months / 6-12 months / 12-36 months
- **Hold Tier** — For HOLD only: watch (conviction ≤5) / keep (6–7) / add_on_dip (≥8)
- **Invest USD** — Amount to invest (for BUY/ADD only)
- **Exit Target** — Target exit date (e.g., "Jul 2026")
- **Price Range Low %** — Expected low (% change from now)
- **Price Range High %** — Expected high (% change from now)
- **Earnings Alert** — ⚠️ if earnings within 7 days
- **Thesis** — Text summary

**Use this for:** Importing into Excel/Sheets, tracking decisions, backtesting, position sizing

**Example:**
```csv
Ticker,Action,Conviction,Net Expected %,Time Horizon,Hold Tier,Invest USD,Exit Target,Price Range Low %,Price Range High %,Earnings Alert,Thesis
NVDA,ADD,8,+14.89%,3-6 months,,500,Jul 2026,-8.0,+18.0,,Core AI infrastructure play. Analyst consensus strong...
MSFT,HOLD,7,+11.89%,1-3 months,keep,,,+5.0,+12.0,,Lagging despite solid fundamentals; watch for catalyst...
TSM,HOLD,8,+7.69%,6-12 months,add_on_dip,,,+2.0,+16.0,,Concentration risk at 23.7%; add on pullback below $100...
LULU,SELL,8,+9.69%,intraday,,,,,-40.0,+5.0,⚠️,Down 67% with no recovery catalyst; earnings in 5 days...
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
  "risk_tolerance": "aggressive",
  "account_type": "wealthsimple_premium_usd",
  "claude_model": "claude-sonnet-4-6",
  "min_net_expected_return_pct": 0.5,
  "max_position_pct": 25,
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
| `min_net_expected_return_pct` | 0.5 | Hurdle rate — trades below this are refused |
| `max_position_pct` | 25 | Single position size cap (% of portfolio) |
| `enable_enrichment` | true | Enable/disable all enrichment APIs |
| `alpha_vantage_enabled` | false | Alpha Vantage free tier limited to 25 req/day; set true only with paid plan |
| `news_lookback_days` | 7 | How far back to fetch news headlines |
| `history_months` | 10 | Months of historical price data to fetch |

### Enrichment APIs (Professional-Grade Market Intelligence)

The app integrates **6 financial data sources** to enrich Claude's analysis with professional-grade signals. All sources run in parallel in Phase 1; optional Alpha Vantage runs sequentially in Phase 2.

| API | Data | Rate Limit | Status |
|-----|------|-----------|--------|
| **Finnhub** | Analyst consensus, earnings calendar, insider activity, news sentiment | Free tier: unlimited | Phase 1 (parallel) |
| **Polygon** | Previous-day OHLCV + VWAP signals | Free tier: 5/min | Phase 1 (parallel) |
| **Twelve Data** | Real-time quotes, earnings dates (better for Canadian tickers) | Free tier: 5/min | Phase 1 (parallel) |
| **FRED** (Federal Reserve) | Macro context: Fed Funds Rate, PCE inflation, yield curve, VIX | Free tier: unlimited | Phase 1 (parallel) |
| **CoinGecko** | BTC price, 7d change, Fear & Greed Index, macro risk signal | Free tier: 10-50/min | Phase 1 (parallel) |
| **Alpha Vantage** (optional) | News sentiment analysis | **Free tier: 25/day** ⚠️ | Phase 2 (sequential) |

**To enable Alpha Vantage** (only if you have a paid plan):
- Set `"alpha_vantage_enabled": true` in `config/settings.json`
- Get your API key from https://www.alphavantage.co/

**API Key Setup:**

Create `API_KEYS.txt` with all 7 keys (copy from `API_KEYS.template.txt`):
```
ANTHROPIC_API_KEY=sk-ant-...
FINNHUB_API_KEY=cxxxxxxxxxxx
ALPHA_VANTAGE_API_KEY=demo
TWELVE_DATA_API_KEY=demo_api_key
POLYGON_API_KEY=your_key_here
FRED_API_KEY=your_key_here
COINGECKO_API_KEY=your_key_here
```

All 7 keys are optional (any missing source is simply skipped). The program continues even if individual APIs fail.

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
[Claude Analyst] (with Config & Constants loaded) → JSON recommendations
    ↓
[Report Generator] → markdown + CSV + JSON log
```

**Performance:** ~18 tickers in ~10 seconds on cold cache (vs ~60s with serial fetching)

### Module Overview

**Shared Utilities** (centralized, single source of truth):

| Module | Purpose |
|--------|---------|
| `config.py` | Load and manage settings from `config/settings.json` |
| `constants.py` | Shared constants: LEVERAGED_ETFS, DEDUP_PAIRS, SKIP_MARKET_DATA, CDR_EXCHANGES |
| `_utils.py` | Helper functions: `safe_float()`, `clean_csv_row()`, `parse_session_filename()` |

**Data Loading & Calculation**:

| Module | Purpose |
|--------|---------|
| `portfolio_loader.py` | Parse Wealthsimple Holdings CSV |
| `activity_loader.py` | Parse Wealthsimple Activities CSV (trade history) |
| `market_data.py` | Fetch live prices, history, PE via yfinance (parallel fetching with ThreadPoolExecutor) |
| `news_fetcher.py` | Fetch recent news headlines (parallel fetching with ThreadPoolExecutor) |
| `fee_calculator.py` | Model Wealthsimple fees + bid-ask spreads |

**Enrichment & Analysis**:

| Module | Purpose |
|--------|---------|
| `enriched_data.py` | Orchestrate 6 enrichment APIs in parallel (Finnhub, Polygon, Twelve Data, FRED, CoinGecko) + optional sequential Alpha Vantage |
| `finnhub_client.py` | Fetch analyst consensus, earnings calendar, insider activity, news sentiment |
| `polygon_client.py` | Fetch previous-day OHLCV + VWAP signals |
| `twelve_data_client.py` | Fetch real-time quotes + earnings dates |
| `fred_client.py` | Fetch macro context (Fed Funds, inflation, yield curve, VIX regime) |
| `coingecko_client.py` | Fetch BTC price, Fear & Greed Index, macro risk signal |
| `alpha_vantage_client.py` | Fetch news sentiment (thread-safe rate limiter; optional, disabled by default) |

**Analysis & Output**:

| Module | Purpose |
|--------|---------|
| `claude_analyst.py` | 23-rule system prompt, build enriched prompt, call Claude API, parse JSON response with new fields (invest_amount_usd, hold_tier, earnings_alert, target_exit_date, price targets, priority_actions) |
| `report_generator.py` | Format markdown + CSV with priority actions table, hold tier labels, earnings badges, invest amounts, exit targets, price ranges |
| `main.py` | CLI entry point, interactive setup, API key loading (API_KEYS.txt first, then .env), enrichment orchestration, CSV export with 12 columns |

### Claude System Prompt (23 Rules)

Claude receives a detailed system prompt with **23 strategic rules** governing analysis and output structure:

**Input Data Claude Gets:**
1. Portfolio snapshot — all holdings with cost basis, current value, P&L, unrealized gains (from portfolio_loader)
2. Market data — current price, 1d/5d/1mo changes, PE, 52w highs/lows, last 5 closes (parallel fetch from market_data)
3. Recent news — last 7 days of headlines per ticker (parallel fetch from news_fetcher)
4. **Enriched intelligence** — analyst consensus, earnings calendars, insider activity, sentiment, macro context (from enriched_data.py)
5. Fee snapshot — one-way and round-trip costs per ticker (from fee_calculator)
6. Recent trades — your trading activity last 90 days (from activity_loader, if provided)
7. Session type — "morning" (pre-open) or "afternoon" (intraday + EOD positioning)
8. Watchlist alerts — target entry/exit prices for monitored tickers (from config/watchlist.json)

**Output Rules (Examples from the 23):**
- **Rule 15 (Earnings Alert):** If earnings within 7 days, set `earnings_alert=true` and lead with "⚠️ EARNINGS [DATE]"
- **Rule 17 (Enrichment Citation):** Cite analyst consensus, EPS beat streaks, insider activity in thesis statements
- **Rule 18 (Investment Sizing):** Set `invest_amount_usd` based on conviction: 8–10 = 40% of session budget, 7 = 25%, 6 = 15%
- **Rule 19 (Hold Tiers):** Every HOLD gets `hold_tier`: "watch" (conviction ≤5), "keep" (6–7), "add_on_dip" (≥8)
- **Rule 20 (Time Horizons):** Exactly one of: intraday / 1-2 weeks / 1-3 months / 3-6 months / 6-12 months / 12-36 months
- **Rule 21 (Exit Plan):** Every recommendation includes `target_exit_date` (e.g., "Jul 2026") and price range (low %, high %)
- **Rule 22 (Buy Signals):** Actively look for BUY opportunities — not just existing portfolio
- **Rule 23 (Priority Actions):** Output `priority_actions` array — ordered "do this today" list by urgency

**Output JSON Structure:**
```json
{
  "recommendations": [
    {
      "ticker": "NVDA",
      "action": "ADD",
      "conviction": 8,
      "net_expected_return_pct": 14.89,
      "invest_amount_usd": 500,
      "time_horizon": "3-6 months",
      "hold_tier": null,
      "earnings_alert": false,
      "target_exit_date": "Jul 2026",
      "price_target_low_pct": -8.0,
      "price_target_high_pct": 18.0,
      "thesis": "Core AI infrastructure. Analyst consensus: 66 analysts STRONG BUY. Beat estimates 4 quarters in a row. Insider buying strong."
    }
  ],
  "priority_actions": [
    {"order": 1, "ticker": "NVDA", "action": "ADD", "reason": "Core position, good entry"},
    {"order": 2, "ticker": "MSFT", "action": "HOLD", "reason": "Watch for earnings catalyst"}
  ],
  "summary": "..."
}

---

## 🤔 FAQ

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

### Q: What's the "Exit Target" and "Price Range"?

**A:** Every recommendation includes:
- **Exit Target Date** (e.g., "Jul 2026") — when Claude expects you to close the position
- **Price Range Low % / High %** — expected price move from entry (e.g., -8% to +18%)

Use these to set stop-loss and take-profit orders in Wealthsimple.

### Q: How do I set up the enrichment APIs?

**A:** Copy `API_KEYS.template.txt` to `API_KEYS.txt` and fill in your keys (signup links are in the template). All 7 keys are optional; missing APIs are simply skipped. To disable all enrichment, set `"enable_enrichment": false` in `config/settings.json`.

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

**A:** With Sonnet: ~$0.09 per run (~$0.18/day for 2 runs = ~$5.40/month)  
With Opus: ~$0.45 per run (~$0.90/day = ~$27/month)  
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
Make sure `.env` exists and contains `ANTHROPIC_API_KEY=your_key_here`. Check for typos.

### "Holdings CSV not found"
The app looks for `holdings-report-*.csv` in `~/Downloads/`. Either:
1. Answer "N" to the auto-detected path and provide the full path
2. Move your CSV to Downloads
3. Export a fresh Holdings report from Wealthsimple

### "No recent news available"
This is normal. yfinance news availability varies by ticker and day. The app still generates recommendations based on price action and fundamentals.

### "Claude response parsing failed"
The response was truncated. This can happen if you have 100+ positions or very large news volumes. Increase `max_tokens` in `claude_analyst.py` from 8192 to 16384.

---

## 📚 Project Structure

```
tech_stock/
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
├── src/
│   ├── __init__.py
│   ├── main.py                  ← Entry point (CLI + interactive, API key loading)
│   ├── config.py                ← Load settings (single source of truth)
│   ├── constants.py             ← Shared constants
│   ├── _utils.py                ← Helper functions (safe_float, clean_csv_row, etc.)
│   ├── portfolio_loader.py      ← Parse Holdings CSV
│   ├── activity_loader.py       ← Parse Activities CSV
│   ├── market_data.py           ← Fetch prices via yfinance (parallel)
│   ├── news_fetcher.py          ← Fetch headlines (parallel)
│   ├── fee_calculator.py        ← Wealthsimple fee model
│   ├── enriched_data.py         ← Orchestrate 6 enrichment APIs (Phase 1 parallel, Phase 2 sequential)
│   ├── finnhub_client.py        ← Analyst consensus, earnings, insider activity, sentiment
│   ├── polygon_client.py        ← Previous-day OHLCV + VWAP signals
│   ├── twelve_data_client.py    ← Real-time quotes, earnings dates (better Canadian coverage)
│   ├── fred_client.py           ← Macro context (Fed rate, inflation, yield curve, VIX)
│   ├── coingecko_client.py      ← BTC price, 7d change, Fear & Greed, macro risk signal
│   ├── alpha_vantage_client.py  ← News sentiment (thread-safe rate limiter; optional)
│   ├── claude_analyst.py        ← 23-rule system prompt, Claude API call, JSON parsing
│   └── report_generator.py      ← Priority actions table, hold tiers, earnings badges, markdown + CSV
├── requirements.txt             ← Python dependencies
├── .env.example                 ← Template for API key
├── .gitignore                   ← Excludes .env, .venv, reports/
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

**Last updated:** April 29, 2026 (Major upgrade: priority actions, invest sizing, hold tiers, earnings alerts, exit planning, 6 enrichment APIs)  
**Version:** 1.2.0  
**Status:** Production-ready with professional-grade signals and actionable recommendations
