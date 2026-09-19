-- Market Analysis: Monthly Returns and Cross-Sectional Ranking
-- Uses ROW_NUMBER() to identify month-end prices, LAG() for monthly returns, and RANK() for overall & sector ranking.

WITH monthly_prices AS (
    SELECT
        company_id,
        strftime('%Y-%m', date) AS month,
        close,
        ROW_NUMBER() OVER (
            PARTITION BY company_id, strftime('%Y-%m', date)
            ORDER BY date DESC
        ) AS rn
    FROM market_data
),
month_end AS (
    SELECT company_id, month, close
    FROM monthly_prices WHERE rn = 1
),
monthly_returns AS (
    SELECT
        company_id,
        month,
        close / LAG(close) OVER (PARTITION BY company_id ORDER BY month) - 1 AS monthly_return
    FROM month_end
)
SELECT
    c.ticker,
    c.sector,
    mr.month,
    ROUND(mr.monthly_return * 100, 2) AS monthly_return_pct,
    RANK() OVER (PARTITION BY mr.month ORDER BY mr.monthly_return DESC) AS overall_rank,
    RANK() OVER (PARTITION BY c.sector, mr.month ORDER BY mr.monthly_return DESC) AS sector_rank
FROM monthly_returns mr
JOIN companies c ON c.company_id = mr.company_id
WHERE mr.monthly_return IS NOT NULL
ORDER BY mr.month DESC, overall_rank ASC;
