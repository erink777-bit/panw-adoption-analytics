"""
Synthetic B2B SaaS dataset generator — PANW-style cybersecurity, consumption + recurring revenue.
Backs the Value Realization Score (VRS) framework (see /specs/product_and_technical_spec.md).

Design notes
------------
- pandas builds/relates the tables; numpy models the consumption behavior & anomalies;
  Faker only dresses up cosmetic attributes (customer names, regions). All seeded => reproducible.
- `licensed_amount` is modeled as a MONTHLY entitlement quantity in the SKU's unit_of_measure
  (credits / device_license / seats / usage_units), so LUR = consumed / licensed_amount is a
  clean monthly ratio across every form factor. Documented in the data-gen README.
- Four anomalies are injected at the target rates and each customer carries a hidden
  ground-truth `behavior_profile` so the Phase 2c tests can be validated (labels are NOT read
  by the pipeline — detection works off the raw data).

Outputs: CSVs in ./output/
"""

import os
import numpy as np
import pandas as pd
from faker import Faker

SEED = 42
np.random.seed(SEED)
fake = Faker()
Faker.seed(SEED)

OUT = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUT, exist_ok=True)

# ---------------------------------------------------------------- config
N_CUSTOMERS = 100
N_PRODUCTS = 500
N_MONTHS = 12
MONTHS = pd.period_range(end="2026-06", periods=N_MONTHS, freq="M").to_timestamp()

REGIONS = ["AMER", "EMEA", "APAC", "LATAM"]
SEGMENTS = ["Enterprise", "Mid-Market"]

# product_platform -> (unit_of_measure, units_purchased range, unit_price range $/yr)
PLATFORMS = {
    "hardware_ngfw":  ("device_license", (1, 30),    (8000, 55000)),
    "software_ngfw":  ("credits",        (50, 2000), (28, 35)),
    "sase":           ("seats",          (100, 12000),(40, 130)),
    "cloud_ngfw":     ("usage_units",    (20, 600),  (60, 220)),
}
PLATFORM_WEIGHTS = [0.30, 0.30, 0.25, 0.15]

HARDWARE_MODELS = ["PA-410", "PA-440", "PA-460", "PA-1410", "PA-3410",
                   "PA-3440", "PA-5410", "PA-5445", "PA-7500"]
SOFTWARE_MODELS = ["VM-100", "VM-300", "VM-500", "VM-700", "CN-Series"]
SASE_MODELS = ["Prisma Access Mobile Users", "Prisma Access Remote Networks",
               "Prisma Access Browser"]
CLOUD_MODELS = ["Cloud NGFW for AWS", "Cloud NGFW for Azure"]

# CDSS / capabilities pool -> (relative expected monthly event volume scale)
FEATURE_CATALOG = {
    "Advanced Threat Prevention": 800_000,
    "Advanced WildFire":          120_000,
    "Advanced URL Filtering":     2_000_000,
    "Advanced DNS Security":      5_000_000,
    "IoT/OT Security":            60_000,
    "GlobalProtect":              40_000,
    "Enterprise DLP":             90_000,
    "SaaS Security":              70_000,
    "AI Access Security":         30_000,
    "SD-WAN":                     150_000,
    "App-ID":                     3_000_000,
    "Decryption":                 1_200_000,
}
FEATURE_NAMES = list(FEATURE_CATALOG.keys())

# realistic capability-to-platform mapping (which CDSS/features attach where)
CORE_FEATURES = ["Advanced Threat Prevention", "Advanced WildFire", "Advanced URL Filtering",
                 "Advanced DNS Security", "App-ID", "Decryption"]
PLATFORM_FEATURES = {
    "hardware_ngfw": CORE_FEATURES + ["IoT/OT Security", "GlobalProtect", "Enterprise DLP"],
    "software_ngfw": CORE_FEATURES + ["GlobalProtect", "Enterprise DLP", "IoT/OT Security"],
    "sase":          CORE_FEATURES + ["SD-WAN", "SaaS Security", "AI Access Security",
                                      "Enterprise DLP", "GlobalProtect"],
    "cloud_ngfw":    CORE_FEATURES + ["Enterprise DLP"],
}

# behavior mix across the ~100 accounts (target anomaly rates from the brief,
# plus a slow-onboarder profile to exercise the partial TTV band / Onboarding Stall state)
BEHAVIOR_MIX = {
    "shelfware":      0.10,  # no usage anywhere
    "overage":        0.15,  # consistently >120% of entitlement
    "spike_drop":     0.05,  # burn early then drop to 0
    "slow_onboarder": 0.05,  # dark for ~2 months, activates in month 3 (TTV ~0.47), features later
    "normal":         0.65,
}


# ---------------------------------------------------------------- 1. customers
def make_customers():
    rows = []
    profiles = []
    for name, share in BEHAVIOR_MIX.items():
        profiles += [name] * round(share * N_CUSTOMERS)
    while len(profiles) < N_CUSTOMERS:
        profiles.append("normal")
    profiles = profiles[:N_CUSTOMERS]
    np.random.shuffle(profiles)
    for i in range(N_CUSTOMERS):
        rows.append({
            "cust_id": f"C{i+1:04d}",
            "cust_name": fake.company(),
            "region": np.random.choice(REGIONS, p=[0.45, 0.30, 0.18, 0.07]),
            "segment": np.random.choice(SEGMENTS, p=[0.55, 0.45]),
            "behavior_profile": profiles[i],           # ground-truth (synthetic only)
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 2. products
def make_products():
    rows = []
    for i in range(N_PRODUCTS):
        platform = np.random.choice(list(PLATFORMS.keys()), p=PLATFORM_WEIGHTS)
        uom = PLATFORMS[platform][0]
        if platform == "hardware_ngfw":
            base = np.random.choice(HARDWARE_MODELS)
        elif platform == "software_ngfw":
            base = np.random.choice(SOFTWARE_MODELS)
        elif platform == "sase":
            base = np.random.choice(SASE_MODELS)
        else:
            base = np.random.choice(CLOUD_MODELS)
        rows.append({
            "product_id": f"P{i+1:04d}",
            "product_name": f"{base} SKU-{i+1:04d}",
            "product_platform": platform,
            "unit_of_measure": uom,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 3. features + thresholds
def make_features(products):
    rows, thr = [], []
    fid = 0
    for _, p in products.iterrows():
        pool = PLATFORM_FEATURES[p["product_platform"]]   # only platform-relevant capabilities
        k = min(np.random.randint(3, 7), len(pool))       # 3-6 features per product
        w = np.array([3.0 if nm in CORE_FEATURES else 1.0 for nm in pool]); w = w / w.sum()
        feats = np.random.choice(pool, size=k, replace=False, p=w)  # core CDSS attach more often
        for fname in feats:
            fid += 1
            expected = int(FEATURE_CATALOG[fname] * np.random.uniform(0.6, 1.4))
            feature_id = f"F{fid:05d}"
            rows.append({
                "feature_id": feature_id,
                "feature_name": fname,
                "feature_description": f"{fname} capability delivered within {p['product_name']}",
                "product_id": p["product_id"],
                "_expected_active_volume": expected,   # helper for consumption gen
            })
            thr.append({
                "feature_id": feature_id,
                "meaningful_floor_events": int(0.20 * expected),
                "deep_threshold_events": int(0.80 * expected),
            })
    return pd.DataFrame(rows), pd.DataFrame(thr)


# ---------------------------------------------------------------- 4. entitlements (+ expansions)
def make_entitlements(customers, products):
    rows = []
    eid = 0
    prod_lookup = products.set_index("product_id")
    for _, c in customers.iterrows():
        n_ent = np.random.randint(2, 8)                # ~2-7 SKUs per customer -> ~500
        chosen = products.sample(n_ent)
        for _, p in chosen.iterrows():
            eid += 1
            _, up_rng, price_rng = PLATFORMS[p["product_platform"]]
            units = int(np.random.randint(*up_rng))
            price = round(np.random.uniform(*price_rng), 2)
            # entitlements mostly run the full window; some start staggered
            start = MONTHS[0] if np.random.rand() < 0.7 else \
                MONTHS[np.random.randint(0, 4)]
            end = start + pd.DateOffset(months=12)
            rows.append({
                "entitlement_id": f"E{eid:05d}",
                "product_id": p["product_id"],
                "cust_id": c["cust_id"],
                "units_purchased": units,
                "licensed_amount": units,              # monthly entitlement quantity
                "unit_price": price,
                "arr": round(units * price, 2),
                "start_date": start.date().isoformat(),
                "end_date": end.date().isoformat(),
                "is_expansion": False,
            })
    ent = pd.DataFrame(rows)

    # ---- Mid-year expansions: ~6 accounts sign a second, larger, overlapping contract
    expansion_custs = customers.sample(6)["cust_id"].tolist()
    for cust in expansion_custs:
        base = ent[ent.cust_id == cust].sample(1).iloc[0]
        eid += 1
        p = prod_lookup.loc[base.product_id]
        _, up_rng, price_rng = PLATFORMS[p["product_platform"]]
        bigger = int(base.units_purchased * np.random.uniform(1.6, 2.5))
        price = round(np.random.uniform(*price_rng), 2)
        start = MONTHS[np.random.randint(5, 8)]        # mid-year start -> overlaps base
        end = start + pd.DateOffset(months=12)
        rows.append({
            "entitlement_id": f"E{eid:05d}",
            "product_id": base.product_id,
            "cust_id": cust,
            "units_purchased": bigger,
            "licensed_amount": bigger,
            "unit_price": price,
            "arr": round(bigger * price, 2),
            "start_date": start.date().isoformat(),
            "end_date": end.date().isoformat(),
            "is_expansion": True,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 5. consumption
def make_consumption(customers, entitlements):
    profile = customers.set_index("cust_id")["behavior_profile"].to_dict()
    rows = []
    cid = 0
    for _, e in entitlements.iterrows():
        beh = profile[e.cust_id]
        start = pd.Timestamp(e.start_date)
        end = pd.Timestamp(e.end_date)
        active_months = [m for m in MONTHS if start <= m < end]
        for idx, m in enumerate(active_months):
            L = e.licensed_amount
            if beh == "shelfware":
                util = 0.0
            elif beh == "overage":
                util = np.random.uniform(1.2, 1.6)
            elif beh == "spike_drop":
                util = np.random.uniform(3.0, 4.0) if idx < 3 else 0.0
            elif beh == "slow_onboarder":
                # dark months 1-2 -> first meaningful use in month 3 (~60+ days: TTV ~0.47,
                # exercising the 31-90-day partial band), ramp, then normal levels
                if idx < 2:
                    util = 0.0
                elif idx == 2:
                    util = np.random.uniform(0.18, 0.28)
                elif idx == 3:
                    util = np.random.uniform(0.40, 0.55)
                else:
                    util = float(np.clip(np.random.normal(0.72, 0.12), 0.15, 1.05))
            else:  # normal, single_feature_dep, (expansion accounts default here)
                util = float(np.clip(np.random.normal(0.72, 0.12), 0.15, 1.05))
                if e.is_expansion:                     # expansion ramps after signing
                    util *= min(1.0, 0.4 + 0.12 * idx)
            noise = np.random.uniform(0.9, 1.1) if util > 0 else 1.0
            consumed = round(L * util * noise, 2)
            cid += 1
            rows.append({
                "consumption_id": f"U{cid:06d}",
                "entitlement_id": e.entitlement_id,
                "cust_id": e.cust_id,
                "product_id": e.product_id,
                "month": m.date().isoformat(),
                "consumed_units": consumed,
                "licensed_amount": L,
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 6. feature adoption
def make_feature_adoption(customers, entitlements, features):
    profile = customers.set_index("cust_id")["behavior_profile"].to_dict()
    feats_by_prod = features.groupby("product_id")
    rows = []
    aid = 0
    for _, e in entitlements.iterrows():
        beh = profile[e.cust_id]
        if e.product_id not in feats_by_prod.groups:
            continue
        pf = feats_by_prod.get_group(e.product_id)
        start = pd.Timestamp(e.start_date)
        end = pd.Timestamp(e.end_date)
        active_months = [m for m in MONTHS if start <= m < end]

        # decide, per feature, adoption pattern for this entitlement
        for _, f in pf.iterrows():
            expected = f["_expected_active_volume"]
            # adoption decision
            if beh == "shelfware":
                adopted, adopt_idx = False, None
            elif beh == "spike_drop":
                adopted, adopt_idx = (np.random.rand() < 0.7), 0
            elif beh == "overage":
                adopted, adopt_idx = (np.random.rand() < 0.85), np.random.randint(0, 2)
            elif beh == "slow_onboarder":
                # features light up only after consumption starts -> shallow feature
                # adoption in the activation month (Onboarding Stall: ttv<0.5 AND fa<0.3)
                adopted = np.random.rand() < 0.6
                adopt_idx = np.random.randint(3, max(4, len(active_months) - 1))
            else:  # normal
                adopted = np.random.rand() < 0.6       # ~40% feature shelfware
                adopt_idx = np.random.randint(0, max(1, len(active_months) - 1))
            for idx, m in enumerate(active_months):
                events = 0
                if adopted and idx >= adopt_idx:
                    if beh == "spike_drop" and idx >= 3:
                        events = 0
                    elif beh == "overage":
                        events = int(expected * np.random.uniform(0.8, 1.3))
                    else:
                        events = int(expected * np.random.uniform(0.25, 1.1))
                aid += 1
                rows.append({
                    "adoption_id": f"A{aid:07d}",
                    "cust_id": e.cust_id,
                    "entitlement_id": e.entitlement_id,
                    "product_id": e.product_id,
                    "feature_id": f.feature_id,
                    "month": m.date().isoformat(),
                    "usage_events": events,
                })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- run
def main():
    customers = make_customers()
    products = make_products()
    features, thresholds = make_features(products)
    entitlements = make_entitlements(customers, products)
    consumption = make_consumption(customers, entitlements)
    feature_adoption = make_feature_adoption(customers, entitlements, features)

    # thresholds live as columns on the features table (meaningful_floor = 20% of
    # expected active volume, deep = 80%) rather than a separate table
    features_out = (features.drop(columns=["_expected_active_volume"])
                    .merge(thresholds, on="feature_id"))

    tables = {
        "customers": customers,
        "products": products,
        "entitlements": entitlements,
        "features": features_out,
        "consumption": consumption,
        "feature_adoption": feature_adoption,
    }
    for name, df in tables.items():
        df.to_csv(os.path.join(OUT, f"{name}.csv"), index=False)

    # -------- summary + anomaly verification
    print("=== ROW COUNTS ===")
    for name, df in tables.items():
        print(f"{name:20s} {len(df):>8,}")

    print("\n=== BEHAVIOR MIX (ground truth) ===")
    print(customers.behavior_profile.value_counts())

    # quick anomaly sanity checks on generated data
    cons = consumption.merge(customers[["cust_id", "behavior_profile"]], on="cust_id")
    cons["lur"] = cons.consumed_units / cons.licensed_amount
    print("\n=== ANOMALY SANITY CHECKS ===")
    shelf = cons.groupby("cust_id").consumed_units.sum()
    print("accounts with zero total consumption (shelfware):",
          (shelf == 0).sum())
    over = cons.groupby("cust_id").lur.mean()
    print("accounts avg LUR > 1.2 (overage):", (over > 1.2).sum())
    # overlapping entitlements
    ent = entitlements.copy()
    ent["s"] = pd.to_datetime(ent.start_date); ent["e"] = pd.to_datetime(ent.end_date)
    overlaps = 0
    for (_, _), g in ent.groupby(["cust_id", "product_id"]):
        g = g.sort_values("s")
        for i in range(len(g)):
            for j in range(i + 1, len(g)):
                if g.iloc[j].s < g.iloc[i].e:
                    overlaps += 1
    print("overlapping entitlement pairs (mid-year expansion):", overlaps)
    print(f"\nWrote {len(tables)} CSVs to {OUT}")


if __name__ == "__main__":
    main()
