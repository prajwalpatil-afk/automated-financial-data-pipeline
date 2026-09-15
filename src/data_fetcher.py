"""Data ingestion module for financial statements and market data via yfinance.

Extracts company profiles, normalized multi-year financial statements,
and historical OHLCV data into structured dictionaries.
"""

from datetime import datetime, timedelta
import logging
from typing import Any, Dict, List, Optional
import pandas as pd
import yfinance as yf

from src.config import (
    MARKET_DATA_HISTORY_PERIOD,
    MARKET_DATA_TRAILING_DAYS,
    REQUIRED_BALANCE_ITEMS,
    REQUIRED_CASHFLOW_ITEMS,
    REQUIRED_INCOME_ITEMS,
)

logger = logging.getLogger(__name__)


class DataExtractionError(Exception):
    """Raised when an error occurs while fetching or extracting financial data."""
    pass


class TickerNotFoundError(DataExtractionError):
    """Raised when a ticker symbol cannot be resolved by yfinance."""
    pass


# Map raw yfinance line item variations to canonical snake_case identifiers
LINE_ITEM_MAPPING = {
    # Income statement variations
    "Total Revenue": "total_revenue",
    "Operating Revenue": "total_revenue",
    "Revenue": "total_revenue",
    "Operating Income": "operating_income",
    "Operating Expense": "operating_expense",
    "Net Income": "net_income",
    "Net Income Common Stockholders": "net_income",
    "EBIT": "ebit",
    "Interest Expense": "interest_expense",
    "Tax Provision": "tax_provision",

    # Balance sheet variations
    "Total Assets": "total_assets",
    "Total Liabilities Net Minority Interest": "total_liabilities",
    "Total Liabilities": "total_liabilities",
    "Cash And Cash Equivalents": "cash_and_cash_equivalents",
    "Cash Cash Equivalents And Short Term Investments": "cash_and_cash_equivalents",
    "Total Debt": "total_debt",
    "Long Term Debt": "long_term_debt",
    "Current Debt": "current_debt",
    "Stockholders Equity": "stockholders_equity",
    "Common Stock Equity": "stockholders_equity",

    # Cash flow statement variations
    "Operating Cash Flow": "operating_cash_flow",
    "Cash Flow From Continuing Operating Activities": "operating_cash_flow",
    "Capital Expenditure": "capital_expenditure",
    "Free Cash Flow": "free_cash_flow",
    "Investing Cash Flow": "investing_cash_flow",
    "Financing Cash Flow": "financing_cash_flow",
}


def _normalize_line_item(raw_name: str) -> Optional[str]:
    """Map a raw statement line item to its standardized name."""
    cleaned = str(raw_name).strip()
    return LINE_ITEM_MAPPING.get(cleaned)


def fetch_company_profile(ticker: str) -> Dict[str, Any]:
    """Fetch high-level company profile and market metadata from yfinance.

    Args:
        ticker: Uppercase stock ticker symbol (e.g. 'AAPL').

    Returns:
        Dict containing ticker, company_name, sector, industry, beta,
        shares_outstanding, and current_price.

    Raises:
        TickerNotFoundError: If the ticker is invalid or returns no data.
        DataExtractionError: If network or extraction fails.
    """
    ticker_clean = ticker.upper().strip()
    logger.info("Fetching company profile for %s", ticker_clean)
    try:
        yf_ticker = yf.Ticker(ticker_clean)
        info = yf_ticker.info

        # yfinance often returns an empty dict or {'trailingPegRatio': None} for invalid tickers
        if not info or ("symbol" not in info and "shortName" not in info and "regularMarketPrice" not in info):
            # Check fast_info as fallback
            fast_info = getattr(yf_ticker, "fast_info", None)
            if not fast_info or not hasattr(fast_info, "last_price") or fast_info.last_price is None:
                raise TickerNotFoundError(f"Ticker '{ticker_clean}' not found or returned no data.")

        company_name = info.get("longName") or info.get("shortName") or ticker_clean
        sector = info.get("sector", "Unknown")
        industry = info.get("industry", "Unknown")
        beta = info.get("beta")
        shares_outstanding = info.get("sharesOutstanding")
        current_price = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("previousClose")
        )

        return {
            "ticker": ticker_clean,
            "company_name": company_name,
            "sector": sector,
            "industry": industry,
            "beta": float(beta) if beta is not None else None,
            "shares_outstanding": int(shares_outstanding) if shares_outstanding is not None else None,
            "current_price": float(current_price) if current_price is not None else None,
        }
    except TickerNotFoundError:
        raise
    except Exception as e:
        logger.error("Failed to fetch company profile for %s: %s", ticker_clean, e)
        raise DataExtractionError(f"Error extracting company profile for '{ticker_clean}': {e}") from e


def _extract_statement_records(
    df: Optional[pd.DataFrame],
    statement_type: str,
    ticker: str,
) -> List[Dict[str, Any]]:
    """Convert a yfinance financial statement DataFrame into normalized flat records.

    yfinance statement DataFrames have line items as index and period dates as columns.
    """
    records: List[Dict[str, Any]] = []
    if df is None or df.empty:
        logger.warning("No %s statement available for %s", statement_type, ticker)
        return records

    fetched_at = datetime.utcnow().isoformat()

    # Iterate through periods (columns)
    for period_col in df.columns:
        # Normalize period date string (e.g. '2024-09-28')
        if hasattr(period_col, "strftime"):
            period_str = period_col.strftime("%Y-%m-%d")
        else:
            period_str = str(period_col).split(" ")[0]

        # Iterate through line items (rows)
        for raw_item, val in df[period_col].items():
            if pd.isna(val):
                continue

            canonical_item = _normalize_line_item(str(raw_item))
            if canonical_item:
                records.append({
                    "statement_type": statement_type,
                    "period": period_str,
                    "line_item": canonical_item,
                    "value": float(val),
                    "fetched_at": fetched_at,
                })

    return records


def fetch_financial_statements(ticker: str) -> List[Dict[str, Any]]:
    """Fetch annual financial statements (income, balance, cashflow) for a ticker.

    Args:
        ticker: Stock ticker symbol.

    Returns:
        List of dictionaries with keys: statement_type, period, line_item, value, fetched_at.

    Raises:
        DataExtractionError: If fetching financial statements encounters an unexpected failure.
    """
    ticker_clean = ticker.upper().strip()
    logger.info("Fetching financial statements for %s", ticker_clean)
    try:
        yf_ticker = yf.Ticker(ticker_clean)

        # yfinance properties: financials (income), balance_sheet, cashflow
        income_df = getattr(yf_ticker, "financials", None)
        if income_df is None or income_df.empty:
            income_df = getattr(yf_ticker, "income_stmt", None)

        balance_df = getattr(yf_ticker, "balance_sheet", None)
        cashflow_df = getattr(yf_ticker, "cashflow", None)

        all_records: List[Dict[str, Any]] = []
        all_records.extend(_extract_statement_records(income_df, "income", ticker_clean))
        all_records.extend(_extract_statement_records(balance_df, "balance", ticker_clean))
        all_records.extend(_extract_statement_records(cashflow_df, "cashflow", ticker_clean))

        if not all_records:
            logger.warning("No financial statement records could be extracted for %s", ticker_clean)

        return all_records
    except Exception as e:
        logger.error("Failed to fetch financial statements for %s: %s", ticker_clean, e)
        raise DataExtractionError(f"Error extracting financials for '{ticker_clean}': {e}") from e


def fetch_market_data(
    ticker: str,
    period: str = MARKET_DATA_HISTORY_PERIOD,
    trailing_days: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Fetch historical OHLCV market data for a ticker.

    Args:
        ticker: Stock ticker symbol.
        period: yfinance period string (e.g. '2y', '1mo'). Used if trailing_days is None.
        trailing_days: If provided, fetches only the last N calendar days.

    Returns:
        List of dictionaries with keys: date, open, high, low, close, volume, fetched_at.

    Raises:
        TickerNotFoundError: If no price history is available.
        DataExtractionError: On unexpected extraction failures.
    """
    ticker_clean = ticker.upper().strip()
    logger.info(
        "Fetching market data for %s (period=%s, trailing_days=%s)",
        ticker_clean,
        period,
        trailing_days,
    )
    try:
        yf_ticker = yf.Ticker(ticker_clean)

        if trailing_days is not None and trailing_days > 0:
            end_dt = datetime.utcnow()
            start_dt = end_dt - timedelta(days=trailing_days)
            hist = yf_ticker.history(start=start_dt.strftime("%Y-%m-%d"), end=end_dt.strftime("%Y-%m-%d"))
        else:
            hist = yf_ticker.history(period=period)

        if hist is None or hist.empty:
            raise TickerNotFoundError(f"No market data returned for '{ticker_clean}'.")

        fetched_at = datetime.utcnow().isoformat()
        records: List[Dict[str, Any]] = []

        for idx, row in hist.iterrows():
            # Format index to YYYY-MM-DD
            if hasattr(idx, "strftime"):
                date_str = idx.strftime("%Y-%m-%d")
            else:
                date_str = str(idx).split(" ")[0]

            records.append({
                "date": date_str,
                "open": round(float(row["Open"]), 4) if pd.notna(row.get("Open")) else None,
                "high": round(float(row["High"]), 4) if pd.notna(row.get("High")) else None,
                "low": round(float(row["Low"]), 4) if pd.notna(row.get("Low")) else None,
                "close": round(float(row["Close"]), 4) if pd.notna(row.get("Close")) else None,
                "volume": int(row["Volume"]) if pd.notna(row.get("Volume")) else None,
                "fetched_at": fetched_at,
            })

        return records
    except TickerNotFoundError:
        raise
    except Exception as e:
        logger.error("Failed to fetch market data for %s: %s", ticker_clean, e)
        raise DataExtractionError(f"Error extracting market data for '{ticker_clean}': {e}") from e


def fetch_all_data(
    ticker: str,
    trailing_days: Optional[int] = None,
) -> Dict[str, Any]:
    """Convenience function to fetch profile, financial statements, and market data.

    Args:
        ticker: Stock ticker symbol.
        trailing_days: Optional trailing window for market data. If None, uses default 2y.

    Returns:
        Dict with keys: 'profile', 'financial_statements', 'market_data'.
    """
    ticker_clean = ticker.upper().strip()
    profile = fetch_company_profile(ticker_clean)
    financials = fetch_financial_statements(ticker_clean)
    market = fetch_market_data(ticker_clean, trailing_days=trailing_days)

    return {
        "profile": profile,
        "financial_statements": financials,
        "market_data": market,
    }
