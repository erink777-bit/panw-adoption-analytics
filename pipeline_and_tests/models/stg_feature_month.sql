-- model: stg_feature_month  (staging)
-- Feature-level monthly adoption score using the per-feature thresholds carried on
-- the features table: 0 = not enabled, 0.3 = enabled but idle, 0.7 = actively used,
-- 1.0 = deeply used. Usage summed across concurrent entitlements before scoring.
CREATE OR REPLACE VIEW `panw-502122.panw_adoption.stg_feature_month` AS
WITH agg AS (
  SELECT cust_id, product_id, feature_id, month, SUM(usage_events) AS usage_events
  FROM `panw-502122.panw_adoption.feature_adoption`
  GROUP BY cust_id, product_id, feature_id, month
)
SELECT
  a.cust_id, a.product_id, a.feature_id, a.month, f.feature_name, a.usage_events,
  CASE
    WHEN a.usage_events = 0                          THEN 0.0
    WHEN a.usage_events <  f.meaningful_floor_events THEN 0.3
    WHEN a.usage_events <  f.deep_threshold_events   THEN 0.7
    ELSE 1.0
  END AS feature_score
FROM agg a
JOIN `panw-502122.panw_adoption.features` f USING (feature_id);
