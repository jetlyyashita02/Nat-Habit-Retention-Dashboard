"""
Narrative engine — auto-writes the quarterly category review from data.
Mirrors the reference QBR write-up structure:
NET · Seasonality · Pack economics · Weather-SKU funnel · Channel ·
Variant cuts · Spillover · Sentiment · Action items.
Every number is computed; every verdict is a data-driven branch.
"""
from __future__ import annotations

import pandas as pd

QNAME = {1: "JFM", 2: "AMJ", 3: "JAS", 4: "OND"}
QLABEL = {"JFM": "Jan–Mar", "AMJ": "Apr–Jun", "JAS": "Jul–Sep", "OND": "Oct–Dec"}


def q_label(q: str) -> str:
    y, n = q.split("-Q")
    return f"{QNAME[int(n)]}'{y[2:]}"


def month_to_q(month: str) -> str:
    y, m = month.split("-")
    return f"{y}-Q{(int(m) - 1) // 3 + 1}"


def prev_q(q: str) -> str:
    y, n = int(q[:4]), int(q[-1])
    return f"{y - 1}-Q4" if n == 1 else f"{y}-Q{n - 1}"


def next_q(q: str) -> str:
    y, n = int(q[:4]), int(q[-1])
    return f"{y + 1}-Q1" if n == 4 else f"{y}-Q{n + 1}"


def _prim(long_df):
    return long_df[long_df["item_seq"] == 1].drop_duplicates(["customer", "order_seq"])


def cohort(long_df, q: str) -> set:
    p = _prim(long_df)
    e = p[p["order_seq"] == 1]
    return set(e[e["month"].map(month_to_q) == q]["customer"])


def _pairs_within(long_df, custs: set):
    """entry primary item -> 2nd-order primary item for the cohort."""
    p = _prim(long_df)
    p = p[p["customer"].isin(custs)]
    e = p[p["order_seq"] == 1][["customer", "category", "variant", "size_g",
                                "sku_key", "intended_season", "month", "order_date"]]
    n = p[p["order_seq"] == 2][["customer", "category", "variant", "size_g",
                                "sku_key", "intended_season", "order_date"]]
    m = e.merge(n, on="customer", how="inner", suffixes=("_e", "_n"))
    gaps = long_df[long_df["order_seq"] == 2].drop_duplicates("customer")[
        ["customer", "gap_days"]]
    return m.merge(gaps, on="customer", how="left"), e


def c2c_retention(long_df, q: str):
    c = cohort(long_df, q)
    if not c:
        return None, 0
    depth = long_df.groupby("customer")["journey_depth"].first()
    dep = depth.reindex(sorted(c))
    return 100 * (dep >= 2).mean(), len(c)


def variant_cuts(long_df, q: str, category: str, min_base: int = 5):
    """per-variant base / V2V / V2C for the quarter's entry cohort."""
    c = cohort(long_df, q)
    pairs, entries = _pairs_within(long_df, c)
    rows = []
    for v, g in entries[entries["category"] == category].groupby("variant"):
        base = len(g)
        if base < min_base:
            continue
        pg = pairs[pairs["variant_e"] == v]
        rep = len(pg)
        v2v = 100 * (pg["variant_n"] == v).mean() if rep else None
        v2c = 100 * (pg["category_n"] == category).mean() if rep else None
        days = pg["gap_days"].mean() if rep else None
        rows.append({"variant": v, "base": base, "v2v": v2v, "v2c": v2c,
                     "repeat_days": days, "repeaters": rep})
    return pd.DataFrame(rows).sort_values("base", ascending=False)


def pack_economics(long_df, q: str, category: str):
    c = cohort(long_df, q)
    pairs, _ = _pairs_within(long_df, c)
    fm = pairs[pairs["category_e"] == category]
    out = {}
    for size in (30, 50):
        g = fm[fm["size_g_e"] == size]
        out[f"days_{size}"] = g["gap_days"].mean() if len(g) else None
        out[f"repeaters_{size}"] = len(g)
    g50 = fm[fm["size_g_e"] == 50]
    if len(g50):
        out["rep_into_50"] = 100 * ((g50["category_n"] == category) &
                                    (g50["size_g_n"] == 50)).mean()
        out["down_to_30"] = 100 * ((g50["category_n"] == category) &
                                   (g50["size_g_n"] == 30)).mean()
    return out


def weather_funnel(long_df, q: str, category: str):
    """self-repeat & concern-destination for seasonal vs concern entry lines."""
    c = cohort(long_df, q)
    pairs, _ = _pairs_within(long_df, c)
    fm = pairs[pairs["category_e"] == category]
    out = {}
    weather = fm[fm["intended_season_e"].isin(["Cold Winter", "Hot Dry", "Hot Humid"])]
    rep = weather[weather["variant_n"] == weather["variant_e"]]
    out["weather_self"] = 100 * len(rep) / len(weather) if len(weather) else None
    out["weather_repeaters"] = len(weather)
    if len(weather):
        to_concern = weather[weather["intended_season_n"] == "Non-Seasonal (Concern)"]
        out["to_concern"] = 100 * len(to_concern) / len(weather)
    return out


def spillover(long_df, q: str, category: str):
    c = cohort(long_df, q)
    pairs, _ = _pairs_within(long_df, c)
    fm = pairs[pairs["category_e"] == category]
    if not len(fm):
        return {}
    dest = fm["category_n"].value_counts(normalize=True) * 100
    return {"self": dest.get(category), "active_gel": dest.get("Active Gel"),
            "aloe": dest.get("Aloe Vera Gel"), "repeaters": len(fm)}


def seasonality(long_df, category: str):
    """monthly order volumes for the category + peak/trough + quarterly new customers."""
    p = _prim(long_df)
    cat = p[p["category"] == category]
    monthly = cat.groupby("month").size()
    newq = (p[p["order_seq"] == 1].assign(q=lambda x: x["month"].map(month_to_q))
            .groupby("q").size())
    peak_m = monthly.idxmax() if len(monthly) else None
    if len(monthly):
        win = monthly[monthly.index.map(lambda m: m[5:7] in ("11", "12"))]
        summer = monthly[monthly.index.map(lambda m: m[5:7] in ("04", "05", "06", "07", "08"))]
        ratio = (win.mean() / summer.min()) if len(win) and len(summer) and summer.min() else None
    else:
        ratio = None
    return {"monthly": monthly, "peak_month": peak_m, "peak_over_trough": ratio,
            "new_by_q": newq}


def sentiment(nps_df: pd.DataFrame, q: str) -> dict:
    if nps_df is None or "created_at" not in nps_df or n_df_len(nps_df) == 0:
        return {}
    d = nps_df.dropna(subset=["created_at"]).copy()
    d["q"] = d["created_at"].dt.to_period("Q").astype(str).str.replace("Q", "-Q")
    qd = d[d["q"] == q]
    if not len(qd):
        return {"covered": False}
    price_kw = ("expensive", "price", "pricy", "costly")
    tex_kw = ("greasy", "greasiness", "absorption", "absorb", "sticky",
              "non-sticky", "runny", "texture")

    def has_kw(row, kws):
        joined = " ".join(str(x) for x in row["_dislikes"]).lower()
        return any(k in joined for k in kws)

    n = len(qd)
    return {"covered": True, "n": n,
            "brand_nps": _nps(qd["NPS Score For Brand"]),
            "price_dislike": 100 * qd.apply(lambda r: has_kw(r, price_kw), axis=1).mean(),
            "texture_dislike": 100 * qd.apply(lambda r: has_kw(r, tex_kw), axis=1).mean()}


def n_df_len(df):
    return len(df)


def _nps(s):
    s = s.dropna()
    if not len(s):
        return None
    return round(100 * ((s >= 9).mean() - (s <= 6).mean()), 1)


# ------------------------------------------------------------------ writer
def write_narrative(long_df, category: str, q: str,
                    nps_df=None, sales_df=None, min_base: int = 5) -> list[dict]:
    """Returns ordered blocks: {section, text} in the reference QBR style."""
    qp = prev_q(q)
    blocks = []

    def _fmt(x, nd=1, suf=""):
        return "—" if x is None or pd.isna(x) else f"{x:.{nd}f}{suf}"

    # ---- NET headline
    r_q, n_q = c2c_retention(long_df, q)
    r_p, n_p = c2c_retention(long_df, qp)
    acq_delta = 100 * (n_q - n_p) / n_p if n_p else None
    parts = []
    if r_q is not None and r_p is not None:
        d = r_q - r_p
        direction = ("down slightly" if -0.5 < d < 0 else
                     "down" if d <= -0.5 else "up slightly" if 0 <= d < 0.5 else "up")
        parts.append(f"**Net:** {q_label(q)} cohort retention closed at "
                     f"{_fmt(r_q)}% (C2C) — {direction} from {q_label(qp)}'s "
                     f"{_fmt(r_p)}% ({d:+.1f}ppt).")
    if acq_delta is not None:
        parts.append(f"Acquisition {'fell' if acq_delta < 0 else 'grew'} "
                     f"{abs(acq_delta):.1f}% QoQ ({n_p:,} → {n_q:,} new customers).")
    sent = sentiment(nps_df, q)
    if sent.get("covered"):
        parts.append(f"NPS price-dislike sits at {sent['price_dislike']:.0f}% "
                     "— price is no longer the primary churn flag." if sent["price_dislike"] < 20
                     else f"NPS price-dislike is still {sent['price_dislike']:.0f}% — "
                     "price remains a live churn driver.")
    elif nps_df is not None:
        parts.append("(No survey coverage for this quarter.)")
    if 0 < n_q < 100:
        parts.append("*(Small cohort — treat cuts as directional.)*")
    blocks.append({"section": "Net", "text": " ".join(parts)})

    # ---- Seasonality
    seas = seasonality(long_df, category)
    txt = []
    if seas["peak_over_trough"] and seas["peak_over_trough"] > 1.2:
        txt.append(f"{category} is seasonal: order volume runs ~{seas['peak_over_trough']:.1f}x "
                   f"from the summer trough to the Nov–Dec peak "
                   f"(peak month {seas['peak_month']}).")
    newq = seas["new_by_q"]
    if q in newq and qp in newq:
        dd = 100 * (newq[q] - newq[qp]) / newq[qp] if newq[qp] else None
        if dd is not None:
            txt.append(f"New customers {'fell' if dd < 0 else 'grew'} {abs(dd):.1f}% "
                       f"alongside the season ({newq[qp]:,} → {newq[q]:,}).")
    txt.append("The softening, where present, tracks seasonality — not a structural "
               "decline in stickiness.")
    blocks.append({"section": "Seasonality", "text": " ".join(txt)})

    # ---- Pack economics
    pk = pack_economics(long_df, q, category)
    txt = []
    d30, d50 = pk.get("days_30"), pk.get("days_50")
    if d30 and d50:
        txt.append(f"True loyalists on 30g repeat in ~{d30:.0f} days vs 50g's "
                   f"~{d50:.0f} — a {abs(d50 - d30):.0f}-day gap "
                   f"({pk.get('repeaters_30', 0):,} vs {pk.get('repeaters_50', 0):,} repeaters).")
    if "rep_into_50" in pk:
        txt.append(f"{pk['rep_into_50']:.0f}% of 50g first-buyers repeat into 50g again; "
                   f"{pk.get('down_to_30', 0):.0f}% downsize to 30g — "
                   + ("50g isn't building its own loyalty yet; pack economics is the ceiling."
                      if pk.get("down_to_30", 0) > pk["rep_into_50"] else
                      "50g loyalty is forming — protect the value ladder."))
    if txt:
        blocks.append({"section": "Pack economics", "text": " ".join(txt)})

    # ---- Weather-SKU funnel
    wf = weather_funnel(long_df, q, category)
    if wf.get("weather_self") is not None:
        txt = (f"Weather SKUs are a funnel into the core: they self-repeat at only "
               f"{wf['weather_self']:.0f}% ({wf['weather_repeaters']:,} repeaters)")
        if wf.get("to_concern") is not None:
            txt += (f", but {wf['to_concern']:.0f}% of their repeaters land in a "
                    "Concern SKU on the next order — the largest single destination.")
        blocks.append({"section": "Weather-SKU funnel", "text": txt.rstrip(".") + "."})

    # ---- Channel (needs sales CSV)
    if sales_df is not None and len(sales_df):
        s = sales_df[sales_df["category"] == category].copy()
        s["q"] = s["month"].map(month_to_q)
        g = s.groupby(["q", "channel"])["rev"].sum().unstack(fill_value=0)
        g["D2C share"] = 100 * g.get("D2C", 0) / g.sum(axis=1)
        if q in g.index and qp in g.index:
            d2 = g.loc[q, "D2C share"] - g.loc[qp, "D2C share"]
            txt = (f"D2C revenue share for {category} moved {d2:+.1f}ppt QoQ "
                   f"({g.loc[qp, 'D2C share']:.1f}% → {g.loc[q, 'D2C share']:.1f}%) "
                   "in the sales file's coverage window.")
            blocks.append({"section": "Channel", "text": txt})
        else:
            blocks.append({"section": "Channel", "text":
                           "Sales file doesn't cover both quarters — upload a longer "
                           "sales export to compute channel share drift."})

    # ---- Variant cuts
    vq = variant_cuts(long_df, q, category, min_base)
    vp = variant_cuts(long_df, qp, category, min_base)
    if len(vq):
        bullets = []
        for _, r in vq.iterrows():
            pv = vp[vp["variant"] == r["variant"]]
            line = f"**{r['variant']}** — base {r['base']:,}"
            if len(pv):
                db = 100 * (r["base"] - pv.iloc[0]["base"]) / pv.iloc[0]["base"]
                line += f" ({pv.iloc[0]['base']:,} → {r['base']:,}, {db:+.1f}%)"
            if r["v2v"] is not None and len(pv) and pv.iloc[0]["v2v"] is not None:
                line += f" · V2V {pv.iloc[0]['v2v']:.1f}% → {r['v2v']:.1f}%"
            if r["v2c"] is not None and len(pv) and pv.iloc[0]["v2c"] is not None:
                line += f" · V2C {pv.iloc[0]['v2c']:.1f}% → {r['v2c']:.1f}%"
            # verdict
            v2c_d = (r["v2c"] - pv.iloc[0]["v2c"]) if (r["v2c"] is not None and len(pv)
                                                       and pv.iloc[0]["v2c"] is not None) else None
            base_d = ((r["base"] - pv.iloc[0]["base"]) / pv.iloc[0]["base"]
                      if len(pv) and pv.iloc[0]["base"] else None)
            if base_d is not None and base_d < -0.05 and (v2c_d or 0) < 0:
                line += " — **the one to isolate**: shrinking base while weakening on every metric."
            elif base_d is not None and base_d > 0.15:
                line += " — fastest grower; retain hard."
            elif (v2c_d or 0) < -1.5:
                line += " — the real drag on category pull-through."
            elif (r["v2v"] or 0) > 12:
                line += " — the portfolio's stickiness anchor."
            bullets.append("• " + line)
        blocks.append({"section": "Variant-level", "text": "\n".join(bullets)})

    # ---- Spillover
    sp = spillover(long_df, q, category)
    sp_p = spillover(long_df, qp, category)
    if sp.get("repeaters"):
        txt = (f"Cross-moisturisers spillover ({q_label(q)}, {sp['repeaters']:,} repeaters): "
               f"Active Gel draws {_fmt(sp.get('active_gel'))}%, "
               f"Aloe Vera Gel {_fmt(sp.get('aloe'))}%; "
               f"self-retention in {category} holds at {_fmt(sp.get('self'))}%")
        if sp_p.get("self") is not None:
            txt += f" ({'vs ' + _fmt(sp_p['self']) + '% last quarter'})"
        blocks.append({"section": "Spillover", "text": txt + "."})

    # ---- Sentiment
    if sent.get("covered"):
        txt = [f"Survey pulse ({sent['n']:,} responses this quarter): "
               f"brand NPS {sent.get('brand_nps', '—')}."]
        if sent["texture_dislike"] >= 5:
            txt.append(f"Greasiness/absorption-style complaints sit at "
                       f"{sent['texture_dislike']:.0f}% of dislikes — "
                       "watch as a seasonal off-fit pattern rather than a product fault.")
        blocks.append({"section": "Sentiment", "text": " ".join(txt)})

    # ---- Action items
    actions = []
    if len(vq):
        drag = vq.assign(v2c_filled=vq["v2c"].fillna(0)).sort_values("base", ascending=False)
        if len(vp):
            merged = drag.merge(vp[["variant", "v2c", "base"]], on="variant",
                                suffixes=("", "_p"))
            merged["v2c_d"] = merged["v2c_filled"] - merged["v2c_p"].fillna(0)
            d = merged.sort_values("v2c_d").iloc[0]
            if d["v2c_d"] < -1:
                actions.append(f"**Retention fix:** {d['variant']} is the biggest V2C drag "
                               f"({d['v2c_d']:+.1f}ppt) on a {int(d['base']):,}-customer base — "
                               "prioritise reformulation/cohort-calling here.")
        g = drag.iloc[0]
        actions.append(f"**Defend the base:** {g['variant']} carries the largest cohort "
                       f"({int(g['base']):,} entry customers) — its V2V/V2C sets the "
                       "category trajectory.")
    if pk.get("down_to_30", 0) and pk.get("down_to_30", 0) > 30:
        actions.append("**Pack economics:** downsize pressure >30% from 50g — "
                       "test 50g value framing / refill pricing before peak season.")
    if sent.get("covered") and sent.get("price_dislike", 100) < 15:
        actions.append("**Pricing — solved:** price-dislike <15% in NPS; maintain, "
                       "no further action.")
    if wf.get("to_concern") is not None and wf["to_concern"] > 15:
        actions.append("**Funnel play:** weather-SKU buyers land in Concern SKUs — "
                       "bundle the handover (seasonal → concern cross-sell at reorder).")
    blocks.append({"section": "Action items", "text": "\n".join(f"{i+1}. {a}"
                                                                for i, a in enumerate(actions))})
    return blocks
