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
from src.backtester import run_backtest
from src.claude_analyst import call_claude
from src.constants import DEDUP_PAIRS, SKIP_MARKET_DATA
from src.drift_tracker import compute_drift, get_previous_session
from src.enriched_data import enrich
from src.fee_calculator import build_fee_snapshot
from src.market_data import add_options_implied_moves, get_context_moves, get_market_data
from src.news_fetcher import get_news_for_tickers
from src.portfolio_analytics import aggregate_company_exposure, build_hedge_suggestions, compute_risk_dashboard
from src.portfolio_loader import compute_sector_exposure, parse_holdings_csv
from src.report_generator import generate_markdown, save_report, watchlist_price_alerts

CONFIG_DIR  = ROOT / "config"
DATA_DIR    = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
RECS_LOG_DIR = DATA_DIR / "recommendations_log"
UPLOAD_DIR  = ROOT / "temporary_upload"

MODELS = {
    "1": ("claude-sonnet-4-6", "Sonnet 4.6", "~$0.22/run — two-pass, recommended"),
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


def _get_downloads_dir() -> Path:
    """Get the Downloads folder path (cross-platform: macOS, Windows, Linux)."""
    home = Path.home()
    if sys.platform == "win32":
        # Windows: typically C:\Users\YourName\Downloads
        downloads = home / "Downloads"
    else:
        # macOS and Linux: ~/Downloads
        downloads = home / "Downloads"
    return downloads if downloads.exists() else home


def find_csv_by_date(pattern_prefix: str, max_results: int = 1) -> Path | None:
    r"""
    Search for a CSV file by today's date.

    Pattern: pattern_prefix-YYYY-MM-DD.csv (e.g., "holdings-report-2026-04-29.csv")

    Search order:
    1. Check temp UPLOAD_DIR first (highest priority)
    2. Check Downloads folder (macOS ~/Downloads, Windows C:\Users\...\Downloads)
    3. Search entire home directory

    Returns the first match or None.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    target_pattern = f"{pattern_prefix}-{today}.csv"

    # 1. Check UPLOAD_DIR first (highest priority)
    candidate = UPLOAD_DIR / target_pattern
    if candidate.exists():
        return candidate

    # 2. Check Downloads folder
    downloads = _get_downloads_dir()
    candidate = downloads / target_pattern
    if candidate.exists():
        return candidate

    # 3. Search home directory recursively (slower, last resort)
    home = Path.home()
    try:
        matches = list(home.glob(f"**/{target_pattern}"))
        if matches:
            return matches[0]
    except (PermissionError, OSError):
        pass

    return None


def find_latest_csv(pattern: str) -> Path | None:
    """Find the most recently modified CSV file matching pattern in UPLOAD_DIR."""
    candidates = sorted(UPLOAD_DIR.glob(pattern), reverse=True)
    return candidates[0] if candidates else None


def is_file_older_than_days(path: Path, days: int) -> bool:
    """Check if a file is older than N days. Returns True if old, False if recent."""
    if not path.exists():
        return True
    age_seconds = datetime.now().timestamp() - path.stat().st_mtime
    return age_seconds > (days * 86400)


def _prompt_positive_float(label: str, example: int) -> float:
    """Prompt for a non-negative number; blank → 0.0; loop until valid."""
    while True:
        raw = input(f"   How much {C.BOLD}{label}{C.RESET} would you like to invest today? $").strip()
        if not raw:
            return 0.0
        try:
            val = float(raw)
            if val < 0:
                print(f"   {C.YELLOW}↳ Please enter a positive number (e.g. {example} or 0){C.RESET}")
                continue
            return val
        except ValueError:
            print(f"   {C.YELLOW}↳ Invalid input. Please enter a number (e.g. {example} or 0){C.RESET}")


def _prompt_for_existing_path(prompt_label: str = "Enter the full path to your Holdings CSV: ") -> Path:
    """Prompt for a path that must exist on disk; loop until valid."""
    while True:
        raw = input(f"   {prompt_label}").strip()
        if not raw:
            print(f"   {C.YELLOW}↳ Path cannot be empty. Please provide a valid path.{C.RESET}")
            continue
        test_path = Path(raw)
        if test_path.exists():
            return test_path
        print(f"   {C.RED}✗ File not found: {raw}{C.RESET}")
        print(f"   {C.YELLOW}↳ Please enter a valid file path{C.RESET}")


def _prompt_yes_no(prompt: str) -> str:
    """Prompt for Y/N answer; loop until valid; returns 'Y' or 'N'."""
    while True:
        answer = input(f"   {prompt}").strip().upper()
        if answer in ("Y", "N"):
            return answer
        print(f"   {C.YELLOW}↳ Please enter 'Y' or 'N'{C.RESET}")


def copy_csv_to_temp(csv_path: Path) -> Path:
    """
    Copy a CSV file to the temp UPLOAD_DIR if it's not already there.
    Returns the path in UPLOAD_DIR (either newly copied or already present).
    """
    if not csv_path:
        return None

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # If already in UPLOAD_DIR, return as-is
    if csv_path.parent == UPLOAD_DIR:
        return csv_path

    # Copy to UPLOAD_DIR with the original filename
    import shutil
    dest_path = UPLOAD_DIR / csv_path.name
    shutil.copy2(csv_path, dest_path)
    return dest_path


def _load_api_keys_from_file():
    """Load API keys from API_KEYS.txt (user-friendly) or .env (advanced)."""
    # Try API_KEYS.txt first (user-visible, easy to find)
    api_keys_file = ROOT / "API_KEYS.txt"
    if api_keys_file.exists():
        try:
            with open(api_keys_file) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#') or line.startswith('='):
                        continue
                    if '=' in line:
                        key, val = line.split('=', 1)
                        key = key.strip()
                        val = val.strip()
                        # Only set if it looks like a real key (not the example template)
                        if val and not val.startswith('Get it from') and val != 'sk-ant-api03-xxx...':
                            os.environ[key] = val
        except Exception:
            pass

    # Also try .env (for CI/Docker/advanced users with hidden files)
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=True)


def validate_environment():
    """Fail fast if the API key is missing — before wasting 60s on market data."""
    _load_api_keys_from_file()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(f"\n{C.RED}[ERROR]{C.RESET} ANTHROPIC_API_KEY is not set.")
        print()
        print(f"  {C.YELLOW}EASY WAY (recommended):{C.RESET}")
        print("    1. Copy the template file:")
        print("       cp API_KEYS.template.txt API_KEYS.txt")
        print()
        print("    2. Open API_KEYS.txt and paste your API keys:")
        print("       - Anthropic: https://console.anthropic.com/api/keys")
        print("       - (Other APIs listed inside the file)")
        print()
        print("    3. Save the file and run this program again")
        print()
        print(f"  {C.YELLOW}ADVANCED (for Docker/CI):{C.RESET}")
        print("    - Use .env file: cp .env.example .env && nano .env")
        sys.exit(1)


def interactive_setup() -> dict:
    """Walk the user through setup questions with strict input validation."""
    print(f"\n{C.BOLD}{'=' * 65}{C.RESET}")
    print(f"{C.BOLD}  TECH STOCK ADVISOR{C.RESET}")
    print(f"{C.BOLD}{'=' * 65}{C.RESET}")

    # ── Session type ─────────────────────────────────────────────────────
    hour = datetime.now().hour
    default_session = "morning" if hour < 13 else "afternoon"
    print(f"\n  {C.DIM}Current time: {datetime.now().strftime('%H:%M')} — defaulting to {default_session.upper()} session{C.RESET}")

    while True:
        session_input = input(f"  Session type (morning/afternoon) [Enter = {default_session}]: ").strip().lower()
        if not session_input:
            session_type = default_session
            break
        if session_input in ("morning", "afternoon"):
            session_type = session_input
            break
        print(f"   {C.YELLOW}↳ Invalid input. Please enter 'morning' or 'afternoon'{C.RESET}")

    print()

    # ── USD / CAD Budget ─────────────────────────────────────────────────
    print(f"1. Investment budget for this session:")
    budget_usd = _prompt_positive_float("USD", 500)
    print(f"2. Investment budget for this session:")
    budget_cad = _prompt_positive_float("CAD", 1000)

    # ── Holdings CSV (required every time) ────────────────────────────────
    print(f"\n3. {C.BOLD}Holdings CSV{C.RESET}")
    today_str = datetime.now().strftime("%Y-%m-%d")
    print(f"   {C.DIM}Looking for: holdings-report-{today_str}.csv{C.RESET}")

    holdings_auto = find_csv_by_date("holdings-report")
    holdings_path = None

    if holdings_auto:
        print(f"   {C.GREEN}✓ Found:{C.RESET} {C.CYAN}{holdings_auto.resolve()}{C.RESET}")
        if _prompt_yes_no("Use this file? (Y/N): ") == "Y":
            holdings_path = holdings_auto
        else:
            print(f"\n   {C.BOLD}Provide the correct Holdings CSV path:{C.RESET}")
            holdings_path = _prompt_for_existing_path("   Full path to Holdings CSV: ")
    else:
        print(f"   {C.YELLOW}✗ No Holdings CSV found for today ({today_str}){C.RESET}")
        print(f"   {C.YELLOW}Checked: temp folder, Downloads, home directory{C.RESET}")
        print(f"\n   {C.YELLOW}To use today's export, either:{C.RESET}")
        print(f"   {C.DIM}  • Export from Wealthsimple (it auto-includes today's date){C.RESET}")
        print(f"   {C.DIM}  • Place in Downloads or any folder{C.RESET}")
        print(f"   {C.DIM}  • Provide the full path below{C.RESET}\n")
        holdings_path = _prompt_for_existing_path("   Full path to Holdings CSV: ")

    # ── Activities CSV (optional; helps avoid whipsawing) ──────────────────
    activities_path = None
    print(f"\n4. {C.BOLD}Trade History (Activities){C.RESET} {C.DIM}(optional, for context){C.RESET}")
    print(f"   {C.DIM}Looking for: activities-export-{today_str}.csv{C.RESET}")

    activities_auto = find_csv_by_date("activities-export")

    if activities_auto:
        print(f"   {C.GREEN}✓ Found:{C.RESET} {C.CYAN}{activities_auto.resolve()}{C.RESET}")
        if _prompt_yes_no("Use this file? (Y/N): ") == "Y":
            activities_path = activities_auto
        else:
            if _prompt_yes_no("Provide a different Activities CSV? (Y/N): ") == "Y":
                activities_path = _prompt_for_existing_path("   Full path to Activities CSV: ")
    else:
        if _prompt_yes_no("Do you have an Activities CSV to include? (Y/N): ") == "Y":
            activities_path = _prompt_for_existing_path("   Full path to Activities CSV: ")

    # ── Model selection ──────────────────────────────────────────────────
    while True:
        print(f"\n5. {C.BOLD}Which model would you like to use?{C.RESET}")
        for key, (_, name, desc) in MODELS.items():
            print(f"   [{key}] {name} — {desc}")
        model_input = input("   Choose (1/2) [Enter = 1]: ").strip()

        if not model_input:
            model_id, model_name, _ = MODELS["1"]
            break

        if model_input in MODELS:
            model_id, model_name, _ = MODELS[model_input]
            break

        print(f"   {C.YELLOW}↳ Invalid choice. Please enter '1' or '2'{C.RESET}")

    print()

    # Copy CSV files to temp folder if they're not already there
    # (consolidates all input files in one place for easier management)
    if holdings_path:
        holdings_path = copy_csv_to_temp(holdings_path)
    if activities_path:
        activities_path = copy_csv_to_temp(activities_path)

    return {
        "session_type":    session_type,
        "budget_usd":      budget_usd,
        "budget_cad":      budget_cad,
        "holdings_path":   holdings_path,
        "activities_path": activities_path,
        "model_id":        model_id,
        "model_name":      model_name,
    }


def watchlist_tickers(watchlist: dict) -> list:
    """Extract tickers from watchlist entries."""
    return sorted({e["ticker"] for e in watchlist.get("entries", []) if e.get("ticker")})


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

    for t in watchlist_tickers(watchlist):
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


def save_recommendations_csv(
    recommendation: dict,
    session_type: str,
    csv_dir: Path,
    market_data: dict = None,
) -> Path:
    """Save recommendations as a clean CSV table."""
    import csv
    csv_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    csv_path = csv_dir / f"{timestamp}_{session_type}_recommendations.csv"

    recs = recommendation.get("recommendations", [])
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "Ticker", "Action", "Hold Tier", "Conviction",
                "Invest USD", "Expected Stock Move %",
                "Expected Benefit of Action %", "Net Expected %",
                "Time Horizon", "Exit Target", "Bear Case %", "Bull Case %",
                "Stop Loss %", "Take Profit %", "Catalyst Verified", "Catalyst Source", "Manual Review",
                "Quote", "Previous Close", "Quote Time UTC", "Quote Source",
                "Earnings Alert", "Thesis",
            ],
            extrasaction="ignore",
        )
        writer.writeheader()
        for r in recs:
            lo = r.get("price_target_low_pct")
            hi = r.get("price_target_high_pct")
            ticker = r.get("ticker", "")
            md = (market_data or {}).get(ticker, {})
            expected_move = r.get("expected_move_pct", 0)
            net_expected = r.get("net_expected_pct", 0)
            controls = r.get("risk_controls") or {}
            writer.writerow({
                "Ticker":           ticker,
                "Action":           r.get("action", "HOLD"),
                "Hold Tier":        r.get("hold_tier", ""),
                "Conviction":       r.get("conviction", 0),
                "Invest USD":       f"${r['invest_amount_usd']:,.0f}" if r.get("invest_amount_usd") else "",
                "Expected Stock Move %": f"{expected_move:+.2f}%",
                "Expected Benefit of Action %": f"{net_expected:+.2f}%",
                "Net Expected %":   f"{net_expected:+.2f}%",
                "Time Horizon":     r.get("time_horizon", ""),
                "Exit Target":      r.get("target_exit_date", ""),
                "Bear Case %":      f"{lo:+.0f}%" if lo is not None else "",
                "Bull Case %":      f"{hi:+.0f}%" if hi is not None else "",
                "Stop Loss %":      f"{controls.get('stop_loss_pct'):+.1f}%" if controls.get("stop_loss_pct") is not None else "",
                "Take Profit %":    f"{controls.get('take_profit_pct'):+.1f}%" if controls.get("take_profit_pct") is not None else "",
                "Catalyst Verified": "YES" if r.get("catalyst_verified") else "NO",
                "Catalyst Source":  r.get("catalyst_source", ""),
                "Manual Review":    "YES" if r.get("manual_review_required") else "NO",
                "Quote":            f"{md.get('current_price')} {md.get('currency', '')}".strip() if md.get("current_price") is not None else "",
                "Previous Close":   f"{md.get('previous_close')} {md.get('currency', '')}".strip() if md.get("previous_close") is not None else "",
                "Quote Time UTC":   md.get("quote_timestamp_utc", ""),
                "Quote Source":     md.get("quote_source", ""),
                "Earnings Alert":   "⚠️ YES" if r.get("earnings_alert") else "",
                "Thesis":           r.get("thesis", ""),
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
    cost_color = C.GREEN if cost < 0.30 else C.YELLOW
    total_tok = usage.get("total_tokens", 0)
    passes = usage.get("passes", 1)
    print(
        f"  {C.DIM}[{model_name}]{C.RESET}  "
        f"passes: {passes}  "
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
    open_report: bool = True,
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
    risk_benchmarks = settings.get("risk_benchmark_tickers", ["SPY", "QQQ", "SMH"])
    market_data_all = get_market_data(sorted(set(tickers) | set(risk_benchmarks)))
    market_data = {ticker: market_data_all.get(ticker, {}) for ticker in tickers}

    print(f"{C.DIM}[tech_stock] Fetching news...{C.RESET}")
    news_by_ticker = get_news_for_tickers(tickers)

    print(f"{C.DIM}[tech_stock] Fetching enriched intelligence (Finnhub, Polygon, FRED, CoinGecko)...{C.RESET}")
    enriched = enrich(tickers)
    if enriched.get("sources_active"):
        print(f"{C.DIM}[tech_stock] Enrichment sources: {', '.join(enriched['sources_active'])}{C.RESET}")
    else:
        print(f"{C.DIM}[tech_stock] Enrichment: no external sources active (add API keys to .env){C.RESET}")

    if settings.get("enable_options_implied_move_for_earnings", False):
        earnings_tickers = []
        for ticker, data in (enriched.get("per_ticker") or {}).items():
            earnings = data.get("upcoming_earnings") or {}
            if earnings.get("date"):
                earnings_tickers.append(ticker)
        if earnings_tickers:
            print(f"{C.DIM}[tech_stock] Fetching options implied moves for earnings tickers: {', '.join(earnings_tickers)}{C.RESET}")
            add_options_implied_moves(market_data, earnings_tickers)

    print(f"{C.DIM}[tech_stock] Calculating fees...{C.RESET}")
    fee_snapshot = build_fee_snapshot(tickers)

    # ── Sector exposure ───────────────────────────────────────────────────
    sector_exposure = compute_sector_exposure(portfolio.get("holdings", []), market_data)

    # ── Portfolio risk / exposure dashboard ───────────────────────────────
    company_exposure, _ = aggregate_company_exposure(
        portfolio.get("holdings", []),
        settings.get("cad_per_usd_assumption", 1.37),
    )
    risk_dashboard = compute_risk_dashboard(portfolio.get("holdings", []), market_data_all, settings)
    hedge_suggestions = build_hedge_suggestions(risk_dashboard, company_exposure, settings)

    context_symbols = sorted(set(settings.get("sector_rotation_tickers", [])) | set(settings.get("cross_asset_tickers", [])))
    market_context = get_context_moves(context_symbols) if context_symbols else {}

    # ── Watchlist price alerts ────────────────────────────────────────────
    price_alerts = watchlist_price_alerts(watchlist, market_data)
    if price_alerts:
        print(f"{C.DIM}[tech_stock] {len(price_alerts)} watchlist price alert(s){C.RESET}")

    # ── Drift vs previous session ─────────────────────────────────────────
    print(f"{C.DIM}[tech_stock] Computing drift vs previous session...{C.RESET}")
    previous_session = get_previous_session(RECS_LOG_DIR)

    # ── Backtest summary (fed back into prompt for self-calibration) ──────
    print(f"{C.DIM}[tech_stock] Running backtest on past recommendations...{C.RESET}")
    backtest_summary = run_backtest(RECS_LOG_DIR)
    if backtest_summary.get("n_samples", 0) > 0:
        print(
            f"{C.DIM}[tech_stock] Track record: {backtest_summary['n_samples']} samples, "
            f"avg {backtest_summary['overall']['avg_return_pct']:+.2f}%, "
            f"win {backtest_summary['overall']['hit_rate']:.0%}{C.RESET}"
        )

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
            sector_exposure=sector_exposure,
            backtest_summary=backtest_summary,
            price_alerts=price_alerts,
            previous_session=previous_session,
            risk_dashboard=risk_dashboard,
            company_exposure=company_exposure,
            market_context=market_context,
            hedge_suggestions=hedge_suggestions,
            enriched=enriched,
        )
    except ValueError as e:
        print(f"{C.RED}[ERROR]{C.RESET} Claude response parsing failed: {e}")
        sys.exit(1)

    # ── Compute drift between this run and the previous session ───────────
    drift = recommendation.get("drift_vs_previous") or compute_drift(
        recommendation,
        previous_session,
        conviction_delta_threshold=settings.get("drift_conviction_delta", 2),
    )
    if drift:
        recommendation["drift_vs_previous"] = drift  # persist into log

    log_path = save_recommendation_log(recommendation, session_type)
    md_content = generate_markdown(
        session_type,
        recommendation,
        market_data,
        news_by_ticker=news_by_ticker,
        portfolio=portfolio,
        sector_exposure=sector_exposure,
        backtest_summary=backtest_summary,
        drift=drift,
        price_alerts=price_alerts,
        recent_activities=recent_activities,
        enriched=enriched,
        risk_dashboard=risk_dashboard,
        company_exposure=company_exposure,
        market_context=market_context,
        usage=usage,
        settings=settings,
        previous_session=previous_session,
    )
    report_path = save_report(md_content, session_type, REPORTS_DIR)
    csv_path = save_recommendations_csv(recommendation, session_type, REPORTS_DIR, market_data)

    print_summary(recommendation, session_type)
    print_usage(usage, display_model)

    print(f"\n{C.BOLD}{'=' * 65}{C.RESET}")
    print(f"  {C.BOLD}📊 Markdown report:{C.RESET}")
    print(f"  {C.CYAN}{report_path.resolve()}{C.RESET}\n")
    print(f"  {C.BOLD}📋 CSV table:{C.RESET}")
    print(f"  {C.CYAN}{csv_path.resolve()}{C.RESET}")
    print(f"{C.BOLD}{'=' * 65}{C.RESET}\n")

    if open_report:
        open_file(report_path)

    return {
        "recommendation": recommendation,
        "usage": usage,
        "report_path": report_path,
        "csv_path": csv_path,
        "log_path": log_path,
        "session_type": session_type,
        "model_name": display_model,
    }


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
