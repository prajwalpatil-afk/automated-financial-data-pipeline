"""Integration and pipeline tests covering database persistence, freshness,

SQL analytics queries (financial, market, ranking, sector), and report exports.
"""

from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
import pytest

from src.analytics import execute_sql_query, export_report_to_csv, load_query, run_all_analytics
from src.database import (
    get_all_companies,
    get_company,
    get_financials_df,
    get_latest_market_date,
    get_latest_market_price,
    get_market_data_df,
    init_db,
    is_fundamentals_fresh,
    upsert_company,
    upsert_financial_statements,
    upsert_market_data,
    upsert_valuation_result,
)


@pytest.fixture
def populated_db(tmp_path):
    """Create an SQLite database pre-populated with multi-company financial and market fixtures."""
    db_file = tmp_path / "test_pipeline.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    init_db(conn)

    # 1. Upsert Companies
    c1 = upsert_company(conn, {"ticker": "AAPL", "company_name": "Apple Inc.", "sector": "Technology", "industry": "Consumer Electronics"})
    c2 = upsert_company(conn, {"ticker": "MSFT", "company_name": "Microsoft Corp.", "sector": "Technology", "industry": "Software"})
    c3 = upsert_company(conn, {"ticker": "XOM", "company_name": "Exxon Mobil", "sector": "Energy", "industry": "Oil & Gas"})

    # 2. Upsert Multi-Year Financial Statements
    # AAPL (high growth)
    upsert_financial_statements(conn, c1, [
        {"statement_type": "income", "period": "2023-09-30", "line_item": "total_revenue", "value": 380000.0},
        {"statement_type": "income", "period": "2023-09-30", "line_item": "operating_income", "value": 110000.0},
        {"statement_type": "income", "period": "2023-09-30", "line_item": "net_income", "value": 95000.0},
        {"statement_type": "cashflow", "period": "2023-09-30", "line_item": "operating_cash_flow", "value": 110000.0},
        {"statement_type": "cashflow", "period": "2023-09-30", "line_item": "capital_expenditure", "value": -11000.0},
        {"statement_type": "income", "period": "2024-09-30", "line_item": "total_revenue", "value": 456000.0}, # +20% growth
        {"statement_type": "income", "period": "2024-09-30", "line_item": "operating_income", "value": 140000.0},
        {"statement_type": "income", "period": "2024-09-30", "line_item": "net_income", "value": 120000.0},
        {"statement_type": "cashflow", "period": "2024-09-30", "line_item": "operating_cash_flow", "value": 130000.0},
        {"statement_type": "cashflow", "period": "2024-09-30", "line_item": "capital_expenditure", "value": -12000.0},
    ])

    # MSFT (moderate growth)
    upsert_financial_statements(conn, c2, [
        {"statement_type": "income", "period": "2023-06-30", "line_item": "total_revenue", "value": 210000.0},
        {"statement_type": "income", "period": "2023-06-30", "line_item": "operating_income", "value": 88000.0},
        {"statement_type": "income", "period": "2023-06-30", "line_item": "net_income", "value": 72000.0},
        {"statement_type": "cashflow", "period": "2023-06-30", "line_item": "operating_cash_flow", "value": 87000.0},
        {"statement_type": "cashflow", "period": "2023-06-30", "line_item": "capital_expenditure", "value": -28000.0},
        {"statement_type": "income", "period": "2024-06-30", "line_item": "total_revenue", "value": 231000.0}, # +10% growth
        {"statement_type": "income", "period": "2024-06-30", "line_item": "operating_income", "value": 99000.0},
        {"statement_type": "income", "period": "2024-06-30", "line_item": "net_income", "value": 82000.0},
        {"statement_type": "cashflow", "period": "2024-06-30", "line_item": "operating_cash_flow", "value": 98000.0},
        {"statement_type": "cashflow", "period": "2024-06-30", "line_item": "capital_expenditure", "value": -30000.0},
    ])

    # XOM (lower growth)
    upsert_financial_statements(conn, c3, [
        {"statement_type": "income", "period": "2023-12-31", "line_item": "total_revenue", "value": 340000.0},
        {"statement_type": "income", "period": "2023-12-31", "line_item": "operating_income", "value": 55000.0},
        {"statement_type": "income", "period": "2023-12-31", "line_item": "net_income", "value": 36000.0},
        {"statement_type": "cashflow", "period": "2023-12-31", "line_item": "operating_cash_flow", "value": 50000.0},
        {"statement_type": "cashflow", "period": "2023-12-31", "line_item": "capital_expenditure", "value": -19000.0},
        {"statement_type": "income", "period": "2024-12-31", "line_item": "total_revenue", "value": 346800.0}, # +2% growth
        {"statement_type": "income", "period": "2024-12-31", "line_item": "operating_income", "value": 52000.0},
        {"statement_type": "income", "period": "2024-12-31", "line_item": "net_income", "value": 33000.0},
        {"statement_type": "cashflow", "period": "2024-12-31", "line_item": "operating_cash_flow", "value": 48000.0},
        {"statement_type": "cashflow", "period": "2024-12-31", "line_item": "capital_expenditure", "value": -20000.0},
    ])

    # 3. Upsert Monthly Market Data (2 months for returns)
    upsert_market_data(conn, c1, [
        {"date": "2024-01-31", "open": 185.0, "high": 187.0, "low": 184.0, "close": 185.0, "volume": 1000000},
        {"date": "2024-02-29", "open": 185.0, "high": 195.0, "low": 184.0, "close": 194.25, "volume": 1200000}, # +5.0% return
    ])
    upsert_market_data(conn, c2, [
        {"date": "2024-01-31", "open": 400.0, "high": 405.0, "low": 395.0, "close": 400.0, "volume": 800000},
        {"date": "2024-02-29", "open": 400.0, "high": 415.0, "low": 398.0, "close": 408.0, "volume": 900000}, # +2.0% return
    ])
    upsert_market_data(conn, c3, [
        {"date": "2024-01-31", "open": 102.0, "high": 104.0, "low": 100.0, "close": 102.0, "volume": 500000},
        {"date": "2024-02-29", "open": 102.0, "high": 103.0, "low": 98.0, "close": 98.0, "volume": 600000},   # -3.92% return
    ])

    # 4. Upsert Valuation Results
    upsert_valuation_result(conn, c1, {
        "valuation_date": "2024-03-01",
        "wacc": 0.085,
        "terminal_growth": 0.025,
        "enterprise_value": 3200000.0,
        "equity_value": 3150000.0,
        "intrinsic_value": 220.0,
        "current_price": 194.25, # Undervalued (upside +13.3%)
    })
    upsert_valuation_result(conn, c2, {
        "valuation_date": "2024-03-01",
        "wacc": 0.082,
        "terminal_growth": 0.025,
        "enterprise_value": 3100000.0,
        "equity_value": 3050000.0,
        "intrinsic_value": 430.0,
        "current_price": 408.0, # Undervalued (upside +5.4%)
    })
    upsert_valuation_result(conn, c3, {
        "valuation_date": "2024-03-01",
        "wacc": 0.088,
        "terminal_growth": 0.020,
        "enterprise_value": 400000.0,
        "equity_value": 380000.0,
        "intrinsic_value": 90.0,
        "current_price": 98.0, # Overvalued (upside -8.2%)
    })

    yield conn
    conn.close()


# =====================================================================
# Database & Freshness Tests
# =====================================================================
def test_database_idempotency_and_freshness(populated_db):
    # Upserting existing company updates without duplicating
    c1 = upsert_company(populated_db, {"ticker": "AAPL", "company_name": "Apple Inc. Updated"})
    assert get_company(populated_db, "AAPL")["company_name"] == "Apple Inc. Updated"

    # Freshness check
    assert is_fundamentals_fresh(populated_db, "AAPL", max_age_days=7) is True
    assert is_fundamentals_fresh(populated_db, "NONEXISTENT", max_age_days=7) is False

    # Latest market date & price
    assert get_latest_market_date(populated_db, "AAPL") == "2024-02-29"
    assert get_latest_market_price(populated_db, "AAPL") == 194.25


# =====================================================================
# SQL Analytics Tests
# =====================================================================
def test_sql_financial_analysis(populated_db):
    query = load_query("financial_analysis")
    df = execute_sql_query(populated_db, query)
    assert not df.empty
    assert "yoy_revenue_growth_pct" in df.columns
    assert "operating_margin_pct" in df.columns

    # Check AAPL YoY growth in 2024: (456k - 380k) / 380k = +20.0%
    aapl_2024 = df[(df["ticker"] == "AAPL") & (df["period"] == "2024-09-30")]
    assert len(aapl_2024) == 1
    assert aapl_2024["yoy_revenue_growth_pct"].iloc[0] == 20.0


def test_sql_market_analysis_rankings(populated_db):
    query = load_query("market_analysis")
    df = execute_sql_query(populated_db, query)
    assert not df.empty
    assert "overall_rank" in df.columns
    assert "sector_rank" in df.columns

    feb_data = df[df["month"] == "2024-02"]
    assert len(feb_data) == 3

    # AAPL (+5.0%) should be rank 1 overall
    aapl_row = feb_data[feb_data["ticker"] == "AAPL"].iloc[0]
    assert aapl_row["overall_rank"] == 1
    assert aapl_row["sector_rank"] == 1

    # MSFT (+2.0%) should be rank 2 overall and rank 2 in Tech sector
    msft_row = feb_data[feb_data["ticker"] == "MSFT"].iloc[0]
    assert msft_row["overall_rank"] == 2
    assert msft_row["sector_rank"] == 2

    # XOM (-3.92%) should be rank 3 overall, but rank 1 in Energy sector
    xom_row = feb_data[feb_data["ticker"] == "XOM"].iloc[0]
    assert xom_row["overall_rank"] == 3
    assert xom_row["sector_rank"] == 1


def test_sql_ranking_growth_rate_and_screen(populated_db):
    query = load_query("ranking")
    df = execute_sql_query(populated_db, query)
    assert not df.empty
    assert "revenue_growth_rank" in df.columns
    assert "screen_status" in df.columns

    # AAPL (+20%) should be rank 1 in revenue growth rate
    assert df.iloc[0]["ticker"] == "AAPL"
    assert df.iloc[0]["revenue_growth_rank"] == 1

    # MSFT (+10%) should be rank 2 in revenue growth rate
    assert df.iloc[1]["ticker"] == "MSFT"
    assert df.iloc[1]["revenue_growth_rank"] == 2

    # AAPL and MSFT pass the screen (positive growth, margin, trailing return)
    assert df[df["ticker"] == "AAPL"]["screen_status"].iloc[0] == "PASS"
    assert df[df["ticker"] == "MSFT"]["screen_status"].iloc[0] == "PASS"

    # XOM fails screen due to negative trailing return
    assert df[df["ticker"] == "XOM"]["screen_status"].iloc[0] == "FAIL"


def test_sql_sector_analysis(populated_db):
    query = load_query("sector_analysis")
    df = execute_sql_query(populated_db, query)
    assert not df.empty
    assert "upside_pct" in df.columns
    assert "signal" in df.columns
    assert "sector_avg_upside_pct" in df.columns

    aapl = df[df["ticker"] == "AAPL"].iloc[0]
    assert aapl["signal"] == "Undervalued"
    assert aapl["upside_pct"] > 0

    xom = df[df["ticker"] == "XOM"].iloc[0]
    assert xom["signal"] == "Overvalued"
    assert xom["upside_pct"] < 0


def test_run_all_analytics_and_export_csv(populated_db, tmp_path):
    reports_dir = tmp_path / "test_reports"
    results = run_all_analytics(populated_db, reports_dir=reports_dir, export_csv=True)

    assert "financial_analysis" in results
    assert "market_analysis" in results
    assert "ranking" in results
    assert "sector_analysis" in results

    # Verify CSV files are written
    assert (reports_dir / "financial_analysis.csv").exists()
    assert (reports_dir / "market_analysis.csv").exists()
    assert (reports_dir / "ranking.csv").exists()
    assert (reports_dir / "sector_analysis.csv").exists()


# =====================================================================
# Fabricated Pipeline Execution & Failure Handling Tests
# =====================================================================
from unittest.mock import patch
from src.pipeline import PipelineError, run_pipeline


@pytest.fixture
def mock_pipeline_data():
    profile = {
        "ticker": "FABRIC",
        "company_name": "Fabricated Corp",
        "sector": "Technology",
        "industry": "Software",
        "beta": 1.1,
        "shares_outstanding": 1000000,
        "current_price": 100.0,
    }
    financials = []
    for yr in ["2022-12-31", "2023-12-31", "2024-12-31"]:
        financials.extend([
            {"statement_type": "income", "period": yr, "line_item": "total_revenue", "value": 100000.0},
            {"statement_type": "income", "period": yr, "line_item": "operating_income", "value": 20000.0},
            {"statement_type": "income", "period": yr, "line_item": "net_income", "value": 16000.0},
            {"statement_type": "balance", "period": yr, "line_item": "total_assets", "value": 200000.0},
            {"statement_type": "balance", "period": yr, "line_item": "total_liabilities", "value": 80000.0},
            {"statement_type": "balance", "period": yr, "line_item": "cash_and_cash_equivalents", "value": 25000.0},
            {"statement_type": "balance", "period": yr, "line_item": "total_debt", "value": 20000.0},
            {"statement_type": "cashflow", "period": yr, "line_item": "operating_cash_flow", "value": 22000.0},
            {"statement_type": "cashflow", "period": yr, "line_item": "capital_expenditure", "value": -4000.0},
        ])
    market = [
        {"date": "2024-01-02", "open": 98.0, "high": 101.0, "low": 97.0, "close": 100.0, "volume": 50000},
        {"date": "2024-01-03", "open": 100.0, "high": 103.0, "low": 99.0, "close": 102.0, "volume": 60000},
    ]
    return profile, financials, market


def test_pipeline_fabricated_run_and_freshness(tmp_path, mock_pipeline_data):
    profile, financials, market = mock_pipeline_data
    db_file = tmp_path / "fab_pipeline.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    init_db(conn)

    reports_dir = tmp_path / "fab_reports"

    with patch("src.pipeline.fetch_company_profile", return_value=profile), \
         patch("src.pipeline.fetch_financial_statements", return_value=financials), \
         patch("src.pipeline.fetch_market_data", return_value=market):

        # 1. Initial run: should fetch both fundamentals and market data
        metrics1 = run_pipeline("FABRIC", force_refresh=False, conn=conn, reports_dir=reports_dir)
        assert metrics1["status"] == "SUCCESS"
        assert metrics1["fundamentals_fetched"] == len(financials)
        assert metrics1["market_records_fetched"] == len(market)
        assert metrics1["records_inserted"] > 0
        assert metrics1["records_skipped"] == 0
        assert metrics1["valuation"]["intrinsic_value"] > 0

        # 2. Consecutive run: fundamentals are now fresh (< 7 days), so they should be skipped!
        metrics2 = run_pipeline("FABRIC", force_refresh=False, conn=conn, reports_dir=reports_dir)
        assert metrics2["status"] == "SUCCESS"
        assert metrics2["fundamentals_fetched"] == 0
        assert metrics2["records_skipped"] == 1

        # 3. Forced refresh run: should refetch fundamentals despite being fresh
        metrics3 = run_pipeline("FABRIC", force_refresh=True, conn=conn, reports_dir=reports_dir)
        assert metrics3["status"] == "SUCCESS"
        assert metrics3["fundamentals_fetched"] == len(financials)
        assert metrics3["records_skipped"] == 0

    conn.close()


def test_pipeline_failure_handling(tmp_path, mock_pipeline_data):
    profile, financials, market = mock_pipeline_data
    db_file = tmp_path / "fail_pipeline.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    init_db(conn)

    # Provide corrupted financials (missing total_revenue)
    bad_financials = [r for r in financials if r["line_item"] != "total_revenue"]

    with patch("src.pipeline.fetch_company_profile", return_value=profile), \
         patch("src.pipeline.fetch_financial_statements", return_value=bad_financials), \
         patch("src.pipeline.fetch_market_data", return_value=market):

        with pytest.raises(PipelineError) as exc_info:
            run_pipeline("FABRIC", force_refresh=True, conn=conn)

        assert "Data validation failed" in str(exc_info.value)

    conn.close()

