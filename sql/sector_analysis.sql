-- Sector Analysis: Valuation vs Market Comparison & Sector Aggregations
-- Evaluates intrinsic value against market price, computes upside percentage, assigns Undervalued/Overvalued signal,
-- and benchmarks each company against sector averages.

WITH latest_valuations AS (
    SELECT
        v.company_id,
        v.valuation_date,
        v.intrinsic_value,
        v.current_price,
        ROUND((v.intrinsic_value - v.current_price) / NULLIF(v.current_price, 0) * 100.0, 1) AS upside_pct,
        CASE
            WHEN v.intrinsic_value > v.current_price THEN 'Undervalued'
            ELSE 'Overvalued'
        END AS signal,
        ROW_NUMBER() OVER (PARTITION BY v.company_id ORDER BY v.valuation_date DESC) AS rn
    FROM valuation_results v
),
company_valuation AS (
    SELECT
        c.ticker,
        c.company_name,
        c.sector,
        lv.valuation_date,
        lv.intrinsic_value,
        lv.current_price,
        lv.upside_pct,
        lv.signal
    FROM latest_valuations lv
    JOIN companies c ON c.company_id = lv.company_id
    WHERE lv.rn = 1
),
sector_averages AS (
    SELECT
        sector,
        ROUND(AVG(intrinsic_value), 2) AS sector_avg_intrinsic_value,
        ROUND(AVG(current_price), 2) AS sector_avg_current_price,
        ROUND(AVG(upside_pct), 1) AS sector_avg_upside_pct
    FROM company_valuation
    GROUP BY sector
)
SELECT
    cv.ticker,
    cv.company_name,
    cv.sector,
    cv.valuation_date,
    cv.intrinsic_value,
    cv.current_price,
    cv.upside_pct,
    cv.signal,
    sa.sector_avg_intrinsic_value,
    sa.sector_avg_current_price,
    sa.sector_avg_upside_pct,
    ROUND(cv.upside_pct - sa.sector_avg_upside_pct, 1) AS relative_to_sector_upside_pct
FROM company_valuation cv
JOIN sector_averages sa ON sa.sector = cv.sector
ORDER BY cv.sector, cv.upside_pct DESC;
