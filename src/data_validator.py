"""Data validation and quality assurance module for financial statements and market data.

Applies deterministic structural, logical, and integrity rules before data is loaded
into the SQLite database. Generates formatted pass/fail reports.
"""

from dataclasses import dataclass, field
from datetime import datetime
import logging
from typing import Any, Dict, List, Optional

from src.config import (
    MAX_CONSECUTIVE_GAP_DAYS_WARNING,
    MIN_FINANCIAL_YEARS,
    REQUIRED_BALANCE_ITEMS,
    REQUIRED_CASHFLOW_ITEMS,
    REQUIRED_INCOME_ITEMS,
    REQUIRED_OHLCV_FIELDS,
    REQUIRED_STATEMENT_TYPES,
)

logger = logging.getLogger(__name__)


@dataclass
class ValidationReport:
    """Structured data quality check report."""

    is_valid: bool = True
    income_status: str = "PASS"
    balance_status: str = "PASS"
    cashflow_status: str = "PASS"
    market_status: str = "PASS"

    missing_required_fields: int = 0
    duplicate_periods: int = 0
    duplicate_dates: int = 0
    invalid_ohlc_rows: int = 0
    gap_warnings: int = 0

    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def summary_text(self) -> str:
        """Format data quality check output matching Section 6 of the execution plan."""
        overall_status = "PASS" if self.is_valid else "FAIL"
        return (
            "Data Quality Check\n"
            "------------------\n"
            f"Income Statement: {self.income_status}\n"
            f"Balance Sheet: {self.balance_status}\n"
            f"Cash Flow: {self.cashflow_status}\n"
            f"Market Data (OHLCV): {self.market_status}\n"
            f"Missing required fields: {self.missing_required_fields}\n"
            f"Duplicate periods: {self.duplicate_periods}\n"
            f"Duplicate dates: {self.duplicate_dates}\n"
            f"Invalid OHLC rows: {self.invalid_ohlc_rows}\n"
            f"Gap warnings: {self.gap_warnings}\n"
            f"Status: {overall_status}"
        )


def validate_fundamentals(
    financial_records: List[Dict[str, Any]],
    report: Optional[ValidationReport] = None,
) -> ValidationReport:
    """Validate completeness, data types, and logical consistency of financial statements.

    Args:
        financial_records: List of dicts containing statement_type, period, line_item, value.
        report: Optional existing report to update.

    Returns:
        Updated ValidationReport.
    """
    if report is None:
        report = ValidationReport()

    if not financial_records:
        report.is_valid = False
        report.income_status = "FAIL"
        report.balance_status = "FAIL"
        report.cashflow_status = "FAIL"
        report.errors.append("No financial statement records provided.")
        return report

    # 1. Statement Type Presence
    present_statements = {r.get("statement_type") for r in financial_records}
    for st in REQUIRED_STATEMENT_TYPES:
        if st not in present_statements:
            report.is_valid = False
            msg = f"Missing required statement type: '{st}'."
            report.errors.append(msg)
            if st == "income":
                report.income_status = "FAIL"
            elif st == "balance":
                report.balance_status = "FAIL"
            elif st == "cashflow":
                report.cashflow_status = "FAIL"

    # 2. Check required line items per statement type
    by_statement: Dict[str, Dict[str, Dict[str, float]]] = {
        "income": {},
        "balance": {},
        "cashflow": {},
    }
    seen_keys = set()

    for rec in financial_records:
        st = rec.get("statement_type")
        period = rec.get("period")
        line_item = rec.get("line_item")
        val = rec.get("value")

        if not st or not period or not line_item:
            report.missing_required_fields += 1
            report.errors.append(f"Incomplete record encountered: {rec}")
            continue

        # Check uniqueness of (statement_type, period, line_item)
        key = (st, period, line_item)
        if key in seen_keys:
            report.duplicate_periods += 1
            report.errors.append(f"Duplicate entry for {key}")
        else:
            seen_keys.add(key)

        # Value validity
        if val is None or not isinstance(val, (int, float)):
            report.missing_required_fields += 1
            report.errors.append(f"Non-numeric value for {key}: {val}")
            continue

        if st in by_statement:
            if period not in by_statement[st]:
                by_statement[st][period] = {}
            by_statement[st][period][line_item] = float(val)

    # Validate required line items for each statement type across periods
    def check_required_items(statement_type: str, required_items: List[str]) -> bool:
        periods_dict = by_statement.get(statement_type, {})
        if not periods_dict:
            return False

        has_failure = False
        for period, items in periods_dict.items():
            for req in required_items:
                if req not in items:
                    report.missing_required_fields += 1
                    report.errors.append(
                        f"Missing required line item '{req}' in {statement_type} for period {period}"
                    )
                    has_failure = True
        return not has_failure

    if not check_required_items("income", REQUIRED_INCOME_ITEMS):
        report.income_status = "FAIL"
        report.is_valid = False

    if not check_required_items("balance", REQUIRED_BALANCE_ITEMS):
        report.balance_status = "FAIL"
        report.is_valid = False

    if not check_required_items("cashflow", REQUIRED_CASHFLOW_ITEMS):
        report.cashflow_status = "FAIL"
        report.is_valid = False

    # Logical non-negative checks (e.g. revenue > 0, total assets > 0)
    for period, items in by_statement.get("income", {}).items():
        rev = items.get("total_revenue")
        if rev is not None and rev <= 0:
            report.is_valid = False
            report.income_status = "FAIL"
            report.errors.append(f"Total revenue must be positive; got {rev} for {period}")

    for period, items in by_statement.get("balance", {}).items():
        assets = items.get("total_assets")
        if assets is not None and assets <= 0:
            report.is_valid = False
            report.balance_status = "FAIL"
            report.errors.append(f"Total assets must be positive; got {assets} for {period}")

    # Check sufficient history (>= MIN_FINANCIAL_YEARS)
    income_periods = sorted(by_statement.get("income", {}).keys())
    if len(income_periods) < MIN_FINANCIAL_YEARS:
        report.is_valid = False
        report.income_status = "FAIL"
        report.errors.append(
            f"Insufficient financial history: found {len(income_periods)} periods, "
            f"minimum required is {MIN_FINANCIAL_YEARS}."
        )

    return report


def validate_market_data(
    market_records: List[Dict[str, Any]],
    report: Optional[ValidationReport] = None,
) -> ValidationReport:
    """Validate completeness, numeric integrity, and OHLC relationships for market data.

    Args:
        market_records: List of dicts with date, open, high, low, close, volume.
        report: Optional existing report to update.

    Returns:
        Updated ValidationReport.
    """
    if report is None:
        report = ValidationReport()

    if not market_records:
        report.is_valid = False
        report.market_status = "FAIL"
        report.errors.append("No market data records provided.")
        return report

    seen_dates = set()
    dates_list: List[datetime] = []

    for idx, rec in enumerate(market_records):
        # 1. Required fields presence
        for fld in REQUIRED_OHLCV_FIELDS:
            if fld not in rec or rec[fld] is None:
                report.missing_required_fields += 1
                report.errors.append(f"Missing field '{fld}' in market record at index {idx}.")
                report.market_status = "FAIL"
                report.is_valid = False

        date_str = rec.get("date")
        o = rec.get("open")
        h = rec.get("high")
        l = rec.get("low")
        c = rec.get("close")
        v = rec.get("volume")

        # 2. Date uniqueness
        if date_str:
            if date_str in seen_dates:
                report.duplicate_dates += 1
                report.market_status = "FAIL"
                report.is_valid = False
                report.errors.append(f"Duplicate market date: {date_str}")
            else:
                seen_dates.add(date_str)
                try:
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    dates_list.append(dt)
                except ValueError:
                    report.errors.append(f"Malformed date string: {date_str}")
                    report.market_status = "FAIL"
                    report.is_valid = False

        # 3. Numeric & Positivity checks
        if any(x is None or not isinstance(x, (int, float)) for x in [o, h, l, c, v]):
            report.invalid_ohlc_rows += 1
            report.market_status = "FAIL"
            report.is_valid = False
            continue

        o, h, l, c = float(o), float(h), float(l), float(c)
        v = int(v)

        if c <= 0 or o <= 0 or h <= 0 or l <= 0 or v < 0:
            report.invalid_ohlc_rows += 1
            report.market_status = "FAIL"
            report.is_valid = False
            report.errors.append(
                f"Negative or non-positive price/volume on {date_str}: O={o}, H={h}, L={l}, C={c}, V={v}"
            )
            continue

        # 4. OHLC logical consistency
        # high >= low, high >= open, high >= close, low <= open, low <= close
        # Allow tiny float rounding tolerance (1e-4)
        tol = 1e-4
        if (
            (h < l - tol)
            or (h < o - tol)
            or (h < c - tol)
            or (l > o + tol)
            or (l > c + tol)
        ):
            report.invalid_ohlc_rows += 1
            report.market_status = "FAIL"
            report.is_valid = False
            report.errors.append(
                f"Inconsistent OHLC relationship on {date_str}: O={o}, H={h}, L={l}, C={c}"
            )

    # 5. Gap analysis (weekends/holidays are expected; > MAX_CONSECUTIVE_GAP_DAYS_WARNING emits warning)
    if len(dates_list) > 1:
        dates_sorted = sorted(dates_list)
        for i in range(1, len(dates_sorted)):
            delta = (dates_sorted[i] - dates_sorted[i - 1]).days
            if delta > MAX_CONSECUTIVE_GAP_DAYS_WARNING:
                report.gap_warnings += 1
                msg = (
                    f"Market data gap of {delta} days detected between "
                    f"{dates_sorted[i-1].strftime('%Y-%m-%d')} and {dates_sorted[i].strftime('%Y-%m-%d')}."
                )
                report.warnings.append(msg)
                logger.warning(msg)

    return report


def validate_all(
    financial_records: List[Dict[str, Any]],
    market_records: List[Dict[str, Any]],
) -> ValidationReport:
    """Run comprehensive validation on both financial statements and market data.

    Args:
        financial_records: List of financial statement records.
        market_records: List of historical OHLCV records.

    Returns:
        ValidationReport combining all checks.
    """
    report = ValidationReport()
    validate_fundamentals(financial_records, report)
    validate_market_data(market_records, report)
    return report
