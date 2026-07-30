-- model: mart_customer_feature_month  (mart, feature-level detail)
-- Feature-level adoption for the dashboard drill-down: which entitled features are
-- live vs. idle vs. deep, per customer x product x feature x month.
CREATE OR REPLACE TABLE `panw-502122.panw_adoption.mart_customer_feature_month` AS
SELECT
  cust_id, product_id, feature_id, feature_name, month, usage_events, feature_score,
  CASE feature_score
    WHEN 0.0 THEN 'not_enabled'
    WHEN 0.3 THEN 'enabled_idle'
    WHEN 0.7 THEN 'active'
    ELSE 'deep'
  END AS adoption_level
FROM `panw-502122.panw_adoption.stg_feature_month`;
