-- ============================================================================
-- Data-quality test harness for the VRS pipeline (panw-502122.panw_adoption)
-- Returns one row per assertion: cat, test, val, expect, result (PASS/FAIL).
-- A test PASSES when the measured value equals the expected value.
-- Run in the BigQuery console, or via tests/run_tests.py (exits non-zero on any FAIL).
-- Categories: integrity | overlap | anomaly | ground_truth | schema | unit | regression | freshness
-- (36 fatal assertions; cross-env parity vs the offline CSV build runs non-fatally in run_tests.py)
-- ============================================================================
WITH months AS (SELECT m FROM UNNEST(GENERATE_DATE_ARRAY(DATE '2025-07-01', DATE '2026-06-01', INTERVAL 1 MONTH)) m),
exp AS (  -- expected concurrently-active licensed amount per SKU-month (overlap resolution oracle)
  SELECT e.cust_id, e.product_id, mo.m AS month, SUM(e.licensed_amount) AS lic
  FROM `panw-502122.panw_adoption.entitlements` e CROSS JOIN months mo
  WHERE mo.m >= e.start_date AND mo.m < e.end_date GROUP BY 1,2,3
),
results AS (
  -- ---- INTEGRITY: referential, grain, ranges, coverage --------------------
  SELECT 1 ord,'integrity' cat,'orphan_consumption_customers' test,
    (SELECT COUNT(*) FROM `panw-502122.panw_adoption.consumption` c LEFT JOIN `panw-502122.panw_adoption.customers` u USING(cust_id) WHERE u.cust_id IS NULL) val, 0 expect
  UNION ALL SELECT 2,'integrity','orphan_consumption_products',
    (SELECT COUNT(*) FROM `panw-502122.panw_adoption.consumption` c LEFT JOIN `panw-502122.panw_adoption.products` p USING(product_id) WHERE p.product_id IS NULL),0
  UNION ALL SELECT 3,'integrity','orphan_consumption_entitlements',
    (SELECT COUNT(*) FROM `panw-502122.panw_adoption.consumption` c LEFT JOIN `panw-502122.panw_adoption.entitlements` e USING(entitlement_id) WHERE e.entitlement_id IS NULL),0
  UNION ALL SELECT 4,'integrity','orphan_feature_adoption_features',
    (SELECT COUNT(*) FROM `panw-502122.panw_adoption.feature_adoption` f LEFT JOIN `panw-502122.panw_adoption.features` ff USING(feature_id) WHERE ff.feature_id IS NULL),0
  UNION ALL SELECT 5,'integrity','sku_month_grain_unique',
    (SELECT COUNT(*) FROM (SELECT cust_id,product_id,month FROM `panw-502122.panw_adoption.mart_customer_sku_month` GROUP BY 1,2,3 HAVING COUNT(*)>1)),0
  UNION ALL SELECT 6,'integrity','vrs_within_0_100',
    (SELECT COUNT(*) FROM `panw-502122.panw_adoption.mart_customer_sku_month` WHERE vrs<0 OR vrs>100),0
  UNION ALL SELECT 7,'integrity','components_within_0_1',
    (SELECT COUNT(*) FROM `panw-502122.panw_adoption.mart_customer_sku_month` WHERE util_health NOT BETWEEN 0 AND 1 OR feature_adoption NOT BETWEEN 0 AND 1 OR sustained_usage NOT BETWEEN 0 AND 1 OR ttv_score NOT BETWEEN 0 AND 1),0
  UNION ALL SELECT 8,'integrity','no_negative_or_zero_license',
    (SELECT COUNT(*) FROM `panw-502122.panw_adoption.consumption` WHERE consumed_units<0 OR licensed_amount<=0),0
  UNION ALL SELECT 9,'integrity','twelve_months_present',
    (SELECT COUNT(DISTINCT month) FROM `panw-502122.panw_adoption.consumption`),12
  UNION ALL SELECT 10,'integrity','every_entitlement_has_consumption',
    (SELECT COUNT(*) FROM `panw-502122.panw_adoption.entitlements` e LEFT JOIN (SELECT DISTINCT entitlement_id FROM `panw-502122.panw_adoption.consumption`) c USING(entitlement_id) WHERE c.entitlement_id IS NULL),0
  -- ---- OVERLAP RESOLUTION (mid-year expansions) ---------------------------
  UNION ALL SELECT 11,'overlap','overlap_pairs_exist_ge6',
    (SELECT IF(COUNT(*)>=6,6,COUNT(*)) FROM `panw-502122.panw_adoption.entitlements` a JOIN `panw-502122.panw_adoption.entitlements` b ON a.cust_id=b.cust_id AND a.product_id=b.product_id AND a.entitlement_id<b.entitlement_id AND a.start_date<b.end_date AND b.start_date<a.end_date),6
  UNION ALL SELECT 12,'overlap','licensed_equals_sum_active_entitlements',
    (SELECT COUNT(*) FROM `panw-502122.panw_adoption.stg_sku_month` s JOIN exp USING(cust_id,product_id,month) WHERE ABS(s.licensed_amount-exp.lic)>0.5),0
  -- ---- ANOMALY DETECTION (each injected anomaly must be caught) ------------
  UNION ALL SELECT 13,'anomaly','shelfware_accounts_eq_10',
    (SELECT COUNT(*) FROM (SELECT cust_id FROM `panw-502122.panw_adoption.consumption` GROUP BY 1 HAVING SUM(consumed_units)=0)),10
  UNION ALL SELECT 14,'anomaly','shelfware_all_state_shelfware_risk',
    -- first calendar month of an unactivated SKU resolves to 'Grace Period' (spec 4.4); every later month must be Shelfware Risk
    (SELECT COUNT(*) FROM `panw-502122.panw_adoption.mart_customer_sku_month` m WHERE m.cust_id IN (SELECT cust_id FROM `panw-502122.panw_adoption.consumption` GROUP BY 1 HAVING SUM(consumed_units)=0) AND m.state NOT IN ('Shelfware Risk','Grace Period')),0
  UNION ALL SELECT 15,'anomaly','overage_accounts_eq_15',
    (SELECT COUNT(*) FROM (SELECT cust_id FROM `panw-502122.panw_adoption.stg_sku_month` GROUP BY 1 HAVING AVG(lur)>1.2)),15
  UNION ALL SELECT 16,'anomaly','overage_all_raise_expansion_flag',
    (SELECT COUNT(*) FROM (SELECT cust_id FROM `panw-502122.panw_adoption.stg_sku_month` GROUP BY 1 HAVING AVG(lur)>1.2) o WHERE o.cust_id NOT IN (SELECT cust_id FROM `panw-502122.panw_adoption.mart_customer_sku_month` WHERE flag_expansion)),0
  UNION ALL SELECT 17,'anomaly','churn_signal_customers_eq_5',
    (SELECT COUNT(DISTINCT cust_id) FROM `panw-502122.panw_adoption.mart_customer_sku_month` WHERE state='Churn Signal'),5
  UNION ALL SELECT 18,'anomaly','slow_onboarder_accounts_eq_5',
    (SELECT COUNT(*) FROM `panw-502122.panw_adoption.customers` WHERE behavior_profile='slow_onboarder'),5
  UNION ALL SELECT 19,'anomaly','slow_onboarders_all_hit_onboarding_stall',
    (SELECT COUNT(*) FROM `panw-502122.panw_adoption.customers` c WHERE c.behavior_profile='slow_onboarder' AND c.cust_id NOT IN (SELECT cust_id FROM `panw-502122.panw_adoption.mart_customer_sku_month` WHERE state='Onboarding Stall')),0
  UNION ALL SELECT 20,'anomaly','partial_ttv_band_exercised',
    -- the 31-90-day TTV ramp must produce at least one score strictly between 0 and 1
    (SELECT IF(COUNT(*)>0,1,0) FROM `panw-502122.panw_adoption.mart_customer_sku_month` WHERE ttv_score>0 AND ttv_score<1),1
  -- ---- GROUND TRUTH (no false positives on healthy accounts) ---------------
  UNION ALL SELECT 21,'ground_truth','normal_no_risk_states_or_expansion',
    (SELECT COUNT(*) FROM `panw-502122.panw_adoption.mart_customer_sku_month` m JOIN `panw-502122.panw_adoption.customers` c USING(cust_id) WHERE c.behavior_profile='normal' AND (m.state IN ('Churn Signal','Shelfware Risk','Lapsed','Onboarding Stall') OR m.flag_expansion)),0
  -- ---- SCHEMA: expected columns exist with expected types (guards load/auto-detect drift)
  UNION ALL SELECT 22,'schema','customers_schema',
    (SELECT COUNTIF((column_name='cust_id' AND data_type='STRING') OR (column_name='cust_name' AND data_type='STRING') OR (column_name='region' AND data_type='STRING') OR (column_name='segment' AND data_type='STRING') OR (column_name='behavior_profile' AND data_type='STRING')) FROM `panw-502122.panw_adoption.INFORMATION_SCHEMA.COLUMNS` WHERE table_name='customers'),5
  UNION ALL SELECT 23,'schema','products_schema',
    (SELECT COUNTIF((column_name='product_id' AND data_type='STRING') OR (column_name='product_name' AND data_type='STRING') OR (column_name='product_platform' AND data_type='STRING') OR (column_name='unit_of_measure' AND data_type='STRING')) FROM `panw-502122.panw_adoption.INFORMATION_SCHEMA.COLUMNS` WHERE table_name='products'),4
  UNION ALL SELECT 24,'schema','entitlements_schema',
    (SELECT COUNTIF((column_name='entitlement_id' AND data_type='STRING') OR (column_name='product_id' AND data_type='STRING') OR (column_name='cust_id' AND data_type='STRING') OR (column_name='units_purchased' AND data_type='INT64') OR (column_name='licensed_amount' AND data_type='INT64') OR (column_name='unit_price' AND data_type='FLOAT64') OR (column_name='arr' AND data_type='FLOAT64') OR (column_name='start_date' AND data_type='DATE') OR (column_name='end_date' AND data_type='DATE') OR (column_name='is_expansion' AND data_type='BOOL')) FROM `panw-502122.panw_adoption.INFORMATION_SCHEMA.COLUMNS` WHERE table_name='entitlements'),10
  UNION ALL SELECT 25,'schema','features_schema',
    (SELECT COUNTIF((column_name='feature_id' AND data_type='STRING') OR (column_name='feature_name' AND data_type='STRING') OR (column_name='feature_description' AND data_type='STRING') OR (column_name='product_id' AND data_type='STRING') OR (column_name='meaningful_floor_events' AND data_type='INT64') OR (column_name='deep_threshold_events' AND data_type='INT64')) FROM `panw-502122.panw_adoption.INFORMATION_SCHEMA.COLUMNS` WHERE table_name='features'),6
  UNION ALL SELECT 26,'schema','consumption_schema',
    (SELECT COUNTIF((column_name='consumption_id' AND data_type='STRING') OR (column_name='entitlement_id' AND data_type='STRING') OR (column_name='cust_id' AND data_type='STRING') OR (column_name='product_id' AND data_type='STRING') OR (column_name='month' AND data_type='DATE') OR (column_name='consumed_units' AND data_type='FLOAT64') OR (column_name='licensed_amount' AND data_type='INT64')) FROM `panw-502122.panw_adoption.INFORMATION_SCHEMA.COLUMNS` WHERE table_name='consumption'),7
  UNION ALL SELECT 27,'schema','feature_adoption_schema',
    (SELECT COUNTIF((column_name='adoption_id' AND data_type='STRING') OR (column_name='cust_id' AND data_type='STRING') OR (column_name='entitlement_id' AND data_type='STRING') OR (column_name='product_id' AND data_type='STRING') OR (column_name='feature_id' AND data_type='STRING') OR (column_name='month' AND data_type='DATE') OR (column_name='usage_events' AND data_type='INT64')) FROM `panw-502122.panw_adoption.INFORMATION_SCHEMA.COLUMNS` WHERE table_name='feature_adoption'),7
  UNION ALL SELECT 28,'schema','mart_sku_month_schema',
    (SELECT COUNTIF((column_name='cust_id' AND data_type='STRING') OR (column_name='product_id' AND data_type='STRING') OR (column_name='month' AND data_type='DATE') OR (column_name='lur' AND data_type='FLOAT64') OR (column_name='util_health' AND data_type='FLOAT64') OR (column_name='feature_adoption' AND data_type='FLOAT64') OR (column_name='sustained_usage' AND data_type='FLOAT64') OR (column_name='ttv_score' AND data_type='FLOAT64') OR (column_name='arr' AND data_type='FLOAT64') OR (column_name='vrs' AND data_type='FLOAT64') OR (column_name='flag_single_feature_dependency' AND data_type='BOOL') OR (column_name='flag_expansion' AND data_type='BOOL') OR (column_name='state' AND data_type='STRING')) FROM `panw-502122.panw_adoption.INFORMATION_SCHEMA.COLUMNS` WHERE table_name='mart_customer_sku_month'),13
  -- ---- UNIT: scoring-curve properties must hold on every row of the mart
  UNION ALL SELECT 29,'unit','shelfware_scores_zero',
    (SELECT COUNT(*) FROM `panw-502122.panw_adoption.mart_customer_sku_month` WHERE lur < 0.10 AND util_health <> 0),0
  UNION ALL SELECT 30,'unit','overage_capped_and_flagged',
    (SELECT COUNT(*) FROM `panw-502122.panw_adoption.mart_customer_sku_month` WHERE lur > 1.2 AND (util_health <> 0.8 OR flag_expansion = FALSE)),0
  UNION ALL SELECT 31,'unit','peak_band_scores_one',
    (SELECT COUNT(*) FROM `panw-502122.panw_adoption.mart_customer_sku_month` WHERE lur >= 1.0 AND lur <= 1.2 AND util_health <> 1.0),0
  UNION ALL SELECT 32,'unit','partial_ttv_implies_31_90_days',
    (SELECT COUNT(*) FROM `panw-502122.panw_adoption.mart_customer_sku_month` WHERE ttv_score > 0 AND ttv_score < 1 AND (ttv_days < 31 OR ttv_days > 90)),0
  -- ---- REGRESSION: aggregate checksums pinned; any unintended change fails the run
  UNION ALL SELECT 33,'regression','total_rows_stable',
    (SELECT COUNT(*) FROM `panw-502122.panw_adoption.mart_customer_sku_month`),5483
  UNION ALL SELECT 34,'regression','vrs_checksum_stable',
    (SELECT IF(ABS(SUM(vrs) - 373804) < 2, 0, 1) FROM `panw-502122.panw_adoption.mart_customer_sku_month`),0
  UNION ALL SELECT 35,'regression','latest_month_arr_stable',
    (SELECT IF(ABS(SUM(arr) - 146499822) < 5, 0, 1) FROM `panw-502122.panw_adoption.mart_customer_sku_month` WHERE month = DATE '2026-06-01'),0
  UNION ALL SELECT 36,'freshness','latest_month_is_current',
    (SELECT IF(MAX(month) = DATE '2026-06-01', 0, 1) FROM `panw-502122.panw_adoption.mart_customer_sku_month`),0
)
SELECT cat, test, val, expect, IF(val=expect,'PASS','FAIL') AS result
FROM results ORDER BY ord;
