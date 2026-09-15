"""Central configuration module for the Stock Valuation Data Pipeline.

Defines project directory paths, data freshness rules, validation criteria,
and baseline financial/valuation model parameters.
"""

from pathlib import Path

# =====================================================================
# Project Directories & File Paths
# =====================================================================
BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"
SQL_DIR = BASE_DIR / "sql"
REPORTS_DIR = BASE_DIR / "reports"
LOGS_DIR = BASE_DIR / "logs"
TESTS_DIR = BASE_DIR / "tests"

DB_PATH = DATA_DIR / "valuation.db"
LOG_FILE = LOGS_DIR / "pipeline.log"

# Ensure runtime directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# =====================================================================
# Target Tickers Universe
# =====================================================================
DEFAULT_TICKERS = ["AAPL", "MSFT", "NVDA"]

# =====================================================================
# Data Ingestion & Freshness Configuration
# =====================================================================
# Financial statements change quarterly/annually; refetch only when older than 7 days
FUNDAMENTALS_FRESHNESS_DAYS = 7

# On regular pipeline runs, fetch a small trailing window for idempotent upserts
MARKET_DATA_TRAILING_DAYS = 10

# Default historical period for initial market data load.
# NOTE: Verify in Phase 5 (market_analysis.py) that 2y (~504 trading days / 24 months)
# aligns with the exact volatility and monthly return window before finalizing.
MARKET_DATA_HISTORY_PERIOD = "2y"

# =====================================================================
# Data Validation Settings
# =====================================================================
REQUIRED_STATEMENT_TYPES = ["income", "balance", "cashflow"]

REQUIRED_INCOME_ITEMS = [
    "total_revenue",
    "operating_income",
    "net_income",
]

REQUIRED_BALANCE_ITEMS = [
    "total_assets",
    "total_liabilities",
    "cash_and_cash_equivalents",
    "total_debt",
]

REQUIRED_CASHFLOW_ITEMS = [
    "operating_cash_flow",
    "capital_expenditure",
]

REQUIRED_OHLCV_FIELDS = [
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
]

# Minimum years of continuous financial data required for DCF and trend analysis
MIN_FINANCIAL_YEARS = 3

# Max gap of consecutive missing trading days before emitting a data-quality warning
MAX_CONSECUTIVE_GAP_DAYS_WARNING = 5

# =====================================================================
# Valuation & DCF Modeling Baseline Assumptions
# =====================================================================
DEFAULT_RISK_FREE_RATE = 0.042       # 10-Year US Treasury yield proxy (4.2%)
DEFAULT_MARKET_RISK_PREMIUM = 0.055  # Equity Risk Premium (5.5%)
DEFAULT_TERMINAL_GROWTH_RATE = 0.025 # Long-term GDP growth rate proxy (2.5%)
DEFAULT_TAX_RATE = 0.21              # US Corporate Tax Rate (21%)
DEFAULT_COST_OF_DEBT = 0.045         # Base pre-tax cost of debt if unavailable (4.5%)
PROJECTION_YEARS = 5                 # Forecast horizon

# Scenario parameters (multipliers or delta adjustments against base DCF assumptions)
SCENARIOS = {
    "bull": {
        "revenue_growth_multiplier": 1.20,
        "operating_margin_multiplier": 1.10,
        "wacc_adjustment": -0.005,           # Lower discount rate (-50 bps)
        "terminal_growth_adjustment": 0.005, # Higher terminal growth (+50 bps)
    },
    "base": {
        "revenue_growth_multiplier": 1.00,
        "operating_margin_multiplier": 1.00,
        "wacc_adjustment": 0.0,
        "terminal_growth_adjustment": 0.0,
    },
    "bear": {
        "revenue_growth_multiplier": 0.80,
        "operating_margin_multiplier": 0.90,
        "wacc_adjustment": 0.010,            # Higher discount rate (+100 bps)
        "terminal_growth_adjustment": -0.005,# Lower terminal growth (-50 bps)
    },
}

# Monte Carlo simulation settings (optional extension)
MONTE_CARLO_SIMULATIONS = 10000
MONTE_CARLO_SEED = 42
