# Data Generation

Generates a reproducible, PANW-style synthetic dataset backing the Value Realization Score (VRS)
framework (see `/specs/product_and_technical_spec.md`).

## Generators

| File | Stack | Purpose |
|---|---|---|
| `generate_data.py` | **Faker + pandas + numpy** | Reference generator; writes CSVs to `./output/`. Faker = cosmetic fields (names, regions); numpy = the usage/anomaly modeling; pandas = table assembly. |
| `bq_generate.sql` | BigQuery SQL | What actually populated the BigQuery sandbox. The sandbox can't read local CSVs and restricts DML, so the same dataset is generated in-warehouse with `GENERATE_ARRAY` + `CREATE TABLE AS`. |

Both produce the **same schema and the same anomaly rates**. `SEED=42` in the Python script makes the RNG deterministic (identical output for a given seed). The SQL version
gets the same reproducibility from hashing fixed strings with `FARM_FINGERPRINT` instead of a numeric seed.

## Run

```bash
# Python reference generator (CSVs)
pip install faker pandas numpy && python generate_data.py

# BigQuery-native generation (populates panw-502122.panw_adoption)
# run bq_generate.sql top to bottom via the BigQuery console or bq CLI
```

## Tables produced

Downstream, the pipeline (`/pipeline_and_tests`) transforms these six raw tables through two
staging views and one intermediate view into the four mart tables the dashboard reads.

| Table | ~Rows | Notes |
|---|---|---|
| `customers` | 100 | Customer master (+ hidden `behavior_profile` ground-truth label) |
| `products` | 500 | Product catalog (includes `product_platform`, `unit_of_measure`) |
| `entitlements` | ~470–480 | Contract entitlements (includes `unit_price`, `arr` for ARR-weighted roll-ups) |
| `features` | ~2,250 | Feature catalog (includes `meaningful_floor_events`, `deep_threshold_events`) |
| `consumption` | ~5,400 | Monthly consumption per entitlement |
| `feature_adoption` | ~24–25k | Monthly usage events per feature |

**Feature thresholds** (`meaningful_floor_events`, `deep_threshold_events`) are columns on the
`features` table. They are the per-feature cutoffs the Feature Adoption metric needs:
`meaningful_floor_events = 0.20 × expected_active_volume` (below this a feature is "enabled but idle")
and `deep_threshold_events = 0.80 × expected_active_volume` (at/above this it is "deeply used"), where
`expected_active_volume` is the feature's typical monthly event count under healthy use: a per-feature-type baseline from the feature catalog (e.g., URL-filtering events vs. VPN session events differ by orders of magnitude), varied ±40% per product instance at generation. In production this benchmark would be derived from observed telemetry — for example, the median monthly event volume among actively-using customers of that feature.

**Deployment and value-realization metrics are computed, not synthesized.** Time to
Value (deployment) and VRS (value realization) are calculated by the Phase 2b pipeline from consumption,
feature adoption, and entitlements — they are the pipeline's `mart_*` output tables, not raw generated
input. Generating them as raw inputs would remove the ability to measure them independently.

## Key modeling decision

`licensed_amount` is a **monthly** entitlement quantity in the SKU's `unit_of_measure`
(credits / device_license / seats / usage_units), so `LUR = consumed / licensed_amount` is a clean
monthly ratio across every form factor.

## Injected anomalies (rates verified at generation)

| Anomaly | Rate | Signature |
|---|---|---|
| Shelfware | 10% | zero consumption across the account |
| Consistent overage | 15% | monthly LUR 1.2–1.6 sustained |
| Spike & drop | 5% | LUR ~3–4 in months 1–3, then 0. (LUR here = consumed ÷ *monthly* license, so 3–4× means ~90% of the annual entitlement burned in the first quarter, then flatline.) |
| Mid-year expansion | 6 accounts | second, larger contract with overlapping active entitlement dates |
| Slow onboarder | 5% | dark for ~2 months, first meaningful use in month 3 (TTV ~0.47 — exercises the 31–90-day partial band and the **Onboarding Stall** state), features light up later |

`behavior_profile` on the customer table is **ground truth for validating the Phase 2c tests only** —
the pipeline and detection tests operate on the raw data and never read this label.
