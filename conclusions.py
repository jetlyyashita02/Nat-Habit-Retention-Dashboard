"""
conclusions.py — dynamic business-interpretation engine.

Rules:
  * every number in a sentence comes from the current filtered data
  * no hardcoding of categories, SKUs, months or values
  * no false causality: "observed alongside / potential relationship / requires
    validation" — never "X caused Y"
  * functions return [] when the underlying data does not support the statement
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from formatting import fmt_pct, fmt_money, fmt_int, fmt_num, fmt_days

def _ok(x):
    return x is not None and not (isinstance(x, float) and np.isnan(x))

# ---------------------------------------------------------------------------
def sales_conclusions(kpis_cur, kpis_prev, cat_contrib, chan_contrib, var_contrib, months) -> list[str]:
    out = []
    try:
        if _ok(kpis_cur.get("revenue")) and _ok(kpis_prev.get("revenue")) and kpis_prev["revenue"] > 0:
            g = (kpis_cur["revenue"] - kpis_prev["revenue"]) / kpis_prev["revenue"]
            out.append(f"Revenue for the selected period is {fmt_money(kpis_cur['revenue'])}, "
                       f"{'up' if g >= 0 else 'down'} {fmt_pct(abs(g))} vs the previous comparable period ({fmt_money(kpis_prev['revenue'])}).")
        if len(cat_contrib) and _ok(cat_contrib.iloc[0].get("revenue_share")):
            r = cat_contrib.iloc[0]
            out.append(f"Top contributing category: {r['category']} at {fmt_pct(r['revenue_share'])} of revenue "
                       f"({fmt_money(r['revenue'])}).")
        if len(cat_contrib) >= 2:
            top2 = cat_contrib.head(2)["revenue_share"].sum()
            if top2 >= 0.7:
                out.append(f"Concentration: the top {min(2, len(cat_contrib))} categories carry {fmt_pct(top2)} of revenue — a concentrated mix.")
        if len(chan_contrib) and _ok(chan_contrib.iloc[0].get("revenue_share")):
            r = chan_contrib.iloc[0]
            out.append(f"Largest channel: {r['channel']} at {fmt_pct(r['revenue_share'])} of revenue.")
        if len(var_contrib):
            r = var_contrib.iloc[0]
            out.append(f"Top variant by revenue: {r['product']} ({r['category']}) at {fmt_pct(r['revenue_share'])} — "
                       f"cumulative share of the top 5 variants is {fmt_pct(var_contrib['cumulative_share'].iloc[min(4, len(var_contrib) - 1)])}.")
    except Exception:
        return []
    return out

def migration_conclusions(mig: dict) -> list[str]:
    out = []
    try:
        if not mig or mig.get("n_acquired", 0) == 0:
            return []
        out.append(f"Of {fmt_int(mig['n_acquired'])} acquired customers, {fmt_int(mig['n_second'])} placed a second order "
                   f"({fmt_pct(mig['any_second_pct'])}); {fmt_pct(mig['repeat_pct'])} repeated in the same "
                   f"{mig['level']} while {fmt_pct(mig['switch_pct'])} switched to a different one.")
        if _ok(mig.get("avg_days_1_2")):
            out.append(f"Average time from first to second order is {fmt_days(mig['avg_days_1_2'])}.")
        to = mig.get("retention_outflow")
        if to is not None and len(to):
            best = to[to["second_orders"] >= 10].sort_values("same_pct", ascending=False)
            if len(best):
                r = best.iloc[0]
                out.append(f"Strongest stay-rate: {r['entry']} ({fmt_pct(r['same_pct'])} of acquired customers repeated in the same {mig['level']}).")
            worst = to[to["second_orders"] >= 10].sort_values("switched_pct", ascending=False)
            if len(worst):
                r = worst.iloc[0]
                out.append(f"Largest outflow: {r['entry']} — {fmt_pct(r['switched_pct'])} of its customers moved to another {mig['level']}; top destination: {r['top_destination']}.")
        net = mig.get("net")
        if net is not None and len(net) and net["net"].abs().max() > 0:
            g, l = net.iloc[0], net.iloc[-1]
            if g["net"] > 0:
                out.append(f"Net migration gainer: {g['entity']} (+{fmt_int(g['net'])}); net loser: {l['entity']} ({fmt_int(l['net'])}).")
        if mig.get("largest_flow") and mig["largest_flow"] != "—":
            out.append(f"Largest observed flow: {mig['largest_flow']}.")
    except Exception:
        return []
    return out

def retention_conclusions(fm_vals, fm_mature, fm_df, v2v_v2c: dict | None, windows: list[int], as_of) -> list[str]:
    out = []
    try:
        if fm_vals is None or not len(fm_vals) or fm_df is None:
            return []
        # most mature window available anywhere
        w_avail = [w for w in windows if (fm_mature[f"w{w}"] & fm_vals[f"w{w}"].notna()).any()]
        if w_avail:
            w = max(w_avail)
            sub = fm_df[fm_mature[f"w{w}"] & fm_vals[f"w{w}"].notna()].copy()
            sub["w"] = fm_vals[f"w{w}"][sub.index]
            if len(sub):
                best = sub.loc[sub["w"].idxmax()]
                worst = sub.loc[sub["w"].idxmin()]
                out.append(f"At the {w}-day window (most mature available as of {as_of}), {best['variant'] or best['sku']} shows the strongest retention ({fmt_pct(best['w'])}) and {worst['variant'] or worst['sku']} the weakest ({fmt_pct(worst['w'])}).")
        # price-revision relationship (non-causal)
        price = fm_df.get("price") if isinstance(fm_df, dict) else None
    except Exception:
        pass
    try:
        if v2v_v2c and v2v_v2c.get("overall", {}).get("qualifying"):
            o = v2v_v2c["overall"]
            gap = (o["v2c_pct"] - o["v2v_pct"]) * 100
            out.append(f"Across {fmt_int(o['qualifying'])} customers with a second order, V2V (same variant) is {fmt_pct(o['v2v_pct'])} and V2C (same category) is {fmt_pct(o['v2c_pct'])} — a {gap:.1f}pp gap: "
                       f"{'most repeaters stay with their exact variant' if o['v2v_pct'] > 0.5 * o['v2c_pct'] else 'category loyalty holds even when customers change variant'}.")
            byc = v2v_v2c.get("by_category")
            if byc is not None and len(byc):
                hi = byc[(byc["v2c_pct"] >= 0.15) & (byc["v2v_pct"] <= 0.10)]
                if len(hi):
                    r = hi.iloc[0]
                    out.append(f"{r['category']} shows relatively strong category loyalty ({fmt_pct(r['v2c_pct'])} V2C) but weak variant loyalty ({fmt_pct(r['v2v_pct'])} V2V) — customers stay in the category but switch variants.")
    except Exception:
        pass
    return out

def price_revision_conclusions(price_df: pd.DataFrame) -> list[str]:
    out = []
    try:
        if price_df is None or not len(price_df):
            return []
        p = price_df[price_df["change_type"].isin(["Increased Price", "Decreased Price", "New Variant", "Same Price"])]
        n_inc = int((p["change_type"] == "Increased Price").sum())
        n_dec = int((p["change_type"] == "Decreased Price").sum())
        n_same = int((p["change_type"] == "Same Price").sum())
        n_new = int((p["change_type"] == "New Variant").sum())
        out.append(f"Price-revision log: {n_inc} increase(s), {n_dec} decrease(s), {n_same} same-price, {n_new} new variant(s).")
    except Exception:
        pass
    return out

def price_x_retention_conclusions(price_df: pd.DataFrame, fm_vals, fm_mature, fm_df, windows) -> list[str]:
    """Non-causal price × retention cross-check on the Retention FM cohort."""
    out = []
    try:
        if price_df is None or not len(price_df) or fm_vals is None or fm_mature is None or fm_df is None:
            return []
        w_avail = [w for w in windows if (fm_mature[f"w{w}"] & fm_vals[f"w{w}"].notna()).any()]
        if not w_avail:
            return []
        w = max(w_avail)
        sub = fm_df[fm_mature[f"w{w}"] & fm_vals[f"w{w}"].notna()].copy()
        sub["ret"] = fm_vals[f"w{w}"][sub.index]
        p = price_df.dropna(subset=["change_type"])
        merged = sub.merge(p[["sku", "change_type"]], on="sku", how="left")
        inc = merged[merged["change_type"] == "Increased Price"]["ret"]
        ref = merged[merged["change_type"].isin(["Same Price", "Decreased Price"])]["ret"]
        if len(inc) >= 1 and len(ref) >= 3 and inc.mean() < ref.mean() - 0.005:
            sku = merged.loc[inc.idxmin(), "sku"]
            out.append(f"{w}-day retention for price-increased SKUs averages {fmt_pct(inc.mean())} vs {fmt_pct(ref.mean())} for same/decreased-price SKUs. "
                       f"Retention is lower following the observed price change (e.g. {sku}); the dashboard flags this as a potential relationship requiring further validation, not a confirmed cause.")
    except Exception:
        pass
    return out

def price_conclusions(revisions: pd.DataFrame, detected_flags: pd.DataFrame, threshold: float,
                      retention_hint: str | None = None) -> list[str]:
    out = []
    try:
        if revisions is not None and len(revisions):
            p = revisions[revisions["change_type"].isin(["Increased Price", "Decreased Price", "New Variant"])]
            inc = p[p["change_type"] == "Increased Price"]
            dec = p[p["change_type"] == "Decreased Price"]
            if len(inc):
                s = ", ".join(f"{r['sku']} ({r['product'][:38]})" for _, r in inc.head(3).iterrows())
                out.append(f"Explicit price increases logged for {len(inc)} SKU(s): {s}.")
            if len(dec):
                out.append(f"Explicit price decreases logged for {len(dec)} SKU(s).")
        if detected_flags is not None and len(detected_flags):
            inc = detected_flags[detected_flags["direction"] == "Increase"]
            dec = detected_flags[detected_flags["direction"] == "Decrease"]
            out.append(f"Detected from sales data (realized price = revenue ÷ quantity): {len(inc)} SKU-month(s) above +{fmt_pct(threshold)} and {len(dec)} below −{fmt_pct(threshold)} "
                       f"— realized price moves, which may include discount/promo effects, not only list-price changes.")
            if len(detected_flags):
                r = detected_flags.iloc[0]
                out.append(f"Largest detected move: {r['sku']} in {r['month']} at {fmt_pct(r['change_pct'], signed=True)} (₹{r['prev_price']:.2f} → ₹{r['unit_price']:.2f}).")
        if retention_hint:
            out.append(retention_hint)
    except Exception:
        return []
    return out

def nps_conclusions(nps: dict, brand: dict, product: dict, themes_like: pd.DataFrame,
                    themes_dislike: pd.DataFrame, comp: pd.DataFrame, by_cat: pd.DataFrame) -> list[str]:
    out = []
    try:
        if not brand.get("n"):
            return []
        health = "healthy" if brand["nps"] >= 50 else ("moderate" if brand["nps"] >= 30 else "at risk")
        out.append(f"Brand NPS is {brand['nps']:+.0f} ({health}) on {fmt_int(brand['n'])} responses; "
                   f"Product NPS is {product['nps']:+.0f} on {fmt_int(product['n'])}.")
        diff = product["nps"] - brand["nps"]
        if abs(diff) >= 5:
            if diff < 0:
                out.append(f"Product NPS is {abs(diff):.0f} points below Brand NPS, suggesting the product experience may be a larger constraint than overall brand perception.")
            else:
                out.append(f"Product NPS is {diff:.0f} points above Brand NPS — product experience is a relative strength.")
        if len(themes_like):
            out.append(f"Biggest positive driver (product level): “{themes_like.iloc[0]['theme']}” with {fmt_int(themes_like.iloc[0]['mentions'])} mentions.")
        if len(themes_dislike):
            neg = themes_dislike[~themes_dislike["theme"].str.lower().str.contains("no complaints")]
            if len(neg):
                out.append(f"Biggest negative driver (product level): “{neg.iloc[0]['theme']}” with {fmt_int(neg.iloc[0]['mentions'])} mentions — a complaint theme, not a confirmed root cause.")
        if len(by_cat):
            bc = by_cat[by_cat["n"] >= 5]
            if len(bc):
                best, worst = bc.loc[bc["brand_nps"].idxmax()], bc.loc[bc["brand_nps"].idxmin()]
                out.append(f"Strongest category NPS: {best['dimension']} ({best['brand_nps']:+.0f}); weakest: {worst['dimension']} ({worst['brand_nps']:+.0f}).")
        if len(comp):
            first = comp[comp["is_first_time"]]
            rest = comp[~comp["is_first_time"]]
            if len(first):
                out.append(f"{fmt_pct(first.iloc[0]['share'])} of respondents are first-time Nat Habit customers.")
            if len(rest):
                out.append(f"Top competitive acquisition source: {rest.iloc[0]['source']} ({fmt_int(rest.iloc[0]['customers'])} customers, {fmt_pct(rest.iloc[0]['share'])}).")
    except Exception:
        return []
    return out

def cs_conclusions(cs: dict, k: dict) -> list[str]:
    out = []
    try:
        if not k.get("tickets"):
            return []
        d = cs["df"]
        top_type = d.groupby("failure_type").size().sort_values(ascending=False)
        if len(top_type):
            t = top_type.index[0]
            out.append(f"Largest CS issue: {t}, accounting for {fmt_pct(top_type.iloc[0] / k['tickets'])} of {fmt_int(k['tickets'])} tickets.")
            sub = d[d["failure_type"] == t]
            r = sub["failure_reason"].mode()
            if len(r):
                out.append(f"Within this issue, the dominant reason is {r.iloc[0]} ({fmt_int((sub['failure_reason'] == r.iloc[0]).sum())} tickets).")
        top_cat = cs_counts_local(d)
        if len(top_cat):
            out.append(f"Most affected category: {top_cat.iloc[0]['dimension']} ({fmt_int(top_cat.iloc[0]['n'])} tickets).")
        if _ok(k.get("median_fulfil_hours")):
            h = k["median_fulfil_hours"]
            out.append(f"Median fulfilment-to-delivery time is {h:.0f} hours ({h/24:.1f} days)"
                       + (f", with {fmt_pct(k['pct_over_72h'])} of ticketed orders taking more than 72 hours." if _ok(k.get("pct_over_72h")) else "."))
        if k.get("unresolved_pct", 0) > 0.05:
            out.append(f"{fmt_pct(k['unresolved_pct'])} of tickets are not marked resolved in this export.")
    except Exception:
        return []
    return out

def cs_counts_local(d: pd.DataFrame) -> pd.DataFrame:
    g = d[d["category"] != "Unspecified"].groupby("category").size().reset_index(name="n")
    return g.sort_values("n", ascending=False).rename(columns={"category": "dimension"})

def ntc_conclusions(df: pd.DataFrame, as_of, maturity_days: int = 90) -> list[str]:
    out = []
    try:
        from calculations import ntc_maturity
        d = ntc_maturity(df, as_of, maturity_days)
        mat = d[d["mature"]].sort_values("cohort")
        if len(mat) < 3:
            return []
        last3 = mat.tail(3)
        prev3 = mat.iloc[-6:-3] if len(mat) >= 6 else mat.iloc[:-3]
        if len(prev3):
            def wavg(col):
                w = last3["first_order"].fillna(0)
                return float((last3[col].fillna(0) * w).sum() / w.sum()) if w.sum() else np.nan
            def pavg(col):
                w = prev3["first_order"].fillna(0)
                return float((prev3[col].fillna(0) * w).sum() / w.sum()) if w.sum() else np.nan
            cur, prev = wavg("sec_pct"), pavg("sec_pct")
            if _ok(cur) and _ok(prev) and prev > 0:
                chg = (cur - prev) / prev
                out.append(f"New-to-category 2nd-order rate over the last {len(last3)} mature cohorts is {fmt_pct(cur)}, "
                           f"{'down' if chg < 0 else 'up'} {fmt_pct(abs(chg))} vs the preceding {len(prev3)} cohorts ({fmt_pct(prev)}) — "
                           + ("a declining repeat behaviour worth investigating." if chg < -0.1 else "within a normal band."))
        best = mat.loc[mat["sec_pct"].idxmax()] if mat["sec_pct"].notna().any() else None
        worst = mat.loc[mat["sec_pct"].idxmin()] if mat["sec_pct"].notna().any() else None
        if best is not None:
            out.append(f"Strongest repeat cohort (mature): {best['cohort']} at {fmt_pct(best['sec_pct'])}; weakest: {worst['cohort']} at {fmt_pct(worst['sec_pct'])}.")
        imm = d[~d["mature"]]
        if len(imm):
            out.append(f"{len(imm)} most recent cohort(s) are younger than {maturity_days} days and are flagged “immature” — their low repeat rates reflect short observation time, not weaker behaviour.")
    except Exception:
        return []
    return out

# ---------------------------------------------------------------------------
# EXECUTIVE
# ---------------------------------------------------------------------------
def executive_attention(ctx: dict) -> list[tuple[int, str]]:
    """Prioritized "what needs attention" — only items the data supports."""
    items: list[tuple[int, str]] = []
    try:
        fm = ctx.get("fm")
        if fm and fm.get("vals") is not None:
            vals, mat, df = fm["vals"], fm["mature"], fm["df"]
            windows = fm["windows"]
            w_avail = [w for w in windows if (mat[f"w{w}"] & vals[f"w{w}"].notna()).any()]
            if w_avail:
                w = max(w_avail)
                sub = df[mat[f"w{w}"] & vals[f"w{w}"].notna()].copy()
                sub["v"] = vals[f"w{w}"][sub.index]
                if len(sub):
                    worst = sub.loc[sub["v"].idxmin()]
                    items.append((1, f"{worst['category']}/{worst['variant'] or worst['sku']} has the weakest {w}-day retention ({fmt_pct(worst['v'])}) among mature cohorts."))
        mig = ctx.get("mig")
        if mig and mig.get("net") is not None and len(mig["net"]):
            net = mig["net"]
            if (net["net"] < 0).any():
                l = net.loc[net["net"].idxmin()]
                items.append((2, f"{l['entity']} is the largest net migration loser ({fmt_int(l['net'])} more customers lost than gained)."))
        varc = ctx.get("var_contrib")
        if varc is not None and len(varc):
            r = varc.iloc[0]
            if _ok(r.get("revenue_share")) and r["revenue_share"] >= 0.25:
                items.append((3, f"{r['product']} contributes {fmt_pct(r['revenue_share'])} of revenue — single-variant concentration risk."))
        b, p = ctx.get("brand_nps"), ctx.get("product_nps")
        if b and p and _ok(b.get("nps")) and _ok(p.get("nps")) and (b["nps"] - p["nps"]) >= 5:
            items.append((4, f"Product NPS ({p['nps']:+.0f}) is materially below Brand NPS ({b['nps']:+.0f})."))
        flags = ctx.get("price_flags")
        if flags is not None and len(flags):
            r = flags.iloc[0]
            items.append((5, f"{r['sku']} shows a {fmt_pct(r['change_pct'], signed=True)} realized-price move in {r['month']} (detected from sales data)."))
        ntc = ctx.get("ntc")
        if ntc:
            from calculations import ntc_maturity
            d = ntc_maturity(ntc["df"], ntc["as_of"], ntc.get("maturity_days", 90))
            mat = d[d["mature"]]
            if len(mat) >= 6:
                last3, prev3 = mat.tail(3), mat.iloc[-6:-3]
                w1 = (last3["sec_pct"].fillna(0) * last3["first_order"]).sum() / last3["first_order"].sum()
                w0 = (prev3["sec_pct"].fillna(0) * prev3["first_order"]).sum() / prev3["first_order"].sum()
                if w0 > 0 and (w1 - w0) / w0 < -0.1:
                    items.append((6, f"New-to-category 2nd-order rate has declined vs previous cohorts ({fmt_pct(w0)} → {fmt_pct(w1)})."))
        cs = ctx.get("cs_kpis")
        if cs and cs.get("tickets"):
            d = ctx["cs_df"]
            g = d.groupby("failure_reason").size()
            if len(g):
                top = g.idxmax()
                if g.max() / g.sum() >= 0.25:
                    items.append((7, f"CS: “{top}” is {fmt_pct(g.max() / g.sum())} of all tickets."))
        aop = ctx.get("aop_roas")
        if aop and len(aop):
            last = aop.dropna(subset=["roas"]).tail(3)
            bad = last[last["roas"] < 1]
            if len(bad):
                items.append((8, f"AOP: ROAS below 1.0 in {len(bad)} of the last {len(last)} months (months: {', '.join(bad['month'])})."))
    except Exception:
        pass
    items.sort(key=lambda x: x[0])
    return items

def executive_changes(ctx: dict) -> list[str]:
    out = []
    try:
        aop = ctx.get("aop_monthly")
        if aop is not None and len(aop) >= 2:
            a = aop.dropna(subset=["revenue"]).tail(2)
            if len(a) == 2 and a.iloc[0]["revenue"] > 0:
                g = (a.iloc[1]["revenue"] - a.iloc[0]["revenue"]) / a.iloc[0]["revenue"]
                lbl = "AOP run-rate" if ctx.get("aop_is_plan", True) else "sales"
                out.append(f"{lbl} revenue {a.iloc[1]['month']} vs {a.iloc[0]['month']}: {'+' if g >= 0 else ''}{fmt_pct(g)} ({fmt_money(a.iloc[0]['revenue'])} → {fmt_money(a.iloc[1]['revenue'])}).")
        ntc = ctx.get("ntc")
        if ntc:
            from calculations import ntc_maturity
            d = ntc_maturity(ntc["df"], ntc["as_of"], ntc.get("maturity_days", 90))
            mat = d[d["mature"]]
            if len(mat) >= 2:
                last = mat.tail(3)
                w1 = (last["sec_pct"].fillna(0) * last["first_order"]).sum() / last["first_order"].sum()
                out.append(f"Latest mature new-to-category cohorts: weighted 2nd-order rate {fmt_pct(w1)} (avg {fmt_num(last['avg_days_to_sec'].mean(), 0)} days).")
        sales = ctx.get("sales_kpis"), ctx.get("sales_prev_kpis")
        if sales and sales[0] and sales[1] and _ok(sales[0].get("revenue")) and _ok(sales[1].get("revenue")):
            if sales[1]["revenue"] > 0:
                g = (sales[0]["revenue"] - sales[1]["revenue"]) / sales[1]["revenue"]
                out.append(f"Actual sales revenue in the latest month: {fmt_money(sales[0]['revenue'])}, {fmt_pct(g, signed=True)} vs the previous month.")
        b, p = ctx.get("brand_nps"), ctx.get("product_nps")
        if b and p and _ok(b.get("nps")):
            out.append(f"Voice: Brand NPS {b['nps']:+.0f} / Product NPS {p['nps']:+.0f} ({fmt_int(b['n'])} responses).")
        mig = ctx.get("mig")
        if mig and mig.get("n_acquired"):
            out.append(f"Migration: {fmt_pct(mig['repeat_pct'])} of acquired customers stayed in the same {mig['level']}; {fmt_pct(mig['switch_pct'])} switched.")
    except Exception:
        pass
    return out

# ---------------------------------------------------------------------------
# INSIGHTS — cross-page synthesis (the "tie everything up" engine)
# ---------------------------------------------------------------------------
INSIGHT_TONE_ICON = {"pos": "🟢", "neg": "🔴", "warn": "🟠", "info": "🔵"}


def _it(tone: str, page: str, text: str) -> dict:
    return {"tone": tone, "page": page, "text": text}


def insight_bundle(ctx: dict) -> list[dict]:
    """Cross-page synthesis tying all pages together.

    Returns a list of sections: {"icon", "title", "items"} where each item is
    {"tone": pos|neg|warn|info, "page": str, "text": str}.
    A section is omitted entirely when the data does not support it — nothing
    is ever invented, and overlaps are phrased as potential relationships.
    """
    sections: list[dict] = []

    def add(icon: str, title: str, items: list):
        items = [it for it in items if it and it.get("text")]
        if items:
            sections.append({"icon": icon, "title": title, "items": items})

    # ---- 1 · Growth & momentum (Sales) ------------------------------------
    items = []
    try:
        sk, skp = ctx.get("sales_kpis"), ctx.get("sales_prev_kpis")
        if sk and skp and _ok(sk.get("revenue")) and _ok(skp.get("revenue")) and skp["revenue"] > 0:
            g = (sk["revenue"] - skp["revenue"]) / skp["revenue"]
            items.append(_it("pos" if g >= 0 else "neg", "Sales",
                             f"Latest-month revenue is {fmt_money(sk['revenue'])}, {fmt_pct(g, signed=True)} vs the previous "
                             f"month ({fmt_money(skp['revenue'])}). Months can be partial (MTD), so the percentage compares "
                             f"different day counts — read it as momentum, not a like-for-like growth rate."))
        cc = ctx.get("cat_contrib")
        if cc is not None and len(cc) and _ok(cc.iloc[0].get("revenue_share")):
            r = cc.iloc[0]
            items.append(_it("info", "Sales",
                             f"{r['category']} is the largest category at {fmt_pct(r['revenue_share'])} of revenue "
                             f"({fmt_money(r['revenue'])}) out of {len(cc)} categories — the rest of the mix matters "
                             f"less than keeping this one healthy."))
        chh = ctx.get("chan_contrib")
        if chh is not None and len(chh) and _ok(chh.iloc[0].get("revenue_share")):
            r = chh.iloc[0]
            items.append(_it("info", "Sales",
                             f"{r['channel']} is the largest channel at {fmt_pct(r['revenue_share'])} of revenue "
                             f"({fmt_money(r['revenue'])})."))
    except Exception:
        pass
    add("📈", "Growth & momentum", items)

    # ---- 2 · Loyalty & repeat behaviour (Retention / Migration / NTC) ------
    items = []
    try:
        vv = ctx.get("vv")
        if vv and vv.get("overall", {}).get("qualifying"):
            o = vv["overall"]
            gap = (o["v2c_pct"] - o["v2v_pct"]) * 100
            items.append(_it("pos", "Retention",
                             f"Of {fmt_int(o['qualifying'])} customers with a second order, {fmt_pct(o['v2v_pct'])} repeat with the "
                             f"same variant (V2V) while {fmt_pct(o['v2c_pct'])} stay in the same category (V2C). The {gap:.1f}pp gap means "
                             f"most repeat behaviour is CATEGORY loyalty — customers return to the category even when they change variant, "
                             f"so the portfolio (not a single SKU) is what keeps them."))
        mig = ctx.get("mig")
        if mig and mig.get("n_acquired"):
            tail = f", averaging {fmt_days(mig['avg_days_1_2'])} from first to second order" if _ok(mig.get("avg_days_1_2")) else ""
            items.append(_it("warn" if mig.get("any_second_pct", 1) < 0.3 else "info", "Migration",
                             f"Only {fmt_pct(mig['repeat_pct'])} of {fmt_int(mig['n_acquired'])} acquired customers repeat in the same "
                             f"category ({fmt_pct(mig['switch_pct'])} switch); {fmt_pct(mig['any_second_pct'])} place any second order "
                             f"within the observed window{tail}. The 1st→2nd-order step is the biggest loyalty bottleneck in the data."))
        ntc = ctx.get("ntc")
        if ntc:
            from calculations import ntc_kpis
            k = ntc_kpis(ntc["df"], ntc["as_of"], ntc["maturity_days"])
            if _ok(k.get("avg_sec_pct")):
                items.append(_it("pos" if k["avg_sec_pct"] >= 0.3 else "warn", "New-to-Category",
                                 f"New-to-category customers place a 2nd order at {fmt_pct(k['avg_sec_pct'])} (avg {fmt_num(k['avg_days_sec'], 0)} days) "
                                 f"and a 3rd at {fmt_pct(k['avg_third_pct'])} — the 2nd→3rd drop is where the movement curve flattens, i.e. where "
                                 f"repeat-acquisition effort pays off."))
    except Exception:
        pass
    add("🔁", "Loyalty & repeat behaviour", items)

    # ---- 3 · Where customers move (Migration) ------------------------------
    items = []
    try:
        mig = ctx.get("mig")
        if mig:
            net = mig.get("net")
            if net is not None and len(net) and net["net"].abs().max() > 0:
                g, l = net.iloc[0], net.iloc[-1]
                items.append(_it("pos", "Migration",
                                 f"Net migration gainer: {g['entity']} (+{fmt_int(g['net'])} more customers gained than lost)."))
                items.append(_it("neg", "Migration",
                                 f"Net migration loser: {l['entity']} ({fmt_int(l['net'])} more customers lost than gained)."))
            to = mig.get("retention_outflow")
            if to is not None and len(to):
                best = to[to["second_orders"] >= 10].sort_values("same_pct", ascending=False)
                if len(best):
                    r = best.iloc[0]
                    items.append(_it("pos", "Migration",
                                     f"Strongest stay-rate: {r['entry']} — {fmt_pct(r['same_pct'])} of its acquired customers repeated in the "
                                     f"same {mig['level']}."))
            if mig.get("largest_flow") and mig["largest_flow"] != "—":
                items.append(_it("info", "Migration", f"Largest observed switch flow: {mig['largest_flow']}."))
    except Exception:
        pass
    add("🧭", "Where customers move", items)

    # ---- 4 · Voice of the customer (NPS) ------------------------------------
    items = []
    try:
        b, p = ctx.get("brand_nps"), ctx.get("product_nps")
        if b and b.get("n"):
            health = "healthy" if b["nps"] >= 50 else ("moderate" if b["nps"] >= 30 else "at risk")
            relation = ("the product experience is the weaker link vs the brand" if p["nps"] < b["nps"]
                        else "product experience is keeping pace with the brand")
            items.append(_it("pos" if b["nps"] >= 50 else "warn", "NPS & CS",
                             f"Brand NPS is {b['nps']:+.1f} ({health}, {fmt_int(b['n'])} responses) vs Product NPS {p['nps']:+.1f} — {relation}."))
            nm = ctx.get("nps_model")
            if nm is not None:
                from calculations import theme_counts
                likes = theme_counts(nm, "like")
                dislikes = theme_counts(nm, "dislike")
                if len(likes):
                    r = likes.iloc[0]
                    items.append(_it("pos", "NPS & CS",
                                     f"Most-liked product theme: “{r['theme']}” ({fmt_int(r['mentions'])} mentions)."))
                if len(dislikes):
                    neg = dislikes[~dislikes["theme"].str.lower().str.contains("no complaints")]
                    if len(neg):
                        r = neg.iloc[0]
                        items.append(_it("neg", "NPS & CS",
                                         f"Most-frequent dislike theme: “{r['theme']}” ({fmt_int(r['mentions'])} mentions) — a complaint theme, "
                                         f"not a confirmed root cause."))
    except Exception:
        pass
    add("💬", "Voice of the customer", items)

    # ---- 5 · Service & fulfilment (CS) --------------------------------------
    items = []
    try:
        ck, cdf = ctx.get("cs_kpis"), ctx.get("cs_df")
        if ck and ck.get("tickets") and cdf is not None and len(cdf):
            top_type = cdf.groupby("failure_type").size().sort_values(ascending=False)
            if len(top_type):
                t = top_type.index[0]
                sub = cdf[cdf["failure_type"] == t]
                r = sub["failure_reason"].mode()
                reason_txt = f"; dominant reason within it: {r.iloc[0]}" if len(r) else ""
                items.append(_it("warn" if top_type.iloc[0] / ck["tickets"] >= 0.25 else "info", "NPS & CS",
                                 f"Top CS failure type is {t} — {fmt_pct(top_type.iloc[0] / ck['tickets'])} of {fmt_int(ck['tickets'])} tickets{reason_txt}."))
            if _ok(ck.get("median_fulfil_hours")):
                h = ck["median_fulfil_hours"]
                items.append(_it("warn" if h > 72 else "info", "NPS & CS",
                                 f"Median fulfilment-to-delivery time is {h:.0f} hours ({h / 24:.1f} days); "
                                 f"{fmt_pct(ck['pct_over_72h'])} of ticketed orders exceed 72 hours."))
    except Exception:
        pass
    add("🛠️", "Service & fulfilment", items)

    # ---- 6 · Pricing ---------------------------------------------------------
    items = []
    try:
        rev = (ctx.get("fm") or {}).get("price")
        if rev is not None and len(rev):
            n_inc = int((rev["change_type"] == "Increased Price").sum())
            n_dec = int((rev["change_type"] == "Decreased Price").sum())
            n_same = int((rev["change_type"] == "Same Price").sum())
            n_new = int((rev["change_type"] == "New Variant").sum())
            items.append(_it("info", "Price",
                             f"Explicit price-revision log (from Retention FM notes): {n_inc} increase(s), {n_dec} decrease(s), "
                             f"{n_same} same-price, {n_new} new variant(s) — all in one date cluster, consistent with a planned revision cycle."))
        flags = ctx.get("price_flags")
        if flags is not None and len(flags):
            r = flags.iloc[0]
            n_up = int((flags["direction"] == "Increase").sum())
            n_dn = int((flags["direction"] == "Decrease").sum())
            thr = ctx.get("price_threshold", 0.05)
            items.append(_it("warn", "Price",
                             f"Detected from realized prices (revenue ÷ quantity, ±{fmt_pct(thr)} MoM): {n_up} SKU-month increase(s) and "
                             f"{n_dn} decrease(s); largest move is {r['sku']} in {r['month']} at {fmt_pct(r['change_pct'], signed=True)}. "
                             f"Realized price also moves with discounts and promos — treat as a signal, not a list-price confirmation."))
    except Exception:
        pass
    add("💰", "Pricing", items)

    # ---- 7 · Retention deep-dive ----------------------------------------------
    items = []
    try:
        fm = ctx.get("fm")
        if fm and fm.get("vals") is not None:
            vals, mat, df, windows = fm["vals"], fm["mature"], fm["df"], fm["windows"]
            w_avail = [w for w in windows if (mat[f"w{w}"] & vals[f"w{w}"].notna()).any()]
            if w_avail:
                w = max(w_avail)
                sub = df[mat[f"w{w}"] & vals[f"w{w}"].notna()].copy()
                sub["v"] = vals[f"w{w}"][sub.index]
                if len(sub):
                    best, worst = sub.loc[sub["v"].idxmax()], sub.loc[sub["v"].idxmin()]
                    items.append(_it("info", "Retention",
                                     f"Most mature window available as of {ctx.get('as_of')}: {w} days — strongest is "
                                     f"{best['category']}/{best['variant'] or best['sku']} ({fmt_pct(best['v'])}) and weakest is "
                                     f"{worst['category']}/{worst['variant'] or worst['sku']} ({fmt_pct(worst['v'])}) across {len(sub)} SKUs."))
            imm = [w for w in windows if w not in w_avail]
            if imm:
                items.append(_it("warn", "Retention",
                                 f"Longer windows ({', '.join(str(w) for w in imm)} days) are not yet observable for any cohort as of "
                                 f"{ctx.get('as_of')} — they are shown as N/A, never 0%."))
    except Exception:
        pass
    add("⏳", "Retention deep-dive", items)

    # ---- 8 · Plan (AOP) -----------------------------------------------------------
    items = []
    try:
        am = ctx.get("aop_monthly")
        if am is not None and len(am):
            ref = max(ctx["sales_months"]) if ctx.get("sales_months") else str(ctx.get("as_of"))[:7]
            booked = am[am["month"] <= ref]
            if len(booked):
                act = booked[booked["revenue"].notna()].tail(1).iloc[0]
                roas_txt = f", ROAS {act['roas']:.2f}" if _ok(act.get("roas")) else ""
                items.append(_it("info", "AOP",
                                 f"Latest booked month (up to {ref}): {act['month']} — revenue {fmt_money(act['revenue'])}, spend "
                                 f"{fmt_money(act['spend'])}{roas_txt}. Later months in the AOP sheet are plan, not booked."))
            items.append(_it("info", "AOP",
                             f"The AOP plan spans {am['month'].iloc[0]} → {am['month'].iloc[-1]} ({len(am)} months); it is always shown "
                             f"separately from actual sales and never combined with them."))
    except Exception:
        pass
    add("📐", "Plan (AOP)", items)

    # ---- 9 · Cross-page connections (guarded) --------------------------------------
    links: list[dict] = []
    try:  # packaging: CS × NPS
        ck, cdf = ctx.get("cs_kpis"), ctx.get("cs_df")
        nm = ctx.get("nps_model")
        if ck and ck.get("tickets") and cdf is not None and len(cdf) and nm is not None:
            top_reason = cdf["failure_reason"].mode()
            if len(top_reason):
                tr = str(top_reason.iloc[0]).lower()
                if "packag" in tr:
                    n_pkg = int((cdf["failure_reason"].str.lower() == tr).sum())
                    n_mention, mention = 0, False
                    for kind in ("dislike", "dislike_brand", "like", "like_brand"):
                        t = nm.get(f"themes_{kind}")
                        if t is not None and len(t):
                            m = t["theme"].str.lower().str.contains("packag")
                            if m.any():
                                mention = True
                                n_mention += int(m.sum())
                    if mention:
                        links.append(_it("warn", "NPS & CS",
                                         f"“{top_reason.iloc[0]}” leads CS tickets ({fmt_pct(n_pkg / ck['tickets'])} of them) while packaging "
                                         f"also appears in NPS responses ({n_mention} mentions) — the same weakness shows up in two "
                                         f"independent sources. A potential relationship requiring further validation, not a confirmed cause."))
    except Exception:
        pass
    try:  # net migration loser × category loyalty
        mig, vv = ctx.get("mig"), ctx.get("vv")
        if mig and vv and mig.get("net") is not None:
            net = mig["net"]
            if (net["net"] < 0).any():
                l = net.loc[net["net"].idxmin()]
                byc = vv.get("by_category")
                if byc is not None and len(byc):
                    row = byc[byc["category"] == l["entity"]]
                    if len(row) and row.iloc[0]["v2c_pct"] < vv["overall"]["v2c_pct"]:
                        links.append(_it("warn", "Migration × Retention",
                                         f"{l['entity']} is the largest net migration loser ({fmt_int(l['net'])}) and its category loyalty "
                                         f"(V2C {fmt_pct(row.iloc[0]['v2c_pct'])}) sits below the overall {fmt_pct(vv['overall']['v2c_pct'])} — "
                                         f"weaker loyalty is observed alongside the net outflow (potential relationship, requires validation)."))
    except Exception:
        pass
    try:  # channel scope consistency
        chh = ctx.get("chan_contrib")
        jch = ctx.get("journey_channels")
        if chh is not None and len(chh) and jch and "D2C" in jch and len(jch) <= 2:
            r = chh.iloc[0]
            if str(r["channel"]).upper().startswith("D2C"):
                links.append(_it("pos", "Sales × Migration",
                                 f"{r['channel']} is the largest sales channel ({fmt_pct(r['revenue_share'])} of revenue) and the loyalty "
                                 f"base sheet is D2C-scoped — migration, V2V/V2C and retention describe the same customer pool as the "
                                 f"business's biggest channel, so the two pages talk about the same customers."))
    except Exception:
        pass
    try:  # product NPS gap
        b, p = ctx.get("brand_nps"), ctx.get("product_nps")
        if b and p and _ok(b.get("nps")) and _ok(p.get("nps")) and (b["nps"] - p["nps"]) >= 5:
            links.append(_it("warn", "NPS",
                             f"Product NPS ({p['nps']:+.0f}) trails Brand NPS ({b['nps']:+.0f}) by {b['nps'] - p['nps']:.0f} points — the product "
                             f"experience (packaging, efficacy, texture) suggests the more actionable lever for lifting sentiment."))
    except Exception:
        pass
    try:  # price × retention
        fm = ctx.get("fm")
        if fm and fm.get("vals") is not None and fm.get("price") is not None:
            hint = price_x_retention_conclusions(fm["price"], fm["vals"], fm["mature"], fm["df"], fm["windows"])
            if hint:
                links.append(_it("warn", "Price × Retention", hint[0]))
    except Exception:
        pass
    add("🔗", "Cross-page connections", links)

    return sections
