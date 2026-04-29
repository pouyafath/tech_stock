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

# 4. Set up API keys (CHOOSE ONE METHOD):
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

### Step 2: Run the app

```bash
source .venv/bin/activate
python src/main.py
```

(Your API keys are read from `API_KEYS.txt` or `.env` automatically)

### Step 3: Answer 5 questions

```
Session type (morning/afternoon) [Enter = morning]: 
1. How much USD would you like to invest today? $500
2. How much CAD would you like to invest today? $1000
3. Holdings CSV detected: /Users/you/Downloads/holdings-report-2026-04-24.csv
   Is this correct? (Y/N): Y
4. Activities CSV detected: (Skip for now, just press Enter)
5. Which model? 
   [1] Sonnet 4.6 (recommended, ~$0.09/run, fast)
   [2] Opus 4.7 (deeper analysis, ~$0.45/run)
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

---

## 🎯 What You Got

✅ **Markdown report** with full recommendations and analysis  
✅ **CSV table** with ticker, action, conviction, net expected return  
✅ **JSON log** for backtesting (in `data/recommendations_log/`)

---

## 💡 Next Steps

### Optional: Include Trade History

To give Claude more context:

1. Go to **Account → Activity → Export Activities Export (CSV)**
2. Select last **3 months**
3. Save to Downloads
4. Run again and answer "Y" to the Activities CSV question

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

Run `python src/main.py` whenever you want fresh recommendations.
