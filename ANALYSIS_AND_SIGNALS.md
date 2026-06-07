# How tech_stock Analyzes Portfolios And Produces Signals

This document explains the analysis methodology, data sources, quality controls,
and limitations of tech_stock. It is intended for users who want to understand
why the application made a recommendation and for auditors who want to evaluate
the report's trustworthiness.

> tech_stock is a research and decision-support tool. It does not place trades,
> guarantee data freshness, or provide financial advice.

## Summary

tech_stock combines two types of analysis:

1. **Deterministic analysis**: calculations and rules implemented in Python,
   including position sizing, technical indicators, fee assumptions, portfolio
   risk, quote reconciliation, quality warnings, and trade readiness.
2. **Claude analysis**: synthesis of the structured portfolio, market, news,
   catalyst, fee, risk, and historical context into recommendations and written
   rationale.

Claude does not receive an unstructured request to "pick stocks." It receives a
structured context assembled by the application, and its first response is
checked and revised before the final report is rendered.

## End-To-End Pipeline

```text
Wealthsimple holdings CSV
Optional activities CSV
Configuration and watchlist
        |
        v
Portfolio normalization
Ticker, currency, CDR, share-class, ETF, and cash handling
        |
        v
Market data and optional enrichment
Quotes, history, technicals, fundamentals, news, analyst data, macro context
        |
        v
Deterministic analytics
Fees, concentration, beta, volatility, drawdown, correlation, position age
        |
        v
Claude pass 1
Structured recommendation JSON
        |
        v
Quality gates, drift review, previous-session comparison, sizing
        |
        v
Claude pass 2
Complete revised recommendation JSON
        |
        v
Normalization and report generation
Markdown report, CSV table, JSON log, dashboards, journal, cost record
```

## Inputs

### Holdings report

The required real-portfolio input is a Wealthsimple holdings report. It provides
the position quantities, reported market prices and values, book values,
currencies, and unrealized returns used by the application.

The holdings report is a snapshot. Export a fresh file before any paid run.

### Activities export

The optional activities export provides transaction-level history. It improves:

- FIFO holding-day calculations.
- Leveraged ETF holding-period warnings.
- Previous-session execution checks.
- Detection of recent trades that could make a new recommendation a whipsaw.

The activities export is not a substitute for the holdings report.

### Configuration

`config/settings.json` defines assumptions and thresholds such as:

- Claude model and token budget.
- Wealthsimple account and fee assumptions.
- Position and concentration caps.
- Quote mismatch threshold.
- News and history lookback periods.
- Cache behavior.
- Enrichment source switches.
- Risk benchmarks and warning thresholds.

The default fee model describes a Wealthsimple Premium USD account. Users with a
different account type or broker must review it before relying on fee-aware
outputs.

## Data Sources

Data availability, freshness, quotas, and fields vary by provider, symbol,
market, and API plan. tech_stock treats all external data as fallible and records
degradation where possible.

| Source | Required | Typical use |
|---|---|---|
| Wealthsimple CSV | Yes for real portfolio analysis | Positions, quantities, reported values, cost basis, currencies |
| Anthropic Claude | Yes for real recommendations | Structured reasoning, recommendation synthesis, second-pass critique |
| yfinance | No API key | Quotes, history, fundamentals, technical inputs, some news and analyst fields |
| Finnhub | Optional | Analyst recommendations, earnings calendar, insider activity, sentiment |
| Polygon | Optional | Snapshot and previous-session market data where plan entitlements permit |
| Twelve Data | Optional | Quote redundancy and some non-US symbol support |
| FRED | Optional | Rates, yield curve, CPI, VIX, and FX context |
| CoinGecko | Optional | Crypto risk-on/risk-off context |
| Alpha Vantage | Optional and disabled by default | News and earnings enrichment |

Missing optional sources do not stop the report. The application should show the
resulting coverage gap or source degradation.

## Market And Technical Analysis

The market-data layer can calculate or retrieve:

- Current or fallback price, source, timestamp, price basis, previous close, and
  daily change.
- Historical closes and volume.
- 52-week high and low.
- RSI, MACD, Bollinger Bands, SMA 50, SMA 200, and SMA cross state.
- ATR(14), ATR as a percentage of price, and short/medium-term volatility.
- Beta and correlation to configured benchmarks such as SPY, QQQ, and SMH.
- Market capitalization, valuation ratios, FCF yield, margins, dividend fields,
  and analyst target fields where available.
- Optional options-implied move when enabled and available.

Technical indicators are context, not proof. The application should not treat a
single RSI, MACD, or moving-average value as sufficient justification for a
trade.

## News, Catalysts, And Professional Analysis

tech_stock can analyze external professional analysis indirectly through
structured provider data such as analyst recommendations, consensus counts,
target prices, upgrades, downgrades, earnings calendars, insider activity, and
news sentiment.

It does not subscribe to or read private brokerage research reports unless a
configured data source provides that information through its API. It should not
invent individual analyst targets or present unsourced poster-style statistics.

Large movers require special attention:

- A significant move should have a catalyst summary or a manual-review flag.
- BUY/ADD recommendations on large movers should be downgraded or blocked when a
  required catalyst is missing.
- The report should clearly name the catalyst source when one is verified.

## Portfolio Risk Analysis

The deterministic portfolio layer can calculate:

- Position and company-level exposure.
- Sector exposure and concentration.
- Top-three concentration.
- Portfolio beta.
- Annualized volatility.
- Max drawdown estimate.
- Highly correlated pairs.
- Leveraged ETF exposure and holding duration.
- Position age and stale-position risk.
- Trailing-stop state.
- Hedge suggestions when risk thresholds are exceeded.

Economically equivalent lines, such as USD shares and related CDRs, may be
rolled up for exposure analysis while remaining separate tradeable rows.

Inverse ETF hedge suggestions are risk controls, not default recommendations.
They should include sizing caps and risk notes.

## Fee-Aware Analysis

The application compares expected return with the configured trading-cost
hurdle. The default settings include assumptions for:

- Commission.
- FX spread.
- Bid-ask spread by capitalization tier.
- Regulatory fees.

The default configuration is not correct for every account. A CAD account,
currency conversion, another broker, or a different subscription tier can
materially change the result.

Review:

```text
config/settings.json -> account_type
config/settings.json -> fee_model
config/settings.json -> min_net_expected_return_pct
```

## Claude's Role

Claude receives structured context including:

- Portfolio positions and exposure.
- Market data, technical indicators, and fundamentals.
- News, catalyst, analyst, earnings, macro, and risk context.
- Fee assumptions.
- Recent activities.
- Historical recommendation performance.
- Decision-journal scorecard.
- Drift and thesis-tracking context.

Claude is asked to return structured recommendation JSON with fields such as:

- Action: `BUY`, `ADD`, `HOLD`, `TRIM`, or `SELL`.
- Conviction.
- Time horizon.
- Expected move and expected range.
- Thesis and invalidation.
- Risk controls.
- Catalyst verification.
- Manual-review state.
- Hedge suggestions.

The model can still be wrong. The deterministic quality layer exists to make
common failures visible and to force a second review.

## Two-Pass Review

### Pass 1

Claude produces an initial complete recommendation object.

### Deterministic review

The application normalizes the response, evaluates report-quality warnings,
compares the result with previous sessions, applies policy gates, and computes
deterministic sizing.

### Pass 2

Claude receives:

- The first recommendation JSON.
- Quality warnings.
- Drift summary.
- Previous-session comparison.
- Instructions to return a complete revised JSON object.

Both calls contribute to the usage and cost totals shown in the report.

## Quality Controls

Quality controls include both warning generation and policy gates.

Examples:

- Stale or unstamped quote.
- Holdings-vs-quote mismatch.
- Missing catalyst on a large mover.
- Missing enrichment citation.
- Invalid time horizon.
- Oversized position or company exposure.
- Missing risk controls.
- Range inconsistency.
- Missing analyst or insider citation.
- BUY/ADD above a configured position cap.
- Market-data error.
- Leveraged ETF holding-period risk.
- Thesis decay.
- Trailing-stop breach.
- Drawdown circuit breaker.

Warnings include a severity, code, ticker, message, and required action where
applicable.

## Trade Readiness

The UI classifies signals into three readiness states:

| State | Meaning |
|---|---|
| `TRADE_READY` | Fresh enough quote, no blocking warning, and required catalyst/source checks satisfied. |
| `REVIEW_FIRST` | The signal may be usable, but warnings, optional-source degradation, or manual review remain. |
| `BLOCKED` | A stale or unstamped quote, missing required catalyst, market-data error, or position-cap issue prevents action. |

Trade readiness is a quality classification, not a prediction of profitability.

## Data Confidence

Reports and dashboards summarize:

- Quote freshness.
- Source coverage.
- Catalyst coverage.
- Warning count.
- Overall readiness.

The Data Confidence block is the first place to look before reading the action
queue.

## Outputs And Audit Trail

Each successful run normally writes:

| Output | Purpose |
|---|---|
| Markdown report | Human-readable research memo |
| Recommendation CSV | Compact table for review and tracking |
| JSON recommendation log | Structured session snapshot for history and backtesting |
| Cost log entry | Anthropic usage and estimated cost |
| Decision-journal entries | Pending user decisions for later outcome scoring |

Past recommendation logs feed the backtester, drift tracker, performance views,
and learning loop.

## Important Limitations

- External quotes may be delayed, stale, previous-close, or otherwise
  non-executable.
- API provider plans can restrict fields or endpoints.
- News and catalyst coverage can be incomplete.
- Analyst consensus is not independent truth and can be stale.
- Wealthsimple CSV values are snapshots and can differ from fetched quotes.
- Technical indicators are backward-looking.
- Backtest results are based on the application's own historical recommendation
  logs and are not proof of future performance.
- Claude can misinterpret data, overstate confidence, or produce an incorrect
  thesis.
- Taxes, account-specific restrictions, liquidity, order-book depth, and user
  circumstances may not be fully modeled.

## Recommended Review Workflow

Before taking action:

1. Confirm that the holdings CSV is fresh.
2. Read Data Confidence and quality warnings.
3. Verify quote source, timestamp, currency, and previous close.
4. Verify the catalyst for any large mover.
5. Review the account fee and FX assumptions.
6. Check position and company exposure after the proposed trade.
7. Review stop, take-profit, invalidation, and time horizon.
8. Confirm the order type and executable market price in the brokerage app.

## Code References

| Area | Module |
|---|---|
| Holdings parsing | `src/portfolio_loader.py` |
| Activities parsing | `src/activity_loader.py` |
| Market data and indicators | `src/market_data.py` |
| Optional enrichment | `src/enriched_data.py` |
| Claude prompt and calls | `src/claude_analyst.py` |
| Quality warnings and gates | `src/report_quality.py` |
| Data Confidence | `src/data_confidence.py` |
| Portfolio analytics | `src/portfolio_analytics.py` |
| Recommendation sizing | `src/recommendation_sizing.py` |
| Report rendering | `src/report_generator.py` |
| Backtesting | `src/backtester.py` |
| Drift tracking | `src/drift_tracker.py` |
| Decision journal | `src/decision_journal.py` |

For the full module map, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
