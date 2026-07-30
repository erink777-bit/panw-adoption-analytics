# Dashboard Metric Definitions

Definitions and calculations for every metric shown in the VRS adoption dashboard.
Grain of the base record is **customer × product (SKU) × month**; "SKU" = a customer's
entitlement to a product. Full detail is in `specs/product_and_technical_spec.md`.

---

## 1. The North Star

### VRS — Value Realization Score
**What it answers:** overall, is this customer getting the value they paid for on this SKU?
**Calculation:** a 0–100 weighted blend of four components (each normalized 0–1):

```
VRS = 100 × ( 0.35·Utilization + 0.25·FeatureAdoption
            + 0.25·SustainedUsage + 0.15·TimeToValue )
```

**Range / bands:** 0–100. ≥70 Value Realized · 50–69 Developing · 30–49 At Risk · <30 Critical.

---

## 2. The four components (each 0–1)

### Utilization (`util_health`)
**Answers:** how much of what they bought are they consuming? (depth)
**Input:** `LUR = consumed_units ÷ licensed_amount` (see LUR below).
**Calculation:** a non-linear curve on LUR that penalizes both under- and over-use:

| LUR | util_health |
|---|---|
| < 0.10 | 0.0 (shelfware) |
| 0.10–0.60 | 0.3 → 0.9 (ramp: `0.3 + (LUR−0.10)×1.2`) |
| 0.60–1.00 | 0.9 → 1.0 (ramp: `0.9 + (LUR−0.60)×0.25`) |
| 1.00–1.20 | 1.0 (peak) |
| > 1.20 | 0.8 (overage cap) |

### Feature Adoption (`feature_adoption`)
**Answers:** how broadly and deeply are the SKU's features used? (breadth + depth)
**Calculation:** the **average of `feature_score` across all of that SKU's entitled features** (see feature_score in §5). Un-adopted features count as 0, so this captures breadth.
**Range:** 0–1.

### Sustained Usage (`sustained_usage`)
**Answers:** is usage durable, or did it spike and drop? (durability)
**Calculation:** a recency-weighted average of the "active" flag over the trailing 3 months, where `active = 1 if LUR ≥ 0.10 that month, else 0`:

```
sustained_usage = (0.5·active[m] + 0.3·active[m−1] + 0.2·active[m−2])
                / (sum of the weights that exist)      # renormalized for early months
```

**Range:** 0–1. All three months active → 1.0; only the oldest active (spike-then-drop) → 0.2; none → 0.0.

### Time to Value (`ttv_score`)
**Answers:** how fast did the SKU reach first meaningful use after deployment? (speed)
**Input:** `ttv_days = date(first month LUR ≥ 0.10) − entitlement start date`.
**Calculation:**

| ttv_days | ttv_score |
|---|---|
| ≤ 30 | 1.0 |
| 31–90 | `1 − (ttv_days − 30) ÷ 60` (1.0 → 0.0) |
| > 90, or never reached | 0.0 |

**Range:** 0–1. (Constant per SKU across its months.)
**Grace period:** in a SKU's **first calendar month with no meaningful use yet**, TTV is not judged —
`ttv_score` is null, the remaining weights are renormalized (0.35/0.25/0.25 rescaled to sum to 1),
and the state resolves to **Grace Period** instead of Shelfware Risk.
**Feature-less SKUs:** if a product carries no separately-adoptable features, `feature_adoption` is
null and its 25% weight is likewise renormalized away (spec §4.2 graceful degradation).

---

## 3. SKU-level fields (Customer drill-down)

### LUR (`lur`) — License Utilization Rate
**Calculation:** `SUM(consumed_units) ÷ SUM(licensed_amount)` for that customer × product × month. The sums combine all **concurrently-active entitlements** (this resolves mid-year expansions — two overlapping contracts are summed, not double-counted). `licensed_amount` is a monthly entitlement quantity in the SKU's unit (credits / device-licenses / seats / usage-units).

### state
**What it is:** one mutually-exclusive label per SKU-month, resolved by a **priority ladder** (most specific / urgent first; first match wins):

| Priority | state | Rule |
|---|---|---|
| 0 | Grace Period | first calendar month of the SKU, no meaningful use yet — too new to judge |
| 1 | Churn Signal | `prior_lur ≥ 0.6 AND sustained_usage < 0.34` (recent collapse) |
| 2 | Lapsed | `util_health = 0 AND ever_active_before = 1` (was active, now dead) |
| 3 | Shelfware Risk | `util_health = 0 AND ever_active_before = 0` (never activated) |
| 4 | Onboarding Stall | `ttv_score < 0.5 AND feature_adoption < 0.3` (slow + shallow deploy) |
| 5–8 | Value Realized / Developing / At Risk / Critical | VRS ≥ 70 / ≥ 50 / ≥ 30 / else |

Supporting signals used only by the state rules: `prior_lur` = trailing-3-month average LUR (recent history); `ever_active_before` = 1 if the SKU was ever active in any prior month (lifetime memory that separates a churned/Lapsed SKU from true shelfware).

### Guardrail flags (independent booleans — fire even on healthy SKUs)
These catch a risk/opportunity the composite VRS and the state can mask:

| Flag | Rule | Meaning |
|---|---|---|
| `flag_expansion` | `LUR > 1.20` | over-consuming — a Sales upsell (a SKU can be Value Realized *and* flagged) |
| `flag_single_feature_dependency` | `feature_adoption < 0.25 AND lur ≥ 0.9` | genuinely heavy usage but almost no features live — healthy-looking yet fragile. Gated on **raw LUR** (not the scored util_health) so overage SKUs (>1.2×, score capped at 0.8) are still caught; such SKUs carry both this flag and `flag_expansion` |

### arr — Annual Recurring Revenue (per SKU)
`SUM(units_purchased × unit_price)` across the SKU's entitlements, annualized. Drives all ARR-weighted roll-ups and dollars-at-risk.

---

## 4. Roll-ups & portfolio KPIs

### ARR-weighted VRS (customer / product / platform / portfolio)
**Answers:** the aggregate score, weighted so dollars matter more than SKU count.
**Calculation:** `Σ(SKU_vrs × SKU_arr) ÷ Σ(SKU_arr)` over the SKUs in the group (a customer, a product, a platform, or the whole portfolio). A plain average is shown alongside on the customer roll-up for contrast.

### Total ARR
`Σ(SKU arr)` over the filtered set.

### ARR at risk (`ARR_at_risk`)
**Answers:** how many dollars are in genuinely troubled SKUs.
**Calculation:** `Σ(arr WHERE VRS < 50)` — **SKU-level**: only the at-risk SKUs' ARR counts, so a customer with one weak SKU and three healthy ones contributes just the weak SKU's dollars. In the "At Risk" band or worse (aligned to the state bands). The KPI also shows it as a **% of Total ARR**.

### Customers
Distinct customer count in the filtered set.

### Customers at risk
**Answers:** how many *accounts* are unhealthy overall (a customer-level view, vs. the SKU-level ARR-at-risk).
**Calculation:** count of distinct customers whose **ARR-weighted VRS < 50** (each customer scored as `Σ(SKU_vrs×SKU_arr)/Σ(SKU_arr)` across their SKUs). Note the grain difference: ARR-at-risk and SKUs-at-risk are SKU-level; Customers and Customers-at-risk are customer-level.

### SKUs at risk
Count of SKU rows (customer × product) with `VRS < 50` in the filtered set. More granular than customers — healthy accounts can still carry an odd at-risk SKU.

### ARR by state (chart + table)
For the selected month, grouped by `state`: `Σ(arr)` (bar), plus a companion table with **SKUs** (row count) and **Customers** (distinct count) per state. A customer with SKUs in multiple states appears under each of those states.

### Portfolio VRS trend (chart)
ARR-weighted VRS per month across the selected filters — the 12-month trajectory.

---

### KPI movement (month-over-month / quarter-over-quarter)
For each headline KPI (Portfolio VRS, ARR at risk, Customers at risk, SKUs at risk), the Portfolio tab
shows the current value plus the change vs. the **prior month** and the **prior quarter** (3 months
back). Computed by recalculating the same KPI for those months and differencing (`current − prior`).
An up-arrow means the value rose vs. the comparison month; for at-risk metrics a decrease (down-arrow)
is the good direction.

## Recommended plays (By Customer tab)

The Recommended plays table turns each state/flag into a **play**: the anomaly it addresses + an owner + a
recommended action + the ARR at stake + an ARR-prioritized account worklist. The four plays map 1:1
to the four injected anomalies (spike-and-drop spans two plays across its lifecycle):

| Play | Addresses (anomaly) | Trigger | Owner | Recommended action |
|---|---|---|---|---|
| Activate | Shelfware | state = Shelfware Risk | Customer Success | drive first deployment, or flag as renewal risk |
| Win back | Spike & drop | state = Churn Signal **or** Lapsed | CS / Account | diagnose why usage stopped; build a save plan |
| Upsell | Consistent overage | `flag_expansion` | Sales | right-size the contract; capture overage revenue |

Notes on the mapping:
- **Win back** covers spike-and-drop across its whole lifecycle — both the acute collapse (Churn Signal)
  and the lapsed tail (Lapsed) — so it's a stable "accounts to win back" list regardless of exactly where
  each account is in its collapse.
- **Mid-year expansion** (the 4th anomaly) has **no play** — it is a healthy growth event handled by the
  pipeline's overlap resolution; if the expanded account over-consumes it surfaces under Upsell.
- Onboarding Stall, Churn Signal vs. Lapsed states, and the single-feature-dependency flag remain defined
  in the framework/spec as finer-grained signals, but the plays table rolls them up to the three plays that
  map 1:1 to the injected anomalies.

Headline metrics on the tab: **ARR to defend** (sum of ARR across the at-risk plays), **ARR to expand**
(ARR of upsell/overage SKUs), and **Accounts needing action** (distinct customers in any play).

## 5. Feature-level fields (feature drill-down)

### usage_events
Raw monthly activity count for a feature on that SKU (e.g. sessions inspected, queries resolved), summed across the customer's concurrent entitlements.

### feature_score (0 / 0.3 / 0.7 / 1.0)
Per-feature adoption depth, from `usage_events` vs. that feature's own thresholds (`meaningful_floor_events`, `deep_threshold_events`, stored on the `features` table):

| Condition | feature_score | adoption_level |
|---|---|---|
| `usage_events = 0` | 0.0 | not_enabled |
| `< meaningful_floor_events` | 0.3 | enabled_idle |
| `< deep_threshold_events` | 0.7 | active |
| `≥ deep_threshold_events` | 1.0 | deep |

Per-feature thresholds: `meaningful_floor_events = 0.20 × expected_active_volume`, `deep_threshold_events = 0.80 × expected_active_volume`, where `expected_active_volume` is that feature's typical healthy monthly volume.

### adoption_level
The plain-language label for `feature_score` (see table above).

---

## 6. Sidebar filters (not metrics)

`Month` (defaults to latest), `Segment` (Enterprise / Mid-Market), `Region` (AMER / EMEA / APAC / LATAM),
`Product platform` (hardware_ngfw / software_ngfw / sase / cloud_ngfw). A badge shows the active data
source (live BigQuery vs. offline CSV). Filters subset every metric on the page.
