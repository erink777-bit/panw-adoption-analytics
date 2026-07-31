# Dashboard

Streamlit application over the VRS marts: portfolio health, product performance, and
customer-level drill-downs. Every roll-up is ARR-weighted to match the pipeline
(`SUM(vrs × arr) / SUM(arr)`).

## Hosted version

A hosted instance runs at https://panw-adoption-analytics.streamlit.app — no installation required.

## Data modes (auto-detected)

- **BigQuery (live):** when Google credentials are present, the app queries
  `panw-502122.panw_adoption` directly.
- **Local (offline):** otherwise it reads the pre-built `data/*.csv` exports committed with the
  repository — verified identical to the BigQuery marts. The sidebar badge shows the active mode.

## Running locally

Requires Python 3.10+ (https://www.python.org/downloads/ — on Windows, select
"Add python.exe to PATH" during installation).

**Windows:** double-click `run_dashboard.bat`. It installs requirements on the first run and opens
the app at http://localhost:8501.

**Any platform:**

```bash
pip install -r requirements.txt
streamlit run dashboard/app.py
```

**Live BigQuery connection (one-time):** run `connect_bigquery.bat`, or
`gcloud auth application-default login`. The app switches to live mode automatically once
credentials are available; no code change is required.

**Regenerating the offline CSVs** (only needed if the raw data changes):

```bash
pip install duckdb
python dashboard/build_local_data.py
```

## Layout

**Sidebar filters:** as-of month (defaults to the latest), segment, region, and product platform.
An empty filter applies no restriction. A badge shows the active data source.

**Portfolio:** headline cards (Portfolio VRS gauge with MoM/QoQ change, Total ARR, ARR at Risk,
Customers at Risk, Expansion ARR); the VRS band key; a 12-month VRS trend; "Where the ARR sits
today" — the current ARR mix across VRS bands with quarter-over-quarter share changes and 12-month
share sparklines; and Top movers — the largest month-over-month VRS changes, actionable accounts
first, each with a recommended play.

**By Product:** platform summary cards (VRS, ARR, ARR at risk); a products table filterable by
platform, sorted by ARR at risk, with inline anomaly counts; selecting a row opens that product's
customer list, worst VRS first.

**By Customer:** ARR at Risk, Expansion ARR, and Accounts Needing Action; a Recommended plays table
(Activate / Win back / Upsell, each with an owner, filterable by play); and a customer drill-down
with per-product License Utilization and VRS trajectories plus feature-level detail.
