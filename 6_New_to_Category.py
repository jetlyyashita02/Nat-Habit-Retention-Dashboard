"""🆕 New-to-Category — order movement of newly acquired customers (cohort view)."""
import pandas as pd
import plotly.express as px
import streamlit as st

import sources as S

st.set_page_config(page_title="New to Category", page_icon="🆕", layout="wide")
st.title("🆕 Product Order Movement — New to Category")
st.caption("Cohorts by onboarding month: how many customers place a 2nd / 3rd / … "
           "6th order, and how fast. Upload a fresh movement export to refresh.")


@st.cache_data(show_spinner="Loading…")
def _load(b: bytes):
    return S.load_movement(b)


@st.cache_data(show_spinner="Loading sample…")
def _sample():
    return S.load_movement("data/order_movement_ntc.csv")


up = st.sidebar.file_uploader("Order-movement CSV (onb_month, first_order, sec_pct, …)",
                              type=["csv"])
mv = _load(up.getvalue()) if up else _sample()
S.show_warnings(mv)

years = sorted({m[:4] for m in mv["month"]})
y1, y2 = st.select_slider("Cohort years", options=years,
                          value=(years[max(0, len(years) - 4)], years[-1]))
d = mv[(mv["month"] >= f"{y1}-01") & (mv["month"] <= f"{y2}-12")].copy()

k1, k2, k3, k4 = st.columns(4)
k1.metric("Cohort months", len(d), border=True)
k2.metric("New customers (1st orders)", f"{d['first_order'].sum():,.0f}", border=True)
w = d["first_order"] > 0
k3.metric("Avg 2nd-order rate", f"{d.loc[w, 'sec_pct'].mean():.1f}%", border=True)
k4.metric("Avg days to 2nd order", f"{d.loc[w, 'avg_days_to_sec'].mean():.0f}",
          border=True)

st.subheader("Repeat-rate curves by cohort month")
pct_cols = {"sec_pct": "2nd order", "third_pct": "3rd order", "fourth_pct": "4th order",
            "fifth_pct": "5th order", "sixth_pct": "6th order"}
sel = st.multiselect("Curves", list(pct_cols.values()),
                     default=["2nd order", "3rd order", "4th order"], key="mv_curves")
if sel:
    fig = go = None
    import plotly.graph_objects as go
    fig = go.Figure()
    for col, lab in pct_cols.items():
        if lab in sel:
            fig.add_scatter(x=d["month"], y=d[col], mode="lines+markers", name=lab)
    fig.update_layout(height=420, yaxis_title="% of cohort", yaxis_ticksuffix="%")
    st.plotly_chart(fig, width='stretch')

c1, c2 = st.columns(2)
with c1:
    st.subheader("New customers by cohort month")
    st.plotly_chart(px.bar(d, x="month", y="first_order",
                           color_discrete_sequence=["#E8604A"])
                    .update_layout(height=340), width='stretch')
with c2:
    st.subheader("Avg days to next order")
    fig2 = px.line()
    for col, lab in [("avg_days_to_sec", "→2nd"), ("avg_days_to_third", "→3rd"),
                     ("avg_days_to_fourth", "→4th")]:
        if col in d:
            fig2.add_scatter(x=d["month"], y=d[col], name=lab, mode="lines")
    fig2.update_layout(height=340)
    st.plotly_chart(fig2, width='stretch')

st.subheader("Full cohort table")
show = d.copy()
for c in ["sec_pct", "third_pct", "fourth_pct", "fifth_pct", "sixth_pct"]:
    if c in show:
        show[c] = show[c].round(1)
cfg = {c: st.column_config.NumberColumn(c, format="%.1f%%")
       for c in pct_cols if c in show.columns}
st.dataframe(show.drop(columns=["onb_month"]), hide_index=True,
             width='stretch', height=460, column_config=cfg)
st.download_button("⬇ Download cohort table", d.to_csv(index=False),
                   "new_to_category.csv", key="dl_mv")

st.subheader("Heatmap — 2nd-order % by cohort month")
hm = d.set_index("month")[["sec_pct"]]
if len(hm):
    st.plotly_chart(px.imshow(hm.T, text_auto=".1f", aspect="auto",
                              color_continuous_scale="Greens",
                              labels=dict(value="%")).update_layout(height=260),
                    width='stretch')

st.caption("Definitions: first_order = new-to-category customers onboarded that "
           "month; Nth % = share of the cohort with an Nth order (any category); "
           "avg_days = mean days from previous order.")
