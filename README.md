# tech_stock

A local, Claude-powered portfolio analysis application for Wealthsimple CSV
exports. It combines portfolio holdings, market data, optional enrichment
sources, deterministic risk checks, and a two-pass Claude review to produce
trader-facing reports.

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-green)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-lightgrey)](LICENSE)
[![Latest Release](https://img.shields.io/github/v/release/pouyafath/tech_stock)](https://github.com/pouyafath/tech_stock/releases)

> tech_stock is a research and decision-support tool. It is not a broker, does
> not place trades, and does not provide financial advice. Always verify prices,
> catalysts, account fees, and order details before trading.

## What It Does

tech_stock reads a Wealthsimple holdings report and, optionally, an activities
export. It then:

1. Normalizes positions, currencies, CDRs, share classes, ETFs, and cash.
2. Fetches available quotes, history, technical indicators, fundamentals, news,
   macro context, and analyst data.
3. Calculates portfolio concentration, volatility, beta, drawdown, correlation,
   position age, trailing-stop, and fee-aware risk signals.
4. Sends structured context to Claude for an initial recommendation.
5. Runs deterministic quality gates and asks Claude to revise the result.
6. Writes a markdown report, recommendation CSV, JSON session log, cost record,
   and decision-journal entries.
7. Shows the same structured results in the Desktop, Streamlit, Textual, and CLI
   interfaces.

Typical recommendations use `BUY`, `ADD`, `HOLD`, `TRIM`, and `SELL`, with
conviction, time horizon, risk controls, catalyst status, trade readiness, and
quality warnings.

## Main Features

- Four interfaces: embedded Desktop App, Streamlit web dashboard, Textual TUI,
  and the original CLI.
- Source-backed Buy Signals with `Trade Ready`, `Review First`, and `Blocked`
  readiness states.
- Data Confidence summaries for quote freshness, source coverage, catalyst
  coverage, and warning counts.
- Two-pass Claude review with deterministic quality gates between passes.
- Trader action queue, deterministic trim/sell sizing, risk controls, and
  fee-aware expected returns.
- Portfolio risk dashboard with concentration, company exposure, beta,
  volatility, drawdown, correlated pairs, and hedge suggestions.
- Report history, backtesting, decision journal, thesis tracking, performance
  history, learning views, notifications, and scheduling.
- API health checks, editable API key management, preflight diagnostics, demo
  mode, monthly budget controls, and checksum-verified updates.
- Local-first storage: reports, logs, settings, uploaded CSVs, and API key files
  remain on the user's machine.

## Requirements

- A supported platform: macOS, Windows, or Linux.
- Python 3.11 or newer when running from source.
- A Wealthsimple holdings CSV for a real portfolio run.
- An Anthropic API key for paid Claude-generated recommendations.
- Optional API keys for richer enrichment data.

You do not need a Wealthsimple Premium account to run the software. The default
fee model is configured for a Wealthsimple Premium USD account, so users with a
different account type or broker must review and adjust `config/settings.json`.

## Choose How To Run It

| Interface | Best for | Browser required |
|---|---|---|
| Desktop App | Primary embedded dashboard and normal daily use | No |
| Streamlit | Full browser dashboard, uploads, comparisons, and onboarding | Yes |
| Textual | Keyboard-driven terminal dashboard | No |
| CLI | Automation, scheduling, scripting, and fastest execution | No |

All interfaces call the same report pipeline and write the same output formats.

## Quick Start

### Option A: Install a packaged application

Download the latest package from the
[GitHub Releases page](https://github.com/pouyafath/tech_stock/releases):

- macOS: `tech_stock.dmg`
- Windows: `tech_stock_setup.exe` or `tech_stock-windows.zip`
- Linux: `tech_stock-x86_64.AppImage`

Open the application and choose **Desktop App**. The packaged application stores
user data in `~/Documents/tech_stock/` by default.

Current macOS releases are ad-hoc signed, not Apple-notarized. On first launch,
macOS may block the app. See
[Troubleshooting: macOS blocks the app](docs/TROUBLESHOOTING.md).

### Option B: Run from source

```bash
git clone https://github.com/pouyafath/tech_stock.git
cd tech_stock

python3 -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .\.venv\Scripts\Activate.ps1   # Windows PowerShell

python -m pip install -r requirements.txt
cp API_KEYS.template.txt API_KEYS.txt
```

Add your Anthropic key to `API_KEYS.txt`, then launch:

```bash
./run.sh                         # macOS/Linux launcher
python src/main.py               # interactive CLI on any platform
python src/desktop_app.py        # embedded Desktop App
python -m streamlit run ui/streamlit_app.py
python ui/textual_app.py
```

For a no-key, no-cost tour:

```bash
python src/main.py --demo
```

For the complete five-minute setup, see [QUICKSTART.md](QUICKSTART.md).

## Wealthsimple CSV Inputs

### Holdings CSV: required for a real portfolio run

Use a Wealthsimple holdings report, normally named:

```text
holdings-report-YYYY-MM-DD.csv
```

The holdings report contains position-level fields such as symbol, quantity,
market price, market value, book value, and unrealized return.

### Activities CSV: optional but recommended

Use an activities export, normally named:

```text
activities-export-YYYY-MM-DD.csv
```

The activities export contains transaction-level fields such as activity type,
direction, settlement date, quantity, unit price, and cash amount. It improves
holding-day calculations and previous-session execution checks.

Do not select an activities export as the Holdings file. The app detects this
mistake and explains which file belongs in each field.

## API Keys

Create a key file from the template:

```bash
cp API_KEYS.template.txt API_KEYS.txt
```

Only `ANTHROPIC_API_KEY` is required for Claude-generated recommendations.
Optional keys improve source coverage:

| Source | Used for |
|---|---|
| Finnhub | Earnings calendar, analyst recommendations, insider activity, news sentiment |
| Polygon | Snapshot and previous-session market data where the configured plan permits it |
| Twelve Data | Quote redundancy, including some non-US symbols |
| FRED | Rates, yield curve, CPI, VIX, and FX context |
| CoinGecko | Crypto risk-on/risk-off context |
| Alpha Vantage | Optional news and earnings enrichment |

Provider availability, limits, entitlements, and freshness vary by API plan.
Missing optional keys do not stop a run; the app records source degradation and
coverage gaps.

API keys may be stored in `API_KEYS.txt` or `.env`. The app shows the active
storage mode and discovered paths in **API Checks**. Never commit either file.

## Common Commands

```bash
# Interactive CLI
python src/main.py

# Direct report runs
python src/main.py morning --holdings ~/Downloads/holdings-report-2026-06-04.csv
python src/main.py afternoon \
  --holdings ~/Downloads/holdings-report-2026-06-04.csv \
  --activities ~/Downloads/activities-export-2026-06-04.csv

# Model selection and paper portfolio
python src/main.py morning --model opus --holdings ~/Downloads/holdings-report.csv
python src/main.py morning --paper --holdings ~/Downloads/holdings-report.csv

# Scheduled or headless run
python src/main.py --non-interactive --session-type morning \
  --holdings ~/Downloads/holdings-report.csv

# Diagnostics and updates
python src/main.py doctor --json
python src/main.py doctor --json --force-refresh --demo-smoke
python src/main.py check-update
python src/main.py update
```

Windows users should replace `/` with `\` where appropriate and use paths such
as `%USERPROFILE%\Downloads\holdings-report.csv`.

## Outputs And Storage

The active workspace is:

- Source checkout: the project folder.
- Packaged application: `~/Documents/tech_stock/`.
- Custom location: set `TECH_STOCK_HOME=/your/path`.

Important workspace paths:

| Path | Purpose |
|---|---|
| `reports/` | Markdown reports and recommendation CSVs |
| `data/recommendations_log/` | Structured JSON snapshot for each session |
| `data/decision_journal.json` | User decisions and outcomes |
| `data/cost_log.jsonl` | Anthropic usage and estimated cost history |
| `logs/` | Diagnostics and update logs |
| `temporary_upload/` | Copied or uploaded Wealthsimple CSVs |
| `config/settings.json` | Model, budget, risk, fee, cache, and enrichment settings |
| `config/watchlist.json` | Symbols to analyze without holding |
| `config/portfolio.json` | Optional fallback portfolio |

Updates replace application files, not the workspace. Reports, configuration,
API key files, logs, uploads, and journals are preserved.

## Report Trust Model

The application is designed to make uncertainty visible:

- Quotes include source, timestamp, price basis, and freshness where available.
- Holdings prices are reconciled against fetched quotes.
- Large movers require catalyst context or manual review.
- Missing sources create structured degradation records.
- Quality warnings are shown near the top of reports and in dashboards.
- Buy Signals are classified as ready, review-first, or blocked.
- Reports separate trader action, risk controls, catalyst status, and audit
  rationale.

Use the report as a research memo, not an automatic trading instruction.

## Documentation

| Document | Audience | Contents |
|---|---|---|
| [QUICKSTART.md](QUICKSTART.md) | New users | Five-minute installation and first report |
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | All users | Complete installation, configuration, UI, workflow, storage, and update guide |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | All users | Common errors and recovery steps |
| [ANALYSIS_AND_SIGNALS.md](ANALYSIS_AND_SIGNALS.md) | Traders and auditors | Data sources, signal methodology, quality gates, and limitations |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Developers and auditors | Module map, data flow, storage, and design tenets |
| [docs/COOKBOOK.md](docs/COOKBOOK.md) | Advanced users | Scheduling, budgets, exports, backtests, and operational recipes |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Contributors | Development workflow, testing, and review standards |
| [docs/RELEASE_PROCESS.md](docs/RELEASE_PROCESS.md) | Maintainers | Versioning, CI builds, draft release checks, and publication |
| [CHANGELOG.md](CHANGELOG.md) | Everyone | Release history |

## Development

```bash
python -m pip install -r requirements-dev.txt

PYTHONPATH="$(pwd)" python -m pytest -q
ruff check src/ tests/ ui/ tools/
ruff format --check src/ tests/ ui/ tools/
```

See [CONTRIBUTING.md](CONTRIBUTING.md) before submitting changes.

## Privacy And Security

- Portfolio CSVs, reports, logs, settings, and API key files are stored locally.
- A paid report sends the structured portfolio and market context required for
  analysis to Anthropic.
- Optional enrichment providers receive ticker or market-data requests.
- API keys are redacted from diagnostics and excluded from workspace exports.
- `API_KEYS.txt`, `.env`, generated reports, uploads, caches, and local workspace
  files must not be committed.

## License

MIT. See [LICENSE](LICENSE).
