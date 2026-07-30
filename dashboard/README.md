# Dashboard

A lightweight Streamlit app over the VRS marts — lets an exec view adoption performance by
**Customer** and by **Product**, with portfolio VRS and dollars-at-risk headlined.

## Two data modes (auto-detected)

- **BigQuery (live):** if Google credentials are available, it queries `panw-502122.panw_adoption`.
- **Local (offline):** otherwise it reads `data/*.csv` — **no cloud auth needed.** The sidebar
  shows which mode is active. The offline CSVs are pre-built and committed, so the app runs
  out of the box.

## Run

Install deps and launch (run the lines **separately** — Windows PowerShell doesn't support `&&`):

```powershell
cd dashboard
pip install -r requirements.txt
streamlit run app.py
```

That's it — it opens in your browser and runs in offline mode with no login. It will *automatically*
switch to live BigQuery if you later set up credentials (`gcloud auth application-default login`,
or point `GOOGLE_APPLICATION_CREDENTIALS` at a service-account key). No code change needed.

To regenerate the offline CSVs from the raw data (only needed if the data changes):

```powershell
pip install duckdb
python build_local_data.py
```

## Layout

**Sidebar filters:** month (defaults to latest), segment, region, product platform; plus a data-source badge.

**▶ Actions tab** (landing tab — the action-oriented view): every state/flag rendered as a **play** with
an owner, a recommended action, ARR at stake, and an ARR-prioritized account worklist. Headline metrics:
ARR to defend, ARR to expand, accounts needing action. Plays: Save (Churn), Activate (Shelfware),
Win back (Lapsed), Deploy (Onboarding Stall), Upsell (overage flag), Broaden adoption (single-feature flag).

**Portfolio tab**: portfolio VRS (ARR-weighted), total ARR, ARR-at-risk (VRS < 50) with %, customers,
customers-at-risk, SKUs-at-risk; a **KPI movement** table (each KPI vs last month and last quarter);
ARR-by-state bar + table (ARR / SKUs / customers per state); portfolio VRS trend over 12 months.

**By Customer tab:** leaderboard sorted by dollars-at-risk (worst first) → drill into a customer's
SKUs → feature-level detail for a SKU.

**By Product tab:** VRS by platform (the product-GM view) + top individual products by dollars-at-risk.

All roll-ups are ARR-weighted, matching the pipeline (`SUM(vrs*arr)/SUM(arr)`).
