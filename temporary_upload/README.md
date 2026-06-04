# Temporary Upload Folder

Place your Wealthsimple CSV exports here before running the app.

## What to upload

### Holdings CSV (required for a real portfolio run)
1. Log into [Wealthsimple](https://www.wealthsimple.com)
2. Go to **Account → Activity**
3. Click **Export Holdings Report (CSV)**
4. Drag the CSV file into this folder (or copy the file path when prompted)

**File name pattern:** `holdings-report-YYYY-MM-DD.csv`

### Activities CSV (optional, longest available history recommended)
1. Go to **Account → Activity**
2. Click **Export Activities (CSV)**
3. Export the **full available history** if possible; otherwise choose the longest range available
4. Drag the CSV file into this folder

**File name pattern:** `activities-export-YYYY-MM-DD.csv`

## Notes

- The app checks this folder, your Downloads folder, and the active workspace for recent CSV files. Interactive flows ask you to confirm the detected path before using it.
- Holdings and activities exports are different schemas. Put `holdings-report-*.csv` in the Holdings field and `activities-export-*.csv` in the Activities field.
- Export a fresh Holdings CSV before any paid run; stale holdings snapshots create visible quote-mismatch warnings and can distort position sizing.
- A full Activities export lets the app compute exact FIFO holding days. Short exports still work, but older holdings will show lower-bound durations.
- This folder is **NOT** tracked by Git — your data stays private
- You can safely delete old CSV files after running the app
- The app only runs analysis on the holdings and activities you upload

---

**Next:** Run the app with `./run.sh` in the project root or read the
[User Guide](../docs/USER_GUIDE.md).
