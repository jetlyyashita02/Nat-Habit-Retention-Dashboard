"""💰 Sales & Revenue — variant + channel contribution, dynamic time periods + AOP."""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import sources as S

st.set_page_config(page_title="Sales & Revenue", page_icon="💰", layout="wide")
st.title("💰 Sales & Revenue Contribution")
st.caption("Variant-level and channel-level contribution, dynamic across time "
           "periods — from the sales aggregate CSV. AOP revenue & spend below.")


@st.cache_data(show_spinner="Loading…")
def _load(b: bytes):
    return S.load_sales(b)


@st.cache_data(show_spinner="Loading sample…")
def _sample():
    return S.load_sales("data/sales_rev_aggregate.csv")


up = st.sidebar.file_uploader("Sales aggregate CSV (order_date, sku, order_source, …)",
                              type=["csv"])
df = _load(up.getvalue()) if up else _sample()

with st.sidebar:
    months = sorted(df["month"].unique())
    from_m = st.selectbox("From month", months, 0)
    to_m = st.selectbox("To month", months, len(months) - 1)
    cats = st.multiselect("Categories", sorted(df["category"].unique()),
                          default=sorted(df["category"].unique()))
    chs = st.multiselect("Channels", sorted(df["channel"].unique()),
                         default=sorted(df["channel"].unique()))

d = df[(df["month"] >= from_m) & (df["month"] <= to_m)
       & df["category"].isin(cats) & df["channel"].isin(chs)]

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Revenue", f"₹{d['rev'].sum():,.0f}", border=True)
k2.metric("Orders", f"{d['orders'].sum():,.0f}", border=True)
k3.metric("Customers", f"{d['customers'].sum():,.0f}", border=True)
k4.metric("Qty", f"{d['qty'].sum():,.0f}", border=True)
k5.metric("AOV", f"₹{d['rev'].sum() / max(d['orders'].sum(), 1):,.0f}", border=True)

c1, c2 = st.columns(2)
with c1:
    t = d.groupby("month")["rev"].sum().reset_index()
    st.plotly_chart(px.area(t, x="month", y="rev", title="Revenue by month",
                            color_discrete_sequence=["#E8604A"]).update_layout(height=320),
                    width='stretch')
with c2:
    t = d.groupby("category")["rev"].sum().sort_values(ascending=False).reset_index()
    t["share %"] = 100 * t["rev"] / t["rev"].sum()
    st.plotly_chart(px.bar(t, x="category", y="rev", text="share %",
                           title="Revenue by category", color_discrete_sequence=["#8C2F1B"])
                    .update_layout(height=320), width='stretch')
    st.caption(" · ".join(f"{r['category']}: {r['share %']:.1f}%" for _, r in t.iterrows()))

st.subheader("Channel contribution")
t = d.groupby("channel").agg(rev=("rev", "sum"), orders=("orders", "sum"),
                             customers=("customers", "sum")).reset_index()
t["share %"] = (100 * t["rev"] / t["rev"].sum()).round(1)
t = t.sort_values("rev", ascending=False)
st.plotly_chart(px.bar(t, x="channel", y="rev", color="share %",
                       title="Revenue by channel", color_continuous_scale="Teal")
                .update_layout(height=320), width='stretch')
st.dataframe(t, hide_index=True, width='stretch')
st.download_button("⬇ Download channel table", t.to_csv(index=False),
                   "channel_contribution.csv", key="dl_ch")

st.subheader("Variant-level contribution (Pareto)")
v = (d.groupby(["sku", "product", "category"]).agg(rev=("rev", "sum"),
                                                   orders=("orders", "sum"),
                                                   qty=("qty", "sum"))
     .reset_index().sort_values("rev", ascending=False))
v["share %"] = (100 * v["rev"] / v["rev"].sum()).round(2)
v["cum share %"] = v["share %"].cumsum().round(1)
st.dataframe(v, hide_index=True, width='stretch', height=420)
st.download_button("⬇ Download variant table", v.to_csv(index=False),
                   "variant_contribution.csv", key="dl_var")

hm = d.pivot_table(index="channel", columns="month", values="rev",
                   aggfunc="sum", fill_value=0)
st.plotly_chart(px.imshow(hm, text_auto=",.0f", aspect="auto", color_continuous_scale="Greens",
                          title="Revenue heatmap — channel × month").update_layout(height=340),
                width='stretch')

# ------------------------------------------------------------- AOP
st.divider()
st.header("AOP — Revenue vs Spend (plan file)")
st.caption("Upload the AOP sheet (SD Category × Channel, monthly Jan'24 → Mar'28). "
           "Filters below apply to the AOP section.")


@st.cache_data(show_spinner="Parsing AOP…")
def _aop(b: bytes):
    return S.load_aop(b)


@st.cache_data(show_spinner="Parsing sample AOP…")
def _aop_sample():
    return S.load_aop("data/aop_data.csv")


aop_up = st.file_uploader("AOP CSV", type=["csv"], key="aop_up")
aop = _aop(aop_up.getvalue()) if aop_up else _aop_sample()
S.show_warnings(df, aop.get('revenue'))

if len(aop["revenue"]):
    rev, spend, roas = aop["revenue"], aop["spend"], aop["roas"]
    acats = st.multiselect("AOP categories", sorted(rev["Category"].dropna().unique()),
                           default=[c for c in ["Face Malai", "Active Gel", "Aloe Vera Gel"]
                                    if c in set(rev["Category"].dropna())], key="aop_cats")
    rev = rev[rev["Category"].isin(acats)]
    spend = spend[spend["Category"].isin(acats)]
    hist = st.checkbox("Only actuals (≤ Aug'26)", value=True)
    if hist:
        rev, spend = rev[rev["month"] <= "2026-08"], spend[spend["month"] <= "2026-08"]
    rt = rev.groupby("month")["value"].sum()
    stt = spend.groupby("month")["value"].sum()
    fig = go.Figure()
    fig.add_bar(x=rt.index, y=rt.values, name="Revenue", marker_color="#E8604A")
    fig.add_scatter(x=stt.index, y=stt.values, name="Spend", line=dict(color="#2A9D8F"))
    fig.update_layout(title="AOP revenue vs spend by month", height=380, barmode="group")
    st.plotly_chart(fig, width='stretch')

    a1, a2, a3 = st.columns(3)
    a1.metric("Revenue (period)", f"₹{rt.sum():,.0f}", border=True)
    a2.metric("Spend (period)", f"₹{stt.sum():,.0f}", border=True)
    a3.metric("Blended ROAS", f"{rt.sum() / max(stt.sum(), 1):.2f}", border=True)

    st.subheader("Category mix over time (revenue share)")
    mix = (rev.pivot_table(index="month", columns="Category", values="value",
                           aggfunc="sum", fill_value=0))
    mix = mix.div(mix.sum(axis=1), axis=0) * 100
    st.plotly_chart(px.area(mix, title="Revenue share % by category",
                            color_discrete_sequence=px.colors.qualitative.Prism)
                    .update_layout(height=360), width='stretch')

    chan = (rev.groupby(["Channels - Main", "month"])["value"].sum().reset_index())
    st.plotly_chart(px.line(chan, x="month", y="value", color="Channels - Main",
                            title="Revenue by channel (AOP)").update_layout(height=340),
                    width='stretch')
else:
    st.info("AOP file didn't parse — check it matches the SD-category monthly layout.")
