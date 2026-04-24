# Temporary Upload Folder

Place your Wealthsimple CSV exports here before running the app.

## What to upload

### Holdings CSV (Required every time)
1. Log into [Wealthsimple](https://www.wealthsimple.com)
2. Go to **Account → Activity**
3. Click **Export Holdings Report (CSV)**
4. Drag the CSV file into this folder (or copy the file path when prompted)

**File name pattern:** `holdings-report-YYYY-MM-DD.csv`

### Activities CSV (Optional, only if older than 7 days)
1. Go to **Account → Activity**
2. Click **Export Activities (CSV)**
3. Select last **3 months**
4. Drag the CSV file into this folder

**File name pattern:** `activities-export-YYYY-MM-DD.csv`

## Notes

- The app will auto-detect the most recent CSV files in this folder
- This folder is **NOT** tracked by Git — your data stays private
- You can safely delete old CSV files after running the app
- The app only runs analysis on the holdings and activities you upload

---

**Next:** Run the app with `./run.sh` in the project root
