# tech_stock 📈

> A Claude-powered portfolio advisor for Wealthsimple Premium USD accounts with twice-daily trading recommendations, fee-aware analysis, and conviction scoring.

[![GitHub](https://img.shields.io/badge/GitHub-tech--stock-blue)](https://github.com/pouyafath/tech_stock)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-green)]()
[![Claude API](https://img.shields.io/badge/API-Claude%20Sonnet%20%26%20Opus-orange)]()
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

✅ **Interactive Setup** — Guided prompts for USD/CAD budgets, CSV import, model selection  
✅ **Fee-Aware** — Refuses to recommend trades below the fee hurdle (default 0.5% net expected return)  
✅ **Conviction Scoring** — 1-10 scale; scores < 6 automatically become HOLD recommendations  
✅ **Live Market Data** — Real-time prices, 3-month history, PE ratios, 52-week highs/lows via yfinance  
✅ **Recent News** — Pulls last 7 days of headlines per ticker from Yahoo Finance  
✅ **Trade History Context** — Loads your recent Wealthsimple trades to avoid whipsawing  
✅ **Dual Output** — Markdown report + CSV table + JSON log for backtesting  
✅ **Model Choice** — Pick Sonnet (~$0.09/run, fast) or Opus (~$0.45/run, deeper analysis) per session  

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

# Set up API key
cp .env.example .env
# Edit .env and paste your ANTHROPIC_API_KEY
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
   [1] Sonnet 4.6 — ~$0.09/run (recommended)
   [2] Opus 4.7   — ~$0.45/run (deeper analysis)
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

Structured table with:
- Ticker
- Action (BUY, ADD, HOLD, TRIM, SELL)
- Conviction (1-10)
- Net Expected % (after fees)
- Time Horizon (intraday, 1-2 weeks, 1-3 months)
- Thesis (text summary)

**Use this for:** Importing into Excel/Sheets, tracking decisions, backtesting

**Example:**
```csv
Ticker,Action,Conviction,Net Expected %,Time Horizon,Thesis
NVDA,ADD,8,+14.89%,1-3 months,NVDA is the core AI infrastructure holding...
MSFT,ADD,7,+11.89%,1-3 months,MSFT is lagging despite solid fundamentals...
TSM,HOLD,8,+7.69%,1-3 months,TSM concentration risk at 23.7% of portfolio...
LULU,SELL,8,+9.69%,intraday,LULU is down 67% with no recovery catalyst...
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
  "budget_cad": 3000.0,
  "budget_usd": 0.0,
  "risk_tolerance": "aggressive",
  "account_type": "wealthsimple_premium_usd",
  "claude_model": "claude-sonnet-4-6",
  "min_net_expected_return_pct": 0.5,
  "max_position_pct": 25.0
}
```

**Key settings:**

| Key | Default | Purpose |
|-----|---------|---------|
| `budget_cad` | 3000 | Available CAD to deploy (overridden per run in interactive mode) |
| `budget_usd` | 0 | Available USD to deploy (overridden per run in interactive mode) |
| `risk_tolerance` | "aggressive" | Can be "moderate" to get more conservative recommendations |
| `claude_model` | "claude-sonnet-4-6" | "claude-sonnet-4-6" (fast, cheap) or "claude-opus-4-7" (thorough, expensive) |
| `min_net_expected_return_pct` | 0.5 | Hurdle rate — trades below this are refused |
| `max_position_pct` | 25 | Single position size cap (as % of total portfolio) |

### `config/watchlist.json`

Add tickers to monitor (not yet held):

```json
{
  "all": [
    "MSFT", "AAPL", "GOOGL",
    "AMD", "CRM", "NVDA",
    "PLTR", "SMCI", "ARM", "IONQ",
    "SHOP.TO", "CSU.TO", "OTEX.TO", "KXS.TO"
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
[Market Data] ← yfinance → prices, history, PE, news
[News Fetcher] ← yfinance → headlines
[Fee Calculator] → round-trip costs
    ↓
[Claude Analyst] → JSON recommendations
    ↓
[Report Generator] → markdown + CSV
```

### Module Overview

| Module | Purpose |
|--------|---------|
| `main.py` | CLI entry point, interactive setup, orchestration |
| `portfolio_loader.py` | Parse Wealthsimple Holdings CSV |
| `activity_loader.py` | Parse Wealthsimple Activities CSV (trade history) |
| `market_data.py` | Fetch live prices, history, PE via yfinance |
| `news_fetcher.py` | Fetch recent news headlines |
| `fee_calculator.py` | Model Wealthsimple fees + bid-ask spreads |
| `claude_analyst.py` | Build prompt, call Claude API, parse JSON response |
| `report_generator.py` | Format recommendations as markdown + CSV |

### Claude System Prompt

Claude gets:
1. **Portfolio snapshot** — all holdings with cost basis and P&L
2. **Market data** — current price, 1d/5d/1mo changes, PE, 52w highs/lows, last 5 closes
3. **Recent news** — last 7 days of headlines per ticker
4. **Fee snapshot** — one-way and round-trip costs per ticker
5. **Recent trades** — your trading activity last 90 days
6. **Session type** — "morning" (pre-open setup) or "afternoon" (intraday + EOD positioning)

Claude then outputs structured JSON with:
- Action: BUY, ADD, HOLD, TRIM, SELL
- Conviction: 1-10
- Thesis: Why this move makes sense
- Net expected return after fees
- Risk/invalidation condition
- Time horizon

---

## 🤔 FAQ

### Q: Do I have to follow the recommendations?

**A:** No. This tool is advisory only. You execute all trades manually in Wealthsimple. Log your actual trades (and whether you followed the recommendation) in `trade_history.csv` to measure the agent's performance.

### Q: How often should I run it?

**A:** Twice daily is the design pattern:
- **Morning (~9:30 AM ET):** Pre-open setup, overnight catalysts, premarket moves
- **Afternoon (~3 PM ET):** Intraday action, EOD positioning, swing trade entries

But you can run it as often as you like. Use `min_net_expected_return_pct` (default 0.5%) to avoid churn.

### Q: Can I use this with a CAD account or non-Wealthsimple broker?

**A:** The fee model is hard-coded for Wealthsimple Premium USD accounts. For other brokers, you'd need to modify `fee_calculator.py`. CAD accounts and CAD-hedged CDRs are handled but fees will be inaccurate.

### Q: What's the cost per run?

**A:** With Sonnet: ~$0.09 per run (~$0.18/day for 2 runs = ~$5.40/month)  
With Opus: ~$0.45 per run (~$0.90/day = ~$27/month)

### Q: Can I schedule this automatically?

**A:** Yes. Use cron (Linux/macOS) or Task Scheduler (Windows) to call the CLI mode at 9:30 AM and 3 PM. You'll need to:
1. Store your API key in a `.env` file (make sure `.gitignore` excludes it)
2. Have your Holdings CSV auto-exported or manually placed in `~/Downloads/`
3. Use a wrapper script to activate venv and run the command

### Q: How do I backtest the recommendations?

**A:** Use `data/trade_history.csv` to track execution, and `data/recommendations_log/` for raw JSON. Compare:
- Recommendations you followed vs didn't follow
- Your P&L vs QQQ buy-and-hold benchmark
- Win rate by sector, action type (ADD vs SELL), conviction score

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
│   ├── main.py                  ← Entry point (CLI + interactive)
│   ├── portfolio_loader.py      ← Parse Holdings CSV
│   ├── activity_loader.py       ← Parse Activities CSV
│   ├── market_data.py           ← Fetch prices via yfinance
│   ├── news_fetcher.py          ← Fetch headlines
│   ├── fee_calculator.py        ← Wealthsimple fee model
│   ├── claude_analyst.py        ← Claude API + prompt
│   └── report_generator.py      ← Format markdown + CSV
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

**Last updated:** April 24, 2026  
**Version:** 1.0.0  
**Status:** Production-ready
