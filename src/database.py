"""SQLite database persistence layer.

Implements raw sqlite3 schema management, idempotent upserts,
dataset-specific freshness checks, and analytical query helpers.
"""

from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional
import pandas as pd

from src.config import DB_PATH, FUNDAMENTALS_FRESHNESS_DAYS

logger = logging.getLogger(__name__)


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Create and return a SQLite connection configured with WAL and foreign keys."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def init_db(conn: Optional[sqlite3.Connection] = None, db_path: Path = DB_PATH) -> None:
    """Initialize database tables and indexes adhering to Section 4 of the execution plan."""
    should_close = False
    if conn is None:
        conn = get_connection(db_path)
        should_close = True

    try:
        with conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS companies (
                company_id   INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker       TEXT UNIQUE NOT NULL,
                company_name TEXT,
                sector       TEXT,
                industry     TEXT
            );

            CREATE TABLE IF NOT EXISTS financial_statements (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id     INTEGER NOT NULL REFERENCES companies(company_id) ON DELETE CASCADE,
                statement_type TEXT NOT NULL,     -- 'income', 'balance', 'cashflow'
                period         TEXT NOT NULL,     -- e.g. '2024-09-30'
                line_item      TEXT NOT NULL,     -- e.g. 'total_revenue', 'net_income'
                value          REAL,
                fetched_at     TEXT NOT NULL,
                UNIQUE(company_id, statement_type, period, line_item)
            );

            CREATE TABLE IF NOT EXISTS market_data (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id  INTEGER NOT NULL REFERENCES companies(company_id) ON DELETE CASCADE,
                date        TEXT NOT NULL,        -- 'YYYY-MM-DD'
                open        REAL,
                high        REAL,
                low         REAL,
                close       REAL,
                volume      INTEGER,
                fetched_at  TEXT NOT NULL,
                UNIQUE(company_id, date)
            );

            CREATE TABLE IF NOT EXISTS valuation_results (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id       INTEGER NOT NULL REFERENCES companies(company_id) ON DELETE CASCADE,
                valuation_date   TEXT NOT NULL,   -- 'YYYY-MM-DD'
                wacc             REAL,
                terminal_growth  REAL,
                enterprise_value REAL,
                equity_value     REAL,
                intrinsic_value  REAL,
                current_price    REAL,
                UNIQUE(company_id, valuation_date)
            );

            CREATE INDEX IF NOT EXISTS idx_fs_company_period
                ON financial_statements(company_id, period);

            CREATE INDEX IF NOT EXISTS idx_market_company_date
                ON market_data(company_id, date);

            CREATE INDEX IF NOT EXISTS idx_valuation_company_date
                ON valuation_results(company_id, valuation_date);
            """)
        logger.info("Database initialized successfully at %s", db_path)
    finally:
        if should_close:
            conn.close()


# =====================================================================
# Idempotent Upsert Operations
# =====================================================================
def upsert_company(conn: sqlite3.Connection, profile: Dict[str, Any]) -> int:
    """Insert or update company metadata, returning the company_id."""
    ticker = profile["ticker"].upper().strip()
    company_name = profile.get("company_name")
    sector = profile.get("sector")
    industry = profile.get("industry")

    sql = """
    INSERT INTO companies (ticker, company_name, sector, industry)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(ticker) DO UPDATE SET
        company_name = excluded.company_name,
        sector = excluded.sector,
        industry = excluded.industry
    RETURNING company_id;
    """
    with conn:
        cursor = conn.execute(sql, (ticker, company_name, sector, industry))
        row = cursor.fetchone()
        if row:
            return row[0]

        # Fallback if RETURNING is not supported
        cur = conn.execute("SELECT company_id FROM companies WHERE ticker = ?", (ticker,))
        return cur.fetchone()[0]


def upsert_financial_statements(
    conn: sqlite3.Connection,
    company_id: int,
    records: List[Dict[str, Any]],
) -> int:
    """Idempotently insert or update financial statement records.

    Returns the count of processed records.
    """
    if not records:
        return 0

    sql = """
    INSERT INTO financial_statements (
        company_id, statement_type, period, line_item, value, fetched_at
    ) VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(company_id, statement_type, period, line_item) DO UPDATE SET
        value = excluded.value,
        fetched_at = excluded.fetched_at;
    """
    payload = [
        (
            company_id,
            r["statement_type"],
            r["period"],
            r["line_item"],
            r.get("value"),
            r.get("fetched_at", datetime.now(timezone.utc).isoformat()),
        )
        for r in records
    ]

    with conn:
        conn.executemany(sql, payload)

    return len(payload)


def upsert_market_data(
    conn: sqlite3.Connection,
    company_id: int,
    records: List[Dict[str, Any]],
) -> int:
    """Idempotently insert or update OHLCV market data records.

    Returns the count of processed records.
    """
    if not records:
        return 0

    sql = """
    INSERT INTO market_data (
        company_id, date, open, high, low, close, volume, fetched_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(company_id, date) DO UPDATE SET
        open = excluded.open,
        high = excluded.high,
        low = excluded.low,
        close = excluded.close,
        volume = excluded.volume,
        fetched_at = excluded.fetched_at;
    """
    payload = [
        (
            company_id,
            r["date"],
            r.get("open"),
            r.get("high"),
            r.get("low"),
            r.get("close"),
            r.get("volume"),
            r.get("fetched_at", datetime.now(timezone.utc).isoformat()),
        )
        for r in records
    ]

    with conn:
        conn.executemany(sql, payload)

    return len(payload)


def upsert_valuation_result(
    conn: sqlite3.Connection,
    company_id: int,
    result: Dict[str, Any],
) -> int:
    """Idempotently insert or update DCF valuation output for a company and date."""
    sql = """
    INSERT INTO valuation_results (
        company_id, valuation_date, wacc, terminal_growth,
        enterprise_value, equity_value, intrinsic_value, current_price
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(company_id, valuation_date) DO UPDATE SET
        wacc = excluded.wacc,
        terminal_growth = excluded.terminal_growth,
        enterprise_value = excluded.enterprise_value,
        equity_value = excluded.equity_value,
        intrinsic_value = excluded.intrinsic_value,
        current_price = excluded.current_price;
    """
    params = (
        company_id,
        result["valuation_date"],
        result.get("wacc"),
        result.get("terminal_growth"),
        result.get("enterprise_value"),
        result.get("equity_value"),
        result.get("intrinsic_value"),
        result.get("current_price"),
    )
    with conn:
        conn.execute(sql, params)

    return 1


# =====================================================================
# Dataset-Specific Freshness Checks
# =====================================================================
def is_fundamentals_fresh(
    conn: sqlite3.Connection,
    ticker: str,
    max_age_days: int = FUNDAMENTALS_FRESHNESS_DAYS,
) -> bool:
    """Check if financial statements for a ticker were refreshed within max_age_days."""
    sql = """
    SELECT MAX(fs.fetched_at)
    FROM financial_statements fs
    JOIN companies c ON c.company_id = fs.company_id
    WHERE c.ticker = ?;
    """
    cursor = conn.execute(sql, (ticker.upper().strip(),))
    row = cursor.fetchone()
    if not row or not row[0]:
        return False

    try:
        latest_fetch = datetime.fromisoformat(row[0])
        # Ensure timezone-aware comparison if ISO string contains timezone, else compare timestamps
        if latest_fetch.tzinfo is not None:
            now_dt = datetime.now(timezone.utc)
        else:
            now_dt = datetime.utcnow()
        age = now_dt - latest_fetch
        return age.total_seconds() < (max_age_days * 86400)
    except (ValueError, TypeError):
        return False


def get_latest_market_date(conn: sqlite3.Connection, ticker: str) -> Optional[str]:
    """Retrieve the most recent market date (YYYY-MM-DD) stored for a ticker."""
    sql = """
    SELECT MAX(m.date)
    FROM market_data m
    JOIN companies c ON c.company_id = m.company_id
    WHERE c.ticker = ?;
    """
    cursor = conn.execute(sql, (ticker.upper().strip(),))
    row = cursor.fetchone()
    return row[0] if row and row[0] else None


# =====================================================================
# Query & Retrieval Helpers
# =====================================================================
def get_company_id(conn: sqlite3.Connection, ticker: str) -> Optional[int]:
    """Retrieve the company_id for a ticker."""
    sql = "SELECT company_id FROM companies WHERE ticker = ?;"
    cursor = conn.execute(sql, (ticker.upper().strip(),))
    row = cursor.fetchone()
    return row[0] if row else None


def get_company(conn: sqlite3.Connection, ticker: str) -> Optional[Dict[str, Any]]:
    """Retrieve full company profile dictionary by ticker."""
    sql = "SELECT * FROM companies WHERE ticker = ?;"
    cursor = conn.execute(sql, (ticker.upper().strip(),))
    row = cursor.fetchone()
    return dict(row) if row else None


def get_all_companies(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Retrieve all companies tracked in the database."""
    sql = "SELECT * FROM companies ORDER BY ticker;"
    cursor = conn.execute(sql)
    return [dict(r) for r in cursor.fetchall()]


def get_financials_df(conn: sqlite3.Connection, ticker: str) -> pd.DataFrame:
    """Retrieve financial statements as a pivoted DataFrame with periods as index and line items as columns."""
    sql = """
    SELECT fs.period, fs.statement_type, fs.line_item, fs.value
    FROM financial_statements fs
    JOIN companies c ON c.company_id = fs.company_id
    WHERE c.ticker = ?
    ORDER BY fs.period ASC;
    """
    df = pd.read_sql_query(sql, conn, params=(ticker.upper().strip(),))
    if df.empty:
        return pd.DataFrame()

    # Pivot: Index = period, Columns = line_item, Values = value
    pivot_df = df.pivot_table(index="period", columns="line_item", values="value", aggfunc="first")
    pivot_df.sort_index(inplace=True)
    return pivot_df


def get_market_data_df(
    conn: sqlite3.Connection,
    ticker: str,
    start_date: Optional[str] = None,
) -> pd.DataFrame:
    """Retrieve chronologically ordered OHLCV data as a DataFrame."""
    params = [ticker.upper().strip()]
    sql = """
    SELECT m.date, m.open, m.high, m.low, m.close, m.volume
    FROM market_data m
    JOIN companies c ON c.company_id = m.company_id
    WHERE c.ticker = ?
    """
    if start_date:
        sql += " AND m.date >= ?"
        params.append(start_date)

    sql += " ORDER BY m.date ASC;"
    df = pd.read_sql_query(sql, conn, params=params)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)
    return df


def get_latest_market_price(conn: sqlite3.Connection, ticker: str) -> Optional[float]:
    """Retrieve the latest stored closing price for a ticker."""
    sql = """
    SELECT m.close
    FROM market_data m
    JOIN companies c ON c.company_id = m.company_id
    WHERE c.ticker = ?
    ORDER BY m.date DESC
    LIMIT 1;
    """
    cursor = conn.execute(sql, (ticker.upper().strip(),))
    row = cursor.fetchone()
    return float(row[0]) if row and row[0] is not None else None


def get_latest_valuation_result(conn: sqlite3.Connection, ticker: str) -> Optional[Dict[str, Any]]:
    """Retrieve the most recent valuation record for a ticker."""
    sql = """
    SELECT v.*
    FROM valuation_results v
    JOIN companies c ON c.company_id = v.company_id
    WHERE c.ticker = ?
    ORDER BY v.valuation_date DESC
    LIMIT 1;
    """
    cursor = conn.execute(sql, (ticker.upper().strip(),))
    row = cursor.fetchone()
    return dict(row) if row else None
