"""Unit tests for data extraction and data fetching (mocked yfinance)."""

from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from src.data_fetcher import (
    DataExtractionError,
    TickerNotFoundError,
    fetch_company_profile,
    fetch_financial_statements,
    fetch_market_data,
    fetch_all_data,
)


@pytest.fixture
def mock_yf_ticker():
    """Fixture providing a mock yfinance Ticker with sample data."""
    ticker_mock = MagicMock()
    ticker_mock.info = {
        "symbol": "TEST",
        "longName": "Test Corporation",
        "sector": "Technology",
        "industry": "Software",
        "beta": 1.25,
        "sharesOutstanding": 1000000,
        "currentPrice": 150.50,
    }

    # Sample income statement DataFrame
    dates = [pd.Timestamp("2024-09-30"), pd.Timestamp("2023-09-30")]
    income_df = pd.DataFrame(
        {
            dates[0]: [1000.0, 250.0, 200.0],
            dates[1]: [900.0, 220.0, 180.0],
        },
        index=["Total Revenue", "Operating Income", "Net Income"],
    )
    ticker_mock.financials = income_df

    # Sample balance sheet DataFrame
    balance_df = pd.DataFrame(
        {
            dates[0]: [5000.0, 2000.0, 800.0, 1200.0],
            dates[1]: [4500.0, 1800.0, 700.0, 1100.0],
        },
        index=["Total Assets", "Total Liabilities", "Cash And Cash Equivalents", "Total Debt"],
    )
    ticker_mock.balance_sheet = balance_df

    # Sample cash flow DataFrame
    cf_df = pd.DataFrame(
        {
            dates[0]: [300.0, -50.0],
            dates[1]: [270.0, -45.0],
        },
        index=["Operating Cash Flow", "Capital Expenditure"],
    )
    ticker_mock.cashflow = cf_df

    # Sample historical OHLCV DataFrame
    hist_dates = pd.date_range(start="2024-01-01", periods=3, freq="D")
    hist_df = pd.DataFrame(
        {
            "Open": [100.0, 102.0, 101.0],
            "High": [105.0, 106.0, 104.0],
            "Low": [99.0, 101.0, 100.0],
            "Close": [104.0, 103.0, 102.5],
            "Volume": [100000, 120000, 95000],
        },
        index=hist_dates,
    )
    ticker_mock.history.return_value = hist_df

    return ticker_mock


def test_fetch_company_profile_success(mock_yf_ticker):
    with patch("yfinance.Ticker", return_value=mock_yf_ticker):
        profile = fetch_company_profile("TEST")
        assert profile["ticker"] == "TEST"
        assert profile["company_name"] == "Test Corporation"
        assert profile["sector"] == "Technology"
        assert profile["beta"] == 1.25
        assert profile["current_price"] == 150.50


def test_fetch_company_profile_not_found():
    empty_mock = MagicMock()
    empty_mock.info = {}
    empty_mock.fast_info = None

    with patch("yfinance.Ticker", return_value=empty_mock):
        with pytest.raises(TickerNotFoundError):
            fetch_company_profile("INVALID")


def test_fetch_financial_statements_success(mock_yf_ticker):
    with patch("yfinance.Ticker", return_value=mock_yf_ticker):
        statements = fetch_financial_statements("TEST")
        assert len(statements) > 0
        line_items = {s["line_item"] for s in statements}
        assert "total_revenue" in line_items
        assert "total_assets" in line_items
        assert "operating_cash_flow" in line_items

        rev_record = next(
            s for s in statements if s["line_item"] == "total_revenue" and s["period"] == "2024-09-30"
        )
        assert rev_record["value"] == 1000.0
        assert rev_record["statement_type"] == "income"


def test_fetch_market_data_success(mock_yf_ticker):
    with patch("yfinance.Ticker", return_value=mock_yf_ticker):
        records = fetch_market_data("TEST", period="1mo")
        assert len(records) == 3
        assert records[0]["date"] == "2024-01-01"
        assert records[0]["open"] == 100.0
        assert records[0]["close"] == 104.0
        assert records[0]["volume"] == 100000


def test_fetch_all_data(mock_yf_ticker):
    with patch("yfinance.Ticker", return_value=mock_yf_ticker):
        payload = fetch_all_data("TEST")
        assert "profile" in payload
        assert "financial_statements" in payload
        assert "market_data" in payload
        assert payload["profile"]["ticker"] == "TEST"
