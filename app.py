"""Executive Overview — the home page of the Retention & Category Intelligence dashboard.

Aggregates health across retention, revenue, customer voice, migration,
new-customer movement and the AOP plan, then generates:
  * "What changed?"  — dynamic, from current data
  * "What needs attention?" — prioritized issues, only shown when the data supports them
"""
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import sources
from calculations import ntc_kpis
from conclusions import executive_attention, executive_changes
from context import build_context
from formatting import fmt_int, fmt_money, fmt_pct, fmt_pct_auto, init_page, kpi_cards

init_page("Executive Overview", "🧭",
          "Retention & Category Intelligence — health across retention, revenue, voice, migration, "
          "new customers and the AOP plan. Everything below recalculates from the sources on each page.")

# ---------------------------------------------------------------------------
# load all models
# ---------------------------------------------------------------------------
st.sidebar.markdown("### 🧭 Executive")
st.sidebar.caption("Sources: upload fresh CSVs on each page — this overview updates automatically.")

st1 = st.sidebar.expander("Sales / Revenue")
sources.page_uploader("sales", help_text="Upload the monthly Sales/Revenue aggregate.")
sales, sales_rep, _ = sources.get_model("sales")

st2 = st.sidebar.expander("Customer journey")
sources.page_uploader("journey", help_text="Customer × order level export for computed retention & migration.")
journey, journey_rep, _ = sources.get_model("journey")

st3 = st.sidebar.expander("NPS / CS")
sources.page_uploader("nps")
nps, nps_rep, _ = sources.get_model("nps")
sources.page_uploader("cs")
cs, cs_rep, _ = sources.get_model("cs")

st4 = st.sidebar.expander("AOP plan")
sources.page_uploader("aop")
aop, aop_rep, _ = sources.get_model("aop")

st5 = st.sidebar.expander("Retention FM")
sources.page_uploader("retention_fm")
fm, fm_rep, _ = sources.get_model("retention_fm")

st6 = st.sidebar.expander("New-to-category")
sources.page_uploader("order_movement")
ntc, ntc_rep, _ = sources.get_model("order_movement")

as_of = st.sidebar.date_input("As-of date (cohort maturity)", value=pd.Timestamp.now().date(), key="ex_asof")

# ---------------------------------------------------------------------------
# compute (shared context builder — same numbers as Insights page & static export)
# ---------------------------------------------------------------------------
ctx, models = build_context(as_of=as_of)
sales = models["sales"]

# ---------------------------------------------------------------------------
# KPI bands
# ---------------------------------------------------------------------------
def _band(title, icon, cards):
    st.markdown(f"#### {icon} {title}")
    kpi_cards(cards)

c1, c2, c3 = st.columns(3)
with c1:
    cards = []
    if ctx.get("mig"):
        m = ctx["mig"]
        cards.append(("Repeat / stay %", fmt_pct(m["repeat_pct"])))
        cards.append(("Migration %", fmt_pct(m["switch_pct"])))
        cards.append(("Avg days 1→2", f"{m['avg_days_1_2']:.0f} d" if m["avg_days_1_2"] == m["avg_days_1_2"] else "—"))
    if ctx.get("jr") is not None and len(ctx["jr"]["df"]):
        d = ctx["jr"]["df"]
        def wavg(wc):
            ok = d[wc].notna()
            c = d.loc[ok, "customers"]
            return float((d.loc[ok, wc] * c).sum() / c.sum()) if ok.any() else np.nan
        cards.append(("30-day retention", fmt_pct_auto(wavg("w30"))))
        cards.append(("60-day retention", fmt_pct_auto(wavg("w60"))))
        cards.append(("90-day retention", fmt_pct_auto(wavg("w90"))))
    elif ctx.get("fm") is not None:
        fm = ctx["fm"]
        w_avail = [w for w in fm["windows"] if (fm["mature"][f"w{w}"] & fm["vals"][f"w{w}"].notna()).any()]
        if w_avail:
            for w in (30, 60, 90):
                if w in w_avail:
                    sub = fm["vals"][f"w{w}"][fm["mature"][f"w{w}"]]
                    cards.append((f"{w}-day retention (FM)", fmt_pct_auto(sub.mean())))
    if ctx.get("vv"):
        o = ctx["vv"]["overall"]
        cards.append(("V2V %", fmt_pct(o["v2v_pct"])))
        cards.append(("V2C %", fmt_pct(o["v2c_pct"])))
    _band("Retention & loyalty", "⏳", cards or [("No retention source", "—")])

with c2:
    cards = []
    sk, skp = ctx.get("sales_kpis"), ctx.get("sales_prev_kpis")
    if sk:
        g = None
        if skp and skp.get("revenue") and sk.get("revenue") is not None and skp["revenue"] > 0:
            g = (sk["revenue"] - skp["revenue"]) / skp["revenue"]
        cards.append(("Revenue (latest month)", fmt_money(sk["revenue"]),
                      fmt_pct(g, signed=True) if g is not None else None, g))
        cc, chh = ctx.get("cat_contrib"), ctx.get("chan_contrib")
        if cc is not None and len(cc):
            cards.append(("Top category", f"{cc.iloc[0]['category']} ({fmt_pct(cc.iloc[0]['revenue_share'])})"))
        if chh is not None and len(chh):
            cards.append(("Top channel", f"{chh.iloc[0]['channel']} ({fmt_pct(chh.iloc[0]['revenue_share'])})"))
    _band("Revenue (actual sales)", "💰", cards or [("No sales source", "—")])

with c3:
    cards = []
    b, p = ctx.get("brand_nps"), ctx.get("product_nps")
    if b:
        cards.append(("Brand NPS", f"{b['nps']:+.0f}"))
        cards.append(("Product NPS", f"{p['nps']:+.0f}"))
    ck = ctx.get("cs_kpis")
    if ck and ck.get("tickets"):
        cards.append(("CS tickets", fmt_int(ck["tickets"])))
        cards.append(("Top complaint", ck["top_failure_reason"][:22]))
    if ctx.get("ntc"):
        k = ntc_kpis(ctx["ntc"]["df"], ctx["ntc"]["as_of"], ctx["ntc"]["maturity_days"])
        cards.append(("2nd-order % (mature)", fmt_pct(k["avg_sec_pct"])))
        cards.append(("3rd-order % (mature)", fmt_pct(k["avg_third_pct"])))
    _band("Voice & new customers", "💬", cards or [("No voice source", "—")])

c4, = st.columns([1])
with c4:
    cards = []
    am = ctx.get("aop_monthly")
    if am is not None and len(am):
        act = am[am["revenue"].notna()].tail(1)
        if len(act):
            cards.append(("AOP revenue (latest booked)", fmt_money(act["revenue"].iloc[0])))
            cards.append(("AOP spend", fmt_money(act["spend"].iloc[0])))
            cards.append(("AOP ROAS", f"{act['roas'].iloc[0]:.2f}" if act["roas"].notna().any() else "—"))
    _band("AOP / plan", "📐", cards or [("No AOP source", "—")])
    st.caption("AOP = plan sheet (booked actuals + future plan), shown separately from actual sales.")

# ---------------------------------------------------------------------------
# trend: actual vs AOP
# ---------------------------------------------------------------------------
if ctx.get("sales_kpis") is not None or ctx.get("aop_monthly") is not None:
    st.divider()
    st.subheader("Revenue trend — actual vs AOP")
    fig = go.Figure()
    if sales is not None:
        s = sales["df"].groupby("month")["revenue"].sum().reset_index()
        fig.add_trace(go.Scatter(x=s["month"], y=s["revenue"], name="Actual sales", mode="lines+markers"))
    if ctx.get("aop_monthly") is not None:
        a = ctx["aop_monthly"]
        fig.add_trace(go.Scatter(x=a["month"], y=a["revenue"], name="AOP (plan/actual in AOP sheet)",
                                 mode="lines", line=dict(dash="dot")))
    fig.update_layout(height=400, legend=dict(orientation="h"))
    st.plotly_chart(fig, width="stretch")
    st.caption("Two different sources are overlaid for reference only — they are never summed or mixed.")

# ---------------------------------------------------------------------------
# What changed / What needs attention
# ---------------------------------------------------------------------------
st.divider()
col1, col2 = st.columns(2)
with col1:
    st.subheader("🔄 What changed?")
    changes = executive_changes(ctx)
    if changes:
        for c in changes:
            st.markdown(f"- {c}")
    else:
        st.info("Not enough data loaded to describe changes.")
with col2:
    st.subheader("🚨 What needs attention?")
    items = executive_attention(ctx)
    if items:
        for i, (_, text) in enumerate(items, 1):
            st.markdown(f"**{i}.** {text}")
    else:
        st.success("No attention items detected from the current data.")
    st.caption("Each item is generated from the current data and only shown when its underlying numbers exist. "
               "Items flag observations to investigate — not confirmed causes.")
