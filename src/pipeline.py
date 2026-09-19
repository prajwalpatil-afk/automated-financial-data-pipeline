"""Automated pipeline orchestrator for financial data extraction, validation,

loading, valuation modeling, and analytical reporting.
"""

from datetime import datetime, timezone
import logging
from pathlib import Path
import time
from typing import Any, Dict, Optional
import sqlite3

from src.analytics import run_all_analytics
from src.config import (
    DEFAULT_RISK_FREE_RATE,
    DEFAULT_TERMINAL_GROWTH_RATE,
    FUNDAMENTALS_FRESHNESS_DAYS,
    LOG_FILE,
    MARKET_DATA_HISTORY_PERIOD,
    MARKET_DATA_TRAILING_DAYS,
    REPORTS_DIR,
)
from src.data_fetcher import (
    fetch_company_profile,
    fetch_financial_statements,
    fetch_market_data,
)
from src.data_validator import (
    ValidationReport,
    validate_fundamentals,
    validate_market_data,
)
from src.database import (
    get_connection,
    get_financials_df,
    get_latest_market_date,
    get_market_data_df,
    init_db,
    is_fundamentals_fresh,
    upsert_company,
    upsert_financial_statements,
    upsert_market_data,
    upsert_valuation_result,
)
from src.financial_analysis import analyze_financials
from src.market_analysis import analyze_market_data
from src.valuation import (
    calculate_dcf,
    compute_cost_of_debt,
    compute_cost_of_equity,
    compute_wacc,
    evaluate_valuation,
    run_scenarios,
)

# Configure logger
logger = logging.getLogger("pipeline")


def setup_pipeline_logging(log_file: Path = LOG_FILE) -> None:
    """Set up standard library logging to console and pipeline.log."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
        file_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

        stream_handler = logging.StreamHandler()
        stream_formatter = logging.Formatter("[%(levelname)s] %(message)s")
        stream_handler.setFormatter(stream_formatter)
        logger.addHandler(stream_handler)


class PipelineError(Exception):
    """Raised when a fatal error terminates pipeline execution for a ticker."""
    pass


def run_pipeline(
    ticker: str,
    force_refresh: bool = False,
    conn: Optional[sqlite3.Connection] = None,
    reports_dir: Path = REPORTS_DIR,
) -> Dict[str, Any]:
    """Execute the end-to-end data pipeline for a given stock ticker.

    Flow: Extract -> Validate -> Load -> Transform -> Value -> Analyze & Export

    Args:
        ticker: Uppercase ticker symbol (e.g. 'AAPL').
        force_refresh: If True, refetches fundamentals even if fresh.
        conn: Optional active SQLite connection (creates one if None).
        reports_dir: Destination directory for CSV analytics.

    Returns:
        Dict containing execution metrics, record counts, and valuation summary.
    """
    setup_pipeline_logging()
    start_time = time.time()
    ticker_clean = ticker.upper().strip()
    logger.info("========== Starting Pipeline Run for %s ==========", ticker_clean)

    should_close_conn = False
    if conn is None:
        conn = get_connection()
        should_close_conn = True

    init_db(conn)

    metrics: Dict[str, Any] = {
        "ticker": ticker_clean,
        "status": "SUCCESS",
        "fundamentals_fetched": 0,
        "market_records_fetched": 0,
        "records_inserted": 0,
        "records_skipped": 0,
        "execution_time_seconds": 0.0,
        "valuation": {},
        "error": None,
    }

    try:
        # 1. Freshness Check
        fundamentals_fresh = is_fundamentals_fresh(conn, ticker_clean, max_age_days=FUNDAMENTALS_FRESHNESS_DAYS)
        need_fundamentals = force_refresh or (not fundamentals_fresh)
        latest_market_dt = get_latest_market_date(conn, ticker_clean)

        logger.info(
            "Freshness Status for %s: Fundamentals Fresh=%s (Force=%s), Latest Market Date=%s",
            ticker_clean,
            fundamentals_fresh,
            force_refresh,
            latest_market_dt,
        )

        profile = None
        financial_records = []
        market_records = []

        # 2. Extract Phase
        if need_fundamentals:
            logger.info("Extracting company profile and financial statements for %s...", ticker_clean)
            profile = fetch_company_profile(ticker_clean)
            financial_records = fetch_financial_statements(ticker_clean)
            metrics["fundamentals_fetched"] = len(financial_records)
        else:
            logger.info("Fundamentals are fresh (<%d days). Skipping statement extract.", FUNDAMENTALS_FRESHNESS_DAYS)
            metrics["records_skipped"] += 1
            profile = fetch_company_profile(ticker_clean)

        if latest_market_dt is None:
            logger.info("No prior market data found. Fetching full %s history...", MARKET_DATA_HISTORY_PERIOD)
            market_records = fetch_market_data(ticker_clean, period=MARKET_DATA_HISTORY_PERIOD)
        else:
            logger.info("Prior market data found. Fetching trailing %d days for upsert...", MARKET_DATA_TRAILING_DAYS)
            market_records = fetch_market_data(ticker_clean, trailing_days=MARKET_DATA_TRAILING_DAYS)

        metrics["market_records_fetched"] = len(market_records)

        # 3. Validate Phase
        val_report = ValidationReport()
        if need_fundamentals:
            val_report = validate_fundamentals(financial_records, val_report)
        if market_records:
            val_report = validate_market_data(market_records, val_report)

        logger.info("\n%s", val_report.summary_text())

        if not val_report.is_valid:
            error_details = "; ".join(val_report.errors[:5])
            raise PipelineError(f"Data validation failed for {ticker_clean}: {error_details}")

        # 4. Load Phase (Idempotent Upsert)
        if profile is not None:
            company_id = upsert_company(conn, profile)
        else:
            # Look up existing company_id
            cursor = conn.execute("SELECT company_id FROM companies WHERE ticker = ?", (ticker_clean,))
            row = cursor.fetchone()
            if not row:
                # If profile wasn't fetched yet company not in DB, fetch profile
                profile = fetch_company_profile(ticker_clean)
                company_id = upsert_company(conn, profile)
            else:
                company_id = row[0]

        if financial_records:
            fs_count = upsert_financial_statements(conn, company_id, financial_records)
            metrics["records_inserted"] += fs_count

        if market_records:
            mkt_count = upsert_market_data(conn, company_id, market_records)
            metrics["records_inserted"] += mkt_count

        # 5. Transform & Valuation Phase
        logger.info("Running transformations and DCF valuation for %s...", ticker_clean)
        df_fin = get_financials_df(conn, ticker_clean)
        df_mkt = get_market_data_df(conn, ticker_clean)

        fin_analytics = analyze_financials(df_fin)
        mkt_analytics = analyze_market_data(df_mkt)

        dcf_baseline = fin_analytics.get("dcf_baseline", {})
        if not dcf_baseline or dcf_baseline.get("latest_revenue", 0) <= 0:
            raise PipelineError(f"Insufficient financial data to compute DCF for {ticker_clean}")

        # Beta & Cost of Capital
        beta = profile.get("beta") if profile else 1.0
        if beta is None or beta <= 0:
            beta = 1.0

        rf = DEFAULT_RISK_FREE_RATE
        cost_of_equity = compute_cost_of_equity(beta=beta, risk_free_rate=rf)

        interest = float(df_fin["interest_expense"].dropna().iloc[-1]) if "interest_expense" in df_fin.columns and not df_fin["interest_expense"].dropna().empty else None
        debt = dcf_baseline.get("latest_debt", 0.0)
        cost_of_debt = compute_cost_of_debt(interest_expense=interest, total_debt=debt, tax_rate=dcf_baseline.get("effective_tax_rate", 0.21))

        # Market Cap & WACC
        latest_price = mkt_analytics.get("latest_price")
        shares = profile.get("shares_outstanding") if profile and profile.get("shares_outstanding") else 1
        if shares <= 0:
            shares = 1

        equity_val = (latest_price * shares) if latest_price and latest_price > 0 else 1000000.0
        wacc = compute_wacc(equity_val, debt, cost_of_equity, cost_of_debt)

        # DCF valuation using historical avg_fcf_conversion_ratio
        dcf_results = calculate_dcf(
            base_revenue=dcf_baseline["latest_revenue"],
            growth_rate=dcf_baseline.get("baseline_growth_rate", 0.05),
            operating_margin=dcf_baseline.get("avg_operating_margin", 0.15),
            tax_rate=dcf_baseline.get("effective_tax_rate", 0.21),
            wacc=wacc,
            terminal_growth=DEFAULT_TERMINAL_GROWTH_RATE,
            cash=dcf_baseline.get("latest_cash", 0.0),
            debt=debt,
            shares_outstanding=shares,
            fcf_conversion_ratio=dcf_baseline.get("avg_fcf_conversion_ratio", 1.0),
        )

        eval_summary = evaluate_valuation(
            intrinsic_value=dcf_results["intrinsic_value"],
            current_price=latest_price,
        )

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        upsert_valuation_result(conn, company_id, {
            "valuation_date": today_str,
            "wacc": dcf_results["wacc"],
            "terminal_growth": dcf_results["terminal_growth"],
            "enterprise_value": dcf_results["enterprise_value"],
            "equity_value": dcf_results["equity_value"],
            "intrinsic_value": dcf_results["intrinsic_value"],
            "current_price": latest_price,
        })

        metrics["valuation"] = {
            "intrinsic_value": dcf_results["intrinsic_value"],
            "current_price": latest_price,
            "upside_pct": eval_summary["upside_pct"],
            "signal": eval_summary["signal"],
            "wacc": dcf_results["wacc"],
        }

        # 6. SQL Analytics & CSV Reports Export
        logger.info("Executing SQL analytical scripts and exporting CSV reports...")
        run_all_analytics(conn, reports_dir=reports_dir, export_csv=True)

    except Exception as e:
        logger.error("Pipeline run failed for %s: %s", ticker_clean, e, exc_info=True)
        metrics["status"] = "FAILED"
        metrics["error"] = str(e)
        raise
    finally:
        metrics["execution_time_seconds"] = round(time.time() - start_time, 2)
        logger.info(
            "Pipeline Finished: Ticker=%s, Status=%s, Fetched=(FS:%d, Mkt:%d), Inserted=%d, Skipped=%d, Time=%.2fs",
            ticker_clean,
            metrics["status"],
            metrics["fundamentals_fetched"],
            metrics["market_records_fetched"],
            metrics["records_inserted"],
            metrics["records_skipped"],
            metrics["execution_time_seconds"],
        )
        if should_close_conn and conn:
            conn.close()

    return metrics
