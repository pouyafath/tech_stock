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
import os
import subprocess
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

CONFIG_DIR  = ROOT / "config"
DATA_DIR    = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
RECS_LOG_DIR = DATA_DIR / "recommendations_log"
DOWNLOADS_DIR = Path.home() / "Downloads"

SKIP_MARKET_DATA = {"CASH"}

# Pairs where one is a share class / near-duplicate of the other.
# When both appear, keep only the first in each pair for market data.
DEDUP_PAIRS = [("GOOGL", "GOOG"), ("BRK.A", "BRK.B")]

MODELS = {
    "1": ("claude-sonnet-4-6", "Sonnet 4.6", "~$0.09/run — fast, recommended"),
    "2": ("claude-opus-4-7",   "Opus 4.7",   "~$0.45/run — deeper analysis, slower"),
}

# ── ANSI colour codes (no extra dependencies) ─────────────────────────────────
class C:
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    ORANGE = "\033[38;5;208m"
    CYAN   = "\033[96m"
    GREY   = "\033[90m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    RESET  = "\033[0m"

ACTION_STYLE = {
    "BUY":  (f"{C.GREEN}🟢 BUY {C.RESET}",  C.GREEN),
    "ADD":  (f"{C.YELLOW}🟡 ADD {C.RESET}", C.YELLOW),
    "HOLD": (f"{C.GREY}⚪ HOLD{C.RESET}",   C.GREY),
    "TRIM": (f"{C.ORANGE}🟠 TRIM{C.RESET}", C.ORANGE),
    "SELL": (f"{C.RED}🔴 SELL{C.RESET}",    C.RED),
}


def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def find_latest_csv(pattern: str) -> Path | None:
    candidates = sorted(DOWNLOADS_DIR.glob(pattern), reverse=True)
    return candidates[0] if candidates else None


def validate_environment():
    """Fail fast if the API key is missing — before wasting 60s on market data."""
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(f"\n{C.RED}[ERROR]{C.RESET} ANTHROPIC_API_KEY is not set.")
        print("  1. Copy the template:  cp .env.example .env")
        print("  2. Open .env and paste your API key from https://console.anthropic.com/")
        print("  3. Or export it:       export ANTHROPIC_API_KEY=sk-ant-api03-...")
        sys.exit(1)


def interactive_setup() -> dict:
    """Walk the user through setup questions. Returns config dict."""
    print(f"\n{C.BOLD}{'=' * 65}{C.RESET}")
    print(f"{C.BOLD}  TECH STOCK ADVISOR{C.RESET}")
    print(f"{C.BOLD}{'=' * 65}{C.RESET}")

    hour = datetime.now().hour
    default_session = "morning" if hour < 13 else "afternoon"
    print(f"\n  {C.DIM}Current time: {datetime.now().strftime('%H:%M')} — defaulting to {default_session.upper()} session{C.RESET}")
    session_input = input(f"  Session type (morning/afternoon) [Enter = {default_session}]: ").strip().lower()
    session_type = session_input if session_input in ("morning", "afternoon") else default_session

    print()

    while True:
        raw = input(f"1. How much {C.BOLD}USD{C.RESET} would you like to invest today? $").strip()
        if not raw:
            budget_usd = 0.0; break
        try:
            budget_usd = float(raw); break
        except ValueError:
            print("   ↳ Please enter a number (e.g. 500 or 0).")

    while True:
        raw = input(f"2. How much {C.BOLD}CAD{C.RESET} would you like to invest today? $").strip()
        if not raw:
            budget_cad = 0.0; break
        try:
            budget_cad = float(raw); break
        except ValueError:
            print("   ↳ Please enter a number (e.g. 1000 or 0).")

    holdings_auto = find_latest_csv("holdings-report-*.csv")
    holdings_hint = str(holdings_auto) if holdings_auto else f"{DOWNLOADS_DIR}/holdings-report-YYYY-MM-DD.csv"
    print(f"\n3. Holdings CSV detected:\n   {C.CYAN}{holdings_hint}{C.RESET}")
    answer = input("   Is this correct? (Y/N): ").strip().upper()

    if answer == "Y" and holdings_auto:
        holdings_path = holdings_auto
    else:
        raw = input("   Enter the full path to your Holdings CSV: ").strip()
        holdings_path = Path(raw) if raw else None

    if not holdings_path or not holdings_path.exists():
        print(f"   ↳ {C.YELLOW}WARNING:{C.RESET} Holdings CSV not found. Will fall back to config/portfolio.json")
        holdings_path = None

    activities_auto = find_latest_csv("activities-export-*.csv")
    activities_hint = str(activities_auto) if activities_auto else f"{DOWNLOADS_DIR}/activities-export-YYYY-MM-DD.csv"
    print(f"\n4. Activities CSV detected:\n   {C.CYAN}{activities_hint}{C.RESET}")
    answer = input("   Is this correct? (Y/N, or Enter to skip): ").strip().upper()

    if answer == "Y" and activities_auto:
        activities_path = activities_auto
    elif answer == "N":
        raw = input("   Enter the full path to your Activities CSV (or Enter to skip): ").strip()
        activities_path = Path(raw) if raw else None
    else:
        activities_path = None

    if activities_path and not activities_path.exists():
        print(f"   ↳ {C.YELLOW}WARNING:{C.RESET} Activities CSV not found — skipping trade history.")
        activities_path = None

    print(f"\n5. Which model would you like to use?")
    for key, (_, name, desc) in MODELS.items():
        print(f"   [{key}] {C.BOLD}{name}{C.RESET} — {desc}")
    model_input = input("   Choose (1/2) [Enter = 1]: ").strip()
    model_id, model_name, _ = MODELS.get(model_input, MODELS["1"])

    print()
    return {
        "session_type":    session_type,
        "budget_usd":      budget_usd,
        "budget_cad":      budget_cad,
        "holdings_path":   holdings_path,
        "activities_path": activities_path,
        "model_id":        model_id,
        "model_name":      model_name,
    }


def get_all_tickers(portfolio: dict, watchlist: dict) -> list:
    """Combine portfolio + watchlist tickers, deduplicated. Excludes CDRs, CAD ETFs, CASH."""
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

    # Remove near-duplicate share classes (e.g. keep GOOGL, drop GOOG)
    for keep, drop in DEDUP_PAIRS:
        if keep in tickers and drop in tickers:
            tickers.discard(drop)

    return sorted(tickers)


def save_recommendation_log(data: dict, session_type: str) -> Path:
    RECS_LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    path = RECS_LOG_DIR / f"{timestamp}_{session_type}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path


def save_recommendations_csv(recommendation: dict, session_type: str, csv_dir: Path) -> Path:
    """Save recommendations as a clean CSV table."""
    import csv
    csv_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    csv_path = csv_dir / f"{timestamp}_{session_type}_recommendations.csv"

    recs = recommendation.get("recommendations", [])
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["Ticker", "Action", "Conviction", "Net Expected %", "Time Horizon", "Thesis"],
            extrasaction="ignore",
        )
        writer.writeheader()
        for r in recs:
            writer.writerow({
                "Ticker":          r.get("ticker", ""),
                "Action":          r.get("action", "HOLD"),
                "Conviction":      r.get("conviction", 0),
                "Net Expected %":  f"{r.get('net_expected_pct', 0):+.2f}%",
                "Time Horizon":    r.get("time_horizon", ""),
                "Thesis":          r.get("thesis", ""),
            })
    return csv_path


def print_summary(recommendation: dict, session_type: str):
    print(f"\n{C.BOLD}{'=' * 65}{C.RESET}")
    print(f"{C.BOLD}  TECH STOCK ADVISOR — {session_type.upper()} SESSION{C.RESET}")
    print(f"{C.BOLD}{'=' * 65}{C.RESET}")

    summary = recommendation.get("session_summary", "")
    if summary:
        print(f"\n{summary}\n")

    recs = recommendation.get("recommendations", [])
    if recs:
        print(f"{C.BOLD}RECOMMENDATIONS:{C.RESET}")
        for r in recs:
            action = r.get("action", "HOLD")
            label, color = ACTION_STYLE.get(action, (f"⚪ {action}", C.GREY))
            ticker = r.get("ticker", "")
            conviction = r.get("conviction", 0)
            net = r.get("net_expected_pct", 0)
            horizon = r.get("time_horizon", "")
            net_color = C.GREEN if net > 0 else C.RED
            print(
                f"  {label}  {C.BOLD}{ticker:8s}{C.RESET}"
                f"  conviction={C.BOLD}{conviction}{C.RESET}/10"
                f"  net={net_color}{net:+.2f}%{C.RESET}"
                f"  {C.DIM}[{horizon}]{C.RESET}"
            )
            print(f"     {C.DIM}→ {r.get('thesis', '')[:80]}{C.RESET}")

    flags = recommendation.get("watchlist_flags", [])
    if flags:
        print(f"\n{C.BOLD}WATCHLIST FLAGS:{C.RESET}")
        for f in flags:
            print(f"  {C.CYAN}⚑{C.RESET} {C.BOLD}{f.get('ticker', '')}{C.RESET}: {f.get('why_noteworthy', '')[:80]}")

    warnings = recommendation.get("warnings", [])
    if warnings:
        print(f"\n{C.YELLOW}⚠️  WARNINGS:{C.RESET}")
        for w in warnings:
            print(f"  {C.YELLOW}!{C.RESET} {w}")

    print(f"{C.BOLD}{'=' * 65}{C.RESET}\n")


def print_usage(usage: dict, model_name: str):
    """Print a compact cost summary after Claude returns."""
    hit = f"{C.GREEN}cache HIT ✓{C.RESET}" if usage.get("cache_hit") else f"{C.DIM}cache miss{C.RESET}"
    cost = usage.get("cost_usd", 0)
    cost_color = C.GREEN if cost < 0.10 else C.YELLOW
    total_tok = usage.get("total_tokens", 0)
    print(
        f"  {C.DIM}[{model_name}]{C.RESET}  "
        f"tokens: {total_tok:,}  "
        f"cost: {cost_color}${cost:.4f}{C.RESET}  "
        f"{hit}"
    )


def open_file(path: Path):
    """Open the file in the default app (macOS / Linux / Windows)."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        elif sys.platform.startswith("linux"):
            subprocess.run(["xdg-open", str(path)], check=False)
        elif sys.platform == "win32":
            os.startfile(str(path))
    except Exception:
        pass  # non-fatal — file path is always printed


def run(
    session_type: str,
    holdings_csv: Path = None,
    activities_csv: Path = None,
    budget_usd: float = None,
    budget_cad: float = None,
    model_id: str = None,
    model_name: str = None,
):
    validate_environment()

    print(f"\n{C.DIM}[tech_stock] Starting {session_type} session — {datetime.now().strftime('%Y-%m-%d %H:%M')}{C.RESET}")

    # Load portfolio
    if holdings_csv:
        print(f"{C.DIM}[tech_stock] Loading holdings from CSV: {holdings_csv.name}{C.RESET}")
        portfolio = parse_holdings_csv(holdings_csv)
        print(f"{C.DIM}[tech_stock] Found {len(portfolio['holdings'])} positions | {portfolio.get('exported_at', '')}{C.RESET}")
    else:
        print(f"{C.DIM}[tech_stock] Using config/portfolio.json (no Holdings CSV provided){C.RESET}")
        portfolio = load_json(CONFIG_DIR / "portfolio.json")

    recent_activities = None
    if activities_csv:
        print(f"{C.DIM}[tech_stock] Loading activities from CSV: {activities_csv.name} (last 90 days){C.RESET}")
        recent_activities = parse_activities_csv(activities_csv, days=90)
        print(f"{C.DIM}[tech_stock] Found {len(recent_activities)} recent trades{C.RESET}")

    watchlist = load_json(CONFIG_DIR / "watchlist.json")
    settings  = load_json(CONFIG_DIR / "settings.json")

    if budget_cad is not None:
        settings["budget_cad"] = budget_cad
    if budget_usd is not None:
        settings["budget_usd"] = budget_usd
    if model_id:
        settings["claude_model"] = model_id

    tickers = get_all_tickers(portfolio, watchlist)
    print(f"{C.DIM}[tech_stock] Tracking {len(tickers)} tickers: {', '.join(tickers)}{C.RESET}")

    print(f"{C.DIM}[tech_stock] Fetching market data...{C.RESET}")
    market_data = get_market_data(tickers)

    print(f"{C.DIM}[tech_stock] Fetching news...{C.RESET}")
    news_by_ticker = get_news_for_tickers(tickers)

    print(f"{C.DIM}[tech_stock] Calculating fees...{C.RESET}")
    fee_snapshot = build_fee_snapshot(tickers)

    display_model = model_name or settings.get("claude_model", "claude-sonnet-4-6")
    print(f"{C.DIM}[tech_stock] Calling Claude ({display_model}) for recommendations...{C.RESET}")

    try:
        recommendation, usage = call_claude(
            session_type=session_type,
            portfolio=portfolio,
            market_data=market_data,
            news_by_ticker=news_by_ticker,
            fee_snapshot=fee_snapshot,
            recent_activities=recent_activities,
            settings_override=settings,
        )
    except ValueError as e:
        print(f"{C.RED}[ERROR]{C.RESET} Claude response parsing failed: {e}")
        sys.exit(1)

    log_path = save_recommendation_log(recommendation, session_type)
    md_content = generate_markdown(session_type, recommendation, market_data)
    report_path = save_report(md_content, session_type, REPORTS_DIR)
    csv_path = save_recommendations_csv(recommendation, session_type, REPORTS_DIR)

    print_summary(recommendation, session_type)
    print_usage(usage, display_model)

    print(f"\n{C.BOLD}{'=' * 65}{C.RESET}")
    print(f"  {C.BOLD}📊 Markdown report:{C.RESET}")
    print(f"  {C.CYAN}{report_path.resolve()}{C.RESET}\n")
    print(f"  {C.BOLD}📋 CSV table:{C.RESET}")
    print(f"  {C.CYAN}{csv_path.resolve()}{C.RESET}")
    print(f"{C.BOLD}{'=' * 65}{C.RESET}\n")

    open_file(report_path)


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
    parser.add_argument("--holdings",  "-p", type=Path, metavar="CSV",
                        help="Path to Wealthsimple Holdings CSV export")
    parser.add_argument("--activities", "-a", type=Path, metavar="CSV",
                        help="Path to Wealthsimple Activities CSV export (optional)")
    parser.add_argument("--model", "-m", choices=["sonnet", "opus"],
                        help="Model: sonnet = claude-sonnet-4-6, opus = claude-opus-4-7")

    args = parser.parse_args()

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

    if args.holdings and not args.holdings.exists():
        print(f"{C.RED}[ERROR]{C.RESET} Holdings CSV not found: {args.holdings}")
        sys.exit(1)
    if args.activities and not args.activities.exists():
        print(f"{C.RED}[ERROR]{C.RESET} Activities CSV not found: {args.activities}")
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
