-- model: int_sku_components  (intermediate)
-- Three of the four VRS components at customer x product x month:
--   util_health       - non-linear utilization curve on LUR (penalizes shelfware & overage)
--   feature_adoption  - mean feature_score across the SKU's entitled features (breadth + depth)
--   sustained_usage   - recency-weighted trailing-3-month activity (spike-and-drop defense)
-- Also emits prior_lur (trailing avg, for the churn-signal rule downstream).
CREATE OR REPLACE VIEW `panw-502122.panw_adoption.int_sku_components` AS
WITH fa AS (
  SELECT cust_id, product_id, month, AVG(feature_score) AS feature_adoption
  FROM `panw-502122.panw_adoption.stg_feature_month`
  GROUP BY cust_id, product_id, month
),
base AS (
  SELECT
    s.cust_id, s.product_id, s.month, s.consumed_units, s.licensed_amount, s.lur,
    COALESCE(fa.feature_adoption, 0) AS feature_adoption,
    CASE
      WHEN s.lur < 0.10 THEN 0.0
      WHEN s.lur < 0.60 THEN 0.3 + (s.lur - 0.10) * 1.2   -- ramp 0.3 -> 0.9
      WHEN s.lur < 1.00 THEN 0.9 + (s.lur - 0.60) * 0.25  -- ramp 0.9 -> 1.0
      WHEN s.lur <= 1.20 THEN 1.0                          -- fully utilized (peak)
      ELSE 0.8                                             -- overage: capped
    END AS util_health,
    CAST(s.lur >= 0.10 AS INT64) AS active                 -- "meaningful use" floor
  FROM `panw-502122.panw_adoption.stg_sku_month` s
  LEFT JOIN fa USING (cust_id, product_id, month)
),
sus AS (
  SELECT *,
    LAG(active, 1) OVER w AS a1,
    LAG(active, 2) OVER w AS a2,
    -- prior_lur: 3-month look-back (recent history) -> powers the acute churn signal
    AVG(lur) OVER (PARTITION BY cust_id, product_id ORDER BY month
                   ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) AS prior_lur,
    -- ever_active_before: lifetime memory -> separates a churned/lapsed SKU (was active)
    -- from true shelfware (never active), even months after the drop
    MAX(active) OVER (PARTITION BY cust_id, product_id ORDER BY month
                      ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS ever_active_before
  FROM base
  WINDOW w AS (PARTITION BY cust_id, product_id ORDER BY month)
)
SELECT
  cust_id, product_id, month, consumed_units, licensed_amount, lur,
  util_health, feature_adoption,
  -- recency weights 0.5/0.3/0.2, renormalized over available trailing months
  (0.5*active + 0.3*IFNULL(a1,0) + 0.2*IFNULL(a2,0))
    / (0.5 + IF(a1 IS NULL,0,0.3) + IF(a2 IS NULL,0,0.2)) AS sustained_usage,
  prior_lur, IFNULL(ever_active_before, 0) AS ever_active_before
FROM sus;
