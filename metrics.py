"""
Metrics layer — implements every field from the Summary Sheet + dashboard mockup.

All functions take the LONG table from etl.py:
  one row per (customer, order_seq, item) with category / variant / size /
  intended_season / timing_season / gap_days / journey_depth.
"""

from __future__ import annotations

import pandas as pd

from etl import TIMING_SEASON_ORDER

SEASON_MATCH = {
    "Cold Winter (Dec-Feb)": "Cold Winter",
    "Hot Dry (Mar-May)": "Hot Dry",
    "Hot Humid (Jun-Sep)": "Hot Humid",
    "Post-Monsoon (Oct-Nov)": None,   # no variant is 'intended' for post-monsoon
}
INTENDED_TO_TIMING = {"Cold Winter": "Cold Winter (Dec-Feb)",
                      "Hot Dry": "Hot Dry (Mar-May)",
                      "Hot Humid": "Hot Humid (Jun-Sep)",
                      "Non-Seasonal (Concern)": None,
                      "Gel": None}


# ----------------------------------------------------------------------------
# Cohort filter (entry-order semantics, like the Summary Sheet analyses)
# ----------------------------------------------------------------------------
def filter_cohort(long_df: pd.DataFrame, *, category: str | None = None,
                  sku_key: str | None = None, from_month: str | None = None,
                  to_month: str | None = None, depths: list[int] | None = None,
                  regions: list[str] | None = None, cities: list[str] | None = None):
    """Return (filtered_long_df, cohort_customer_ids).

    Category / Variant / month filters apply to the customer's FIRST order
    (entry purchase). Journey Depth = customer's total orders. Geo applies to
    the customer's city.
    """
    df = long_df
    if df.empty:
        return df, set()

    entry = df[df["order_seq"] == 1]
    keep = None

    def _and(s: set):
        nonlocal keep
        keep = s if keep is None else (keep & s)

    if category:
        _and(set(entry.loc[entry["category"].eq(category), "customer"]))
    if sku_key:
        _and(set(entry.loc[entry["sku_key"].eq(sku_key), "customer"]))

    per_cust = entry.drop_duplicates("customer").set_index("customer")
    m = pd.Series(True, index=per_cust.index)
    if from_month:
        m &= per_cust["month"] >= from_month
    if to_month:
        m &= per_cust["month"] <= to_month
    if regions:
        m &= per_cust["region"].isin(regions)
    if cities:
        m &= per_cust["city"].isin(cities)
    _and(set(m[m].index))

    cohort = keep if keep is not None else set(entry["customer"])

    if depths:
        depth = df.groupby("customer")["journey_depth"].first()
        cohort = {c for c in cohort if depth.get(c) in depths}

    d = df[df["customer"].isin(cohort)]
    return d, cohort


# ----------------------------------------------------------------------------
# Dashboard tiles
# ----------------------------------------------------------------------------
def seasonality_tiles(long_df: pd.DataFrame) -> dict:
    """Orders by the variant's INTENDED season bucket (dashboard mockup tiles)."""
    orders = long_df.drop_duplicates(["customer", "order_seq"])
    counts = {}
    for b in ["Cold Winter", "Hot Dry", "Hot Humid", "Non-Seasonal (Concern)"]:
        sel = long_df[long_df["intended_season"] == b]
        counts[b] = sel.drop_duplicates(["customer", "order_seq"]).shape[0]
    peak = max(counts, key=counts.get) if any(counts.values()) else "—"
    return {**counts, "Peak Season": peak,
            "Peak Orders": counts.get(peak, 0) if peak != "—" else 0}


def timing_seasonality(long_df: pd.DataFrame) -> pd.Series:
    """Orders by calendar month of purchase (Summary Sheet table 1 style)."""
    orders = long_df.drop_duplicates(["customer", "order_seq"])
    s = orders["timing_season"].value_counts().reindex(TIMING_SEASON_ORDER).fillna(0).astype(int)
    return s


def gels_totals(long_df: pd.DataFrame) -> dict:
    orders = long_df.drop_duplicates(["customer", "order_seq"])
    def order_count(cat):
        sel = long_df[long_df["category"] == cat]
        return sel.drop_duplicates(["customer", "order_seq"]).shape[0]
    return {
        "Active Gel Count": order_count("Active Gel"),
        "Aloevera Gel Count": order_count("Aloe Vera Gel"),
        "Total Orders": orders.shape[0],
        "Customers": long_df["customer"].nunique(),
        "Repeat Buyers": orders.groupby("customer").size().ge(2).sum(),
    }


# ----------------------------------------------------------------------------
# Loyalty — V2V (variant → same variant) and V2C (variant → same category)
# ----------------------------------------------------------------------------
def loyalty_metrics(long_df: pd.DataFrame, sku_key: str | None = None) -> dict:
    """First → second purchase loyalty for the cohort.

    V2V: 2nd order contains the same VARIANT as the 1st order.
    V2C: 2nd order stays in the same CATEGORY (any variant).
    When a specific sku_key is given, only customers whose ENTRY order contains
    that SKU are considered; V2V then means the same variant re-purchased.
    """
    out = {}
    d = long_df
    if sku_key:
        entry_has = d[(d["order_seq"] == 1) & (d["sku_key"] == sku_key)]["customer"]
        d = d[d["customer"].isin(set(entry_has))]

    firsts = d[d["order_seq"] == 1]
    first_cats = firsts.groupby("customer")["category"].agg(set)
    first_vars = firsts.groupby("customer")["variant"].agg(set)
    secs = d[d["order_seq"] == 2]
    secs = secs.assign(_fc=secs["customer"].map(first_cats),
                       _fv=secs["customer"].map(first_vars))
    repeat_custs = set(secs["customer"].unique()) & set(first_cats.index)

    v2v_ids, v2c_ids = set(), set()
    if len(secs):
        v2v_hit = [ (v in s) if isinstance(s, set) else False
                    for v, s in zip(secs["variant"], secs["_fv"]) ]
        v2c_hit = [ (c in s) if isinstance(s, set) else False
                    for c, s in zip(secs["category"], secs["_fc"]) ]
        v2v_ids = set(secs.loc[v2v_hit, "customer"])
        v2c_ids = set(secs.loc[v2c_hit, "customer"])

    n = len(repeat_custs)
    gap_map = secs.drop_duplicates("customer").set_index("customer")["gap_days"]
    gaps = gap_map.reindex(sorted(repeat_custs)) if n else pd.Series(dtype=float)
    depth_map = d.groupby("customer")["journey_depth"].first()

    def _agg(ids):
        if not ids:
            return dict(pct=0.0, avg_days=None, avg_orders=None, common=None)
        g = gap_map.reindex(sorted(ids))
        dep = depth_map.reindex(list(ids))
        items = d[(d["customer"].isin(ids)) & (d["order_seq"] == 2)]
        common = items["sku_key"].mode()
        return dict(pct=100 * len(ids) / n if n else 0.0,
                    avg_days=round(g.mean(), 1) if g.notna().any() else None,
                    avg_orders=round(dep.mean(), 2) if len(dep) else None,
                    common=common.iloc[0] if len(common) else None)

    v2v, v2c = _agg(v2v_ids), _agg(v2c_ids)
    return {
        "Repeat customers (2+ orders)": n,
        "V2V Loyalty %": round(v2v["pct"], 1),
        "V2C Loyalty %": round(v2c["pct"], 1),
        "Avg Purchase Days V2V": v2v["avg_days"],
        "Avg Purchase Days V2C": v2c["avg_days"],
        "Avg Order Count V2V": v2v["avg_orders"],
        "Avg Order Count V2C": v2c["avg_orders"],
        "Most Common 2nd Order V2V": v2v["common"],
        "Most Common 2nd Order V2C": v2c["common"],
        # overall journey stats for the cohort
        "Avg Gap (all repeats)": round(gaps.mean(), 1) if n and gaps.notna().any() else None,
        "Avg Journey Depth": round(depth_map.reindex(list(repeat_custs)).mean(), 2) if n else None,
        "_v2v_ids": v2v_ids, "_v2c_ids": v2c_ids,
    }


# ----------------------------------------------------------------------------
# Variant summary (Summary Sheet table 1 + order-frequency table 3)
# ----------------------------------------------------------------------------
def variant_summary(long_df: pd.DataFrame) -> pd.DataFrame:
    """Per variant: purchases by timing season, peak, avg gap, match, strength."""
    orders = long_df.drop_duplicates(["customer", "order_seq", "sku_key"])
    piv = orders.pivot_table(index="variant", columns="timing_season",
                             values="order_seq", aggfunc="count",
                             fill_value=0).reindex(columns=TIMING_SEASON_ORDER).fillna(0)
    rows = []
    for variant, r in piv.iterrows():
        sub = long_df[long_df["variant"] == variant]
        total = int(r.sum())
        peak = r.idxmax() if total else "—"
        intended = sub["intended_season"].iloc[0] if len(sub) else "—"
        intended_timing = INTENDED_TO_TIMING.get(intended)
        match = ("—" if intended_timing is None
                 else ("Matches" if peak == intended_timing else "No Match"))
        share = (r.max() / total) if total else 0
        if match == "—":
            strength = "—" if intended == "Gel" else "Evergreen"
        elif share >= 0.40:
            strength = "Highly Seasonal"
        elif share >= 0.30:
            strength = "Moderately Seasonal"
        else:
            strength = "Evergreen"
        gaps = sub.drop_duplicates(["customer", "order_seq"])["gap_days"].dropna()
        rows.append({
            "Variant": variant, **{c: int(r[c]) for c in TIMING_SEASON_ORDER},
            "Total Orders": total, "Peak Season": peak, "Peak Share %": round(100 * share, 1),
            "Avg Purchase Gap Days": round(gaps.mean(), 1) if len(gaps) else None,
            "Intended Season": intended, "Season Match?": match,
            "Seasonality Strength": strength,
        })
    out = pd.DataFrame(rows).sort_values("Total Orders", ascending=False)
    return out


def order_frequency(long_df: pd.DataFrame) -> pd.DataFrame:
    """Per variant entry cohort: once / twice / mid / high loyal + reorder speed."""
    entry_items = long_df[long_df["order_seq"] == 1]
    depth = long_df.groupby("customer")["journey_depth"].first()
    gaps = long_df.drop_duplicates(["customer", "order_seq"]).pivot(
        index="customer", columns="order_seq", values="gap_days")
    rows = []
    for variant, grp in entry_items.groupby("variant"):
        custs = grp["customer"].unique()
        dep = depth.reindex(custs).dropna().astype(int)
        n = len(dep)
        g12 = gaps.reindex(custs)[2].dropna() if 2 in gaps.columns else pd.Series(dtype=float)
        g23 = gaps.reindex(gaps.reindex(custs).index)[3].dropna() if 3 in gaps.columns else pd.Series(dtype=float)
        allg = long_df[long_df["customer"].isin(custs)]["gap_days"].dropna()
        once = int((dep == 1).sum()); twice = int((dep == 2).sum())
        mid = int(dep.between(3, 4).sum()); high = int(dep.ge(5).sum())
        rows.append({
            "Category": grp["category"].iloc[0], "Variant": variant,
            "Unique Entry Users": n, "Bought Once Only": once, "Bought Twice": twice,
            "Mid Loyal (3-4)": mid, "High Loyal (5+)": high,
            "Drop-Off %": round(100 * once / n, 1) if n else None,
            "Repeat Rate %": round(100 - 100 * once / n, 1) if n else None,
            "Avg Days 1→2": round(g12.mean(), 0) if len(g12) else None,
            "Avg Days 2→3": round(g23.mean(), 0) if len(g23) else None,
            "Overall Avg Gap": round(allg.mean(), 0) if len(allg) else None,
        })
    return pd.DataFrame(rows).sort_values("Unique Entry Users", ascending=False)


# ----------------------------------------------------------------------------
# Formula-driven conclusions (mirrors the workbook's conclusion blocks)
# ----------------------------------------------------------------------------
def _entry_next(long_df):
    """Entry primary item → next-order primary item pairs (1 per customer)."""
    d = long_df
    firsts = d[(d["order_seq"] == 1) & (d["item_seq"] == 1)][
        ["customer", "category", "variant", "size_g", "sku_key"]].rename(
        columns={"category": "ecat", "variant": "evar",
                 "size_g": "esize", "sku_key": "esku"})
    seconds = d[(d["order_seq"] == 2) & (d["item_seq"] == 1)][
        ["customer", "category", "variant", "size_g", "sku_key"]].rename(
        columns={"category": "ncat", "variant": "nvar",
                 "size_g": "nsize", "sku_key": "nsku"})
    return firsts.merge(seconds, on="customer", how="inner")


def conclusions(long_df: pd.DataFrame) -> list[dict]:
    """Business conclusion blocks — every number computed, every verdict
    branch driven by the data (never hardcoded)."""
    out = []
    en = _entry_next(long_df)

    # 1 — Is Face Malai Seasonal? (primary-item per order, same as the workbook)
    prim = (long_df[long_df["item_seq"] == 1]
            .drop_duplicates(["customer", "order_seq"]))
    piv = prim.pivot_table(index="variant", columns="timing_bucket",
                           values="order_seq", aggfunc="count", fill_value=0)
    intent_map = prim.groupby("variant")["intended_season"].first()
    n_high = n_ever = 0
    for v, row in piv.iterrows():
        tot = row.sum()
        if tot == 0:
            continue
        it = intent_map[v]
        if it == "Gel":
            continue
        if it == "Non-Seasonal (Concern)":
            n_ever += 1          # concern variants classify as Evergreen
            continue
        share = row.max() / tot
        if share >= 0.40:
            n_high += 1
        elif share < 0.30:
            n_ever += 1
    n_fm = int(sum(1 for v in piv.index if intent_map[v] != "Gel"))
    if n_high == 0 and n_ever > 0:
        ans = f"NO — Mostly evergreen with {n_ever} evergreen variants"
    elif n_high >= n_ever and n_high > 0:
        ans = f"YES — {n_high} of {n_fm} Face Malai variants are highly seasonal"
    else:
        ans = (f"MIXED — {n_high} highly seasonal vs {n_ever} evergreen variants; "
               f"seasonality is variant-led, not category-led")
    out.append({"q": "Is Face Malai Seasonal?", "a": ans})

    # 2 — Overall Repeat Behaviour
    tot = len(en)
    rep = int((en["esku"] == en["nsku"]).sum()) if tot else 0
    pct = 100 * rep / tot if tot else 0
    verdict = "STRONG" if pct >= 60 else ("MODERATE" if pct >= 45 else "WEAK")
    out.append({"q": "Overall Repeat Behaviour", "a": (
        f"{pct:.0f}% of all face moisturiser transitions are same product repeats "
        f"({rep:,} of {tot:,} transitions). {verdict} — switching behaviour exists "
        "across sizes and formats.")})

    # 3 & 4 — 30g paths
    fm30 = en[(en["ecat"] == "Face Malai") & (en["esize"] == 30)]
    n30 = len(fm30)
    to_fm50 = int(((fm30["ncat"] == "Face Malai") & (fm30["nsize"] == 50)).sum())
    to_ag50 = int(((fm30["ncat"] == "Active Gel") & (fm30["nsize"] == 50)).sum())
    p_fm50 = 100 * to_fm50 / n30 if n30 else 0
    p_ag50 = 100 * to_ag50 / n30 if n30 else 0
    if n30:
        a3 = (f"Out of {n30:,} FM 30g transitions — {to_fm50:,} ({p_fm50:.0f}%) "
              "moved to FM 50g. " +
              ("This is the primary internal upsize path."
               if to_fm50 >= to_ag50 else
               "Secondary — the cross-category gel switch is bigger."))
        a4 = (f"Out of {n30:,} FM 30g transitions — {to_ag50:,} ({p_ag50:.0f}%) "
              "moved to Active Gel 50g. " +
              ("More 30g buyers move to Active Gel than FM 50g — gel format has "
               "stronger pull than size upgrade within FM."
               if to_ag50 > to_fm50 else
               "FM 50g currently converts better than the gel switch."))
    else:
        a3 = a4 = "No FM 30g transitions in the current selection."
    out.append({"q": "30g → 50g Conversion (FM Only)", "a": a3})
    out.append({"q": "30g → Active Gel (Cross-Category Upsize)", "a": a4})

    # 5 — Downsize risk
    fm50 = en[(en["ecat"] == "Face Malai") & (en["esize"] == 50)]
    ag50 = en[(en["ecat"] == "Active Gel") & (en["esize"] == 50)]
    d1 = int(((fm50["ncat"] == "Face Malai") & (fm50["nsize"] == 30)).sum())
    d2 = int(((ag50["ncat"] == "Face Malai") & (ag50["nsize"] == 30)).sum())
    p1 = 100 * d1 / len(fm50) if len(fm50) else 0
    p2 = 100 * d2 / len(ag50) if len(ag50) else 0
    alert = ("Portfolio-wide downsize pressure detected."
             if max(p1, p2) >= 20 else "Downsize pressure within tolerance.")
    out.append({"q": "Downsize Risk Assessment", "a": (
        f"DOWNSIZE ALERT: {p1:.0f}% of FM 50g buyers drop to 30g ({d1:,} transitions). "
        f"AND {p2:.0f}% of Active Gel buyers also drop to FM 30g ({d2:,} transitions). "
        f"{alert}")})

    # 6 — Key recommendation
    if to_ag50 > to_fm50 and n30:
        rec = ("FOCUS: 30g buyers prefer switching to Active Gel over FM 50g. "
               "Bundle strategy: FM 30g + Active Gel 50g trial kit could accelerate "
               "this natural behaviour.")
    elif n30:
        rec = (f"FOCUS: strengthen the FM 30g → FM 50g upsize path ({p_fm50:.0f}% today). "
               "Consider 50g refill pricing or a size-up nudge at reorder.")
    else:
        rec = "FOCUS: insufficient 30g transitions in the current selection to recommend."
    out.append({"q": "Key Business Recommendation", "a": rec})

    # ---- extended dynamic conclusions (7-12) ----
    depth = long_df.groupby("customer")["journey_depth"].first()
    ep = long_df[(long_df["order_seq"] == 1) & (long_df["item_seq"] == 1)][
        ["customer", "variant"]].merge(depth, on="customer", how="left")

    # 7 — retention & drop-off
    users = len(ep)
    if users:
        once = int((ep["journey_depth"] == 1).sum())
        vg = (ep.assign(rep=ep["journey_depth"] >= 2)
              .groupby("variant").agg(n=("journey_depth", "count"), rate=("rep", "mean")))
        vg = vg[vg["n"] >= 10]
        if len(vg) >= 2:
            best = vg["rate"].idxmax(); worst = vg["rate"].idxmin()
            ret = (f"RETENTION: {round(100*once/users)}% of entry customers never reorder "
                   f"({once:,} of {users:,}). Best repeat: {best} ({round(100*vg.loc[best,'rate'])}%) · "
                   f"Worst: {worst} ({round(100*vg.loc[worst,'rate'])}%). Prioritise win-back for {worst}.")
        else:
            ret = (f"RETENTION: {round(100*once/users)}% of entry customers never reorder "
                   f"({once:,} of {users:,}).")
        out.append({"q": "Customer Retention & Drop-Off", "a": ret})

    # 8 — reorder cadence
    if len(en):
        gaps = sorted(x for x in
                      long_df.drop_duplicates(["customer", "order_seq"]).query("order_seq == 2")["gap_days"]
                      if pd.notna(x))
        if gaps:
            k = len(gaps) // 2
            med = int(round(gaps[k] if len(gaps) % 2 else (gaps[k-1] + gaps[k]) / 2))
            avg = int(round(sum(gaps) / len(gaps)))
            out.append({"q": "Reorder Cadence (Replenishment)", "a": (
                f"REPLENISHMENT: typical reorder gap is {med} days (median) · {avg} days (average). "
                f"Trigger reorder nudges around day {max(0, med - 15)} — two weeks before the jar runs out.")})

    # 9 — demand peak (purchase timing)
    orders = long_df.drop_duplicates(["customer", "order_seq"])
    tb = orders["timing_bucket"].value_counts()
    if len(tb):
        topb = tb.idxmax()
        out.append({"q": "Demand Peak (Purchase Timing)", "a": (
            f"DEMAND PEAK: {round(100 * tb.max() / len(orders))}% of orders occur in {topb} "
            f"({tb.max():,} of {len(orders):,} orders) — the calendar window to weight stock and campaigns.")})

    # 10 — category gravity
    if len(en):
        nets = {}
        for cat in set(en["ecat"]) | set(en["ncat"]):
            inflow = int(((en["ncat"] == cat) & (en["ecat"] != cat)).sum())
            outflow = int(((en["ecat"] == cat) & (en["ncat"] != cat)).sum())
            nets[cat] = inflow - outflow
        nz = {k: v for k, v in nets.items() if v != 0}
        if nz:
            win = max(nz, key=nz.get); lose = min(nz, key=nz.get)
            out.append({"q": "Category Gravity (Net Migration)", "a": (
                f"CATEGORY GRAVITY: {win} gains {abs(nz[win])} net repeat-customers; "
                f"{lose} loses {abs(nz[lose])}. Align cross-sell with the natural pull.")})

    # 11 — stickiest variant (primary-item V2V)
    if len(en):
        g = en.assign(hit=(en["nvar"] == en["evar"])).groupby("evar").agg(
            n=("customer", "size"), rate=("hit", "mean"))
        g = g[g["n"] >= 10]
        if len(g):
            v = g["rate"].idxmax()
            out.append({"q": "Stickiest Variant (V2V Leader)", "a": (
                f"STICKIEST VARIANT: {v} — {round(100 * g.loc[v, 'rate'])}% of its repeat-path buyers "
                f"re-buy the same variant. Anchor bundles and subscriptions around it.")})

    # 12 — top natural switch pair
    if len(en):
        sw = en[en["esku"] != en["nsku"]]
        if len(sw):
            pair = sw.groupby(["esku", "nsku"]).size().sort_values(ascending=False)
            (a, b), n = pair.index[0], pair.iloc[0]
            denom = int((en["esku"] == a).sum())
            out.append({"q": "Top Natural Switch Pair", "a": (
                f"TOP SWITCH: {a} → {b}: {n} customers"
                + (f" ({round(100 * n / denom)}% of {a}'s next purchases)" if denom else "")
                + " — the portfolio's strongest natural migration path.")})
    return out
# ----------------------------------------------------------------------------
# Migration & grammage transitions
# ----------------------------------------------------------------------------
def transition_matrix(long_df: pd.DataFrame, level: str = "sku_key") -> pd.DataFrame:
    """Entry item → next-order item transition counts (first→second purchase)."""
    d = long_df
    firsts = d[d["order_seq"] == 1][["customer", level]].rename(columns={level: "from"})
    seconds = d[d["order_seq"] == 2][["customer", "gap_days", level]].rename(columns={level: "to"})
    m = firsts.merge(seconds, on="customer")
    g = (m.groupby(["from", "to"])
           .agg(Customers=("customer", "size"), AvgDays=("gap_days", "mean"))
           .reset_index())
    g["AvgDays"] = g["AvgDays"].round(1)
    g["% of Entry"] = (100 * g["Customers"] /
                       g.groupby("from")["Customers"].transform("sum")).round(1)
    return g.rename(columns={"AvgDays": "Avg Days 1→2"}) \
            .sort_values(["from", "Customers"], ascending=[True, False])


def grammage_transitions(long_df: pd.DataFrame) -> pd.DataFrame:
    """Entry SKU → next primary SKU classified as Repeat / Same Size / Upsize /
    Lateral / Downsize (Summary Sheet 'Grammage Transition' style)."""
    d = long_df
    firsts = d[(d["order_seq"] == 1) & (d["item_seq"] == 1)][
        ["customer", "category", "variant", "size_g", "sku_key"]].rename(
        columns={"category": "from_cat", "variant": "from_var",
                 "size_g": "from_size", "sku_key": "from_sku"})
    seconds = d[(d["order_seq"] == 2) & (d["item_seq"] == 1)][
        ["customer", "category", "variant", "size_g", "sku_key"]].rename(
        columns={"category": "to_cat", "variant": "to_var",
                 "size_g": "to_size", "sku_key": "to_sku"})
    m = firsts.merge(seconds, on="customer", how="inner")

    def classify(r):
        if r.from_sku == r.to_sku:
            return "Repeat Exact Same Product"
        if r.to_size > r.from_size:
            return "Upsized"
        if r.to_size < r.from_size:
            return "Downsized"
        if r.from_cat != r.to_cat:
            return "Lateral (Same Size, Different Category)"
        return "Repeated Same Size (Any Variant)"

    m["Move"] = m.apply(classify, axis=1)
    rows = []
    for (cat, size), g in m.groupby(["from_cat", "from_size"]):
        n = len(g)
        move_counts = g["Move"].value_counts()
        dest = g[g["Move"] != "Repeat Exact Same Product"].groupby("Move")["to_sku"].agg(
            lambda s: " | ".join(f"{k} ({v})" for k, v in s.value_counts().head(3).items()))
        rows.append({
            "Category": cat, "Entry Size": f"{size}g", "Total Next Purchases": n,
            "Repeat Exact Same": int(move_counts.get("Repeat Exact Same Product", 0)),
            "Repeat %": round(100 * move_counts.get("Repeat Exact Same Product", 0) / n, 1),
            "Upsized": int(move_counts.get("Upsized", 0)),
            "Upsize %": round(100 * move_counts.get("Upsized", 0) / n, 1),
            "Upsize Destinations": dest.get("Upsized", ""),
            "Lateral Switch": int(move_counts.get("Lateral (Same Size, Different Category)", 0)),
            "Lateral Destinations": dest.get("Lateral (Same Size, Different Category)", ""),
            "Downsized": int(move_counts.get("Downsized", 0)),
            "Downsize %": round(100 * move_counts.get("Downsized", 0) / n, 1),
            "Downsize Destinations": dest.get("Downsized", ""),
            "Same Size Diff Variant": int(move_counts.get("Repeated Same Size (Any Variant)", 0)),
            "Dominant Next Move": move_counts.index[0] if n else "",
        })
    return pd.DataFrame(rows)
