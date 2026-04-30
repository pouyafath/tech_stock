"""
enriched_data.py
Orchestrates all enrichment API calls (Finnhub, Alpha Vantage, Twelve Data,
Polygon, FRED, CoinGecko) and returns a unified data structure ready to be
injected into the Claude prompt.

Architecture:
  Phase 1 (parallel): Finnhub, Polygon, Twelve Data, FRED, CoinGecko
  Phase 2 (sequential): Alpha Vantage — optional (disabled by default due to 25 req/day limit).
    Can be enabled in settings.json if using a paid plan. Free tier is not recommended.

Any individual source that fails is simply omitted — the run continues.
The key contract: enrich(tickers) always returns a dict, never raises.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from src.alpha_vantage_client import news_sentiment as av_sentiment
from src.coingecko_client import crypto_context
from src.config import load_settings
from src.finnhub_client import (
    earnings_calendar,
    earnings_surprises,
    insider_summary,
    news_sentiment as finnhub_sentiment,
    recommendation_trends,
    upgrade_downgrade,
)
from src.fred_client import economic_calendar_estimate, macro_context
from src.polygon_client import stock_snapshot
from src.twelve_data_client import earnings as td_earnings
from src.twelve_data_client import quote as td_quote


def _degradation(source: str, operation: str, error: Exception, ticker: str | None = None) -> dict:
    return {
        "source": source,
        "operation": operation,
        "ticker": ticker,
        "error": f"{type(error).__name__}: {error}",
    }


def _enrich_ticker_fast(ticker: str) -> dict:
    """
    Per-ticker enrichment from fast sources (Finnhub, Polygon, Twelve Data).
    Alpha Vantage is excluded here — it's rate-limited to 5/min and handled
    sequentially in enrich() after the parallel phase completes.
    """
    result: dict = {"_degradation": []}

    # Finnhub
    try:
        rec = recommendation_trends(ticker)
        if rec:
            result["analyst_consensus"] = rec
    except Exception as e:
        result["_degradation"].append(_degradation("finnhub", "recommendation_trends", e, ticker))

    try:
        upgrades = upgrade_downgrade(ticker, days_back=90)
        if upgrades:
            result["upgrade_downgrade"] = upgrades
    except Exception as e:
        result["_degradation"].append(_degradation("finnhub", "upgrade_downgrade", e, ticker))

    try:
        ec = earnings_calendar(ticker, days_ahead=45)
        if ec:
            result["upcoming_earnings"] = ec
    except Exception as e:
        result["_degradation"].append(_degradation("finnhub", "earnings_calendar", e, ticker))

    try:
        es = earnings_surprises(ticker, limit=4)
        if es:
            result["earnings_history"] = es
    except Exception as e:
        result["_degradation"].append(_degradation("finnhub", "earnings_surprises", e, ticker))

    try:
        ins = insider_summary(ticker, days=90)
        if ins:
            result["insider_activity"] = ins
    except Exception as e:
        result["_degradation"].append(_degradation("finnhub", "insider_summary", e, ticker))

    try:
        fh_sent = finnhub_sentiment(ticker)
        if fh_sent:
            result["finnhub_sentiment"] = fh_sent
    except Exception as e:
        result["_degradation"].append(_degradation("finnhub", "news_sentiment", e, ticker))

    # Polygon — previous-day OHLCV + VWAP signal
    try:
        snap = stock_snapshot(ticker)
        if snap:
            result["polygon_snapshot"] = snap
    except Exception as e:
        result["_degradation"].append(_degradation("polygon", "stock_snapshot", e, ticker))

    # Twelve Data — Canadian tickers get better coverage here
    try:
        td_q = td_quote(ticker)
        if td_q:
            result["td_quote"] = td_q
    except Exception as e:
        result["_degradation"].append(_degradation("twelve_data", "quote", e, ticker))

    try:
        td_e = td_earnings(ticker)
        if td_e:
            result["td_earnings"] = td_e
    except Exception as e:
        result["_degradation"].append(_degradation("twelve_data", "earnings", e, ticker))

    return result


def enrich(tickers: list[str]) -> dict:
    """
    Fetch enrichment data for all tickers, plus macro/crypto context.

    Phase 1: parallel fetch of Finnhub, Polygon, Twelve Data, FRED, CoinGecko.
    Phase 2: sequential Alpha Vantage calls (5 req/min limit).

    Returns:
        {
            "per_ticker": {
                "NVDA": {
                    "analyst_consensus": {...},
                    "upcoming_earnings": {...},
                    "earnings_history": [...],
                    "insider_activity": {...},
                    "finnhub_sentiment": {...},
                    "polygon_snapshot": {...},
                    "td_quote": {...},
                    "av_sentiment": {...},
                },
                ...
            },
            "macro": {
                "series": {...},
                "rate_regime": "...",
                "yield_curve_signal": "...",
                "vix_regime": "...",
                "inflation_signal": "...",
            },
            "crypto": {
                "btc_price": ...,
                "btc_change_7d": ...,
                "risk_signal": "NEUTRAL|CAUTION|RISK-OFF|RISK-ON",
                "risk_note": "...",
            },
            "fetched_at": "2026-04-29T10:22:00",
            "sources_active": [...],
        }
    """
    settings = load_settings()
    if not settings.get("enable_enrichment", True):
        return {"per_ticker": {}, "macro": None, "crypto": None, "sources_active": [], "degradation": []}

    out: dict = {
        "per_ticker": {t: {} for t in tickers},
        "macro": None,
        "economic_calendar": economic_calendar_estimate(),
        "crypto": None,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "sources_active": [],
        "degradation": [],
    }

    # ── Phase 1: Parallel fast sources ───────────────────────────────────────
    max_workers = min(8, len(tickers) + 2) if tickers else 2

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        ticker_futures = {ex.submit(_enrich_ticker_fast, t): t for t in tickers}
        macro_future   = ex.submit(_safe(macro_context, "fred"))
        crypto_future  = ex.submit(_safe(crypto_context, "coingecko"))

        for future in as_completed(list(ticker_futures) + [macro_future, crypto_future]):
            if future is macro_future:
                macro_result = future.result()
                if isinstance(macro_result, dict) and macro_result.get("_degradation"):
                    out["degradation"].append(macro_result["_degradation"])
                    out["macro"] = None
                else:
                    out["macro"] = macro_result
            elif future is crypto_future:
                crypto_result = future.result()
                if isinstance(crypto_result, dict) and crypto_result.get("_degradation"):
                    out["degradation"].append(crypto_result["_degradation"])
                    out["crypto"] = None
                else:
                    out["crypto"] = crypto_result
            else:
                ticker = ticker_futures[future]
                try:
                    ticker_result = future.result()
                    out["degradation"].extend(ticker_result.pop("_degradation", []) or [])
                    out["per_ticker"][ticker] = ticker_result
                except Exception as e:
                    out["degradation"].append(_degradation("enrich", "_enrich_ticker_fast", e, ticker))
                    out["per_ticker"][ticker] = {}

    # ── Phase 2: Sequential Alpha Vantage (free tier: only 25 req/day) ────────
    if settings.get("alpha_vantage_enabled", False):
        for ticker in tickers:
            try:
                av_sent = av_sentiment(ticker, limit=10)
                if av_sent:
                    out["per_ticker"].setdefault(ticker, {})["av_sentiment"] = av_sent
            except Exception as e:
                out["degradation"].append(_degradation("alpha_vantage", "news_sentiment", e, ticker))

    # ── Tally active sources ──────────────────────────────────────────────────
    sources = set()
    for ticker_data in out["per_ticker"].values():
        if ticker_data.get("analyst_consensus") or ticker_data.get("upgrade_downgrade"):
            sources.add("finnhub")
        if ticker_data.get("polygon_snapshot"):
            sources.add("polygon")
        if ticker_data.get("av_sentiment"):
            sources.add("alpha_vantage")
        if ticker_data.get("td_quote"):
            sources.add("twelve_data")
    if out["macro"]:
        sources.add("fred")
    if out.get("economic_calendar"):
        sources.add("calendar_estimate")
    if out["crypto"]:
        sources.add("coingecko")

    out["sources_active"] = sorted(sources)
    return out


def _safe(fn, source: str = None):
    """Wrap a zero-arg callable to never raise."""
    def wrapper():
        try:
            return fn()
        except Exception as e:
            return {"_degradation": _degradation(source or fn.__name__, fn.__name__, e)}
    return wrapper


def format_enrichment_for_prompt(enriched: dict) -> str:
    """Convert enriched data to a concise text block for the Claude prompt."""
    if not enriched or not any([
        enriched.get("per_ticker"),
        enriched.get("macro"),
        enriched.get("crypto"),
    ]):
        return ""

    lines = ["\n## ENRICHED MARKET INTELLIGENCE\n"]
    sources = enriched.get("sources_active", [])
    if sources:
        lines.append(f"*Data sources: {', '.join(sources)}*\n")
    degradation = enriched.get("degradation") or []
    if degradation:
        lines.append("### Data Coverage / Degradation")
        for item in degradation[:12]:
            ticker = f"{item.get('ticker')}: " if item.get("ticker") else ""
            lines.append(
                f"  - {ticker}{item.get('source')}.{item.get('operation')} "
                f"unavailable ({item.get('error')})"
            )
        lines.append("")

    # ── Macro context ─────────────────────────────────────────────────────
    macro = enriched.get("macro")
    if macro:
        lines.append("### Macro Environment (FRED)")
        series = macro.get("series") or {}
        for sid, info in series.items():
            val = info.get("value")
            if val is not None:
                lines.append(f"  - {info['label']}: {val:.2f}{info['units']}")
        lines.append(f"  - Rate regime: {macro.get('rate_regime', 'N/A')}")
        lines.append(f"  - Yield curve: {macro.get('yield_curve_signal', 'N/A')}")
        lines.append(f"  - Inflation: {macro.get('inflation_signal', 'N/A')}")
        lines.append(f"  - VIX regime: {macro.get('vix_regime', 'N/A')}")
        lines.append("")

    econ = enriched.get("economic_calendar") or (macro or {}).get("economic_calendar")
    if econ:
        lines.append("### Macro Event Calendar")
        if econ.get("next_nfp_estimate"):
            lines.append(f"  - Next NFP estimate: {econ['next_nfp_estimate']}")
        if econ.get("next_cpi_window"):
            lines.append(f"  - CPI release window estimate: {econ['next_cpi_window']}")
        if econ.get("fomc_note"):
            lines.append(f"  - {econ['fomc_note']}")
        lines.append("")

    # ── Crypto context ────────────────────────────────────────────────────
    crypto = enriched.get("crypto")
    if crypto:
        lines.append("### Crypto Context (CoinGecko + Fear & Greed)")
        if crypto.get("btc_price") is not None:
            lines.append(
                f"  - BTC: ${crypto['btc_price']:,.0f} "
                f"(24h: {(crypto.get('btc_change_24h') or 0):+.1f}%, "
                f"7d: {(crypto.get('btc_change_7d') or 0):+.1f}%)"
            )
        if crypto.get("fear_greed_index") is not None:
            lines.append(
                f"  - Fear & Greed: {crypto['fear_greed_index']} ({crypto.get('fear_greed_label', '')})"
            )
        lines.append(f"  - Risk signal: **{crypto.get('risk_signal', 'NEUTRAL')}**")
        lines.append(f"  - {crypto.get('risk_note', '')}")
        lines.append("")

    # ── Per-ticker enrichment ─────────────────────────────────────────────
    per_ticker = enriched.get("per_ticker") or {}
    ticker_lines = []
    for ticker, data in sorted(per_ticker.items()):
        if not data:
            continue
        t_lines = [f"#### {ticker}"]

        rec = data.get("analyst_consensus")
        if rec:
            t_lines.append(
                f"  - Analyst consensus: **{rec['consensus_label']}** "
                f"({rec['buy']}B / {rec['hold']}H / {rec['sell']}S "
                f"from {rec['total_analysts']} analysts, {rec.get('period', '')})"
            )

        upgrades = data.get("upgrade_downgrade")
        if upgrades:
            recent = upgrades[0]
            t_lines.append(
                f"  - Latest analyst rating change: {recent.get('action', 'rating change')} "
                f"{recent.get('from_grade') or 'N/A'} -> {recent.get('to_grade') or 'N/A'} "
                f"by {recent.get('firm') or 'unknown firm'} ({str(recent.get('date') or '')[:10]})"
            )

        ue = data.get("upcoming_earnings")
        if ue and ue.get("date"):
            hour = " (BMO)" if ue.get("hour") == "bmo" else " (AMC)" if ue.get("hour") == "amc" else ""
            eps_str = f", EPS est: ${ue['eps_estimate']}" if ue.get("eps_estimate") else ""
            t_lines.append(f"  - Next earnings: {ue['date']}{hour}{eps_str}")

        eh = data.get("earnings_history")
        if eh:
            recent = eh[0]
            surp = recent.get("surprise_pct")
            if surp is not None:
                icon = "✅" if surp > 0 else "❌"
                t_lines.append(
                    f"  - Last EPS surprise: {icon} {surp:+.1f}% "
                    f"({recent.get('period', '')})"
                )
            # Streak: number of consecutive beats
            beats = sum(1 for q in eh if (q.get("surprise_pct") or 0) > 0)
            if beats == len(eh) and len(eh) >= 3:
                t_lines.append(f"  - ✅ Beat estimates {beats} quarters in a row")
            elif beats == 0 and len(eh) >= 3:
                t_lines.append(f"  - ❌ Missed estimates {len(eh)} quarters in a row")

        ins = data.get("insider_activity")
        if ins:
            icon = "🟢" if ins["signal"] == "BUYING" else "🔴" if ins["signal"] == "SELLING" else "⚪"
            t_lines.append(
                f"  - Insider activity (90d): {icon} {ins['signal']} "
                f"({ins['buys']} buys / {ins['sells']} sells, "
                f"net {ins['net_shares']:+,} shares)"
            )

        snap = data.get("polygon_snapshot")
        if snap:
            vwap_sig = snap.get("vwap_signal", "")
            after = snap.get("after_hrs_change_pct")
            after_str = f", after-hours {after:+.1f}%" if after is not None else ""
            snapshot_change = snap.get("snapshot_change_pct")
            snapshot_str = f", snapshot change {snapshot_change:+.1f}%" if snapshot_change is not None else ""
            t_lines.append(
                f"  - Previous session (Polygon): VWAP {snap.get('vwap_pct', 0):+.1f}% -> {vwap_sig}"
                f"{after_str}{snapshot_str}"
            )

        fh_sent = data.get("finnhub_sentiment")
        if fh_sent:
            bull = fh_sent.get("bullish_pct")
            bear = fh_sent.get("bearish_pct")
            if bull is not None:
                t_lines.append(
                    f"  - News buzz (Finnhub): {bull*100:.0f}% bullish / "
                    f"{bear*100:.0f}% bearish"
                )

        av_sent = data.get("av_sentiment")
        if av_sent:
            t_lines.append(
                f"  - AV sentiment: **{av_sent['label']}** "
                f"(score {av_sent['ticker_avg_sentiment']:+.3f} "
                f"from {av_sent['articles_analyzed']} articles)"
            )

        # Only append if there's real content beyond the ticker header
        if len(t_lines) > 1:
            ticker_lines.extend(t_lines)
            ticker_lines.append("")

    if ticker_lines:
        lines.append("### Per-Ticker Enrichment")
        lines.extend(ticker_lines)

    return "\n".join(lines)


if __name__ == "__main__":
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).parent.parent / ".env")

    tickers = ["NVDA", "MSFT", "PLTR", "SHOP.TO"]
    print("Fetching enriched data...")
    data = enrich(tickers)
    print(f"Sources active: {data['sources_active']}")
    print("\n" + "=" * 60)
    print(format_enrichment_for_prompt(data))
