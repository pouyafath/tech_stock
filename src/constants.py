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
