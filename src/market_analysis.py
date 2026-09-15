"""Market performance analytics module.

Computes daily returns, month-end returns, annualized volatility across the
available history, and extracts the latest available market price.
"""

from typing import Any, Dict, Optional, Tuple
import numpy as np
import pandas as pd


def compute_daily_returns(df: pd.DataFrame) -> pd.Series:
    """Calculate percentage change in daily closing prices.

    Args:
        df: Chronologically sorted market data DataFrame with DatetimeIndex and 'close'.

    Returns:
        Pandas Series of daily returns.
    """
    if "close" not in df.columns or df.empty:
        return pd.Series(dtype=float)

    return df["close"].pct_change().dropna()


def compute_monthly_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate daily closing prices to month-end and calculate month-over-month returns.

    Args:
        df: Chronologically sorted market data DataFrame with DatetimeIndex and 'close'.

    Returns:
        DataFrame indexed by month string ('YYYY-MM') with columns 'month_end_close'
        and 'monthly_return'.
    """
    if "close" not in df.columns or df.empty:
        return pd.DataFrame(columns=["month_end_close", "monthly_return"])

    # Ensure index is DatetimeIndex
    df_copy = df.copy()
    if not isinstance(df_copy.index, pd.DatetimeIndex):
        df_copy.index = pd.to_datetime(df_copy.index)

    # Group by calendar month and take the last available trading day's close
    monthly_closes = df_copy["close"].resample("ME").last().dropna()
    if monthly_closes.empty:
        # Fallback for older pandas versions where 'ME' is 'M'
        monthly_closes = df_copy["close"].resample("M").last().dropna()

    monthly_df = pd.DataFrame({
        "month_end_close": monthly_closes,
        "monthly_return": monthly_closes.pct_change(),
    })
    monthly_df.index = monthly_df.index.strftime("%Y-%m")
    monthly_df.index.name = "month"

    return monthly_df


def compute_annualized_volatility(daily_returns: pd.Series) -> Optional[float]:
    """Calculate a single annualized volatility metric over the full available history.

    Formula: daily_returns.std() * sqrt(252)

    Args:
        daily_returns: Series of daily returns.

    Returns:
        Annualized volatility as a float (e.g. 0.245 for 24.5%), or None if insufficient data.
    """
    clean_returns = daily_returns.dropna()
    if len(clean_returns) < 2:
        return None

    daily_std = float(clean_returns.std(ddof=1))
    annualized_vol = daily_std * np.sqrt(252)
    return float(annualized_vol)


def get_latest_price_info(df: pd.DataFrame) -> Tuple[Optional[float], Optional[str]]:
    """Retrieve the most recent closing price and corresponding date.

    Returns:
        Tuple of (latest_price, date_str).
    """
    if "close" not in df.columns or df.empty:
        return None, None

    last_row = df.iloc[-1]
    latest_price = float(last_row["close"])

    idx = df.index[-1]
    if hasattr(idx, "strftime"):
        date_str = idx.strftime("%Y-%m-%d")
    else:
        date_str = str(idx).split(" ")[0]

    return latest_price, date_str


def analyze_market_data(df: pd.DataFrame) -> Dict[str, Any]:
    """Execute complete market analytics on an OHLCV DataFrame.

    Returns:
        Dict containing:
        - 'daily_returns': pd.Series
        - 'monthly_returns': pd.DataFrame
        - 'annualized_volatility': float
        - 'latest_price': float
        - 'latest_date': str
    """
    if df.empty:
        return {
            "daily_returns": pd.Series(dtype=float),
            "monthly_returns": pd.DataFrame(),
            "annualized_volatility": None,
            "latest_price": None,
            "latest_date": None,
        }

    daily_ret = compute_daily_returns(df)
    monthly_ret = compute_monthly_returns(df)
    volatility = compute_annualized_volatility(daily_ret)
    latest_price, latest_date = get_latest_price_info(df)

    return {
        "daily_returns": daily_ret,
        "monthly_returns": monthly_ret,
        "annualized_volatility": volatility,
        "latest_price": latest_price,
        "latest_date": latest_date,
    }
