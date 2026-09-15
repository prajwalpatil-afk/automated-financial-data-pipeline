"""Unit tests for market performance analytics (returns, volatility, latest price)."""

import numpy as np
import pandas as pd
import pytest

from src.market_analysis import (
    analyze_market_data,
    compute_annualized_volatility,
    compute_daily_returns,
    compute_monthly_returns,
    get_latest_price_info,
)


@pytest.fixture
def sample_market_df():
    """Create a sample OHLCV DataFrame spanning multiple months."""
    # 60 business days from 2024-01-01
    dates = pd.date_range(start="2024-01-02", periods=60, freq="B")
    # Monotonic price series: 100, 101, 102, ...
    closes = [100.0 + i * 0.5 for i in range(len(dates))]
    opens = [c - 0.2 for c in closes]
    highs = [c + 1.0 for c in closes]
    lows = [c - 1.0 for c in closes]
    volumes = [100000 + i * 500 for i in range(len(dates))]

    df = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        },
        index=dates,
    )
    return df


def test_compute_daily_returns(sample_market_df):
    daily_ret = compute_daily_returns(sample_market_df)
    assert len(daily_ret) == len(sample_market_df) - 1
    # Day 1 close: 100.0, Day 2 close: 100.5 -> return = 0.5 / 100 = 0.005
    assert pytest.approx(daily_ret.iloc[0], 0.0001) == 0.005


def test_compute_monthly_returns(sample_market_df):
    monthly_df = compute_monthly_returns(sample_market_df)
    assert not monthly_df.empty
    assert "month_end_close" in monthly_df.columns
    assert "monthly_return" in monthly_df.columns
    # Spans Jan, Feb, Mar 2024
    assert len(monthly_df) >= 3
    # First month's return is NaN, subsequent months have return
    assert np.isnan(monthly_df["monthly_return"].iloc[0])
    assert monthly_df["monthly_return"].iloc[1] > 0


def test_compute_annualized_volatility(sample_market_df):
    daily_ret = compute_daily_returns(sample_market_df)
    vol = compute_annualized_volatility(daily_ret)
    assert vol is not None
    # Manual check: vol = std * sqrt(252)
    expected = float(daily_ret.std(ddof=1) * np.sqrt(252))
    assert pytest.approx(vol, 0.0001) == expected
    assert vol > 0


def test_compute_annualized_volatility_insufficient_data():
    empty_series = pd.Series(dtype=float)
    assert compute_annualized_volatility(empty_series) is None

    single_val = pd.Series([0.01])
    assert compute_annualized_volatility(single_val) is None


def test_get_latest_price_info(sample_market_df):
    price, date_str = get_latest_price_info(sample_market_df)
    assert price == sample_market_df["close"].iloc[-1]
    assert date_str == sample_market_df.index[-1].strftime("%Y-%m-%d")


def test_analyze_market_data(sample_market_df):
    results = analyze_market_data(sample_market_df)
    assert len(results["daily_returns"]) == len(sample_market_df) - 1
    assert not results["monthly_returns"].empty
    assert results["annualized_volatility"] is not None
    assert results["latest_price"] == sample_market_df["close"].iloc[-1]
    assert results["latest_date"] is not None
