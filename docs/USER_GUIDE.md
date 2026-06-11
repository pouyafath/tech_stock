# tech_stock User Guide

This guide explains how to install, configure, run, update, and understand
tech_stock. For a shorter setup path, start with
[QUICKSTART.md](../QUICKSTART.md).

## Product Scope

tech_stock is a local portfolio research application. It reads Wealthsimple CSV
exports, fetches available market context, asks Claude to produce structured
recommendations, applies deterministic quality checks, and saves reports for
review.

It does not:

- Connect to a brokerage account.
- Place, modify, or cancel orders.
- Guarantee that a quote is live or executable.
- Replace verification of news, fees, taxes, or order details.
- Provide financial advice.

## Supported Platforms And Interfaces

| Platform | Packaged application | Source installation |
|---|---|---|
| macOS | `.dmg` containing `tech_stock.app` | Supported |
| Windows | Inno Setup installer and zipped application | Supported |
| Linux | AppImage where the release build succeeds | Supported |

| Interface | Description |
|---|---|
| Desktop App | Embedded Tkinter dashboard. No browser is required. |
| Streamlit | Local browser dashboard with onboarding, uploads, comparisons, and downloads. |
| Textual | Rich terminal dashboard with keyboard controls. |
| CLI | Original interactive and scriptable command-line workflow. |

All interfaces use the same analysis pipeline and output files.

## Installation

### Platform options at a glance

| Platform | App-based option | Terminal-based option |
|---|---|---|
| macOS | Install `tech_stock.dmg`, then open the embedded Desktop App | Clone the source and run `./run.sh` or `python src/main.py` |
| Windows | Install `tech_stock_setup.exe` or extract `tech_stock-windows.zip` | Clone the source and run `python src\main.py` |
| Linux | Run `tech_stock-x86_64.AppImage` when available | Clone the source and run `./run.sh` or `python src/main.py` |

### Packaged application

1. Open the [GitHub Releases page](https://github.com/pouyafath/tech_stock/releases).
2. Download the latest package for your operating system.
3. Install or extract the package.
4. Launch tech_stock and choose **Desktop App**.
5. Add an Anthropic API key in **API Checks** before a real paid run.

Packaged applications use `~/Documents/tech_stock/` as the default writable
workspace. Application updates do not remove this workspace.

Current macOS packages are ad-hoc signed rather than Apple-notarized. If macOS
blocks the first launch, follow
[Troubleshooting: macOS blocks the app](TROUBLESHOOTING.md).

### Source installation: macOS or Linux

```bash
git clone https://github.com/pouyafath/tech_stock.git
cd tech_stock

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

chmod +x run.sh run-ui.sh
./run.sh
```

### Source installation: Windows PowerShell

```powershell
git clone https://github.com/pouyafath/tech_stock.git
cd tech_stock

py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

python src\desktop_app.py
```

To create the API key file in PowerShell:

```powershell
Copy-Item API_KEYS.template.txt API_KEYS.txt
notepad API_KEYS.txt
```

If PowerShell blocks virtual-environment activation:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then run `.\.venv\Scripts\Activate.ps1` again.

## Demo Mode

Demo mode uses bundled sample holdings, activities, and a cached recommendation
log. It does not require API keys and does not spend Anthropic tokens.

```bash
python src/main.py --demo
```

You can also choose **Try demo** in the launcher or first-run Streamlit wizard.

Demo mode is useful for:

- Confirming that the UI starts.
- Learning the report structure.
- Testing report rendering and dashboard view models.
- Verifying an installation before adding private data.

## API Keys

### Required key

`ANTHROPIC_API_KEY` is required for real Claude-generated recommendations.

### Optional enrichment keys

| Environment variable | Source | Typical contribution |
|---|---|---|
| `FINNHUB_API_KEY` | Finnhub | Analyst recommendations, earnings calendar, insider activity, sentiment |
| `POLYGON_API_KEY` | Polygon | Snapshot and previous-session market data where plan entitlements allow |
| `TWELVE_DATA_API_KEY` | Twelve Data | Quote redundancy and some non-US symbol support |
| `FRED_API_KEY` | FRED | Rates, yield curve, CPI, VIX, and FX context |
| `COINGECKO_API_KEY` | CoinGecko | Crypto market risk context |
| `ALPHA_VANTAGE_API_KEY` | Alpha Vantage | Optional news and earnings enrichment |

API provider limits and available fields change over time and vary by plan.
tech_stock treats optional sources as enrichment, not as a requirement for a
successful run.

### Key file methods

The simple method is:

```bash
cp API_KEYS.template.txt API_KEYS.txt
```

Then edit `API_KEYS.txt`.

The advanced method is:

```bash
cp .env.example .env
```

Then edit `.env`.

The Desktop App's **API Checks** tab can add, update, remove, discover, and test
keys. It also shows the active file-based storage mode and exact search paths.

Never commit `API_KEYS.txt` or `.env`.

## Wealthsimple Inputs

### Holdings report

A real run should use a fresh Wealthsimple holdings report:

```text
holdings-report-YYYY-MM-DD.csv
```

The app expects position-level fields including:

- Symbol
- Quantity
- Market Price
- Market Price Currency
- Market Value
- Book Value (Market)
- Market Unrealized Returns

The exact exported values are used for position sizing and quote reconciliation,
so export a fresh report before a paid run.

### Activities export

The optional activities export normally looks like:

```text
activities-export-YYYY-MM-DD.csv
```

It contains transaction-level fields such as:

- Account information
- Activity type and subtype
- Direction
- Symbol and name
- Quantity and unit price
- Transaction and settlement dates
- Cash amount and commission

Use the longest available history when possible. The app uses it for FIFO
holding-day calculations and recent execution checks.

### Common input mistake

Do not choose an activities export in the Holdings field. These are different
schemas. Newer versions of tech_stock detect a swapped file and show an
actionable correction message.

### File discovery

Interactive flows search common locations for recent files and ask the user to
confirm a detected path before running. You can always browse to a different
file.

Uploaded or copied files are stored in `temporary_upload/` under the active
workspace.

## Running Reports

### Desktop App

1. Open **Run Report**.
2. Select the session: morning or afternoon.
3. Select Sonnet or Opus.
4. Review USD and CAD budget values.
5. Confirm the Holdings CSV path.
6. Confirm or skip the Activities CSV path.
7. Preview holdings.
8. Run the report.

The Desktop App shows progress and generated output paths.

### Interactive CLI

```bash
python src/main.py
```

The CLI prompts for the session, budgets, detected CSV paths, and model.

### Direct CLI

```bash
python src/main.py morning \
  --holdings ~/Downloads/holdings-report-2026-06-04.csv \
  --activities ~/Downloads/activities-export-2026-06-04.csv
```

Additional examples:

```bash
# Afternoon run
python src/main.py afternoon --holdings ~/Downloads/holdings-report.csv

# Use Opus
python src/main.py morning --model opus --holdings ~/Downloads/holdings-report.csv

# Also apply recommendations to the local paper portfolio
python src/main.py morning --paper --holdings ~/Downloads/holdings-report.csv

# Headless run for scheduling
python src/main.py --non-interactive --session-type morning \
  --holdings ~/Downloads/holdings-report.csv

# Override the configured monthly budget cap for one run
python src/main.py morning --force --holdings ~/Downloads/holdings-report.csv
```

### Launcher

On macOS and Linux:

```bash
./run.sh
```

Direct launcher choices:

```bash
./run.sh 1    # CLI
./run.sh 2    # Streamlit
./run.sh 3    # Textual
./run.sh 4    # Desktop App
./run.sh 5    # Update check
```

## Interface Guide

### Desktop App

The Desktop App is the primary browser-free experience. Its available views
include:

- **Dashboard**: next action, risk metrics, Data Confidence, action queue,
  quality warnings, stops, drift, hedge ideas, and market context.
- **Buy Signals**: source-backed BUY/ADD and add-on-dip ideas with readiness
  filters, quote details, targets, catalysts, warnings, and risk controls.
- **Run Report**: model, budget, CSV selection, preview, and report execution.
- **Report Viewer**: styled markdown display, search, and latest report loading.
- **History**: previous report browsing and rendering.
- **Config Editor**: validated editing for settings, watchlist, and fallback
  portfolio JSON.
- **API Checks**: key management, discovery paths, and connectivity checks.
- **Diagnostics**: preflight status, source degradation, recent errors, spend,
  and support information.
- **Updates**: release checks, cache force-refresh, checksum status, update
  actions, and logs.

### Streamlit

Start the browser dashboard:

```bash
python -m streamlit run ui/streamlit_app.py
```

Streamlit is the best interface for the first-run wizard, CSV upload, browser
markdown rendering, history comparison, chart-heavy views, and file downloads.

### Textual

Start the terminal dashboard:

```bash
python ui/textual_app.py
```

Useful shortcuts:

- `r`: refresh the active view.
- `Ctrl+R`: run a report.
- `Ctrl+S`: save valid JSON in the editor.

### CLI

The CLI is the best choice for scheduled runs, automation, remote terminals, and
minimal overhead.

## Understanding A Report

Read the report in this order:

1. **Data Confidence**: summarizes whether the available data is suitable for
   action.
2. **Report Quality Warnings**: lists deterministic issues and required review.
3. **Trader Action Plan**: prioritizes actions and sizes.
4. **Portfolio Health and Risk Dashboard**: shows exposure and concentration.
5. **Recommendation details**: explains thesis, catalyst, risk controls,
   expected range, and invalidation.
6. **Sources and degradation**: shows what data was available or missing.

Readiness states:

| State | Meaning |
|---|---|
| `TRADE_READY` | Fresh enough data and no blocking quality issue was detected. |
| `REVIEW_FIRST` | The idea may be usable, but warnings or manual review remain. |
| `BLOCKED` | A blocking data, catalyst, market-data, or position-cap issue exists. |

No readiness state guarantees an executable or profitable trade.

## Settings

The main configuration file is `config/settings.json`.

Important settings include:

| Setting | Purpose |
|---|---|
| `claude_model` | Default Claude model |
| `budget_cad` | Default CAD deployment budget |
| `monthly_budget_usd` | Optional monthly Anthropic spend cap; `0` means no cap |
| `account_type` | Describes the fee-model assumption |
| `fee_model` | Commission, FX, spread, and regulatory assumptions |
| `max_position_pct` | Single-position cap used by quality checks |
| `quote_reconciliation_threshold_pct` | Holdings-vs-quote mismatch warning threshold |
| `enable_enrichment` | Master switch for optional enrichment clients |
| `alpha_vantage_enabled` | Enables the rate-limited Alpha Vantage enrichment path |
| `enable_two_pass_review` | Enables the second Claude critique pass |
| `cache_enabled` | Enables local data caching |

Review the fee model before using the app with a non-default Wealthsimple
account or another broker.

## Workspace And Files

### Workspace selection

- Source checkout: the project directory.
- Packaged application: `~/Documents/tech_stock/`.
- Override: set `TECH_STOCK_HOME=/your/path`.

### File layout

```text
tech_stock/
  config/
    settings.json
    watchlist.json
    portfolio.json
  data/
    recommendations_log/
    decision_journal.json
    cost_log.jsonl
    samples/
  logs/
  reports/
  temporary_upload/
  API_KEYS.txt
  .env
```

### Output files

Each successful report run normally creates:

- Markdown report: `reports/<timestamp>_<session>.md`
- Recommendation CSV: `reports/<timestamp>_<session>_recommendations.csv`
- JSON session log: `data/recommendations_log/<timestamp>_<session>.json`
- Cost record: `data/cost_log.jsonl`
- Decision-journal additions: `data/decision_journal.json`

## Diagnostics

Run the preflight doctor before a paid run or when troubleshooting:

```bash
python src/main.py doctor --json
```

Force a live GitHub release lookup:

```bash
python src/main.py doctor --json --force-refresh
```

Verify whether an older installed app would see the newest published release
without applying an update:

```bash
python src/main.py doctor --json --force-refresh --simulate-current-version 1.27.2
```

Also validate bundled demo data and UI view models without Anthropic spend:

```bash
python src/main.py doctor --json --force-refresh --demo-smoke
```

The doctor payload includes:

- Installed and latest published version.
- Optional simulated installed version for release-health checks.
- Update cache age and source.
- Release asset and checksum availability.
- Workspace paths and writability.
- API key discovery and configured-source status.
- Holdings and activities CSV freshness.
- Monthly Anthropic budget status.
- Optional demo smoke-test results.

## Updates

Update checks are available from the launcher, Desktop App, Streamlit, Textual,
and CLI.

```bash
python src/main.py check-update
python src/main.py update
```

Manual checks force-refresh GitHub Releases. Startup checks may use a short-lived
cache.

Packaged updates download the platform asset and verify it against
`SHA256SUMS.txt` when the release provides checksums. Source checkouts update
with `git pull --ff-only`.

The workspace is kept separate from application files, so updates preserve user
reports, configuration, uploads, API key files, logs, and journals.

## Scheduling

Use the Streamlit **Schedule** view to create per-user schedules without
requiring administrator access. It generates platform-appropriate launchd, Task
Scheduler, or cron configuration.

Scheduled commands use `--non-interactive` and `--session-type` so they do not
wait for input.

See [COOKBOOK.md](COOKBOOK.md) for examples.

## Privacy

Stored locally:

- Wealthsimple CSV files.
- Reports and recommendation logs.
- Configuration and watchlist files.
- Decision journal and performance history.
- API key files.
- Diagnostics and update logs.

Sent externally during a paid run:

- Structured portfolio and market context required for Claude analysis.
- Ticker and market-data requests to enabled enrichment providers.

API keys are redacted from diagnostics and excluded from sanitized workspace
exports.

## Next Reading

- [Troubleshooting](TROUBLESHOOTING.md)
- [How Analysis And Signals Work](../ANALYSIS_AND_SIGNALS.md)
- [Operational Cookbook](COOKBOOK.md)
- [Architecture](ARCHITECTURE.md)
