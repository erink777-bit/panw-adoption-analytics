"""
Value Realization Score (VRS) — executive adoption dashboard.

A lightweight Streamlit app over the VRS marts. Lets a CPO / product GM view adoption
performance by Customer and by Product, headlined by portfolio VRS, dollars-at-risk, and
a recommended-actions worklist.

Two data modes, auto-detected:
  * BigQuery  — if Google credentials are available, queries panw-502122.panw_adoption live.
  * Local     — otherwise reads data/*.csv (build once with `python build_local_data.py`).
    This lets the dashboard run with NO cloud auth.

Run:
    pip install -r requirements.txt
    streamlit run app.py
"""
import base64
import os
import pandas as pd
import plotly.express as px
import streamlit as st

PROJECT = "panw-502122"
DATASET = "panw_adoption"
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
FQ = f"`{PROJECT}.{DATASET}"

# displayed states are the four VRS bands (soft palette); operational states
# (Shelfware Risk, Churn Signal, ...) remain in the data layer for play logic only
STATE_COLORS = {"Value Realized": "#7CAE8A", "Developing": "#E7C878",
                "At Risk": "#C77E76", "Critical": "#B36259"}

PLAYS = [
    {"type": "state", "states": ["Shelfware Risk"], "play": "Activate", "owner": "Customer Success",
     "kind": "at risk", "addresses": "Shelfware",
     "profile": "Bought the product but never deployed it — effectively zero usage across the term."},
    {"type": "state", "states": ["Churn Signal", "Lapsed"], "play": "Win back", "owner": "Account teams",
     "kind": "at risk", "addresses": "Spike & drop",
     "profile": "Burned through usage early, then went dark — actively collapsing or already lapsed."},
    {"type": "flag", "flag": "flag_expansion", "play": "Upsell", "owner": "Sales",
     "kind": "upside", "addresses": "Consistent overage",
     "profile": "Consuming more than 120% of the licensed amount — real demand that is currently uncaptured revenue."},
]

st.set_page_config(page_title="VRS Adoption Dashboard", layout="wide")


# ------------------------------------------------------------- data layer
@st.cache_resource
def detect_mode():
    """BigQuery if credentials work within 10s, else local CSVs.

    The probe runs in a worker thread with a hard timeout: on hosts with no
    Google credentials (e.g. Streamlit Community Cloud) the auth lookup can
    stall for minutes, which would leave the app stuck on a spinner."""
    import concurrent.futures

    def _probe():
        from google.cloud import bigquery
        c = bigquery.Client(project=PROJECT)
        c.query("SELECT 1").result()
        return c

    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        c = ex.submit(_probe).result(timeout=10)
        return "bq", c
    except Exception:
        return "local", None
    finally:
        ex.shutdown(wait=False)


MODE, _CLIENT = detect_mode()


@st.cache_data(ttl=600)
def bq(sql):
    return _CLIENT.query(sql).result().to_dataframe()


@st.cache_data(ttl=600)
def local_frames():
    base = pd.read_csv(os.path.join(DATA, "mart_sku_month_full.csv"))
    feat = pd.read_csv(os.path.join(DATA, "mart_feature_full.csv"))
    for col in ("flag_expansion", "flag_single_feature_dependency"):
        if base[col].dtype == object:
            base[col] = base[col].map({"true": True, "false": False, True: True, False: False})
    return base, feat


BASE_COLS = ["cust_id", "cust_name", "segment", "region", "product_id", "product_name",
             "product_platform", "vrs", "arr", "lur", "util_health", "feature_adoption",
             "sustained_usage", "ttv_score", "state", "flag_expansion",
             "flag_single_feature_dependency"]


def _inq(vals):
    return "(" + ",".join(f"'{x}'" for x in vals) + ")"


def get_months():
    if MODE == "bq":
        m = bq(f"SELECT DISTINCT month FROM {FQ}.mart_customer_sku_month` ORDER BY month")["month"]
        return [d.strftime("%Y-%m") for d in m]
    base, _ = local_frames()
    return sorted(base["month"].str[:7].unique())


def get_month_data(month, segs, regs, plats):
    if MODE == "bq":
        return bq(f"""
          SELECT m.cust_id, c.cust_name, c.segment, c.region, m.product_id, p.product_name,
                 p.product_platform, m.vrs, m.arr, m.lur, m.util_health, m.feature_adoption,
                 m.sustained_usage, m.ttv_score, m.state, m.flag_expansion, m.flag_single_feature_dependency
          FROM {FQ}.mart_customer_sku_month` m
          JOIN {FQ}.customers` c USING(cust_id) JOIN {FQ}.products` p USING(product_id)
          WHERE m.month='{month}-01' AND c.segment IN {_inq(segs)} AND c.region IN {_inq(regs)}
                AND p.product_platform IN {_inq(plats)}""")
    base, _ = local_frames()
    d = base[(base["month"] == f"{month}-01") & base["segment"].isin(segs)
             & base["region"].isin(regs) & base["product_platform"].isin(plats)]
    return d[BASE_COLS].copy()


def get_trend(segs, regs, plats):
    if MODE == "bq":
        return bq(f"""
          SELECT m.month, SUM(m.vrs*m.arr)/SUM(m.arr) AS vrs
          FROM {FQ}.mart_customer_sku_month` m
          JOIN {FQ}.customers` c USING(cust_id) JOIN {FQ}.products` p USING(product_id)
          WHERE c.segment IN {_inq(segs)} AND c.region IN {_inq(regs)} AND p.product_platform IN {_inq(plats)}
          GROUP BY 1 ORDER BY 1""")
    base, _ = local_frames()
    d = base[base["segment"].isin(segs) & base["region"].isin(regs) & base["product_platform"].isin(plats)]
    return (d.groupby("month")[["vrs", "arr"]]
            .apply(lambda g: (g["vrs"] * g["arr"]).sum() / g["arr"].sum())
            .reset_index(name="vrs"))


def get_risk_trend(segs, regs, plats):
    if MODE == "bq":
        return bq(f"""SELECT m.month, SUM(IF(m.vrs<50, m.arr, 0)) AS arr_at_risk
                      FROM {FQ}.mart_customer_sku_month` m
                      JOIN {FQ}.customers` c USING(cust_id) JOIN {FQ}.products` p USING(product_id)
                      WHERE c.segment IN {_inq(segs)} AND c.region IN {_inq(regs)}
                            AND p.product_platform IN {_inq(plats)}
                      GROUP BY 1 ORDER BY 1""")
    base, _ = local_frames()
    d = base[base["segment"].isin(segs) & base["region"].isin(regs)
             & base["product_platform"].isin(plats)].copy()
    d["r"] = d["arr"].where(d["vrs"] < 50, 0)
    return d.groupby("month", as_index=False)["r"].sum().rename(columns={"r": "arr_at_risk"})


def get_band_trend(segs, regs, plats):
    """ARR per VRS band per month (for the stacked adoption-state chart)."""
    if MODE == "bq":
        return bq(f"""SELECT m.month,
                        CASE WHEN m.vrs >= 70 THEN 'Value Realized'
                             WHEN m.vrs >= 50 THEN 'Developing'
                             WHEN m.vrs >= 30 THEN 'At Risk'
                             ELSE 'Critical' END AS band,
                        SUM(m.arr) AS arr
                      FROM {FQ}.mart_customer_sku_month` m
                      JOIN {FQ}.customers` c USING(cust_id) JOIN {FQ}.products` p USING(product_id)
                      WHERE c.segment IN {_inq(segs)} AND c.region IN {_inq(regs)}
                            AND p.product_platform IN {_inq(plats)}
                      GROUP BY 1, 2 ORDER BY 1""")
    base, _ = local_frames()
    d = base[base["segment"].isin(segs) & base["region"].isin(regs)
             & base["product_platform"].isin(plats)].copy()
    d["band"] = pd.cut(d["vrs"], bins=[-1, 30, 50, 70, 101],
                       labels=["Critical", "At Risk", "Developing", "Value Realized"], right=False)
    return d.groupby(["month", "band"], observed=True, as_index=False)["arr"].sum().rename(columns={"arr": "arr"})


def get_features(cid, pid, month):
    if MODE == "bq":
        return bq(f"""SELECT feature_name, usage_events, feature_score, adoption_level
                      FROM {FQ}.mart_customer_feature_month`
                      WHERE cust_id='{cid}' AND product_id='{pid}' AND month='{month}-01'
                      ORDER BY feature_score DESC""")
    _, feat = local_frames()
    d = feat[(feat["cust_id"] == cid) & (feat["product_id"] == pid) & (feat["month"] == f"{month}-01")]
    return d[["feature_name", "usage_events", "feature_score", "adoption_level"]].sort_values(
        "feature_score", ascending=False)


def get_sku_series(cid, pid):
    """12-month License Utilization / VRS / state trajectory for one customer's product."""
    if MODE == "bq":
        return bq(f"""SELECT month, lur, vrs, state FROM {FQ}.mart_customer_sku_month`
                      WHERE cust_id='{cid}' AND product_id='{pid}' ORDER BY month""")
    base, _ = local_frames()
    d = base[(base["cust_id"] == cid) & (base["product_id"] == pid)].sort_values("month")
    return d[["month", "lur", "vrs", "state"]].copy()


# ------------------------------------------------------------- helpers
def money(x):
    if abs(x) >= 1e6:
        return f"${x/1e6:.1f}M"
    if abs(x) >= 1e3:
        return f"${x/1e3:.0f}K"
    return f"${x:.0f}"


def spct(x):   # a 0-1 signal shown as a percent
    return f"{x*100:.0f}%"


def vpct(x):   # a 0-100 VRS shown as a percent
    return f"{x:.0f}%"


# red -> yellow -> green gradient for score cells (light tints, dark text)
_GRAD_LO, _GRAD_MID, _GRAD_HI = (247, 231, 228), (252, 251, 247), (231, 241, 232)


def _grad(t):
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    if t < 0.5:
        u, a, b = t / 0.5, _GRAD_LO, _GRAD_MID
    else:
        u, a, b = (t - 0.5) / 0.5, _GRAD_MID, _GRAD_HI
    r, g, bl = (int(a[i] + (b[i] - a[i]) * u) for i in range(3))
    return f"background-color: rgb({r},{g},{bl}); color: #3D465C"


def _vrs_bg(v):
    try:
        return _grad(float(v) / 100.0)
    except (TypeError, ValueError):
        return ""


def _sig_bg(v):
    try:
        return _grad(float(v))
    except (TypeError, ValueError):
        return ""


# canonical band palette — one hue per band, used everywhere on the Portfolio tab
BAND_FILL = {"Value Realized": "#7CB08A", "Developing": "#E7C566",
             "At Risk": "#E8A06B", "Critical": "#DC8B80"}          # solid (charts)
BAND_PLAIN = {"Value Realized": "#5E9A6E", "Developing": "#C09A45",
              "At Risk": "#C77E76", "Critical": "#B36259"}         # plain in-table label text


def band_of(v):
    """VRS band displayed as the customer/SKU state everywhere in the UI."""
    return ("Value Realized" if v >= 70 else
            "Developing" if v >= 50 else
            "At Risk" if v >= 30 else "Critical")


PLOTLY_CONFIG = {"displayModeBar": False}


def dechrome(fig):
    """Item 6: quiet chart chrome — white plot, no x gridlines, faint y gridlines."""
    fig.update_layout(plot_bgcolor="#ffffff", paper_bgcolor="rgba(0,0,0,0)")
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="#eeeeee", zerolinecolor="#eeeeee")
    return fig


def style_scores(frame, vrs_cols=(), sig_cols=(), money_cols=()):
    """Return a Styler: VRS/signal cols shaded red->green; money cols shown as $X.XM.

    Columns are kept numeric and only *formatted* for display, so Streamlit sorts
    them by their real numeric value rather than the '$1.5M' / '$400K' text."""
    vrs_cols = [c for c in vrs_cols if c in frame.columns]
    sig_cols = [c for c in sig_cols if c in frame.columns]
    money_cols = [c for c in money_cols if c in frame.columns]
    fmt = {c: "{:.0f}%" for c in vrs_cols}
    fmt.update({c: "{:.0%}" for c in sig_cols})
    fmt.update({c: money for c in money_cols})
    sty = frame.style.format(fmt, na_rep="-")
    if vrs_cols:
        sty = sty.map(_vrs_bg, subset=vrs_cols)
    if sig_cols:
        sty = sty.map(_sig_bg, subset=sig_cols)
    return sty


def wvrs(g):
    return round((g["vrs"] * g["arr"]).sum() / g["arr"].sum(), 1) if g["arr"].sum() else 0.0


def kpis_for(d):
    if d is None or d.empty:
        return None
    cvrs = d.groupby("cust_id")[["vrs", "arr"]].apply(wvrs)
    return {"vrs": wvrs(d), "arr": d["arr"].sum(), "at_risk": d.loc[d["vrs"] < 50, "arr"].sum(),
            "cust_risk": int((cvrs < 50).sum()), "skus_risk": int((d["vrs"] < 50).sum()),
            "customers": d["cust_id"].nunique(),
            "exp_arr": d.loc[d["flag_expansion"], "arr"].sum(),
            "exp_cust": int(d.loc[d["flag_expansion"], "cust_id"].nunique())}


def delta(cur, prev, kind):
    if prev is None:
        return "—"
    diff = cur - prev
    arrow = "▲" if diff > 0 else ("▼" if diff < 0 else "▬")
    mag = abs(diff)
    s = money(mag) if kind == "money" else (f"{mag:.1f}%" if kind == "score" else f"{int(round(mag))}")
    return f"{arrow} {s}"


# ------------------------------------------------------------- sidebar
st.sidebar.title("Filters")
month_opts = get_months()
sel_month = st.sidebar.selectbox("As of month", month_opts, index=len(month_opts) - 1,
                                 format_func=lambda m: pd.to_datetime(m + "-01").strftime("%b %Y"),
                                 help="Point-in-time snapshot. Defaults to the latest month; change only to view the book as of a past point in time. Movement over time is shown by the MoM/QoQ figures and the trend chart on the Portfolio tab.")
_ALL_SEG = ["Enterprise", "Mid-Market"]
_ALL_REG = ["AMER", "EMEA", "APAC", "LATAM"]
_ALL_PLAT = ["hardware_ngfw", "software_ngfw", "sase", "cloud_ngfw"]
_PLAT_NAMES = {"hardware_ngfw": "Hardware NGFW", "software_ngfw": "Software NGFW",
               "sase": "SASE", "cloud_ngfw": "Cloud NGFW"}
segs = st.sidebar.multiselect("Segment", _ALL_SEG, default=[],
                              placeholder="All segments") or _ALL_SEG
regs = st.sidebar.multiselect("Region", _ALL_REG, default=[],
                              placeholder="All regions") or _ALL_REG
plats = st.sidebar.multiselect("Product platform", _ALL_PLAT, default=[],
                               format_func=lambda p: _PLAT_NAMES.get(p, p),
                               placeholder="All platforms") or _ALL_PLAT
st.sidebar.caption(f"data source: **{'BigQuery (live)' if MODE == 'bq' else 'local CSV (offline)'}**")
# selectbox always returns a value; "All" expands to the full list.

df = get_month_data(sel_month, segs, regs, plats)
if df.empty:
    st.warning("No data for this filter combination."); st.stop()

idx = month_opts.index(sel_month)
prev_m = month_opts[idx - 1] if idx >= 1 else None
prevq_m = month_opts[idx - 3] if idx >= 3 else None

_logo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "panw_logo.png")
_logo_html = ""
if os.path.exists(_logo):
    with open(_logo, "rb") as _f:
        _logo_b64 = base64.b64encode(_f.read()).decode()
    _logo_html = (
        f"<img src='data:image/png;base64,{_logo_b64}' style='width:175px'/>"
        "<div style='width:1px;height:40px;background:#E3E1DA'></div>"
    )
st.markdown(
    "<div style='display:flex;align-items:center;gap:14px'>"
    + _logo_html +
    "<div>"
    "<div style='font-size:26px;font-weight:700;color:#1B2338;white-space:nowrap'>"
    "Value Realization Score — Adoption Dashboard</div>"
    "<div style='font-size:13px;color:#6B7690'>"
    "ARR-weighted blend of License Utilization · Feature Adoption · Sustained Usage · Time to Value</div>"
    "</div>"
    f"<div style='margin-left:auto;text-align:right;color:#6B7690;font-size:13px;white-space:nowrap'>as of "
    f"<b style='color:#1B2338'>{pd.to_datetime(sel_month + '-01').strftime('%b %Y')}</b></div>"
    "</div>", unsafe_allow_html=True)

st.markdown("<style>div[data-testid='stVerticalBlockBorderWrapper']"
            "{background:#ffffff;border:1px solid #E3E1DA;border-radius:12px}</style>",
            unsafe_allow_html=True)

PLAT_LABEL = {"hardware_ngfw": "Hardware NGFW", "software_ngfw": "Software NGFW",
              "sase": "SASE", "cloud_ngfw": "Cloud NGFW"}
_psig = ["License Utilization", "Feature Adoption", "Sustained Usage", "Time to Value"]


def _wc(g, col):
    # NaN-safe ARR-weighting: null Time to Value (grace) / Feature Adoption
    # (feature-less SKU) rows are excluded from that signal's weighting.
    v = g[col].notna()
    aw = g.loc[v, "arr"].sum()
    return round((g.loc[v, col] * g.loc[v, "arr"]).sum() / aw, 2) if aw else float("nan")


tab_p, tab_prod, tab_c = st.tabs(["Portfolio", "By Product", "By Customer"])

# ------------------------------------------------------------- Portfolio
with tab_p:
    cur = kpis_for(df)
    prev = kpis_for(get_month_data(prev_m, segs, regs, plats)) if prev_m else None
    prevq = kpis_for(get_month_data(prevq_m, segs, regs, plats)) if prevq_m else None
    total_arr, at_risk = cur["arr"], cur["at_risk"]

    # ---- one type scale, used everywhere on this page ----
    DELTA_GREY = "#8A93A6"
    _lab = "font-size:12px;font-weight:600;color:#6B7690;white-space:nowrap"      # card label
    _big = "font-size:24px;font-weight:700;color:#1B2338"                          # card value
    _sub = "font-size:12px;color:#6B7690"                                          # secondary line
    _ttl = "font-size:15px;font-weight:700;color:#1B2338"                          # section title

    def _delta(diff, fmt="money", suffix=" MoM", extra=""):
        if diff is None:
            return ""
        arrow = "▲" if diff > 0 else ("▼" if diff < 0 else "▬")
        v = money(abs(diff)) if fmt == "money" else (f"{abs(diff):.1f}%" if fmt == "pct" else f"{abs(diff):.0f}")
        return (f"<div style='font-size:12px;font-weight:500;color:{DELTA_GREY};"
                f"white-space:nowrap'>{arrow} {v}{suffix}{extra}</div>")

    def _card(inner, bg="#ffffff", border="#E3E1DA"):
        return (f"<div style='flex:1;background:{bg};border:1px solid {border};border-radius:12px;"
                f"padding:12px 16px;min-width:0'>{inner}</div>")

    # ---- KPI strip: five uniform white cards ----
    p = max(0.0, min(100.0, cur["vrs"]))
    _arclen = 131.9
    gauge = (
        "<svg width='96' height='56' viewBox='0 0 100 56'>"
        "<path d='M 8 50 A 42 42 0 0 1 92 50' fill='none' stroke='#F3E6DF'"
        " stroke-width='11' stroke-linecap='round'/>"
        "<path d='M 8 50 A 42 42 0 0 1 92 50' fill='none' stroke='#FA582D'"
        f" stroke-width='11' stroke-linecap='round' stroke-dasharray='{p / 100 * _arclen:.1f} {_arclen}'/>"
        "</svg>")
    vrs_card = _card(
        "<div style='display:flex;gap:14px;align-items:center'>"
        f"<div style='flex:none;text-align:center'>{gauge}"
        f"<div style='font-size:24px;font-weight:700;color:#1B2338;margin-top:-28px'>{p:.1f}%</div></div>"
        f"<div><div style='{_lab}'>Portfolio VRS</div>"
        + _delta(cur["vrs"] - prev["vrs"] if prev else None, fmt="pct")
        + _delta(cur["vrs"] - prevq["vrs"] if prevq else None, fmt="pct", suffix=" QoQ")
        + "</div></div>")
    arr_card = _card(
        f"<div style='{_lab}'>Total ARR</div><div style='{_big}'>{money(total_arr)}</div>"
        f"<div style='{_sub}'>{cur['customers']} customers</div>")
    risk_card = _card(
        f"<div style='{_lab}'>ARR at Risk</div><div style='{_big}'>{money(at_risk)}</div>"
        + _delta(at_risk - prev["at_risk"] if prev else None))
    crisk_card = _card(
        f"<div style='{_lab}'>Customers at Risk</div><div style='{_big}'>{cur['cust_risk']}</div>"
        + _delta(cur["cust_risk"] - prev["cust_risk"] if prev else None, fmt="count"))
    exp_delta = _delta(cur["exp_arr"] - prev["exp_arr"] if prev else None,
                       extra=f" · {cur['exp_cust']} accounts")
    if not exp_delta:
        exp_delta = f"<div style='{_sub}'>{cur['exp_cust']} accounts</div>"
    exp_card = _card(
        f"<div style='{_lab}'>Expansion ARR</div><div style='{_big}'>{money(cur['exp_arr'])}</div>"
        + exp_delta)
    st.markdown("<div style='display:flex;gap:10px;align-items:stretch'>"
                + vrs_card + arr_card + risk_card + crisk_card + exp_card + "</div>",
                unsafe_allow_html=True)

    # ---- quiet band key ----
    _bands_strip = " &nbsp;·&nbsp; ".join(
        f"<span style='white-space:nowrap'><span style='color:{BAND_PLAIN[b]};font-weight:600'>{b}</span>"
        f" <span style='color:#6B7690'>{rng}</span></span>"
        for b, rng in [("Value Realized", "70–100%"), ("Developing", "50–69%"),
                       ("At Risk", "30–49%"), ("Critical", "0–29%")])
    st.markdown(
        "<div style='font-size:12px;margin:10px 0 4px;display:flex;gap:14px;align-items:center;flex-wrap:wrap'>"
        "<span style='font-size:11px;font-weight:700;color:#6B7690;letter-spacing:1px'>VRS BANDS</span>"
        f"<span>{_bands_strip}</span></div>", unsafe_allow_html=True)

    # ---- two chart cards ----
    tr = get_trend(segs, regs, plats)
    tr["month"] = pd.to_datetime(tr["month"].astype(str)).dt.strftime("%b '%y")
    bt = get_band_trend(segs, regs, plats)
    _BANDS = ["Value Realized", "Developing", "At Risk", "Critical"]
    MIX_FILL = {"Value Realized": "#C9DFCF", "Developing": "#F0E5C4",
                "At Risk": "#E8C5A8", "Critical": "#DCA89E"}
    SPARK = {"Value Realized": "#7CAE8A", "Developing": "#D9BC6A",
             "At Risk": "#D89B76", "Critical": "#C77E76"}
    d_now = df.copy()
    d_now["band"] = d_now["vrs"].apply(band_of)
    cur_band = d_now.groupby("band")["arr"].sum().reindex(_BANDS).fillna(0)
    hist = bt.copy()
    hist["month"] = hist["month"].astype(str).str[:7]
    piv = (hist.pivot_table(index="month", columns="band", values="arr", aggfunc="sum")
           .reindex(columns=_BANDS).fillna(0))
    shares = (piv.div(piv.sum(axis=1), axis=0) * 100).tail(12)
    sh_now = shares.loc[sel_month] if sel_month in shares.index else shares.iloc[-1]
    sh_q = shares.loc[prevq_m] if (prevq_m and prevq_m in shares.index) else None

    def _sparksvg(vals, color):
        if len(vals) < 2:
            return ""
        w, h, pad = 110, 30, 3
        lo, hi = min(vals), max(vals)
        rng = (hi - lo) or 1.0
        pts = " ".join(f"{pad + i * (w - 2 * pad) / (len(vals) - 1):.1f},"
                       f"{h - pad - (v - lo) / rng * (h - 2 * pad):.1f}"
                       for i, v in enumerate(vals))
        return (f"<svg width='{w}' height='{h}' viewBox='0 0 {w} {h}'>"
                f"<polyline points='{pts}' fill='none' stroke='{color}' stroke-width='1.6'"
                f" stroke-linejoin='round' stroke-linecap='round'/></svg>")

    t1, t2 = st.columns(2)
    with t1, st.container(border=True, height=298):
        st.markdown(f"<div style='{_ttl}'>Portfolio VRS trend</div>", unsafe_allow_html=True)
        figt = px.line(tr, x="month", y="vrs", markers=True, color_discrete_sequence=["#FA582D"])
        figt.add_hline(y=70, line_dash="dot", line_color="#8FB79A",
                       annotation_text="Value Realized · 70%", annotation_position="top left",
                       annotation_font_color="#8FB79A")
        figt.update_layout(height=232, xaxis_type="category",
                           yaxis=dict(range=[63, 72], dtick=2),
                           yaxis_title="Portfolio VRS (%)", yaxis_ticksuffix="%", xaxis_title="",
                           margin=dict(t=10, b=10))
        st.plotly_chart(dechrome(figt), width="stretch", config=PLOTLY_CONFIG)
    with t2, st.container(border=True, height=298):
        st.markdown(f"<div style='{_ttl}'>Where the ARR sits today</div>", unsafe_allow_html=True)
        def _mixseg(b):
            _pct = cur_band[b] / total_arr * 100
            _txt = ""
            if _pct >= 18:
                _txt = f"{b} · {_pct:.0f}%"
            elif _pct >= 7:
                _txt = f"{_pct:.0f}%"
            return (f"<div style='width:{_pct:.2f}%;background:{MIX_FILL[b]};display:flex;"
                    f"align-items:center;justify-content:center;font-size:11px;font-weight:600;"
                    f"color:{BAND_PLAIN[b]};white-space:nowrap;overflow:hidden'>{_txt}</div>")
        _mix = "".join(_mixseg(b) for b in _BANDS)
        st.markdown(f"<div style='display:flex;gap:2px;height:22px;border-radius:999px;overflow:hidden;"
                    f"margin:4px 0 14px'>{_mix}</div>", unsafe_allow_html=True)
        _cells, _empty = "", []
        for _b in _BANDS:
            if cur_band[_b] <= 0:
                _empty.append(_b)
                continue
            _dhtml = "<div style='font-size:12px;font-weight:600;color:#6B7690'>&nbsp;</div>"
            if sh_q is not None:
                _d = sh_now[_b] - sh_q[_b]
                if abs(_d) < 0.05:
                    _dhtml = "<div style='font-size:12px;color:#B7BDC9'>no change</div>"
                else:
                    _ar = "▲" if _d > 0 else "▼"
                    _dhtml = f"<div style='font-size:12px;font-weight:600;color:#6B7690'>{_ar} {abs(_d):.1f}pt</div>"
            _p = cur_band[_b] / total_arr * 100
            _ptxt = f"{_p:.1f}%" if _p < 1 else f"{_p:.0f}%"
            _cells += (
                "<div style='flex:1;background:#ffffff;border:1px solid #E3E1DA;border-radius:10px;"
                "padding:10px 12px;min-width:0'>"
                f"<div style='font-size:12px;font-weight:600;color:{BAND_PLAIN[_b]};white-space:nowrap'>{_b}</div>"
                f"<div style='font-size:20px;font-weight:700;color:#1B2338;margin-top:2px'>{money(cur_band[_b])}</div>"
                f"<div style='{_sub};white-space:nowrap'>{_ptxt} of ARR</div>"
                + _dhtml
                + f"<div style='margin-top:6px'>{_sparksvg(list(shares[_b]), SPARK[_b])}</div></div>")
        st.markdown(f"<div style='display:flex;gap:12px;align-items:stretch'>{_cells}</div>",
                    unsafe_allow_html=True)
        _foot = "Δ = change in share vs last quarter · sparklines show 12-mo share"
        if _empty:
            _foot += " · no ARR currently in: " + ", ".join(_empty)
        st.caption(_foot)

    # ---- top movers ----
    with st.container(border=True):
        st.markdown(f"<div style='{_ttl}'>Top movers this month</div>"
                    f"<div style='{_sub};margin-bottom:6px'>Largest VRS swings — accounts needing action first.</div>",
                    unsafe_allow_html=True)
        if prev is None:
            st.info("No prior month in range — movers need a month-over-month comparison.")
        else:
            dfp = get_month_data(prev_m, segs, regs, plats)
            cv_cur = df.groupby(["cust_id", "cust_name"]).apply(
                lambda g: pd.Series({"vrs": wvrs(g), "arr": g["arr"].sum()}), include_groups=False).reset_index()
            cv_prev = dfp.groupby("cust_id").apply(wvrs, include_groups=False).rename("vrs_prev").reset_index()
            mv = cv_cur.merge(cv_prev, on="cust_id", how="inner")
            mv["delta"] = mv["vrs"] - mv["vrs_prev"]

            def _play_of(cid):
                g = df[df["cust_id"] == cid]
                if g["state"].isin(["Churn Signal", "Lapsed"]).any():
                    return "Win back · Account teams"
                if (g["state"] == "Shelfware Risk").any():
                    return "Activate · Customer Success"
                if g["flag_expansion"].any():
                    return f"Upsell · Sales (overage {g.loc[g['flag_expansion'], 'lur'].max():.0%})"
                return "— monitor"

            mv["play"] = mv["cust_id"].apply(_play_of)
            mv["_act"] = mv["play"] != "— monitor"
            mv = mv.reindex(mv["delta"].abs().sort_values(ascending=False).index)
            mv = pd.concat([mv[mv["_act"]], mv[~mv["_act"]]]).head(7)

            _rows = ""
            for _, r in mv.iterrows():
                band = band_of(r["vrs"])
                vcol = "#A8574E" if r["vrs"] < 50 else "#1B2338"
                darr = "▼" if r["delta"] < 0 else ("▲" if r["delta"] > 0 else "▬")
                _rows += (
                    f"<tr style='border-bottom:1px solid #F0EEE8'>"
                    f"<td style='padding:9px 10px;font-weight:500;color:#3D465C'>{r['cust_name']}</td>"
                    f"<td style='padding:9px 10px;font-weight:700;color:{vcol}'>{r['vrs']:.0f}%</td>"
                    f"<td style='padding:9px 10px;font-weight:500;color:{DELTA_GREY}'>{darr} {abs(r['delta']):.0f}</td>"
                    f"<td style='padding:9px 10px;font-weight:500;color:#3D465C'>{money(r['arr'])}</td>"
                    f"<td style='padding:9px 10px;font-weight:500;color:{BAND_PLAIN[band]};"
                    f"white-space:nowrap'>{band}</td>"
                    f"<td style='padding:9px 10px;color:#6B7690'>{r['play']}</td></tr>")
            _hdr = "".join(f"<th style='text-align:left;padding:8px 10px;color:#6B7690;font-size:12px;"
                           f"font-weight:600;border-bottom:1px solid #E3E1DA'>{h}</th>"
                           for h in ["Customer", "VRS", "Δ MoM", "ARR", "State", "Recommended play"])
            st.markdown(f"<table style='width:100%;border-collapse:collapse;font-size:13.5px'>"
                        f"<thead><tr>{_hdr}</tr></thead><tbody>{_rows}</tbody></table>",
                        unsafe_allow_html=True)


# ------------------------------------------------------------- By Customer
with tab_c:
    # customer-level rollup: ARR-weighted VRS + the four signals it is built from
    def _w(x, col):
        v = x[col].notna()
        aw = x.loc[v, "arr"].sum()
        return round((x.loc[v, col] * x.loc[v, "arr"]).sum() / aw, 2) if aw else float("nan")
    grp = df.groupby(["cust_id", "cust_name", "segment", "region"])[
        ["vrs", "arr", "util_health", "feature_adoption", "sustained_usage", "ttv_score"]]
    cust = grp.apply(lambda x: pd.Series({
        "VRS": wvrs(x),
        "License Utilization": _w(x, "util_health"),
        "Feature Adoption": _w(x, "feature_adoption"),
        "Sustained Usage": _w(x, "sustained_usage"),
        "Time to Value": _w(x, "ttv_score"),
        "TotalARR": x["arr"].sum(),
        "ARRatrisk": x.loc[x["vrs"] < 50, "arr"].sum()})).reset_index()
    _sig = ["License Utilization", "Feature Adoption", "Sustained Usage", "Time to Value"]

    # ---- KPI cards ----
    risk_rows = df[df["vrs"] < 50]
    exp_rows = df[df["flag_expansion"]]
    _r_arr, _r_acc = risk_rows["arr"].sum(), risk_rows["cust_id"].nunique()
    _e_arr, _e_acc = exp_rows["arr"].sum(), exp_rows["cust_id"].nunique()
    _a_acc = pd.concat([risk_rows["cust_id"], exp_rows["cust_id"]]).nunique()
    st.markdown(
        "<div style='display:flex;gap:10px;align-items:stretch;margin-bottom:12px'>"
        + _card(f"<div style='{_lab}'>ARR at Risk</div><div style='{_big}'>{money(_r_arr)}</div>"
                f"<div style='font-size:12px;color:#6B7690'>{_r_acc} accounts</div>")
        + _card(f"<div style='{_lab}'>Expansion ARR</div><div style='{_big}'>{money(_e_arr)}</div>"
                f"<div style='font-size:12px;color:#6B7690'>{_e_acc} accounts</div>")
        + _card(f"<div style='{_lab}'>Accounts Needing Action</div><div style='{_big}'>{_a_acc}</div>"
                f"<div style='font-size:12px;color:#6B7690'>of {df['cust_id'].nunique()} customers</div>")
        + "</div>", unsafe_allow_html=True)

    # ---- Recommended plays — by account ----
    def _play_row(cid):
        g = df[df["cust_id"] == cid]
        if g["state"].isin(["Churn Signal", "Lapsed"]).any():
            return "Win back", "Account teams"
        if (g["state"] == "Shelfware Risk").any():
            return "Activate", "Customer Success"
        if g["flag_expansion"].any():
            return "Upsell", "Sales"
        return None, None

    with st.container(border=True):
        _pl, _pr = st.columns([2.4, 1.6], vertical_alignment="center")
        with _pl:
            st.markdown(f"<div style='{_ttl}'>Recommended plays — by account</div>", unsafe_allow_html=True)
        with _pr:
            _popts = ["All", "Activate", "Win back", "Upsell"]
            if hasattr(st, "pills"):
                pchoice = st.pills("Play filter", _popts, default="All", label_visibility="collapsed")
            else:
                pchoice = st.radio("Play filter", _popts, horizontal=True, label_visibility="collapsed")
            pchoice = pchoice or "All"

        _pids = pd.concat([risk_rows["cust_id"], exp_rows["cust_id"]]).unique()
        prow = cust[cust["cust_id"].isin(_pids)].copy()
        prow[["Play", "Owner"]] = prow["cust_id"].apply(lambda c: pd.Series(_play_row(c)))
        prow = prow.dropna(subset=["Play"])
        if pchoice != "All":
            prow = prow[prow["Play"] == pchoice]
        prow = prow.sort_values(["ARRatrisk", "TotalARR"], ascending=False)
        pdisp = prow.rename(columns={"cust_name": "Customer", "segment": "Segment",
                                     "TotalARR": "Total ARR", "ARRatrisk": "ARR at risk"})[
            ["Customer", "Segment", "Play", "Owner", "VRS"] + _sig + ["Total ARR", "ARR at risk"]]
        _PLAY_CSS = {"Activate": "color:#C09A45;font-weight:500",
                     "Win back": "color:#B36259;font-weight:500",
                     "Upsell": "color:#5E9A6E;font-weight:500"}
        styw = style_scores(pdisp, vrs_cols=["VRS"], sig_cols=_sig, money_cols=["Total ARR", "ARR at risk"])
        styw = styw.map(lambda v: _PLAY_CSS.get(v, ""), subset=["Play"])
        styw = styw.map(lambda _v: "color:#3D465C;font-weight:500", subset=["Customer", "Segment", "Owner", "Total ARR"])
        styw = styw.map(lambda _v: "color:#B08480;font-weight:500", subset=["ARR at risk"])
        st.dataframe(styw, width="stretch", hide_index=True)

    # ---- Drill into any customer ----
    with st.container(border=True):
        _dl, _dr = st.columns([1.1, 2.9], vertical_alignment="center")
        with _dl:
            st.markdown(f"<div style='{_ttl}'>Drill into any customer</div>", unsafe_allow_html=True)
        with _dr:
            _names = sorted(df["cust_name"].unique())
            _default = "Mcclure, Ward and Lee"   # cleanest ramp-to-full-utilization story
            pick = st.selectbox("Customer", _names,
                                index=_names.index(_default) if _default in _names else 0,
                                label_visibility="collapsed")
        cid = df.loc[df["cust_name"] == pick, "cust_id"].iloc[0]
        st.caption(f"Products ({pd.to_datetime(sel_month + '-01').strftime('%b %Y')}) — "
                   "click a row to switch the trajectory below.")

        sub = df[df["cust_id"] == cid][["product_name", "product_platform", "vrs", "state", "util_health",
                "feature_adoption", "sustained_usage", "ttv_score", "arr"]]
        subd = sub.sort_values("vrs").copy()
        subd = subd.rename(columns={
            "product_name": "Product", "product_platform": "Platform", "vrs": "VRS",
            "state": "State", "util_health": "License Utilization", "feature_adoption": "Feature Adoption",
            "sustained_usage": "Sustained Usage", "ttv_score": "Time to Value", "arr": "ARR"})
        subd["Platform"] = subd["Platform"].map(PLAT_LABEL).fillna(subd["Platform"])
        subd["State"] = subd["VRS"].apply(band_of)   # display the VRS band, not the raw state
        subd = subd.reset_index(drop=True)
        _STATE_CSS = {b: f"color:{BAND_PLAIN[b]};font-weight:500" for b in BAND_PLAIN}
        stys = style_scores(subd, vrs_cols=["VRS"],
                            sig_cols=["License Utilization", "Feature Adoption", "Sustained Usage", "Time to Value"],
                            money_cols=["ARR"])
        stys = stys.map(lambda v: _STATE_CSS.get(v, ""), subset=["State"])
        stys = stys.map(lambda _v: "color:#3D465C;font-weight:500", subset=["Product", "Platform", "ARR"])
        ev_cp = st.dataframe(stys, width="stretch", hide_index=True,
                             on_select="rerun", selection_mode="single-row", key=f"cust_prod_{cid}")
        if ev_cp.selection.rows:
            prod_pick = subd.iloc[ev_cp.selection.rows[0]]["Product"]
        else:
            prod_pick = subd.iloc[0]["Product"]
        pid = df.loc[(df["cust_id"] == cid) & (df["product_name"] == prod_pick), "product_id"].iloc[0]

    with st.container(border=True):
        ser = get_sku_series(cid, pid)
        ser["month"] = pd.to_datetime(ser["month"].astype(str)).dt.strftime("%b '%y")
        _prow = df[(df["cust_id"] == cid) & (df["product_name"] == prod_pick)].iloc[0]
        _pband = band_of(_prow["vrs"])
        st.markdown(
            f"<div style='{_ttl};margin-bottom:10px'>{pick} — {prod_pick}"
            f" <span style='font-size:13px;font-weight:400;color:#6B7690'>· {money(_prow['arr'])} ARR ·</span>"
            f" <span style='font-size:13px;font-weight:600;color:{BAND_PLAIN[_pband]}'>{_pband}</span></div>",
            unsafe_allow_html=True)
        cc1, cc2 = st.columns(2)
        with cc1, st.container(border=True):
            figl = px.line(ser, x="month", y="lur", markers=True, color_discrete_sequence=["#FA582D"])
            figl.add_hline(y=1.0, line_dash="dot", line_color="#8FB79A",
                           annotation_text="full · 1.0", annotation_position="top left",
                           annotation_font_color="#8FB79A")
            figl.add_hline(y=1.2, line_dash="dot", line_color="#B08480",
                           annotation_text="overage · 1.2", annotation_position="top left",
                           annotation_font_color="#B08480")
            figl.update_layout(title=dict(text="License Utilization by month · consumed / licensed",
                                          font=dict(size=13, color="#6B7690"), x=0, xanchor="left"),
                               height=272, xaxis_type="category",
                               yaxis=dict(tickvals=[0, 0.5, 1.0, 1.2],
                                          range=[-0.05, max(1.35, float(ser['lur'].max()) * 1.1)]),
                               yaxis_title=None, xaxis_title="", margin=dict(t=34, b=10, l=4))
            st.plotly_chart(dechrome(figl), width="stretch", config=PLOTLY_CONFIG)
        with cc2, st.container(border=True):
            figv = px.line(ser, x="month", y="vrs", markers=True, color_discrete_sequence=["#FA582D"])
            figv.add_hline(y=50, line_dash="dot", line_color="#D8A48F",
                           annotation_text="at risk below · 50%", annotation_position="bottom left",
                           annotation_font_color="#D8A48F")
            figv.update_layout(title=dict(text="VRS by month",
                                          font=dict(size=13, color="#6B7690"), x=0, xanchor="left"),
                               height=272, xaxis_type="category", yaxis_range=[0, 100],
                               yaxis=dict(tickvals=[0, 25, 50, 75, 100]),
                               yaxis_title=None, yaxis_ticksuffix="%", xaxis_title="",
                               margin=dict(t=34, b=10, l=4))
            st.plotly_chart(dechrome(figv), width="stretch", config=PLOTLY_CONFIG)

        st.markdown(f"<div style='{_ttl}'>Feature detail</div>", unsafe_allow_html=True)
        st.caption("Each feature judged against its own expected monthly volume.")
        fdf = get_features(cid, pid, sel_month).copy()
        fdf = fdf.rename(columns={"feature_name": "Feature", "usage_events": "Usage events",
                                  "feature_score": "Score", "adoption_level": "Adoption level"})
        _ADOPT_CSS = {"deep": f"color:{BAND_PLAIN['Value Realized']};font-weight:500",
                      "active": f"color:{BAND_PLAIN['Developing']};font-weight:500",
                      "enabled_idle": f"color:{BAND_PLAIN['At Risk']};font-weight:500",
                      "not_enabled": "color:#6B7690;font-weight:500"}
        styf = style_scores(fdf, sig_cols=["Score"])
        styf = styf.map(lambda v: _ADOPT_CSS.get(v, ""), subset=["Adoption level"])
        styf = styf.map(lambda _v: "color:#3D465C;font-weight:500", subset=["Feature"])
        styf = styf.format({"Usage events": "{:,.0f}", "Score": "{:.0%}"}, na_rep="-")
        st.dataframe(styf, width="stretch", hide_index=True,
                     column_config={"Adoption level": st.column_config.Column(
                         help="Score by monthly usage vs expected volume: not_enabled = 0 events → 0% · "
                              "enabled_idle = under 20% → 30% · active = 20–80% → 70% · deep = 80%+ → 100%")})
        _leg = [("not_enabled", "none", "#9AA0A6"),
                ("enabled_idle", "under 20%", BAND_PLAIN["At Risk"]),
                ("active", "20–80%", BAND_PLAIN["Developing"]),
                ("deep", "over 80%", BAND_PLAIN["Value Realized"])]
        st.markdown("<div style='font-size:12px;color:#6B7690;margin-top:4px'>"
                    "Adoption level = monthly usage vs expected: "
                    + " &nbsp;·&nbsp; ".join(
                        f"<span style='color:{c};font-weight:600'>{n}</span> <span>{d}</span>"
                        for n, d, c in _leg)
                    + "</div>", unsafe_allow_html=True)

# ------------------------------------------------------------- By Product
with tab_prod:
    _PLAT_ORDER = ["sase", "hardware_ngfw", "cloud_ngfw", "software_ngfw"]

    # ---- platform KPI cards ----
    _cards = ""
    for _plat in _PLAT_ORDER:
        g = df[df["product_platform"] == _plat]
        if g.empty:
            continue
        _v = wvrs(g)
        _arr = g["arr"].sum()
        _rk = g.loc[g["vrs"] < 50, "arr"].sum()
        _pct = (_rk / _arr * 100) if _arr else 0
        _cards += (
            "<div style='flex:1;background:#ffffff;border:1px solid #E3E1DA;border-radius:12px;"
            "padding:12px 16px;min-width:0'>"
            f"<div style='font-size:12px;font-weight:600;color:#6B7690'>{PLAT_LABEL[_plat]}</div>"
            f"<div style='font-size:24px;font-weight:700;color:#1B2338;margin-top:2px'>{_v:.1f}% "
            "<span style='font-size:12px;color:#6B7690;font-weight:400'>VRS</span></div>"
            f"<div style='font-size:12.5px;color:#6B7690;margin-top:2px;white-space:nowrap'>"
            f"ARR {money(_arr)} · <span style='color:#B08480;font-weight:500'>at risk {money(_rk)}</span>"
            f" · {_pct:.0f}%</div>"
            "<div style='height:6px;border-radius:3px;background:#F0EEE8;overflow:hidden;margin-top:12px'>"
            f"<div style='width:{_v:.0f}%;height:100%;background:#FA582D'></div></div></div>")
    st.markdown(f"<div style='display:flex;gap:10px;margin-bottom:12px'>{_cards}</div>",
                unsafe_allow_html=True)

    # ---- products table (one table, platform filter) ----
    with st.container(border=True):
        _hl, _hr = st.columns([2.1, 1.9], vertical_alignment="center")
        with _hl:
            st.markdown(f"<div style='{_ttl}'>Products — VRS across the customer base</div>", unsafe_allow_html=True)
            st.caption("Sorted by ARR at risk. Click a row to see the customers driving the score.")
        with _hr:
            _opts = ["All"] + [PLAT_LABEL[p] for p in _PLAT_ORDER]
            if hasattr(st, "pills"):
                choice = st.pills("Platform filter", _opts, default="All", label_visibility="collapsed")
            else:
                choice = st.radio("Platform filter", _opts, horizontal=True, label_visibility="collapsed")
            choice = choice or "All"

        dm = df.copy()
        dm["model"] = dm["product_name"].str.replace(r"\s*SKU-\d+$", "", regex=True)
        pm = (dm.groupby(["product_platform", "model"])[
                  ["vrs", "arr", "util_health", "feature_adoption", "sustained_usage", "ttv_score",
                   "cust_id", "state", "flag_expansion"]]
              .apply(lambda g: pd.Series({
                  "VRS": wvrs(g), "License Utilization": _wc(g, "util_health"),
                  "Feature Adoption": _wc(g, "feature_adoption"), "Sustained Usage": _wc(g, "sustained_usage"),
                  "Time to Value": _wc(g, "ttv_score"), "ARR": g["arr"].sum(),
                  "ARR_at_risk": g.loc[g["vrs"] < 50, "arr"].sum(),
                  "shelf": g.loc[g["state"] == "Shelfware Risk", "cust_id"].nunique(),
                  "sd": g.loc[g["state"].isin(["Churn Signal", "Lapsed"]), "cust_id"].nunique(),
                  "ov": g.loc[g["flag_expansion"], "cust_id"].nunique()}))
              .reset_index())
        pm["Platform"] = pm["product_platform"].map(PLAT_LABEL)

        def _anom_text(r):
            parts = []
            if r["shelf"]:
                parts.append(f"{int(r['shelf'])} shelfware")
            if r["sd"]:
                parts.append(f"{int(r['sd'])} spike & drop")
            if r["ov"]:
                parts.append(f"{int(r['ov'])} overage")
            return " · ".join(parts) if parts else "—"
        pm["Anomalies"] = pm.apply(_anom_text, axis=1)

        view = pm if choice == "All" else pm[pm["Platform"] == choice]
        view = view.sort_values("ARR_at_risk", ascending=False).reset_index(drop=True)
        tblp = view.rename(columns={"model": "Product model", "ARR_at_risk": "ARR at risk"})[
            ["Product model", "Platform", "VRS"] + _psig + ["ARR", "ARR at risk", "Anomalies"]]
        styp = style_scores(tblp, vrs_cols=["VRS"], sig_cols=_psig, money_cols=["ARR", "ARR at risk"])
        styp = styp.map(lambda _v: "color:#B08480;font-weight:500", subset=["ARR at risk"])
        styp = styp.map(lambda _v: "color:#3D465C;font-weight:500", subset=["Product model", "Platform", "ARR"])
        styp = styp.map(lambda _v: "color:#9AA0A6;font-size:11px", subset=["Anomalies"])
        _SIG_HELP = {
            "VRS": "0–100 · 35% License Utilization + 25% Feature Adoption + "
                   "25% Sustained Usage + 15% Time to Value, ARR-weighted",
            "License Utilization": "Depth of use (consumed / licensed): ~0% below 0.1 (shelfware) → "
                                   "100% near full use → capped at 80% above 1.2× (overage). 35% of VRS.",
            "Feature Adoption": "Breadth: average per-feature depth; un-adopted features count as 0. 25% of VRS.",
            "Sustained Usage": "Durability: recency-weighted activity over the last 3 months (50/30/20); "
                               "spike-then-drop scores 20%. 25% of VRS.",
            "Time to Value": "Speed to first real use: 100% within 30 days → 0% by 90 days; "
                             "never activated → 0%. 15% of VRS.",
        }
        _sig_cfg = {k: st.column_config.Column(help=v) for k, v in _SIG_HELP.items()}
        evp = st.dataframe(styp, width="stretch", hide_index=True, column_config=_sig_cfg,
                           on_select="rerun", selection_mode="single-row", key=f"pt_{choice}")

        if len(view):
            if evp.selection.rows:
                _row = view.iloc[evp.selection.rows[0]]
            else:
                _PREF_MODEL = {   # per filter: healthiest-looking top rows with a touch of variety
                    "All": "PA-460", "Hardware NGFW": "PA-460",
                    "SASE": "Prisma Access Remote Networks",
                    "Software NGFW": "VM-700", "Cloud NGFW": "Cloud NGFW for AWS"}
                _prefm = view[view["model"] == _PREF_MODEL.get(choice, "")]
                _row = _prefm.iloc[0] if len(_prefm) else view.iloc[0]
            model, _mplat = _row["model"], _row["product_platform"]
            with st.container(border=True):
                    st.markdown(f"<div style='{_ttl}'>{model} — customers on this product</div>", unsafe_allow_html=True)
                    st.caption("Worst VRS first. Anomaly ties each account to an edge-case pattern.")
                    dd = dm[(dm["product_platform"] == _mplat) & (dm["model"] == model)]
                    cc = (dd.groupby(["cust_id", "cust_name", "segment", "region"])[
                              ["vrs", "arr", "util_health", "feature_adoption", "sustained_usage", "ttv_score"]]
                          .apply(lambda g: pd.Series({
                              "VRS": wvrs(g), "License Utilization": _wc(g, "util_health"),
                              "Feature Adoption": _wc(g, "feature_adoption"), "Sustained Usage": _wc(g, "sustained_usage"),
                              "Time to Value": _wc(g, "ttv_score"), "ARR": g["arr"].sum()}))
                          .reset_index().sort_values("VRS"))

                    def _anom_of(g):
                        if (g["state"] == "Shelfware Risk").any():
                            return "Shelfware"
                        if g["state"].isin(["Churn Signal", "Lapsed"]).any():
                            return "Spike & drop"
                        if g["flag_expansion"].any():
                            return "Overage (upsell)"
                        if g["flag_single_feature_dependency"].any():
                            return "Single Feature Flag"
                        return "—"
                    anm = (dd.groupby("cust_id")[["state", "flag_expansion", "flag_single_feature_dependency"]]
                           .apply(_anom_of).rename("Anomaly").reset_index())
                    cc = cc.merge(anm, on="cust_id", how="left")
                    cd = cc.rename(columns={"cust_name": "Customer", "segment": "Segment", "region": "Region"})[
                        ["Customer", "Segment", "Region", "Anomaly", "VRS"] + _psig + ["ARR"]]
                    _ANOM = "color:#6B7690;font-weight:500"   # item 25: plain neutral text, no pill
                    _ANOM_CSS = {k: _ANOM for k in
                                 ("Shelfware", "Spike & drop", "Overage (upsell)", "Single Feature Flag")}
                    styc = style_scores(cd, vrs_cols=["VRS"], sig_cols=_psig, money_cols=["ARR"])
                    styc = styc.map(lambda v: _ANOM_CSS.get(v, ""), subset=["Anomaly"])
                    styc = styc.map(lambda _v: "color:#3D465C;font-weight:500", subset=["Customer", "Segment", "Region", "ARR"])
                    st.dataframe(styc, width="stretch", hide_index=True, column_config=_sig_cfg)

        st.markdown(
            "<div style='font-size:12px;color:#6B7690;margin-top:6px;display:flex;gap:14px;"
            "align-items:center;flex-wrap:wrap'>"
            "<span style='font-size:11px;font-weight:700;color:#6B7690;letter-spacing:1px'>VRS</span>"
            "<span><span style='color:#3D465C;font-weight:600'>35%</span> License Utilization"
            " &nbsp;+&nbsp; <span style='color:#3D465C;font-weight:600'>25%</span> Feature Adoption"
            " &nbsp;+&nbsp; <span style='color:#3D465C;font-weight:600'>25%</span> Sustained Usage"
            " &nbsp;+&nbsp; <span style='color:#3D465C;font-weight:600'>15%</span> Time to Value"
            " &nbsp;·&nbsp; hover a column header for how each signal is scored</span></div>",
            unsafe_allow_html=True)
