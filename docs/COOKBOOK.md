# tech_stock — Cookbook

Common tasks beyond "open the app and click Run."

## Try the demo without any setup

```
./run.sh 2          # menu choice 2 = Streamlit
```

Click "🎬 Try demo" on the launcher OR the secondary "Try demo" button
in the first-run wizard. Streamlit boots with `TECH_STOCK_DEMO_MODE=1`,
loads the bundled `data/samples/recommendation_log_sample.json`, and
shows you a full report against a synthetic Wealthsimple-style portfolio.
No API key, no CSV, no cost.

## Run doctor / preflight diagnostics

Use this before paid runs, before release testing, or when the app says it
is on an older release than GitHub:

```
.venv/bin/python -m src.main doctor --json
.venv/bin/python -m src.main doctor --json --force-refresh
```

The JSON payload includes installed version, latest published release,
update-cache age/source, workspace paths, API-key discovery, API status,
CSV freshness, monthly budget status, and release asset/checksum
availability.

To also validate bundled samples and view-model rendering without
Anthropic spend:

```
.venv/bin/python -m src.main doctor --json --demo-smoke
```

## Run a single CLI report

```
.venv/bin/python -m src.main morning \
    --holdings ~/Downloads/holdings-report-2026-05-27.csv \
    --activities ~/Downloads/activities-export-2026-05-27.csv
```

Or interactive mode (just answer the prompts):

```
.venv/bin/python -m src.main
```

## Schedule daily runs

Open the Streamlit ⏰ Schedule tab → pick morning + afternoon times →
Install. On macOS this writes a launchd plist; on Windows a Task
Scheduler XML; on Linux a crontab line. None require sudo.

Verify it's installed:

```
launchctl list | grep com.techstock     # macOS
schtasks /Query | findstr tech_stock    # Windows
crontab -l | grep tech_stock            # Linux
```

The scheduled command invokes the CLI with `--non-interactive
--session-type {morning,afternoon}` so it can't hang waiting for
input.

## Cap your monthly Anthropic spend

`config/settings.json`:

```json
{
  "monthly_budget_usd": 10.0
}
```

Soft warns at 80%, hard blocks at 100% of the cap. Override a single
run via `--force` or `ALLOW_OVERAGE=1`.

The Diagnostics tab's 💰 Spend sub-section shows total / MTD /
projected-monthly + a 30-day daily chart, all driven by
`data/cost_log.jsonl`.

## Replay an old session

Recommendation logs live in `data/recommendations_log/`. Each is a
self-contained JSON snapshot — model, portfolio, recommendations,
quality warnings, drift, usage, market context.

Open `History` in any UI → pick a file → see the rendered report.
The Performance tab consumes the whole directory to compute portfolio
time-series.

## Inspect or edit settings

Editor tab in Streamlit + Desktop. Three editable JSON files:

- `config/settings.json` — model, budgets, cache TTLs, notifications
- `config/watchlist.json` — tickers to track without holding
- `config/portfolio.json` — fallback portfolio when no CSV is uploaded

Live validation. Save is disabled while invalid.

## Wipe everything

Diagnostics → 🔒 Privacy → check the confirmation box → "Delete all
local data". Wipes reports, recommendation logs, journal, thesis log,
cache, cost log. Settings and API keys are preserved.

If you want EVERYTHING gone (including secrets), close the app and:

```
rm -rf data/ reports/ logs/ exports/ cache/
rm config/.env
```

## Export the workspace for another machine

Diagnostics → 🔒 Privacy → "📦 Export workspace…". Produces a zip in
`exports/`. Secrets (`.env`, `API_KEYS.txt`, the temporary upload
folder) are stripped automatically.

Restore on the other machine by unzipping into the project root.

## Backtest your own past recommendations

```
.venv/bin/python -m src.backtester data/recommendations_log
```

Prints per-action and per-conviction hit-rates. The same data drives
the Learning tab's reliability diagram and walk-forward chart.

## Hook a notification into a custom event

```python
from src.notifications import send

send(
    "Custom alert",
    "Your trailing stop on NVDA was just breached.",
    channel="trailing_stop_breach",
    urgency="critical",
)
```

The channel name is gated by `config/settings.json →
notifications.channels`. Use `general` to bypass channel gating.

## Run the test suite

```
.venv/bin/python -m pytest -q                       # all tests; v1.21 has 588 expected
.venv/bin/python -m pytest tests/test_backtester_calibration.py -v
.venv/bin/python -m pytest -k "horizon"             # match by name
```

## Re-run the first-run wizard

The wizard short-circuits when `config/settings.json → onboarding.stage
== "done"`. To rerun it:

```python
from src.onboarding import reset_onboarding
reset_onboarding()
```

Or open the Editor tab and delete the `onboarding` block from
`settings.json`.

## Generate a CHANGELOG release-notes blob

```
python -m src.changelog_utils 1.21.0   # specific version
python -m src.changelog_utils --latest # most recent
python -m src.changelog_utils --list   # every version
```

The release CI uses this to populate the GitHub Release body.

## Build a distributable bundle

```
./build_macos.sh        # → dist/tech_stock.dmg
./build_linux.sh        # → dist/tech_stock-x86_64.AppImage (or tarball)
build_windows.bat       # → dist/tech_stock_setup.exe (Windows only)
```

Or just push a `v*.*.*` tag and let CI do it — see
[RELEASE_PROCESS.md](RELEASE_PROCESS.md).
