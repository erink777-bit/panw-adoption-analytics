-- model: mart_product_month  (mart, ARR-weighted product roll-up)
-- Rolls SKU-level VRS up to the product across customers, ARR-weighted, so a few large
-- accounts aren't drowned out by many small ones. Feeds the "performance by Product" view.
CREATE OR REPLACE TABLE `panw-502122.panw_adoption.mart_product_month` AS
SELECT
  m.product_id, p.product_name, p.product_platform, m.month,
  ROUND(SAFE_DIVIDE(SUM(m.vrs * m.arr), SUM(m.arr)), 1) AS vrs_arr_weighted,
  ROUND(SUM(m.arr), 0)                                  AS total_arr,
  ROUND(SUM(IF(m.vrs < 50, m.arr, 0)), 0)               AS arr_at_risk,  -- At Risk band or worse
  COUNT(DISTINCT m.cust_id)                             AS customers
FROM `panw-502122.panw_adoption.mart_customer_sku_month` m
JOIN `panw-502122.panw_adoption.products` p USING (product_id)
GROUP BY m.product_id, p.product_name, p.product_platform, m.month;
