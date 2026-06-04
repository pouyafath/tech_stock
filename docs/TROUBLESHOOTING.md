# tech_stock Troubleshooting

Use this guide for common installation, input, API, report, update, and UI
problems.

Start with the preflight doctor:

```bash
python src/main.py doctor --json --force-refresh --demo-smoke
```

It checks the installed version, latest published release, update cache,
workspace, API key discovery, CSV freshness, monthly budget, release assets,
checksums, bundled demo data, and UI view models.

## The App Says The Holdings CSV Is Missing Required Columns

Example:

```text
Holdings CSV is missing required columns: [...]
Got columns: ['account_id', 'account_type', 'activity_type', ...]
```

The selected file is probably a Wealthsimple activities export, not a holdings
report.

Use:

- Holdings field: `holdings-report-YYYY-MM-DD.csv`
- Activities field: `activities-export-YYYY-MM-DD.csv`

The holdings report contains position-level fields such as `Market Price`,
`Market Value`, and `Book Value (Market)`. The activities export contains
transaction-level fields such as `activity_type`, `direction`,
`transaction_date`, and `unit_price`.

Recent versions of tech_stock detect swapped files and show a direct correction
message.

## The App Cannot Find My CSV Files

The app searches common workspace and Downloads locations, but filenames and
operating-system permissions can affect discovery.

1. Confirm that the holdings file is a CSV.
2. Prefer the Wealthsimple filename pattern
   `holdings-report-YYYY-MM-DD.csv`.
3. Prefer the activities filename pattern
   `activities-export-YYYY-MM-DD.csv`.
4. Use **Browse** in the UI or pass the full path on the CLI.
5. Confirm the detected path before running.

Example:

```bash
python src/main.py morning \
  --holdings "/full/path/to/holdings-report.csv" \
  --activities "/full/path/to/activities-export.csv"
```

## `ANTHROPIC_API_KEY` Is Missing

Create a key file:

```bash
cp API_KEYS.template.txt API_KEYS.txt
```

Then add:

```text
ANTHROPIC_API_KEY=your-key-here
```

You can also use `.env` or manage keys in the Desktop App's **API Checks** tab.

Run:

```bash
python src/main.py doctor --json
```

Check the `api_keys.search_paths` and `api_keys.checks` sections to see where the
app searched and which file supplied the key.

## Optional APIs Show Missing Or Failed

Only Anthropic is required for real Claude recommendations. Optional source
failures should degrade gracefully and appear as coverage warnings.

Use **API Checks** to:

- See whether a key is configured.
- Add, update, or remove a key.
- Run connectivity checks.
- See provider error details and latency.

Provider entitlements, quotas, field availability, and freshness vary by plan.
A configured key can still fail because of quota, plan restrictions, network
issues, or provider outages.

## A Quote Looks Wrong Or Stale

Do not trade from the report until the quote is verified.

Check:

- Quote source.
- Quote timestamp.
- Price basis: current, delayed, previous close, or fallback.
- Currency.
- Previous close.
- Holdings-vs-quote mismatch warning.
- Source degradation records.

Export a fresh holdings CSV and run again. Large movers should also have a
verified catalyst or manual-review flag.

## The Report Is Blocked Or Says Review First

This is expected when the app detects uncertainty.

Common causes:

- Stale or unstamped quote.
- Missing required catalyst for a large mover.
- Market-data error.
- Position cap violation.
- Quote mismatch.
- Missing risk controls.
- Manual-review flag.
- Optional source degradation.

Read **Data Confidence** and **Report Quality Warnings** before the action table.

## macOS Blocks The App

Current public macOS builds are ad-hoc signed and are not Apple-notarized.
macOS may show:

```text
"tech_stock" Not Opened
Apple could not verify "tech_stock" is free of malware.
```

To open the downloaded app:

1. Click **Done** on the warning.
2. Open **System Settings**.
3. Open **Privacy & Security**.
4. Scroll to **Security**.
5. Find the message that `tech_stock` was blocked.
6. Click **Open Anyway** and confirm.

This is usually required once per downloaded build. Avoiding the warning for all
users requires an Apple Developer ID signature, Apple notarization, and
stapling.

## The Desktop App Or Launcher Closes Unexpectedly

Run the same entrypoint from a terminal so errors remain visible:

```bash
python src/desktop_app.py
```

Also inspect:

- `logs/diagnostics.jsonl`
- `logs/update.log`
- Desktop App **Diagnostics**
- `python src/main.py doctor --json --demo-smoke`

If the issue is specific to report rendering, try Streamlit:

```bash
python -m streamlit run ui/streamlit_app.py
```

## Streamlit Starts But No Browser Opens

Streamlit normally prints a local URL such as:

```text
http://localhost:8501
```

Open that URL manually in a browser.

If port `8501` is busy:

```bash
python -m streamlit run ui/streamlit_app.py --server.port 8502
```

Then open `http://localhost:8502`.

## The Updater Shows An Older Version

The updater reads published GitHub Releases, not tags or draft releases.

Force a live check:

```bash
python src/main.py doctor --json --force-refresh
python src/main.py check-update
```

Inspect:

- `update.latest_version`
- `update.from_cache`
- `update.cache_age_seconds`
- `update.release_url`
- `update.asset_available`
- `update.checksum_available`

If GitHub only has a draft release, the app will continue to show the latest
published release.

## Update Download Or Checksum Verification Fails

Do not install an asset that fails checksum verification.

1. Run a force-refresh update check.
2. Confirm the release contains the platform asset.
3. Confirm the release contains `SHA256SUMS.txt`.
4. Check `logs/update.log`.
5. Download the release manually from GitHub if needed.

Release assets are available at:

<https://github.com/pouyafath/tech_stock/releases>

## A Source Checkout Will Not Update

Source checkouts use:

```bash
git pull --ff-only
```

This fails when local commits or branch history prevent a fast-forward.

Check:

```bash
git status
git branch --show-current
git fetch origin
```

Commit or preserve local work before changing branches. Do not delete
`API_KEYS.txt`, `.env`, reports, uploads, or other user data.

## Monthly Budget Blocks A Run

The app can block paid runs after the configured Anthropic monthly budget is
reached.

Check:

```bash
python src/main.py doctor --json
```

Review `budget` in the output and `monthly_budget_usd` in
`config/settings.json`.

To override one intentional run:

```bash
python src/main.py morning --force --holdings ~/Downloads/holdings-report.csv
```

## PowerShell Blocks Virtual-Environment Activation

Run:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\.venv\Scripts\Activate.ps1
```

Alternatively, call the virtual-environment Python directly:

```powershell
.\.venv\Scripts\python.exe src\main.py
```

## Linux AppImage Does Not Start

Make the file executable:

```bash
chmod +x tech_stock-x86_64.AppImage
./tech_stock-x86_64.AppImage
```

Some Linux distributions require FUSE compatibility packages. If the AppImage
still fails, run from source using the instructions in
[USER_GUIDE.md](USER_GUIDE.md).

## Tests Fail In A Development Checkout

Install development dependencies:

```bash
python -m pip install -r requirements-dev.txt
```

Run the same gates used by the project:

```bash
PYTHONPATH="$(pwd)" python -m pytest -q
ruff check src/ tests/ ui/ tools/
ruff format --check src/ tests/ ui/ tools/
```

## Getting More Diagnostic Detail

Useful files and commands:

```bash
python src/main.py doctor --json --force-refresh --demo-smoke
python src/main.py --version
python src/main.py check-update
```

Workspace logs:

```text
logs/diagnostics.jsonl
logs/update.log
data/cost_log.jsonl
```

When reporting a problem, remove private portfolio values and never include API
keys.
