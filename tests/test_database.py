"""Unit tests for SQLite database schema, upserts, freshness, and query helpers."""

from datetime import datetime, timedelta
import sqlite3
import pytest

from src.database import (
    get_all_companies,
    get_company,
    get_company_id,
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
def in_memory_db():
    """Create an in-memory SQLite database connection with schema initialized."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    init_db(conn)
    yield conn
    conn.close()


def test_schema_creation(in_memory_db):
    """Verify all 4 tables and indexes exist."""
    cursor = in_memory_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
    )
    tables = {row[0] for row in cursor.fetchall()}
    assert "companies" in tables
    assert "financial_statements" in tables
    assert "market_data" in tables
    assert "valuation_results" in tables

    cursor = in_memory_db.execute(
        "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name;"
    )
    indexes = {row[0] for row in cursor.fetchall()}
    assert "idx_fs_company_period" in indexes
    assert "idx_market_company_date" in indexes
    assert "idx_valuation_company_date" in indexes


def test_upsert_company_idempotency(in_memory_db):
    """Upserting company profile should create and subsequent upsert should update."""
    cid1 = upsert_company(
        in_memory_db,
        {"ticker": "AAPL", "company_name": "Apple Inc.", "sector": "Tech", "industry": "Consumer Elec"},
    )
    assert cid1 > 0

    # Upsert again with changed name
    cid2 = upsert_company(
        in_memory_db,
        {"ticker": "AAPL", "company_name": "Apple Inc. Updated", "sector": "Tech", "industry": "Consumer Elec"},
    )
    assert cid1 == cid2

    company = get_company(in_memory_db, "AAPL")
    assert company["company_name"] == "Apple Inc. Updated"

    all_comps = get_all_companies(in_memory_db)
    assert len(all_comps) == 1


def test_foreign_key_enforcement(in_memory_db):
    """Inserting into child table with invalid company_id should raise IntegrityError."""
    with pytest.raises(sqlite3.IntegrityError):
        upsert_market_data(
            in_memory_db,
            company_id=9999,  # Non-existent
            records=[{"date": "2024-01-01", "open": 100, "high": 105, "low": 99, "close": 104, "volume": 1000}],
        )


def test_upsert_financial_statements_and_pivot(in_memory_db):
    cid = upsert_company(in_memory_db, {"ticker": "MSFT", "company_name": "Microsoft"})
    records = [
        {"statement_type": "income", "period": "2023-12-31", "line_item": "total_revenue", "value": 200000},
        {"statement_type": "income", "period": "2023-12-31", "line_item": "net_income", "value": 70000},
        {"statement_type": "income", "period": "2024-12-31", "line_item": "total_revenue", "value": 240000},
        {"statement_type": "income", "period": "2024-12-31", "line_item": "net_income", "value": 85000},
    ]

    count1 = upsert_financial_statements(in_memory_db, cid, records)
    assert count1 == 4

    # Re-run upsert with an updated value
    records[3]["value"] = 88000
    count2 = upsert_financial_statements(in_memory_db, cid, records)
    assert count2 == 4

    # Total rows in table should still be 4
    cur = in_memory_db.execute("SELECT COUNT(*) FROM financial_statements WHERE company_id = ?", (cid,))
    assert cur.fetchone()[0] == 4

    # Test DataFrame retrieval and pivot
    df = get_financials_df(in_memory_db, "MSFT")
    assert len(df) == 2  # 2 periods
    assert "total_revenue" in df.columns
    assert "net_income" in df.columns
    assert df.loc["2024-12-31", "net_income"] == 88000


def test_upsert_market_data_and_price_retrieval(in_memory_db):
    cid = upsert_company(in_memory_db, {"ticker": "NVDA", "company_name": "Nvidia"})
    records = [
        {"date": "2024-01-02", "open": 480, "high": 490, "low": 475, "close": 485, "volume": 500000},
        {"date": "2024-01-03", "open": 485, "high": 495, "low": 482, "close": 492, "volume": 600000},
    ]
    upsert_market_data(in_memory_db, cid, records)

    latest_date = get_latest_market_date(in_memory_db, "NVDA")
    assert latest_date == "2024-01-03"

    latest_price = get_latest_market_price(in_memory_db, "NVDA")
    assert latest_price == 492.0

    df = get_market_data_df(in_memory_db, "NVDA")
    assert len(df) == 2
    assert "close" in df.columns


def test_freshness_logic(in_memory_db):
    cid = upsert_company(in_memory_db, {"ticker": "TEST", "company_name": "Test"})

    # Initially not fresh
    assert is_fundamentals_fresh(in_memory_db, "TEST", max_age_days=7) is False

    # Insert record fetched today
    today_iso = datetime.utcnow().isoformat()
    upsert_financial_statements(
        in_memory_db,
        cid,
        [{"statement_type": "income", "period": "2024-01-01", "line_item": "revenue", "value": 100, "fetched_at": today_iso}],
    )
    assert is_fundamentals_fresh(in_memory_db, "TEST", max_age_days=7) is True

    # Insert stale record (10 days ago)
    stale_iso = (datetime.utcnow() - timedelta(days=10)).isoformat()
    upsert_financial_statements(
        in_memory_db,
        cid,
        [{"statement_type": "income", "period": "2024-01-01", "line_item": "revenue", "value": 100, "fetched_at": stale_iso}],
    )
    assert is_fundamentals_fresh(in_memory_db, "TEST", max_age_days=7) is False


def test_upsert_valuation_result(in_memory_db):
    cid = upsert_company(in_memory_db, {"ticker": "AAPL", "company_name": "Apple"})
    val_record = {
        "valuation_date": "2024-06-01",
        "wacc": 0.085,
        "terminal_growth": 0.025,
        "enterprise_value": 3000000.0,
        "equity_value": 2900000.0,
        "intrinsic_value": 195.50,
        "current_price": 180.00,
    }
    upsert_valuation_result(in_memory_db, cid, val_record)

    cur = in_memory_db.execute("SELECT * FROM valuation_results WHERE company_id = ?", (cid,))
    row = dict(cur.fetchone())
    assert row["intrinsic_value"] == 195.50
    assert row["current_price"] == 180.00
