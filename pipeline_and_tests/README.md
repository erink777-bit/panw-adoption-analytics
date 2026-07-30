# Pipeline & Tests

dbt-style SQL that transforms the six raw BigQuery tables into the Value Realization Score (VRS)
metric marts, plus automated data-quality tests. Runs against `panw-502122.panw_adoption`.

Visual lineage: `../docs/vrs_pipeline_dataflow.svg` (gray = raw, blue = view, green = mart).

## Model DAG (run order)

```
raw: customers, products, entitlements, features, consumption, feature_adoption
                       │
     ┌─────────────────┴───────────────────┐
     ▼                                      ▼
stg_sku_month                        stg_feature_month
(overlap-resolved LUR)               (0/0.3/0.7/1.0 feature score)
     │                                      │
     └───────────────┬──────────────────────┘
                     ▼
             int_sku_components
     (util_health, feature_adoption, sustained_usage, prior_lur)
                     │
                     ▼
          mart_customer_sku_month  ◄── the headline table: VRS + state + guardrail flags
             │            │
             ▼            ▼
   mart_customer_month   mart_product_month   (ARR-weighted roll-ups + dollars-at-risk)

   mart_customer_feature_month  ◄── built from stg_feature_month (dashboard drill-down)
```

Run the files in `models/` in this order: `stg_sku_month` → `stg_feature_month` →
`int_sku_components` → `mart_customer_sku_month` → `mart_customer_feature_month` →
`mart_customer_month` → `mart_product_month`. (Staging + intermediate are views, so they're
free to rebuild; the four marts are tables.)

## What each layer does

- **staging** — cleans/reshapes raw tables. `stg_sku_month` resolves overlapping entitlements
  (mid-year expansions) by summing concurrently-active consumed + licensed amounts before dividing.
- **intermediate** — `int_sku_components` computes three of the four VRS components and the
  trailing-LUR signal used by the churn rule.
- **marts** — `mart_customer_sku_month` adds Time to Value, the composite VRS, the state machine,
  and the guardrail flags; the roll-ups are ARR-weighted.

## Validation (verified against ground-truth `behavior_profile`)

| Behavior | Correctly classified |
|---|---|
| shelfware (10) | 10/10 → **Shelfware Risk** state (never active) |
| overage (15) | 15/15 → **Value Realized** state + **expansion** flag |
| spike-drop (5) | 5/5 → **Churn Signal** during collapse, then **Lapsed** (not shelfware) |
| normal (70) | 0 false flags |

`state` is a single mutually-exclusive label (priority ladder, most-specific first). Guardrail
`flag_*` columns are orthogonal signals that fire even on healthy accounts (single-feature
dependency, expansion). `ever_active_before` separates a churned/Lapsed SKU from true shelfware.

Overlap resolution verified on the mid-year-expansion accounts: licensed amount steps up to the
sum of both active contracts in the overlap window; LUR is scored against the combined entitlement
(no double-count, no dropped contract).

## Data-quality tests (`tests/`)

`tests/dq_tests.sql` is a self-contained harness — 36 assertions across eight categories (integrity, overlap, anomaly detection, ground truth, schema, unit, regression, freshness), each returning `PASS`/`FAIL`. `tests/run_tests.py` additionally runs a non-fatal cross-environment parity check comparing the live BigQuery mart against the offline CSV build (row count, VRS and ARR checksums).
`tests/run_tests.py` executes it against BigQuery and exits non-zero on any failure (CI-ready).

| Category | Covers |
|---|---|
| integrity (10) | no orphan foreign keys, unique SKU-month grain, VRS ∈ 0–100, components ∈ 0–1, no negative/zero license, 12 months present, every entitlement has consumption |
| overlap (2) | overlapping entitlement pairs exist; `stg_sku_month.licensed_amount` equals the summed concurrently-active licenses (overlap-resolution oracle) |
| anomaly (5) | shelfware = 10 accounts → all Shelfware Risk; overage = 15 → all raise expansion flag; churn = 5 customers |
| ground_truth (1) | "normal" accounts never hit a risk state or expansion flag (no false positives) |

Current status: **18/18 PASS.**

```bash
pip install google-cloud-bigquery && python tests/run_tests.py
```
