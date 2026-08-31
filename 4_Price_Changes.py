"""Page 4 — Price Changes: explicit price revisions (Retention FM log) +
price changes detected from realized sales prices, plus trend vs revision overlay."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import sources
from calculations import derived_price_changes, price_flags
from conclusions import price_conclusions, price_revision_conclusions, price_x_retention_conclusions
from formatting import (download_button, fmt_money, fmt_pct, fmt_pct_auto, init_page,
                        kpi_cards, render_report, section)
from calculations import fm_retention_table

init_page("4 · Price Changes", "🏷️",
          "Two evidence sources: (A) explicit price-revision log from the Retention FM sheet, "
          "(B) changes detected from realized sales prices (revenue ÷ quantity).")

# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 🏷️ Price changes")
    st.divider()
    st.caption("**Source A — explicit revisions** (Retention FM)")
    sources.page_uploader("retention_fm")
    fm, fm_rep, _ = sources.get_model("retention_fm")
    st.divider()
    st.caption("**Source B — detected from sales**")
    sources.page_uploader("sales")
    s_model, s_rep, _ = sources.get_model("sales")
    threshold = st.slider("Significance threshold (|MoM change|)", 1.0, 15.0, 5.0, 0.5,
                          key="price_thr", help="Flag SKU-months whose realized unit price moved more than this vs the previous month.")
    if s_model is not None:
        sales_df = s_model["df"]
        pchans = st.multiselect("Channels (for detection)", sorted(sales_df["channel"].unique()), key="price_f_ch")
        pmonths = st.multiselect("Months (for detection)", sorted(sales_df["month"].unique()), key="price_f_mo")
    if st.button("↺ Reset filters", key="price_reset"):
        for k in [k for k in st.session_state if k.startswith("price_")]:
            del st.session_state[k]
        st.rerun()

render_report(fm_rep, "Retention FM")
render_report(s_rep, "Sales data")

# ---------------------------------------------------------------------------
# Source A — explicit revisions
# ---------------------------------------------------------------------------
revisions = pd.DataFrame()
if fm is not None:
    revisions = fm["price"].copy()
    n_inc = int((revisions["change_type"] == "Increased Price").sum())
    n_dec = int((revisions["change_type"] == "Decreased Price").sum())
    n_same = int((revisions["change_type"] == "Same Price").sum())
    n_new = int((revisions["change_type"] == "New Variant").sum())
else:
    n_inc = n_dec = n_same = n_new = 0

detected = None
if s_model is not None:
    sf = s_model["df"]
    if pchans:
        sf = sf[sf["channel"].isin(pchans)]
    if pmonths:
        sf = sf[sf["month"].isin(pmonths)]
    detected = derived_price_changes(sf, threshold=threshold / 100.0)
    flags = price_flags(detected, threshold / 100.0)
    n_flag = len(flags)
    n_finc = int((flags["direction"] == "Increase").sum())
    n_fdec = int((flags["direction"] == "Decrease").sum())
else:
    flags = pd.DataFrame()
    n_flag = n_finc = n_fdec = 0

st.header("Price changes")
kpi_cards([
    ("Explicit: increases", str(n_inc)),
    ("Explicit: decreases", str(n_dec)),
    ("Explicit: same price", str(n_same)),
    ("Explicit: new variants", str(n_new)),
    ("Detected moves (≥±" + f"{threshold:g}%)", str(n_flag)),
    ("Detected: ↑ / ↓", f"{n_finc} / {n_fdec}"),
])

t1, t2 = st.tabs(["📋 A · Explicit price revisions", "🔎 B · Detected from sales data"])
with t1:
    if len(revisions):
        disp = revisions.copy()
        disp["change_type"] = disp["change_type"].map(
            lambda v: {"Increased Price": "🔺 Increased", "Decreased Price": "🔻 Decreased",
                       "Same Price": "➖ Same", "New Variant": "✨ New variant", "Other": "❔ Other"}.get(v, v))
        disp["date"] = disp["date"].map(str)
        st.dataframe(disp[["sku", "product", "note", "change_type", "date", "scope", "season"]],
                     width="stretch", hide_index=True, height=460)
        st.caption("Parsed from the price-revision notes in the Retention FM sheet "
                   "(e.g. 'Decreased-Price Revision - 2nd February, 2026').")
        download_button("⬇ Download price revisions", revisions, "price_revisions.csv")
    else:
        st.info("No price-revision log found in this Retention FM export.")

with t2:
    if detected is None:
        st.info("Upload a Sales/Revenue CSV (with quantity) to detect realized price changes.")
    elif detected.empty:
        st.info("No quantity>0 rows in the selected filter — realized price cannot be computed.")
    else:
        st.caption("**Detected from sales data** — realized unit price = revenue ÷ quantity for each SKU-month. "
                   "This is the *realized* selling price (includes discounts/promos), not necessarily list/MRP.")
        f = flags
        if len(f):
            disp = f.copy()
            disp["prev_price"] = disp["prev_price"].map(lambda v: fmt_money(v))
            disp["unit_price"] = disp["unit_price"].map(lambda v: fmt_money(v))
            disp["change_pct"] = disp["change_pct"].map(lambda v: fmt_pct(v, signed=True))
            disp["direction"] = disp["direction"].map(lambda v: {"Increase": "🔺 Increase", "Decrease": "🔻 Decrease"}.get(v, v))
            st.dataframe(disp[["sku", "product", "month", "prev_price", "unit_price", "change_pct", "direction"]],
                         width="stretch", hide_index=True, height=460)
            download_button("⬇ Download detected price changes", f, "price_changes_detected.csv")
        else:
            st.success(f"No SKU-month moved more than ±{threshold:g}% in the selected period.")
        # full series download
        dser = detected.copy()
        dser["change_pct"] = dser["change_pct"] * 100
        st.expander("Full realized-price series (all SKU-months)")
        st.dataframe(dser[["sku", "product", "month", "unit_price", "change_pct"]].head(500),
                     width="stretch", hide_index=True)
        download_button("⬇ Download full realized-price series",
                        dser.rename(columns={"change_pct": "change_pct_x100"}), "realized_price_series.csv")

# ---------------------------------------------------------------------------
# trend: realized price + revision events
# ---------------------------------------------------------------------------
st.divider()
section("Price trend — realized price vs revision events",
        "Pick a SKU: realized unit price per month (from sales) with explicit revision dates overlaid.")
if detected is not None and len(detected):
    skus = detected["sku"].unique()
    sku_sel = st.selectbox("SKU", sorted(skus), key="price_trend_sku")
    series = detected[detected["sku"] == sku_sel].sort_values("month")
    if len(series):
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=series["month"], y=series["unit_price"], mode="lines+markers",
                                 name="Realized unit price (sales)"))
        if len(revisions):
            ev = revisions[revisions["sku"] == sku_sel]
            for _, r in ev.iterrows():
                if pd.notna(r["date"]):
                    m = f"{r['date'].year:04d}-{r['date'].month:02d}"
                    if m in set(series["month"]):
                        fig.add_vline(x=m, line=dict(color="#c62828", dash="dash", width=2),
                                      annotation_text=f" {r['change_type']}", annotation_position="top")
        fig.update_layout(yaxis_title="₹ / unit", height=440, xaxis_title="month")
        st.plotly_chart(fig, width="stretch")

# ---------------------------------------------------------------------------
# price × retention cross-check (non-causal)
# ---------------------------------------------------------------------------
st.divider()
section("Price × Retention cross-check (Retention FM cohort)",
        "Compares retention of price-increased SKUs vs same/decreased-price SKUs in the FM cohort. "
        "Observational only — not a causal claim.")
as_of = st.date_input("As-of date for cohort maturity", value=pd.Timestamp.now().date(), key="price_asof")
if fm is not None:
    rt, windows = fm["df"], fm["windows"]
    vals, mat = fm_retention_table(rt, windows, as_of)
    w_avail = [w for w in windows if (mat[f"w{w}"] & vals[f"w{w}"].notna()).any()]
    if w_avail:
        w = max(w_avail)
        sub = rt[mat[f"w{w}"] & vals[f"w{w}"].notna()].copy()
        sub["retention"] = vals[f"w{w}"][sub.index]
        merged = sub.merge(revisions[["sku", "change_type"]], on="sku", how="left") if len(revisions) else sub
        d = merged.copy()
        d[f"{w}d retention"] = d["retention"].map(fmt_pct_auto)
        st.dataframe(d[["sku", "variant", "customers", "change_type", f"{w}d retention"]],
                     width="stretch", hide_index=True)
    else:
        st.info("No mature retention windows available for the selected as-of date.")

st.divider()
section("Business interpretation")
hint = None
if fm is not None:
    vals2, mat2 = fm_retention_table(fm["df"], fm["windows"], as_of)
    hx = price_x_retention_conclusions(revisions, vals2, mat2, fm["df"], fm["windows"])
    hint = hx[0] if hx else None
for c in price_revision_conclusions(revisions):
    st.markdown(f"- {c}")
for c in price_conclusions(revisions, flags, threshold / 100.0, hint):
    st.markdown(f"- {c}")
