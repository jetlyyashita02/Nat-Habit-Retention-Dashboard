"""Page 5 — Retention + Metabase V2V/V2C.

V2V (variant loyalty)  = customers whose 2nd order is the SAME VARIANT as the 1st
                          / customers with a qualifying (observed) 2nd order
V2C (category loyalty) = customers whose 2nd order stays in the SAME CATEGORY
                          / customers with a qualifying (observed) 2nd order
They are computed separately and are NOT the same metric (V2C >= V2V by construction).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import sources
from calculations import fm_retention_table, journey_retention, v2v_v2c_analysis
from conclusions import retention_conclusions
from formatting import (download_button, fmt_int, fmt_pct, fmt_pct_auto, init_page,
                        kpi_cards, render_report, section)

init_page("5 · Retention & V2V/V2C", "⏳",
          "Metabase-style retention windows (Retention FM) + computed retention, V2V / V2C loyalty from journey data.")

# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### ⏳ Retention")
    st.divider()
    st.caption("**Retention FM (sheet)**")
    sources.page_uploader("retention_fm")
    fm, fm_rep, _ = sources.get_model("retention_fm")
    as_of = st.date_input("As-of date (cohort maturity)", value=pd.Timestamp.now().date(), key="ret_asof")
    st.divider()
    st.caption("**Computed (journey)**")
    sources.page_uploader("journey")
    jmodel, j_rep, _ = sources.get_model("journey")
    j_level = "Category"
    j_cohorts = None
    if jmodel is not None:
        j_level = st.radio("Computed retention level", ["Category", "Variant", "SKU"], horizontal=True, key="ret_jlvl")
        first = jmodel["orders"][jmodel["orders"]["is_first"]]
        coh = sorted(first["cohort_month"].dropna().unique())
        j_cohorts = st.multiselect("Cohort months", coh, key="ret_jcoh")
    if st.button("↺ Reset filters", key="ret_reset"):
        for k in [k for k in st.session_state if k.startswith("ret_")]:
            del st.session_state[k]
        st.rerun()

render_report(fm_rep, "Retention FM")
render_report(j_rep, "Journey data")

# ===========================================================================
# METABASE TABLE (Retention FM)
# ===========================================================================
st.header("Metabase retention table (Retention FM)")
if fm is None:
    st.info("Upload the Retention FM CSV to enable the Metabase table.")
else:
    rt, windows = fm["df"], fm["windows"]
    vals, mat = fm_retention_table(rt, windows, as_of)

    level = st.radio("Level", ["Variant (SKU)", "Category"], horizontal=True, key="ret_metabase_lvl")

    def aggregate(group_col):
        rows = []
        for gname, g in rt.groupby(group_col, observed=True):
            row = {group_col: gname, "customers": g["customers"].sum()}
            for w in windows:
                vc, mc = vals.loc[g.index, f"w{w}"], mat.loc[g.index, f"w{w}"]
                ok = mc & vc.notna()
                if ok.any():
                    row[f"w{w}"] = (vc[ok] * g["customers"][ok]).sum() / g["customers"][ok].sum()
                    row[f"m{w}"] = True
                else:
                    row[f"w{w}"] = np.nan
                    row[f"m{w}"] = False
            rows.append(row)
        return pd.DataFrame(rows).set_index(group_col)

    if level == "Category":
        agg = aggregate("category")
        name_col = "category"
    else:
        cols = ["customers"] + [f"w{w}" for w in windows]
        agg = rt.set_index("sku")[cols].copy()
        sub = rt[rt["sku"].isin(agg.index)]
        for w in windows:
            agg[f"m{w}"] = mat.loc[sub.index, f"w{w}"].values
        agg["variant"] = rt.set_index("sku")["variant"]
        name_col = "sku"

    # display
    disp = pd.DataFrame(index=agg.index)
    disp[name_col if level == "Category" else "variant"] = (
        agg["variant"] if level != "Category" else agg.index.astype(str))
    disp["Customer Acquired"] = agg["customers"].map(fmt_int)
    for w in windows:
        v, m = agg[f"w{w}"], agg[f"m{w}"]
        disp[f"{w} Days %"] = [fmt_pct_auto(v[i]) if bool(m[i]) else "Not mature" for i in agg.index]
    disp = disp.sort_values("Customer Acquired", ascending=False)
    st.dataframe(disp, width="stretch", hide_index=True, height=560)
    n_immature = int((~agg[[f"m{w}" for w in windows]].all(axis=1)).sum())
    st.caption(
        "Denominator: customers acquired in each row's cohort (the sheet's 'Customer' column). "
        "A window is **Not mature** when onboarding date + window > as-of date — it is shown as unavailable, never as 0%. "
        f"{n_immature} rows have at least one immature window.")
    # download (numbers as %-numbers, like the sheet)
    dl = pd.DataFrame(index=agg.index)
    dl[name_col if level == "Category" else "variant"] = disp[name_col if level == "Category" else "variant"]
    dl["customers"] = agg["customers"]
    for w in windows:
        dl[f"{w} Days %"] = np.where(agg[f"m{w}"], (agg[f"w{w}"] * 100).round(2), np.nan)
    download_button("⬇ Download Metabase table (FM)", dl.reset_index(), "metabase_retention_fm.csv")

# ===========================================================================
# COMPUTED RETENTION (journey)
# ===========================================================================
st.divider()
st.header("Computed retention (from journey data)")
if jmodel is None:
    st.info("Upload a customer × order CSV to compute retention directly. "
            "The Metabase table above still shows the Retention FM sheet values.")
else:
    lvl_key = {"Category": "category", "Variant": "variant", "SKU": "sku"}[j_level]
    jr = journey_retention(jmodel, lvl_key, as_of=as_of, cohort_months=j_cohorts or None)
    d = jr["df"]
    if d.empty:
        st.info("No cohorts in the selected range.")
    else:
        mature = d[d["mature_days"] > 0]
        wcols = [f"w{w}" for w in [15, 30, 60, 90, 120, 180, 240, 300, 360] if f"w{w}" in d.columns]

        def wavg(wc):
            ok = d[wc].notna()
            if not ok.any():
                return np.nan
            c = d.loc[ok, "customers"]
            return float((d.loc[ok, wc] * c).sum() / c.sum())

        kpi_cards([
            ("Acquired customers", fmt_int(int(d["customers"].sum()))),
            ("30-day retention", fmt_pct_auto(wavg("w30"))),
            ("60-day retention", fmt_pct_auto(wavg("w60"))),
            ("90-day retention", fmt_pct_auto(wavg("w90"))),
            ("180-day retention", fmt_pct_auto(wavg("w180"))),
            ("360-day retention", fmt_pct_auto(wavg("w360"))),
        ])
        st.caption("Denominator: customers whose first (primary-line) order is in the cohort; "
                   "retained@W = any further order within W days. Immature cohort×window cells are excluded (never 0%).")

        t1, t2 = st.tabs([f"By {j_level.lower()}", "Cohort view"])
        with t1:
            agg = []
            for ent, g in d.groupby("entity", observed=True):
                row = {"entity": ent, "customers": int(g["customers"].sum())}
                for wc in wcols:
                    ok = g[wc].notna()
                    row[wc] = float((g.loc[ok, wc] * g.loc[ok, "customers"]).sum() / g.loc[ok, "customers"].sum()) if ok.any() else np.nan
                agg.append(row)
            adf = pd.DataFrame(agg).sort_values("customers", ascending=False)
            disp = adf.copy()
            disp["customers"] = disp["customers"].map(fmt_int)
            for wc in wcols:
                disp[wc.replace("w", "") + "d"] = disp[wc].map(fmt_pct_auto)
            st.dataframe(disp, width="stretch", hide_index=True)
            download_button(f"⬇ Download computed retention ({j_level.lower()})", adf, "computed_retention.csv")
        with t2:
            cagg = d.groupby("cohort", observed=True).apply(
                lambda g: pd.Series({
                    "customers": g["customers"].sum(),
                    **{wc: ((g[wc].fillna(np.nan) * g["customers"]).sum() / g["customers"].sum())
                        if g[wc].notna().any() else np.nan for wc in wcols}
                }), include_groups=False).reset_index()
            # heatmap cohort × window (mature only)
            z = cagg.set_index("cohort")[wcols]
            fig = go.Figure(go.Heatmap(
                z=z.values, x=[w.replace("w", "") + "d" for w in wcols], y=list(z.index)[::-1],
                colorscale="Blues",
                text=[[fmt_pct_auto(v) if not (isinstance(v, float) and np.isnan(v)) else "" for v in row] for row in z.values],
                texttemplate="%{text}"))
            fig.update_layout(height=max(420, 26 * len(z) + 120), xaxis_title="window",
                              yaxis_title="cohort (start → newest)")
            st.plotly_chart(fig, width="stretch")
            # retention curve
            curve = pd.DataFrame({
                "window": [w.replace("w", "") for w in wcols],
                "retention": cagg[wcols].mean(axis=0).values,
            })
            fig = px.line(curve, x="window", y="retention", markers=True,
                          title="Average retention by window (mature cohorts only)")
            fig.update_yaxes(tickformat=".1%")
            fig.update_layout(height=400)
            st.plotly_chart(fig, width="stretch")
            download_button("⬇ Download cohort retention", cagg, "cohort_retention.csv")

# ===========================================================================
# V2V / V2C
# ===========================================================================
st.divider()
st.header("V2V / V2C loyalty")
st.markdown("""
**V2V (variant loyalty)** = customers whose next purchase is the *same product variant* ÷ customers with a qualifying second order
**V2C (category loyalty)** = customers whose next purchase stays in the *same category* (any variant) ÷ customers with a qualifying second order
""")
if jmodel is None:
    st.info("V2V/V2C are computed from journey data — upload a customer × order CSV. "
            "They cannot be derived from the aggregate Retention FM sheet alone.")
else:
    vv = v2v_v2c_analysis(jmodel)
    o = vv["overall"]
    kpi_cards([
        ("Customers with 2nd order", fmt_int(o["qualifying"])),
        ("V2V % (same variant)", fmt_pct(o["v2v_pct"])),
        ("V2C % (same category)", fmt_pct(o["v2c_pct"])),
        ("V2C − V2V gap", fmt_pct((o["v2c_pct"] - o["v2v_pct"]) * 1)),
    ])
    t1, t2 = st.tabs(["By category", "By variant (top 15)"])
    byc = vv["by_category"].copy()
    byc["v2v_pct"] = byc["v2v_pct"].map(fmt_pct)
    byc["v2c_pct"] = byc["v2c_pct"].map(fmt_pct)
    byc["gap"] = byc["gap"].map(fmt_pct)
    byc["qualifying"] = byc["qualifying"].map(fmt_int)
    with t1:
        st.dataframe(byc, width="stretch", hide_index=True)
        download_button("⬇ Download V2V/V2C by category", vv["by_category"], "v2v_v2c_category.csv")
    with t2:
        bvy = vv["by_variant"].head(15).copy()
        bvy["v2v_pct"] = bvy["v2v_pct"].map(fmt_pct)
        bvy["v2c_pct"] = bvy["v2c_pct"].map(fmt_pct)
        bvy["qualifying"] = bvy["qualifying"].map(fmt_int)
        st.dataframe(bvy, width="stretch", hide_index=True)
        download_button("⬇ Download V2V/V2C by variant", vv["by_variant"], "v2v_v2c_variant.csv")
    # strategy matrix
    qual = vv["by_category"][vv["by_category"]["qualifying"] >= 20]
    if len(qual) >= 4:
        med_v, med_c = qual["v2v_pct"].median(), qual["v2c_pct"].median()
        q = qual.copy()
        q["quadrant"] = [
            "High V2V · High V2C (anchor)" if (a >= med_v and b >= med_c)
            else "High V2V · Low V2C (variant-locked)" if a >= med_v
            else "Low V2V · High V2C (category loyal, variant switchers)" if b >= med_c
            else "Low V2V · Low V2C (at risk)"
            for a, b in zip(q["v2v_pct"], q["v2c_pct"])]
        fig = px.scatter(q, x="v2v_pct", y="v2c_pct", text=q["category"],
                         size=q["qualifying"], size_max=28,
                         title="Category strategy matrix (quadrants by median split, n≥20)")
        fig.add_hline(y=med_c, line=dict(color="gray", dash="dot"))
        fig.add_vline(x=med_v, line=dict(color="gray", dash="dot"))
        fig.update_xaxes(tickformat=".0%")
        fig.update_yaxes(tickformat=".0%")
        fig.update_layout(height=460)
        st.plotly_chart(fig, width="stretch")
        dq = q.copy()
        dq["v2v_pct"] = dq["v2v_pct"].map(fmt_pct)
        dq["v2c_pct"] = dq["v2c_pct"].map(fmt_pct)
        dq["qualifying"] = dq["qualifying"].map(fmt_int)
        st.dataframe(dq[["category", "qualifying", "v2v_pct", "v2c_pct", "quadrant"]],
                     width="stretch", hide_index=True)
        download_button("⬇ Download strategy matrix", q, "v2v_v2c_strategy.csv")

st.divider()
section("Business interpretation")
for c in retention_conclusions(
        vals if fm is not None else None,
        mat if fm is not None else None,
        fm["df"] if fm is not None else None,
        vv if jmodel is not None else None,
        fm["windows"] if fm is not None else [],
        as_of):
    st.markdown(f"- {c}")
