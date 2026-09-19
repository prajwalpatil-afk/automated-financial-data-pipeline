"""Unit tests for DCF modeling, CAPM, WACC, scenarios, sensitivity, and Monte Carlo."""

import pytest

from src.valuation import (
    calculate_dcf,
    compute_cost_of_debt,
    compute_cost_of_equity,
    compute_sensitivity_matrix,
    compute_wacc,
    evaluate_valuation,
    run_monte_carlo_dcf,
    run_scenarios,
)


def test_compute_cost_of_equity():
    # Ke = Rf + Beta * ERP = 0.042 + 1.2 * 0.055 = 0.108
    ke = compute_cost_of_equity(beta=1.2, risk_free_rate=0.042, market_risk_premium=0.055)
    assert pytest.approx(ke, 0.0001) == 0.108

    # Missing beta defaults to 1.0
    ke_default = compute_cost_of_equity(beta=None, risk_free_rate=0.042, market_risk_premium=0.055)
    assert pytest.approx(ke_default, 0.0001) == 0.097


def test_compute_cost_of_debt():
    # Pre-tax Kd = 2000 / 40000 = 0.05 -> After-tax = 0.05 * (1 - 0.21) = 0.0395
    kd = compute_cost_of_debt(interest_expense=2000.0, total_debt=40000.0, tax_rate=0.21)
    assert pytest.approx(kd, 0.0001) == 0.0395

    # Fallback to default (4.5% pre-tax)
    kd_fallback = compute_cost_of_debt(interest_expense=None, total_debt=None, tax_rate=0.21)
    assert pytest.approx(kd_fallback, 0.0001) == 0.045 * 0.79


def test_compute_wacc():
    # Equity = 75k, Debt = 25k (Total = 100k, We = 0.75, Wd = 0.25)
    # Ke = 0.10, Kd = 0.04 -> WACC = 0.75 * 0.10 + 0.25 * 0.04 = 0.085
    wacc = compute_wacc(
        equity_value=75000.0,
        total_debt=25000.0,
        cost_of_equity=0.10,
        after_tax_cost_of_debt=0.04,
    )
    assert pytest.approx(wacc, 0.0001) == 0.085


@pytest.fixture
def base_dcf_params():
    return {
        "base_revenue": 100000.0,
        "growth_rate": 0.08,
        "operating_margin": 0.20,
        "tax_rate": 0.21,
        "wacc": 0.085,
        "terminal_growth": 0.025,
        "cash": 20000.0,
        "debt": 15000.0,
        "shares_outstanding": 1000,
        "projection_years": 5,
        "fcf_conversion_ratio": 1.10,
    }


def test_calculate_dcf_monotonicity_and_conversion(base_dcf_params):
    base_res = calculate_dcf(**base_dcf_params)
    assert base_res["intrinsic_value"] > 0
    assert base_res["enterprise_value"] > 0
    assert len(base_res["projected_fcfs"]) == 5

    # Higher growth should increase intrinsic value
    higher_growth_params = dict(base_dcf_params, growth_rate=0.12)
    high_growth_res = calculate_dcf(**higher_growth_params)
    assert high_growth_res["intrinsic_value"] > base_res["intrinsic_value"]

    # Higher discount rate (WACC) should decrease intrinsic value
    higher_wacc_params = dict(base_dcf_params, wacc=0.10)
    high_wacc_res = calculate_dcf(**higher_wacc_params)
    assert high_wacc_res["intrinsic_value"] < base_res["intrinsic_value"]

    # Higher FCF conversion ratio should increase intrinsic value
    higher_conv_params = dict(base_dcf_params, fcf_conversion_ratio=1.20)
    high_conv_res = calculate_dcf(**higher_conv_params)
    assert high_conv_res["intrinsic_value"] > base_res["intrinsic_value"]


def test_calculate_dcf_safety_clamp(base_dcf_params):
    # WACC <= terminal_growth should not throw ZeroDivisionError or produce negative values
    invalid_spread_params = dict(base_dcf_params, wacc=0.02, terminal_growth=0.025)
    res = calculate_dcf(**invalid_spread_params)
    assert res["intrinsic_value"] > 0
    assert res["wacc"] > res["terminal_growth"]


def test_run_scenarios(base_dcf_params):
    scenarios = run_scenarios(base_dcf_params)
    assert "bull" in scenarios
    assert "base" in scenarios
    assert "bear" in scenarios

    bull_val = scenarios["bull"]["intrinsic_value"]
    base_val = scenarios["base"]["intrinsic_value"]
    bear_val = scenarios["bear"]["intrinsic_value"]

    assert bull_val > base_val > bear_val


def test_compute_sensitivity_matrix(base_dcf_params):
    matrix = compute_sensitivity_matrix(base_dcf_params)
    assert matrix.shape == (5, 5)

    # In each column, intrinsic value decreases as WACC increases
    for col in matrix.columns:
        col_vals = matrix[col].tolist()
        assert all(col_vals[i] >= col_vals[i + 1] for i in range(len(col_vals) - 1))

    # In each row, intrinsic value increases as terminal growth increases
    for idx in matrix.index:
        row_vals = matrix.loc[idx].tolist()
        assert all(row_vals[i] <= row_vals[i + 1] for i in range(len(row_vals) - 1))


def test_evaluate_valuation():
    undervalued = evaluate_valuation(intrinsic_value=120.0, current_price=100.0)
    assert undervalued["signal"] == "Undervalued"
    assert undervalued["upside_pct"] == 20.0

    overvalued = evaluate_valuation(intrinsic_value=80.0, current_price=100.0)
    assert overvalued["signal"] == "Overvalued"
    assert overvalued["upside_pct"] == -20.0

    no_price = evaluate_valuation(intrinsic_value=100.0, current_price=None)
    assert no_price["signal"] == "No Market Price"
    assert no_price["upside_pct"] is None


def test_run_monte_carlo_dcf_reproducibility(base_dcf_params):
    res1 = run_monte_carlo_dcf(base_dcf_params, n_simulations=1000, seed=42)
    res2 = run_monte_carlo_dcf(base_dcf_params, n_simulations=1000, seed=42)

    assert res1["mean"] == res2["mean"]
    assert res1["median"] == res2["median"]
    assert res1["p10"] < res1["p25"] <= res1["median"] <= res1["p75"] < res1["p90"]
