"""
main.py
Entry point for the tech_stock portfolio advisor.

Usage (with CSV exports from Wealthsimple):
    python src/main.py morning  --holdings ~/Downloads/holdings-report-2026-04-23.csv
    python src/main.py morning  --holdings ~/Downloads/holdings-report-2026-04-23.csv \
                                --activities ~/Downloads/activities-export-2026-04-23.csv

Usage (with manual config/portfolio.json):
    python src/main.py morning
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is on path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.activity_loader import parse_activities_csv
from src.claude_analyst import call_claude
from src.fee_calculator import build_fee_snapshot
from src.market_data import get_market_data
from src.news_fetcher import get_news_for_tickers
from src.portfolio_loader import parse_holdings_csv
from src.report_generator import generate_markdown, save_report

CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
RECS_LOG_DIR = DATA_DIR / "recommendations_log"

# Skip these tickers from market data (CAD-only instruments yfinance handles poorly)
SKIP_MARKET_DATA = {"CASH"}


def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def get_all_tickers(portfolio: dict, watchlist: dict) -> list:
    """Combine portfolio tickers + watchlist tickers, deduplicated. Excludes CDRs and skip list."""
    tickers = set()
    for h in portfolio.get("holdings", []):
        ticker = h.get("ticker", "")
        # Skip CDRs (they're the same stock as US listing), pure-CAD ETFs, and skip list
        if h.get("is_cdr"):
            continue
        if ticker in SKIP_MARKET_DATA:
            continue
        if h.get("market_currency") == "CAD" and h.get("security_type") == "EXCHANGE_TRADED_FUND":
            # CAD ETFs like VGRO, CASH — skip market data fetch
            continue
        if ticker:
            tickers.add(ticker)

    for t in watchlist.get("all", []):
        if t not in SKIP_MARKET_DATA:
            tickers.add(t)

    return sorted(tickers)


def save_recommendation_log(data: dict, session_type: str):
    """Save Claude's raw JSON response to data/recommendations_log/."""
    RECS_LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    path = RECS_LOG_DIR / f"{timestamp}_{session_type}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path


def print_summary(recommendation: dict, session_type: str):
    """Print a compact summary to the terminal."""
    print("\n" + "=" * 65)
    print(f"  TECH STOCK ADVISOR — {session_type.upper()} SESSION")
    print("=" * 65)

    summary = recommendation.get("session_summary", "")
    if summary:
        print(f"\n{summary}\n")

    recs = recommendation.get("recommendations", [])
    if recs:
        print("RECOMMENDATIONS:")
        action_icons = {"BUY": "🟢", "ADD": "🟡", "HOLD": "⚪", "TRIM": "🟠", "SELL": "🔴"}
        for r in recs:
            icon = action_icons.get(r.get("action", "HOLD"), "⚪")
            ticker = r.get("ticker", "")
            action = r.get("action", "HOLD")
            conviction = r.get("conviction", 0)
            net = r.get("net_expected_pct", 0)
            horizon = r.get("time_horizon", "")
            print(f"  {icon} {ticker:8s} {action:4s}  conviction={conviction}/10  "
                  f"net_expected={net:+.2f}%  [{horizon}]")
            print(f"     → {r.get('thesis', '')[:80]}")

    flags = recommendation.get("watchlist_flags", [])
    if flags:
        print("\nWATCHLIST FLAGS:")
        for f in flags:
            print(f"  ⚑ {f.get('ticker', '')}: {f.get('why_noteworthy', '')[:80]}")

    warnings = recommendation.get("warnings", [])
    if warnings:
        print("\n⚠️  WARNINGS:")
        for w in warnings:
            print(f"  ! {w}")

    print("=" * 65 + "\n")


def run(session_type: str, holdings_csv: Path = None, activities_csv: Path = None):
    print(f"\n[tech_stock] Starting {session_type} session — {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # --- Load portfolio ---
    if holdings_csv:
        print(f"[tech_stock] Loading holdings from CSV: {holdings_csv.name}")
        portfolio = parse_holdings_csv(holdings_csv)
        print(f"[tech_stock] Found {len(portfolio['holdings'])} positions | {portfolio.get('exported_at', '')}")
    else:
        print("[tech_stock] Using config/portfolio.json (no --holdings CSV provided)")
        portfolio = load_json(CONFIG_DIR / "portfolio.json")

    # --- Load recent activities ---
    recent_activities = None
    if activities_csv:
        print(f"[tech_stock] Loading activities from CSV: {activities_csv.name} (last 90 days)")
        recent_activities = parse_activities_csv(activities_csv, days=90)
        print(f"[tech_stock] Found {len(recent_activities)} recent trades")

    # --- Load watchlist and settings ---
    watchlist = load_json(CONFIG_DIR / "watchlist.json")
    settings = load_json(CONFIG_DIR / "settings.json")

    # --- Build ticker list ---
    tickers = get_all_tickers(portfolio, watchlist)
    print(f"[tech_stock] Tracking {len(tickers)} tickers: {', '.join(tickers)}")

    # --- Fetch market data ---
    print("[tech_stock] Fetching market data...")
    market_data = get_market_data(tickers)

    # --- Fetch news ---
    print("[tech_stock] Fetching news...")
    news_by_ticker = get_news_for_tickers(tickers)

    # --- Build fee snapshot ---
    print("[tech_stock] Calculating fees...")
    fee_snapshot = build_fee_snapshot(tickers)

    # --- Call Claude ---
    print("[tech_stock] Calling Claude for recommendations...")
    try:
        recommendation = call_claude(
            session_type=session_type,
            portfolio=portfolio,
            market_data=market_data,
            news_by_ticker=news_by_ticker,
            fee_snapshot=fee_snapshot,
            recent_activities=recent_activities,
        )
    except ValueError as e:
        print(f"[ERROR] Claude response parsing failed: {e}")
        sys.exit(1)

    # --- Save logs and report ---
    log_path = save_recommendation_log(recommendation, session_type)
    print(f"[tech_stock] JSON log saved → {log_path.relative_to(ROOT)}")

    md_content = generate_markdown(session_type, recommendation, market_data)
    report_path = save_report(md_content, session_type, REPORTS_DIR)
    print(f"[tech_stock] Report saved     → {report_path.relative_to(ROOT)}")

    print_summary(recommendation, session_type)
    print(f"[tech_stock] Done. Open {report_path.relative_to(ROOT)} for the full report.\n")


def main():
    parser = argparse.ArgumentParser(
        description="Tech Stock Portfolio Advisor — powered by Claude",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # With live CSV exports from Wealthsimple (recommended):
  python src/main.py morning --holdings ~/Downloads/holdings-report-2026-04-23.csv
  python src/main.py morning --holdings ~/Downloads/holdings-report.csv --activities ~/Downloads/activities-export.csv

  # With manual portfolio.json (fallback):
  python src/main.py afternoon
        """,
    )
    parser.add_argument("session", choices=["morning", "afternoon"], help="Session type")
    parser.add_argument(
        "--holdings", "-p",
        type=Path,
        metavar="CSV",
        help="Path to Wealthsimple Holdings CSV export (recommended, export fresh each run)",
    )
    parser.add_argument(
        "--activities", "-a",
        type=Path,
        metavar="CSV",
        help="Path to Wealthsimple Activities CSV export (optional, last 3 months recommended)",
    )

    args = parser.parse_args()

    # Validate paths
    if args.holdings and not args.holdings.exists():
        print(f"[ERROR] Holdings CSV not found: {args.holdings}")
        sys.exit(1)
    if args.activities and not args.activities.exists():
        print(f"[ERROR] Activities CSV not found: {args.activities}")
        sys.exit(1)

    run(args.session, holdings_csv=args.holdings, activities_csv=args.activities)


if __name__ == "__main__":
    main()
