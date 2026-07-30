# Executive presentation — asset & talking-point notes

Running notes for the Phase 3 deck. Visuals earmarked to reuse:

- **`docs/vrs_pipeline_dataflow.svg`** — the pipeline lineage (raw → staging views → intermediate → marts).
  Use on the "how we built it, AI-first + spec-driven" / methodology slide. Simplify labels to plain
  language for the exec version (hide the `stg_*`/`int_*` model names).
- **Customer-journey diagram** (purchase → entitlement → [TTV gate] → in-production: utilization +
  feature adoption + sustained usage → VRS) — use on the "what the metric measures" slide.
  Regenerate as a standalone SVG for the deck.

## Verified numbers (single source of truth for the deck)

Independently recomputed from the raw CSVs after the slow-onboarder injection.
Scope: **June 2026 snapshot, offline CSV build, simple (unweighted) mean for signal averages** —
quote this scope consistently. ⚠️ BigQuery currently holds a *different* generated dataset
(bq_generate.sql ran independently); resync BQ before citing any live-BQ number or demoing in BQ mode.

- **Portfolio:** Total ARR **$146.5M** · ARR at risk **$28.4M (19.4%)** · portfolio VRS **70.2** (ARR-weighted)
- **At-risk ARR by platform:** SASE **$14.3M (27%)** · Hardware **$12.8M (15% of $86.1M)** ·
  Cloud **$0.7M (19%)** · Software **$0.6M (14%)**. 100% of at-risk ARR = Shelfware ($16.4M) + Lapsed ($12.0M).
- **Anomaly footprint ($M ARR — Shelfware / Spike & Drop / Overage):** Hardware 7.9 / 4.9 / **13.5** ·
  SASE 7.6 / 6.7 / 5.8 · Cloud 0.5 / 0.2 / 0.2 · Software 0.4 / 0.3 / 0.8
- **Overage / upsell pool: $20.3M ARR across 15 customers** — hardware is $13.5M = **66%** of it.
  (Corrects earlier working figures of "$13.5M of $15M" and "14 customers".)
- **Signal averages (Jun-26):** License Utilization **0.75** · Feature Adoption **0.46** ·
  Sustained Usage **0.83** · Time to Value **0.86** (TTV reflects the slow-onboarder profile; pre-injection it was 0.89)
- **Hardware risk concentration:** PA-5410 + PA-5445 + PA-410 = **53%** of hardware at-risk ARR
- **Cloud split:** Cloud NGFW for Azure VRS **60** vs AWS **76**
- **Slow onboarders (new, 5 accounts):** dark ~2 months → activate month 3 (TTV 0.47, the 31–90-day
  partial band) → features later. Lifecycle: Grace Period → Shelfware Risk → **Onboarding Stall** → Value Realized.

Key talking points to carry into the deck:
- One North Star (VRS), four plain questions: how deep / how broad / how durable / how fast.
- The four anomalies a naive utilization metric misreads, and how VRS catches each.
- States vs. guardrail flags; ARR-weighted roll-ups and dollars-at-risk (VRS < 50).
- Incentive design: measure teams on Value-Realized % and net state transitions, not raw consumption.
- PANW fit: consumption/credit model + modular CDSS = the business model VRS already measures.
