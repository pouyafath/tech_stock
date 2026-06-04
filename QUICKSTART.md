# tech_stock Quick Start

This guide gets a new user from installation to a first report in about five
minutes.

> For a no-key, no-cost preview, run `python src/main.py --demo` or choose
> **Try demo** in the launcher.

## 1. Install

### Packaged app

Download the latest release from:

<https://github.com/pouyafath/tech_stock/releases>

Choose the file for your platform:

- macOS: `tech_stock.dmg`
- Windows: `tech_stock_setup.exe`
- Linux: `tech_stock-x86_64.AppImage`

Open the app and choose **Desktop App**.

### Source installation

```bash
git clone https://github.com/pouyafath/tech_stock.git
cd tech_stock

python3 -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .\.venv\Scripts\Activate.ps1   # Windows PowerShell

python -m pip install -r requirements.txt
```

## 2. Add An Anthropic API Key

Create the user-friendly key file:

```bash
cp API_KEYS.template.txt API_KEYS.txt
```

Open `API_KEYS.txt` and set:

```text
ANTHROPIC_API_KEY=your-key-here
```

Anthropic is required for real recommendations. All other API keys in the
template are optional enrichment sources.

You can also add, update, remove, and test keys from the Desktop App's
**API Checks** tab.

## 3. Export Wealthsimple CSV Files

Export a fresh holdings report from Wealthsimple and save it to Downloads:

```text
holdings-report-YYYY-MM-DD.csv
```

The holdings report is required for a real portfolio run.

Optionally export the longest available activities history:

```text
activities-export-YYYY-MM-DD.csv
```

The activities file improves holding-day calculations and previous-session
execution checks.

These are different file formats. Select the holdings report in the Holdings
field and the activities export in the Activities field.

## 4. Launch

### macOS or Linux launcher

```bash
chmod +x run.sh run-ui.sh
./run.sh
```

### Any platform: direct commands

```bash
python src/desktop_app.py                    # embedded Desktop App
python src/main.py                           # interactive CLI
python -m streamlit run ui/streamlit_app.py # browser dashboard
python ui/textual_app.py                     # terminal dashboard
```

The launcher offers:

```text
[1] CLI
[2] Streamlit UI
[3] Textual TUI
[4] Desktop App
[5] Update
```

For normal daily use, start with the Desktop App. For scripting or scheduled
runs, use the CLI.

## 5. Run A Report

In the Desktop App:

1. Open **Run Report**.
2. Confirm the detected Holdings CSV path.
3. Confirm or skip the Activities CSV path.
4. Select morning or afternoon.
5. Select Sonnet or Opus.
6. Review the budget fields.
7. Click **Run Report**.

Or run directly:

```bash
python src/main.py morning \
  --holdings ~/Downloads/holdings-report-2026-06-04.csv \
  --activities ~/Downloads/activities-export-2026-06-04.csv
```

The app writes:

- A markdown report in `reports/`
- A recommendation CSV in `reports/`
- A structured JSON session log in `data/recommendations_log/`
- A cost record in `data/cost_log.jsonl`
- Pending actionable decisions in `data/decision_journal.json`

## 6. Review Before Trading

Start with these sections:

1. **Data Confidence**: quote freshness, source coverage, catalyst coverage,
   warning count, and overall readiness.
2. **Report Quality Warnings**: issues that require verification.
3. **Trader Action Plan**: prioritized actions and deterministic sizing.
4. **Risk Controls**: entry zones, stop loss, take profit, and invalidation.
5. **Catalyst and Sources**: why the move may be happening and where the
   supporting data came from.

Do not trade from a stale, blocked, or unverified signal.

## Useful First Commands

```bash
# Check configuration and release status
python src/main.py doctor --json

# Include the no-cost demo smoke test
python src/main.py doctor --json --force-refresh --demo-smoke

# Check for updates
python src/main.py check-update

# Launch demo mode
python src/main.py --demo
```

## Next Reading

- [Complete User Guide](docs/USER_GUIDE.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [How Analysis And Signals Work](ANALYSIS_AND_SIGNALS.md)
- [Operational Cookbook](docs/COOKBOOK.md)
