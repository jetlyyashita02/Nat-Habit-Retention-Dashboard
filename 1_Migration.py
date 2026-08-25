"""🔁 Migration — inter-category & inter-variant (entry → next order)."""
import io

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import etl
import metrics as M

st.set_page_config(page_title="Migration", page_icon="🔁", layout="wide")
st.title("🔁 Inter-Category & Inter-Variant Migration")
st.caption("Where do buyers go on their next purchase? (entry order → 2nd order, "
           "primary SKU in each order). Upload the journey dump to refresh.")


@st.cache_data(show_spinner="Loading…")
def _load(b: bytes):
    return etl.load_any(io.BytesIO(b))[0]


@st.cache_data(show_spinner="Loading sample…")
def _sample():
    return etl.load_journey_csv("data/sample_journeys.csv")


up = st.sidebar.file_uploader("Journey CSV (Sheet22 format or raw order-level)", type=["csv"])
import sources
long_df = _load(up.getvalue()) if up else _sample()
sources.show_warnings(long_df)

level = st.radio("Migration level", ["Category", "Variant", "SKU"], horizontal=True)
col_map = {"Category": "category", "Variant": "variant", "sku_key": "SKU"}
lv = level.lower() if level != "SKU" else "sku_key"

# primary-item entry -> next pairs
d = long_df
firsts = d[(d["order_seq"] == 1) & (d["item_seq"] == 1)][["customer", lv]].rename(columns={lv: "from"})
seconds = d[(d["order_seq"] == 2) & (d["item_seq"] == 1)][["customer", lv]].rename(columns={lv: "to"})
pairs = firsts.merge(seconds, on="customer", how="inner")

k1, k2, k3, k4 = st.columns(4)
k1.metric("Customers with a 2nd order", f"{len(pairs):,}", border=True)
same = (pairs["from"] == pairs["to"]).sum()
k2.metric(f"Repeated same {level.lower()}", f"{same:,} ({100 * same / len(pairs):.1f}%)" if len(pairs) else "—", border=True)
switched = pairs[pairs["from"] != pairs["to"]]
k3.metric(f"Switched {level.lower()}", f"{len(switched):,}", border=True)
gaps = d[(d["order_seq"] == 2)].drop_duplicates("customer")["gap_days"]
k4.metric("Avg days 1→2", f"{gaps.mean():.0f}" if gaps.notna().any() else "—", border=True)

st.subheader(f"{level}-to-{level} matrix")
mat = pd.crosstab(pairs["from"], pairs["to"])
fig = go.Figure(go.Heatmap(z=mat.values, x=mat.columns, y=mat.index,
                           colorscale="Greens", text=mat.values,
                           texttemplate="%{text}", hovertemplate="%{y} → %{x}: %{z}<extra></extra>"))
fig.update_layout(height=max(420, 34 * len(mat)), yaxis_title="Entry", xaxis_title="2nd order")
st.plotly_chart(fig, width='stretch')

c1, c2 = st.columns(2)
with c1:
    st.subheader("Top switch flows")
    if len(switched):
        flows = (switched.groupby(["from", "to"]).size().reset_index(name="customers")
                 .sort_values("customers", ascending=False).head(20))
        st.dataframe(flows, hide_index=True, width='stretch')
        st.download_button("⬇ Download flows", flows.to_csv(index=False),
                           "migration_flows.csv", key="dl_flows")
with c2:
    st.subheader("Retention vs outflow by " + level.lower())
    pp = pairs.assign(stay=pairs["from"] == pairs["to"])
    g = pp.groupby("from").agg(customers=("customer", "size"),
                               stay_pct=("stay", "mean")).reset_index()
    def _dest(key):
        s = pp[(pp["from"] == key) & (~pp["stay"])]["to"]
        return s.mode().iloc[0] if len(s) else "—"
    g["top destination"] = g["from"].map(_dest)
    g = g.rename(columns={"stay_pct": "stay %"})
    g["stay %"] = (100 * g["stay %"]).round(1)
    st.dataframe(g.sort_values("customers", ascending=False), hide_index=True,
                 width='stretch', height=420)

st.subheader("Net migration (gains − losses among switchers)")
if len(switched):
    out = switched.groupby("from")["customer"].nunique()
    inn = switched.groupby("to")["customer"].nunique()
    net = (pd.concat([inn.rename("gained"), out.rename("lost")], axis=1)
           .fillna(0).assign(net=lambda x: x["gained"] - x["lost"])
           .sort_values("net", ascending=False))
    net.index.name = lv
    net = net.reset_index()
    fig2 = px.bar(net, x=lv, y="net", color=net["net"] > 0,
                  color_discrete_map={True: "#E8604A", False: "#C0392B"},
                  labels={"net": "net customers gained"}, title=f"Net {level.lower()} gravity")
    fig2.update_layout(showlegend=False, height=380)
    st.plotly_chart(fig2, width='stretch')
    st.dataframe(net, hide_index=True, width='stretch')
