"""
Data-quality test runner for the VRS pipeline.

Executes tests/dq_tests.sql against BigQuery and prints a PASS/FAIL table.
Exits non-zero if ANY assertion fails, so it can gate CI / a pre-deploy check.

Usage:
    pip install google-cloud-bigquery
    # auth: `gcloud auth application-default login` (or a service-account key)
    python run_tests.py                       # uses PROJECT below
    python run_tests.py my-other-project      # override project

The 36 fatal assertions cover: referential integrity, grain uniqueness, value
ranges, month coverage, overlap-resolution correctness, detection of all four
injected anomalies (plus slow onboarders), no-false-positives on healthy
accounts, schema (expected columns/types on every table), unit properties of
the scoring curve, regression checksums, and freshness.

After the SQL suite, a NON-FATAL cross-environment parity check compares the
live BigQuery mart against the offline CSV build the dashboard ships with
(row count, VRS checksum, ARR checksum). A mismatch prints a WARNING but does
not fail the run — per practice, cross-env checks are ephemeral and advisory.
"""

import csv
import os
import sys

from google.cloud import bigquery

PROJECT = "panw-502122"
HERE = os.path.dirname(os.path.abspath(__file__))
SQL_FILE = os.path.join(HERE, "dq_tests.sql")
LOCAL_MART = os.path.join(HERE, "..", "..", "dashboard", "data", "mart_sku_month_full.csv")


def run_sql_suite(client) -> int:
    with open(SQL_FILE) as fh:
        sql = fh.read()
    rows = list(client.query(sql).result())

    width = max((len(r["test"]) for r in rows), default=20)
    failures = 0
    print(f"\n{'CATEGORY':<13} {'TEST':<{width}} {'VAL':>5} {'EXP':>5}  RESULT")
    print("-" * (13 + width + 22))
    for r in rows:
        if r["result"] != "PASS":
            failures += 1
        print(f"{r['cat']:<13} {r['test']:<{width}} {r['val']:>5} {r['expect']:>5}  {r['result']}")
    total = len(rows)
    print("-" * (13 + width + 22))
    print(f"{total - failures}/{total} passed"
          + (f"  ({failures} FAILED)" if failures else "  - all green"))
    return failures


def cross_env_parity(client) -> None:
    """Non-fatal: compare the BQ mart vs the offline CSV build (if present)."""
    print("\nCROSS-ENV PARITY (BigQuery vs offline CSV build) - non-fatal")
    if not os.path.exists(LOCAL_MART):
        print("  offline mart not found; skipped")
        return
    n = 0
    vrs_sum = 0.0
    arr_sum = 0.0
    with open(LOCAL_MART, newline="", encoding="utf8") as fh:
        for row in csv.DictReader(fh):
            n += 1
            vrs_sum += float(row["vrs"])
            arr_sum += float(row["arr"])

    bq = list(client.query(
        f"SELECT COUNT(*) n, SUM(vrs) v, SUM(arr) a "
        f"FROM `{PROJECT}.panw_adoption.mart_customer_sku_month`").result())[0]

    checks = [
        ("row count", n, bq["n"], 0),
        ("VRS checksum", vrs_sum, float(bq["v"]), 2.0),
        ("ARR checksum", arr_sum, float(bq["a"]), 5.0),
    ]
    for name, local, remote, tol in checks:
        ok = abs(local - remote) <= tol
        tag = "PARITY OK " if ok else "WARNING   "
        print(f"  {tag} {name}: offline={local:,.1f}  bigquery={remote:,.1f}")


def main(project: str = PROJECT) -> int:
    client = bigquery.Client(project=project)
    failures = run_sql_suite(client)
    cross_env_parity(client)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else PROJECT))
