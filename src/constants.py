"""
constants.py
Shared symbol lists and small constants used across multiple modules.
Keep this file dependency-free — only stdlib imports.
"""

# Daily-reset 2x/3x leveraged ETFs — should not be held > ~14 days due to decay.
# Used by report_generator (warning section) and referenced by the system prompt
# in claude_analyst (rule 11).
LEVERAGED_ETFS = frozenset({
    "SOXL", "SOXS", "TQQQ", "SQQQ", "UPRO", "UVXY", "TMF", "TZA", "SPXL",
    "LABU", "LABD", "TSLL", "NVDL", "TMV", "UDOW", "SDOW", "FAS", "FAZ",
    "TNA", "YINN", "YANG",
})

LEVERAGED_ETF_LEVERAGE = {
    "SOXL": 3.0,
    "SOXS": -3.0,
    "TQQQ": 3.0,
    "SQQQ": -3.0,
    "UPRO": 3.0,
    "UVXY": 1.5,
    "TMF": 3.0,
    "TZA": -3.0,
    "SPXL": 3.0,
    "LABU": 3.0,
    "LABD": -3.0,
    "TSLL": 2.0,
    "NVDL": 2.0,
    "TMV": -3.0,
    "UDOW": 3.0,
    "SDOW": -3.0,
    "FAS": 3.0,
    "FAZ": -3.0,
    "TNA": 3.0,
    "YINN": 3.0,
    "YANG": -3.0,
}


# Pairs where one ticker is a near-duplicate / share class of the other.
# When both appear in a portfolio + watchlist union, drop the second.
DEDUP_PAIRS = (
    ("GOOGL", "GOOG"),
    ("BRK.A", "BRK.B"),
)


# Tickers that should never be sent to yfinance (synthetic / not-listed-as-equity).
SKIP_MARKET_DATA = frozenset({"CASH"})


# Wealthsimple "Exchange" / "MIC" values that indicate a CDR (CAD-hedged
# Canadian Depositary Receipt) listed on TSX rather than the US line.
CDR_EXCHANGES = frozenset({"XTSE", "TSX"})


# Deterministic sector labels for ETFs/CDRs/share classes that yfinance may
# report as Unknown or that may be skipped after ticker de-duplication.
SECTOR_OVERRIDES = {
    "ARKF": "Technology",
    "ARKK": "Technology",
    "ARKQ": "Technology",
    "ARKG": "Healthcare",
    "SOXL": "Semiconductors",
    "SOXS": "Semiconductors",
    "TQQQ": "Technology",
    "SQQQ": "Technology",
    "SPY": "Broad Market ETF",
    "VOO": "Broad Market ETF",
    "VGRO": "Multi-Asset ETF",
    "VGRO.TO": "Multi-Asset ETF",
    "XEQT": "Multi-Asset ETF",
    "XEQT.TO": "Multi-Asset ETF",
    "VEQT": "Multi-Asset ETF",
    "VEQT.TO": "Multi-Asset ETF",
    "VCNS": "Multi-Asset ETF",
    "VCNS.TO": "Multi-Asset ETF",
}


SECTOR_ALIASES = {
    "GOOG": "GOOGL",
    "BRK.B": "BRK.A",
}


COMPANY_GROUPS = {
    "AAPL": {"AAPL", "AAPL.TO"},
    "AMD": {"AMD", "AMD.TO"},
    "AMZN": {"AMZN", "AMZN.TO"},
    "AVGO": {"AVGO", "AVGO.TO"},
    "COST": {"COST", "COST.TO"},
    "CRWD": {"CRWD", "CRWD.TO"},
    "GOOGL": {"GOOGL", "GOOG", "GOOGL.TO", "GOOG.TO"},
    "INTC": {"INTC", "INTC.TO"},
    "META": {"META", "META.TO"},
    "MSFT": {"MSFT", "MSFT.TO"},
    "NVDA": {"NVDA", "NVDA.TO"},
    "PLTR": {"PLTR", "PLTR.TO"},
    "SHOP": {"SHOP", "SHOP.TO"},
    "SPOT": {"SPOT", "SPOT.TO"},
    "TSLA": {"TSLA", "TSLA.TO"},
    "TSM": {"TSM", "TSM.TO"},
}


COMPANY_ALIASES = {
    alias: company
    for company, aliases in COMPANY_GROUPS.items()
    for alias in aliases
}


RISK_BENCHMARK_TICKERS = ("SPY", "QQQ", "SMH")


SECTOR_ROTATION_TICKERS = ("XLK", "XLV", "XLF", "XLE", "XLY", "XLP", "XLU", "XLI")


CROSS_ASSET_TICKERS = ("UUP", "TLT", "GLD", "HYG")
