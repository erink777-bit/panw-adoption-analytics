-- model: mart_customer_month  (mart, ARR-weighted customer roll-up)
-- Rolls SKU-level VRS up to the customer, weighted by ARR so the score tracks
-- dollars-at-risk rather than SKU count. Also exposes arr_at_risk (ARR of SKUs in the
-- "At Risk" band or worse, i.e. VRS < 50) for the exec dollars-at-risk view.
--
-- Each input row is ONE SKU (customer x product x month) with that SKU's own vrs and arr,
-- so the weighted average below is exactly:
--     customer VRS = SUM_over_SKUs(SKU_vrs * SKU_arr) / SUM_over_SKUs(SKU_arr)
-- (vrs and arr in the SQL are the per-SKU values in each row, not customer-level totals.)
CREATE OR REPLACE TABLE `panw-502122.panw_adoption.mart_customer_month` AS
SELECT
  m.cust_id, c.cust_name, c.segment, c.region, m.month,
  ROUND(SAFE_DIVIDE(SUM(m.vrs * m.arr), SUM(m.arr)), 1) AS vrs_arr_weighted,
  ROUND(AVG(m.vrs), 1)                                  AS vrs_simple_avg,
  ROUND(SUM(m.arr), 0)                                  AS total_arr,
  ROUND(SUM(IF(m.vrs < 50, m.arr, 0)), 0)               AS arr_at_risk,  -- At Risk band or worse (aligned with docs)
  COUNT(*)                                              AS skus
FROM `panw-502122.panw_adoption.mart_customer_sku_month` m
JOIN `panw-502122.panw_adoption.customers` c USING (cust_id)
GROUP BY m.cust_id, c.cust_name, c.segment, c.region, m.month;
