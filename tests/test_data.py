"""Unit tests for data extraction and data quality validation."""

from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from src.data_fetcher import (
    DataExtractionError,
    TickerNotFoundError,
    fetch_all_data,
    fetch_company_profile,
    fetch_financial_statements,
    fetch_market_data,
)
from src.data_validator import (
    ValidationReport,
    validate_all,
    validate_fundamentals,
    validate_market_data,
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

    # 3 periods for financial statements
    dates = [pd.Timestamp("2024-09-30"), pd.Timestamp("2023-09-30"), pd.Timestamp("2022-09-30")]
    income_df = pd.DataFrame(
        {
            dates[0]: [1000.0, 250.0, 200.0],
            dates[1]: [900.0, 220.0, 180.0],
            dates[2]: [800.0, 190.0, 150.0],
        },
        index=["Total Revenue", "Operating Income", "Net Income"],
    )
    ticker_mock.financials = income_df

    balance_df = pd.DataFrame(
        {
            dates[0]: [5000.0, 2000.0, 800.0, 1200.0],
            dates[1]: [4500.0, 1800.0, 700.0, 1100.0],
            dates[2]: [4000.0, 1600.0, 600.0, 1000.0],
        },
        index=["Total Assets", "Total Liabilities", "Cash And Cash Equivalents", "Total Debt"],
    )
    ticker_mock.balance_sheet = balance_df

    cf_df = pd.DataFrame(
        {
            dates[0]: [300.0, -50.0],
            dates[1]: [270.0, -45.0],
            dates[2]: [240.0, -40.0],
        },
        index=["Operating Cash Flow", "Capital Expenditure"],
    )
    ticker_mock.cashflow = cf_df

    hist_dates = pd.date_range(start="2024-01-01", periods=5, freq="B")  # business days
    hist_df = pd.DataFrame(
        {
            "Open": [100.0, 102.0, 101.0, 103.0, 104.0],
            "High": [105.0, 106.0, 104.0, 107.0, 108.0],
            "Low": [99.0, 101.0, 100.0, 102.0, 103.0],
            "Close": [104.0, 103.0, 102.5, 106.0, 107.0],
            "Volume": [100000, 120000, 95000, 110000, 115000],
        },
        index=hist_dates,
    )
    ticker_mock.history.return_value = hist_df

    return ticker_mock


@pytest.fixture
def valid_fundamentals():
    """Returns valid 3-year financial records."""
    records = []
    periods = ["2022-12-31", "2023-12-31", "2024-12-31"]
    for p in periods:
        records.extend([
            {"statement_type": "income", "period": p, "line_item": "total_revenue", "value": 1000.0},
            {"statement_type": "income", "period": p, "line_item": "operating_income", "value": 250.0},
            {"statement_type": "income", "period": p, "line_item": "net_income", "value": 200.0},
            {"statement_type": "balance", "period": p, "line_item": "total_assets", "value": 4000.0},
            {"statement_type": "balance", "period": p, "line_item": "total_liabilities", "value": 1500.0},
            {"statement_type": "balance", "period": p, "line_item": "cash_and_cash_equivalents", "value": 600.0},
            {"statement_type": "balance", "period": p, "line_item": "total_debt", "value": 900.0},
            {"statement_type": "cashflow", "period": p, "line_item": "operating_cash_flow", "value": 300.0},
            {"statement_type": "cashflow", "period": p, "line_item": "capital_expenditure", "value": -50.0},
        ])
    return records


@pytest.fixture
def valid_market_records():
    """Returns valid OHLCV records."""
    return [
        {"date": "2024-01-02", "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0, "volume": 10000},
        {"date": "2024-01-03", "open": 104.0, "high": 107.0, "low": 103.0, "close": 106.0, "volume": 12000},
        {"date": "2024-01-04", "open": 106.0, "high": 108.0, "low": 105.0, "close": 107.5, "volume": 11000},
    ]


# =====================================================================
# Ingestion Tests
# =====================================================================
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


def test_fetch_market_data_success(mock_yf_ticker):
    with patch("yfinance.Ticker", return_value=mock_yf_ticker):
        records = fetch_market_data("TEST", period="1mo")
        assert len(records) == 5
        assert records[0]["open"] == 100.0
        assert records[0]["close"] == 104.0


# =====================================================================
# Validation Tests
# =====================================================================
def test_validation_all_success(valid_fundamentals, valid_market_records):
    report = validate_all(valid_fundamentals, valid_market_records)
    assert report.is_valid is True
    assert report.income_status == "PASS"
    assert report.balance_status == "PASS"
    assert report.cashflow_status == "PASS"
    assert report.market_status == "PASS"
    assert report.missing_required_fields == 0
    assert report.duplicate_periods == 0
    assert report.duplicate_dates == 0
    assert report.invalid_ohlc_rows == 0
    assert "Status: PASS" in report.summary_text()


def test_validation_missing_required_line_item(valid_fundamentals):
    # Remove total_revenue from 2024-12-31
    bad_fundamentals = [
        r for r in valid_fundamentals
        if not (r["period"] == "2024-12-31" and r["line_item"] == "total_revenue")
    ]
    report = validate_fundamentals(bad_fundamentals)
    assert report.is_valid is False
    assert report.income_status == "FAIL"
    assert report.missing_required_fields >= 1


def test_validation_invalid_ohlc_logic(valid_market_records):
    # Set high < low
    corrupt_market = list(valid_market_records)
    corrupt_market.append({
        "date": "2024-01-05",
        "open": 100.0,
        "high": 90.0,  # invalid: High < Low
        "low": 95.0,
        "close": 92.0,
        "volume": 5000,
    })
    report = validate_market_data(corrupt_market)
    assert report.is_valid is False
    assert report.market_status == "FAIL"
    assert report.invalid_ohlc_rows >= 1


def test_validation_duplicate_dates(valid_market_records):
    corrupt_market = list(valid_market_records)
    corrupt_market.append(valid_market_records[0])  # Duplicate date
    report = validate_market_data(corrupt_market)
    assert report.is_valid is False
    assert report.duplicate_dates == 1


def test_validation_market_gap_warning():
    # Gap of 8 days between trading sessions
    market_with_gap = [
        {"date": "2024-01-01", "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0, "volume": 1000},
        {"date": "2024-01-10", "open": 104.0, "high": 108.0, "low": 103.0, "close": 107.0, "volume": 1200},
    ]
    report = validate_market_data(market_with_gap)
    # Gap should emit a warning but not fail validation
    assert report.is_valid is True
    assert report.gap_warnings == 1
