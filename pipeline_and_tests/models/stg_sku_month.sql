-- model: stg_sku_month  (staging)
-- Overlap-resolved monthly utilization at customer x product (SKU) grain.
-- Summing consumed_units + licensed_amount across all concurrently-active entitlements
-- for the same customer x product x month is the step that correctly handles mid-year
-- expansions (two overlapping contracts) without double-counting or dropping either.
CREATE OR REPLACE VIEW `panw-502122.panw_adoption.stg_sku_month` AS
SELECT
  cust_id, product_id, month,
  SUM(consumed_units)  AS consumed_units,
  SUM(licensed_amount) AS licensed_amount,
  SAFE_DIVIDE(SUM(consumed_units), NULLIF(SUM(licensed_amount), 0)) AS lur
FROM `panw-502122.panw_adoption.consumption`
GROUP BY cust_id, product_id, month;
