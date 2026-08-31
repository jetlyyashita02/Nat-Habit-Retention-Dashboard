"""Page 6 — New-to-Category order movement: cohort repeat rates, avg days,
repeat curves, cohort heatmap (with maturity flags)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import sources
from calculations import ntc_kpis, ntc_maturity
from conclusions import ntc_conclusions
from formatting import (download_button, fmt_int, fmt_pct, init_page, kpi_cards,
                        render_report, section)

init_page("6 · New-to-Category", "🌱",
          "How new customers progress from 1st to 6th order, cohort by cohort. "
          "Recent cohorts are flagged 'immature' when the observation window is still open.")

# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 🌱 New-to-category")
    sources.page_uploader("order_movement")
    om, om_rep, _ = sources.get_model("order_movement")
    maturity_days = 90
    cohorts_sel = None
    if om is not None:
        maturity_days = st.slider("Cohort maturity window (days)", 30, 365, 90, 15,
                                  key="ntc_mat",
                                  help="A cohort is 'mature' when (as-of − cohort start) ≥ this. "
                                       "Immature cohorts are flagged and excluded from KPI averages.")
        cohorts_sel = st.multiselect("Cohorts", sorted(om["df"]["cohort"].unique()), key="ntc_coh")
    if st.button("↺ Reset filters", key="ntc_reset"):
        for k in [k for k in st.session_state if k.startswith("ntc_")]:
            del st.session_state[k]
        st.rerun()

render_report(om_rep, "Order movement data")
if om is None:
    st.info("Upload the Product Order Movement CSV to enable this page.")
    st.stop()

d = om["df"].copy()
as_of = om["as_of"]
if cohorts_sel:
    d = d[d["cohort"].isin(cohorts_sel)]
dm = ntc_maturity(d, as_of, maturity_days)
k = ntc_kpis(d, as_of, maturity_days)

# ---------------------------------------------------------------------------
st.header("New-to-category order movement")
kpi_cards([
    ("Cohorts (mature / total)", f"{k['cohorts_mature']} / {k['cohorts_total']}"),
    ("New customers (mature cohorts)", fmt_int(k["new_customers"])),
    ("Avg 2nd-order % (mature)", fmt_pct(k["avg_sec_pct"])),
    ("Avg days to 2nd (mature)", f"{k['avg_days_sec']:.0f} d" if k["avg_days_sec"] == k["avg_days_sec"] else "—"),
    ("Avg 3rd-order % (mature)", fmt_pct(k["avg_third_pct"])),
    ("Avg days to 3rd (mature)", f"{k['avg_days_third']:.0f} d" if k["avg_days_third"] == k["avg_days_third"] else "—"),
])
st.caption(f"As-of date: {as_of} (from the file's export timestamp). A cohort is mature when it has had at least "
           f"{maturity_days} days of observation. KPI averages are weighted by first-order volume over mature cohorts only.")

t1, t2, t3 = st.tabs(["📋 Order movement table", "📈 Repeat curves", "🔥 Heatmap"])
with t1:
    disp = dm.copy()
    for col in ["first_order", "sec_order", "third_order", "fourth_order", "fifth_order", "sixth_order"]:
        if col in disp.columns:
            disp[col] = disp[col].map(fmt_int)
    for col in ["sec_pct", "third_pct", "fourth_pct", "fifth_pct", "sixth_pct"]:
        if col in disp.columns:
            disp[col] = disp[col].map(fmt_pct)
    for col in ["avg_days_to_sec", "avg_days_to_third", "avg_days_to_fourth", "avg_days_to_fifth", "avg_days_to_sixth"]:
        if col in disp.columns:
            disp[col] = disp[col].map(lambda v: f"{v:.0f}" if v == v else "—")
    disp["status"] = np.where(dm["mature"], "✅ mature", "⏳ immature")
    disp = disp.rename(columns={
        "cohort": "Cohort", "first_order": "1st Order", "sec_order": "2nd Order", "sec_pct": "2nd %",
        "avg_days_to_sec": "Avg Days 2", "third_order": "3rd Order", "third_pct": "3rd %",
        "avg_days_to_third": "Avg Days 3", "fourth_order": "4th Order", "fourth_pct": "4th %",
        "avg_days_to_fourth": "Avg Days 4", "fifth_order": "5th Order", "fifth_pct": "5th %",
        "avg_days_to_fifth": "Avg Days 5", "sixth_order": "6th Order", "sixth_pct": "6th %",
        "avg_days_to_sixth": "Avg Days 6"})
    cols = [c for c in ["Cohort", "1st Order", "2nd Order", "2nd %", "Avg Days 2", "3rd Order", "3rd %", "Avg Days 3",
                        "4th Order", "4th %", "Avg Days 4", "5th Order", "5th %", "Avg Days 5",
                        "6th Order", "6th %", "Avg Days 6", "observed_days", "status"] if c in disp.columns]
    st.dataframe(disp[cols], width="stretch", hide_index=True, height=520)
    st.caption("⏳ immature = the observation window is still open — its (low) repeat rates are NOT real churn.")
    download_button("⬇ Download order movement table", dm, "new_to_category_movement.csv")

with t2:
    mat = dm[dm["mature"]].copy()
    if mat.empty:
        st.info("No mature cohorts in the selected range.")
    else:
        curves = st.multiselect("Repeat-rate curves", ["2nd", "3rd", "4th", "5th", "6th"],
                                default=["2nd", "3rd", "4th", "5th"], key="ntc_curves")
        long = []
        for ord_ in curves:
            col = {"2nd": "sec_pct", "3rd": "third_pct", "4th": "fourth_pct",
                   "5th": "fifth_pct", "6th": "sixth_pct"}[ord_]
            s = mat[["cohort", col]].dropna()
            s["order"] = ord_ + " order %"
            long.append(s.rename(columns={col: "rate"}))
        if long:
            ld = pd.concat(long, ignore_index=True)
            fig = px.line(ld, x="cohort", y="rate", color="order", markers=True,
                          title="Repeat-rate curves by cohort (mature cohorts)")
            fig.update_yaxes(tickformat=".0%")
            fig.update_layout(height=460, legend=dict(orientation="h"))
            st.plotly_chart(fig, width="stretch")
        c1, c2 = st.columns(2)
        with c1:
            fig = px.bar(mat, x="cohort", y="first_order", title="New customers by cohort")
            fig.update_layout(height=380)
            st.plotly_chart(fig, width="stretch")
        with c2:
            days = mat[["cohort", "avg_days_to_sec", "avg_days_to_third", "avg_days_to_fourth"]].dropna(how="all")
            dl = days.melt(id_vars="cohort", var_name="step", value_name="avg_days")
            dl["step"] = dl["step"].map(lambda v: v.replace("avg_days_to_", "days to "))
            fig = px.line(dl, x="cohort", y="avg_days", color="step", markers=True,
                          title="Average days to next order")
            fig.update_layout(height=380, legend=dict(orientation="h"))
            st.plotly_chart(fig, width="stretch")
        download_button("⬇ Download repeat curves", ld, "repeat_curves.csv")

with t3:
    mat = dm[dm["mature"]].copy()
    if len(mat):
        z = mat.set_index("cohort")["sec_pct"]
        z2 = z.values.reshape(-1, 1)
        fig = go.Figure(go.Heatmap(z=z2, x=["2nd order %"], y=list(z.index)[::-1],
                                   colorscale="YlGnBu",
                                   text=[[fmt_pct(v) if pd.notna(v) else "" for v in row] for row in z2],
                                   texttemplate="%{text}", zmin=0))
        fig.update_layout(height=max(420, 22 * len(z) + 120), xaxis_title="")
        st.plotly_chart(fig, width="stretch")
        st.caption("Cohort × 2nd-order % (mature cohorts only).")

st.divider()
section("Business interpretation")
for c in ntc_conclusions(om["df"], as_of, maturity_days):
    st.markdown(f"- {c}")
