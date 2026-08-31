"""Page 2 — Sales & Revenue contribution + AOP (plan) revenue/spend/ROAS."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import sources
from calculations import (channel_contribution, category_contribution, pivot_matrix,
                          sales_filter, sales_kpis, sales_trend, variant_contribution,
                          aop_monthly, aop_long_filtered, aop_category_share, aop_fy)
from conclusions import sales_conclusions
from formatting import (download_button, fmt_int, fmt_money, fmt_pct, init_page,
                        kpi_cards, render_report, section)

init_page("2 · Sales & Revenue", "💰",
          "Actual sales contribution (category / variant / channel) and the AOP plan (revenue, spend, ROAS). "
          "Actual and AOP are shown separately and never mixed.")

# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 💰 Sales & AOP")
    st.divider()
    st.caption("**Actual sales**")
    sources.page_uploader("sales")
    s_model, s_rep, _ = sources.get_model("sales")
    if s_model is not None:
        df = s_model["df"]
        months_all = sorted(df["month"].unique())
        months_sel = st.multiselect("Months", months_all, key="sales_f_months")
        cats_sel = st.multiselect("Categories", sorted(df["category"].unique()), key="sales_f_cats")
        chans_sel = st.multiselect("Channels", sorted(df["channel"].unique()), key="sales_f_chans")
        skus_sel = st.multiselect("SKUs", sorted(df["sku"].unique())[:200], key="sales_f_skus")
        if st.button("↺ Reset sales filters", key="sales_reset"):
            for k in [k for k in st.session_state if k.startswith("sales_f_")]:
                del st.session_state[k]
            st.rerun()
    st.divider()
    st.caption("**AOP / Plan**")
    sources.page_uploader("aop")
    aop, aop_rep, _ = sources.get_model("aop")
    aop_cats, aop_chans, aop_owners, aop_newex, aop_ref = [], [], [], [], None
    if aop is not None:
        cc, ch = aop["category_col"], aop["channel_sub_col"]
        aop_cats = st.multiselect("AOP categories", sorted(aop["meta"][cc].unique()), key="aop_f_cats")
        aop_chans = st.multiselect("AOP channels", sorted(aop["meta"][ch].unique()), key="aop_f_chans")
        aop_owners = st.multiselect("Category owners", sorted(aop["meta"]["Category Owner"].dropna().unique()), key="aop_f_owners")
        aop_newex = st.multiselect("New vs existing", sorted(aop["meta"]["New/Existing"].dropna().unique()), key="aop_f_ne")
        # default ref month: last month where >50% of TOTAL rows carry revenue
        tot = aop["long"][(aop["long"][ch].str.upper().str.strip() == "TOTAL") & (aop["long"]["block"] == "revenue")]
        ref_default = aop["months"][-1]
        if len(tot):
            n_tot_lines = tot["month"].nunique() and tot.groupby("month").size().max()
            frac = tot.assign(pos=tot["value"].notna() & (tot["value"] > 0)).groupby("month")["pos"].mean()
            mature = [m for m in frac.index if frac[m] >= 0.5]
            if mature:
                ref_default = max(mature)
        aop_ref = st.selectbox("Actual ↔ Plan split (ref month)", aop["months"],
                               index=aop["months"].index(ref_default) if ref_default in aop["months"] else 0,
                               key="aop_f_ref",
                               help="Months ≤ ref are treated as booked actuals in the AOP sheet; later months are future plan.")

render_report(s_rep, "Sales data")
render_report(aop_rep, "AOP data")

# ===========================================================================
# ACTUAL SALES
# ===========================================================================
st.header("Actual / Sales")
if s_model is None:
    st.info("Upload a Sales/Revenue CSV (order date, SKU, channel, product, category, orders, customers, quantity, revenue).")
else:
    df = s_model["df"]
    f = sales_filter(df, months=months_sel or None, categories=cats_sel or None,
                     channels=chans_sel or None, skus=skus_sel or None)
    kpis = sales_kpis(f)

    # previous-month comparison (latest selected month vs prior month in data)
    prev_kpis = None
    fm = sorted(f["month"].unique())
    if fm:
        last_m = fm[-1]
        prior = [m for m in sorted(df["month"].unique()) if m < last_m]
        if prior:
            pf = sales_filter(df, months=[prior[-1]], categories=cats_sel or None,
                              channels=chans_sel or None, skus=skus_sel or None)
            prev_kpis = sales_kpis(pf)

    g = None
    if prev_kpis and prev_kpis.get("revenue") and kpis.get("revenue") is not None and prev_kpis["revenue"] > 0:
        g = (kpis["revenue"] - prev_kpis["revenue"]) / prev_kpis["revenue"]
    kpi_cards([
        ("Revenue", fmt_money(kpis["revenue"]), fmt_pct(g, signed=True) if g is not None and not np.isnan(g) else None,
         None if g is None or np.isnan(g) else g),
        ("Orders", fmt_int(kpis["orders"])),
        ("Customers (touch counts)", fmt_int(kpis["customers"])),
        ("Quantity", fmt_int(kpis["quantity"])),
        ("AOV (rev/order)", fmt_money(kpis["aov"])),
        ("Rev / customer", fmt_money(kpis["rev_per_customer"])),
    ])
    st.caption("Customer figures from an aggregate file are *touch counts* — the same customer buying in several "
               "categories/channels is counted once per row, so they may not sum to a unique-customer total.")

    t1, t2 = st.tabs(["📈 Revenue trend", " Contribution"])
    with t1:
        view = st.radio("View", ["Monthly total", "By category", "By channel"], horizontal=True)
        by = {"Monthly total": "month", "By category": "category", "By channel": "channel"}[view]
        tr = sales_trend(f, by)
        if by == "month":
            fig = go.Figure()
            fig.add_trace(go.Bar(x=tr["month"], y=tr["revenue"], name="Revenue"))
            if "orders" in tr.columns and tr["orders"].notna().any():
                fig.add_trace(go.Scatter(x=tr["month"], y=tr["orders"], name="Orders",
                                         yaxis="y2", mode="lines+markers"))
            fig.update_layout(yaxis_title="Revenue", yaxis2=dict(title="Orders", overlaying="y", side="right"),
                              height=420, legend=dict(orientation="h"))
        else:
            fig = px.area(tr, x="month", y="revenue", color="bucket",
                          title="Revenue contribution by " + ("category" if by == "category" else "channel"))
            fig.update_layout(height=420)
        st.plotly_chart(fig, width="stretch")
        download_button("⬇ Download trend", tr, "sales_trend.csv")

    with t2:
        cat = category_contribution(f)
        var = variant_contribution(f)
        chan = channel_contribution(f)
        c1, c2, c3 = st.tabs(["Category", "Variant (Pareto)", "Channel"])
        with c1:
            disp = cat.copy()
            disp["revenue"] = disp["revenue"].map(fmt_money)
            disp["revenue_share"] = disp["revenue_share"].map(fmt_pct)
            disp["orders"] = disp["orders"].map(fmt_int)
            disp["customers"] = disp["customers"].map(fmt_int)
            disp["quantity"] = disp["quantity"].map(fmt_int)
            disp["quantity_share"] = disp["quantity_share"].map(fmt_pct)
            st.dataframe(disp[["category", "revenue", "revenue_share", "orders", "customers",
                               "quantity", "quantity_share"]], width="stretch", hide_index=True)
            fig = px.bar(cat.iloc[::-1], x="revenue", y="category", orientation="h")
            fig.update_layout(height=max(360, 32 * len(cat) + 100), xaxis_title="Revenue")
            st.plotly_chart(fig, width="stretch")
            download_button("⬇ Download category contribution", cat, "category_contribution.csv")
        with c2:
            d2 = var.copy()
            d2["revenue"] = d2["revenue"].map(fmt_money)
            d2["revenue_share"] = d2["revenue_share"].map(fmt_pct)
            d2["cumulative_share"] = d2["cumulative_share"].map(fmt_pct)
            d2["orders"] = d2["orders"].map(fmt_int)
            d2["quantity"] = d2["quantity"].map(fmt_int)
            st.dataframe(d2[["sku", "product", "category", "revenue", "revenue_share",
                             "orders", "quantity", "cumulative_share"]],
                         width="stretch", hide_index=True, height=460)
            fig = px.bar(var, x="product", y="revenue", title="Variant revenue")
            fig.add_scatter(x=var["product"], y=var["cumulative_share"] * 100, mode="lines",
                            name="Cumulative %", line=dict(color="#c62828"), yaxis="y2")
            fig.update_layout(yaxis2=dict(overlaying="y", side="right", range=[0, 105], title="Cum %"),
                              xaxis_tickangle=-35, height=480)
            st.plotly_chart(fig, width="stretch")
            download_button("⬇ Download variant contribution", var, "variant_contribution.csv")
        with c3:
            d3 = chan.copy()
            d3["revenue"] = d3["revenue"].map(fmt_money)
            d3["revenue_share"] = d3["revenue_share"].map(fmt_pct)
            d3["orders"] = d3["orders"].map(fmt_int)
            d3["customers"] = d3["customers"].map(fmt_int)
            d3["aov"] = d3["aov"].map(fmt_money)
            st.dataframe(d3[["channel", "revenue", "revenue_share", "orders", "customers", "aov"]],
                         width="stretch", hide_index=True)
            m1 = pivot_matrix(f, "channel", "month")
            m2 = pivot_matrix(f, "channel", "category")
            if len(m1):
                st.markdown("**Channel × Month (revenue)**")
                fig = go.Figure(go.Heatmap(z=m1.values, x=m1.columns.astype(str), y=m1.index.astype(str),
                                            colorscale="Teal", texttemplate="%{text:,.0f}"))
                fig.update_layout(height=max(380, 34 * len(m1) + 120))
                st.plotly_chart(fig, width="stretch")
                download_button("⬇ Download channel × month", m1.reset_index(), "channel_month.csv")
            if len(m2):
                st.markdown("**Channel × Category (revenue)**")
                fig = go.Figure(go.Heatmap(z=m2.values, x=m2.columns.astype(str), y=m2.index.astype(str),
                                            colorscale="Teal", texttemplate="%{text:,.0f}"))
                fig.update_layout(height=max(380, 34 * len(m2) + 120))
                st.plotly_chart(fig, width="stretch")
                download_button("⬇ Download channel × category", m2.reset_index(), "channel_category.csv")

    st.divider()
    section("Business interpretation — actual sales")
    for c in sales_conclusions(kpis, prev_kpis, cat, chan, var, fm):
        st.markdown(f"- {c}")

# ===========================================================================
# AOP / PLAN
# ===========================================================================
st.divider()
st.header("AOP / Plan", )
st.caption("AOP figures are the plan sheet (booked actuals for past months + future plan). "
           "They are **not** actual sales and are never combined with the sales figures above.")
if aop is None:
    st.info("Upload the AOP CSV to enable the plan view.")
else:
    kw = dict(categories=aop_cats or None, channels=aop_chans or None, owners=aop_owners or None,
              new_ex=aop_newex or None)
    monthly = aop_monthly(aop, **kw)
    if monthly.empty:
        st.info("No AOP values for the current filter combination.")
    else:
        months = monthly["month"].tolist()
        split_i = max([i for i, m in enumerate(months) if m <= aop_ref], default=len(months) - 1)
        last_act = monthly[monthly["month"] <= aop_ref].dropna(subset=["revenue"]).tail(1)
        kpi_cards([
            ("Latest booked revenue", fmt_money(last_act["revenue"].iloc[0]) if len(last_act) else "—"),
            ("Latest booked spend", fmt_money(last_act["spend"].iloc[0]) if len(last_act) else "—"),
            ("Latest ROAS", f"{last_act['roas'].iloc[0]:.2f}" if len(last_act) and last_act["roas"].notna().any() else "—"),
            ("Months (AOP span)", f"{months[0]} → {months[-1]}"),
            ("Split", f"actual ≤ {aop_ref} · plan > {aop_ref}"),
        ])
        c1, c2, c3, c4 = st.tabs(["Revenue vs Spend", "ROAS", "Share by category", "Growth & FY"])
        with c1:
            fig = go.Figure()
            fig.add_trace(go.Bar(x=months, y=monthly["revenue"], name="Revenue (AOP)"))
            fig.add_trace(go.Bar(x=months, y=monthly["spend"], name="Spend (AOP)"))
            fig.add_shape(type="line", x0=months[split_i], x1=months[split_i], y0=0, y1=1,
                          yref="paper", line=dict(color="#c62828", dash="dash", width=2))
            fig.add_annotation(x=months[0], y=1.08, text="AOP actual (booked)", showarrow=False, xref="x")
            if split_i < len(months) - 1:
                fig.add_annotation(x=months[-1], y=1.08, text="Future plan", showarrow=False, xref="x")
            fig.update_layout(barmode="group", height=420, legend=dict(orientation="h"))
            st.plotly_chart(fig, width="stretch")
            download_button("⬇ Download AOP monthly (filtered)", monthly, "aop_monthly.csv")
        with c2:
            r = monthly.dropna(subset=["roas"])
            if len(r):
                fig = px.line(r, x="month", y="roas", title="ROAS (revenue ÷ spend)")
                fig.add_hline(y=1, line=dict(color="#c62828", dash="dot"))
                fig.update_layout(height=420)
                st.plotly_chart(fig, width="stretch")
                low = r[r["roas"] < 1]
                if len(low):
                    st.warning(f"ROAS below 1.0 in {len(low)} month(s) of the filtered set "
                               f"({low['month'].iloc[0]} → {low['month'].iloc[-1]}).")
        with c3:
            cc = aop["category_col"]
            rev_share = aop_category_share(aop, "revenue", **kw)
            sp_share = aop_category_share(aop, "spend", **kw)
            if len(rev_share):
                st.markdown("**Revenue share by category**")
                fig = px.area(rev_share, x=rev_share.columns, y=rev_share.index,
                              orientation="h", title="Revenue share by category (sums to 100%)")
                fig.update_layout(height=max(380, 34 * len(rev_share) + 120))
                st.plotly_chart(fig, width="stretch")
                download_button("⬇ Download revenue share", rev_share.reset_index(), "aop_revenue_share.csv")
            if len(sp_share):
                st.markdown("**Spend share by category**")
                fig = px.area(sp_share, x=sp_share.columns, y=sp_share.index,
                              orientation="h", title="Spend share by category (sums to 100%)")
                fig.update_layout(height=max(380, 34 * len(sp_share) + 120))
                st.plotly_chart(fig, width="stretch")
                download_button("⬇ Download spend share", sp_share.reset_index(), "aop_spend_share.csv")
        with c4:
            m = monthly.set_index("month")
            mom_rev = m["revenue"].pct_change()
            mom_sp = m["spend"].pct_change()
            g = pd.DataFrame({"month": m.index, "rev_mom": mom_rev, "spend_mom": mom_sp})
            fig = px.line(g, x="month", y=["rev_mom", "spend_mom"],
                          labels={"value": "MoM %", "variable": "Series"},
                          title="MoM growth of filtered AOP totals (revenue vs spend)")
            fig.update_yaxes(tickformat=".0%")
            fig.update_layout(height=420)
            st.plotly_chart(fig, width="stretch")
            fy = aop_fy(aop, categories=aop_cats or None)
            if len(fy):
                st.markdown("**FY comparison (per AOP sheet: Actual Rev / Exit ARR / SD ARR)**")
                fyv = fy[fy["fy"].notna()].groupby("fy")[["Actual Rev", "Exit ARR", "SD ARR"]].sum() \
                    if all(c in fy.columns for c in ["Actual Rev", "Exit ARR", "SD ARR"]) else fy
                disp = fyv.copy()
                for c in disp.columns:
                    disp[c] = disp[c].map(fmt_money)
                st.dataframe(disp, width="stretch")
                if all(c in fyv.columns for c in ["Actual Rev", "Exit ARR", "SD ARR"]):
                    plot = fyv.reset_index().melt(id_vars="fy", value_vars=["Actual Rev", "Exit ARR", "SD ARR"],
                                                  var_name="series", value_name="value")
                    fig = px.bar(plot, x="fy", y="value", color="series")
                    fig.update_layout(height=400, yaxis_title="₹")
                    st.plotly_chart(fig, width="stretch")
                download_button("⬇ Download AOP FY table", fyv.reset_index(), "aop_fy.csv")
            if len(aop["seasonal"]):
                st.markdown("**Seasonal run-rates (per AOP sheet)**")
                ch = aop["channel_sub_col"]
                seas = aop["seasonal"]
                if ch in seas.columns:
                    seas = seas[seas[ch].str.upper().str.strip() == "TOTAL"]
                show_cols = [c for c in seas.columns if c in
                             (aop["meta_names"] + ["Mar–Jun", "Jul–Sep", "Oct–Dec", "Jan–Feb",
                                                   "Summer Run Rate", "Monsoon Run Rate", "Festive Run Rate",
                                                   "Winter Run Rate", "% inc sum to Mon", "% inc Mon to Fest",
                                                   "% Inc Fes to Win", "% Inc Win to Sum"])]
                st.dataframe(seas[show_cols], width="stretch", height=300)
