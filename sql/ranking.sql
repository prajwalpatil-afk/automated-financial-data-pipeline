-- Multi-Metric Company Ranking & Fundamental + Market Screen
-- Ranks companies by Revenue Growth Rate (%), Operating Margin (%), and Free Cash Flow ($).
-- Applies a combined screen: Revenue Growth > 0% AND Operating Margin > 0% AND Trailing Monthly Return > 0%.

WITH company_financial_periods AS (
    SELECT
        c.company_id,
        c.ticker,
        c.company_name,
        c.sector,
        fs.period,
        MAX(CASE WHEN fs.line_item = 'total_revenue' THEN fs.value END) AS revenue,
        MAX(CASE WHEN fs.line_item = 'operating_income' THEN fs.value END) AS operating_income,
        MAX(CASE WHEN fs.line_item = 'operating_cash_flow' THEN fs.value END) AS ocf,
        MAX(CASE WHEN fs.line_item = 'capital_expenditure' THEN fs.value END) AS capex,
        ROW_NUMBER() OVER (PARTITION BY c.company_id ORDER BY fs.period DESC) AS period_recency_rn
    FROM financial_statements fs
    JOIN companies c ON c.company_id = fs.company_id
    GROUP BY c.company_id, fs.period
),
growth_and_fcf AS (
    SELECT
        company_id,
        ticker,
        company_name,
        sector,
        period,
        revenue,
        operating_income,
        ROUND((revenue - LAG(revenue) OVER (PARTITION BY company_id ORDER BY period ASC)) / NULLIF(LAG(revenue) OVER (PARTITION BY company_id ORDER BY period ASC), 0) * 100, 2) AS yoy_revenue_growth_pct,
        ROUND(operating_income / NULLIF(revenue, 0) * 100, 2) AS operating_margin_pct,
        ROUND(COALESCE(ocf, 0) - ABS(COALESCE(capex, 0)), 2) AS free_cash_flow,
        period_recency_rn
    FROM company_financial_periods
),
latest_financials AS (
    SELECT
        company_id,
        ticker,
        company_name,
        sector,
        period AS latest_period,
        yoy_revenue_growth_pct,
        operating_margin_pct,
        free_cash_flow
    FROM growth_and_fcf
    WHERE period_recency_rn = 1
),
monthly_closes AS (
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
month_end_data AS (
    SELECT company_id, month, close
    FROM monthly_closes WHERE rn = 1
),
latest_market_returns AS (
    SELECT
        company_id,
        ROUND((close / LAG(close) OVER (PARTITION BY company_id ORDER BY month ASC) - 1) * 100, 2) AS trailing_monthly_return_pct,
        ROW_NUMBER() OVER (PARTITION BY company_id ORDER BY month DESC) AS recency_rn
    FROM month_end_data
),
trailing_return_per_company AS (
    SELECT company_id, trailing_monthly_return_pct
    FROM latest_market_returns
    WHERE recency_rn = 1
)
SELECT
    lf.ticker,
    lf.company_name,
    lf.sector,
    lf.latest_period,
    lf.yoy_revenue_growth_pct,
    RANK() OVER (ORDER BY lf.yoy_revenue_growth_pct DESC) AS revenue_growth_rank,
    lf.operating_margin_pct,
    RANK() OVER (ORDER BY lf.operating_margin_pct DESC) AS operating_margin_rank,
    lf.free_cash_flow,
    RANK() OVER (ORDER BY lf.free_cash_flow DESC) AS fcf_rank,
    COALESCE(tr.trailing_monthly_return_pct, 0.0) AS trailing_monthly_return_pct,
    CASE
        WHEN lf.yoy_revenue_growth_pct > 0
         AND lf.operating_margin_pct > 0
         AND COALESCE(tr.trailing_monthly_return_pct, 0) > 0
        THEN 'PASS'
        ELSE 'FAIL'
    END AS screen_status
FROM latest_financials lf
LEFT JOIN trailing_return_per_company tr ON tr.company_id = lf.company_id
ORDER BY revenue_growth_rank ASC;
