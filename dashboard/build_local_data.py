"""
Build the VRS marts locally (DuckDB) from the raw CSVs, so the dashboard can run
with NO cloud auth. Produces two denormalized files the app reads in offline mode:
    data/mart_sku_month_full.csv     (customer x product x month + names/segment/platform)
    data/mart_feature_full.csv       (feature-level detail)

This mirrors the BigQuery pipeline models exactly (same formulas / states / flags),
just ported to DuckDB SQL. Run:  python build_local_data.py
"""
import os
import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "..", "data_generation", "output")
OUT = os.path.join(HERE, "data")
os.makedirs(OUT, exist_ok=True)

con = duckdb.connect()
for t in ["customers", "products", "entitlements", "features", "consumption", "feature_adoption"]:
    con.execute(f"CREATE TABLE {t} AS SELECT * FROM read_csv_auto('{os.path.join(RAW, t + '.csv')}')")

con.execute("""CREATE VIEW stg_sku_month AS
  SELECT cust_id, product_id, month, SUM(consumed_units) consumed_units,
         SUM(licensed_amount) licensed_amount,
         SUM(consumed_units)/NULLIF(SUM(licensed_amount),0) lur
  FROM consumption GROUP BY 1,2,3""")

con.execute("""CREATE VIEW stg_feature_month AS
  WITH agg AS (SELECT cust_id,product_id,feature_id,month,SUM(usage_events) usage_events
               FROM feature_adoption GROUP BY 1,2,3,4)
  SELECT a.cust_id,a.product_id,a.feature_id,a.month,f.feature_name,a.usage_events,
    CASE WHEN a.usage_events=0 THEN 0.0
         WHEN a.usage_events<f.meaningful_floor_events THEN 0.3
         WHEN a.usage_events<f.deep_threshold_events THEN 0.7 ELSE 1.0 END feature_score
  FROM agg a JOIN features f USING(feature_id)""")

con.execute("""CREATE VIEW int_sku_components AS
  WITH fa AS (SELECT cust_id,product_id,month,AVG(feature_score) feature_adoption
              FROM stg_feature_month GROUP BY 1,2,3),
  base AS (
    SELECT s.cust_id,s.product_id,s.month,s.lur, COALESCE(fa.feature_adoption,0) feature_adoption,
      CASE WHEN s.lur<0.10 THEN 0.0 WHEN s.lur<0.60 THEN 0.3+(s.lur-0.10)*1.2
           WHEN s.lur<1.00 THEN 0.9+(s.lur-0.60)*0.25 WHEN s.lur<=1.20 THEN 1.0 ELSE 0.8 END util_health,
      CASE WHEN s.lur>=0.10 THEN 1 ELSE 0 END active
    FROM stg_sku_month s LEFT JOIN fa USING(cust_id,product_id,month)),
  sus AS (
    SELECT *, LAG(active,1) OVER w a1, LAG(active,2) OVER w a2,
      AVG(lur) OVER (PARTITION BY cust_id,product_id ORDER BY month ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) prior_lur,
      MAX(active) OVER (PARTITION BY cust_id,product_id ORDER BY month ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) ever_active_before
    FROM base WINDOW w AS (PARTITION BY cust_id,product_id ORDER BY month))
  SELECT cust_id,product_id,month,lur,util_health,feature_adoption,
    (0.5*active+0.3*COALESCE(a1,0)+0.2*COALESCE(a2,0))
      /(0.5+CASE WHEN a1 IS NULL THEN 0 ELSE 0.3 END+CASE WHEN a2 IS NULL THEN 0 ELSE 0.2 END) sustained_usage,
    prior_lur, COALESCE(ever_active_before,0) ever_active_before
  FROM sus""")

con.execute("""CREATE TABLE mart_customer_sku_month AS
  WITH ent_start AS (SELECT cust_id,product_id,MIN(CAST(start_date AS DATE)) start_date,SUM(arr) arr
                     FROM entitlements GROUP BY 1,2),
  firstval AS (SELECT cust_id,product_id,MIN(month) first_value_month
               FROM stg_sku_month WHERE lur>=0.10 GROUP BY 1,2),
  pf AS (SELECT DISTINCT product_id FROM features),
  ttv AS (
    SELECT e.cust_id,e.product_id,e.arr,e.start_date,
      date_diff('day', e.start_date, CAST(fv.first_value_month AS DATE)) ttv_days,
      CASE WHEN fv.first_value_month IS NULL THEN 0.0
        WHEN date_diff('day', e.start_date, CAST(fv.first_value_month AS DATE))<=30 THEN 1.0
        WHEN date_diff('day', e.start_date, CAST(fv.first_value_month AS DATE))<=90
          THEN 1-(date_diff('day', e.start_date, CAST(fv.first_value_month AS DATE))-30)/60.0
        ELSE 0.0 END ttv_score
    FROM ent_start e LEFT JOIN firstval fv USING(cust_id,product_id)),
  scored AS (
    -- has_features: spec 4.2 graceful degradation - a SKU with no separately-adoptable
    --   features drops the Feature Adoption term and renormalizes the remaining weights.
    -- grace: spec 4.4 grace period - the SKU's first calendar month with no meaningful
    --   use yet drops the TTV term (renormalized) so a brand-new account is not punished.
    SELECT c.*, t.ttv_score,t.arr,
      (pf.product_id IS NOT NULL) has_features,
      (date_trunc('month', t.start_date) = CAST(c.month AS DATE) AND c.util_health = 0) grace,
      100*( 0.35*c.util_health
          + CASE WHEN pf.product_id IS NOT NULL THEN 0.25*c.feature_adoption ELSE 0 END
          + 0.25*c.sustained_usage
          + CASE WHEN date_trunc('month', t.start_date) = CAST(c.month AS DATE) AND c.util_health = 0
                 THEN 0 ELSE 0.15*t.ttv_score END )
       /( 0.35 + CASE WHEN pf.product_id IS NOT NULL THEN 0.25 ELSE 0 END + 0.25
          + CASE WHEN date_trunc('month', t.start_date) = CAST(c.month AS DATE) AND c.util_health = 0
                 THEN 0 ELSE 0.15 END ) vrs
    FROM int_sku_components c JOIN ttv t USING(cust_id,product_id)
    LEFT JOIN pf ON pf.product_id = c.product_id)
  SELECT cust_id,product_id,month, round(lur,3) lur, round(util_health,3) util_health,
    CASE WHEN has_features THEN round(feature_adoption,3) END feature_adoption,
    round(sustained_usage,3) sustained_usage,
    CASE WHEN grace THEN NULL ELSE round(ttv_score,3) END ttv_score,
    ever_active_before, arr, round(vrs,1) vrs,
    (has_features AND feature_adoption<0.25 AND lur>=0.9) flag_single_feature_dependency,
    (lur>1.2) flag_expansion,
    CASE WHEN grace THEN 'Grace Period'
      WHEN COALESCE(prior_lur,0)>=0.6 AND sustained_usage<0.34 THEN 'Churn Signal'
      WHEN util_health=0 AND ever_active_before=1 THEN 'Lapsed'
      WHEN util_health=0 THEN 'Shelfware Risk'
      WHEN ttv_score<0.5 AND feature_adoption<0.3 THEN 'Onboarding Stall'
      WHEN vrs>=70 THEN 'Value Realized' WHEN vrs>=50 THEN 'Developing'
      WHEN vrs>=30 THEN 'At Risk' ELSE 'Critical' END state
  FROM scored""")

con.execute(f"""COPY (
  SELECT m.*, c.cust_name,c.segment,c.region,p.product_name,p.product_platform
  FROM mart_customer_sku_month m JOIN customers c USING(cust_id) JOIN products p USING(product_id)
) TO '{os.path.join(OUT, 'mart_sku_month_full.csv')}' (HEADER)""")

con.execute(f"""COPY (
  SELECT cust_id,product_id,month,feature_name,usage_events,feature_score,
    CASE feature_score WHEN 0.0 THEN 'not_enabled' WHEN 0.3 THEN 'enabled_idle'
         WHEN 0.7 THEN 'active' ELSE 'deep' END adoption_level
  FROM stg_feature_month
) TO '{os.path.join(OUT, 'mart_feature_full.csv')}' (HEADER)""")

dist = con.execute("SELECT state, COUNT(DISTINCT cust_id) c FROM mart_customer_sku_month GROUP BY 1 ORDER BY 2 DESC").fetchall()
print("built local marts ->", OUT)
print("state distribution (customers):", dict(dist))
