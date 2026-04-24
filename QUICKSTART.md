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
cd tech_stock

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up API key
cp .env.example .env
# Open .env in your editor and paste your ANTHROPIC_API_KEY
```

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
ANTHROPIC_API_KEY=your_key_here python src/main.py
```

### Step 3: Answer 5 questions

```
Session type (morning/afternoon) [Enter = morning]: 
1. How much USD would you like to invest today? $500
2. How much CAD would you like to invest today? $1000
3. Holdings CSV detected: /Users/you/Downloads/holdings-report-2026-04-24.csv
   Is this correct? (Y/N): Y
4. Activities CSV detected: (Skip for now, just press Enter)
5. Which model? [1] Sonnet 4.6 (recommended, cheap)
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
ANTHROPIC_API_KEY=your_key python src/main.py
```

Then use `cron` to run at 10 AM and 3 PM:

```bash
crontab -e
# Add:
# 0 10 * * * /path/to/script.sh  # 10 AM
# 0 15 * * * /path/to/script.sh  # 3 PM
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

### "API key not found"
→ Make sure `.env` has `ANTHROPIC_API_KEY=sk-ant-api...` (no spaces)

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
