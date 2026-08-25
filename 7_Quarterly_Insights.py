"""📄 Quarterly Insights — auto-written category narrative for any period."""
import io

import pandas as pd
import streamlit as st

import etl
import narrative as N
import sources as S

st.set_page_config(page_title="Quarterly Insights", page_icon="📄", layout="wide")
st.title("📄 Textual Insights — Quarterly Category Review")
st.caption("Pick a category + quarter (or any quarter available in the data) and the "
           "review writes itself: cohort retention, seasonality, pack economics, "
           "weather-SKU funnel, channel, variant cuts, spillover, sentiment and "
           "action items — every number computed, every verdict data-driven.")


@st.cache_data(show_spinner="Loading…")
def _j(b: bytes):
    return etl.load_any(io.BytesIO(b))[0]


@st.cache_data(show_spinner="Loading sample…")
def _j_s():
    return etl.load_journey_csv("data/sample_journeys.csv")


@st.cache_data(show_spinner="Loading…")
def _n(b: bytes):
    return S.load_nps(b)


@st.cache_data(show_spinner="Loading…")
def _s(b: bytes):
    return S.load_sales(b)


@st.cache_data(show_spinner="Loading sample…")
def _n_s():
    return S.load_nps("data/nps_raw.csv")


@st.cache_data(show_spinner="Loading sample…")
def _s_s():
    return S.load_sales("data/sales_rev_aggregate.csv")


with st.sidebar:
    j_up = st.file_uploader("Journey CSV (required)", type=["csv"], key="qi_j")
    n_up = st.file_uploader("NPS raw CSV (optional — sentiment cuts)",
                            type=["csv"], key="qi_n")
    s_up = st.file_uploader("Sales CSV (optional — channel cuts)",
                            type=["csv"], key="qi_s")

long_df = _j(j_up.getvalue()) if j_up else _j_s()
S.show_warnings(long_df)
nps_df = _n(n_up.getvalue()) if n_up else _n_s()
sales_df = _s(s_up.getvalue()) if s_up else None

cats = sorted(long_df["category"].unique())
category = st.selectbox("Category", cats, index=cats.index("Face Malai")
                        if "Face Malai" in cats else 0)

quarters = sorted({N.month_to_q(m) for m in long_df["month"].unique()})
q = st.selectbox("Quarter under review",
                 quarters[::-1],
                 index=len(quarters) - 2 if len(quarters) > 1 else 0)
qp = N.prev_q(q)
min_base = st.slider("Min variant base to include", 5, 100, 5, 5)
st.caption(f"Compared automatically against **{N.q_label(qp)}** "
           f"({N.QLABEL[N.QNAME[int(qp[-1])]]}).")

k1, k2, k3 = st.columns(3)
r_q, n_q = N.c2c_retention(long_df, q)
r_p, n_p = N.c2c_retention(long_df, qp)
k1.metric(f"{N.q_label(q)} cohort retention (C2C)",
          "—" if r_q is None else f"{r_q:.1f}%",
          delta=None if (r_q is None or r_p is None) else f"{r_q - r_p:+.1f}ppt vs {N.q_label(qp)}",
          border=True)
k2.metric("New customers", f"{n_q:,}", delta=None if not n_p else f"{100 * (n_q - n_p) / n_p:+.1f}%",
          border=True)
k3.metric("Variants in cut", len(N.variant_cuts(long_df, q, category, min_base)), border=True)

blocks = N.write_narrative(long_df, category, q, nps_df=nps_df,
                           sales_df=sales_df, min_base=min_base)
md = [f"# {category} — {N.q_label(q)} review (vs {N.q_label(qp)})\n"]
for b in blocks:
    st.markdown(f"### {b['section']}")
    st.markdown(b["text"], unsafe_allow_html=True)
    md.append(f"## {b['section']}\n{b['text']}\n")

st.divider()
st.download_button("⬇ Download the full review (Markdown)",
                   "\n".join(md).encode("utf-8"),
                   f"{category.replace(' ', '_')}_{q}_review.md", key="dl_review")

with st.expander("Show the numbers behind the variant cuts"):
    vq = N.variant_cuts(long_df, q, category, min_base)
    vp = N.variant_cuts(long_df, qp, category, min_base)
    if len(vq):
        t = vq.merge(vp, on="variant", how="left", suffixes=(f" ({N.q_label(q)})",
                                                             f" ({N.q_label(qp)})"))
        t = t.rename(columns={c: c for c in t.columns})
        st.dataframe(t.round(1), hide_index=True, width='stretch')
        st.download_button("⬇ Download variant cuts", t.round(1).to_csv(index=False),
                           "variant_cuts.csv", key="dl_vc")
