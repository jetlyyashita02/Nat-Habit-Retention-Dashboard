"""
calculations.py — shared metric engine. Pure pandas, no UI, fully testable.

Conventions:
  * percentages returned as FRACTIONS (0.304)
  * "customer" always means unique customer id where the source provides one;
    aggregate files (sales CSV) carry customer COUNTS which cannot be deduped
    across rows — those are labelled "customers (touch counts)" in the UI.
  * order-level migration uses the PRIMARY line of each order (see etl.py).
"""
from __future__ import annotations

import calendar
import re
from datetime import date

import numpy as np
import pandas as pd

from formatting import parse_date, parse_month_label

RETENTION_WINDOWS = [15, 30, 60, 90, 120, 180, 240, 300, 360]

# ===========================================================================
# MIGRATION (customer-level, from journey data)
# ===========================================================================
def _journey_flows(model: dict, level: str, entry_filter=None, channel_filter=None,
                   cohort_months=None, max_gap_days=None) -> pd.DataFrame:
    """One row per customer with an observed first+second (primary-line) order."""
    o = model["orders"]
    col = {"category": "category", "variant": "product", "sku": "sku"}[level]
    f = o[o["is_first"]][["customer_id", col, "channel", "cohort_month"]].rename(
        columns={col: "entry", "channel": "entry_channel", "cohort_month": "entry_cohort"})
    s = o[o["is_second"]][["customer_id", col, "order_date", "days_to_prev"]].rename(
        columns={col: "destination"})
    fl = f.merge(s, on="customer_id", how="inner")
    fl["entry_cohort"] = fl["entry_cohort"]
    if entry_filter:
        fl = fl[fl["entry"].isin(entry_filter)]
    if channel_filter:
        fl = fl[fl["entry_channel"].isin(channel_filter)]
    if cohort_months:
        fl = fl[fl["entry_cohort"].isin(cohort_months)]
    if max_gap_days is not None and not (isinstance(max_gap_days, float) and np.isnan(max_gap_days)):
        fl = fl[fl["days_to_prev"].isna() | (fl["days_to_prev"] <= max_gap_days)]
    fl["switched"] = fl["destination"] != fl["entry"]
    # acquired base = customers whose first order matches the filters
    base = f.copy()
    if entry_filter:
        base = base[base["entry"].isin(entry_filter)]
    if channel_filter:
        base = base[base["entry_channel"].isin(channel_filter)]
    if cohort_months:
        base = base[base["entry_cohort"].isin(cohort_months)]
    return fl, base


def migration_analysis(model: dict, level: str, entry_filter=None, channel_filter=None,
                       cohort_months=None, max_gap_days=None, top_flows: int = 15) -> dict:
    fl, base = _journey_flows(model, level, entry_filter, channel_filter, cohort_months, max_gap_days)
    n_acquired = int(base["customer_id"].nunique())
    n_second = int(fl["customer_id"].nunique())
    n_same = int(fl[~fl["switched"]]["customer_id"].nunique())
    n_switch = int(fl[fl["switched"]]["customer_id"].nunique())
    avg_days = float(fl["days_to_prev"].mean()) if n_second else np.nan

    matrix = fl.pivot_table(index="entry", columns="destination", values="customer_id",
                            aggfunc="nunique", fill_value=0)
    matrix_pct = matrix.div(matrix.sum(axis=1), axis=0)

    flows = fl[fl["switched"]].groupby(["entry", "destination"])["customer_id"].nunique().reset_index()
    flows = flows.rename(columns={"customer_id": "customers"})
    flows = flows.sort_values("customers", ascending=False).head(top_flows).reset_index(drop=True)
    flows["pct_of_switchers"] = flows["customers"] / n_switch if n_switch else np.nan

    rows = []
    for e, g in fl.groupby("entry"):
        b = int(base[base["entry"] == e]["customer_id"].nunique())
        g_same = int(g[~g["switched"]]["customer_id"].nunique())
        g_sw = int(g[g["switched"]]["customer_id"].nunique())
        dests = g[g["switched"]].groupby("destination")["customer_id"].nunique().sort_values(ascending=False)
        rows.append({
            "entry": e, "acquired": b,
            "second_orders": int(g["customer_id"].nunique()),
            "same_pct": g_same / b if b else np.nan,
            "switched_pct": g_sw / b if b else np.nan,
            "top_destination": dests.index[0] if len(dests) else "—",
            "avg_days_1_2": float(g["days_to_prev"].mean()) if len(g) else np.nan,
        })
    table = pd.DataFrame(rows).sort_values("acquired", ascending=False)

    # net migration (per entry entity, over customers with an observed 2nd order)
    gained, lost = {}, {}
    for _, r in fl[fl["switched"]].iterrows():
        gained[r["destination"]] = gained.get(r["destination"], 0) + 1
        lost[r["entry"]] = lost.get(r["entry"], 0) + 1
    ents = sorted(set(gained) | set(lost))
    net = pd.DataFrame([{"entity": e, "gained": gained.get(e, 0), "lost": lost.get(e, 0),
                         "net": gained.get(e, 0) - lost.get(e, 0)} for e in ents])
    net = net.sort_values("net", ascending=False)
    return {
        "level": level, "n_acquired": n_acquired, "n_second": n_second,
        "n_same": n_same, "n_switch": n_switch,
        "repeat_pct": n_same / n_acquired if n_acquired else np.nan,
        "switch_pct": n_switch / n_acquired if n_acquired else np.nan,
        "any_second_pct": n_second / n_acquired if n_acquired else np.nan,
        "avg_days_1_2": avg_days,
        "top_destination": fl.groupby("destination")["customer_id"].nunique().idxmax() if n_second else "—",
        "largest_flow": (f"{flows.iloc[0]['entry']} → {flows.iloc[0]['destination']}" if len(flows) else "—"),
        "matrix": matrix, "matrix_pct": matrix_pct, "flows": flows,
        "retention_outflow": table, "net": net,
    }

# ===========================================================================
# SALES / REVENUE
# ===========================================================================
def sales_filter(df: pd.DataFrame, months=None, categories=None, channels=None,
                 skus=None, products=None) -> pd.DataFrame:
    d = df
    for col, vals, name in [("month", months, "months"), ("category", categories, "categories"),
                            ("channel", channels, "channels"), ("sku", skus, "SKUs"),
                            ("product", products, "products")]:
        if vals:
            vals = [v for v in vals if v != "All"]
            if vals and col in d.columns:
                d = d[d[col].isin(vals)]
    return d

def _safe_div(a, b):
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where((b == 0) | pd.isna(b) | pd.isna(a), np.nan, a / b)

def sales_kpis(df: pd.DataFrame) -> dict:
    rev = float(df["revenue"].sum()) if len(df) else np.nan
    orders = float(df["orders"].sum()) if len(df) and df["orders"].notna().any() else np.nan
    cust = float(df["customers"].sum()) if len(df) and df["customers"].notna().any() else np.nan
    qty = float(df["quantity"].sum()) if len(df) and df["quantity"].notna().any() else np.nan
    return {
        "revenue": rev, "orders": orders, "customers": cust, "quantity": qty,
        "aov": _safe_div(rev, orders), "rev_per_customer": _safe_div(rev, cust),
        "rev_per_order": _safe_div(rev, orders),
    }

def sales_trend(df: pd.DataFrame, by: str) -> pd.DataFrame:
    """by in {'month','category','channel'}: stacked revenue contribution over months."""
    if by == "month":
        d = df.groupby("month", as_index=False)[["revenue", "orders"]].sum()
        d["bucket"] = d["month"]
    else:
        d = df.groupby(["month", by], as_index=False)["revenue"].sum()
        d = d.rename(columns={by: "bucket"})
        d["orders"] = np.nan
    return d.sort_values(["month", "bucket"])

def category_contribution(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("category", as_index=False)[["revenue", "orders", "customers", "quantity"]].sum()
    tot = g["revenue"].sum()
    g["revenue_share"] = _safe_div(g["revenue"], tot)
    g["orders_share"] = _safe_div(g["orders"], g["orders"].sum())
    g["customers_share"] = _safe_div(g["customers"], g["customers"].sum())
    g["quantity_share"] = _safe_div(g["quantity"], g["quantity"].sum())
    return g.sort_values("revenue", ascending=False)

def variant_contribution(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby(["sku", "product", "category"], as_index=False)[["revenue", "orders", "quantity"]].sum()
    tot = g["revenue"].sum()
    g = g.sort_values("revenue", ascending=False).reset_index(drop=True)
    g["revenue_share"] = _safe_div(g["revenue"], tot)
    g["cumulative_share"] = g["revenue_share"].cumsum()
    return g

def channel_contribution(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("channel", as_index=False)[["revenue", "orders", "customers"]].sum()
    tot = g["revenue"].sum()
    g["revenue_share"] = _safe_div(g["revenue"], tot)
    g["aov"] = _safe_div(g["revenue"], g["orders"])
    return g.sort_values("revenue", ascending=False)

def pivot_matrix(df: pd.DataFrame, row_col: str, col_col: str, val: str = "revenue") -> pd.DataFrame:
    if row_col not in df.columns or col_col not in df.columns:
        return pd.DataFrame()
    return df.pivot_table(index=row_col, columns=col_col, values=val, aggfunc="sum", fill_value=0)

# ===========================================================================
# AOP
# ===========================================================================
def aop_long_filtered(aop: dict, categories=None, channels=None, owners=None,
                      new_ex=None, use_total_rows: bool = True,
                      month_min=None, month_max=None,
                      drop_total_cats: bool = True) -> pd.DataFrame:
    m = aop["meta_names"]
    long = aop["long"]
    if long.empty:
        return long
    ch_col = aop["channel_sub_col"]
    d = long
    if categories and aop["category_col"] in d.columns:
        d = d[d[aop["category_col"]].isin(categories)]
    if channels and ch_col in d.columns:
        d = d[d[ch_col].isin(channels)]
    if owners and "Category Owner" in d.columns:
        d = d[d["Category Owner"].isin(owners)]
    if new_ex and "New/Existing" in d.columns:
        d = d[d["New/Existing"].isin(new_ex)]
    if use_total_rows and ch_col in d.columns and aop["total_row_found"]:
        d = d[d[ch_col].str.upper().str.strip() == "TOTAL"]
    elif ch_col in d.columns:
        d = d[~(d[ch_col].str.upper().str.strip() == "TOTAL")]
    if not categories and drop_total_cats and aop["category_col"] in d.columns:
        # grand-total category rows (label starting with "total") double the
        # aggregate when constituent categories are also present
        cat_l = d[aop["category_col"]].astype(str).str.strip().str.lower()
        d = d[~cat_l.str.startswith("total")]
    if month_min:
        d = d[d["month"] >= month_min]
    if month_max:
        d = d[d["month"] <= month_max]
    return d

def aop_monthly(aop: dict, **kw) -> pd.DataFrame:
    d = aop_long_filtered(aop, **kw)
    if d.empty:
        return pd.DataFrame(columns=["month", "revenue", "spend", "roas"])
    d = d[d["month"].astype(str).str.match(r"^\d{4}-\d{2}$")]  # exclude quarterly/summary keys
    if d.empty:
        return pd.DataFrame(columns=["month", "revenue", "spend", "roas"])
    piv = d.pivot_table(index="month", columns="block", values="value", aggfunc="sum").sort_index()
    out = pd.DataFrame({"month": piv.index.tolist()})
    out["revenue"] = piv["revenue"].to_numpy() if "revenue" in piv.columns else np.nan
    out["spend"] = piv["spend"].to_numpy() if "spend" in piv.columns else np.nan
    out["roas"] = _safe_div(out["revenue"], out["spend"])
    return out

def aop_category_share(aop: dict, block: str, **kw) -> pd.DataFrame:
    d = aop_long_filtered(aop, **kw)
    if d.empty:
        return pd.DataFrame()
    cat_col = aop["category_col"]
    piv = d.pivot_table(index=cat_col, columns="month", values="value", aggfunc="sum")
    tot = piv.sum(axis=1)
    share = piv.div(tot, axis=0)
    return share

def aop_fy(aop: dict, categories=None, **kw) -> pd.DataFrame:
    fy = aop["fy"]
    if fy.empty:
        return fy
    if categories and aop["category_col"] in fy.columns:
        fy = fy[fy[aop["category_col"]].isin(categories)]
    if aop["channel_sub_col"] in fy.columns and aop["total_row_found"]:
        fy = fy[fy[aop["channel_sub_col"]].str.upper().str.strip() == "TOTAL"]
    return fy

def aop_split_months(months: list[str], ref_month: str) -> tuple[list, list]:
    actual = [m for m in months if m <= ref_month]
    plan = [m for m in months if m > ref_month]
    return actual, plan

# ===========================================================================
# RETENTION
# ===========================================================================
def cohort_maturity_days(onb_date: date, as_of: date) -> int:
    return max(0, (as_of - onb_date).days)

def fm_retention_table(rt: pd.DataFrame, windows: list[int], as_of: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns (values, mature) DataFrames indexed like rt.
    values: fraction or NaN; mature: bool (False => window not yet observable).
    Denominator = 'Customer' cohort size of each row (documented in sheet header).
    """
    vals, mat = [], []
    for _, r in rt.iterrows():
        mad = cohort_maturity_days(r["onb_date"], as_of)
        v, m = [], []
        for w in windows:
            if w <= mad:
                v.append(r[f"w{w}"]); m.append(True)
            else:
                v.append(np.nan); m.append(False)
        vals.append(v); mat.append(m)
    cols = [f"w{w}" for w in windows]
    return pd.DataFrame(vals, index=rt.index, columns=cols), pd.DataFrame(mat, index=rt.index, columns=cols)

def journey_retention(model: dict, level: str = "category", as_of: date = None,
                      cohort_months: list | None = None) -> dict:
    """
    Computed retention from journey data.
    Denominator = customers whose FIRST (primary-line) order falls in the cohort
    (month × entity). Retained@W = customer made any further primary order within W days.
    """
    o = model["orders"]
    col = {"category": "category", "variant": "product", "sku": "sku"}[level]
    first = o[o["is_first"]][["customer_id", col, "cohort_month", "order_date"]].rename(columns={col: "entity"})
    later = o[~o["is_first"]][["customer_id", "order_date", "days_to_prev"]].rename(columns={"days_to_prev": "gap"})
    m = first.merge(later, on="customer_id", how="left")
    if cohort_months:
        m = m[m["cohort_month"].isin(cohort_months)]
    m["gap"] = m["gap"].where(m["gap"] > 0)
    as_of = as_of or pd.Timestamp.now().date()
    month_start = lambda cm: date(int(cm[:4]), int(cm[5:7]), 1)
    rows = []
    for (cm, ent), g in m.groupby(["cohort_month", "entity"], observed=True):
        n = int(g["customer_id"].nunique())
        mad = max(0, (as_of - month_start(cm)).days)
        row = {"cohort": cm, "entity": ent, "customers": n, "mature_days": mad}
        for w in RETENTION_WINDOWS:
            if w <= mad:
                ok = g.groupby("customer_id")["gap"].min()
                row[f"w{w}"] = float((ok <= w).mean())
            else:
                row[f"w{w}"] = np.nan
        rows.append(row)
    d = pd.DataFrame(rows)
    return {"df": d}

def v2v_v2c_analysis(model: dict) -> dict:
    """
    V2V (variant loyalty): 2nd order is the SAME VARIANT (product name) as 1st.
    V2C (category loyalty): 2nd order stays in the SAME CATEGORY as 1st (any variant).
    Denominator = customers with an observed qualifying second order.
    V2C >= V2V by construction; they are NOT the same metric.
    """
    o = model["orders"]
    f = o[o["is_first"]][["customer_id", "product", "category"]].rename(
        columns={"product": "v1", "category": "c1"})
    s = o[o["is_second"]][["customer_id", "product", "category"]].rename(
        columns={"product": "v2", "category": "c2"})
    m = f.merge(s, on="customer_id", how="inner")
    m["v2v"] = m["v1"] == m["v2"]
    m["v2c"] = m["c1"] == m["c2"]

    def block(col, name):
        g = m.groupby(col, observed=True).agg(
            qualifying=("customer_id", "nunique"),
            v2v=("v2v", "sum"), v2c=("v2c", "sum")).reset_index().rename(columns={col: name})
        g["v2v_pct"] = _safe_div(g["v2v"], g["qualifying"])
        g["v2c_pct"] = _safe_div(g["v2c"], g["qualifying"])
        g["gap"] = g["v2c_pct"] - g["v2v_pct"]
        return g.sort_values("qualifying", ascending=False)

    by_cat = block("c1", "category")
    by_var = block("v1", "variant").merge(
        m[m["v2v"] | m["v2c"]][["v1", "c1"]].drop_duplicates().rename(columns={"v1": "variant", "c1": "category"}),
        on="variant", how="left")
    overall_qual = int(m["customer_id"].nunique())
    overall = {
        "qualifying": overall_qual,
        "v2v_pct": float(m["v2v"].mean()) if len(m) else np.nan,
        "v2c_pct": float(m["v2c"].mean()) if len(m) else np.nan,
    }
    return {"by_category": by_cat, "by_variant": by_var, "overall": overall}

# ===========================================================================
# PRICE CHANGES
# ===========================================================================
def derived_price_changes(sales: pd.DataFrame, threshold: float = 0.05) -> pd.DataFrame:
    """
    Realized unit price per SKU-month = revenue / quantity (quantity > 0 only).
    MoM change % vs the SKU's previous month with sales.
    This is a DETECTED signal from realized prices — not list/MRP.
    """
    d = sales[sales["quantity"].notna() & (sales["quantity"] > 0)].copy()
    if d.empty:
        return pd.DataFrame(columns=["sku", "product", "month", "unit_price", "prev_price", "change_pct", "direction"])
    if "month" not in d.columns:
        d["month"] = d["order_date"].map(parse_date).map(
            lambda v: f"{v.year:04d}-{v.month:02d}" if isinstance(v, (pd.Timestamp, date)) else None)
    g = d.groupby(["sku", "product", "month"], as_index=False)[["revenue", "quantity"]].sum()
    g["unit_price"] = _safe_div(g["revenue"], g["quantity"])
    g = g.sort_values(["sku", "month"])
    g["prev_price"] = g.groupby("sku")["unit_price"].shift(1)
    g["prev_month"] = g.groupby("sku")["month"].shift(1)
    g["change_pct"] = _safe_div(g["unit_price"] - g["prev_price"], g["prev_price"])
    g["direction"] = np.where(g["change_pct"].isna(), "",
                            np.where(g["change_pct"] > threshold, "Increase",
                              np.where(g["change_pct"] < -threshold, "Decrease", "Stable")))
    return g

def price_flags(detected: pd.DataFrame, threshold: float = 0.05) -> pd.DataFrame:
    if detected.empty:
        return detected
    return detected[detected["direction"].isin(["Increase", "Decrease"])].sort_values(
        "change_pct", key=abs, ascending=False)

# ===========================================================================
# INTRA-CATEGORY MOVEMENT (category-scoped sales — no customer ids)
# ===========================================================================
_SIZE_RE = re.compile(r"-(\d{2,4})$")
_UNIT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|g|kg|l)\b", re.I)


def intra_category_movement(df: pd.DataFrame) -> dict:
    """
    Intra-category movement from a category-scoped sales aggregate.

    Source note: this export has no customer/order ids, so this measures
    SKU- and grammage-level revenue-share movement (1st half of the observed
    window vs 2nd half) — it is NOT customer-level migration.

    Returns {"ok": True, "window": (start, end, split), "n_skus", "sku",
             "grammage", "trend", "top_skus"} or {"ok": False, "reason"}.
    """
    d = df.dropna(subset=["order_date", "revenue"]).copy()
    if d.empty:
        return {"ok": False, "reason": "No parseable rows with dates and revenue."}
    d["dt"] = pd.to_datetime(d["order_date"], errors="coerce")
    d = d.dropna(subset=["dt"])
    if d.empty:
        return {"ok": False, "reason": "No parseable order dates."}
    d0, d1 = d["dt"].min(), d["dt"].max()
    if d0 == d1:
        return {"ok": False, "reason": "Window is a single day — cannot split into two halves."}
    mid = d0 + (d1 - d0) / 2
    d["half"] = np.where(d["dt"] <= mid, 1, 2)
    tot = d.groupby("half")["revenue"].sum()
    tot1, tot2 = float(tot.get(1, 0.0)), float(tot.get(2, 0.0))

    def share_table(idx_cols, dframe):
        g = dframe.groupby(idx_cols + ["half"], as_index=False)["revenue"].sum()
        p = g.pivot(index=idx_cols, columns="half", values="revenue").reindex(columns=[1, 2], fill_value=0.0)
        p = p.fillna(0.0)  # missing (entity, half) combinations = no sales in that half
        out = pd.DataFrame({"rev_1st": p[1], "rev_2nd": p[2]})
        out["share_1st"] = out["rev_1st"] / tot1 if tot1 else np.nan
        out["share_2nd"] = out["rev_2nd"] / tot2 if tot2 else np.nan
        out["delta_pp"] = (out["share_2nd"] - out["share_1st"]) * 100
        out["total_rev"] = out["rev_1st"] + out["rev_2nd"]
        out = out.reset_index()
        out["status"] = np.where((out["rev_1st"] == 0) & (out["rev_2nd"] > 0), "Entered",
                         np.where((out["rev_2nd"] == 0) & (out["rev_1st"] > 0), "Exited", "Continuing"))
        return out.sort_values("delta_pp", ascending=False).reset_index(drop=True)

    sku = share_table(["sku", "product"], d)

    def _parse(sc, pc):
        m = _SIZE_RE.search(str(sc))
        if not m:
            return None, ""
        size = str(int(float(m.group(1))))
        u = _UNIT_RE.search(str(pc))
        return size, (u.group(2).lower() if u else "")

    parsed = [_parse(sc, pc) for sc, pc in zip(d["sku"], d["product"])]
    units_by_size = {}
    for size, unit in parsed:
        if size and unit:
            units_by_size.setdefault(size, set()).add(unit)
    # infer a unit for unlabelled rows only when the size is unambiguously labelled elsewhere
    inferred = {sz: (next(iter(us)) if len(us) == 1 else "") for sz, us in units_by_size.items()}

    def _label(p):
        size, unit = p
        if not size:
            return None
        unit = unit or inferred.get(size, "")
        return f"{size}{unit}" if unit else size

    d["grammage"] = [_label(p) for p in parsed]
    grammage = share_table(["grammage"], d.dropna(subset=["grammage"])) if d["grammage"].notna().any() else pd.DataFrame()
    top = sku.nlargest(10, "total_rev")["sku"].tolist()
    trend = d[d["sku"].isin(top)].groupby(["dt", "sku"], as_index=False)["revenue"].sum().sort_values(["sku", "dt"])
    return {"ok": True, "window": (str(d0.date()), str(d1.date()), str(mid.date())),
            "n_skus": int(sku["sku"].nunique()), "sku": sku, "grammage": grammage,
            "trend": trend, "top_skus": top}

# ===========================================================================
# NPS
# ===========================================================================
def nps_score_stats(scores: pd.Series) -> dict:
    s = pd.to_numeric(scores, errors="coerce").dropna()
    s = s[(s >= 0) & (s <= 10)]
    n = int(len(s))
    if n == 0:
        return {"n": 0, "nps": np.nan, "avg": np.nan, "promoters": np.nan, "passives": np.nan, "detractors": np.nan,
                "dist": pd.Series(dtype=float)}
    dist = s.value_counts().reindex(range(11), fill_value=0)
    p, pa, dt = (s >= 9).sum(), ((s == 8) | (s == 7)).sum(), (s <= 6).sum()
    return {
        "n": n, "nps": float(p / n * 100 - dt / n * 100), "avg": float(s.mean()),
        "promoters": float(p / n), "passives": float(pa / n), "detractors": float(dt / n),
        "dist": dist,
    }

def nps_by_dimension(nps: dict, column: str) -> pd.DataFrame:
    d = nps["df"]
    if column not in d.columns or not d[column].replace("", np.nan).notna().any():
        return pd.DataFrame()
    rows = []
    for val, g in d[d[column] != ""].groupby(column):
        rows.append({"dimension": val, "n": len(g),
                     **{k: v for k, v in [("brand_nps", nps_score_stats(g["brand_score"])["nps"]),
                                          ("product_nps", nps_score_stats(g["product_score"])["nps"]),
                                          ("brand_avg", nps_score_stats(g["brand_score"])["avg"])]}})
    out = pd.DataFrame(rows)
    # exclude buckets too small to read (n < 5)
    out = out.sort_values("n", ascending=False)
    return out

def theme_counts(nps: dict, kind: str) -> pd.DataFrame:
    t = nps[f"themes_{kind}"]
    if t is None or t.empty:
        return pd.DataFrame(columns=["theme", "mentions"])
    g = t.groupby("theme").size().reset_index(name="mentions").sort_values("mentions", ascending=False)
    n = nps["df"].shape[0]
    g["pct_of_responses"] = g["mentions"] / n if n else np.nan
    return g

def competitor_pull(nps: dict) -> pd.DataFrame:
    d = nps["df"]
    if not nps.get("has_migrated"):
        return pd.DataFrame()
    s = d["migrated_from"].replace("", np.nan).dropna()
    g = s.value_counts().reset_index()
    g.columns = ["source", "customers"]
    g["is_first_time"] = g["source"].str.lower().str.contains("first")
    g["share"] = g["customers"] / g["customers"].sum()
    return g.sort_values("customers", ascending=False).reset_index(drop=True)

# ===========================================================================
# CS
# ===========================================================================
def cs_kpis(cs: dict) -> dict:
    d = cs["df"]
    n = len(d)
    if n == 0:
        return {"tickets": 0}
    status = d["chat_status"].str.lower()
    resolved = status.isin(["resolved", "closed", "solved"]).sum()
    top_type = d["failure_type"].mode()
    top_reason = d["failure_reason"].mode()
    fh = d["fulfil_hours"].dropna()
    return {
        "tickets": int(n),
        "resolved_pct": float(resolved / n),
        "unresolved_pct": float(1 - resolved / n),
        "top_failure_type": top_type.iloc[0] if len(top_type) else "—",
        "top_failure_reason": top_reason.iloc[0] if len(top_reason) else "—",
        "median_fulfil_hours": float(fh.median()) if len(fh) else np.nan,
        "pct_over_72h": float((fh > 72).mean()) if len(fh) else np.nan,
        "n_with_fulfil_times": int(len(fh)),
    }

def cs_hierarchy(cs: dict) -> pd.DataFrame:
    d = cs["df"]
    g = (d.groupby(["failure_type", "failure_reason", "failure_subreason"], observed=True)
         .size().reset_index(name="tickets")
         .sort_values("tickets", ascending=False))
    return g

def cs_counts(cs: dict, column: str) -> pd.DataFrame:
    d = cs["df"]
    if column not in d.columns:
        return pd.DataFrame()
    g = d[d[column] != "Unspecified"].groupby(column).size().reset_index(name="tickets")
    g["share"] = g["tickets"] / g["tickets"].sum()
    return g.sort_values("tickets", ascending=False)

# ===========================================================================
# NEW-TO-CATEGORY ORDER MOVEMENT
# ===========================================================================
def ntc_maturity(df: pd.DataFrame, as_of: date, maturity_days: int = 90) -> pd.DataFrame:
    d = df.copy()
    d["cohort_start"] = d["cohort"].map(lambda c: date(int(c[:4]), int(c[5:7]), 1))
    d["observed_days"] = (pd.to_datetime(as_of) - pd.to_datetime(d["cohort_start"])).dt.days
    d["mature"] = d["observed_days"] >= maturity_days
    return d

def ntc_kpis(df: pd.DataFrame, as_of: date, maturity_days: int = 90) -> dict:
    d = ntc_maturity(df, as_of, maturity_days)
    mat = d[d["mature"]]
    def wavg(col, weight="first_order"):
        w = mat[weight].fillna(0)
        v = mat[col]
        ok = v.notna() & (w > 0)
        return float((v[ok] * w[ok]).sum() / w[ok].sum()) if ok.any() else np.nan
    return {
        "cohorts_total": int(len(d)),
        "cohorts_mature": int(len(mat)),
        "new_customers": int(mat["first_order"].sum()) if len(mat) else np.nan,
        "avg_sec_pct": wavg("sec_pct"),
        "avg_days_sec": wavg("avg_days_to_sec"),
        "avg_third_pct": wavg("third_pct"),
        "avg_days_third": wavg("avg_days_to_third"),
        "maturity_days": maturity_days,
    }

# ===========================================================================
# shared small helpers
# ===========================================================================
def last_month_pair(months: list[str]):
    """(prev_month, last_month) or (None, None)."""
    months = sorted(months)
    if len(months) < 2:
        return None, None
    return months[-2], months[-1]

def growth_pct(cur, prev):
    if cur is None or prev in (None, 0) or pd.isna(cur) or pd.isna(prev):
        return np.nan
    return (cur - prev) / abs(prev)
