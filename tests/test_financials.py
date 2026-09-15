"""Unit tests for financial statements analytics and fundamental metrics."""

import numpy as np
import pandas as pd
import pytest

from src.financial_analysis import (
    analyze_financials,
    compute_cagr,
    compute_free_cash_flow,
    compute_margins,
    compute_ratios,
    compute_revenue_growth,
    extract_dcf_baseline,
)


@pytest.fixture
def sample_financials_df():
    """Create a 3-year pivoted financial statement DataFrame."""
    periods = ["2022-12-31", "2023-12-31", "2024-12-31"]
    data = {
        "total_revenue": [100000.0, 120000.0, 150000.0],
        "operating_income": [20000.0, 26400.0, 34500.0],
        "net_income": [15000.0, 20000.0, 27000.0],
        "total_assets": [200000.0, 230000.0, 270000.0],
        "total_liabilities": [80000.0, 90000.0, 100000.0],
        "stockholders_equity": [120000.0, 140000.0, 170000.0],
        "total_debt": [40000.0, 45000.0, 50000.0],
        "cash_and_cash_equivalents": [25000.0, 30000.0, 40000.0],
        "operating_cash_flow": [22000.0, 28000.0, 36000.0],
        "capital_expenditure": [-5000.0, -6000.0, -7000.0],  # Negative outflow
        "tax_provision": [4000.0, 5000.0, 6500.0],
        "ebit": [20000.0, 26400.0, 34500.0],
    }
    df = pd.DataFrame(data, index=periods)
    return df


def test_compute_revenue_growth(sample_financials_df):
    growth = compute_revenue_growth(sample_financials_df)
    assert len(growth) == 3
    assert np.isnan(growth.iloc[0])
    assert pytest.approx(growth.loc["2023-12-31"], 0.001) == 0.20   # (120k - 100k) / 100k
    assert pytest.approx(growth.loc["2024-12-31"], 0.001) == 0.25   # (150k - 120k) / 120k


def test_compute_cagr(sample_financials_df):
    cagr = compute_cagr(sample_financials_df["total_revenue"])
    assert cagr is not None
    # (150000 / 100000) ** (1/2) - 1 = sqrt(1.5) - 1 ≈ 0.2247
    assert pytest.approx(cagr, 0.001) == 0.2247


def test_compute_margins(sample_financials_df):
    margins = compute_margins(sample_financials_df)
    assert "operating_margin" in margins.columns
    assert "net_margin" in margins.columns
    # 2022: op_margin = 20k / 100k = 0.20, net_margin = 15k / 100k = 0.15
    assert pytest.approx(margins.loc["2022-12-31", "operating_margin"], 0.001) == 0.20
    assert pytest.approx(margins.loc["2022-12-31", "net_margin"], 0.001) == 0.15
    # 2024: op_margin = 34.5k / 150k = 0.23, net_margin = 27k / 150k = 0.18
    assert pytest.approx(margins.loc["2024-12-31", "operating_margin"], 0.001) == 0.23
    assert pytest.approx(margins.loc["2024-12-31", "net_margin"], 0.001) == 0.18


def test_compute_free_cash_flow_and_sign_handling(sample_financials_df):
    fcf_df = compute_free_cash_flow(sample_financials_df)
    # FCF = OCF - abs(CapEx) = 36000 - 7000 = 29000
    assert pytest.approx(fcf_df.loc["2024-12-31", "free_cash_flow"], 0.001) == 29000.0
    # FCF conversion = 29000 / 27000 ≈ 1.074
    assert pytest.approx(fcf_df.loc["2024-12-31", "fcf_conversion"], 0.001) == 1.074


def test_compute_ratios(sample_financials_df):
    ratios = compute_ratios(sample_financials_df)
    # 2024 D/E = 50k / 170k ≈ 0.294
    assert pytest.approx(ratios.loc["2024-12-31", "debt_to_equity"], 0.001) == 0.294
    # 2024 ROA = 27k / 270k = 0.10
    assert pytest.approx(ratios.loc["2024-12-31", "return_on_assets"], 0.001) == 0.10
    # 2024 Cash to Debt = 40k / 50k = 0.80
    assert pytest.approx(ratios.loc["2024-12-31", "cash_to_debt"], 0.001) == 0.80


def test_extract_dcf_baseline(sample_financials_df):
    baseline = extract_dcf_baseline(sample_financials_df)
    assert baseline["latest_revenue"] == 150000.0
    assert pytest.approx(baseline["baseline_growth_rate"], 0.001) == 0.2247
    assert baseline["latest_fcf"] == 29000.0
    assert baseline["latest_cash"] == 40000.0
    assert baseline["latest_debt"] == 50000.0
    # Effective tax = 6500 / 34500 ≈ 0.1884
    assert pytest.approx(baseline["effective_tax_rate"], 0.001) == 0.1884


def test_analyze_financials_empty():
    res = analyze_financials(pd.DataFrame())
    assert res["growth"].empty
    assert res["dcf_baseline"] == {}
