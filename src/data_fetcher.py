"""Data ingestion module for financial statements and market data via yfinance.

Extracts company profiles, normalized multi-year financial statements,
and historical OHLCV data into structured dictionaries.
"""

from datetime import datetime, timedelta, timezone
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


# Map canonical line item identifiers to prioritized raw yfinance line item variations
PREFERRED_LINE_ITEMS: Dict[str, Dict[str, List[str]]] = {
    "income": {
        "total_revenue": ["Total Revenue", "Operating Revenue", "Revenue"],
        "operating_income": ["Operating Income"],
        "operating_expense": ["Operating Expense"],
        "net_income": ["Net Income", "Net Income Common Stockholders"],
        "ebit": ["EBIT"],
        "interest_expense": ["Interest Expense"],
        "tax_provision": ["Tax Provision"],
    },
    "balance": {
        "total_assets": ["Total Assets"],
        "total_liabilities": ["Total Liabilities Net Minority Interest", "Total Liabilities"],
        "cash_and_cash_equivalents": ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"],
        "total_debt": ["Total Debt"],
        "long_term_debt": ["Long Term Debt"],
        "current_debt": ["Current Debt"],
        "stockholders_equity": ["Stockholders Equity", "Common Stock Equity"],
    },
    "cashflow": {
        "operating_cash_flow": ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"],
        "capital_expenditure": ["Capital Expenditure"],
        "free_cash_flow": ["Free Cash Flow"],
        "investing_cash_flow": ["Investing Cash Flow"],
        "financing_cash_flow": ["Financing Cash Flow"],
    },
}

# Anchor line items required for a period to be considered a complete statement column
ANCHOR_LINE_ITEMS = {
    "income": "total_revenue",
    "balance": "total_assets",
    "cashflow": "operating_cash_flow",
}


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

    Applies prioritized line item matching to prevent duplicate line items per period,
    and discards incomplete trailing columns lacking the anchor line item.
    """
    records: List[Dict[str, Any]] = []
    if df is None or df.empty:
        logger.warning("No %s statement available for %s", statement_type, ticker)
        return records

    fetched_at = datetime.now(timezone.utc).isoformat()
    mapping = PREFERRED_LINE_ITEMS.get(statement_type, {})
    anchor_item = ANCHOR_LINE_ITEMS.get(statement_type)

    # Iterate through periods (columns)
    for period_col in df.columns:
        if hasattr(period_col, "strftime"):
            period_str = period_col.strftime("%Y-%m-%d")
        else:
            period_str = str(period_col).split(" ")[0]

        period_values: Dict[str, float] = {}
        for canonical_name, candidate_raw_names in mapping.items():
            for raw_name in candidate_raw_names:
                if raw_name in df.index and pd.notna(df.loc[raw_name, period_col]):
                    period_values[canonical_name] = float(df.loc[raw_name, period_col])
                    break  # Take only the top-priority match for this canonical item

        # Skip incomplete trailing periods that lack the statement anchor item
        if anchor_item and anchor_item not in period_values:
            logger.debug(
                "Skipping incomplete %s period %s for %s (missing %s)",
                statement_type,
                period_str,
                ticker,
                anchor_item,
            )
            continue

        for canonical_name, val in period_values.items():
            records.append({
                "statement_type": statement_type,
                "period": period_str,
                "line_item": canonical_name,
                "value": val,
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
            end_dt = datetime.now(timezone.utc)
            start_dt = end_dt - timedelta(days=trailing_days)
            hist = yf_ticker.history(start=start_dt.strftime("%Y-%m-%d"), end=end_dt.strftime("%Y-%m-%d"))
        else:
            hist = yf_ticker.history(period=period)

        if hist is None or hist.empty:
            raise TickerNotFoundError(f"No market data returned for '{ticker_clean}'.")

        fetched_at = datetime.now(timezone.utc).isoformat()
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
