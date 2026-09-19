"""Financial analysis module for fundamental corporate metrics.

Computes revenue growth, profitability margins, Free Cash Flow (FCF),
balance sheet ratios, and DCF baseline projection parameters.
"""

from typing import Any, Dict, Optional
import numpy as np
import pandas as pd


def compute_revenue_growth(df: pd.DataFrame) -> pd.Series:
    """Calculate Year-over-Year (YoY) revenue growth rate.

    Args:
        df: Pivoted financials DataFrame with period index and line items as columns.

    Returns:
        Pandas Series of YoY revenue growth rates.
    """
    if "total_revenue" not in df.columns:
        return pd.Series(dtype=float)
    return df["total_revenue"].pct_change()


def compute_cagr(series: pd.Series) -> Optional[float]:
    """Compute Compound Annual Growth Rate across available periods in a Series."""
    clean_series = series.dropna()
    if len(clean_series) < 2:
        return None

    start_val = clean_series.iloc[0]
    end_val = clean_series.iloc[-1]
    periods = len(clean_series) - 1

    if start_val <= 0 or end_val <= 0 or periods <= 0:
        return None

    return float((end_val / start_val) ** (1.0 / periods) - 1.0)


def compute_margins(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate Operating Margin and Net Profit Margin.

    Returns:
        DataFrame with 'operating_margin' and 'net_margin' columns.
    """
    res = pd.DataFrame(index=df.index)
    if "total_revenue" in df.columns and "operating_income" in df.columns:
        res["operating_margin"] = df["operating_income"] / df["total_revenue"]
    else:
        res["operating_margin"] = np.nan

    if "total_revenue" in df.columns and "net_income" in df.columns:
        res["net_margin"] = df["net_income"] / df["total_revenue"]
    else:
        res["net_margin"] = np.nan

    return res


def compute_free_cash_flow(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate Free Cash Flow ensuring proper sign handling for Capital Expenditure.

    Formula: FCF = operating_cash_flow - abs(capital_expenditure)

    Returns:
        DataFrame with 'free_cash_flow' and 'fcf_conversion' (FCF / net_income).
    """
    res = pd.DataFrame(index=df.index)
    if "operating_cash_flow" in df.columns and "capital_expenditure" in df.columns:
        res["free_cash_flow"] = df["operating_cash_flow"] - df["capital_expenditure"].abs()
    else:
        res["free_cash_flow"] = np.nan

    if "net_income" in df.columns:
        res["fcf_conversion"] = res["free_cash_flow"] / df["net_income"]
    else:
        res["fcf_conversion"] = np.nan

    return res


def compute_ratios(df: pd.DataFrame) -> pd.DataFrame:
    """Compute balance sheet and operational ratios.

    Includes:
    - Debt-to-Equity: total_debt / stockholders_equity
    - Return on Assets (ROA): net_income / total_assets
    - Cash-to-Debt: cash_and_cash_equivalents / total_debt
    """
    res = pd.DataFrame(index=df.index)

    # Debt to Equity
    if "total_debt" in df.columns:
        if "stockholders_equity" in df.columns:
            res["debt_to_equity"] = df["total_debt"] / df["stockholders_equity"]
        elif "total_assets" in df.columns and "total_liabilities" in df.columns:
            equity = df["total_assets"] - df["total_liabilities"]
            res["debt_to_equity"] = df["total_debt"] / equity.replace(0, np.nan)
        else:
            res["debt_to_equity"] = np.nan
    else:
        res["debt_to_equity"] = np.nan

    # Return on Assets
    if "net_income" in df.columns and "total_assets" in df.columns:
        res["return_on_assets"] = df["net_income"] / df["total_assets"]
    else:
        res["return_on_assets"] = np.nan

    # Cash to Debt
    if "cash_and_cash_equivalents" in df.columns and "total_debt" in df.columns:
        res["cash_to_debt"] = df["cash_and_cash_equivalents"] / df["total_debt"].replace(0, np.nan)
    else:
        res["cash_to_debt"] = np.nan

    return res


def extract_dcf_baseline(df: pd.DataFrame) -> Dict[str, Any]:
    """Extract historical baseline parameters needed to seed the DCF model in Phase 6.

    Aggregates:
    - latest_revenue: most recent total revenue
    - revenue_cagr: historical CAGR or mean YoY growth rate
    - avg_operating_margin: mean operating margin over available years
    - latest_fcf: most recent Free Cash Flow
    - latest_cash: most recent cash & equivalents
    - latest_debt: most recent total debt
    - effective_tax_rate: estimated from tax_provision / ebit, or default fallback

    Returns:
        Dict of baseline parameters.
    """
    if df.empty:
        return {}

    df_sorted = df.sort_index()

    # Revenue & growth
    latest_revenue = float(df_sorted["total_revenue"].iloc[-1]) if "total_revenue" in df_sorted.columns else 0.0
    growth_series = compute_revenue_growth(df_sorted).dropna()
    rev_cagr = compute_cagr(df_sorted["total_revenue"]) if "total_revenue" in df_sorted.columns else None
    mean_growth = float(growth_series.mean()) if not growth_series.empty else 0.05
    baseline_growth = rev_cagr if rev_cagr is not None else mean_growth

    # Margins
    margins = compute_margins(df_sorted)
    op_margin_series = margins["operating_margin"].dropna()
    avg_op_margin = float(op_margin_series.mean()) if not op_margin_series.empty else 0.15

    # FCF & conversion ratio
    fcf_df = compute_free_cash_flow(df_sorted)
    latest_fcf = float(fcf_df["free_cash_flow"].dropna().iloc[-1]) if not fcf_df["free_cash_flow"].dropna().empty else 0.0
    conversion_series = fcf_df["fcf_conversion"].replace([np.inf, -np.inf], np.nan).dropna()
    avg_fcf_conversion = float(conversion_series.mean()) if not conversion_series.empty and not pd.isna(conversion_series.mean()) else 1.0
    if avg_fcf_conversion <= 0:
        avg_fcf_conversion = 1.0

    # Balance sheet items for Enterprise Value -> Equity Value bridge
    latest_cash = float(df_sorted["cash_and_cash_equivalents"].dropna().iloc[-1]) if "cash_and_cash_equivalents" in df_sorted.columns and not df_sorted["cash_and_cash_equivalents"].dropna().empty else 0.0
    latest_debt = float(df_sorted["total_debt"].dropna().iloc[-1]) if "total_debt" in df_sorted.columns and not df_sorted["total_debt"].dropna().empty else 0.0

    # Effective tax rate estimate
    tax_rate = 0.21
    if "tax_provision" in df_sorted.columns and "ebit" in df_sorted.columns:
        ebit_val = df_sorted["ebit"].iloc[-1]
        tax_val = df_sorted["tax_provision"].iloc[-1]
        if pd.notna(ebit_val) and pd.notna(tax_val) and ebit_val > 0 and 0 <= tax_val <= ebit_val:
            tax_rate = float(tax_val / ebit_val)

    return {
        "latest_revenue": latest_revenue,
        "baseline_growth_rate": baseline_growth,
        "avg_operating_margin": avg_op_margin,
        "latest_fcf": latest_fcf,
        "avg_fcf_conversion_ratio": avg_fcf_conversion,
        "latest_cash": latest_cash,
        "latest_debt": latest_debt,
        "effective_tax_rate": tax_rate,
    }


def analyze_financials(df: pd.DataFrame) -> Dict[str, Any]:
    """Execute complete financial analysis on pivoted statements DataFrame."""
    if df.empty:
        return {"growth": pd.Series(), "margins": pd.DataFrame(), "fcf": pd.DataFrame(), "ratios": pd.DataFrame(), "dcf_baseline": {}}

    growth = compute_revenue_growth(df)
    margins = compute_margins(df)
    fcf = compute_free_cash_flow(df)
    ratios = compute_ratios(df)
    dcf_baseline = extract_dcf_baseline(df)

    return {
        "growth": growth,
        "margins": margins,
        "fcf": fcf,
        "ratios": ratios,
        "dcf_baseline": dcf_baseline,
    }
