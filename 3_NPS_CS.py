"""Page 3 — NPS & Customer Support: brand/product NPS, customer voice,
competitive pull, global remarks (VoC) and CS failure analysis."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import re
from collections import Counter

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import sources
from calculations import competitor_pull, cs_counts, cs_hierarchy, cs_kpis, nps_by_dimension, nps_score_stats, theme_counts
from conclusions import cs_conclusions, nps_conclusions
from formatting import (download_button, fmt_days, fmt_int, fmt_pct, init_page,
                        kpi_cards, render_report, section)

init_page("3 · NPS & Customer Support", "💬",
          "Customer voice (NPS, likes/dislikes, competitive pull, global remarks) and CS failure analysis.")

# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 💬 NPS & CS")
    st.divider()
    mode = st.radio("NPS input", ["Upload CSV", "Paste data"], key="nps_mode")
    if mode == "Upload CSV":
        st.session_state.pop("nps_pasted_raw", None)
        sources.page_uploader("nps")
    else:
        st.caption("Paste a fresh NPS export (CSV format, header row first). Delimiters: comma, tab or semicolon.")
        pasted = st.text_area("Paste NPS data", height=180, key="nps_paste_area",
                              placeholder="id,created_at,customer_id,product_category,...\n1,8/1/2026,123,Face Malai,...")
        if st.button("Parse pasted data", key="nps_parse_btn") and pasted.strip():
            st.session_state["nps_pasted_raw"] = pasted
            st.rerun()
        elif st.session_state.get("nps_pasted_raw"):
            st.caption("✅ Pasted data loaded (" + str(len(str(st.session_state['nps_pasted_raw']).splitlines())) + " lines)")
            if st.button("Clear paste", key="nps_clear_btn"):
                st.session_state["nps_pasted_raw"] = None
                st.session_state["nps_paste_area"] = ""
                st.rerun()
    nps, nps_rep, _ = sources.get_model("nps")
    if nps is not None:
        nd = nps["df"]
        nps_cats = st.multiselect("NPS categories", sorted(nd["category"].replace("", np.nan).dropna().unique()), key="nps_f_cats")
        st.divider()
        st.caption("**CS feedback**")
        sources.page_uploader("cs")
    cs, cs_rep, _ = sources.get_model("cs")
    if cs is not None:
        cfd = cs["df"]
        cs_ft = st.multiselect("Failure type", sorted(cfd["failure_type"].unique()), key="cs_f_ft")
        cs_cats = st.multiselect("CS categories", sorted(cfd["category"].replace("Unspecified", np.nan).dropna().unique()), key="cs_f_cats")
        cs_resolved_only = st.checkbox("Resolved only", value=False, key="cs_f_res")
    if st.button("↺ Reset filters", key="nps_reset"):
        for k in [k for k in st.session_state if k.startswith(("nps_f_", "cs_f_"))]:
            del st.session_state[k]
        st.rerun()

render_report(nps_rep, "NPS data")
render_report(cs_rep, "CS data")

# ===========================================================================
# NPS
# ===========================================================================
st.header("NPS / Customer voice")
if nps is None:
    st.info("Upload or paste NPS data to enable this section.")
else:
    nd = nps["df"].copy()
    if nps_cats:
        nd = nd[nd["category"].isin(nps_cats)]
    brand = nps_score_stats(nd["brand_score"])
    product = nps_score_stats(nd["product_score"])
    kpi_cards([
        ("Responses", fmt_int(brand["n"])),
        ("Brand NPS", f"{brand['nps']:+.0f}"),
        ("Product NPS", f"{product['nps']:+.0f}"),
        ("Promoters (9-10)", fmt_pct(brand["promoters"])),
        ("Passives (7-8)", fmt_pct(brand["passives"])),
        ("Detractors (0-6)", fmt_pct(brand["detractors"])),
    ])
    st.caption(f"Average brand score {brand['avg']:.1f} · average product score {product['avg']:.1f}. "
               "NPS = % promoters − % detractors (standard 0-10 scale).")

    t1, t2 = st.tabs(["📊 Distributions & segments", "👍 Likes / 👎 Dislikes"])
    with t1:
        c1, c2 = st.columns(2)
        with c1:
            bd = brand["dist"].rename_axis("score").reset_index(name="responses")
            fig = px.bar(bd, x="score", y="responses", title="Brand NPS distribution",
                         color=bd["score"].map(lambda s: "Promoter" if s >= 9 else ("Passive" if s >= 7 else "Detractor")),
                         color_discrete_map={"Promoter": "#2e7d32", "Passive": "#f9a825", "Detractor": "#c62828"})
            fig.update_layout(showlegend=False, height=380)
            st.plotly_chart(fig, width="stretch")
        with c2:
            pd_ = product["dist"].rename_axis("score").reset_index(name="responses")
            fig = px.bar(pd_, x="score", y="responses", title="Product NPS distribution",
                         color=pd_["score"].map(lambda s: "Promoter" if s >= 9 else ("Passive" if s >= 7 else "Detractor")),
                         color_discrete_map={"Promoter": "#2e7d32", "Passive": "#f9a825", "Detractor": "#c62828"})
            fig.update_layout(showlegend=False, height=380)
            st.plotly_chart(fig, width="stretch")
        # NPS by category
        cat_nps = []
        for c, g in nd[nd["category"] != ""].groupby("category"):
            cat_nps.append({"category": c, "n": len(g),
                            "brand_nps": nps_score_stats(g["brand_score"])["nps"],
                            "product_nps": nps_score_stats(g["product_score"])["nps"]})
        cat_df = pd.DataFrame(cat_nps).sort_values("n", ascending=False)
        if len(cat_df):
            disp = cat_df.copy()
            disp["brand_nps"] = disp["brand_nps"].map(lambda v: f"{v:+.0f}")
            disp["product_nps"] = disp["product_nps"].map(lambda v: f"{v:+.0f}")
            st.markdown("**NPS by category**")
            st.dataframe(disp, width="stretch", hide_index=True)
            fig = px.bar(cat_df.head(12), x="category", y=["brand_nps", "product_nps"],
                         labels={"value": "NPS", "variable": "Series"})
            fig.update_layout(height=400, xaxis_tickangle=-30)
            st.plotly_chart(fig, width="stretch")
            download_button("⬇ Download NPS by category", cat_df, "nps_by_category.csv")
        # NPS by variant (top by responses)
        var_nps = []
        for v, g in nd[nd["variant"] != ""].groupby("variant"):
            var_nps.append({"variant": v, "n": len(g),
                            "brand_nps": nps_score_stats(g["brand_score"])["nps"]})
        var_df = pd.DataFrame(var_nps).sort_values("n", ascending=False).head(15)
        if len(var_df):
            d2 = var_df.copy()
            d2["brand_nps"] = d2["brand_nps"].map(lambda v: f"{v:+.0f}")
            st.markdown("**NPS by variant (top 15 by responses)**")
            st.dataframe(d2, width="stretch", hide_index=True)
            download_button("⬇ Download NPS by variant", var_df, "nps_by_variant.csv")
        # demographic dimensions — only if populated
        demo_tabs = st.tabs([name for name in ["Age", "Skin type", "Hair type"] if nps["has_demos"].get({"Age": "age", "Skin type": "skin_type", "Hair type": "hair_type"}[name])])
        colmap_d = {"Age": "age_bucket", "Skin type": "skin_type_1", "Hair type": "hair_type_1"}
        for tab, name in zip(demo_tabs, [n for n in ["Age", "Skin type", "Hair type"] if nps["has_demos"].get({"Age": "age", "Skin type": "skin_type", "Hair type": "hair_type"}[n])]):
            with tab:
                col = colmap_d[name]
                rows = []
                for v, g in nd[nd[col].notna() & (nd[col] != "")].groupby(col):
                    rows.append({"segment": v, "n": len(g),
                                 "brand_nps": nps_score_stats(g["brand_score"])["nps"],
                                 "product_nps": nps_score_stats(g["product_score"])["nps"]})
                dd = pd.DataFrame(rows).sort_values("n", ascending=False)
                d3 = dd.copy()
                d3["brand_nps"] = d3["brand_nps"].map(lambda v: f"{v:+.0f}")
                d3["product_nps"] = d3["product_nps"].map(lambda v: f"{v:+.0f}")
                st.dataframe(d3, width="stretch", hide_index=True)
                if len(dd):
                    fig = px.bar(dd, x="segment", y=["brand_nps", "product_nps"],
                                 labels={"value": "NPS", "variable": "Series"})
                    fig.update_layout(height=360, xaxis_tickangle=-30)
                    st.plotly_chart(fig, width="stretch")
    with t2:
        likes = theme_counts(nps, "like")
        dislikes = theme_counts(nps, "dislike")
        if not nps["has_like_brand"] and not nps["has_dislike_brand"]:
            st.caption("The brand-level like/dislike columns are empty in this export — product-level themes are used.")
        c1, c2 = st.columns(2)
        with c1:
            if len(likes):
                d = likes.head(12).iloc[::-1].copy()
                fig = px.bar(d, x="mentions", y="theme", orientation="h", title="Top things customers LIKE")
                fig.update_layout(height=520, yaxis=dict(automargin=True))
                st.plotly_chart(fig, width="stretch")
                dl = likes.copy()
                dl["pct_of_responses"] = dl["pct_of_responses"].map(fmt_pct)
                st.dataframe(dl.head(15)[["theme", "mentions", "pct_of_responses"]], width="stretch", hide_index=True)
                download_button("⬇ Download like themes", likes, "nps_likes.csv")
            else:
                st.info("No like themes in this data.")
        with c2:
            if len(dislikes):
                dn = dislikes[~dislikes["theme"].str.lower().str.contains("no complaints")].head(12).iloc[::-1].copy()
                fig = px.bar(dn, x="mentions", y="theme", orientation="h", title="Top things customers DON'T like")
                fig.update_layout(height=520, yaxis=dict(automargin=True))
                st.plotly_chart(fig, width="stretch")
                dl = dislikes[~dislikes["theme"].str.lower().str.contains("no complaints")].head(15).copy()
                dl["pct_of_responses"] = dl["pct_of_responses"].map(fmt_pct)
                st.dataframe(dl[["theme", "mentions", "pct_of_responses"]], width="stretch", hide_index=True)
                download_button("⬇ Download dislike themes", dislikes, "nps_dislikes.csv")
            else:
                st.info("No dislike themes in this data.")
        # competitive pull
        comp = competitor_pull(nps)
        if len(comp):
            st.markdown("**Brand migration — who are we winning customers from?**")
            first = comp[comp["is_first_time"]]
            rest = comp[~comp["is_first_time"]]
            if len(first):
                st.markdown(f" **First-time customers:** {fmt_int(first.iloc[0]['customers'])} "
                            f"({fmt_pct(first.iloc[0]['share'])} of respondents)")
            if len(rest):
                dr = rest.copy()
                dr["customers"] = dr["customers"].map(fmt_int)
                dr["share"] = dr["share"].map(fmt_pct)
                st.dataframe(dr.rename(columns={"source": "previous brand"}), width="stretch", hide_index=True)
                fig = px.bar(rest.head(10), x="source", y="customers")
                fig.update_layout(height=360, xaxis_tickangle=-30, yaxis_title="customers")
                st.plotly_chart(fig, width="stretch")
                download_button("⬇ Download competitive pull", comp, "nps_competitive_pull.csv")

    st.divider()
    section("Automated NPS conclusion")
    by_cat = pd.DataFrame()
    try:
        for c, g in nd[nd["category"] != ""].groupby("category"):
            by_cat = pd.concat([by_cat, pd.DataFrame([{"dimension": c, "n": len(g),
                                                       "brand_nps": nps_score_stats(g["brand_score"])["nps"]}])], ignore_index=True)
    except Exception:
        pass
    for c in nps_conclusions(nps, brand, product, likes, dislikes, comp, by_cat):
        st.markdown(f"- {c}")

# ===========================================================================
# CS
# ===========================================================================
st.divider()
st.header("Customer Support (CS)")
if cs is None:
    st.info("Upload the CS feedback CSV to enable this section.")
else:
    d = cs["df"].copy()
    if cs_ft:
        d = d[d["failure_type"].isin(cs_ft)]
    if cs_cats:
        d = d[d["category"].isin(cs_cats)]
    if cs_resolved_only:
        d = d[d["chat_status"].str.lower().isin(["resolved", "closed", "solved"])]
    k = cs_kpis({"df": d})
    kpi_cards([
        ("Tickets", fmt_int(k["tickets"])),
        ("Resolved %", fmt_pct(k["resolved_pct"])),
        ("Unresolved %", fmt_pct(k["unresolved_pct"])),
        ("Top failure type", k["top_failure_type"][:26]),
        ("Top failure reason", k["top_failure_reason"][:26]),
        ("Median fulfil→delivery", fmt_days(k["median_fulfil_hours"])),
    ])
    if _ok_pct := (k.get("pct_over_72h") is not None and not (isinstance(k["pct_over_72h"], float) and np.isnan(k["pct_over_72h"]))):
        st.caption(f"{fmt_pct(k['pct_over_72h'])} of ticketed orders took more than 72 hours fulfilment→delivery "
                   f"({fmt_int(k['n_with_fulfil_times'])} tickets with timestamps).")
    t1, t2, t3 = st.tabs([" Failure hierarchy", "📊 Breakdowns", "🗣️ Global remarks (VoC)"])
    with t1:
        h = cs_hierarchy({"df": d})
        if len(h):
            n = len(h)
            fig = go.Figure(go.Sunburst(
                labels=list(h["failure_type"]) + list(h["failure_reason"]) + list(h["failure_subreason"]),
                parents=[""] * n + [str(i) for i in range(n)] + [str(n + i) for i in range(n)],
                values=list(h["tickets"]),
                branchvalues="total",
                textinfo="label+value"))
            fig.update_layout(title="Failure type → reason → subreason", height=560)
            st.plotly_chart(fig, width="stretch")
            download_button("⬇ Download CS ticket hierarchy", h, "cs_hierarchy.csv")
    with t2:
        c1, c2 = st.columns(2)
        with c1:
            bc = cs_counts({"df": d}, "category")
            if len(bc):
                fig = px.bar(bc.head(12), x="category", y="tickets", title="Tickets by category")
                fig.update_layout(height=400, xaxis_tickangle=-30)
                st.plotly_chart(fig, width="stretch")
                download_button("⬇ Download tickets by category", bc, "cs_by_category.csv")
            bp = d[d["products_impacted"] != "Unspecified"]["products_impacted"].value_counts().head(10)
            if len(bp):
                fig = px.bar(pd.DataFrame({"product": bp.index, "tickets": bp.values}).iloc[::-1],
                             x="tickets", y="product", orientation="h", title="Top impacted products")
                fig.update_layout(height=420, yaxis=dict(automargin=True))
                st.plotly_chart(fig, width="stretch")
        with c2:
            bf = d["failure_type"].value_counts()
            fig = px.bar(pd.DataFrame({"type": bf.index, "tickets": bf.values}).iloc[::-1],
                         x="tickets", y="type", orientation="h", title="Tickets by failure type")
            fig.update_layout(height=320, yaxis=dict(automargin=True))
            st.plotly_chart(fig, width="stretch")
            if cs["team_present"] and not cs["team_empty"]:
                bt = cs_counts({"df": d}, "responsible_team")
                if len(bt):
                    fig = px.bar(bt, x="responsible_team", y="tickets", title="Tickets by responsible team")
                    fig.update_layout(height=300, xaxis_tickangle=-30)
                    st.plotly_chart(fig, width="stretch")
                    download_button("⬇ Download tickets by team", bt, "cs_by_team.csv")
            else:
                st.info("Responsible team is not available in this export.")
    with t3:
        st.caption("Searchable customer remarks (global remark + case remarks). Filters: category, product, failure type, date, text search.")
        rd = d[d["global_remark"].ne("") | d["remarks"].ne("")].copy()
        f_cat = st.selectbox("Category", ["All"] + sorted(rd["category"].replace("Unspecified", np.nan).dropna().unique()), key="voc_cat")
        f_prod = st.text_input("Product contains…", key="voc_prod")
        f_ft = st.selectbox("Failure type", ["All"] + sorted(rd["failure_type"].unique()), key="voc_ft")
        f_date = st.date_input("Created on/after", value=None, key="voc_date")
        f_text = st.text_input("Search remarks…", key="voc_text")
        vv = rd
        if f_cat != "All":
            vv = vv[vv["category"] == f_cat]
        if f_prod:
            vv = vv[vv["products_impacted"].str.contains(f_prod, case=False, na=False) |
                     vv["products_ordered"].str.contains(f_prod, case=False, na=False)]
        if f_ft != "All":
            vv = vv[vv["failure_type"] == f_ft]
        if f_date is not None:
            vv = vv[vv["created_at"] >= f_date]
        if f_text:
            rx = re.compile(re.escape(f_text), re.I)
            vv = vv[vv["global_remark"].str.contains(rx, na=False) | vv["remarks"].str.contains(rx, na=False)]
        show = vv.sort_values("created_at", ascending=False).head(100)
        st.markdown(f"**{len(vv)} remark(s)** — showing the latest {len(show)}")
        if len(show):
            disp = pd.DataFrame({
                "date": show["created_at"].map(str),
                "category": show["category"],
                "product": show["products_impacted"],
                "failure": show["failure_reason"],
                "remark": show["global_remark"].where(show["global_remark"] != "", show["remarks"]),
            })
            st.dataframe(disp, width="stretch", hide_index=True, height=420)
            download_button("⬇ Download filtered remarks", disp, "voc_remarks.csv")
        # repeated themes (light bag-of-words over failure subreason + remark text)
        words = Counter()
        stop = set(("the a an and or of to in for with on at is are was were i my me we our you your it this that as by from "
                   "not no yes do does did have has had will would can could please very much more some just really really "
                   "thanks thank you good fine ok okay but so if then than there here what which who how why when where "
                   "product products order orders issue customer want need").split())
        for v in d["failure_subreason"]:
            words[v.title()] += 1
        for v in d["global_remark"].head(500):
            for w in re.findall(r"[A-Za-z]{4,}", v.lower()):
                if w not in stop:
                    words[w.title()] += 1
        top_w = words.most_common(12)
        if top_w:
            st.markdown("**Repeated themes** (keyword frequency across remarks + failure subreasons)")
            fig = px.bar(pd.DataFrame(top_w, columns=["theme", "count"]).iloc[::-1], x="count", y="theme", orientation="h")
            fig.update_layout(height=420, yaxis=dict(automargin=True))
            st.plotly_chart(fig, width="stretch")

    st.divider()
    section("Automated CS conclusion")
    for c in cs_conclusions({"df": d}, k):
        st.markdown(f"- {c}")
