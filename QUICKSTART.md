# ⚡ Quick Start Guide

Get tech_stock running in **5 minutes**.

---

## 📋 Prerequisites

- Python 3.11+ (check with `python3 --version`)
- Anthropic API key (get one free at https://console.anthropic.com/)
- Wealthsimple Premium account with USD trading enabled

---

## 🚀 Installation (2 minutes)

```bash
# 1. Clone the repo
git clone https://github.com/pouyafath/tech_stock.git
cd tech_stock

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Make run scripts executable (macOS/Linux — first time only)
chmod +x run.sh run-ui.sh

# 5. Set up API keys (CHOOSE ONE METHOD):
```

### Option A: Easy Way (Recommended) 📄

```bash
# Copy the template to create your API_KEYS.txt
cp API_KEYS.template.txt API_KEYS.txt

# Open API_KEYS.txt and paste your keys:
# Mac:     open API_KEYS.txt
# Windows: notepad API_KEYS.txt
# Linux:   nano API_KEYS.txt
```

Then paste these keys (you'll sign up for free accounts on each):
- **Anthropic:** https://console.anthropic.com/api/keys
- **Finnhub:** https://finnhub.io/dashboard/api-keys
- **Alpha Vantage:** https://www.alphavantage.co/support/#api-key
- **Twelve Data:** https://twelvedata.com/account/api-keys
- **Polygon:** https://polygon.io/dashboard/api-keys
- **FRED:** https://fred.stlouisfed.org/docs/api/fred/
- **CoinGecko:** https://www.coingecko.com/en/api

### Option B: Advanced (.env file) 🔧

```bash
cp .env.example .env
nano .env  # or your preferred editor
```

Save and you're done!

---

## 📊 First Run (2 minutes)

### Step 1: Export from Wealthsimple

1. Log into Wealthsimple
2. Go to **Account → Activity**
3. Click **Export Holdings Report (CSV)**
4. Save to **Downloads** folder (or any location)

### Step 2: Launch the app

```bash
source .venv/bin/activate
./run.sh
```

A menu appears — pick your interface:
```
  [1]  CLI             — Terminal, fastest
  [2]  Streamlit UI    — Web dashboard (opens browser)
  [3]  Textual TUI     — Terminal dashboard
  [4]  Desktop App     — Embedded dashboard (no browser)
  [5]  Check Updates   — Check GitHub Releases and verify update metadata

  Choose [1/2/3/4/5, Enter = 1]:
```

> **No terminal?** Download `tech_stock.dmg` from the [Releases page](https://github.com/pouyafath/tech_stock/releases), double-click for the native launcher, then choose **Desktop App** for the embedded no-browser interface.

Choose **1 (CLI)** for your first run. Your API keys are read from `API_KEYS.txt` or `.env` automatically.

### Step 3: Answer 5 questions (CLI mode)

```
Session type (morning/afternoon) [Enter = morning]: 
1. How much USD would you like to invest today? $500
2. How much CAD would you like to invest today? $1000
3. Holdings CSV detected: /Users/you/Downloads/holdings-report-2026-04-24.csv
   Is this correct? (Y/N): Y
4. Activities CSV detected: (Skip for now, just press Enter)
5. Which model? 
   [1] Sonnet 4.6 (recommended, ~$0.30-$0.70/run typical two-pass range)
   [2] Opus 4.7 (deeper analysis, higher cost)
   Choose (1/2) [Enter = 1]:
```

### Step 4: Review your reports

```
=================================================================
  📊 Report saved to:
  /Users/you/tech_stock/reports/20260424_1030_morning.md

  📋 CSV table saved to:
  /Users/you/tech_stock/reports/20260424_1030_morning_recommendations.csv
=================================================================
```

Open the markdown file in any editor to see recommendations with conviction scores and theses.

Latest paid validation: May 10, 2026 full Sonnet run, 31 tracked tickers, two Claude passes, 50,105 tokens, estimated cost `$0.6341`.

---

## Optional: Jump Directly to a UI

```bash
./run.sh 2    # → Streamlit (opens browser automatically)
./run.sh 3    # → Textual TUI (keyboard-driven terminal dashboard)
./run.sh 4    # → Desktop App (embedded dashboard, no browser)
./run.sh 5    # → Check updates
```

Or launch directly:
```bash
# Embedded desktop dashboard
.venv/bin/python src/desktop_app.py

# Browser dashboard
.venv/bin/python -m streamlit run ui/streamlit_app.py

# Terminal dashboard
.venv/bin/python ui/textual_app.py
```

| UI | Best for |
|----|----------|
| **Desktop App** | Embedded no-browser dashboard with action cards, Buy Signals readiness filters, report runs, report viewer/search, history, config/API key editing, API checks, and updates |
| **Streamlit** | CSV upload & preview, Buy Signals readiness filters, live run progress, dashboard metrics, Decision Journal, history compare, download buttons, JSON/API key editing |
| **Textual** | Same workflow in the terminal, including Buy Signals/readiness summaries, journal summaries, update checks, and keyboard shortcuts (`Ctrl+R` = run, `Ctrl+S` = save, `r` = refresh) |

---

## 🎯 What You Got

✅ **Markdown report** with full recommendations and analysis
✅ **CSV table** with ticker, action, conviction, net expected return
✅ **JSON log** for backtesting (in `data/recommendations_log/`)
✅ **Buy Signals view** with Trade Ready / Review First / Blocked readiness
✅ **Decision journal** for recording what you actually did and scoring model-vs-user outcomes
✅ **API health/key manager** and checksum-verified update flow

---

## 💡 Next Steps

### Optional: Include Trade History

To give Claude more context:

1. Go to **Account → Activity → Export Activities Export (CSV)**
2. Export the **full available history** if Wealthsimple offers it; otherwise select the longest range available
3. Save to Downloads
4. Run again and answer "Y" to the Activities CSV question

The app uses the recent 90-day slice for prompt context and previous-session checks, but uses the full Activities file for exact FIFO holding-day calculations.

### Optional: Schedule Daily Runs

Create a simple script (macOS/Linux):

```bash
#!/bin/bash
cd /path/to/tech_stock
source .venv/bin/activate
python src/main.py
```

Save as `run_daily.sh`, then use `cron` to run at 10 AM and 3 PM:

```bash
chmod +x run_daily.sh
crontab -e
# Add these lines:
# 0 10 * * * /path/to/tech_stock/run_daily.sh  # 10 AM
# 0 15 * * * /path/to/tech_stock/run_daily.sh  # 3 PM
```

### Track Your Trades

After you execute trades, log them in `data/trade_history.csv`:

```csv
date,ticker,action,shares,price_cad,followed_recommendation,notes
2026-04-24,NVDA,BUY,5,118.50,yes,morning recommendation
2026-04-25,LULU,SELL,10,17.25,yes,high conviction 8/10
```

---

## 🆘 Troubleshooting

### "ANTHROPIC_API_KEY is not set"
→ Make sure you created `API_KEYS.txt` from `API_KEYS.template.txt` and pasted your key  
→ OR if using `.env`: make sure it has `ANTHROPIC_API_KEY=sk-ant-api...` (no spaces)

### "Holdings CSV not found"
→ Answer "N" when prompted and provide the full path, OR move the CSV to `~/Downloads/`

### "ModuleNotFoundError: No module named 'anthropic'"
→ Run `source .venv/bin/activate` first, then `pip install -r requirements.txt`

### "How do I check for updates?"
→ From the launcher, choose option **5**
→ From terminal, run `python src/main.py check-update` or `./run.sh 5`
→ Release downloads include `SHA256SUMS.txt`; packaged updates verify the checksum when the file is available

### Need more help?
→ See [README.md](README.md#-troubleshooting) for detailed troubleshooting

---

## 📚 Learn More

- **Full documentation:** [README.md](README.md)
- **Understanding outputs:** [README.md#-output-files](README.md#-output-files)
- **Fee model explained:** [README.md#-fee-model](README.md#-fee-model)
- **Architecture:** [README.md#-architecture](README.md#-architecture)

---

## 💬 Questions?

Check the [FAQ](README.md#-faq) in the main README.

---

**Done!** You're now running an AI-powered portfolio advisor. 🎉

Run `./run.sh` whenever you want fresh recommendations. Add `morning` or `afternoon` to skip the menu.
