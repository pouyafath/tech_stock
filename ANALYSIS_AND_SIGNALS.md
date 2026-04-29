# How tech_stock Analyzes & Suggests Trading Signals

Comprehensive guide to the analysis pipeline, data sources, and signal generation methodology.

---

## 🎯 Signal Generation Pipeline

The program follows a multi-stage analysis flow:

```
User Portfolio (Wealthsimple CSV)
    ↓
[Normalization & Deduplication]
    ↓
Market Data Fetching (live prices, history, fundamentals)
    ↓
News & Sentiment Analysis (recent headlines)
    ↓
Fee Modeling (realistic trading costs)
    ↓
Claude AI Analysis (context-aware recommendations)
    ↓
Backtest Against History (self-calibration)
    ↓
Trade Signals + Conviction Scores
```

---

## 📊 Data Sources & APIs

### 1. **yfinance** (Primary Market Data Source)

| Aspect | Details |
|--------|---------|
| **What** | Free Python wrapper for Yahoo Finance API |
| **Data** | Live stock prices, historical OHLCV, fundamentals, news headlines |
| **Cost** | ✅ **100% FREE** — no API key required |
| **Access** | Direct HTTP requests to Yahoo Finance servers (no auth) |
| **Availability** | Public data — available to all users worldwide |
| **Rate Limits** | ~2000 requests/hour per IP (generally permissive) |
| **Reliability** | 99%+ uptime; widely used in production |

**Data Points Retrieved:**
- Current price, bid-ask spread
- 1-day, 5-day, 1-month % change
- 52-week high/low
- Market cap, PE ratio (trailing + forward)
- Sector, industry classification
- Historical closes (last 90 days)
- Volume (daily + 30-day average)
- News headlines (last 7 days per ticker)

**Code Location:** `src/market_data.py`, `src/news_fetcher.py`

```python
# Example: How we fetch data
import yfinance as yf
ticker = yf.Ticker("NVDA")
info = ticker.info  # fundamentals
hist = ticker.history(start="2026-01-01", end="2026-04-24")  # OHLCV
news = ticker.news  # headlines with sentiment scores
```

### 2. **Wealthsimple (Portfolio Data Source)**

| Aspect | Details |
|--------|---------|
| **What** | Canadian/North American brokerage with CSV export |
| **Data** | Holdings (ticker, quantity, cost basis, market value, P&L, currency) |
| **Cost** | ✅ **FREE** — included with Wealthsimple Premium account |
| **Access** | Manual CSV export from Account → Activity → Export Holdings Report |
| **Availability** | Only for Wealthsimple Premium account holders |
| **Frequency** | Updated in real-time; export as often as needed |

**Data Points Retrieved:**
- Ticker symbol
- Quantity held
- Average cost (CAD/USD)
- Current market value
- Unrealized P&L
- Currency of position (USD/CAD)
- Security type (stock, ETF, etc.)
- Account designation

**Code Location:** `src/portfolio_loader.py`

### 3. **Anthropic Claude API (AI Analysis)**

| Aspect | Details |
|--------|---------|
| **What** | Large language model for multi-step reasoning |
| **Data** | Analyzes market data, portfolio context, news, fees, conviction scoring |
| **Cost** | 💰 **PAID** — ~$0.09–$0.45 per run depending on model |
| | Sonnet 4.6: ~$0.09/run (input-token heavy) |
| | Opus 4.7: ~$0.45/run (superior reasoning) |
| **Access** | REST API with API key (get free from https://console.anthropic.com/) |
| **Availability** | Available to all users with API key |
| **Rate Limits** | Tier-dependent (usually 1000+ requests/day for standard accounts) |

**What Claude Does:**
1. **Context Integration** — understands your specific portfolio, risk tolerance, fees
2. **Multi-step Reasoning** — correlates market events, news sentiment, technical patterns
3. **Conviction Scoring** — 1-10 scale based on strength of thesis + expected move
4. **Risk Assessment** — identifies concentration risk, leverage decay, whipsawing
5. **Thesis Generation** — writes specific, testable reasoning for each trade

**Code Location:** `src/claude_analyst.py`

```python
# Simplified flow: we send Claude this structured prompt
prompt = f"""
Portfolio Summary:
{portfolio_snapshot}

Market Data (current prices, sentiment, technicals):
{market_data_summary}

Recent News & Headlines:
{news_formatted}

Fee Snapshot (realistic round-trip costs):
{fee_snapshot}

Recent Trades (avoid whipsawing):
{recent_activities}

Your task: Recommend BUY/ADD/HOLD/TRIM/SELL for each ticker with:
- Conviction (1-10)
- Net expected return after fees
- Thesis (why this move makes sense)
- Time horizon (intraday, 1-2w, 1-3m, 3-12m)
"""

response = client.messages.create(
    model="claude-opus-4-7",
    max_tokens=8192,
    system=SYSTEM_PROMPT,
    messages=[{"role": "user", "content": prompt}]
)
```

---

## 🧠 Analysis Methodology

### Phase 1: Market Data Normalization

```python
# src/market_data.py: compute_indicators()

1. RSI(14) via Wilder smoothing
   → Identifies overbought (>70) / oversold (<30) conditions
   
2. MACD (12, 26, 9)
   → Momentum oscillator: tracks trend acceleration/deceleration
   
3. Bollinger Bands (20, 2σ)
   → Volatility measurement + mean reversion opportunity
   
4. SMA 50 / 200
   → Long-term trend confirmation
   
5. Volume Spike Ratio (today vs 30d avg)
   → Identifies unusual activity (breakout confirmation)
   
6. Price vs 52-week High/Low
   → Context for mean-reversion probability
```

### Phase 2: Fee-Aware Hurdle

```python
# src/fee_calculator.py

Bid-ask spreads by cap tier:
  Megacap (AAPL, MSFT, NVDA)     → ~0.05% round-trip
  Large-cap (AMD, CRM, AVGO)     → ~0.15% round-trip
  Mid-cap (PLTR, ARM, SMCI)      → ~0.40% round-trip
  
Wealthsimple Premium costs:
  Commission                      → $0
  FX Spread (USD account)        → $0 (zero-margin model)
  SEC regulatory fee             → ~$0.03/trade (~0.005% for $5k)

Decision Rule:
  IF net_expected_return > min_net_expected_return_pct (default 0.5%)
    THEN recommend BUY/ADD
  ELSE
    HOLD or SELL
```

This **refuses** churn trades (trades where fees exceed expected return).

### Phase 3: Sentiment Aggregation

```python
# src/news_fetcher.py: aggregate_sentiment()

1. Fetch last 7 days of headlines per ticker
2. Score each headline with VADER sentiment (-1.0 to +1.0)
3. Aggregate to: avg_sentiment, bullish/neutral/bearish counts
4. Include in Claude prompt for context

Example: "NVDA beats earnings"
  → VADER score: +0.87 (strongly bullish)
  → Context: beats expected guidance, guidance raise
```

### Phase 4: Claude Multi-Step Reasoning

Claude receives **all** data in a structured prompt and performs:

1. **Correlation Analysis**
   - Does price action match news sentiment?
   - Is RSI extreme? Is there momentum confirmation (MACD)?
   - Does volume support the move?

2. **Risk Assessment**
   - Position concentration in portfolio?
   - Leveraged ETF decay over time?
   - Recent whipsaw activity in this ticker?

3. **Thesis Development**
   - What's the specific catalyst (earnings, FDA, sector rotation)?
   - What's the invalidation condition (if X happens, thesis breaks)?
   - What's the time horizon (this week vs next quarter)?

4. **Conviction Scoring**
   - 1-3: Weak thesis, high uncertainty
   - 4-6: Moderate conviction, some risks
   - 7-9: Strong thesis, clear catalyst
   - 10: Exceptional setup, high-conviction trade

5. **Fee-Adjusted Returns**
   - Expected move: +5%?
   - Fees: -0.4%
   - Net expected: +4.6%
   - Hurdle rate: 0.5% → ✅ PASS → Recommend BUY

### Phase 5: Self-Calibration via Backtesting

```python
# src/backtester.py: run_backtest()

For each past recommendation in data/recommendations_log/:
  1. Extract action (BUY, ADD, HOLD, TRIM, SELL)
  2. Extract conviction (1-10)
  3. Find historical price at trade entry date
  4. Compare to current price
  5. Calculate actual return
  6. Stratify by conviction to identify blind spots

Example findings:
  "Trades I marked 8/10 conviction have 72% hit rate"
  "Trades marked 4/10 have only 38% hit rate" → lower conviction threshold
  "NVDA recommendations beat baseline by +3.2%" → calibrate towards NVDA conviction
```

Claude **uses this feedback** in the next session to adjust conviction scores.

---

## 📡 How Data Reaches the Program

### Flow 1: CSV Upload (Wealthsimple)

```
1. User exports Holdings CSV from Wealthsimple
   File: holdings-report-2026-04-29.csv
   
2. Program detects via find_csv_by_date():
   a. Checks ~/Downloads/ (most common)
   b. Searches entire home directory
   c. Checks temp folder (temporary_upload/)
   
3. User confirms: "Is this the correct file?" (Y/N)
   
4. Program copies to temp folder:
   temporary_upload/holdings-report-2026-04-29.csv
   
5. Program parses CSV and normalizes:
   - Strip whitespace from all fields
   - Remove quotes from values
   - Parse numeric fields (quantity, cost, price)
   - Deduplicate share classes (GOOGL vs GOOG)
```

**Code:** `src/main.py:find_csv_by_date()`, `src/main.py:copy_csv_to_temp()`, `src/portfolio_loader.py:parse_holdings_csv()`

### Flow 2: yfinance (Market Data)

```
1. Program gets list of tickers from portfolio + watchlist
   Example: ["NVDA", "MSFT", "PLTR", "ARM", "IONQ", ...]
   
2. For each ticker, make parallel requests:
   - Fetch current price + bid-ask
   - Fetch 10 months of historical OHLCV
   - Fetch fundamental info (PE, market cap, sector, industry)
   - Fetch last 7 days of news headlines
   
3. yfinance queries Yahoo Finance API:
   GET https://query2.finance.yahoo.com/v10/finance/quoteSummary/NVDA
   GET https://query1.finance.yahoo.com/v7/finance/chart/NVDA?interval=1d
   GET https://feeds.finance.yahoo.com/news/rss?symbols=NVDA
   
4. Program caches response for 1 hour (pickle in data/.cache/)
   - Avoids redundant requests if user runs again
   - Speeds up cold-cache runs from ~60s to ~10s (parallel fetching)
   
5. Compute technical indicators:
   RSI, MACD, Bollinger Bands, SMA 50/200, volume spike ratio
```

**Code:** `src/market_data.py:get_market_data()`, `src/market_data.py:compute_indicators()`

### Flow 3: Anthropic Claude API

```
1. Program constructs JSON payload with all data:
   {
     "portfolio": {...},
     "market_data": {...},
     "news": {...},
     "fees": {...},
     "recent_activities": {...},
     "backtest_summary": {...},
     "settings": {...}
   }
   
2. Program sends HTTP request:
   POST https://api.anthropic.com/v1/messages
   Authorization: Bearer sk-ant-api03-...
   Body: structured prompt + data
   
3. Anthropic servers process via Claude Opus 4.7:
   - Input tokens counted (~4000-6000 for typical session)
   - Model reasons through multi-step analysis
   - Generates JSON response with recommendations
   
4. Response is cached via prompt caching:
   - Same portfolio structure = cache HIT
   - Saves ~3000 input tokens on next request (~$0.015 savings)
   - Cache TTL: 5 minutes
   
5. Program parses JSON response:
   - Extract each ticker's recommendation
   - Validate conviction scores (1-10)
   - Validate expected returns are realistic
   - Extract thesis text
   
6. Save to data/recommendations_log/YYYYMMDD_HHMM_morning.json
   - Used for backtesting
   - Used for drift tracking
   - Used for self-calibration
```

**Code:** `src/claude_analyst.py:call_claude()`

---

## ✅ API Accessibility

| API | Free? | Auth Required? | Availability | Auth Method |
|-----|-------|----------------|--------------|-------------|
| yfinance (Yahoo Finance) | ✅ YES | ❌ NO | Public data, all users | No API key |
| Wealthsimple CSV | ✅ YES | ✅ YES (login) | Premium account holders only | Account login |
| Anthropic Claude | ❌ PAID | ✅ YES | All users with API key | API key from console |

### Cost Breakdown

**Per run** (assuming 18 tickers, ~4500 input tokens):

| Component | Cost | Notes |
|-----------|------|-------|
| Sonnet 4.6 | $0.09 | Recommended for daily use |
| Opus 4.7 | $0.45 | Better for complex portfolios |
| yfinance | $0 | Completely free |
| Wealthsimple | Included | Free with Premium account |

**Monthly** (2 runs/day):

| Model | Daily | Monthly |
|-------|-------|---------|
| Sonnet 4.6 | $0.18 | ~$5.40 |
| Opus 4.7 | $0.90 | ~$27.00 |

---

## 🔄 Caching & Efficiency

### Prompt Caching (Claude API)

The system implements **prompt caching** to reduce costs:

```
Request 1 (morning):
  System prompt (stable)     → cache_control: ephemeral
  Market data (volatile)     → regular input
  Portfolio (stable)         → cache_control: ephemeral
  Cost: $X tokens
  
Request 2 (afternoon, same portfolio):
  System prompt              → HIT ✓ (cached)
  Market data (refreshed)    → new
  Portfolio (same)           → HIT ✓ (cached)
  Cost: $X - cached_tokens (20-30% savings typical)
```

### Data Caching (Local Pickle)

```
data/.cache/market_data/
  NVDA_10.pkl              → expires 1 hour after creation
  MSFT_10.pkl              → 
  ...
  
data/.cache/news/
  NVDA.pkl                 → expires 1 hour
  MSFT.pkl                 →
  
data/.cache/historical_price/
  NVDA_2026-04-24.pkl      → expires 30 days
  ...
```

This massively speeds up repeated runs:
- Cold cache (all data fresh): ~60s (serial) → ~10s (parallel)
- Warm cache (most data cached): ~2s

---

## 🤔 Other Free APIs Worth Considering

### 1. **Alpha Vantage** (Alternative to yfinance)

```python
# Free tier: 5 API calls/minute, 500/day
# Paid tier: $200+/month

Key advantages over yfinance:
  ✓ More reliable (dedicated service, not scraping)
  ✓ Official stock market data
  ✓ Technical indicators built-in (RSI, MACD, etc.)
  ✓ Forex + crypto support
  
Key disadvantages:
  ✗ Rate limited (5/min on free tier)
  ✗ No news headlines (separate API)
  ✗ Less fundamentals data than Yahoo
  
When to use:
  - If yfinance becomes unstable
  - For more reliable batch processing
  - When you need guaranteed uptime
  
Cost: FREE tier (limited), or $200/month for professional

API Key: https://www.alphavantage.co/
```

**Example:**
```python
import requests
response = requests.get(
    'https://www.alphavantage.co/query',
    params={
        'function': 'GLOBAL_QUOTE',
        'symbol': 'NVDA',
        'apikey': 'YOUR_KEY'
    }
)
```

### 2. **Finnhub** (Fundamental + News)

```python
# Free tier: 60 API calls/minute
# News + fundamentals focus (less technical data)

Key advantages:
  ✓ Excellent news sentiment (not just headlines)
  ✓ Company fundamentals (earnings, dividends, etc.)
  ✓ Very generous free tier (60 calls/min)
  ✓ Simple REST API
  
Key disadvantages:
  ✗ No historical candle data (need yfinance)
  ✗ Limited technical indicators
  ✗ Missing some markets (only major US stocks)
  
When to use:
  - Supplement yfinance for better news sentiment
  - For company fundamental analysis
  - When you need more API calls per minute
  
Cost: FREE tier (excellent), or $99/month professional

API Key: https://finnhub.io/
```

**Example:**
```python
import requests
response = requests.get(
    'https://finnhub.io/api/v1/news',
    params={
        'symbol': 'NVDA',
        'token': 'YOUR_KEY'
    }
)
# Returns: [{headline, summary, source, sentiment_score, ...}, ...]
```

### 3. **IEX Cloud** (Institutional-grade, Freemium)

```python
# Free tier: 100 messages/month (very limited)
# Paid tier: $9-99/month depending on features

Key advantages:
  ✓ Institutional-grade data quality
  ✓ Real-time stock prices (not delayed)
  ✓ Large corpus of companies
  ✓ Python SDK available
  
Key disadvantages:
  ✗ Very limited free tier (100/month)
  ✗ Expensive for frequent use
  ✗ Overkill for retail use cases
  
When to use:
  - If you need guaranteed reliability
  - For institutional/professional trading
  - When you have budget for data API
  
Cost: FREE tier (very limited), $9-99/month

API Key: https://iexcloud.io/
```

### 4. **Twelve Data** (Modern Alternative)

```python
# Free tier: 800 API calls/day, 2 requests/second
# Good balance of free tier and data quality

Key advantages:
  ✓ Comprehensive data (stocks, forex, crypto, ETFs)
  ✓ Real-time data included in free tier
  ✓ Good technical indicators
  ✓ News feeds
  ✓ Global markets (not just US)
  
Key disadvantages:
  ✗ Smaller company (less established than Yahoo/Alpha)
  ✗ API design is more complex
  ✗ Fundamentals data limited on free tier
  
When to use:
  - For international/emerging markets
  - For crypto alongside stocks
  - When you need higher free tier limits
  
Cost: FREE tier (good), or $50-500/month

API Key: https://twelvedata.com/
```

### 5. **Polygon.io** (Professional Alternative)

```python
# Free tier: 5 API calls/minute
# Options, crypto, forex support

Key advantages:
  ✓ Professional-grade data
  ✓ Full options chain data (Greeks)
  ✓ Crypto markets included
  ✓ Very detailed historical data
  
Key disadvantages:
  ✗ Overkill for basic stock analysis
  ✗ More complex API
  ✗ Limited free tier
  
When to use:
  - For options analysis
  - For professional traders
  - When you need extreme data granularity
  
Cost: FREE tier (limited), $199+/month

API Key: https://polygon.io/
```

### 6. **EODHD** (End-of-Day Historical Data)

```python
# Free tier: 20 API calls/day, limited symbols
# Excellent for EOD data (when you don't need real-time)

Key advantages:
  ✓ Clean, reliable EOD data
  ✓ Fundamentals + technicals
  ✓ Global markets (40,000+ symbols)
  ✓ Affordable if you upgrade
  
Key disadvantages:
  ✗ Very limited free tier (20/day)
  ✗ End-of-day only (not intraday)
  ✗ Requires API key even for free
  
When to use:
  - For daily/weekly trading strategies
  - When you need global market coverage
  - For automated backtesting
  
Cost: FREE tier (very limited), $20-100/month

API Key: https://eodhd.com/
```

---

## 🎯 Recommended API Stack for Beginners

### Tier 1: Completely Free

```
yfinance (primary)
  ├─ Prices, history, fundamentals
  ├─ News headlines
  └─ No limits, no auth required

+ Finnhub (supplement)
  ├─ Better news sentiment
  └─ 60 calls/minute free
  
+ Manual CSV from Wealthsimple
  └─ Your portfolio data
  
Cost: $0/month
Limitation: News sentiment is basic (VADER)
```

**Good for:** Most retail traders, small portfolios

### Tier 2: Minimal Cost ($0.09 per run)

```
yfinance (primary)
+ Anthropic Claude Sonnet 4.6 (analysis)
  ├─ Multi-step reasoning
  ├─ Conviction scoring
  └─ ~$0.09 per run

Cost: $0-5/month (free tier) or ~$5/month (2x daily)
Gain: AI-powered analysis, backtesting, self-calibration
```

**Good for:** Active traders who run 2x daily, want AI insights

### Tier 3: Professional Setup ($0.45 per run)

```
yfinance (primary)
+ Finnhub (sentiment overlay)
+ Anthropic Claude Opus 4.7 (deeper analysis)
  └─ ~$0.45 per run

Optional upgrades:
  + Alpha Vantage ($200/month) for redundancy
  + IEX Cloud ($50/month) for real-time data

Cost: $25-300/month depending on frequency
Gain: Redundancy, professional-grade analysis, higher accuracy
```

**Good for:** Full-time traders, managed portfolios, hedge funds

---

## 🔐 Privacy & Security Notes

### Data Retention

1. **Wealthsimple CSVs**
   - Stored locally in `temporary_upload/` folder (user's computer)
   - Can be deleted after session completes
   - Never sent to third parties (except Claude for analysis)

2. **Claude Analysis**
   - Sent to Anthropic API (encrypted HTTPS)
   - Used for analysis only
   - Logged by Anthropic (standard API logging)
   - Deleted after response returned (no long-term storage)

3. **yfinance Data**
   - Cached locally in `data/.cache/` (public market data)
   - 1-hour TTL for prices/news
   - 30-day TTL for historical prices
   - No sensitive user data (tickers are public)

4. **Recommendations**
   - Stored in `data/recommendations_log/` (local, encrypted?)
   - Reported back to Claude for self-calibration (for accuracy)
   - Can be deleted manually

### API Key Security

- **Anthropic API Key**
  - Store in `.env` file (git-ignored)
  - Never commit to version control
  - Treat like password; rotate periodically
  
- **Other APIs**
  - Same best practices
  - Consider using environment variables
  - Audit API key usage regularly

---

## 📈 Example: Full Signal Analysis for NVDA

### Input Data

```json
{
  "ticker": "NVDA",
  "current_price": 208.27,
  "change_1d": +4.32%,
  "change_5d": +8.91%,
  "pe_ratio": 54.3,
  "market_cap": 5.12T,
  "52w_high": 228.50,
  "52w_low": 89.20,
  "rsi_14": 72.4,  // overbought
  "macd_hist": 8.2,  // bullish momentum
  "bb_pct": 0.78,  // near upper band
  "sma_50": 198.30,
  "price_vs_sma50": +5.0%,
  "volume_spike": 1.8x,  // above normal
  "news_sentiment": 0.65,  // bullish
  "portfolio_pct": 12.5%,  // concentration risk
  "cost_basis": 145.30,
  "unrealized_return": +43.3%
}
```

### Claude Analysis

> **NVDA: Position sizing risk vs momentum opportunity**
>
> **Current Setup:**
> - Price broke above SMA-50, MACD histogram positive (momentum confirmed)
> - RSI 72.4 suggests overbought, but above 70 is normal in strong trends
> - Volume spike (1.8x) shows institutional participation
> - News sentiment 0.65 (positive catalysts: AI adoption, data center)
>
> **The Problem:**
> - NVDA already 12.5% of portfolio (above 10% concentration limit)
> - PE ratio 54.3 is elevated (market pricing in 25%+ growth expectations)
> - Price at 91% of 52-week high (limited room to upside before consolidation)
>
> **Recommendation:**
> - **ACTION: HOLD** (not ADD)
> - **THESIS:** Momentum is real, but position is already large. Better to:
>   - Deploy new capital to underweight positions (ARM, PLTR below SMA-50)
>   - Rebalance if NVDA hits 12% of portfolio again
>   - Watch for RSI > 80 (exhaustion signal) as exit
> - **TIME HORIZON:** 1-3 months
> - **CONVICTION:** 7/10 (strong momentum, but concentration risk is real)
> - **NET EXPECTED RETURN:** N/A (HOLD = no entry fees)

---

**Last Updated:** April 25, 2026  
**Document Version:** 1.0.0  
**Author:** Tech Stock Team + Claude Opus 4.7
