-- =====================================================================
-- BigQuery-native synthetic data generation for the VRS framework
-- Project.dataset: panw-502122.panw_adoption
-- =====================================================================
-- Why in-warehouse SQL (vs. loading the Python CSVs)?
--   The target is a BigQuery *sandbox*: it can't read local files and
--   restricts DML. Generating natively with GENERATE_ARRAY + CTAS avoids
--   any data transfer. Determinism comes from FARM_FINGERPRINT(seed_string)
--   instead of a RNG seed, so re-running reproduces the same dataset.
-- Mirrors data_generation/generate_data.py (same schema, same anomaly rates).
-- Run top to bottom.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS `panw-502122.panw_adoption` OPTIONS(location='US');

-- 1. CUSTOMERS (100) — exact behavior mix 10/15/5/8/62 via hash-ranked assignment
CREATE OR REPLACE TABLE `panw-502122.panw_adoption.customers` AS
WITH ids AS (SELECT id FROM UNNEST(GENERATE_ARRAY(1,100)) AS id),
h AS (
  SELECT id, FORMAT('C%04d', id) AS cust_id,
    ABS(FARM_FINGERPRINT(FORMAT('reg-%d', id))) AS hr,
    ABS(FARM_FINGERPRINT(FORMAT('seg-%d', id))) AS hs,
    ABS(FARM_FINGERPRINT(FORMAT('beh-%d', id))) AS hb,
    ABS(FARM_FINGERPRINT(FORMAT('nm-%d', id))) AS hn
  FROM ids
),
ranked AS (SELECT *, ROW_NUMBER() OVER (ORDER BY hb) AS rn FROM h)
SELECT cust_id,
  CONCAT(
    ['Summit','Vertex','Apex','Pioneer','Cobalt','Ironclad','Northwind','Silverline','Redwood','Bluepeak','Meridian','Quantum','Sterling','Halcyon','Granite'][OFFSET(MOD(hn,15))],
    ' ',
    ['Systems','Security','Networks','Holdings','Global','Technologies','Industries','Financial','Logistics','Group'][OFFSET(MOD(DIV(hn,15),10))]) AS cust_name,
  ['AMER','EMEA','APAC','LATAM'][OFFSET(MOD(hr,4))] AS region,
  IF(MOD(hs,100) < 55, 'Enterprise', 'Mid-Market') AS segment,
  CASE WHEN rn<=10 THEN 'shelfware' WHEN rn<=25 THEN 'overage' WHEN rn<=30 THEN 'spike_drop'
       ELSE 'normal' END AS behavior_profile
FROM ranked;

-- 2. PRODUCTS (500) — PANW form factors
CREATE OR REPLACE TABLE `panw-502122.panw_adoption.products` AS
WITH ids AS (SELECT id FROM UNNEST(GENERATE_ARRAY(1,500)) AS id),
h AS (SELECT id, FORMAT('P%04d', id) AS product_id,
   ABS(FARM_FINGERPRINT(FORMAT('plat-%d', id))) AS hp, ABS(FARM_FINGERPRINT(FORMAT('mod-%d', id))) AS hm FROM ids),
p AS (SELECT product_id, hm,
   CASE WHEN MOD(hp,100)<30 THEN 'hardware_ngfw' WHEN MOD(hp,100)<60 THEN 'software_ngfw'
        WHEN MOD(hp,100)<85 THEN 'sase' ELSE 'cloud_ngfw' END AS product_platform FROM h)
SELECT product_id,
  CONCAT(CASE product_platform
    WHEN 'hardware_ngfw' THEN ['PA-410','PA-440','PA-460','PA-1410','PA-3410','PA-5410','PA-7500'][OFFSET(MOD(hm,7))]
    WHEN 'software_ngfw' THEN ['VM-100','VM-300','VM-500','VM-700','CN-Series'][OFFSET(MOD(hm,5))]
    WHEN 'sase' THEN ['Prisma Access Mobile Users','Prisma Access Remote Networks','Prisma Access Browser'][OFFSET(MOD(hm,3))]
    ELSE ['Cloud NGFW for AWS','Cloud NGFW for Azure'][OFFSET(MOD(hm,2))] END, ' SKU-', product_id) AS product_name,
  product_platform,
  CASE product_platform WHEN 'hardware_ngfw' THEN 'device_license' WHEN 'software_ngfw' THEN 'credits'
       WHEN 'sase' THEN 'seats' ELSE 'usage_units' END AS unit_of_measure
FROM p;

-- 3. FEATURES helper (with expected volume) -> features + feature_thresholds
CREATE OR REPLACE TABLE `panw-502122.panw_adoption._features_full` AS
WITH prod AS (SELECT product_id, product_name, 3 + MOD(ABS(FARM_FINGERPRINT('k'||product_id)),4) AS k
              FROM `panw-502122.panw_adoption.products`),
exploded AS (SELECT product_id, product_name, fidx FROM prod, UNNEST(GENERATE_ARRAY(1, k)) AS fidx),
named AS (SELECT product_id, product_name, fidx,
   MOD(ABS(FARM_FINGERPRINT(product_id||'-'||CAST(fidx AS STRING))),12) AS fn,
   ABS(FARM_FINGERPRINT('vol-'||product_id||'-'||CAST(fidx AS STRING))) AS hv FROM exploded),
mapped AS (SELECT product_id, product_name, fidx, hv,
   ['Advanced Threat Prevention','Advanced WildFire','Advanced URL Filtering','Advanced DNS Security','IoT/OT Security','GlobalProtect','Enterprise DLP','SaaS Security','AI Access Security','SD-WAN','App-ID','Decryption'][OFFSET(fn)] AS feature_name,
   [800000,120000,2000000,5000000,60000,40000,90000,70000,30000,150000,3000000,1200000][OFFSET(fn)] AS base_vol FROM named)
SELECT FORMAT('F%05d', ROW_NUMBER() OVER (ORDER BY product_id, fidx)) AS feature_id,
  feature_name, CONCAT(feature_name, ' capability delivered within ', product_name) AS feature_description,
  product_id, CAST(ROUND(base_vol*(0.6+MOD(hv,81)/100.0)) AS INT64) AS expected_active_volume
FROM mapped;

-- features carries its own thresholds (meaningful_floor = 20% of expected, deep = 80%)
CREATE OR REPLACE TABLE `panw-502122.panw_adoption.features` AS
SELECT feature_id, feature_name, feature_description, product_id,
  CAST(ROUND(0.20*expected_active_volume) AS INT64) AS meaningful_floor_events,
  CAST(ROUND(0.80*expected_active_volume) AS INT64) AS deep_threshold_events
FROM `panw-502122.panw_adoption._features_full`;

-- 4. ENTITLEMENTS (~470, incl. 6 mid-year expansions with overlapping dates)
CREATE OR REPLACE TABLE `panw-502122.panw_adoption.entitlements` AS
WITH base AS (SELECT c.cust_id, 2 + MOD(ABS(FARM_FINGERPRINT('ne-'||c.cust_id)),6) AS n_ent FROM `panw-502122.panw_adoption.customers` c),
exploded AS (SELECT cust_id, i, FORMAT('P%04d', 1 + MOD(ABS(FARM_FINGERPRINT(cust_id||'-e'||CAST(i AS STRING))),500)) AS product_id
             FROM base, UNNEST(GENERATE_ARRAY(1, n_ent)) AS i),
joined AS (SELECT e.cust_id, e.product_id, p.product_platform,
   ABS(FARM_FINGERPRINT('u-'||e.cust_id||'-'||CAST(e.i AS STRING))) AS hu,
   ABS(FARM_FINGERPRINT('pr-'||e.cust_id||'-'||CAST(e.i AS STRING))) AS hpr,
   ABS(FARM_FINGERPRINT('st-'||e.cust_id||'-'||CAST(e.i AS STRING))) AS hst
   FROM exploded e JOIN `panw-502122.panw_adoption.products` p USING(product_id)),
calc AS (SELECT cust_id, product_id,
   CASE product_platform WHEN 'hardware_ngfw' THEN 1+MOD(hu,30) WHEN 'software_ngfw' THEN 50+MOD(hu,1950) WHEN 'sase' THEN 100+MOD(hu,11900) ELSE 20+MOD(hu,580) END AS units_purchased,
   CASE product_platform WHEN 'hardware_ngfw' THEN 8000+MOD(hpr,47000) WHEN 'software_ngfw' THEN 28+MOD(hpr,7) WHEN 'sase' THEN 40+MOD(hpr,90) ELSE 60+MOD(hpr,160) END AS unit_price,
   CASE WHEN MOD(hst,100)<70 THEN DATE '2025-07-01' ELSE DATE_ADD(DATE '2025-07-01', INTERVAL MOD(hst,4) MONTH) END AS start_date,
   FALSE AS is_expansion FROM joined),
exp_custs AS (SELECT cust_id, FORMAT('P%04d', 1 + MOD(ABS(FARM_FINGERPRINT(cust_id||'-e1')),500)) AS product_id,
   ABS(FARM_FINGERPRINT('xu-'||cust_id)) AS hu, ABS(FARM_FINGERPRINT('xs-'||cust_id)) AS hs
   FROM `panw-502122.panw_adoption.customers` WHERE cust_id IN ('C0007','C0018','C0032','C0045','C0061','C0088')),
expansions AS (SELECT x.cust_id, x.product_id,
   CASE p.product_platform WHEN 'hardware_ngfw' THEN 20+MOD(x.hu,40) WHEN 'software_ngfw' THEN 2000+MOD(x.hu,3000) WHEN 'sase' THEN 8000+MOD(x.hu,12000) ELSE 400+MOD(x.hu,600) END AS units_purchased,
   CASE p.product_platform WHEN 'hardware_ngfw' THEN 8000+MOD(x.hu,47000) WHEN 'software_ngfw' THEN 28+MOD(x.hu,7) WHEN 'sase' THEN 40+MOD(x.hu,90) ELSE 60+MOD(x.hu,160) END AS unit_price,
   DATE_ADD(DATE '2025-07-01', INTERVAL (5+MOD(x.hs,3)) MONTH) AS start_date, TRUE AS is_expansion
   FROM exp_custs x JOIN `panw-502122.panw_adoption.products` p USING(product_id)),
unioned AS (SELECT * FROM calc UNION ALL SELECT * FROM expansions)
SELECT FORMAT('E%05d', ROW_NUMBER() OVER (ORDER BY cust_id, is_expansion, product_id)) AS entitlement_id,
  product_id, cust_id, units_purchased, units_purchased AS licensed_amount, unit_price,
  ROUND(units_purchased*unit_price,2) AS arr, start_date, DATE_ADD(start_date, INTERVAL 12 MONTH) AS end_date, is_expansion
FROM unioned;

-- 5. CONSUMPTION (entitlement x active month, behavior-driven util)
CREATE OR REPLACE TABLE `panw-502122.panw_adoption.consumption` AS
WITH months AS (SELECT m FROM UNNEST(GENERATE_DATE_ARRAY(DATE '2025-07-01', DATE '2026-06-01', INTERVAL 1 MONTH)) AS m),
ent AS (SELECT e.entitlement_id, e.cust_id, e.product_id, e.licensed_amount, e.start_date, e.end_date, e.is_expansion, c.behavior_profile
        FROM `panw-502122.panw_adoption.entitlements` e JOIN `panw-502122.panw_adoption.customers` c USING(cust_id)),
active AS (SELECT ent.*, mo.m, DATE_DIFF(mo.m, ent.start_date, MONTH) AS idx
           FROM ent CROSS JOIN months mo WHERE mo.m >= ent.start_date AND mo.m < ent.end_date),
u AS (SELECT *, ABS(FARM_FINGERPRINT('util-'||entitlement_id||'-'||CAST(m AS STRING))) AS hu,
      ABS(FARM_FINGERPRINT('noise-'||entitlement_id||'-'||CAST(m AS STRING))) AS hn FROM active),
calc AS (SELECT entitlement_id, cust_id, product_id, m AS month, licensed_amount, idx, is_expansion,
   CASE behavior_profile WHEN 'shelfware' THEN 0.0 WHEN 'overage' THEN 1.2+MOD(hu,40)/100.0
        WHEN 'spike_drop' THEN IF(idx<3, 3.0+MOD(hu,100)/100.0, 0.0)
        ELSE LEAST(1.05, GREATEST(0.15, 0.5+MOD(hu,55)/100.0)) END AS util,
   (0.9+MOD(hn,20)/100.0) AS noise FROM u)
SELECT FORMAT('U%06d', ROW_NUMBER() OVER (ORDER BY entitlement_id, month)) AS consumption_id,
  entitlement_id, cust_id, product_id, month,
  ROUND(licensed_amount*(CASE WHEN is_expansion THEN util*LEAST(1.0,0.4+0.12*idx) ELSE util END)*noise,2) AS consumed_units,
  licensed_amount FROM calc;

-- 6. FEATURE_ADOPTION (entitlement x feature x active month, behavior-driven events)
CREATE OR REPLACE TABLE `panw-502122.panw_adoption.feature_adoption` AS
WITH months AS (SELECT m FROM UNNEST(GENERATE_DATE_ARRAY(DATE '2025-07-01', DATE '2026-06-01', INTERVAL 1 MONTH)) AS m),
ent AS (SELECT e.entitlement_id, e.cust_id, e.product_id, e.start_date, e.end_date, c.behavior_profile
        FROM `panw-502122.panw_adoption.entitlements` e JOIN `panw-502122.panw_adoption.customers` c USING(cust_id)),
ef AS (SELECT ent.entitlement_id, ent.cust_id, ent.product_id, ent.start_date, ent.end_date, ent.behavior_profile,
       ff.feature_id, ff.expected_active_volume FROM ent JOIN `panw-502122.panw_adoption._features_full` ff USING(product_id)),
ef_rank AS (SELECT *,
   MOD(ABS(FARM_FINGERPRINT('ad-'||entitlement_id||'-'||feature_id)),100) AS adopt_roll,
   MOD(ABS(FARM_FINGERPRINT('as-'||entitlement_id||'-'||feature_id)),6) AS adopt_start_raw FROM ef),
expanded AS (SELECT r.*, mo.m, DATE_DIFF(mo.m, r.start_date, MONTH) AS idx,
   ABS(FARM_FINGERPRINT('ev-'||r.entitlement_id||'-'||r.feature_id||'-'||CAST(mo.m AS STRING))) AS he
   FROM ef_rank r CROSS JOIN months mo WHERE mo.m >= r.start_date AND mo.m < r.end_date),
withlen AS (SELECT *, COUNT(*) OVER (PARTITION BY entitlement_id, feature_id) AS active_len FROM expanded),
evt AS (SELECT cust_id, entitlement_id, product_id, feature_id, m,
   LEAST(adopt_start_raw, GREATEST(0, active_len-1)) AS adopt_start, idx, behavior_profile, adopt_roll, he, expected_active_volume FROM withlen)
SELECT FORMAT('A%07d', ROW_NUMBER() OVER (ORDER BY entitlement_id, feature_id, m)) AS adoption_id,
  cust_id, entitlement_id, product_id, feature_id, m AS month,
  CASE WHEN behavior_profile='shelfware' THEN 0
    WHEN behavior_profile='spike_drop' THEN IF(adopt_roll<70 AND idx<3, CAST(ROUND(expected_active_volume*(0.25+MOD(he,85)/100.0)) AS INT64), 0)
    WHEN behavior_profile='overage' THEN IF(adopt_roll<85 AND idx>=adopt_start, CAST(ROUND(expected_active_volume*(0.8+MOD(he,50)/100.0)) AS INT64), 0)
    ELSE IF(adopt_roll<60 AND idx>=adopt_start, CAST(ROUND(expected_active_volume*(0.25+MOD(he,85)/100.0)) AS INT64), 0)
  END AS usage_events
FROM evt;

-- clean up internal staging table (only needed during generation above)
DROP TABLE IF EXISTS `panw-502122.panw_adoption._features_full`;
