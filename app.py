"""
MOISTURISERS INTERACTIVE DASHBOARD
Run:  streamlit run app.py
Drop your full raw dump (CSV) in the sidebar — it auto-detects whether the file
is the wide journey format (Sheet22-style) or a raw order-level export.
"""

from __future__ import annotations

import io

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import etl
import metrics as M

st.set_page_config(page_title="Nat Habit — Retention Dashboard",
                   page_icon="🧴", layout="wide",
                   initial_sidebar_state="expanded")

BRAND = {"Cold Winter": "#2E6F8E", "Hot Dry": "#E4A11B",
         "Hot Humid": "#3C8C6E", "Non-Seasonal (Concern)": "#8E5AA8",
         "Post-Monsoon": "#7A6A55", "Gel": "#C46A4B"}

SAMPLE_PATH = "data/raw_dump.csv"          # <- drop your full 155k dump here
SAMPLE_FALLBACK = "data/sample_journeys.csv"


# ---------------------------------------------------------------- load data
@st.cache_data(show_spinner="Loading file…")
def _load_bytes(b: bytes, fname: str):
    long_df, mode = etl.load_any(io.BytesIO(b))
    return long_df, mode


@st.cache_data(show_spinner="Loading sample…")
def _load_sample():
    import os
    path = SAMPLE_PATH if os.path.exists(SAMPLE_PATH) else SAMPLE_FALLBACK
    return etl.load_journey_csv(path)


# ---------------------------------------------------------------- helpers
def fmt_int(x):
    try:
        return f"{int(x):,}"
    except (TypeError, ValueError):
        return "—"


def fmt_num(x, nd=1):
    try:
        return f"{x:,.{nd}f}"
    except (TypeError, ValueError):
        return "—"


def tile(label, value, delta=None, delta_color="normal"):
    return st.metric(label, value, delta=delta, delta_color=delta_color,
                     border=True)


def csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def dl_button(df, label, fname, key):
    st.download_button(label, data=csv_bytes(df), file_name=fname,
                       mime="text/csv", key=key, width='stretch')


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.title("🧴 Moisturisers")
    st.caption("Cohorts · migration · loyalty · revenue · NPS — category intelligence")

    st.subheader("Data source", divider=True)
    import os
    default_note = ("Full local dump (data/raw_dump.csv)" if os.path.exists(SAMPLE_PATH)
                    else "Bundled sample (655 customers)")
    src_note = st.session_state.get("src_note", default_note)
    up = st.file_uploader(
        "Upload your full raw dump (CSV)",
        type=["csv"],
        help="Wide journey format (like Sheet22) or raw order-level export — "
             "auto-detected. 155k+ orders is fine.")
    if up is not None:
        long_df, mode = _load_bytes(up.getvalue(), up.name)
        st.session_state["src_note"] = f"{up.name} — {mode}"
        st.success(f"Loaded: {up.name}", icon="📎")
    else:
        long_df = _load_sample()
    import sources as _S; _S.show_warnings(long_df)
    st.caption(f"Active source: {st.session_state.get('src_note', default_note)}")

    if long_df.empty:
        st.error("No parsable rows found — check the file format.")
        st.stop()

    # ---- filters (mockup set) ----
    st.subheader("Filters", divider=True)
    st.caption("Category / Variant / month filters apply to the customer's "
               "**first (entry) order** — cohort style, like the summary sheet.")

    cats = ["All"] + sorted(long_df["category"].unique())
    category = st.selectbox("Category", cats)

    pool = long_df if category == "All" else long_df[long_df["category"] == category]
    sku_opts = ["All"] + sorted(pool["sku_key"].unique())
    sku_key = st.selectbox("Variant (SKU)", sku_opts,
                           help="e.g. Beetroot Tomato Vit-A 50g")

    months = sorted(long_df["month"].unique())
    mcol1, mcol2 = st.columns(2)
    from_month = mcol1.selectbox("From month", months, index=0)
    to_month = mcol2.selectbox("To month", months, index=len(months) - 1)

    depths_avail = sorted(long_df["journey_depth"].unique())
    depths = st.multiselect("Journey depth (orders per customer)",
                            depths_avail, default=depths_avail)

    regions_avail = ["All"] + sorted(long_df["region"].unique())
    region = st.selectbox("Geo region", regions_avail)
    city_pool = (long_df if region == "All"
                 else long_df[long_df["region"] == region])
    city_opts = sorted(city_pool["city"].dropna().unique())
    cities = st.multiselect(
        "City", city_opts,
        help="Leave empty for all cities in the selected region.")

    region_sel = None if region == "All" else [region]
    category_sel = None if category == "All" else category
    sku_sel = None if sku_key == "All" else sku_key

# ---------------------------------------------------------------- cohort
d, cohort = M.filter_cohort(
    long_df, category=category_sel, sku_key=sku_sel,
    from_month=from_month, to_month=to_month,
    depths=depths, regions=region_sel,
    cities=cities if cities else None)

seas = M.seasonality_tiles(d)
gels = M.gels_totals(d)
loy = M.loyalty_metrics(d, sku_sel)

# ---------------------------------------------------------------- header
st.title("🧴 Nat Habit — Retention Dashboard")
st.info("🏠 **Home** — journey dashboard & conclusions. New pages in the sidebar → "
        "🔁 Migration · 💰 Sales & Revenue (incl. AOP) · 🗣️ NPS & CS · "
        "💲 Price Changes · 📈 Retention & V2V/V2C · 🆕 New-to-Category. "
        "Each page has its own CSV uploader — drop fresh exports anytime.")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Customers in cohort", fmt_int(gels["Customers"]), border=True)
c2.metric("Total orders", fmt_int(gels["Total Orders"]), border=True)
c3.metric("Repeat buyers", fmt_int(gels["Repeat Buyers"]), border=True)
c4.metric("Repeat rate",
          f"{100 * gels['Repeat Buyers'] / gels['Customers']:.1f}%" if gels["Customers"] else "—",
          border=True)
filter_txt = " · ".join(x for x in [
    category if category != "All" else None,
    sku_key if sku_key != "All" else None,
    f"{from_month} → {to_month}",
    f"depth {min(depths) if depths else '–'}–{max(depths) if depths else '–'}",
    region if region != "All" else None] if x)
st.caption(f"Filters: {filter_txt or 'none'}")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    ["📊 Dashboard", "🏁 Conclusions", "🧾 Interactive Table", "🧴 Variant Summary",
     "🔁 Migration & Grammage", "📖 Definitions"])

# ================================================================ TAB 1
with tab1:
    if d.empty:
        st.warning("No customers match the current filters — loosen them a bit.")
        st.stop()

    st.subheader("SEASONALITY", divider=True)
    st.caption("Orders by the variant's **intended season** "
               "(Cold Winter / Hot Dry / Hot Humid lines + non-seasonal concern variants)")
    a1, a2, a3, a4, a5 = st.columns(5)
    a1.metric("Cold Winter (Dec–Feb) variants", fmt_int(seas["Cold Winter"]), border=True)
    a2.metric("Hot Dry (Mar–May) variants", fmt_int(seas["Hot Dry"]), border=True)
    a3.metric("Hot Humid (Jun–Sep) variants", fmt_int(seas["Hot Humid"]), border=True)
    a4.metric("Non-Seasonal / Concern variants", fmt_int(seas["Non-Seasonal (Concern)"]), border=True)
    a5.metric("Peak Season", seas["Peak Season"],
              delta=f"{fmt_int(seas['Peak Orders'])} orders", border=True)

    b1, b2, b3, b4, b5 = st.columns(5)
    with b1:
        st.markdown("**Purchase timing** (orders by calendar month):")
    ts = M.timing_seasonality(d)
    for col, (lab, val) in zip([b2, b3, b4, b5], ts.items()):
        col.metric(lab, fmt_int(val), border=True)

    st.subheader("GELS & TOTALS", divider=True)
    g1, g2, g3, g4, g5 = st.columns(5)
    g1.metric("Active Gel Count", fmt_int(gels["Active Gel Count"]), border=True)
    g2.metric("Aloevera Gel Count", fmt_int(gels["Aloevera Gel Count"]), border=True)
    g3.metric("Total Orders", fmt_int(gels["Total Orders"]), border=True)
    g4.metric("Face Malai Count",
              fmt_int((d[d["category"] == "Face Malai"]
                       .drop_duplicates(["customer", "order_seq"]).shape[0])), border=True)
    g5.metric("One-time buyers",
              fmt_int(gels["Customers"] - gels["Repeat Buyers"]), border=True)

    st.subheader("LOYALTY & JOURNEY", divider=True)
    st.caption("First → second purchase behaviour of the cohort"
               + (f" (entry SKU: **{sku_sel}**) — V2V = next order repeats the same "
                  "variant; V2C = next order stays in the same category."
                  if sku_sel else
                  " — V2V = next order repeats an entry variant; "
                  "V2C = next order stays in an entry category."))
    l1, l2, l3, l4 = st.columns(4)
    l1.metric("V2V Loyalty %", f"{loy['V2V Loyalty %']}%", border=True)
    l2.metric("V2C Loyalty %", f"{loy['V2C Loyalty %']}%", border=True)
    l3.metric("Avg Purchase Days V2V", fmt_num(loy["Avg Purchase Days V2V"]), border=True)
    l4.metric("Avg Purchase Days V2C", fmt_num(loy["Avg Purchase Days V2C"]), border=True)
    l5, l6, l7, l8 = st.columns(4)
    l5.metric("Avg Order Count V2V", fmt_num(loy["Avg Order Count V2V"], 2), border=True)
    l6.metric("Avg Order Count V2C", fmt_num(loy["Avg Order Count V2C"], 2), border=True)
    l7.metric("Most common 2nd order (V2V)",
              loy["Most Common 2nd Order V2V"] or "—", border=True)
    l8.metric("Most common 2nd order (V2C)",
              loy["Most Common 2nd Order V2C"] or "—", border=True)
    st.caption(f"Repeat customers (2+ orders) in cohort: "
               f"**{fmt_int(loy['Repeat customers (2+ orders)'])}** · "
               f"Avg gap between orders: **{fmt_num(loy['Avg Gap (all repeats)'])} days** · "
               f"Avg journey depth: **{fmt_num(loy['Avg Journey Depth'], 2)}**")

    # charts
    left, right = st.columns(2)
    with left:
        orders = d.drop_duplicates(["customer", "order_seq"])
        monthly = (orders.groupby("month").size().reset_index(name="orders"))
        fig = px.bar(monthly, x="month", y="orders",
                     title="Orders by month (cohort)",
                     color_discrete_sequence=["#3C8C6E"])
        fig.update_layout(margin=dict(t=40, b=10), height=300, xaxis_title=None)
        st.plotly_chart(fig, width='stretch')
    with right:
        tsv = ts.reset_index()
        tsv.columns = ["season", "orders"]
        fig2 = px.bar(tsv, x="season", y="orders", title="Orders by purchase-month season",
                      color="season",
                      color_discrete_map={s: BRAND.get(s.replace(" (Dec-Feb)", " Cold Winter"), "#3C8C6E") for s in tsv["season"]})
        fig2.update_layout(margin=dict(t=40, b=10), height=300,
                           showlegend=False, xaxis_title=None)
        st.plotly_chart(fig2, width='stretch')

# ================================================================ TAB 2 — CONCLUSIONS
with tab2:
    st.subheader("Formula-driven conclusions")
    st.caption("Every number and every verdict below is computed live from the "
               "current data — same sentences your workbook hardcodes, but "
               "self-updating with the filters above.")
    cons = M.conclusions(d if not d.empty else long_df)
    for i, c in enumerate(cons):
        st.markdown(
            f"<div style='border-left:4px solid #3C8C6E;padding:8px 14px;"
            f"margin:6px 0;background:#F4F9F5;border-radius:4px'>"
            f"<b>{c['q']}</b><br><span style='color:#333'>{c['a']}</span></div>",
            unsafe_allow_html=True)
    st.download_button(
        "⬇ Download conclusions (CSV)", data=pd.DataFrame(cons).to_csv(index=False),
        file_name="conclusions.csv", mime="text/csv", key="dl_cons",
        width='stretch')

# ================================================================ TAB 3
with tab3:
    st.subheader("Interactive table")
    if d.empty:
        st.warning("No rows for the current filters.")
        st.stop()

    view = st.radio("View", ["Journey (one row per customer)",
                             "Orders (one row per order-item)"],
                    horizontal=True, label_visibility="collapsed")
    q = st.text_input("🔍 Search (customer, city, SKU, region…)",
                      placeholder="e.g. Gurgaon, Turmeric, 27692").strip().lower()

    if view.startswith("Journey"):
        full = etl.journey_wide(d)
    else:
        full = (d[["customer", "order_seq", "order_date", "city", "region",
                   "category", "variant_key", "size_g", "sku_key",
                   "intended_season", "timing_season", "gap_days",
                   "journey_depth", "is_repeat_buyer"]]
                .sort_values(["customer", "order_seq"]))
        full = full.rename(columns={
            "customer": "Customer", "order_seq": "Order #", "order_date": "Date",
            "city": "City", "region": "Region", "category": "Category",
            "variant_key": "Variant", "size_g": "Size (g)", "sku_key": "SKU",
            "intended_season": "Intended Season", "timing_season": "Purchase Season",
            "gap_days": "Gap (days)", "journey_depth": "Journey Depth",
            "is_repeat_buyer": "Repeat?"})

    if q:
        mask = full.astype(str).apply(
            lambda col: col.str.lower().str.contains(q, na=False)).any(axis=1)
        shown_df = full[mask]
    else:
        shown_df = full

    try:
        reg = etl.decoder_table()
        if len(reg):
            with st.expander(f"🧬 Decoder registry — {len(reg)} auto-learned SKU code(s)"):
                st.dataframe(reg, hide_index=True, width='stretch')
                st.caption("Auto-learned from product names. Correct entries by editing "
                           "data/decoder_overrides.json; delete a row to re-learn it.")
    except Exception:
        pass
    st.caption(f"{len(shown_df):,} rows match.")
    dcol1, dcol2, dcol3 = st.columns([1, 2, 2])
    page_size = dcol1.selectbox("Rows per page", [25, 50, 100, 500], index=1)
    total_pages = max(1, -(-len(shown_df) // page_size))
    page = st.session_state.get("tbl_page", 1)
    page = min(max(page, 1), total_pages)
    pcol1, pcol2, pcol3 = dcol2.columns([1, 1.4, 1])
    if pcol1.button("⬅ Prev", width='stretch') and page > 1:
        page -= 1
    pcol2.markdown(f"<h4 style='text-align:center;margin:2px'>Page {page} / {total_pages}</h4>",
                   unsafe_allow_html=True)
    if pcol3.button("Next ➡", width='stretch') and page < total_pages:
        page += 1
    st.session_state["tbl_page"] = page

    start, end = (page - 1) * page_size, page * page_size
    st.dataframe(shown_df.iloc[start:end], height=460, hide_index=True)
    dlcol1, dlcol2 = st.columns(2)
    with dlcol1:
        dl_button(shown_df, "⬇ Download filtered view (CSV)",
                  "filtered_view.csv", "dl_view")
    with dlcol2:
        dl_button(etl.journey_wide(d) if not view.startswith("Journey") else full,
                  "⬇ Download full journeys (CSV)", "filtered_journeys.csv",
                  "dl_journeys")

# ================================================================ TAB 3
with tab3:
    st.subheader("Variant summary — seasonality (timing of purchase)")
    vs = M.variant_summary(long_df)
    st.dataframe(vs, hide_index=True, width='stretch')
    dl_button(vs, "⬇ Download variant seasonality (CSV)",
              "variant_seasonality.csv", "dl_vs")

    st.subheader("Order frequency & retention (entry cohorts)")
    of = M.order_frequency(long_df)
    st.dataframe(of, hide_index=True, width='stretch')
    dl_button(of, "⬇ Download order frequency (CSV)",
              "order_frequency.csv", "dl_of")

    fig3 = px.bar(vs.head(15), x="Variant", y="Total Orders",
                  color="Peak Season", title="Top variants — total orders & peak season",
                  color_discrete_sequence=px.colors.qualitative.Prism)
    fig3.update_layout(margin=dict(t=40, b=10), height=340)
    st.plotly_chart(fig3, width='stretch')

# ================================================================ TAB 4
with tab4:
    st.subheader("Where do buyers go next? (entry SKU → 2nd order)")
    tm_all = M.transition_matrix(long_df)
    from_opts = ["All"] + sorted(tm_all["from"].unique())
    from_sel = st.selectbox("Entry SKU", from_opts)
    tm = tm_all if from_sel == "All" else tm_all[tm_all["from"] == from_sel]
    st.dataframe(tm, hide_index=True, width='stretch',
                 height=380)
    dl_button(tm, "⬇ Download transitions (CSV)", "transitions.csv", "dl_tm")

    # heat matrix (variant level)
    st.subheader("Migration matrix — entry variant → next variant")
    tmv = M.transition_matrix(long_df, level="variant")
    top_vars = (long_df["variant"].value_counts().head(12).index.tolist())
    mat = (tmv[tmv["from"].isin(top_vars) & tmv["to"].isin(top_vars)]
           .pivot(index="from", columns="to", values="Customers")
           .reindex(index=top_vars, columns=top_vars))
    fig4 = go.Figure(go.Heatmap(
        z=mat.values, x=mat.columns, y=mat.index, colorscale="Greens",
        text=mat.fillna(0).astype(int).values, texttemplate="%{text}",
        hovertemplate="%{y} → %{x}: %{z} customers<extra></extra>"))
    fig4.update_layout(height=560, margin=dict(t=10, b=10),
                       yaxis_title="Entry variant", xaxis_title="2nd-order variant")
    st.plotly_chart(fig4, width='stretch')

    st.subheader("Grammage transitions (entry size → next purchase)")
    gt = M.grammage_transitions(long_df)
    st.dataframe(gt, hide_index=True, width='stretch')
    dl_button(gt, "⬇ Download grammage transitions (CSV)",
              "grammage.csv", "dl_gt")

# ================================================================ TAB 5
with tab5:
    st.markdown(
        """
#### How filters work
**Category / Variant / From–To month** are applied to each customer's **first
(entry) order** — the same cohort semantics used in the summary sheet.
**Journey depth** = total orders of that customer. **Geo** uses the customer's
city (mapped to North / West / South / East / Rest of India — edit
`REGION_MAP` in `etl.py` if needed).

#### SKU short-code decoder
Every code reads `FC-<LINE>-<VARIANT>-<SIZE>`:
`FC-CWDM-FW-030` = **F**ace **C**are · **C**old **W**inter **D**aily **M**alai ·
**F**lax **W**alnut · 30 g.

| Line | Category | Intended season |
|---|---|---|
| CWDM | Face Malai | Cold Winter (Dec–Feb) |
| HDDM | Face Malai | Hot Dry (Mar–May) |
| HHDM | Face Malai | Hot Humid (Jun–Sep) |
| DM   | Face Malai | Non-seasonal / concern (Pigmentation, Overnight, Anti-Acne, Dry & Peeling) |
| AC   | Active Gel | Concern gels (Neem TeaTree, Vit-C, Vit-A, Vit-E, Aloe Cactus) |
| HG   | Aloe Vera Gel | Pure aloe (40 g / 80 g) |

Variant codes: FW Flax Walnut · TP Tomato Patchouli · BT* Winter Blackseed
(CWDM) / Beetroot Tomato (AC) · FB Flax Bakuchi · TR Tomato Rosehip ·
PT Pomegranate Tulsi · FC Flax Carrot · TV Tomato Vetiver · GAT GreenApple
Tulsi · PG Turmeric Nutmeg · NR Cocoa Mogra · DP Honey Multi-Nut ·
AA Clove Tea-Tree · NT Neem TeaTree · AC Aloe Cactus · OV Olive Vit-E ·
OK Orange Kiwi · PA Pure Aloe.

#### Metric definitions
- **Seasonality tiles** — count of orders whose items belong to each *intended*
  season line; **Peak Season** = the largest bucket.
- **Purchase timing** — same orders bucketed by the *calendar month* of purchase
  (Cold Winter Dec–Feb · Hot Dry Mar–May · Hot Humid Jun–Sep · Post-Monsoon Oct–Nov).
- **V2V Loyalty %** — of customers with ≥2 orders, % whose 2nd order contains a
  variant from their 1st order (same-variant repeat).
- **V2C Loyalty %** — % whose 2nd order stays within a category from their 1st order.
- **Avg Purchase Days V2V / V2C** — mean days between order 1 → 2 for those loyal groups.
- **Avg Order Count V2V / V2C** — mean total orders of those loyal groups.
- **Seasonality Strength** — Highly Seasonal: peak season ≥ 40 % of orders ·
  Moderately: 30–40 % · Evergreen: < 30 % · concern/gel variants: —.
- **Grammage moves** — Repeat exact SKU · Upsized (larger size) ·
  Lateral (same size, different category) · Downsized (smaller size).

#### Auto-learned SKU codes (decoder registry)
New or unknown SKU codes that were decoded from their product names get
registered automatically in `data/decoder_overrides.json` — review them in the
**Decoder registry** expander on the 🧾 Interactive Table tab. Date conventions
(day-first vs month-first) are pinned per source in `data/config.json`.

#### Load your real 155k dump
Use the uploader in the sidebar. Accepted:
1. **Wide journey CSV** (Sheet22 shape: `first_purchased_sku`,
   `first_order_date`, …) — parsed directly.
2. **Raw order-level CSV** — one row per order/line; the loader auto-detects
   customer, date, SKU/variant and city columns, groups same customer + date
   into one order, and builds journeys in chronological order.
""")
