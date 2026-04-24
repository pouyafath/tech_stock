"""
main.py
Entry point for the tech_stock portfolio advisor.

Interactive mode (recommended):
    python src/main.py

CLI mode (for scripting):
    python src/main.py morning  --holdings ~/Downloads/holdings-report-2026-04-23.csv
    python src/main.py morning  --holdings ~/Downloads/holdings-report-2026-04-23.csv \
                                --activities ~/Downloads/activities-export-2026-04-23.csv
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

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
DOWNLOADS_DIR = Path.home() / "Downloads"

SKIP_MARKET_DATA = {"CASH"}

MODELS = {
    "1": ("claude-sonnet-4-6", "Sonnet 4.6", "~$0.09/run — fast, recommended"),
    "2": ("claude-opus-4-7",   "Opus 4.7",   "~$0.45/run — deeper analysis, slower"),
}


def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def find_latest_csv(pattern: str) -> Path | None:
    candidates = sorted(DOWNLOADS_DIR.glob(pattern), reverse=True)
    return candidates[0] if candidates else None


def interactive_setup() -> dict:
    """Walk the user through setup questions. Returns config dict."""
    print("\n" + "=" * 65)
    print("  TECH STOCK ADVISOR")
    print("=" * 65)

    # Auto-detect session type from current time (ET ~ system time -4h or -5h)
    hour = datetime.now().hour
    default_session = "morning" if hour < 13 else "afternoon"
    print(f"\n  Current time: {datetime.now().strftime('%H:%M')} — defaulting to {default_session.upper()} session")
    session_input = input(f"  Session type (morning/afternoon) [Enter = {default_session}]: ").strip().lower()
    session_type = session_input if session_input in ("morning", "afternoon") else default_session

    print()

    # Q1: USD budget
    while True:
        raw = input("1. How much USD would you like to invest today? $").strip()
        if not raw:
            budget_usd = 0.0
            break
        try:
            budget_usd = float(raw)
            break
        except ValueError:
            print("   ↳ Please enter a number (e.g. 500 or 0).")

    # Q2: CAD budget
    while True:
        raw = input("2. How much CAD would you like to invest today? $").strip()
        if not raw:
            budget_cad = 0.0
            break
        try:
            budget_cad = float(raw)
            break
        except ValueError:
            print("   ↳ Please enter a number (e.g. 1000 or 0).")

    # Q3: Holdings CSV
    holdings_auto = find_latest_csv("holdings-report-*.csv")
    holdings_hint = str(holdings_auto) if holdings_auto else f"{DOWNLOADS_DIR}/holdings-report-YYYY-MM-DD.csv"
    print(f"\n3. Holdings CSV detected:\n   {holdings_hint}")
    answer = input("   Is this correct? (Y/N): ").strip().upper()

    if answer == "Y" and holdings_auto:
        holdings_path = holdings_auto
    else:
        raw = input("   Enter the full path to your Holdings CSV: ").strip()
        holdings_path = Path(raw) if raw else None

    if not holdings_path or not holdings_path.exists():
        print(f"   ↳ WARNING: Holdings CSV not found. Will fall back to config/portfolio.json")
        holdings_path = None

    # Q4: Activities CSV
    activities_auto = find_latest_csv("activities-export-*.csv")
    activities_hint = str(activities_auto) if activities_auto else f"{DOWNLOADS_DIR}/activities-export-YYYY-MM-DD.csv"
    print(f"\n4. Activities CSV detected:\n   {activities_hint}")
    answer = input("   Is this correct? (Y/N, or Enter to skip): ").strip().upper()

    if answer == "Y" and activities_auto:
        activities_path = activities_auto
    elif answer == "N":
        raw = input("   Enter the full path to your Activities CSV (or Enter to skip): ").strip()
        activities_path = Path(raw) if raw else None
    else:
        activities_path = None  # skipped

    if activities_path and not activities_path.exists():
        print("   ↳ WARNING: Activities CSV not found — skipping trade history.")
        activities_path = None

    # Q5: Model
    print("\n5. Which model would you like to use?")
    for key, (_, name, desc) in MODELS.items():
        print(f"   [{key}] {name} — {desc}")
    model_input = input("   Choose (1/2) [Enter = 1]: ").strip()
    model_id, model_name, _ = MODELS.get(model_input, MODELS["1"])

    print()
    return {
        "session_type": session_type,
        "budget_usd": budget_usd,
        "budget_cad": budget_cad,
        "holdings_path": holdings_path,
        "activities_path": activities_path,
        "model_id": model_id,
        "model_name": model_name,
    }


def get_all_tickers(portfolio: dict, watchlist: dict) -> list:
    tickers = set()
    for h in portfolio.get("holdings", []):
        ticker = h.get("ticker", "")
        if h.get("is_cdr"):
            continue
        if ticker in SKIP_MARKET_DATA:
            continue
        if h.get("market_currency") == "CAD" and h.get("security_type") == "EXCHANGE_TRADED_FUND":
            continue
        if ticker:
            tickers.add(ticker)
    for t in watchlist.get("all", []):
        if t not in SKIP_MARKET_DATA:
            tickers.add(t)
    return sorted(tickers)


def save_recommendation_log(data: dict, session_type: str) -> Path:
    RECS_LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    path = RECS_LOG_DIR / f"{timestamp}_{session_type}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path


def print_summary(recommendation: dict, session_type: str):
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


def run(
    session_type: str,
    holdings_csv: Path = None,
    activities_csv: Path = None,
    budget_usd: float = None,
    budget_cad: float = None,
    model_id: str = None,
    model_name: str = None,
):
    print(f"\n[tech_stock] Starting {session_type} session — {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Load portfolio
    if holdings_csv:
        print(f"[tech_stock] Loading holdings from CSV: {holdings_csv.name}")
        portfolio = parse_holdings_csv(holdings_csv)
        print(f"[tech_stock] Found {len(portfolio['holdings'])} positions | {portfolio.get('exported_at', '')}")
    else:
        print("[tech_stock] Using config/portfolio.json (no Holdings CSV provided)")
        portfolio = load_json(CONFIG_DIR / "portfolio.json")

    # Load recent activities
    recent_activities = None
    if activities_csv:
        print(f"[tech_stock] Loading activities from CSV: {activities_csv.name} (last 90 days)")
        recent_activities = parse_activities_csv(activities_csv, days=90)
        print(f"[tech_stock] Found {len(recent_activities)} recent trades")

    # Load config
    watchlist = load_json(CONFIG_DIR / "watchlist.json")
    settings = load_json(CONFIG_DIR / "settings.json")

    # Apply per-run overrides from interactive setup
    if budget_cad is not None:
        settings["budget_cad"] = budget_cad
    if budget_usd is not None:
        settings["budget_usd"] = budget_usd
    if model_id:
        settings["claude_model"] = model_id

    # Build ticker list
    tickers = get_all_tickers(portfolio, watchlist)
    print(f"[tech_stock] Tracking {len(tickers)} tickers: {', '.join(tickers)}")

    print("[tech_stock] Fetching market data...")
    market_data = get_market_data(tickers)

    print("[tech_stock] Fetching news...")
    news_by_ticker = get_news_for_tickers(tickers)

    print("[tech_stock] Calculating fees...")
    fee_snapshot = build_fee_snapshot(tickers)

    model_label = model_name or settings.get("claude_model", "claude-sonnet-4-6")
    print(f"[tech_stock] Calling Claude ({model_label}) for recommendations...")
    try:
        recommendation = call_claude(
            session_type=session_type,
            portfolio=portfolio,
            market_data=market_data,
            news_by_ticker=news_by_ticker,
            fee_snapshot=fee_snapshot,
            recent_activities=recent_activities,
            settings_override=settings,
        )
    except ValueError as e:
        print(f"[ERROR] Claude response parsing failed: {e}")
        sys.exit(1)

    log_path = save_recommendation_log(recommendation, session_type)
    print(f"[tech_stock] JSON log saved → {log_path.relative_to(ROOT)}")

    md_content = generate_markdown(session_type, recommendation, market_data)
    report_path = save_report(md_content, session_type, REPORTS_DIR)

    print_summary(recommendation, session_type)

    print("=" * 65)
    print(f"  Report saved to:\n  {report_path.resolve()}")
    print("=" * 65 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Tech Stock Portfolio Advisor — powered by Claude",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Run without arguments for interactive mode (recommended).

CLI examples:
  python src/main.py morning --holdings ~/Downloads/holdings-report-2026-04-23.csv
  python src/main.py morning --holdings ~/Downloads/holdings-report.csv --activities ~/Downloads/activities-export.csv
        """,
    )
    parser.add_argument("session", nargs="?", choices=["morning", "afternoon"],
                        help="Session type (omit for interactive mode)")
    parser.add_argument("--holdings", "-p", type=Path, metavar="CSV",
                        help="Path to Wealthsimple Holdings CSV export")
    parser.add_argument("--activities", "-a", type=Path, metavar="CSV",
                        help="Path to Wealthsimple Activities CSV export (optional)")
    parser.add_argument("--model", "-m", choices=["sonnet", "opus"],
                        help="Model: sonnet = claude-sonnet-4-6, opus = claude-opus-4-7")

    args = parser.parse_args()

    # Interactive mode if no session provided
    if args.session is None:
        cfg = interactive_setup()
        run(
            session_type=cfg["session_type"],
            holdings_csv=cfg["holdings_path"],
            activities_csv=cfg["activities_path"],
            budget_usd=cfg["budget_usd"],
            budget_cad=cfg["budget_cad"],
            model_id=cfg["model_id"],
            model_name=cfg["model_name"],
        )
        return

    # CLI mode
    if args.holdings and not args.holdings.exists():
        print(f"[ERROR] Holdings CSV not found: {args.holdings}")
        sys.exit(1)
    if args.activities and not args.activities.exists():
        print(f"[ERROR] Activities CSV not found: {args.activities}")
        sys.exit(1)

    model_map = {"sonnet": ("claude-sonnet-4-6", "Sonnet 4.6"), "opus": ("claude-opus-4-7", "Opus 4.7")}
    model_id, model_name = model_map.get(args.model, (None, None))

    run(
        session_type=args.session,
        holdings_csv=args.holdings,
        activities_csv=args.activities,
        model_id=model_id,
        model_name=model_name,
    )


if __name__ == "__main__":
    main()
