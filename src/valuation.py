"""Valuation module implementing CAPM, WACC, DCF modeling, scenarios, sensitivity, and Monte Carlo.

Centerpiece of the analytical layer. Computes intrinsic value per share using a
reusable, pure-function DCF engine informed by historical financial ratios, and
compares results against the latest available market price.
"""

from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

from src.config import (
    DEFAULT_COST_OF_DEBT,
    DEFAULT_MARKET_RISK_PREMIUM,
    DEFAULT_RISK_FREE_RATE,
    DEFAULT_TAX_RATE,
    DEFAULT_TERMINAL_GROWTH_RATE,
    MONTE_CARLO_SEED,
    MONTE_CARLO_SIMULATIONS,
    PROJECTION_YEARS,
    SCENARIOS,
)


# =====================================================================
# Cost of Capital Components (CAPM & WACC)
# =====================================================================
def compute_cost_of_equity(
    beta: Optional[float],
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    market_risk_premium: float = DEFAULT_MARKET_RISK_PREMIUM,
) -> float:
    """Calculate the Cost of Equity using the Capital Asset Pricing Model (CAPM).

    Formula: Cost of Equity = Risk-Free Rate + Beta * Market Risk Premium

    Args:
        beta: Company equity beta sourced directly from yfinance metadata.
        risk_free_rate: 10-year Treasury reference rate.
        market_risk_premium: Expected excess market return.

    Returns:
        Cost of equity as a decimal (e.g. 0.095 for 9.5%).
    """
    effective_beta = float(beta) if beta is not None and beta > 0 else 1.0
    return float(risk_free_rate + (effective_beta * market_risk_premium))


def compute_cost_of_debt(
    interest_expense: Optional[float] = None,
    total_debt: Optional[float] = None,
    tax_rate: float = DEFAULT_TAX_RATE,
    default_cost_of_debt: float = DEFAULT_COST_OF_DEBT,
) -> float:
    """Calculate the after-tax Cost of Debt.

    Formula: Pre-Tax Cost of Debt * (1 - Tax Rate)
    Falls back to default_cost_of_debt if historical debt/interest data is missing.
    """
    pre_tax_kd = default_cost_of_debt
    if (
        interest_expense is not None
        and total_debt is not None
        and total_debt > 0
        and interest_expense > 0
    ):
        calc_kd = float(interest_expense / total_debt)
        # Apply sanity bounds (1% to 20%); fallback if outside realistic corporate range
        if 0.01 <= calc_kd <= 0.20:
            pre_tax_kd = calc_kd

    return float(pre_tax_kd * (1.0 - tax_rate))


def compute_wacc(
    equity_value: float,
    total_debt: float,
    cost_of_equity: float,
    after_tax_cost_of_debt: float,
) -> float:
    """Calculate Weighted Average Cost of Capital (WACC).

    Formula: (E / V) * Ke + (D / V) * Kd * (1 - t)
    """
    total_capital = equity_value + max(0.0, total_debt)
    if total_capital <= 0:
        return cost_of_equity

    weight_equity = equity_value / total_capital
    weight_debt = max(0.0, total_debt) / total_capital

    return float((weight_equity * cost_of_equity) + (weight_debt * after_tax_cost_of_debt))


# =====================================================================
# Core DCF Model (Pure Reusable Function)
# =====================================================================
def calculate_dcf(
    base_revenue: float,
    growth_rate: float,
    operating_margin: float,
    tax_rate: float = DEFAULT_TAX_RATE,
    wacc: float = 0.085,
    terminal_growth: float = DEFAULT_TERMINAL_GROWTH_RATE,
    cash: float = 0.0,
    debt: float = 0.0,
    shares_outstanding: int = 1,
    projection_years: int = PROJECTION_YEARS,
    fcf_conversion_ratio: float = 1.0,
) -> Dict[str, Any]:
    """Pure, reusable Discounted Cash Flow valuation function.

    Projects Revenue -> EBIT -> NOPAT -> FCF (adjusted by historical conversion ratio)
    over N years, computes Gordon Growth Terminal Value, Enterprise Value, and Intrinsic Value.

    Args:
        base_revenue: Most recent annual revenue.
        growth_rate: Annual projected revenue growth rate.
        operating_margin: Projected operating margin.
        tax_rate: Corporate tax rate.
        wacc: Discount rate (WACC).
        terminal_growth: Long-term perpetual growth rate.
        cash: Cash and cash equivalents.
        debt: Total debt.
        shares_outstanding: Diluted common shares outstanding.
        projection_years: Forecast horizon (default 5).
        fcf_conversion_ratio: Historical FCF / Net Income ratio from financial_analysis.py.

    Returns:
        Dict containing intrinsic_value, enterprise_value, equity_value,
        projected cash flows, terminal value, and discount rate.
    """
    # Defensive checks
    effective_shares = max(1, shares_outstanding)
    effective_conversion = fcf_conversion_ratio if fcf_conversion_ratio > 0 else 1.0

    # Safety guard: Gordon Growth denominator (WACC - terminal_growth) must be positive
    effective_wacc = wacc
    if effective_wacc <= terminal_growth:
        effective_wacc = terminal_growth + 0.01  # Minimum 100 bps spread

    projected_revenues: List[float] = []
    projected_fcfs: List[float] = []
    pv_fcfs: List[float] = []

    current_rev = base_revenue
    for t in range(1, projection_years + 1):
        current_rev = current_rev * (1.0 + growth_rate)
        projected_revenues.append(current_rev)

        ebit_t = current_rev * operating_margin
        nopat_t = ebit_t * (1.0 - tax_rate)
        fcf_t = nopat_t * effective_conversion
        projected_fcfs.append(fcf_t)

        pv_t = fcf_t / ((1.0 + effective_wacc) ** t)
        pv_fcfs.append(pv_t)

    # Terminal Value at Year N via Gordon Growth Model
    terminal_fcf = projected_fcfs[-1] * (1.0 + terminal_growth)
    terminal_value = terminal_fcf / (effective_wacc - terminal_growth)
    pv_terminal_value = terminal_value / ((1.0 + effective_wacc) ** projection_years)

    # Enterprise & Equity Value Bridge
    sum_pv_fcfs = sum(pv_fcfs)
    enterprise_value = sum_pv_fcfs + pv_terminal_value
    equity_value = enterprise_value + cash - debt
    intrinsic_value_per_share = max(0.0, equity_value / effective_shares)

    return {
        "intrinsic_value": round(float(intrinsic_value_per_share), 2),
        "enterprise_value": round(float(enterprise_value), 2),
        "equity_value": round(float(equity_value), 2),
        "sum_pv_fcfs": round(float(sum_pv_fcfs), 2),
        "terminal_value": round(float(terminal_value), 2),
        "pv_terminal_value": round(float(pv_terminal_value), 2),
        "projected_revenues": [round(r, 2) for r in projected_revenues],
        "projected_fcfs": [round(f, 2) for f in projected_fcfs],
        "pv_fcfs": [round(p, 2) for p in pv_fcfs],
        "wacc": round(float(effective_wacc), 4),
        "terminal_growth": round(float(terminal_growth), 4),
    }


# =====================================================================
# Scenario Analysis (Bull, Base, Bear)
# =====================================================================
def run_scenarios(
    base_params: Dict[str, Any],
    scenarios_config: Dict[str, Dict[str, float]] = SCENARIOS,
) -> Dict[str, Dict[str, Any]]:
    """Run Bull, Base, and Bear cases through the pure DCF function.

    Applies scenario multipliers to growth rate, margins, WACC, and terminal growth.
    """
    results: Dict[str, Dict[str, Any]] = {}

    base_growth = base_params.get("growth_rate", 0.05)
    base_margin = base_params.get("operating_margin", 0.15)
    base_wacc = base_params.get("wacc", 0.085)
    base_terminal = base_params.get("terminal_growth", DEFAULT_TERMINAL_GROWTH_RATE)

    for scenario_name, modifiers in scenarios_config.items():
        scenario_growth = base_growth * modifiers.get("revenue_growth_multiplier", 1.0)
        scenario_margin = base_margin * modifiers.get("operating_margin_multiplier", 1.0)
        scenario_wacc = base_wacc + modifiers.get("wacc_adjustment", 0.0)
        scenario_terminal = base_terminal + modifiers.get("terminal_growth_adjustment", 0.0)

        dcf_out = calculate_dcf(
            base_revenue=base_params["base_revenue"],
            growth_rate=scenario_growth,
            operating_margin=scenario_margin,
            tax_rate=base_params.get("tax_rate", DEFAULT_TAX_RATE),
            wacc=scenario_wacc,
            terminal_growth=scenario_terminal,
            cash=base_params.get("cash", 0.0),
            debt=base_params.get("debt", 0.0),
            shares_outstanding=base_params.get("shares_outstanding", 1),
            projection_years=base_params.get("projection_years", PROJECTION_YEARS),
            fcf_conversion_ratio=base_params.get("fcf_conversion_ratio", 1.0),
        )
        results[scenario_name] = dcf_out

    return results


# =====================================================================
# Sensitivity Matrix (WACC x Terminal Growth)
# =====================================================================
def compute_sensitivity_matrix(
    base_params: Dict[str, Any],
    wacc_steps: Optional[List[float]] = None,
    growth_steps: Optional[List[float]] = None,
) -> pd.DataFrame:
    """Generate a 2D sensitivity table of Intrinsic Values varying WACC and Terminal Growth.

    Returns:
        DataFrame with WACC as rows, Terminal Growth as columns, and Intrinsic Value as values.
    """
    center_wacc = base_params.get("wacc", 0.085)
    center_g = base_params.get("terminal_growth", DEFAULT_TERMINAL_GROWTH_RATE)

    if wacc_steps is None:
        wacc_steps = [round(center_wacc + delta, 4) for delta in [-0.015, -0.0075, 0.0, 0.0075, 0.015]]
    if growth_steps is None:
        growth_steps = [round(center_g + delta, 4) for delta in [-0.01, -0.005, 0.0, 0.005, 0.01]]

    matrix: Dict[str, List[float]] = {}
    for g in growth_steps:
        col_label = f"g={g*100:.1f}%"
        col_vals: List[float] = []
        for w in wacc_steps:
            dcf_res = calculate_dcf(
                base_revenue=base_params["base_revenue"],
                growth_rate=base_params.get("growth_rate", 0.05),
                operating_margin=base_params.get("operating_margin", 0.15),
                tax_rate=base_params.get("tax_rate", DEFAULT_TAX_RATE),
                wacc=w,
                terminal_growth=g,
                cash=base_params.get("cash", 0.0),
                debt=base_params.get("debt", 0.0),
                shares_outstanding=base_params.get("shares_outstanding", 1),
                projection_years=base_params.get("projection_years", PROJECTION_YEARS),
                fcf_conversion_ratio=base_params.get("fcf_conversion_ratio", 1.0),
            )
            col_vals.append(dcf_res["intrinsic_value"])
        matrix[col_label] = col_vals

    row_labels = [f"wacc={w*100:.2f}%" for w in wacc_steps]
    return pd.DataFrame(matrix, index=row_labels)


# =====================================================================
# Market Valuation Comparison
# =====================================================================
def evaluate_valuation(
    intrinsic_value: float,
    current_price: Optional[float],
) -> Dict[str, Any]:
    """Compare computed intrinsic value against the latest available market price.

    Returns:
        Dict with intrinsic_value, current_price, upside_pct, and signal ('Undervalued'/'Overvalued').
    """
    if current_price is None or current_price <= 0:
        return {
            "intrinsic_value": intrinsic_value,
            "current_price": None,
            "upside_pct": None,
            "signal": "No Market Price",
        }

    upside_pct = round(((intrinsic_value - current_price) / current_price) * 100.0, 1)
    signal = "Undervalued" if intrinsic_value > current_price else "Overvalued"

    return {
        "intrinsic_value": intrinsic_value,
        "current_price": round(current_price, 2),
        "upside_pct": upside_pct,
        "signal": signal,
    }


# =====================================================================
# Monte Carlo Simulation (Optional Extension, NumPy only)
# =====================================================================
def run_monte_carlo_dcf(
    base_params: Dict[str, Any],
    n_simulations: int = MONTE_CARLO_SIMULATIONS,
    seed: int = MONTE_CARLO_SEED,
) -> Dict[str, float]:
    """Run Monte Carlo simulation sampling growth, margins, WACC, and terminal growth.

    Uses a fixed NumPy seed for deterministic, reproducible results.
    """
    rng = np.random.default_rng(seed)

    base_growth = base_params.get("growth_rate", 0.05)
    base_margin = base_params.get("operating_margin", 0.15)
    base_wacc = base_params.get("wacc", 0.085)
    base_g = base_params.get("terminal_growth", DEFAULT_TERMINAL_GROWTH_RATE)
    base_rev = base_params["base_revenue"]
    cash = base_params.get("cash", 0.0)
    debt = base_params.get("debt", 0.0)
    shares = max(1, base_params.get("shares_outstanding", 1))
    tax = base_params.get("tax_rate", DEFAULT_TAX_RATE)
    conversion = base_params.get("fcf_conversion_ratio", 1.0)
    n_years = base_params.get("projection_years", PROJECTION_YEARS)

    # Sample normally distributed random variables with conservative standard deviations
    growth_samples = rng.normal(loc=base_growth, scale=abs(base_growth) * 0.20 + 0.01, size=n_simulations)
    margin_samples = rng.normal(loc=base_margin, scale=abs(base_margin) * 0.15 + 0.01, size=n_simulations)
    wacc_samples = rng.normal(loc=base_wacc, scale=0.01, size=n_simulations)
    terminal_samples = rng.normal(loc=base_g, scale=0.005, size=n_simulations)

    # Clamp parameters to financially sensible boundaries
    margin_samples = np.clip(margin_samples, 0.01, 0.70)
    wacc_samples = np.clip(wacc_samples, 0.04, 0.20)
    terminal_samples = np.clip(terminal_samples, 0.005, 0.04)

    # Ensure WACC > terminal_growth
    wacc_samples = np.maximum(wacc_samples, terminal_samples + 0.01)

    intrinsic_values = np.zeros(n_simulations)

    for i in range(n_simulations):
        g = growth_samples[i]
        m = margin_samples[i]
        w = wacc_samples[i]
        tg = terminal_samples[i]

        # Multi-year projection
        sum_pv_fcf = 0.0
        rev = base_rev
        last_fcf = 0.0
        for t in range(1, n_years + 1):
            rev *= (1.0 + g)
            fcf_t = (rev * m * (1.0 - tax)) * conversion
            sum_pv_fcf += fcf_t / ((1.0 + w) ** t)
            last_fcf = fcf_t

        # Terminal value
        tv = (last_fcf * (1.0 + tg)) / (w - tg)
        pv_tv = tv / ((1.0 + w) ** n_years)

        ev = sum_pv_fcf + pv_tv
        eq_val = ev + cash - debt
        intrinsic_values[i] = max(0.0, eq_val / shares)

    return {
        "mean": round(float(np.mean(intrinsic_values)), 2),
        "median": round(float(np.median(intrinsic_values)), 2),
        "std_dev": round(float(np.std(intrinsic_values)), 2),
        "p10": round(float(np.percentile(intrinsic_values, 10)), 2),
        "p25": round(float(np.percentile(intrinsic_values, 25)), 2),
        "p75": round(float(np.percentile(intrinsic_values, 75)), 2),
        "p90": round(float(np.percentile(intrinsic_values, 90)), 2),
    }
