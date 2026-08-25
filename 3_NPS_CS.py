"""🗣️ NPS & Customer Support — survey scores, drivers, failure analysis, conclusions."""
from collections import Counter

import pandas as pd
import plotly.express as px
import streamlit as st

import sources as S

st.set_page_config(page_title="NPS & CS", page_icon="🗣️", layout="wide")
st.title("🗣️ NPS & Customer Support")
st.caption("Survey understanding + CS failure understanding, with auto-written "
           "conclusions. Upload fresh exports or paste rows directly.")


@st.cache_data(show_spinner="Loading…")
def _nps(b: bytes):
    return S.load_nps(b)


@st.cache_data(show_spinner="Loading…")
def _cs(b: bytes):
    return S.load_cs(b)


@st.cache_data(show_spinner="Loading sample…")
def _nps_s():
    return S.load_nps("data/nps_raw.csv")


@st.cache_data(show_spinner="Loading sample…")
def _cs_s():
    return S.load_cs("data/cs_fb.csv")


n_up = st.sidebar.file_uploader("NPS raw CSV", type=["csv"], key="nps_up")
nps = _nps(n_up.getvalue()) if n_up else _nps_s()
c_up = st.sidebar.file_uploader("CS feedback CSV", type=["csv"], key="cs_up")
cs = _cs(c_up.getvalue()) if c_up else _cs_s()
S.show_warnings(nps, cs)

import io as _io


paste = st.sidebar.text_area(
    "…or paste extra NPS rows here (copy from your sheet incl. header)",
    help="Paste as CSV/TSV straight from Excel — rows are appended to the loaded data.")
if paste.strip():
    try:
        sep = "\t" if "\t" in paste.splitlines()[0] else ","
        extra = pd.read_csv(_io.BytesIO(paste.encode("utf-8")), sep=sep)
        extra = S.load_nps(extra.to_csv(index=False).encode())
        nps = pd.concat([nps, extra], ignore_index=True)
        st.sidebar.success(f"Appended {len(extra)} pasted rows")
    except Exception as e:
        st.sidebar.warning(f"Paste parse failed: {e}")

# ------------------------------------------------------------- NPS
st.header("NPS — understanding")
b = nps["NPS Score For Brand"].dropna()
p = nps["NPS Score For Product"].dropna()
brand_nps = S.nps_score(nps["NPS Score For Brand"])
prod_nps = S.nps_score(nps["NPS Score For Product"])
prom = 100 * (b >= 9).mean(); det = 100 * (b <= 6).mean() if len(b) else 0

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Responses", f"{len(nps):,}", border=True)
k2.metric("NPS — Brand", f"{brand_nps}", border=True)
k3.metric("NPS — Product", f"{prod_nps}", border=True)
k4.metric("Promoters", f"{prom:.0f}%", border=True)
k5.metric("Detractors", f"{det:.0f}%", border=True)

c1, c2 = st.columns(2)
with c1:
    st.plotly_chart(px.histogram(nps, x="NPS Score For Brand", nbins=11,
                                 title="Brand score distribution",
                                 color_discrete_sequence=["#E8604A"])
                    .update_layout(height=300), width='stretch')
with c2:
    bycat = (nps.groupby("product_category")["NPS Score For Brand"]
             .apply(S.nps_score).dropna().sort_values().reset_index())
    st.plotly_chart(px.bar(bycat, x="NPS Score For Brand", y="product_category",
                           orientation="h", title="Brand NPS by category",
                           color_discrete_sequence=["#8C2F1B"])
                    .update_layout(height=max(300, 22 * len(bycat))), width='stretch')

likes = Counter(x for lst in nps["_likes"] for x in lst)
dislikes = Counter(x for lst in nps["_dislikes"] for x in lst)
c3, c4 = st.columns(2)
with c3:
    st.subheader("What customers like")
    lt = pd.DataFrame(likes.most_common(12), columns=["driver", "mentions"])
    if len(lt):
        st.plotly_chart(px.bar(lt, x="mentions", y="driver", orientation="h",
                               color_discrete_sequence=["#E8604A"])
                        .update_layout(height=360), width='stretch')
with c4:
    st.subheader("What they don't")
    dt = pd.DataFrame(dislikes.most_common(12), columns=["driver", "mentions"])
    if len(dt):
        st.plotly_chart(px.bar(dt, x="mentions", y="driver", orientation="h",
                               color_discrete_sequence=["#C0392B"])
                        .update_layout(height=360), width='stretch')

mig = nps["Brand Customer Migrated From"].dropna().value_counts().head(10)
if len(mig):
    st.subheader("Customers migrated from (competitive pull)")
    st.plotly_chart(px.bar(x=mig.values, y=mig.index, orientation="h",
                           color_discrete_sequence=["#2A9D8F"],
                           labels={"x": "customers", "y": ""})
                    .update_layout(height=320), width='stretch')

st.subheader("Variant-level NPS")
vv = (nps.groupby(["product_category", "product_variant"])
      .agg(responses=("product_variant", "size"),
           brand_nps=("NPS Score For Brand", S.nps_score),
           product_nps=("NPS Score For Product", S.nps_score),
           avg_age=("age", "mean")).reset_index().sort_values("responses", ascending=False))
st.dataframe(vv, hide_index=True, width='stretch', height=380)
st.download_button("⬇ Download variant NPS", vv.to_csv(index=False),
                   "variant_nps.csv", key="dl_vnps")

# ------------------------------------------------------------- CS
st.header("Customer Support — failure understanding")
fk1, fk2, fk3, fk4 = st.columns(4)
fk1.metric("Tickets", f"{len(cs):,}", border=True)
if "chat_status" in cs:
    fk2.metric("Resolved", f"{100 * (cs['chat_status'] == 'Resolved').mean():.0f}%", border=True)
top_fail = (cs["failure_type"].value_counts().rename_axis("failure_type")
            .reset_index(name="tickets") if "failure_type" in cs else pd.DataFrame())
if len(top_fail):
    fk3.metric("Top failure", f"{top_fail.iloc[0]['failure_type']} "
              f"({100 * top_fail.iloc[0]['tickets'] / len(cs):.0f}%)", border=True)
if "ship_hours" in cs and cs["ship_hours"].notna().any():
    fk4.metric("Median ship time", f"{cs['ship_hours'].median():.0f} h", border=True)

if len(top_fail):
    st.plotly_chart(px.sunburst(cs.dropna(subset=["failure_type"]),
                                path=["failure_type", "failure_reason", "failure_subreason"],
                                title="Failure tree — type → reason → sub-reason")
                    .update_layout(height=480), width='stretch')

if "Product impacted category" in cs:
    cat = cs["Product impacted category"].dropna().value_counts().head(12).reset_index()
    cat.columns = ["category", "tickets"]
    st.plotly_chart(px.bar(cat, x="tickets", y="category", orientation="h",
                           title="Tickets by impacted category",
                           color_discrete_sequence=["#7A6A55"])
                    .update_layout(height=380), width='stretch')

q = st.text_input("🔍 Search remarks / global remark / product", key="cs_q").lower()
show = cs
if q and "remarks" in cs:
    mask = cs.apply(lambda r: q in str(r.get("remarks", "")).lower()
                    or q in str(r.get("global_remark", "")).lower()
                    or q in str(r.get("products_ordered", "")).lower(), axis=1)
    show = cs[mask]
cols = [c for c in ["created_at", "customer_name", "order_name", "chat_status",
                    "failure_type", "failure_reason", "failure_subreason",
                    "products_impacted", "responsible_team", "global_remark", "chat_link"]
        if c in show.columns]
st.dataframe(show[cols], hide_index=True, width='stretch', height=420)
st.download_button("⬇ Download tickets", show[cols].to_csv(index=False),
                   "cs_tickets.csv", key="dl_cs")

# ------------------------------------------------------------- conclusions
st.header("Auto conclusions")
cons = []
if brand_nps is not None:
    verdict = ("EXCELLENT" if brand_nps >= 70 else "GOOD" if brand_nps >= 50
               else "NEEDS WORK" if brand_nps >= 0 else "CRITICAL")
    cons.append(("NPS verdict",
                 f"Brand NPS is {brand_nps} ({verdict}) — {prom:.0f}% promoters vs "
                 f"{det:.0f}% detractors across {len(b):,} responses. "
                 + (f"Product NPS ({prod_nps}) trails brand NPS — product experience "
                    "is the drag." if prod_nps is not None and prod_nps < brand_nps
                    else "Product experience holds the score up.")))
if len(dislikes):
    top_d, n_d = dislikes.most_common(1)[0]
    cons.append(("Top dislike driver",
                 f"'{top_d}' is the most-cited complaint ({n_d} mentions). "
                 "Fix this first for the fastest NPS lift."))
if len(likes):
    top_l, n_l = likes.most_common(1)[0]
    cons.append(("Top like driver",
                 f"'{top_l}' leads advocacy ({n_l} mentions) — feature it in creative."))
if len(mig) and mig.index[0] != "Nat Habit is my first!":
    cons.append(("Competitive pull",
                 f"Most migrated-from brand: {mig.index[0]} ({mig.iloc[0]} customers) — "
                 "the main conquest pool."))
elif len(mig):
    cons.append(("Competitive pull",
                 f"'Nat Habit is my first!' dominates ({mig.iloc[0]} customers) — "
                 "the base is first-time D2C buyers; education content matters."))
if len(top_fail):
    cons.append(("CS top failure",
                 f"{top_fail.iloc[0]['failure_type']} drives "
                 f"{100 * top_fail.iloc[0]['tickets'] / len(cs):.0f}% of tickets — "
                 "root-cause this with the responsible team."))
if "ship_hours" in cs and cs["ship_hours"].notna().any():
    cons.append(("Fulfilment",
                 f"Median ticket-to-delivery time is {cs['ship_hours'].median():.0f} hours; "
                 f"{100 * (cs['ship_hours'] > 72).mean():.0f}% of ticketed orders took "
                 "over 3 days."))
for q_, a_ in cons:
    st.markdown(f"<div style='border-left:4px solid #E8604A;padding:8px 14px;"
                f"margin:6px 0;background:#FFF1EC;border-radius:4px'><b>{q_}</b>"
                f"<br><span style='color:#333'>{a_}</span></div>", unsafe_allow_html=True)
