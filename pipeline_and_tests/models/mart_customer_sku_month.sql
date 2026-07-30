-- model: mart_customer_sku_month  (mart, THE headline table)
-- Computes Time to Value, the composite VRS, guardrail flags, and the resolved state
-- at customer x product (SKU) x month. This is the "Deployment & Value Realization metrics"
-- deliverable: TTV = deployment speed, VRS = value realization.
CREATE OR REPLACE TABLE `panw-502122.panw_adoption.mart_customer_sku_month` AS
WITH ent_start AS (      -- SKU deployment start + total ARR (for TTV and roll-ups)
  SELECT cust_id, product_id, MIN(start_date) AS start_date, SUM(arr) AS arr
  FROM `panw-502122.panw_adoption.entitlements`
  GROUP BY cust_id, product_id
),
firstval AS (           -- first month the SKU crossed the meaningful-use floor
  SELECT cust_id, product_id, MIN(month) AS first_value_month
  FROM `panw-502122.panw_adoption.stg_sku_month`
  WHERE lur >= 0.10
  GROUP BY cust_id, product_id
),
ttv AS (                -- Time to Value component (0-1)
  SELECT e.cust_id, e.product_id, e.arr, e.start_date,
    DATE_DIFF(fv.first_value_month, e.start_date, DAY) AS ttv_days,
    CASE
      WHEN fv.first_value_month IS NULL THEN 0.0
      WHEN DATE_DIFF(fv.first_value_month, e.start_date, DAY) <= 30 THEN 1.0
      WHEN DATE_DIFF(fv.first_value_month, e.start_date, DAY) <= 90
        THEN 1 - (DATE_DIFF(fv.first_value_month, e.start_date, DAY) - 30) / 60.0
      ELSE 0.0
    END AS ttv_score
  FROM ent_start e
  LEFT JOIN firstval fv USING (cust_id, product_id)
),
pf AS (                 -- products that carry separately-adoptable features (spec 4.2)
  SELECT DISTINCT product_id FROM `panw-502122.panw_adoption.features`
),
scored AS (
  -- has_features: spec 4.2 graceful degradation - a SKU with no separately-adoptable
  --   features drops the Feature Adoption term and renormalizes the remaining weights.
  -- grace: spec 4.4 grace period - the SKU's first calendar month with no meaningful
  --   use yet drops the TTV term (renormalized) so a brand-new account is not punished
  --   or mistaken for shelfware.
  SELECT c.cust_id, c.product_id, c.month, c.lur, c.util_health, c.feature_adoption,
    c.sustained_usage, c.prior_lur, c.ever_active_before, t.ttv_score, t.ttv_days, t.arr,
    (pf.product_id IS NOT NULL) AS has_features,
    (DATE_TRUNC(t.start_date, MONTH) = c.month AND c.util_health = 0) AS grace,
    100 * ( 0.35*c.util_health
          + IF(pf.product_id IS NOT NULL, 0.25*c.feature_adoption, 0)
          + 0.25*c.sustained_usage
          + IF(DATE_TRUNC(t.start_date, MONTH) = c.month AND c.util_health = 0,
               0, 0.15*t.ttv_score) )
      / ( 0.35 + IF(pf.product_id IS NOT NULL, 0.25, 0) + 0.25
          + IF(DATE_TRUNC(t.start_date, MONTH) = c.month AND c.util_health = 0,
               0, 0.15) ) AS vrs
  FROM `panw-502122.panw_adoption.int_sku_components` c
  JOIN ttv t USING (cust_id, product_id)
  LEFT JOIN pf ON pf.product_id = c.product_id
)
SELECT
  cust_id, product_id, month,
  ROUND(lur,3) AS lur, ROUND(util_health,3) AS util_health,
  IF(has_features, ROUND(feature_adoption,3), NULL) AS feature_adoption,
  ROUND(sustained_usage,3) AS sustained_usage,
  IF(grace, NULL, ROUND(ttv_score,3)) AS ttv_score, ttv_days, ever_active_before, arr,
  ROUND(vrs,1) AS vrs,
  -- guardrail flags: ONLY signals that fire orthogonally to the state (catch a risk /
  -- opportunity hiding inside an otherwise-healthy account -- what the VRS average masks).
  -- Shelfware/churn/onboarding are NOT flags: they are already the resolved state.
  -- gate on raw LUR (not the scored util_health): the overage cap fixes util_health at 0.8,
  -- which would exempt heavy over-consumers with narrow adoption - exactly who this flag is for
  (has_features AND feature_adoption < 0.25 AND lur >= 0.9) AS flag_single_feature_dependency, -- healthy-looking but fragile
  (lur > 1.2)                                       AS flag_expansion,                 -- healthy AND a sales upsell
  -- resolved state: one mutually-exclusive label. Priority = most specific/urgent first,
  -- generic VRS bands last (the first matching branch wins).
  CASE
    WHEN grace                                                 THEN 'Grace Period'     -- brand-new, not yet judged
    WHEN IFNULL(prior_lur,0) >= 0.6 AND sustained_usage < 0.34 THEN 'Churn Signal'    -- just collapsed (urgent)
    WHEN util_health = 0 AND ever_active_before = 1            THEN 'Lapsed'           -- was active, now dead
    WHEN util_health = 0                                       THEN 'Shelfware Risk'   -- never activated
    WHEN ttv_score < 0.5 AND feature_adoption < 0.3           THEN 'Onboarding Stall' -- slow + shallow deploy
    WHEN vrs >= 70 THEN 'Value Realized'
    WHEN vrs >= 50 THEN 'Developing'
    WHEN vrs >= 30 THEN 'At Risk'
    ELSE 'Critical'
  END AS state
FROM scored;
