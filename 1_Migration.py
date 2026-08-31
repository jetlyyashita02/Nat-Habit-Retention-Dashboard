"""Page 1 — Migration: inter-category / inter-variant / SKU migration from
customer-level journey data + the Seasonality & Migration summary sheet."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import sources
from calculations import migration_analysis
from conclusions import migration_conclusions
from formatting import (download_button, fmt_days, fmt_int, fmt_pct, init_page,
                        kpi_cards, render_report, section)

init_page("1 · Migration", "🔀",
          "Where customers move after their first purchase — inter-category, inter-variant and SKU level, plus the "
          "Seasonality & Migration summary sheet.")

# ---------------------------------------------------------------------------
# sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 🔀 Migration")
    st.divider()
    page_uploader_rep = sources.page_uploader("journey",
        "Customer-level export — either long form (customer id, order id, order date, sku/variant, category, "
        "channel) or the wide 'base sheet' (one row per customer with first/second/.../sixth order columns, "
        "multi-line orders comma-separated). Without it, customer-level migration cannot be calculated.")
    model, rep, meta = sources.get_model("journey")

    st.divider()
    st.caption("Category-scoped sales (intra-category movement):")
    sources.page_uploader("category_sales",
        "Category-scoped sales aggregate (date, sku, channel, short code, category, orders, customers, qty, rev). "
        "Sample = Moisturisers, 25 Jul – 23 Aug 2026. No customer ids — SKU/grammage-level movement only.")

    level = "Category"
    entry = "All"
    channels_sel = []
    cohorts_sel = []
    max_gap = 0.0
    if model is not None:
        o = model["orders"]
        level = st.radio("Migration level", ["Category", "Variant", "SKU"], horizontal=True)
        level_key = {"Category": "category", "Variant": "product", "SKU": "sku"}[level]
        first = o[o["is_first"]]
        entry = st.multiselect("Entry " + level.lower() + " (1st order)",
                               sorted(first[level_key].unique()),
                               key="mig_f_entry")
        ch_avail = sorted([c for c in first["channel"].unique() if c])
        channels_sel = st.multiselect("Channel (1st order)", ch_avail, key="mig_f_ch")
        coh_avail = sorted(first["cohort_month"].dropna().unique())
        cohorts_sel = st.multiselect("Cohort months (1st order)", coh_avail, key="mig_f_coh")
        max_gap = st.number_input("Max days 1→2 (0 = no cap)", 0, 1800, 0, 30,
                                  key="mig_f_gap")
        if st.button("↺ Reset filters", key="mig_reset"):
            for k in [k for k in st.session_state if k.startswith("mig_f_")]:
                del st.session_state[k]
            st.rerun()
    st.divider()
    st.caption("Sheet source (seasonality & aggregates):")
    sources.page_uploader("migr_seasonality")

render_report(rep, "Journey data")
if model is None:
    st.info("Customer-level migration needs the journey source. Upload a customer × order CSV — "
            "the Seasonality & Migration summary sheet is still shown below.")

# ---------------------------------------------------------------------------
# KPIs + analysis
# ---------------------------------------------------------------------------
if model is not None:
    level_key = {"Category": "category", "Variant": "product", "SKU": "sku"}[level]
    mig = migration_analysis(
        model, level_key.lower() if level_key != "product" else "variant",
        entry_filter=entry or None, channel_filter=channels_sel or None,
        cohort_months=cohorts_sel or None,
        max_gap_days=None if max_gap == 0 else max_gap)

    kpi_cards([
        ("Customers acquired", fmt_int(mig["n_acquired"])),
        ("With 2nd order", f"{fmt_int(mig['n_second'])} ({fmt_pct(mig['any_second_pct'])})"),
        ("Repeat / stay %", fmt_pct(mig["repeat_pct"])),
        ("Migration / switch %", fmt_pct(mig["switch_pct"])),
        ("Avg days 1→2", fmt_days(mig["avg_days_1_2"])),
        ("Top destination", mig["top_destination"][:28]),
    ])

    tab1, tab2, tab3, tab4 = st.tabs(["🔁 Migration matrix", "🧭 Top flows",
                                      "📊 Retention vs outflow", "⚖️ Net migration"])
    with tab1:
        show_pct = st.toggle("Show as % of entry (row-normalised)", value=False)
        matrix = mig["matrix_pct"] if show_pct else mig["matrix"]
        order = mig["retention_outflow"]["entry"]
        rows = [e for e in order if e in matrix.index][:15]
        cols = matrix.sum(axis=0).sort_values(ascending=False).index[:12]
        view = matrix.loc[rows, cols]
        disp = pd.DataFrame(
            [[fmt_pct(v) if show_pct else fmt_int(v) for v in view.loc[r]] for r in rows],
            index=view.index, columns=view.columns)
        disp.index.name = f"1st order {level.lower()}"
        st.dataframe(disp, width="stretch")
        cap = "Cells: unique customers (or % of that entry group) whose 2nd order landed in the column " + level.lower() + "."
        if len(matrix) > len(rows):
            cap += f" Showing top {len(rows)} of {len(matrix)} entries."
        st.caption(cap)
        if st.checkbox("Heatmap view", value=False, key="mig_heat"):
            fig = go.Figure(go.Heatmap(z=matrix.loc[rows, cols].values, x=[str(c)[:18] for c in cols],
                                       y=[str(r)[:24] for r in rows],
                                       colorscale="Blues", texttemplate="%{text}"))
            fig.update_layout(height=max(420, 34 * len(rows) + 120))
            st.plotly_chart(fig, width="stretch")
        dl = view.reset_index().rename(columns={"index": f"entry_{level.lower()}"})
        if not show_pct:
            dl.columns = [str(c) for c in dl.columns]
        download_button("⬇ Download migration matrix (counts)",
                        mig["matrix"].loc[rows, cols].reset_index().rename(columns={"index": f"entry_{level.lower()}"}),
                        "migration_matrix.csv")

    with tab2:
        fl = mig["flows"]
        if len(fl):
            disp = fl.copy()
            disp["customers"] = disp["customers"].map(fmt_int)
            disp["% of switchers"] = disp["pct_of_switchers"].map(fmt_pct)
            st.dataframe(disp[["entry", "destination", "customers", "% of switchers"]],
                         width="stretch", hide_index=True)
            top = fl.head(12).copy()
            top["flow"] = top["entry"] + " → " + top["destination"]
            fig = px.bar(top.iloc[::-1], x="customers", y="flow", orientation="h",
                         title="Top 12 switch flows")
            fig.update_layout(height=480, xaxis_title="customers", yaxis=dict(automargin=True))
            st.plotly_chart(fig, width="stretch")
            download_button("⬇ Download migration flows", fl, "migration_flows.csv")
        else:
            st.info("No switches observed in the current filter selection.")

    with tab3:
        t = mig["retention_outflow"]
        disp = t.copy()
        disp["acquired"] = disp["acquired"].map(fmt_int)
        disp["same %"] = disp["same_pct"].map(fmt_pct)
        disp["switched %"] = disp["switched_pct"].map(fmt_pct)
        disp["avg days 1→2"] = disp["avg_days_1_2"].map(fmt_days)
        st.dataframe(disp.rename(columns={"entry": level.lower(), "second_orders": "2nd orders",
                                          "top_destination": "top destination"}),
                     width="stretch", hide_index=True)
        st.caption("Denominator for same % / switched %: customers acquired in the entry " + level.lower() +
                   " (with the current filters).")
        download_button("⬇ Download retention vs outflow", t, "migration_retention_outflow.csv")

    with tab4:
        net = mig["net"]
        disp = net.copy()
        disp["gained"] = disp["gained"].map(fmt_int)
        disp["lost"] = disp["lost"].map(fmt_int)
        disp["net"] = disp["net"].map(lambda v: f"+{int(v):,}" if v > 0 else f"{int(v):,}")
        disp["status"] = np.where(net["net"] > 0, "🟢 gainer", np.where(net["net"] < 0, "🔴 loser", "⚪ flat"))
        st.dataframe(disp.rename(columns={"entity": level.lower()}), width="stretch", hide_index=True)
        fig = px.bar(net, x="net", y=net["entity"].astype(str), orientation="h",
                     color=net["net"].map(lambda v: "gainer" if v > 0 else "loser"),
                     color_discrete_map={"gainer": "#2e7d32", "loser": "#c62828"})
        fig.update_layout(height=max(420, 30 * len(net) + 120), xaxis_title="net customers gained − lost")
        st.plotly_chart(fig, width="stretch")
        st.caption("Net = customers whose 1st order was elsewhere but 2nd order is here (gained) minus the reverse. "
                   "Only customers with an observed 2nd order are included.")
        download_button("⬇ Download net migration", net, "migration_net.csv")

    st.divider()
    section("Business interpretation")
    for c in migration_conclusions(mig):
        st.markdown(f"- {c}")

# ---------------------------------------------------------------------------
# intra-category movement — category-scoped sales (no customer ids)
# ---------------------------------------------------------------------------
st.divider()
st.header("🧴 Intra-category movement — category-scoped sales")
st.caption("From the category-scoped sales export (sample: Moisturisers, 25 Jul – 23 Aug 2026). "
           "This source is **aggregated — it has no customer/order ids** — so this section measures "
           "SKU- and grammage-level revenue-share movement (1st half of the window vs 2nd half). "
           "It is a complement to, not a replacement for, customer-level migration above.")
cs_model, cs_rep, _ = sources.get_model("category_sales")
render_report(cs_rep, "Category-scoped sales")
if cs_model is None:
    st.info("Upload a category-scoped sales CSV to enable intra-category movement.")
else:
    from calculations import intra_category_movement
    mv = intra_category_movement(cs_model["df"])
    if not mv.get("ok"):
        st.warning(f"Intra-category movement not computed: {mv.get('reason', 'unknown reason')}")
    else:
        w0, w1, mid = mv["window"]
        sk = mv["sku"]
        n_in, n_ex = int((sk["status"] == "Entered").sum()), int((sk["status"] == "Exited").sum())
        cont = sk[sk["status"] == "Continuing"]
        gainer = cont.loc[cont["delta_pp"].idxmax()] if len(cont) else None
        loser = cont.loc[cont["delta_pp"].idxmin()] if len(cont) else None
        kpi_cards([
            ("Window", f"{w0} → {w1} (split {mid})"),
            ("SKUs in scope", fmt_int(mv["n_skus"])),
            ("Entered in 2nd half", fmt_int(n_in)),
            ("Exited before 2nd half", fmt_int(n_ex)),
            ("Top gainer", f"{gainer['sku']} ({gainer['delta_pp']:+.2f} pp)" if gainer is not None and gainer["delta_pp"] > 0 else "—"),
            ("Top loser", f"{loser['sku']} ({loser['delta_pp']:+.2f} pp)" if loser is not None and loser["delta_pp"] < 0 else "—"),
        ])
        st.caption("Share = SKU revenue ÷ total revenue in that half; delta in percentage points. "
                   "Entered/Exited = revenue in one half only (window edge effects possible).")
        t1, t2, t3, t4 = st.tabs(["SKU share shift", "Entered / exited", "Grammage rollup", "Top SKU trend"])
        with t1:
            disp = sk[["sku", "product", "status", "rev_1st", "rev_2nd", "share_1st", "share_2nd", "delta_pp"]].copy()
            for c in ["share_1st", "share_2nd"]:
                disp[c] = disp[c].map(fmt_pct)
            disp["delta_pp"] = disp["delta_pp"].map(lambda v: f"{v:+.2f} pp")
            download_button("⬇ Download SKU share shift", sk, "intra_sku_share_shift.csv")
            st.dataframe(disp, width="stretch", height=430)
        with t2:
            ent = sk[sk["status"] == "Entered"].sort_values("rev_2nd", ascending=False)
            exi = sk[sk["status"] == "Exited"].sort_values("rev_1st", ascending=False)
            st.markdown(f"**Entered in the 2nd half ({len(ent)})**")
            if len(ent):
                st.dataframe(ent[["sku", "product", "rev_2nd", "share_2nd"]], width="stretch", height=220)
                download_button("⬇ Download entered SKUs", ent, "intra_entered.csv")
            else:
                st.caption("None — every SKU with 2nd-half revenue also sold in the 1st half.")
            st.markdown(f"**Exited before the 2nd half ({len(exi)})**")
            if len(exi):
                st.dataframe(exi[["sku", "product", "rev_1st", "share_1st"]], width="stretch", height=220)
                download_button("⬇ Download exited SKUs", exi, "intra_exited.csv")
            else:
                st.caption("None.")
        with t3:
            gg = mv["grammage"]
            if len(gg):
                gdisp = gg.copy()
                for c in ["share_1st", "share_2nd"]:
                    gdisp[c] = gdisp[c].map(fmt_pct)
                gdisp["delta_pp"] = gdisp["delta_pp"].map(lambda v: f"{v:+.2f} pp")
                st.caption("Grammage = size encoded in the SKU code (e.g. -250) + unit from the product name "
                           "where present; unlabelled sizes are merged with their unit when unambiguous.")
                download_button("⬇ Download grammage rollup", gg, "intra_grammage.csv")
                st.dataframe(gdisp, width="stretch", height=320)
            else:
                st.info("No size codes detected in the SKU column.")
        with t4:
            tr = mv["trend"]
            if len(tr):
                fig = px.line(tr, x="dt", y="revenue", color="sku",
                              title="Top 10 SKUs by total revenue — daily revenue")
                fig.update_layout(height=420, legend=dict(orientation="h"), xaxis_title="")
                st.plotly_chart(fig, width="stretch")
                download_button("⬇ Download top-SKU daily revenue", tr, "intra_top_sku_daily.csv")
            else:
                st.info("No trend rows.")

# ---------------------------------------------------------------------------
# summary sheet section
# ---------------------------------------------------------------------------
st.divider()
st.header("📄 Seasonality & Migration summary sheet")
st.caption("Aggregate export (seasonality, V2V/V2C loyalty, grammage transitions, order frequency). "
           "Upload the fresh version of this sheet to refresh.")
st.caption("Note: this sheet is displayed as-is. Its grammage-transition 'entry' figures could not be "
           "exactly reproduced from the base sheet (its entry-cohort definition is not documented); the "
           "customer-level figures elsewhere on this page are computed directly from the base-sheet orders. "
           "Both views agree on direction (e.g. Aloe Vera is losing customers) even where definitions differ.")
sm, sm_rep, _ = sources.get_model("migr_seasonality")
render_report(sm_rep, "Summary sheet")
if sm is not None:
    t1, t2, t3 = st.tabs(["Seasonality", "Order frequency", "Grammage transitions"])
    with t1:
        if "seasonality" in sm and len(sm["seasonality"]):
            s = sm["seasonality"].copy()
            num_cols = [c for c in ["Winter (Dec", "Pre-Summer", "Summer", "Monsoon", "Post-Monsoon", "total_orders"]
                        if c in s.columns]
            s["avg gap (days)"] = s.get("avg_purchase_gap_days")
            disp = s[["variant"] + num_cols + ["peak_season", "avg gap (days)", "season_match", "seasonality_strength"]].copy()
            for c in num_cols:
                disp[c] = disp[c].map(fmt_int)
            st.dataframe(disp, width="stretch", hide_index=True)
            fig = px.bar(s.dropna(subset=[num_cols[0]] if num_cols else []), x="variant",
                         y=num_cols, title="Orders by season",
                         labels={c: c for c in num_cols})
            fig.update_layout(height=460)
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No seasonality block found in this sheet version.")
    with t2:
        if "order_freq" in sm and len(sm["order_freq"]):
            o = sm["order_freq"].copy()
            o["drop off %"] = o["dropoff_pct"].map(fmt_pct)
            o["repeat score %"] = o["retention_score_pct"].map(fmt_pct)
            for c in ["unique_users", "bought_once", "bought_twice", "loyal_3_4", "loyal_5_6",
                      "avg_days_1_2", "avg_days_2_3", "avg_gap"]:
                if c in o.columns:
                    o[c] = o[c].map(fmt_int)
            st.dataframe(o[["category", "variant", "unique_users", "bought_once", "bought_twice",
                            "loyal_3_4", "loyal_5_6", "drop off %", "avg_days_1_2",
                            "avg_days_2_3", "avg_gap", "repeat score %"]],
                         width="stretch", hide_index=True)
            download_button("⬇ Download order-frequency table", o, "order_frequency.csv")
        else:
            st.info("No order-frequency block found in this sheet version.")
    with t3:
        if "grammage" in sm and len(sm["grammage"]):
            g = sm["grammage"].copy()
            for c in ["Total Next Purchases", "Repeated Exact Same Product", "Repeated Same Size (Any Variant)",
                      "Upsized To (Count)", "Lateral Switch (Count)", "Downsized To (Count)"]:
                if c in g.columns:
                    g[c] = g[c].map(fmt_int)
            for c in ["Repeat %", "Upsize %", "Downsize %"]:
                if c in g.columns:
                    g[c] = g[c].map(fmt_pct)
            st.dataframe(g, width="stretch", hide_index=True, height=420)
        if "quarterly_moves" in sm and len(sm["quarterly_moves"]):
            q = sm["quarterly_moves"].copy()
            q["repeat %"] = q["repeat_pct"].map(fmt_pct)
            q["move %"] = q["move_pct"].map(fmt_pct)
            st.subheader("Quarterly upsize / downsize detail")
            st.dataframe(q, width="stretch", hide_index=True)
    if sm.get("conclusions"):
        st.markdown("**Sheet conclusions**")
        for q, a in sm["conclusions"]:
            st.markdown(f"- **{q}** — {a}")
    if "v2v_v2c_sheet" in sm and len(sm["v2v_v2c_sheet"]) and \
            sm["v2v_v2c_sheet"]["V2V Loyalty"].notna().any():
        st.subheader("V2V / V2C loyalty (from sheet)")
        st.dataframe(sm["v2v_v2c_sheet"], width="stretch", hide_index=True)
