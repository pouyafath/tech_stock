# tech_stock — Twice-Daily Portfolio Advisor

A Claude-powered portfolio advisor for Wealthsimple Premium (USD account). Run it twice a day to get structured BUY/SELL/HOLD/TRIM/ADD recommendations with fee-aware net expected returns.

**You execute trades manually in Wealthsimple. This tool only advises.**

---

## Quick Start

```bash
cd tech_stock
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Open .env and paste your Anthropic API key
```

---

## Daily Usage (with Wealthsimple CSV exports — recommended)

**Step 1:** Export from Wealthsimple (takes 30 seconds):
- Go to **Account → Activity** → Export **Holdings report** (CSV) — do this every run
- Optional: Export **Activities export** (CSV) for last **3 months** — reuse for a week

**Step 2:** Run the advisor:
```bash
# Morning (~9:30 AM ET) — with your fresh holdings CSV:
python src/main.py morning --holdings ~/Downloads/holdings-report-2026-04-23.csv

# With activities for richer context (recommended once a week):
python src/main.py morning \
  --holdings ~/Downloads/holdings-report-2026-04-23.csv \
  --activities ~/Downloads/activities-export-2026-04-23.csv

# Afternoon (~3:00 PM ET, 1 hour before close):
python src/main.py afternoon --holdings ~/Downloads/holdings-report-2026-04-23.csv
```

**Which CSV to use?**
| CSV | When | Period |
|---|---|---|
| **Holdings report** | Every run (mandatory) | Just export fresh — always current |
| **Activities export** | Optional, reuse for ~1 week | **3 months** is the sweet spot |

---

## How It Works

1. Loads your live holdings from the Wealthsimple Holdings CSV (or `config/portfolio.json` as fallback)
2. Optionally loads recent trade history from the Activities CSV for context (avoids whipsawing)
3. Fetches live prices + 3-month history + news via `yfinance` (free, no extra API key)
4. Calculates round-trip fees (Wealthsimple Premium + USD account model)
5. Calls Claude (`claude-sonnet-4-6`) with a structured prompt
6. Gets back a JSON recommendation: action, conviction (1–10), thesis, net expected return after fees
7. Saves markdown report to `reports/` and JSON log to `data/recommendations_log/`

---

## Logging Your Trades

After you execute a trade manually in Wealthsimple, log it in `data/trade_history.csv`:
```
2026-04-23,NVDA,BUY,5,118.50,yes,followed morning recommendation
```

The `followed_recommendation` column (yes/no) lets you measure whether following the agent is actually profitable vs. just buying and holding QQQ.

---

## Watchlist

Edit `config/watchlist.json` to add/remove tickers. Pre-seeded with:
- **Megacaps:** MSFT, AAPL, GOOGL
- **Growth:** AMD, CRM, NVDA
- **Aggressive:** PLTR, SMCI, ARM, IONQ
- **Canadian tech:** SHOP.TO, CSU.TO, OTEX.TO, KXS.TO

---

## Settings

Edit `config/settings.json` to change:
- `budget_cad`: your available budget
- `risk_tolerance`: "aggressive" or "moderate"
- `claude_model`: switch to `claude-opus-4-7` for deeper analysis (slower, more expensive)
- `min_net_expected_return_pct`: the anti-churn hurdle (default 0.5%)
- `max_position_pct`: maximum per-position size (default 25%)

---

## Fee Model (Wealthsimple Premium + USD Account)

| Fee Type | Amount |
|---|---|
| Commission | $0 |
| FX Spread | $0 (USD account) |
| Bid-ask (megacap) | ~0.05% one-way |
| Bid-ask (smallcap) | ~0.40% one-way |
| Regulatory (US stock) | ~$0.03/trade |

The agent **refuses to recommend BUY** if the expected move doesn't clear the round-trip fee hurdle.

---

## Reports

Every session generates:
- `reports/YYYYMMDD_HHMM_morning.md` — human-readable report with tables
- `data/recommendations_log/YYYYMMDD_HHMM_morning.json` — raw JSON for backtesting

---

## Measuring Performance

After 4–6 weeks, compare your P&L against "what if I just bought and held QQQ." If the agent isn't beating that benchmark, use the `followed_recommendation` column in `trade_history.csv` to audit which calls added or destroyed value.

---

## Project Structure

```
tech_stock/
├── config/
│   ├── portfolio.json       ← YOUR HOLDINGS (edit after trades)
│   ├── watchlist.json       ← stocks to monitor
│   └── settings.json        ← budget, risk, model, fees
├── data/
│   ├── trade_history.csv    ← your trade log
│   └── recommendations_log/ ← JSON per session
├── reports/                 ← markdown reports
├── src/
│   ├── main.py              ← entry point
│   ├── market_data.py       ← yfinance wrapper
│   ├── news_fetcher.py      ← recent headlines
│   ├── fee_calculator.py    ← Wealthsimple fee model
│   ├── claude_analyst.py    ← Claude API + prompt
│   └── report_generator.py ← markdown formatter
├── requirements.txt
├── .env.example
└── README.md
```
