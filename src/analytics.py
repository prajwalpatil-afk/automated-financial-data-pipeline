"""SQL Analytics runner and report export module.

Executes parameterized raw SQL scripts from sql/ against the SQLite database,
returns Pandas DataFrames, and exports tabular CSV reports to reports/.
"""

import logging
from pathlib import Path
import sqlite3
from typing import Dict, Optional
import pandas as pd

from src.config import REPORTS_DIR, SQL_DIR

logger = logging.getLogger(__name__)

SQL_SCRIPTS = {
    "financial_analysis": SQL_DIR / "financial_analysis.sql",
    "market_analysis": SQL_DIR / "market_analysis.sql",
    "ranking": SQL_DIR / "ranking.sql",
    "sector_analysis": SQL_DIR / "sector_analysis.sql",
}


def load_query(script_name: str, sql_dir: Path = SQL_DIR) -> str:
    """Load SQL script contents from file."""
    path = sql_dir / f"{script_name}.sql" if not script_name.endswith(".sql") else sql_dir / script_name
    if not path.exists():
        raise FileNotFoundError(f"SQL file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def execute_sql_query(
    conn: sqlite3.Connection,
    query_sql: str,
    params: Optional[tuple] = None,
) -> pd.DataFrame:
    """Execute raw SQL query and return results as a Pandas DataFrame."""
    try:
        return pd.read_sql_query(query_sql, conn, params=params or ())
    except Exception as e:
        logger.error("Failed to execute SQL query: %s", e)
        raise


def export_report_to_csv(
    df: pd.DataFrame,
    report_name: str,
    reports_dir: Path = REPORTS_DIR,
) -> Path:
    """Export DataFrame to CSV file in the reports directory."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{report_name}.csv" if not report_name.endswith(".csv") else report_name
    out_path = reports_dir / filename
    df.to_csv(out_path, index=False)
    logger.info("Exported report to %s (%d rows)", out_path, len(df))
    return out_path


def run_all_analytics(
    conn: sqlite3.Connection,
    reports_dir: Path = REPORTS_DIR,
    export_csv: bool = True,
) -> Dict[str, pd.DataFrame]:
    """Execute all four SQL analytics scripts and optionally export CSV reports.

    Returns:
        Dict mapping report names ('financial_analysis', 'market_analysis',
        'ranking', 'sector_analysis') to resulting DataFrames.
    """
    results: Dict[str, pd.DataFrame] = {}

    for report_name, script_path in SQL_SCRIPTS.items():
        logger.info("Running SQL analysis: %s", report_name)
        query = load_query(report_name, sql_dir=script_path.parent)
        df = execute_sql_query(conn, query)
        results[report_name] = df

        if export_csv:
            export_report_to_csv(df, report_name, reports_dir=reports_dir)

    return results
