"""Page 8 — Insights & Conclusions: ties every page together in one view.

Cross-page synthesis (insight_bundle) + what changed / what needs attention +
per-page conclusions. Every sentence is generated from the currently loaded
data — no hardcoded categories, SKUs, months or business results.
"""
import pandas as pd
import streamlit as st

import sources
from calculations import (competitor_pull, cs_kpis, nps_by_dimension, theme_counts)
from conclusions import (INSIGHT_TONE_ICON, cs_conclusions, executive_attention,
                         executive_changes, insight_bundle, migration_conclusions,
                         nps_conclusions, ntc_conclusions, price_conclusions,
                         retention_conclusions, sales_conclusions)
from context import build_context
from formatting import init_page

init_page("Insights & Conclusions", "💡",
          "One page tying everything together: cross-page synthesis, connections between "
          "independent sources, what changed, what needs attention, and per-page conclusions. "
          "Every sentence is generated from the currently loaded data.")

st.sidebar.markdown("### 💡 Insights")
st.sidebar.caption("Recomputed from the same sources as every other page — upload fresh CSVs and this page updates too.")
as_of = st.sidebar.date_input("As-of date (cohort maturity)", value=pd.Timestamp.now().date(), key="ins_asof")

# make uploads available (same keys as the other pages)
for k in ("sales", "category_sales", "journey", "nps", "cs", "aop", "retention_fm", "order_movement"):
    try:
        sources.page_uploader(k)
    except Exception:
        pass

ctx, models = build_context(as_of=as_of)

# ---------------------------------------------------------------------------
# 1 · Cross-page synthesis
# ---------------------------------------------------------------------------
st.subheader("🧩 Cross-page synthesis")
st.caption("Grouped by theme, with the source page of every statement. 🟢 positive · 🔴 negative ·  watch ·  fact.")

bundle = insight_bundle(ctx)
if bundle:
    for sec in bundle:
        st.markdown(f"#### {sec['icon']} {sec['title']}")
        for it in sec["items"]:
            st.markdown(f"- {INSIGHT_TONE_ICON.get(it['tone'], '·')} {it['text']}  "
                        f"<span style='color:#6b7280;font-size:0.85em'>· from {it['page']}</span>",
                        unsafe_allow_html=True)
else:
    st.info("Not enough data loaded to produce a synthesis — upload sources on any page.")

# ---------------------------------------------------------------------------
# 2 · What changed / what needs attention
# ---------------------------------------------------------------------------
st.divider()
c1, c2 = st.columns(2)
with c1:
    st.subheader("🔄 What changed?")
    changes = executive_changes(ctx)
    for c in changes:
        st.markdown(f"- {c}")
    if not changes:
        st.info("Not enough data loaded.")
with c2:
    st.subheader("🚨 What needs attention?")
    items = executive_attention(ctx)
    for i, (_, text) in enumerate(items, 1):
        st.markdown(f"**{i}.** {text}")
    if not items:
        st.success("No attention items detected from the current data.")
    st.caption("Items are generated from the current data and only shown when their underlying numbers exist. "
               "They flag observations to investigate — not confirmed causes.")

# ---------------------------------------------------------------------------
# 3 · Per-page conclusions (detail on demand)
# ---------------------------------------------------------------------------
st.divider()
st.subheader("📄 Per-page conclusions (detail)")


def _page_conc(title, fn, fallback="Source not loaded."):
    with st.expander(title):
        try:
            out = fn()
        except Exception:
            out = []
        if out:
            for c in out:
                st.markdown(f"- {c}")
        else:
            st.caption(fallback)


def _sales():
    return sales_conclusions(ctx.get("sales_kpis"), ctx.get("sales_prev_kpis"),
                             ctx.get("cat_contrib"), ctx.get("chan_contrib"),
                             ctx.get("var_contrib"), ctx.get("sales_months", []))


def _migration():
    return migration_conclusions(ctx.get("mig")) or []


def _retention():
    fm = ctx.get("fm")
    if not fm:
        return []
    return retention_conclusions(fm["vals"], fm["mature"], fm["df"], ctx.get("vv"),
                                 fm["windows"], ctx.get("as_of"))


def _nps():
    nm = ctx.get("nps_model")
    if nm is None:
        return []
    likes, dislikes = theme_counts(nm, "like"), theme_counts(nm, "dislike")
    return nps_conclusions(nm, ctx.get("brand_nps"), ctx.get("product_nps"),
                           likes, dislikes, competitor_pull(nm), nps_by_dimension(nm, "category"))


def _cs():
    if ctx.get("cs_df") is None:
        return []
    return cs_conclusions({"df": ctx["cs_df"]}, ctx.get("cs_kpis") or cs_kpis({"df": ctx["cs_df"]}))


def _price():
    fm = ctx.get("fm")
    hint = None
    if fm and fm.get("price") is not None:
        from conclusions import price_x_retention_conclusions
        h = price_x_retention_conclusions(fm["price"], fm["vals"], fm["mature"], fm["df"], fm["windows"])
        hint = h[0] if h else None
    return price_conclusions(fm.get("price") if fm else None, ctx.get("price_flags"),
                             ctx.get("price_threshold", 0.05), hint)


def _ntc():
    if ctx.get("ntc") is None:
        return []
    return ntc_conclusions(ctx["ntc"]["df"], ctx["ntc"]["as_of"], ctx["ntc"]["maturity_days"])


_page_conc("📊 2 · Sales & Revenue", _sales)
_page_conc("🔀 1 · Migration", _migration)
_page_conc("💬 3 · NPS & Customer Success", _nps)
_page_conc("💰 4 · Price Changes", _price)
_page_conc("🔁 5 · Retention + V2V/V2C", _retention)
_page_conc("📈 6 · New-to-Category", _ntc)

st.divider()
st.caption("**How to read this page** — every sentence above is generated from the currently loaded data; nothing is "
           "handwritten. Overlaps between sources are phrased as *potential relationships requiring further validation*, "
           "never as cause-and-effect. Immature cohort windows are N/A, never 0%. If a source is missing, its section "
           "simply disappears instead of guessing.")
