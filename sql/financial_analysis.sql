-- Financial Analysis: Year-over-Year Performance & Margin Trends
-- Uses CTE and LAG() window function to calculate annual revenue growth, operating margin, and net margin.

WITH pivoted_financials AS (
    SELECT
        c.ticker,
        c.company_name,
        c.sector,
        fs.period,
        MAX(CASE WHEN fs.line_item = 'total_revenue' THEN fs.value END) AS revenue,
        MAX(CASE WHEN fs.line_item = 'operating_income' THEN fs.value END) AS operating_income,
        MAX(CASE WHEN fs.line_item = 'net_income' THEN fs.value END) AS net_income
    FROM financial_statements fs
    JOIN companies c ON c.company_id = fs.company_id
    GROUP BY c.ticker, fs.period
),
yoy_metrics AS (
    SELECT
        ticker,
        company_name,
        sector,
        period,
        revenue,
        operating_income,
        net_income,
        LAG(revenue) OVER (PARTITION BY ticker ORDER BY period ASC) AS prev_revenue,
        ROUND(operating_income / NULLIF(revenue, 0) * 100, 2) AS operating_margin_pct,
        ROUND(net_income / NULLIF(revenue, 0) * 100, 2) AS net_margin_pct
    FROM pivoted_financials
)
SELECT
    ticker,
    company_name,
    sector,
    period,
    revenue,
    prev_revenue,
    ROUND((revenue - prev_revenue) / NULLIF(prev_revenue, 0) * 100, 2) AS yoy_revenue_growth_pct,
    operating_margin_pct,
    net_margin_pct
FROM yoy_metrics
ORDER BY ticker, period ASC;
