# Contributing to tech_stock

Thank you for your interest in contributing! This document provides guidelines for contributing to the project.

## Code of Conduct

- Be respectful and constructive in discussions
- Test your changes with real portfolio data before submitting
- Follow the existing code style and structure
- Document your changes clearly

---

## Getting Started

### 1. Fork and Clone

```bash
git clone https://github.com/your-username/tech_stock.git
cd tech_stock
```

### 2. Set Up Development Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install pytest black flake8  # dev dependencies
```

### 3. Create a Feature Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

---

## Development Workflow

### Making Changes

1. **Edit files** in `src/` or config directories
2. **Test locally** with your own Wealthsimple CSV exports
3. **Run basic checks:**
   ```bash
   # Format code
   black src/
   
   # Check style
   flake8 src/ --max-line-length=100
   
   # Run tests (if available)
   pytest tests/
   ```

### Testing Your Changes

Before submitting a PR, test with:

```bash
# Interactive mode
python src/main.py

# CLI mode with your CSVs
python src/main.py morning --holdings ~/Downloads/holdings-report.csv

# Different models
python src/main.py morning --holdings ~/Downloads/holdings-report.csv --model opus
```

Verify:
- ✅ No errors in terminal output
- ✅ CSV files are generated correctly
- ✅ Report markdown is properly formatted
- ✅ JSON log is valid

---

## Areas for Contribution

### High Priority

- **Broker support:** Add fee models for Interactive Brokers, Questrade, etc.
- **Backtesting framework:** Compare recommendations vs actual outcomes
- **Risk metrics:** Sharpe ratio, maximum drawdown, volatility analysis
- **Test suite:** Unit tests for parsers, calculators, and API integration

### Medium Priority

- **Output formats:** Excel (.xlsx), HTML reports, PDF export
- **Notifications:** Discord webhooks, Slack integration, email summaries
- **Performance:** Optimize yfinance calls (batch multiple tickers in one API call)
- **Documentation:** YAML examples, video tutorials, troubleshooting guides

### Nice to Have

- **Web dashboard:** Real-time portfolio view + recommendation history
- **Mobile app:** iOS/Android notifications
- **A/B testing:** Compare Sonnet vs Opus recommendations
- **Community benchmarks:** Leaderboard of recommendation performance

---

## Coding Standards

### Style

- **Python version:** 3.11+
- **Line length:** Max 100 characters
- **Formatting:** Black (auto-format with `black src/`)
- **Linting:** Flake8 with `--max-line-length=100`

### Code Structure

```python
"""Module docstring describing purpose."""

import standard_lib
import third_party_lib
from local import module

# Constants in UPPER_CASE
MAX_POSITIONS = 25

def function_name(param1: str, param2: int) -> dict:
    """
    Brief description.
    
    Args:
        param1: What it does
        param2: What it does
    
    Returns:
        What it returns
    """
    pass
```

### Type Hints

Use type hints for clarity:

```python
from pathlib import Path
from typing import Optional

def load_portfolio(path: Path, fallback: Optional[dict] = None) -> dict:
    """Load portfolio from CSV or return fallback."""
    pass
```

---

## Commit Messages

Use clear, descriptive commit messages:

```bash
# Good
git commit -m "Add support for Interactive Brokers fee model"
git commit -m "Fix CSV parsing for fractional shares"
git commit -m "Improve Claude prompt for intraday recommendations"

# Avoid
git commit -m "fix bug"
git commit -m "update code"
```

Include a body for larger changes:

```
Add Interactive Brokers fee model

- Implements IB fee structure with tiered commissions
- Handles USD account FX conversion costs
- Updates fee_calculator.py with new broker class
- Adds tests for IB fee accuracy

Fixes #42
```

---

## Pull Request Process

1. **Before submitting:**
   - Run `black src/` and `flake8 src/`
   - Test with your own portfolio data
   - Update README if adding features
   - Add your name to CONTRIBUTORS (optional)

2. **Create PR with:**
   - Clear title: "Add/Fix: Brief description"
   - Description of what changed and why
   - Reference related issues: "Fixes #123"
   - Test results and any caveats

3. **PR review:**
   - Wait for feedback
   - Make requested changes in new commits (don't force-push unless asked)
   - Respond to questions in comments

4. **Merging:**
   - Your PR will be merged after approval
   - You'll be listed in CONTRIBUTORS.md

---

## Common Contributions

### Adding a New Broker Fee Model

File: `src/fee_calculator.py`

```python
class InteractiveBrokersFees:
    """Fee model for Interactive Brokers USD accounts."""
    
    def __init__(self, tier: str = "standard"):
        self.tier = tier
    
    def get_bid_ask_pct(self, ticker: str, exchange: str) -> float:
        """Return one-way bid-ask spread as percentage."""
        # Implement tier-based spreads
        return 0.001  # 0.1% one-way
    
    def get_commission_usd(self, notional: float) -> float:
        """Return per-trade commission in USD."""
        # IB: $1 per trade for US stocks (might waive for $20k+ account)
        return 1.0
    
    def calculate_round_trip_cost_pct(self, ticker: str, notional: float) -> float:
        """Calculate full round-trip cost as percentage of trade."""
        bid_ask_cost = 2 * self.get_bid_ask_pct(ticker, "NYSE")
        commission_cost = self.get_commission_usd(notional) / notional * 100
        return bid_ask_cost + commission_cost
```

Then update `main.py` to allow selecting brokers.

### Adding a New Output Format

File: `src/report_generator.py`

```python
def generate_excel(
    session_type: str,
    recommendation: dict,
    market_data: dict,
) -> str:
    """Generate Excel report with charts."""
    import openpyxl
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Recommendations"
    
    # Add headers and data
    # Add conditional formatting, charts, etc.
    
    return wb
```

### Adding Tests

File: `tests/test_portfolio_loader.py`

```python
import pytest
from src.portfolio_loader import parse_holdings_csv
from pathlib import Path

def test_parse_holdings_csv():
    """Test parsing of Holdings CSV."""
    csv_path = Path("tests/fixtures/sample_holdings.csv")
    portfolio = parse_holdings_csv(csv_path)
    
    assert len(portfolio["holdings"]) == 5
    assert portfolio["cash_cad"] == 1000.0
    assert portfolio["source"] == "holdings_csv"
```

---

## Questions?

- **Setup help:** See [README.md](README.md#-troubleshooting)
- **Architecture:** See [README.md](README.md#-architecture)
- **GitHub Issues:** Open an issue to discuss larger changes before coding

---

## Contributor List

Thanks to everyone who's contributed!

- [@pouyafath](https://github.com/pouyafath) — Original creator
- [Your name here!]

---

**Thank you for contributing to tech_stock!** 🚀
