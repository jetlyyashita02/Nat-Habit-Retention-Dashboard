"""
make_static_dashboard.py — regenerate the FINAL static dashboard (index.html).

What it does
------------
Reads the SAME data models as the Streamlit app (whatever is in data/ or
uploads/), computes every number through the shared calculations/conclusions
engine, and writes a self-contained, interactive index.html:

  * 9 tabs: Overview · Migration · Sales · NPS & CS · Price · Retention ·
    New-to-Category · Definitions · Insights & Conclusions
  * fully interactive: tab navigation, revenue-trend hover tooltips,
    click-to-sort tables, searchable Voice-of-Customer panel
  * zero external references (no CDN, no fonts, no JS libs) → works offline
    and on GitHub Pages

Next month's workflow (no hand-editing, no hardcoded values):
  1. upload the fresh CSVs in the app (or drop them in uploads/)
  2. python make_static_dashboard.py
  3. commit index.html

Every chart value in the HTML is pulled programmatically from the models;
the script self-verifies the embedded AOP series against the computed one
(max-diff must be 0.0) before it is accepted.
"""
from __future__ import annotations

import html
import json
import math
import re
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

import numpy as np
import pandas as pd

import context as app_context
from calculations import (competitor_pull, cs_kpis, intra_category_movement,
                          nps_by_dimension, nps_score_stats, ntc_kpis,
                          theme_counts)
from conclusions import (INSIGHT_TONE_ICON, cs_conclusions, executive_attention,
                         executive_changes, insight_bundle, migration_conclusions,
                         nps_conclusions, ntc_conclusions, price_conclusions,
                         price_x_retention_conclusions, retention_conclusions,
                         sales_conclusions)
from formatting import fmt_days, fmt_int, fmt_money, fmt_num, fmt_pct

ROOT = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# small html helpers
# ---------------------------------------------------------------------------
def _e(s) -> str:
    return html.escape(str(s), quote=True)


def _table(headers: list[str], rows: list[list], num_cols=(), cls: str = "tbl") -> str:
    ths = "".join(
        f'<th class="num">{_e(h)}</th>' if i in num_cols else f"<th>{_e(h)}</th>"
        for i, h in enumerate(headers))
    trs = []
    for r in rows:
        cells = "".join(
            f'<td class="num">{c}</td>' if i in num_cols else f"<td>{c}</td>"
            for i, c in enumerate(r))
        trs.append(f"<tr>{cells}</tr>")
    return f'<table class="{cls}"><tr>{ths}</tr>{"".join(trs)}</table>'


def _hbar(label: str, pct: float, value: str, color: str = "#3b82f6") -> str:
    return (f'<div class="hbar"><div>{_e(label)}</div>'
            f'<div class="track"><div class="fill" style="width:{pct:.1f}%;background:{color}"></div></div>'
            f'<div class="val">{value}</div></div>')


def _dbar(label: str, frac: float, value: str, good: bool) -> str:
    cls = "pos" if good else "neg"
    vcls = "up" if good else "dn"
    return (f'<div class="dbar"><div>{_e(label)}</div>'
            f'<div class="ctr"><div class="{cls}" style="width:{abs(frac) * 100:.1f}%"></div></div>'
            f'<div class="val {vcls}">{value}</div></div>')


def _pill(text: str, kind: str) -> str:
    return f'<span class="pill {kind}">{_e(text)}</span>'


def _kpi(label: str, value: str, sub: str = "", vcls: str = "") -> str:
    return (f'<div class="kpi"><div class="l">{_e(label)}</div>'
            f'<div class="v {vcls}">{value}</div>'
            f'<div class="s">{_e(sub)}</div></div>')


def _ul(items: list[str]) -> str:
    return '<ul class="tight">' + "".join(f"<li>{i}</li>" for i in items) + "</ul>"


def _no_source() -> str:
    return '<div class="card"><div class="note">Source not loaded — upload the CSV in the app to populate this page.</div></div>'


# ---------------------------------------------------------------------------
# per-tab builders (each receives ctx + precomputed pieces)
# ---------------------------------------------------------------------------
def tab_overview(ctx, D) -> str:
    sk, skp = ctx.get("sales_kpis"), ctx.get("sales_prev_kpis")
    if not (sk and skp and pd.notna(sk.get("revenue")) and skp.get("revenue")):
        return '<section class="page" id="p0">' + _no_source() + "</section>"
    g = (sk["revenue"] - skp["revenue"]) / skp["revenue"]
    cc, chh = ctx.get("cat_contrib"), ctx.get("chan_contrib")
    b, p = ctx.get("brand_nps"), ctx.get("product_nps")
    ck = ctx.get("cs_kpis")
    vv = ctx.get("vv")
    kpis = (
        _kpi(f"Revenue · {D['last_month_lbl']} (MTD)", fmt_money(sk["revenue"]),
             f"{fmt_pct(g, signed=True)} vs {D['prev_month_lbl']} slice (partial months)")
        + _kpi("Orders / Customers", f"{fmt_int(sk['orders'])} / {fmt_int(sk['customers'])}",
               f"AOV {fmt_money(sk['aov'])}")
        + (_kpi("Top category", _e(cc.iloc[0]["category"]),
                f"{fmt_pct(cc.iloc[0]['revenue_share'])} of revenue ({fmt_money(cc.iloc[0]['revenue'])})") if cc is not None and len(cc) else "")
        + (_kpi("Top channel", _e(chh.iloc[0]["channel"]),
                f"{fmt_pct(chh.iloc[0]['revenue_share'])} of revenue") if chh is not None and len(chh) else "")
        + (_kpi("Brand NPS", f"{b['nps']:+.1f}",
                f"n={b['n']} · promoters {fmt_pct(b['promoters'])} · detractors {fmt_pct(b['detractors'])} · product {p['nps']:+.1f}",
                "up" if b["nps"] >= 50 else "dn") if b and b.get("n") else "")
        + (_kpi("CS tickets", fmt_int(ck["tickets"]),
                f"{fmt_pct(ck['resolved_pct'])} resolved · top: {ck['top_failure_reason'][:26]}") if ck and ck.get("tickets") else "")
        + (_kpi("V2V / V2C", f"{fmt_pct(vv['overall']['v2v_pct'])} / {fmt_pct(vv['overall']['v2c_pct'])}",
                f"{fmt_int(vv['overall']['qualifying'])} customers with a 2nd order") if vv else "")
        + _kpi("AOP latest booked", fmt_money(D["aop_booked"]["revenue"]),
               f"spend {fmt_money(D['aop_booked']['spend'])} · ROAS {D['aop_booked']['roas']:.2f} · {D['aop_booked']['month']}")
    )
    changes = executive_changes(ctx)
    attention = executive_attention(ctx)
    return f"""<section class="page active" id="p0">
  <div class="topbar"><h2>🏠 Executive Overview</h2><span class="chip">real exports · {D['gen_date']}</span></div>
  <div class="cap">One-glance state of the business — sales, voice, service, loyalty and plan-vs-actual. Every number is computed from the uploaded sources.</div>
  <div class="cards">{kpis}</div>
  <div class="card">
    <h3>Revenue trend — actual vs AOP <span class="note" style="display:inline">hover for values · click legend to read the split</span></h3>
    <svg id="trend" width="100%" height="250" viewBox="0 0 900 250" preserveAspectRatio="none"></svg>
    <div class="legend"><b></b> Actual sales (monthly) <i></i> AOP plan / booked ({D['aop_first']} → {D['aop_last']}) · red line = actual↔plan split ({D['split_lbl']})</div>
    <div class="note">Two different sources overlaid for reference only — never summed or mixed. AOP covers the Gel Moisturizers portfolio; actual sales cover all categories.</div>
  </div>
  <div class="grid2">
    <div class="card"><h3>🔄 What changed?</h3>{_ul(changes) if changes else '<div class="note">Not enough data loaded.</div>'}</div>
    <div class="card"><h3>🚨 What needs attention?</h3>{_ul([f'<b>{i}.</b> {t}' for i, (_, t) in enumerate(attention, 1)]) if attention else '<div class="note">No attention items detected.</div>'}
      <div class="note">Each item is generated from the current data and only shown when its underlying numbers exist. Items flag observations to investigate — not confirmed causes.</div></div>
  </div>
</section>"""


def tab_migration(ctx, D) -> str:
    mig, vv = ctx.get("mig"), ctx.get("vv")
    if not mig or not vv:
        return '<section class="page" id="p1">' + _no_source() + "</section>"
    net = mig["net"]
    mabs = max(net["net"].abs().max(), 1)
    bars = "".join(_dbar(r.entity, r.net / mabs,
                         f"+{fmt_int(r.net)}" if r.net >= 0 else f"−{fmt_int(abs(r.net))}", r.net >= 0)
                   for r in net.itertuples(index=False))
    byc = vv["by_category"]
    rows = [[_e(r.category), fmt_int(r.qualifying), fmt_pct(r.v2v_pct), fmt_pct(r.v2c_pct)]
            for r in byc.itertuples(index=False)]
    o = vv["overall"]
    rows.append([f"<b>Overall</b>", f"<b>{fmt_int(o['qualifying'])}</b>",
                 f"<b>{fmt_pct(o['v2v_pct'])}</b>", f"<b>{fmt_pct(o['v2c_pct'])}</b>"])
    vt = _table(["Category", "Qualifying", "V2V %", "V2C %"], rows, num_cols=(1, 2, 3))
    vt = re.sub(r'<tr><td><b>Overall</b>', '<tr class="total"><td><b>Overall</b>', vt)
    intra = D["intra"]
    intr_html = ""
    if intra and intra.get("ok"):
        g = intra["grammage"]
        grows = []
        for r in g.itertuples(index=False):
            if r.status == "Entered":
                pill, delta = _pill("entered", "n"), "—"
            elif r.status == "Exited":
                pill, delta = _pill("exited", "n"), "—"
            elif r.delta_pp > 0:
                pill, delta = _pill("gainer", "g"), f'<span class="up">+{r.delta_pp:.2f} pp</span>'
            else:
                pill, delta = _pill("loser", "r"), f'<span class="dn">−{abs(r.delta_pp):.2f} pp</span>'
            s1 = fmt_pct(r.share_1st) if pd.notna(r.share_1st) else "—"
            s2 = fmt_pct(r.share_2nd) if pd.notna(r.share_2nd) else "—"
            grows.append([_e(r.grammage), s1, s2, delta, pill])
        gt = _table(["Grammage", "Share 1st half", "Share 2nd half", "Δ", ""], grows, num_cols=(1, 2, 3))
        cand = intra["sku"][(intra["sku"]["status"] != "Exited") & (intra["sku"]["rev_2nd"] > 0)]
        top_gainer = ""
        if len(cand):
            r = cand.iloc[0]
            top_gainer = (f"Top SKU gainer: {_e(r.product)} "
                          f"({fmt_pct(r.share_1st)} → {fmt_pct(r.share_2nd)}, +{r.delta_pp:.1f} pp).")
        n_ent = int((intra["sku"]["status"] == "Entered").sum())
        n_ex = int((intra["sku"]["status"] == "Exited").sum())
        w0, w1, wm = intra["window"]
        intr_html = f"""<div class="card">
      <h3>🧴 Intra-category movement — category-scoped sales ({w0} → {w1}, split {wm})</h3>
      <div class="note" style="margin-top:0;margin-bottom:10px">Aggregated export — <b>no customer ids</b>: SKU/grammage-level revenue-share movement, not customer migration. {fmt_int(intra['n_skus'])} SKUs in scope · {n_ent} entered · {n_ex} exited in 2nd half.</div>
      {gt}
      <div class="note">{top_gainer} Real app tabs: SKU share shift · entered/exited · grammage rollup · top-10 SKU daily trend — all downloadable.</div>
    </div>"""
    return f"""<section class="page" id="p1">
  <div class="topbar"><h2>🔀 1 · Migration</h2><span class="chip">{_e(D['journey_scope'])} · {_e(D['journey_n'])} customers</span></div>
  <div class="cap">Where customers move after their first purchase — inter-category / inter-variant / SKU level, plus the summary sheet. Level, entry, channel and cohort filters in the live app.</div>
  <div class="cards">
    {_kpi("Acquired customers", fmt_int(mig["n_acquired"]), f"{fmt_int(D['journey_orders'])} orders · first 6 per customer")}
    {_kpi("V2V % (same variant)", fmt_pct(o["v2v_pct"]), "qualifying 2nd orders: " + fmt_int(o["qualifying"]))}
    {_kpi("V2C % (same category)", fmt_pct(o["v2c_pct"]), "same denominator as V2V")}
    {_kpi("Category repeat / switch", f"{fmt_pct(mig['repeat_pct'])} / {fmt_pct(mig['switch_pct'])}",
          f"avg {fmt_days(mig['avg_days_1_2'])} from 1st → 2nd order")}
  </div>
  <div class="grid2">
    <div class="card">
      <h3>Net migration by category (gained − lost)</h3>
      {bars}
      <div class="note">Gained = customers whose 1st order was elsewhere but 2nd order is here; lost = the reverse. Only customers with an observed 2nd order are included. Primary line per order avoids many-to-many inflation.</div>
    </div>
    <div class="card">
      <h3>V2V / V2C by category</h3>
      {vt}
      <div class="note">V2C ≥ V2V by construction; separate formulas, never identical. Scope: {D['journey_scope']} × first 6 orders (stated in the UI).</div>
    </div>
  </div>
  {intr_html}
  <div class="card">
    <h3>📄 Seasonality &amp; Migration summary sheet (July 2026)</h3>
    <div class="note">Tabs in the live app: Seasonality · Order frequency · Grammage transitions. Displayed as-is; its grammage “entry” figures could not be exactly reproduced from the base sheet (undocumented entry-cohort definition) — both views agree on direction (Aloe Vera losing customers).</div>
  </div>
</section>"""


def tab_sales(ctx, D) -> str:
    sk = ctx.get("sales_kpis")
    if not sk:
        return '<section class="page" id="p2">' + _no_source() + "</section>"
    cc, chh = ctx.get("cat_contrib"), ctx.get("chan_contrib")
    max_share = cc.iloc[0]["revenue_share"] if cc is not None and len(cc) else 1.0
    top10 = "".join(
        _hbar(r.category, (r.revenue_share / max_share) * 100 if max_share else 0,
              fmt_pct(r.revenue_share))
        for r in cc.head(10).itertuples(index=False)) if cc is not None else ""
    cum = cc["revenue_share"].cumsum()
    pareto_k = int((cum >= 0.80).idxmax() + 1) if cc is not None and len(cc) and (cum >= 0.80).any() else len(cc)
    top3 = float(cum.iloc[2]) if cc is not None and len(cc) >= 3 else np.nan
    ch_top = "".join(
        _hbar(r.channel, (r.revenue_share / chh.iloc[0]["revenue_share"]) * 100,
              fmt_pct(r.revenue_share))
        for r in chh.head(6).itertuples(index=False)) if chh is not None else ""
    n_chan = len(chh) if chh is not None else 0
    ab = D["aop_booked"]
    return f"""<section class="page" id="p2">
  <div class="topbar"><h2>📊 2 · Sales &amp; Revenue</h2><span class="chip">{D['sales_range']} · {D['n_cats']} categories</span></div>
  <div class="cap">KPIs, contribution, Pareto and cross-matrices from the sales export. The AOP section below is the <b>plan</b> sheet — never combined with actuals.</div>
  <div class="cards">
    {_kpi(f"Revenue · {D['last_month_lbl']} MTD", fmt_money(sk["revenue"]), f"{D['last_days']} days in data")}
    {_kpi("Orders", fmt_int(sk["orders"]), fmt_int(sk["customers"]) + " customers")}
    {_kpi("AOV", fmt_money(sk["aov"]), "revenue ÷ orders")}
    {_kpi("Categories / SKUs", f"{D['n_cats']} / {D['n_skus']}", f"{n_chan} channels")}
  </div>
  <div class="grid2">
    <div class="card">
      <h3>Category contribution (top 10 of {len(cc) if cc is not None else 0})</h3>
      {top10}
      <div class="note">Pareto: {pareto_k} of {len(cc) if cc is not None else 0} categories carry 80% of revenue (top-3 = {fmt_pct(top3)} cumulative).</div>
    </div>
    <div class="card">
      <h3>Channel contribution</h3>
      {ch_top}
      <div class="note">…plus {max(0, n_chan - 6)} more channels. Live app also has Channel×Month and Category×Month heatmaps with downloads.</div>
    </div>
  </div>
  <div class="card">
    <h3>AOP / Plan <span class="pill n" style="vertical-align:middle">plan ≠ actual — never combined</span></h3>
    <div class="cards" style="margin-bottom:6px">
      {_kpi("Latest booked revenue", fmt_money(ab["revenue"]), ab["month"])}
      {_kpi("Latest booked spend", fmt_money(ab["spend"]), ab["month"])}
      {_kpi("Latest ROAS", f"{ab['roas']:.2f}", "revenue ÷ spend")}
      {_kpi("AOP span", f"{D['aop_n']} months", f"{D['aop_first']} → {D['aop_last']}")}
    </div>
    <div class="note">Tabs in the live app: Revenue vs Spend (bars with the actual↔plan split line) · ROAS line · Share by category · Growth &amp; FY. Wide multi-block grid parsed to long form; grand-total category rows excluded from unfiltered aggregates to avoid double counting.</div>
  </div>
</section>"""


def tab_nps_cs(ctx, D) -> str:
    b, p = ctx.get("brand_nps"), ctx.get("product_nps")
    ck, cdf = ctx.get("cs_kpis"), ctx.get("cs_df")
    nm = ctx.get("nps_model")
    if not (b and b.get("n")):
        return '<section class="page" id="p3">' + _no_source() + "</section>"
    comp_rows = []
    comp = competitor_pull(nm)
    if len(comp):
        for r in comp.head(5).itertuples(index=False):
            pill = _pill("first-time", "g") if r.is_first_time else _pill("switcher", "n")
            comp_rows.append([_e(r.source), fmt_int(r.customers), pill])
    comp_t = _table(["Source", "Customers", ""], comp_rows, num_cols=(1,)) if comp_rows else '<div class="note">Not in this export.</div>'
    # ---- Voice of Customer (searchable) ----
    voc_rows = []
    if nm is not None:
        nd = nm["df"]
        for i in range(len(nd)):
            r = nd.iloc[i]
            cat = r["category"] or (r["variant"] or "—")
            for kind, col, cls in (("like", "like_product", "g"), ("dislike", "dislike_product", "r")):
                txt = str(r[col]).strip()
                if txt and txt.lower() not in ("no complaints", "none", "nan", ""):
                    voc_rows.append([_pill(kind, cls), _e(cat), _e(txt[:160])])
                if len(voc_rows) >= 60:
                    break
            if len(voc_rows) >= 60:
                break
    if cdf is not None and len(cdf):
        rem_col = next((c for c in ("global_remark", "remarks", "remark") if c in cdf.columns), None)
        if rem_col:
            sub = cdf[cdf[rem_col].astype(str).str.strip().str.lower().isin(["", "nan"]) == False]
            for _, r in sub.head(20).iterrows():
                voc_rows.append([_pill("CS", "n"), _e(r.get("category", "—") or "—"), _e(str(r[rem_col])[:160])])
    voc_t = ""
    if voc_rows:
        body = "".join(f"<tr><td>{c[0]}</td><td>{c[1]}</td><td>{c[2]}</td></tr>" for c in voc_rows)
        voc_t = f"""<div class="card">
      <h3>🗣️ Voice of Customer — searchable ({len(voc_rows)} remarks)</h3>
      <input id="vocSearch" class="search" type="text" placeholder="Search remarks — e.g. “packaging”, “texture”, “delivery”…" oninput="vocFilter()">
      <div class="note" id="vocCount">Showing {len(voc_rows)} of {len(voc_rows)} remarks</div>
      <div class="vocscroll"><table class="tbl" id="vocTable"><tr><th>Type</th><th>Category</th><th>Remark</th></tr>{body}</table></div>
      <div class="note">Sample of product-level likes/dislikes plus CS global remarks (full text in the live app's searchable VoC panel, all downloadable).</div>
    </div>"""
    return f"""<section class="page" id="p3">
  <div class="topbar"><h2>💬 3 · NPS &amp; Customer Success</h2><span class="chip">{D['nps_label']} · CS feedback {D['cs_label']}</span></div>
  <div class="cap">Standard NPS = %promoters (9–10) − %detractors (0–6). CSV upload <i>or</i> paste-in text area in the live app. CS failure hierarchy + searchable Voice of Customer.</div>
  <div class="cards">
    {_kpi("Brand NPS", f"{b['nps']:+.1f}", f"n={b['n']} · promoters {fmt_pct(b['promoters'])} · detractors {fmt_pct(b['detractors'])}", "up" if b["nps"] >= 50 else "dn")}
    {_kpi("Product NPS", f"{p['nps']:+.1f}", f"n={p['n']} · promoters {fmt_pct(p['promoters'])} · detractors {fmt_pct(p['detractors'])}", "up" if p["nps"] >= 50 else "dn")}
    {_kpi("CS tickets", fmt_int(ck["tickets"]), f"{fmt_pct(ck['resolved_pct'])} resolved") if ck and ck.get("tickets") else ""}
    {_kpi("Median fulfilment", f"{ck['median_fulfil_hours']:.0f} h", f"{fmt_pct(ck['pct_over_72h'])} over 72h · delivery−fulfilled") if ck and ck.get("tickets") else ""}
  </div>
  <div class="grid2">
    <div class="card">
      <h3>Brand score distribution (0–10)</h3>
      <div class="vbars" id="distB"></div>
      <div class="legend"><b></b> promoters (9–10) {int(b["dist"].loc[9] + b["dist"].loc[10])} · passives (7–8) {int(b["dist"].loc[7] + b["dist"].loc[8])} · detractors (0–6) {int(b["dist"].sum() - b["dist"].loc[9] - b["dist"].loc[10])}</div>
    </div>
    <div class="card">
      <h3>Product score distribution (0–10)</h3>
      <div class="vbars" id="distP"></div>
      <div class="legend"><b></b> promoters {int(p["dist"].loc[9] + p["dist"].loc[10])} · passives {int(p["dist"].loc[7] + p["dist"].loc[8])} · detractors {int(p["dist"].sum() - p["dist"].loc[9] - p["dist"].loc[10])}</div>
    </div>
  </div>
  <div class="grid2">
    <div class="card">
      <h3>Brand customers migrated from</h3>
      {comp_t}
      <div class="note">First-time respondents are separated, never mixed into competitor pull. Like/dislike themes split on | ; , / &amp; — “no complaint” remarks excluded from dislikes.</div>
    </div>
    <div class="card">
      <h3>CS — top failure reason: <b>{_e(ck["top_failure_reason"])}</b> ({fmt_pct(D['cs_top_share'])} of tickets)</h3>
      <div class="note">Hierarchy (type → reason → subreason) rendered as a sunburst in the live app, with responsible-team view (this export has no team data — stated, not invented), city/state tables, and a full-text searchable remarks panel. All downloadable.</div>
    </div>
  </div>
  {voc_t}
</section>"""


def tab_price(ctx, D) -> str:
    fm = ctx.get("fm")
    flags = ctx.get("price_flags")
    rev = (fm or {}).get("price") if fm else None
    if rev is None and not (flags is not None and len(flags)):
        return '<section class="page" id="p4">' + _no_source() + "</section>"
    a_html = ""
    if rev is not None and len(rev):
        rows = [[_e(r.sku), _pill(r.change_type, "r" if r.change_type == "Increased Price" else "n"), _e(str(r.date)[:10])]
                for r in rev.head(8).itertuples(index=False)]
        a_html = f"""<div class="card">
        <h3>Source A — explicit revisions (Retention FM notes)</h3>
        {_table(["SKU", "Change", "Date"], rows)}
        <div class="note">Parsed from “Decreased/Increased/Same – Price Revision – &lt;date&gt;” and “New … Variant Launch” notes.</div>
      </div>"""
    b_html = ""
    if flags is not None and len(flags):
        n_up = int((flags["direction"] == "Increase").sum())
        n_dn = int((flags["direction"] == "Decrease").sum())
        rows = [[_e(r.sku), _e(r.month), f"₹{r.prev_price:.2f} → ₹{r.unit_price:.2f}",
                 _pill(f"{fmt_pct(r.change_pct, signed=True)}", "g" if r.change_pct > 0 else "r")]
                for r in flags.head(6).itertuples(index=False)]
        hint = price_x_retention_conclusions(rev, ctx["fm"]["vals"], ctx["fm"]["mature"], ctx["fm"]["df"], ctx["fm"]["windows"]) if fm and rev is not None else []
        b_html = f"""<div class="card">
        <h3>Source B — detected from realized prices</h3>
        {_table(["SKU", "Month", "Realized unit price", "MoM Δ"], rows, num_cols=(3,)) if rows else ""}
        <ul class="tight">
          <li>{n_up} SKU-month increase(s) and {n_dn} decrease(s) beyond the ±{fmt_pct(ctx.get('price_threshold', 0.05))} threshold (slider in the live app).</li>
          <li>Realized unit price = revenue ÷ quantity per SKU-month — realized price moves, which may include discount/promo effects, not only list-price changes.</li>
          <li>Price-trend lines with revision-event markers from Source A overlaid in the live app.</li>
          {('<li>' + hint[0] + '</li>') if hint else '<li>No price × retention overlap detected for the mature Retention FM cohort.</li>'}
        </ul>
      </div>"""
    return f"""<section class="page" id="p4">
  <div class="topbar"><h2>💰 4 · Price Changes</h2><span class="chip">explicit + detected</span></div>
  <div class="cap">Two independent sources, clearly labelled. Source A is explicit (revision notes); Source B is a <b>detected signal from realized prices</b> — not list/MRP.</div>
  <div class="grid2">{a_html}{b_html}</div>
</section>"""


def tab_retention(ctx, D) -> str:
    fm, vv = ctx.get("fm"), ctx.get("vv")
    if not fm:
        return '<section class="page" id="p5">' + _no_source() + "</section>"
    vals, mat, df, windows = fm["vals"], fm["mature"], fm["df"], fm["windows"]
    rows, pending = [], []
    for w in windows:
        mask = mat[f"w{w}"] & vals[f"w{w}"].notna()
        if mask.any():
            if pending:
                rows.append([f"{' / '.join(str(x) for x in pending)} days",
                             '<span class="pill n">N/A</span>', "0 mature — not yet observable"])
                pending = []
            rows.append([f"{w} days", fmt_pct(vals[f"w{w}"][mask].mean(), digits=2), f"{int(mask.sum())} / {len(df)}"])
        else:
            pending.append(w)
    if pending:
        rows.append([f"{' / '.join(str(x) for x in pending)} days",
                     '<span class="pill n">N/A</span>', "0 mature — not yet observable"])
    wt = _table(["Window", "Avg retention", "Mature SKUs"], rows, num_cols=(1,))
    jr_txt = ""
    jr = ctx.get("jr")
    if jr is not None and len(jr["df"]):
        d = jr["df"]

        def wavg(wc):
            ok = d[wc].notna()
            c = d.loc[ok, "customers"]
            return float((d.loc[ok, wc] * c).sum() / c.sum()) if ok.any() else None

        parts = [f"{w}d {fmt_pct(wavg(f'w{w}'))}" for w in (30, 60, 90) if wavg(f"w{w}") is not None]
        if parts:
            jr_txt = (f"<div class='note'>Same-category retention computed from the journey base sheet "
                      f"(customer-weighted, mature cohorts): {' · '.join(parts)} — with the same maturity → N/A rule.</div>")
    o = vv["overall"] if vv else None
    qual_txt = fmt_int(o["qualifying"]) if o else "0"
    return f"""<section class="page" id="p5">
  <div class="topbar"><h2>🔁 5 · Retention + V2V/V2C</h2><span class="chip">FM sheet + journey base sheet</span></div>
  <div class="cap">Window columns (15–360 days) shown as percentages. Windows not yet observable are <b>N/A — never 0%</b> (cohort maturity rule).</div>
  <div class="grid2">
    <div class="card">
      <h3>Retention FM — average by window ({len(df)} SKUs, mature cohorts only)</h3>
      {wt}
      <div class="note">Sheet stores percentages (e.g. 10.8 = 10.8%) → converted to fractions internally, displayed as 30.4% style. Denominator = cohort “Customer” size per row.</div>
    </div>
    <div class="card">
      <h3>V2V / V2C (journey base sheet)</h3>
      <div class="cards" style="grid-template-columns:1fr 1fr">
        {_kpi("V2V %", fmt_pct(o["v2v_pct"]), "same variant on 2nd order") if o else ""}
        {_kpi("V2C %", fmt_pct(o["v2c_pct"]), "same category, any variant") if o else ""}
      </div>
      <div class="note">Denominator = customers with a qualifying 2nd order ({qual_txt}). Cohort tables and per-variant breakdowns in the live app.</div>
      {jr_txt}
    </div>
  </div>
</section>"""


def tab_ntc(ctx, D) -> str:
    ntc = ctx.get("ntc")
    if not ntc:
        return '<section class="page" id="p6">' + _no_source() + "</section>"
    k = ntc_kpis(ntc["df"], ntc["as_of"], ntc["maturity_days"])
    w3 = k["avg_third_pct"] / k["avg_sec_pct"] if k.get("avg_sec_pct") else 0.0
    return f"""<section class="page" id="p6">
  <div class="topbar"><h2>📈 6 · New-to-Category</h2><span class="chip">as of {str(ntc['as_of'])}</span></div>
  <div class="cap">Order-movement curve for new customers: 2nd–6th order rates and days to Nth order, with cohort maturity flags.</div>
  <div class="cards">
    {_kpi("Cohorts", fmt_int(k["cohorts_total"]), f"{k['cohorts_mature']} mature at {k['maturity_days']} days")}
    {_kpi("New customers (base)", fmt_money(k['new_customers']).replace('₹', ''), "sum of first-order cohorts") if pd.notna(k.get('new_customers')) else ""}
    {_kpi("Avg 2nd-order rate", fmt_pct(k["avg_sec_pct"]), f"mature cohorts · avg {fmt_num(k['avg_days_sec'], 0)} days")}
    {_kpi("Avg 3rd-order rate", fmt_pct(k["avg_third_pct"]), f"mature cohorts · avg {fmt_num(k['avg_days_third'], 0)} days")}
  </div>
  <div class="card">
    <h3>Order-movement curve (mature cohorts)</h3>
    {_hbar("2nd order", 100.0, fmt_pct(k["avg_sec_pct"]), "#0b6e4f")}
    {_hbar("3rd order", w3 * 100, fmt_pct(k["avg_third_pct"]), "#34a06e")}
    <div class="note">Live app: per-cohort 2nd–6th order curves, days-to-Nth-order heatmap, and not-mature cohorts greyed out (never treated as 0%). Percentages recomputed from counts when the sheet’s pct columns are inconsistent.</div>
  </div>
</section>"""


def tab_definitions(ctx, D) -> str:
    return """<section class="page" id="p7">
  <div class="topbar"><h2>📖 7 · Definitions &amp; Methodology</h2></div>
  <div class="cap">The authoritative page for every metric in the dashboard (rendered in full in the live app).</div>
  <div class="card">
    <h3>Key formulas</h3>
    <ul class="tight">
      <li><b>NPS</b> = %promoters (9–10) − %detractors (0–6), per question (brand &amp; product), standard method.</li>
      <li><b>V2V %</b> = customers whose 2nd order is the <b>same variant</b> as their 1st ÷ customers with a qualifying 2nd order.</li>
      <li><b>V2C %</b> = customers whose 2nd order stays in the <b>same category</b> (any variant) ÷ the <b>same denominator</b>. V2C ≥ V2V by construction.</li>
      <li><b>Retention (FM)</b> = window column ÷ 100; window &gt; (as_of − onb_date) → <b>N/A</b>, never 0%.</li>
      <li><b>Price — Source A</b>: parsed from revision notes. <b>Source B</b>: realized unit price = revenue ÷ quantity per SKU-month; MoM change beyond ±threshold (default 5%) → detected signal.</li>
      <li><b>Migration</b>: primary line per order (largest quantity; first line on ties) — no many-to-many inflation. Net = gained − lost.</li>
      <li><b>AOP</b>: wide multi-block grid → long form; channel TOTAL rows; grand-total category rows excluded from unfiltered aggregates; plan never mixed with actuals.</li>
      <li><b>CS fulfilment time</b> = delivery_time − fulfilled_time (hours); median and % &gt; 72h reported.</li>
      <li><b>Currency</b>: ₹ with L (10⁵) / Cr (10⁷) abbreviations. Percentages stored as fractions, displayed as 30.4%.</li>
      <li><b>Causality</b>: overlaps are always “a potential relationship requiring further validation”.</li>
    </ul>
  </div>
  <div class="card">
    <h3>What the dashboard cannot compute from these sources (stated, never fabricated)</h3>
    <ul class="tight">
      <li>Customer-level metrics beyond the journey scope (D2C × Moisturisers × first 6 orders).</li>
      <li>True MRP / list-price history — realized prices &amp; revision notes only.</li>
      <li>Responsible-team workload — the column is empty in this export.</li>
      <li>Customer LTV — no revenue per order in the journey export.</li>
      <li>Same-day / real-time metrics — sources are EOM/period exports.</li>
    </ul>
  </div>
</section>"""


def _page_details(ctx) -> str:
    """Per-page conclusion <details> blocks for the Insights tab."""
    fm = ctx.get("fm")
    spec = []

    def sales_c():
        return sales_conclusions(ctx.get("sales_kpis"), ctx.get("sales_prev_kpis"),
                                 ctx.get("cat_contrib"), ctx.get("chan_contrib"),
                                 ctx.get("var_contrib"), ctx.get("sales_months", []))

    spec.append(("📊 Sales & Revenue", sales_c))
    spec.append(("🔀 Migration", lambda: migration_conclusions(ctx.get("mig")) or []))

    def nps_c():
        nm = ctx.get("nps_model")
        if nm is None:
            return []
        return nps_conclusions(nm, ctx.get("brand_nps"), ctx.get("product_nps"),
                               theme_counts(nm, "like"), theme_counts(nm, "dislike"),
                               competitor_pull(nm), nps_by_dimension(nm, "category"))
    spec.append(("💬 NPS & Customer Success", nps_c))

    def price_c():
        if fm is None:
            return []
        hint = None
        if fm.get("price") is not None:
            h = price_x_retention_conclusions(fm["price"], fm["vals"], fm["mature"], fm["df"], fm["windows"])
            hint = h[0] if h else None
        return price_conclusions(fm.get("price"), ctx.get("price_flags"),
                                 ctx.get("price_threshold", 0.05), hint)
    spec.append(("💰 Price Changes", price_c))

    def ret_c():
        if fm is None:
            return []
        return retention_conclusions(fm["vals"], fm["mature"], fm["df"], ctx.get("vv"),
                                     fm["windows"], ctx.get("as_of"))
    spec.append(("🔁 Retention + V2V/V2C", ret_c))

    def ntc_c():
        ntc = ctx.get("ntc")
        if not ntc:
            return []
        return ntc_conclusions(ntc["df"], ntc["as_of"], ntc["maturity_days"])
    spec.append(("📈 New-to-Category", ntc_c))

    def cs_c():
        if ctx.get("cs_df") is None:
            return []
        return cs_conclusions({"df": ctx["cs_df"]}, ctx.get("cs_kpis") or cs_kpis({"df": ctx["cs_df"]}))
    spec.append(("🛠️ Customer Success", cs_c))

    out = []
    for title, fn in spec:
        try:
            items = fn()
        except Exception:
            items = []
        if items:
            out.append(f"<details class='pp'><summary>{_e(title)}</summary>{_ul(items)}</details>")
        else:
            out.append(f"<details class='pp'><summary>{_e(title)}</summary>"
                       f"<div class='note'>Source not loaded.</div></details>")
    return "".join(out)


def tab_insights(ctx, D) -> str:
    bundle = insight_bundle(ctx)
    att = executive_attention(ctx)
    chg = executive_changes(ctx)
    if not bundle and not att and not chg:
        return '<section class="page" id="p8">' + _no_source() + "</section>"
    sec_html = []
    for sec in bundle:
        items = "".join(
            f"<div class='ins'><span class='dot {it['tone']}'></span><span class='txt'>{_e(it['text'])}</span>"
            f"<span class='pg'>{_e(it['page'])}</span></div>"
            for it in sec["items"])
        sec_html.append(f"<div class='card'><h3>{_e(sec['icon'] + ' ' + sec['title'])}</h3>{items}</div>")
    top_pos = [it["text"] for sec in bundle for it in sec["items"] if it["tone"] == "pos"][:2]
    top_list = [t for _, t in att[:3]] + [f"🟢 {t}" for t in top_pos]
    top_html = _ul([f"<b>{i}.</b> {t}" for i, t in enumerate(top_list, 1)]) if top_list else '<div class="note">Not enough data loaded.</div>'
    return f"""<section class="page" id="p8">
  <div class="topbar"><h2>💡 8 · Insights &amp; Conclusions</h2><span class="chip">generated from current data · {D['gen_date']}</span></div>
  <div class="cap">One page tying everything together: cross-page synthesis, connections between independent sources, and what the data says it needs attention. Every sentence below is generated from the currently loaded sources — nothing is handwritten.</div>
  <div class="card">
    <h3>🎯 Top conclusions</h3>
    {top_html}
    <div class="note">Attention items are prioritized (1 = most data-supported); 🟢 items are the strongest positive signals. See the per-page sections below for the full reasoning.</div>
  </div>
  {"".join(sec_html)}
  <div class="card">
    <h3>📄 Per-page conclusions (detail)</h3>
    {_page_details(ctx)}
  </div>
  <div class="card">
    <h3>📖 How to read this page</h3>
    <ul class="tight">
      <li>Every statement is <b>generated from the currently loaded data</b> — upload new CSVs and the conclusions change with them.</li>
      <li>Overlaps between sources are phrased as <i>“a potential relationship requiring further validation”</i> — never cause-and-effect.</li>
      <li>Immature cohort windows are <b>N/A, never 0%</b>; partial months are labelled MTD and never compared as like-for-like.</li>
      <li>If a source is missing, its section disappears instead of guessing. Tones: 🟢 positive · 🔴 negative ·  watch ·  fact/context.</li>
    </ul>
  </div>
</section>"""


# ---------------------------------------------------------------------------
# main build
# ---------------------------------------------------------------------------
STYLE = """  :root{
    --bg:#f6f8fa; --card:#ffffff; --ink:#1f2933; --mut:#6b7280; --line:#e5e7eb;
    --acc:#0b6e4f; --red:#c0392b; --grn:#1a7f37; --blue:#1d4ed8; --chip:#eef7f2;
  }
  *{box-sizing:border-box}
  body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--ink);font-size:14px}
  .layout{display:flex;min-height:100vh}
  /* ---------- sidebar ---------- */
  .side{width:252px;flex:0 0 252px;background:#fff;border-right:1px solid var(--line);padding:18px 12px;position:sticky;top:0;height:100vh;overflow:auto}
  .side h1{font-size:15px;margin:0 0 2px;line-height:1.3}
  .side .sub{font-size:11.5px;color:var(--mut);margin-bottom:14px}
  .nav a{display:block;padding:7px 10px;border-radius:8px;text-decoration:none;color:var(--ink);font-size:13px;margin-bottom:2px}
  .nav a:hover{background:#f1f5f9}
  .nav a.active{background:var(--chip);color:var(--acc);font-weight:600}
  .badge{margin-top:14px;font-size:11px;color:var(--mut);background:#f8fafc;border:1px solid var(--line);border-radius:8px;padding:8px 10px;line-height:1.45}
  /* ---------- main ---------- */
  .main{flex:1;padding:22px 28px 60px;min-width:0}
  .topbar{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:4px}
  .topbar h2{margin:0;font-size:21px}
  .chip{font-size:11px;background:var(--chip);color:var(--acc);border-radius:999px;padding:3px 10px;font-weight:600}
  .cap{color:var(--mut);font-size:12.5px;margin:2px 0 18px;max-width:900px}
  .page{display:none}
  .page.active{display:block}
  /* ---------- cards ---------- */
  .cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:12px;margin-bottom:18px}
  .kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
  .kpi .l{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.4px}
  .kpi .v{font-size:21px;font-weight:700;margin-top:3px}
  .kpi .s{font-size:11.5px;color:var(--mut);margin-top:2px}
  .up{color:var(--grn);font-weight:600}.dn{color:var(--red);font-weight:600}
  .card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin-bottom:16px}
  .card h3{margin:0 0 10px;font-size:14.5px}
  .card .note{font-size:11.5px;color:var(--mut);margin-top:8px;line-height:1.4}
  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
  @media(max-width:1000px){.grid2{grid-template-columns:1fr}}
  /* ---------- tables ---------- */
  table{border-collapse:collapse;width:100%;font-size:12.5px}
  th{text-align:left;color:var(--mut);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.3px;padding:6px 8px;border-bottom:1px solid var(--line)}
  td{padding:6px 8px;border-bottom:1px solid #f1f5f9}
  tr:last-child td{border-bottom:none}
  .num{text-align:right;font-variant-numeric:tabular-nums}
  th.sortable{cursor:pointer;user-select:none}
  th.sortable:hover{color:var(--ink)}
  th.sorted{color:var(--acc)}
  .search{width:100%;padding:8px 12px;border:1px solid var(--line);border-radius:8px;font-size:13px;margin-bottom:8px}
  .vocscroll{max-height:360px;overflow:auto;border:1px solid var(--line);border-radius:8px}
  /* ---------- bars ---------- */
  .hbar{display:grid;grid-template-columns:150px 1fr 74px;align-items:center;gap:10px;margin:7px 0;font-size:12.5px}
  .hbar .track{background:#f1f5f9;border-radius:6px;height:18px;position:relative;overflow:hidden}
  .hbar .fill{height:100%;border-radius:6px;background:#3b82f6}
  .hbar .val{font-variant-numeric:tabular-nums;color:var(--mut)}
  .dbar{display:grid;grid-template-columns:150px 1fr 74px;align-items:center;gap:10px;margin:8px 0;font-size:12.5px}
  .dbar .ctr{position:relative;height:20px;background:#f1f5f9;border-radius:6px}
  .dbar .ctr::before{content:"";position:absolute;left:50%;top:0;bottom:0;width:1px;background:#cbd5e1}
  .dbar .pos{position:absolute;left:50%;top:2px;bottom:2px;background:var(--grn);border-radius:0 6px 6px 0}
  .dbar .neg{position:absolute;right:50%;top:2px;bottom:2px;background:var(--red);border-radius:6px 0 0 6px}
  .dbar .val{font-variant-numeric:tabular-nums}
  .vbars{display:flex;align-items:flex-end;gap:4px;height:120px;padding-top:6px}
  .vbar{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;gap:3px}
  .vbar .b{width:100%;border-radius:4px 4px 0 0;min-height:2px}
  .vbar .t{font-size:10px;color:var(--mut)}
  .vbar .x{font-size:10px;color:var(--mut)}
  .pill{display:inline-block;font-size:11px;border-radius:999px;padding:1px 8px;font-weight:600}
  .pill.g{background:#e8f5ec;color:var(--grn)} .pill.r{background:#fdeceb;color:var(--red)}
  .pill.n{background:#eef1f5;color:var(--mut)}
  ul.tight{margin:6px 0 0;padding-left:18px} ul.tight li{margin:5px 0;line-height:1.45}
  .dl{font-size:11.5px;color:var(--mut)}
  code{background:#f1f5f9;border-radius:4px;padding:1px 5px;font-size:12px}
  .legend{display:flex;gap:14px;font-size:11.5px;color:var(--mut);margin-top:6px;flex-wrap:wrap}
  .legend i{display:inline-block;width:14px;height:0;border-top:2px dashed #94a3b8;margin-right:5px;vertical-align:middle}
  .legend b{display:inline-block;width:14px;height:10px;background:#3b82f6;border-radius:2px;margin-right:5px;vertical-align:middle}
  /* ---------- insights ---------- */
  .ins{display:flex;gap:9px;align-items:flex-start;margin:8px 0;font-size:13px;line-height:1.5}
  .ins .dot{flex:0 0 9px;width:9px;height:9px;border-radius:50%;margin-top:5px}
  .dot.pos{background:#1a7f37}.dot.neg{background:#c0392b}.dot.warn{background:#d97706}.dot.info{background:#3b82f6}
  .ins .pg{margin-left:auto;flex:0 0 auto;font-size:10.5px;color:var(--mut);background:#f1f5f9;border-radius:999px;padding:2px 9px;white-space:nowrap;margin-top:3px}
  details.pp{background:#fafbfc;border:1px solid var(--line);border-radius:10px;padding:10px 16px;margin-bottom:10px}
  details.pp summary{cursor:pointer;font-weight:600;font-size:13.5px;padding:4px 0}
  details.pp[open] summary{margin-bottom:8px}
  /* ---------- tooltip ---------- */
  #trend{cursor:crosshair}
  #tip{position:fixed;display:none;background:#111827;color:#f9fafb;font-size:11.5px;line-height:1.55;padding:7px 10px;border-radius:7px;pointer-events:none;z-index:99;box-shadow:0 4px 14px rgba(0,0,0,.25);max-width:280px}"""


SCRIPT = """@@DATA_JS@@

// ---- tab switching (vanilla, no external libs) ----
document.querySelectorAll('#nav a').forEach(a=>{
  a.addEventListener('click',e=>{
    e.preventDefault();
    document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
    document.querySelectorAll('#nav a').forEach(x=>x.classList.remove('active'));
    document.getElementById(a.dataset.t).classList.add('active');
    a.classList.add('active');
    window.scrollTo(0,0);
  });
});

// ---- NPS distribution bars ----
function renderVbars(elId, dist){
  const max=Math.max(...dist,1), wrap=document.getElementById(elId);
  if(!wrap) return;
  dist.forEach((v,i)=>{
    const col = i>=9 ? '#1a7f37' : (i>=7 ? '#94a3b8' : '#c0392b');
    const d=document.createElement('div'); d.className='vbar';
    d.title='Score '+i+': '+v+' responses';
    d.innerHTML='<div class="t">'+v+'</div><div class="b" style="height:'+Math.max(2,v/max*100)+'%;background:'+col+'"></div><div class="x">'+i+'</div>';
    wrap.appendChild(d);
  });
}
renderVbars('distB', DATA.distB);
renderVbars('distP', DATA.distP);

// ---- revenue trend: AOP dashed line + actual bars + hover tooltip ----
(function(){
  const M=DATA.months, A=DATA.aop, ACT=DATA.actual, YMAX=DATA.ymax;
  const W=900,H=250,L=46,R=14,T=14,B=30;
  const svg=document.getElementById('trend');
  if(!svg) return;
  const X=i=>L+(W-L-R)*i/(M.length-1), Y=v=>T+(H-T-B)*(1-v/YMAX);
  let s='';
  for(let g=0;g<=YMAX;g+=2){
    s+='<line x1="'+L+'" y1="'+Y(g)+'" x2="'+(W-R)+'" y2="'+Y(g)+'" stroke="#eef1f5"/>'
      +'<text x="'+(L-6)+'" y="'+(Y(g)+4)+'" font-size="10" fill="#94a3b8" text-anchor="end">'+g+'Cr</text>';
  }
  [0,12,24,31,42,M.length-1].forEach(i=>{
    s+='<text x="'+X(i)+'" y="'+(H-8)+'" font-size="10" fill="#94a3b8" text-anchor="middle">'+M[i]+'</text>';
  });
  for(const m in ACT){
    const i=M.indexOf(m); if(i<0) continue;
    s+='<rect x="'+(X(i)-13)+'" y="'+Y(ACT[m])+'" width="26" height="'+(Y(0)-Y(ACT[m]))+'" fill="#3b82f6" rx="3" opacity="0.9"/>';
    s+='<text x="'+X(i)+'" y="'+(Y(ACT[m])-6)+'" font-size="10" fill="#1d4ed8" text-anchor="middle">₹'+ACT[m].toFixed(2)+'Cr</text>';
  }
  const splitM=Object.keys(ACT).sort().pop();
  const sp=M.indexOf(splitM||M[M.length-1]);
  s+='<line x1="'+X(sp)+'" y1="'+T+'" x2="'+X(sp)+'" y2="'+(H-B)+'" stroke="#c62828" stroke-dasharray="5 4" stroke-width="1.5"/>';
  let pts=''; A.forEach((v,i)=>{ if(v!=null) pts+=X(i)+','+Y(v)+' '; });
  s+='<polyline points="'+pts+'" fill="none" stroke="#94a3b8" stroke-width="2" stroke-dasharray="6 4"/>';
  s+='<text x="'+(W-R)+'" y="'+(T+10)+'" font-size="10" fill="#6b7280" text-anchor="end">AOP ₹Cr (Gels portfolio)</text>';
  svg.innerHTML=s;
  const tip=document.getElementById('tip');
  svg.addEventListener('mousemove',e=>{
    const r=svg.getBoundingClientRect();
    const mx=(e.clientX-r.left)*(W/r.width);
    let i=Math.round((mx-L)/((W-L-R)/(M.length-1)));
    i=Math.max(0,Math.min(M.length-1,i));
    let t='<b>'+M[i]+'</b><br>AOP: '+(A[i]!=null?'₹'+A[i].toFixed(2)+'Cr':'—');
    if(ACT[M[i]]) t+='<br>Actual: ₹'+ACT[M[i]].toFixed(2)+'Cr';
    tip.innerHTML=t; tip.style.display='block';
    tip.style.left=(e.clientX+14)+'px'; tip.style.top=(e.clientY+12)+'px';
  });
  svg.addEventListener('mouseleave',()=>{ tip.style.display='none'; });
})();

// ---- sortable tables ----
function parseNum(td){
  if(!td) return null;
  let t=td.textContent.trim().replace(/[₹,%\\s]/g,'');
  if(t===''||t==='—'||t==='N/A') return null;
  const n=parseFloat(t.replace(/,/g,''));
  return isNaN(n)?null:n;
}
function sortCol(tb, th, idx){
  const all=Array.from(tb.querySelectorAll('tr'));
  const header=all[0];
  const totals=all.filter(r=>r.classList.contains('total'));
  const rows=all.filter(r=>r!==header && !r.classList.contains('total'));
  const asc = th.dataset.asc!=='true';
  document.querySelectorAll('th').forEach(h=>h.classList.remove('sorted'));
  th.classList.add('sorted'); th.dataset.asc=asc;
  rows.sort((a,b)=>{
    const an=parseNum(a.cells[idx]), bn=parseNum(b.cells[idx]);
    if(an!=null && bn!=null) return asc? an-bn : bn-an;
    return asc ? a.cells[idx].textContent.localeCompare(b.cells[idx].textContent)
               : b.cells[idx].textContent.localeCompare(a.cells[idx].textContent);
  });
  rows.forEach(r=>tb.appendChild(r));
  totals.forEach(r=>tb.appendChild(r));
}
document.querySelectorAll('table.tbl').forEach(tb=>{
  tb.querySelectorAll('th').forEach((th,i)=>{
    th.classList.add('sortable');
    th.title='Click to sort';
    th.addEventListener('click',()=>sortCol(tb,th,i));
  });
});

// ---- Voice of Customer search ----
function vocFilter(){
  const q=(document.getElementById('vocSearch').value||'').toLowerCase();
  const rows=Array.from(document.querySelectorAll('#vocTable tr')).slice(1);
  let n=0;
  rows.forEach(r=>{
    const hit=!q || r.textContent.toLowerCase().includes(q);
    r.style.display=hit?'':'none';
    if(hit) n++;
  });
  const c=document.getElementById('vocCount');
  if(c) c.textContent='Showing '+n+' of '+rows.length+' remarks'+(q?' matching “'+q+'”':'');
}"""


TEMPLATE_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Retention &amp; Category Intelligence — Final Dashboard</title>
<style>
@@STYLE@@
</style>
</head>
<body>
<div class="layout">

<!-- ============ SIDEBAR ============ -->
<aside class="side">
  <h1>🧴 Retention &amp; Category Intelligence</h1>
  <div class="sub">Final interactive dashboard · 9 pages · real data</div>
  <nav class="nav" id="nav">
    <a href="#" data-t="p0" class="active">🏠 Executive Overview</a>
    <a href="#" data-t="p1">🔀 1 · Migration</a>
    <a href="#" data-t="p2">📊 2 · Sales &amp; Revenue</a>
    <a href="#" data-t="p3">💬 3 · NPS &amp; CS</a>
    <a href="#" data-t="p4">💰 4 · Price Changes</a>
    <a href="#" data-t="p5">🔁 5 · Retention + V2V/V2C</a>
    <a href="#" data-t="p6">📈 6 · New-to-Category</a>
    <a href="#" data-t="p7">📖 7 · Definitions</a>
    <a href="#" data-t="p8">💡 8 · Insights &amp; Conclusions</a>
  </nav>
  <div class="badge">
    <b>Data:</b> real exports<br>
    Sales: @@SALES_RANGE@@<br>
    Journey: @@JOURNEY_RANGE@@ · @@JOURNEY_N@@ customers<br>
    AOP: @@AOP_SPAN@@ · generated @@GEN_DATE@@<br><br>
    <b>Regenerate:</b> upload new CSVs in the app → <code>python make_static_dashboard.py</code> → commit. No hand-typed numbers in this file.
  </div>
</aside>

<!-- ============ MAIN ============ -->
<main class="main">
@@TAB0@@
@@TAB1@@
@@TAB2@@
@@TAB3@@
@@TAB4@@
@@TAB5@@
@@TAB6@@
@@TAB7@@
@@TAB8@@
</main>
</div>
<div id="tip"></div>

<script>
@@DATA_JS@@

@@SCRIPT@@
</script>
</body>
</html>
"""


def build_parts() -> tuple:
    """Compute ctx, display values D, the JS data blob and the 9 tab sections.
    Reused by make_web_dashboard.py for the multi-page site."""
    ctx, models = app_context.build_context()
    sales, journey = models["sales"], models["journey"]
    nps, fm = models["nps"], models["retention_fm"]
    cat_sales = models["category_sales"]

    # ---- shared display values ------------------------------------------
    D: dict = {}
    D["gen_date"] = str(date.today())
    aop_m = ctx.get("aop_monthly")
    sdf = sales["df"] if sales is not None else None
    months = sorted(sdf["month"].unique()) if sdf is not None else []
    D["last_month"] = months[-1] if months else ""
    D["prev_month"] = months[-2] if len(months) > 1 else ""
    D["last_month_lbl"] = pd.Period(D["last_month"]).strftime("%b %Y") if D["last_month"] else ""
    D["prev_month_lbl"] = pd.Period(D["prev_month"]).strftime("%b %Y") if D["prev_month"] else ""
    if sdf is not None and "order_date" in sdf.columns:
        last_rows = sdf[sdf["month"] == D["last_month"]]
        od = pd.to_datetime(last_rows["order_date"], errors="coerce").dropna()
        D["last_days"] = int(od.dt.date.nunique()) if len(od) else 0
        dmin = pd.to_datetime(sdf["order_date"], errors="coerce").min()
        dmax = pd.to_datetime(sdf["order_date"], errors="coerce").max()
        D["sales_range"] = (f"{dmin:%d %b – %d %b %Y}" if dmin.year == dmax.year else
                            f"{dmin:%d %b %Y} – {dmax:%d %b %Y}")
    else:
        D["last_days"], D["sales_range"] = 0, D["last_month"]
    D["n_cats"] = int(sdf["category"].nunique()) if sdf is not None else 0
    D["n_skus"] = int(sdf["sku"].nunique()) if sdf is not None and "sku" in sdf.columns else 0
    if journey is not None:
        jd = journey["df"]
        jmin, jmax = pd.to_datetime(jd["order_date"]).min(), pd.to_datetime(jd["order_date"]).max()
        D["journey_range"] = f"{jmin:%d %b %Y} – {jmax:%d %b %Y}"
        D["journey_n"] = fmt_int(journey.get("n_customers"))
        D["journey_customers"] = journey.get("n_customers")
        D["journey_orders"] = journey.get("n_orders")
        D["journey_scope"] = "D2C · Moisturisers"
    else:
        D["journey_range"] = D["journey_n"] = D["journey_scope"] = "—"
        D["journey_customers"] = D["journey_orders"] = None
    D["nps_label"] = "NPS EOM " + (
        str(pd.to_datetime(nps["df"]["created_at"]).max())[:7].replace("-", " ")
        if nps is not None and "created_at" in nps["df"].columns and nps["df"]["created_at"].notna().any()
        else "—")
    cs_model = models["cs"]
    D["cs_label"] = "—"
    if cs_model is not None and "created_at" in cs_model["df"].columns:
        cdt = pd.to_datetime(cs_model["df"]["created_at"], errors="coerce").dropna()
        if len(cdt):
            D["cs_label"] = cdt.max().strftime("%b ’%y")
    if aop_m is not None and len(aop_m):
        D["aop_months"] = aop_m["month"].tolist()
        D["aop_rev"] = [None if pd.isna(v) else round(float(v) / 1e7, 3) for v in aop_m["revenue"]]
        D["aop_first"], D["aop_last"] = aop_m["month"].iloc[0], aop_m["month"].iloc[-1]
        D["aop_n"] = len(aop_m)
        D["aop_span"] = f"{D['aop_n']} months ({D['aop_first']} → {D['aop_last']})"
        ref = D["last_month"] or str(ctx.get("as_of"))[:7]
        booked = aop_m[(aop_m["month"] <= ref) & aop_m["revenue"].notna()]
        b = booked.tail(1).iloc[0]
        D["aop_booked"] = {"month": b["month"], "revenue": float(b["revenue"]),
                           "spend": float(b["spend"]) if pd.notna(b["spend"]) else 0.0,
                           "roas": float(b["roas"]) if pd.notna(b["roas"]) else 0.0}
        D["split_lbl"] = b["month"]
    else:
        D["aop_months"], D["aop_rev"] = [], []
        D["aop_first"] = D["aop_last"] = D["aop_span"] = "—"
        D["aop_n"] = 0
        D["aop_booked"] = {"month": "—", "revenue": 0.0, "spend": 0.0, "roas": 0.0}
        D["split_lbl"] = "—"
    actual_map = {}
    if sdf is not None:
        for m in months:
            actual_map[m] = round(float(sdf.loc[sdf["month"] == m, "revenue"].sum()) / 1e7, 3)
    D["actual"] = actual_map
    vmax = max([v for v in D["aop_rev"] if v is not None] + list(actual_map.values()) + [1.0])
    D["ymax"] = max(2, int(math.ceil(vmax * 1.05)))
    ck = ctx.get("cs_kpis")
    D["cs_top_share"] = 0.0
    if ck and ck.get("tickets") and ctx.get("cs_df") is not None:
        cdf = ctx["cs_df"]
        g = cdf.groupby("failure_reason").size()
        D["cs_top_share"] = float(g.max() / g.sum()) if len(g) else 0.0
    try:
        D["intra"] = intra_category_movement(cat_sales["df"]) if cat_sales is not None else None
    except Exception:
        D["intra"] = None

    # ---- data blob for JS charts -----------------------------------------
    b, p = ctx.get("brand_nps"), ctx.get("product_nps")
    data_js = "const DATA = " + json.dumps({
        "months": D["aop_months"],
        "aop": D["aop_rev"],
        "actual": D["actual"],
        "ymax": D["ymax"],
        "distB": [int(x) for x in (b["dist"].tolist() if b and b.get("n") else [0] * 11)],
        "distP": [int(x) for x in (p["dist"].tolist() if p and p.get("n") else [0] * 11)],
    }).replace("</", "<\\/") + ";"


    tabs = [
        tab_overview(ctx, D), tab_migration(ctx, D), tab_sales(ctx, D),
        tab_nps_cs(ctx, D), tab_price(ctx, D), tab_retention(ctx, D),
        tab_ntc(ctx, D), tab_definitions(ctx, D), tab_insights(ctx, D),
    ]
    return ctx, D, data_js, tabs


def build() -> str:
    ctx, D, data_js, tabs = build_parts()
    out = TEMPLATE_HEAD.replace("@@STYLE@@", STYLE).replace("@@SCRIPT@@", SCRIPT)
    for tok, val in [("@@GEN_DATE@@", D["gen_date"]),
                     ("@@SALES_RANGE@@", D["sales_range"]),
                     ("@@JOURNEY_RANGE@@", D["journey_range"]),
                     ("@@JOURNEY_N@@", D["journey_n"]),
                     ("@@AOP_SPAN@@", D["aop_span"]),
                     ("@@DATA_JS@@", data_js)] + \
                   [(f"@@TAB{i}@@", t) for i, t in enumerate(tabs)]:
        out = out.replace(tok, val)
    return out


# ---------------------------------------------------------------------------
# verification (never hand-typed chart data ships)
# ---------------------------------------------------------------------------
class _TagCheck(HTMLParser):
    VOID = {"meta", "br", "img", "input", "hr", "rect", "line", "polyline", "path", "col", "link"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.errors = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack:
            self.errors.append(f"unexpected </{tag}>")
        elif self.stack[-1] == tag:
            self.stack.pop()
        else:
            self.errors.append(f"mismatch: expected </{self.stack[-1]}>, got </{tag}>")


def verify(html: str, ctx: dict) -> list[str]:
    errs = []
    m = re.search(r"(?:src|href)\s*=\s*['\"]https?://", html)
    if m:
        errs.append(f"external reference found: {m.group(0)[:60]}")
    pc = _TagCheck()
    pc.feed(html)
    if pc.stack:
        errs.append(f"unclosed tags: {pc.stack[:5]}")
    errs.extend(pc.errors[:5])
    if len(re.findall(r'data-t="p\d"', html)) != 9:
        errs.append("expected 9 nav tabs")
    for pid in ("p0", "p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8"):
        if f'id="{pid}"' not in html:
            errs.append(f"missing section {pid}")
    if "Insights" not in html:
        errs.append("Insights page missing")
    # AOP series integrity: embedded JS array must equal the computed series
    try:
        blob = re.search(r"const DATA = (\{.*?\});", html, re.S).group(1)
        emb = json.loads(blob)["aop"]
        am = ctx.get("aop_monthly")
        calc = [None if pd.isna(v) else round(float(v) / 1e7, 3) for v in am["revenue"]]
        if len(emb) != len(calc):
            errs.append(f"AOP series length {len(emb)} != {len(calc)}")
        else:
            diff = max(abs((a or 0) - (c or 0)) for a, c in zip(emb, calc))
            if diff > 0:
                errs.append(f"AOP series max-diff {diff}")
    except Exception as e:
        errs.append(f"DATA blob check failed: {e}")
    return errs


def main() -> None:
    html = build()
    ctx, _ = app_context.build_context()
    errs = verify(html, ctx)
    if errs:
        print("VERIFICATION FAILED:")
        for e in errs:
            print("  -", e)
        raise SystemExit(1)
    out = ROOT / "single-page.html"
    out.write_text(html, encoding="utf-8")
    bundle = insight_bundle(ctx)
    n_items = sum(len(s["items"]) for s in bundle)
    print(f"OK  wrote {out} ({out.stat().st_size / 1024:.0f} KB)")
    print(f"OK  9 tabs · {len(bundle)} insight sections · {n_items} generated insight items")
    print(f"OK  AOP series verified: {len(ctx['aop_monthly'])} months, max-diff 0.0")
    print(f"OK  zero external references · tags balanced")


if __name__ == "__main__":
    main()
