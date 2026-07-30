# Value Realization Score (VRS) — Product Adoption Analytics

A working prototype of a product-adoption North Star for a recurring-revenue,
consumption-based security business. One 0–100 score per customer × SKU × month —
built from License Utilization, Feature Adoption, Sustained Usage, and Time to
Value — with states and guardrail flags that route every account to an owner and
a play. Built spec-first with AI coding tools: the Markdown spec is the contract,
and 36 automated data-quality tests enforce it against a live BigQuery instance.

## Repository Map

| Path | Contents |
|---|---|
| `/data_generation` | Python scripts that generate the synthetic dataset (`generate_data.py`, seeded and reproducible), the generated CSVs in `output/`, and `bq_generate.sql` (the in-warehouse variant used to seed the BigQuery sandbox). Four anomaly behaviors — spike & drop, shelfware, consistent overage, mid-year expansion — are injected at known rates as hidden ground truth, plus a slow-onboarder profile. |
| `/specs` | The Markdown product & technical specification (`product_and_technical_spec.md`): the North Star formula, component definitions, thresholds, state machine, edge-case handling, and open decisions for leadership. |
| `/pipeline_and_tests` | The metric pipeline and its tests. `models/` holds dbt-style BigQuery SQL (2 staging views → 1 intermediate view → 4 marts). `tests/dq_tests.sql` is the 36-assertion data-quality harness (unit, data quality, schema, source-to-target integrity, regression checksums, freshness, anomaly detection, false-positive checks); `tests/run_tests.py` executes it against BigQuery, adds a non-fatal cross-environment parity check against the offline CSV build, and exits non-zero on any failure. |
| `/dashboard` | The Streamlit visualization prototype (`app.py`): Portfolio, Actions, By Customer, and By Product views over the VRS marts. Runs live against BigQuery or fully offline from bundled CSVs — identical numbers either way. |
| `/docs` | Supporting documentation: per-metric definitions for every number on the dashboard, the pipeline lineage diagram (SVG), and executive-deck notes with independently verified figures. |
| `executive_presentation.pptx / .pdf` | The executive presentation (Palo Alto Networks corporate template). |

## Running the Dashboard Locally

Requires Python 3.10+.

**Windows, one click:** open `/dashboard` and double-click `run_dashboard.bat`.
It installs requirements on first run and opens the app at `http://localhost:8501`.
Keep the console window open while using the dashboard.

**Any platform, manually:**

```bash
cd dashboard
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

The app is BigQuery-first: on startup it connects live to
`panw-502122.panw_adoption` and queries the marts directly. If no Google
credentials are present it falls back to `dashboard/data/*.csv` — offline
exports of the same marts, verified identical — so reviewers can run it with
zero cloud setup. A sidebar badge shows the active mode.

**To enable the live BigQuery connection (one-time):** double-click
`dashboard/connect_bigquery.bat`. It installs the Google Cloud SDK if needed,
signs you in (`gcloud auth application-default login`), and relaunches the
dashboard in live mode.

## Regenerating Data and Running Tests

```bash
# Regenerate the synthetic dataset (seeded — reproducible)
cd data_generation && python generate_data.py

# Rebuild the offline marts the dashboard reads
cd ../dashboard && python build_local_data.py

# Run the 36 data-quality tests against BigQuery (CI-ready)
pip install google-cloud-bigquery
python ../pipeline_and_tests/tests/run_tests.py
```
