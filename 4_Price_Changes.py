"""💲 Price Changes — revision notes + derived unit-price trends from sales data."""
import pandas as pd
import plotly.express as px
import streamlit as st

import sources as S

st.set_page_config(page_title="Price Changes", page_icon="💲", layout="wide")
st.title("💲 Price Changes")
st.caption("Two views: (1) the explicit price-revision notes from the retention "
           "sheet, and (2) unit-price trends derived live from the sales CSV — "
           "month-over-month moves are auto-flagged.")


@st.cache_data(show_spinner="Loading…")
def _ret(b: bytes):
    return S.load_retention(b)


@st.cache_data(show_spinner="Loading…")
def _sales(b: bytes):
    return S.load_sales(b)


@st.cache_data(show_spinner="Loading sample…")
def _ret_s():
    return S.load_retention("data/retention_fm_feb26.csv")


@st.cache_data(show_spinner="Loading sample…")
def _sales_s():
    return S.load_sales("data/sales_rev_aggregate.csv")


r_up = st.sidebar.file_uploader("Retention sheet CSV (has the price-lookup table)",
                                type=["csv"], key="ret_up")
ret, side = _ret(r_up.getvalue()) if r_up else _ret_s()
s_up = st.sidebar.file_uploader("Sales aggregate CSV (for unit-price trends)",
                                type=["csv"], key="sales_up2")
sales = _sales(s_up.getvalue()) if s_up else _sales_s()
S.show_warnings(sales, ret)

st.header("1 · Price revision notes (from retention sheet)")
if side is not None and len(side):
    order = ["Increased", "Decreased", "Same", "Launch / New", "Other", "—"]
    side["_o"] = side["change_type"].apply(lambda x: order.index(x) if x in order else 9)
    side_v = side.sort_values(["_o", "sku"]).drop(columns="_o")
    k1, k2, k3 = st.columns(3)
    k1.metric("SKUs with price notes", len(side), border=True)
    k2.metric("Decreased", int((side["change_type"] == "Decreased").sum()), border=True)
    k3.metric("Increased", int((side["change_type"] == "Increased").sum()), border=True)
    st.dataframe(side_v, hide_index=True, width='stretch')
    st.download_button("⬇ Download price notes", side_v.to_csv(index=False),
                       "price_changes.csv", key="dl_pc")
    st.plotly_chart(px.histogram(side_v, x="change_type", category_orders={"change_type": order},
                                 title="Price-revision mix", color_discrete_sequence=["#2A9D8F"])
                    .update_layout(height=300), width='stretch')
else:
    st.info("No price-revision side table found in the uploaded retention sheet.")

st.header("2 · Derived unit-price trends (₹ per unit, from sales CSV)")
up = (sales.groupby(["sku", "product", "month"])
      .apply(lambda g: pd.Series({"unit_price": g["rev"].sum() / g["qty"].sum()
                                  if g["qty"].sum() else None,
                                  "qty": g["qty"].sum()}), include_groups=False)
      .reset_index())
prices = up.pivot_table(index=["sku", "product"], columns="month",
                        values="unit_price", aggfunc="first")
skus = prices.reset_index()[["sku", "product"]].assign(
    label=lambda x: x["product"].str.slice(0, 42))
sel = st.multiselect("SKUs to plot", skus["label"].tolist(),
                     default=skus["label"].tolist()[:5], key="price_skus")
if sel:
    label_to_sku = dict(zip(skus["label"], skus["sku"]))
    sub = prices.loc[[label_to_sku[s] for s in sel]].reset_index()
    melted = sub.melt(id_vars=["sku", "product"], var_name="month", value_name="₹/unit").dropna()
    st.plotly_chart(px.line(melted, x="month", y="₹/unit", color="product",
                            markers=True, title="Unit price by month")
                    .update_layout(height=420, legend=dict(font=dict(size=10)))
                    .update_traces(line=dict(width=2)), width='stretch')

st.subheader("Auto-detected price moves (>5% month-over-month)")
rows = []
for (sku, product), g in up.groupby(["sku", "product"]):
    g = g.sort_values("month")
    g["prev"] = g["unit_price"].shift()
    g["delta %"] = 100 * (g["unit_price"] / g["prev"] - 1)
    hits = g[g["delta %"].abs() > 5]
    for _, r in hits.iterrows():
        rows.append({"sku": sku, "product": product, "month": r["month"],
                     "₹/unit": round(r["unit_price"], 1),
                     "change %": round(r["delta %"], 1)})
det = pd.DataFrame(rows)
if len(det):
    det["direction"] = det["change %"].apply(lambda x: "⬆ increase" if x > 0 else "⬇ decrease")
    det = det.sort_values(["month", "change %"], ascending=[False, True])
    st.dataframe(det, hide_index=True, width='stretch')
    st.download_button("⬇ Download detected moves", det.to_csv(index=False),
                       "detected_price_moves.csv", key="dl_moves")
    st.caption("Unit price = revenue ÷ qty for the SKU-month; discounts, packs and "
               "channel mix also move it — cross-check big moves with the revision notes above.")
else:
    st.success("No month-over-month unit-price moves above ±5% in the current data.")
