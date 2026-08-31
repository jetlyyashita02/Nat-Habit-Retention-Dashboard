"""
etl.py — transform raw CSV grids into internal analytical models.

All builders receive the raw 2-D grid (header=None), a SourceReport, and — for
flat sources — a column map {canonical: column_index} plus the header row.
Design rules:
  * bad rows are quarantined (counted + warned), never crash the app
  * percentages leave here as FRACTIONS (0.304)
  * the wide AOP sheet and the multi-block summary sheet are parsed by their
    structural block labels, not fixed positions
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from formatting import (SourceReport, clean_str, is_blank, month_of, parse_date,
                        parse_datetime, parse_month_label, parse_number, parse_pct,
                        split_multi)

# ===========================================================================
# helpers
# ===========================================================================
def _body(raw: pd.DataFrame, header_row: int) -> pd.DataFrame:
    return raw.iloc[header_row + 1:].reset_index(drop=True)

def _cell(raw, i, j):
    try:
        return clean_str(raw.iloc[i, j])
    except Exception:
        return ""

def _col(raw: pd.DataFrame, i: int, colmap: dict, canon: str):
    j = colmap.get(canon)
    if j is None:
        return None
    return raw.iloc[i, j]

def _series(raw: pd.DataFrame, header_row: int, colmap: dict, canon: str):
    j = colmap.get(canon)
    if j is None:
        return None
    body = _body(raw, header_row)
    return body.iloc[:, j]

# ===========================================================================
# SALES / REVENUE
# ===========================================================================
def build_sales_model(raw: pd.DataFrame, rep: SourceReport, colmap: dict, header_row: int):
    for req in ["order_date", "category", "revenue"]:
        if req not in colmap:
            rep.err(f"Required column missing: a date/category/revenue column. Sales analysis cannot be calculated without it.")
            return None
    body = _body(raw, header_row)
    d = pd.DataFrame(index=body.index)
    d["order_date"] = body.iloc[:, colmap["order_date"]].map(parse_date)
    d["month"] = body.iloc[:, colmap["order_date"]].map(lambda v: month_of(parse_date(v)) or parse_month_label(v))
    n_bad = int(d["order_date"].isna().sum()) + int(d["month"].isna().sum())
    if n_bad:
        rep.warnings.append(f"{n_bad} rows had unparseable/missing dates and are excluded from date-based views.")
    if "sku" in colmap:
        d["sku"] = body.iloc[:, colmap["sku"]].map(clean_str)
    else:
        d["sku"] = ""
        rep.warnings.append("⚠ SKU column not found — variant-level analysis falls back to the product name.")
    if "product" in colmap:
        d["product"] = body.iloc[:, colmap["product"]].map(clean_str)
    else:
        d["product"] = d["sku"]
    d["category"] = body.iloc[:, colmap["category"]].map(clean_str)
    if "channel" in colmap:
        d["channel"] = body.iloc[:, colmap["channel"]].map(clean_str)
    else:
        d["channel"] = "Unknown"
        rep.warnings.append("⚠ Channel column not found — channel contribution shows a single 'Unknown' bucket.")
    for c in ["orders", "customers", "quantity", "revenue"]:
        if c in colmap:
            d[c] = body.iloc[:, colmap[c]].map(parse_number)
        else:
            d[c] = np.nan
            rep.warnings.append(f"⚠ '{c}' column not found — related metrics will be partial.")
    d = d.dropna(subset=["month"]).reset_index(drop=True)
    d.loc[d["category"] == "", "category"] = "(Uncategorized)"
    d.loc[d["channel"] == "", "channel"] = "Unknown"
    d.loc[d["product"] == "", "product"] = d["sku"]
    d.loc[d["sku"] == "", "sku"] = d["product"]
    n_dup = int(len(d) - d.drop_duplicates().shape[0])
    if n_dup:
        rep.warnings.append(f"{n_dup:,} fully duplicate rows removed (kept one).")
        d = d.drop_duplicates().reset_index(drop=True)
    if d["quantity"].notna().any() and (d["quantity"] == 0).any():
        rep.warnings.append(f"{int((d['quantity'] == 0).sum())} rows have zero quantity — excluded from price calculations.")
    if (d["revenue"] < 0).any():
        rep.warnings.append(f"{int((d['revenue'] < 0).sum())} rows have negative revenue (kept; check refunds).")
    rep.date_min = str(d["month"].min())
    rep.date_max = str(d["month"].max())
    rep.entities = {"Categories": int(d["category"].nunique()), "Variants": int(d["product"].nunique()),
                    "SKUs": int(d["sku"].nunique()), "Channels": int(d["channel"].nunique())}
    return {"df": d}

# ===========================================================================
# JOURNEY (customer × order)
# ===========================================================================
def build_journey_model(raw: pd.DataFrame, rep: SourceReport, colmap: dict, header_row: int):
    from sources import journey_is_wide
    if journey_is_wide(raw, header_row):
        return _build_journey_wide(raw, rep, colmap, header_row)
    for req in ["customer_id", "order_date", "category"]:
        if req not in colmap:
            rep.err(f"Customer-level retention/migration requires a customer id, an order date and a category column. "
                    f"Missing: {[r for r in ['customer_id','order_date','category'] if r not in colmap]}. Customer-level analysis skipped.")
            return None
    body = _body(raw, header_row)
    d = pd.DataFrame(index=body.index)
    d["customer_id"] = body.iloc[:, colmap["customer_id"]].map(clean_str)
    d["order_date"] = body.iloc[:, colmap["order_date"]].map(parse_date)
    d["sku"] = body.iloc[:, colmap["sku"]].map(clean_str) if "sku" in colmap else ""
    d["product"] = body.iloc[:, colmap.get("product", colmap.get("sku"))].map(clean_str) if (colmap.get("product") is not None or colmap.get("sku") is not None) else ""
    d["category"] = body.iloc[:, colmap["category"]].map(clean_str)
    d["channel"] = body.iloc[:, colmap["channel"]].map(clean_str) if "channel" in colmap else ""
    d["quantity"] = body.iloc[:, colmap["quantity"]].map(parse_number) if "quantity" in colmap else 1.0
    if "sku" not in colmap or "product" not in colmap:
        rep.warnings.append("⚠ SKU/product column missing — variant-level V2V/V2C unavailable; category-level only.")

    if "order_id" in colmap:
        provided_full = body.iloc[:, colmap["order_id"]].map(clean_str)
    else:
        provided_full = pd.Series([""] * len(body), index=body.index)
        rep.warnings.append("⚠ Order ID column missing — each row is treated as a separate order. "
                            "If one order contains several rows, migration may overcount switches; upload with an order ID for exact order-level results.")
    mask = d["customer_id"].ne("") & d["order_date"].notna()
    n_synthetic = int((provided_full[mask] == "").sum())
    if n_synthetic:
        rep.warnings.append(f"{n_synthetic:,} rows lack an order_id and are treated as separate orders.")
    d = d[mask].reset_index(drop=True)
    provided = provided_full[mask].reset_index(drop=True)
    d["order_id"] = provided.where(provided != "", "ROW-" + d.index.astype(str))
    return _journey_common(d, rep)

def _journey_common(d: pd.DataFrame, rep: SourceReport) -> dict:
    """Shared downstream pipeline for customer-level journey data (line-grain df)."""
    d.loc[d["category"] == "", "category"] = "(Uncategorized)"
    d.loc[d["product"] == "", "product"] = d["sku"]
    d.loc[d["sku"] == "", "sku"] = d["product"]
    d = d.sort_values(["customer_id", "order_date", "order_id"]).reset_index(drop=True)

    # PRIMARY line per order: avoids inflating migration via many-to-many combos
    d["_q"] = d["quantity"].fillna(0)
    primary = d.sort_values("_q", ascending=False).groupby(
        ["customer_id", "order_date", "order_id"], observed=True).head(1)
    d["is_primary"] = d.index.isin(primary.index)
    n_lines = len(d)
    n_orders = int(d["is_primary"].sum())
    if n_orders < n_lines:
        n_multi = int(d.groupby(["customer_id", "order_date", "order_id"], observed=True).size().gt(1).sum())
        rep.warnings.append(f"Multi-line orders: {n_lines - n_orders:,} extra lines across {n_multi:,} orders. "
                            f"Migration/retention use the PRIMARY line per order (largest quantity).")
    d = d.drop(columns=["_q"]).sort_values(["customer_id", "order_date", "order_id"]).reset_index(drop=True)
    # order sequence + day gaps at ORDER level (multi-line orders must not shift the sequence)
    o = (d[["customer_id", "order_date", "order_id"]]
         .drop_duplicates().sort_values(["customer_id", "order_date", "order_id"]).reset_index(drop=True))
    o["_dt"] = pd.to_datetime(o["order_date"], errors="coerce")
    o["order_seq"] = o.groupby("customer_id", observed=True).cumcount() + 1
    o["days_to_prev"] = o.groupby("customer_id", observed=True)["_dt"].diff().dt.days
    d = d.merge(o[["customer_id", "order_id", "order_seq", "days_to_prev"]],
                on=["customer_id", "order_id"], how="left")
    d["cohort_month"] = d["order_date"].map(month_of)
    d["is_first"] = d["order_seq"] == 1
    d["is_second"] = d["order_seq"] == 2
    d = d.dropna(subset=["category"]).reset_index(drop=True)
    rep.date_min = str(d["order_date"].min())
    rep.date_max = str(d["order_date"].max())
    rep.entities = {"Customers": int(d["customer_id"].nunique()), "Orders": n_orders,
                    "Categories": int(d["category"].nunique()), "Variants": int(d["product"].nunique())}
    return {"df": d, "orders": d[d["is_primary"]].reset_index(drop=True),
            "n_customers": int(d["customer_id"].nunique()), "n_orders": n_orders}

# ---------------------------------------------------------------------------
# journey "base sheet" (wide): one row per customer, first..sixth order columns
# ---------------------------------------------------------------------------
_JW_WORDS = ["first", "second", "third", "fourth", "fifth", "sixth"]
_JW_CAT_SUFFIX = ["first", "2nd", "3rd", "4th", "5th", "6th"]
_JW_DAYS = ["1st and 2nd", "2nd and 3rd", "3rd and 4th", "4th and 5th", "5th and 6th"]

def _split_csv_lines(v) -> list:
    if v is None or is_blank(v):
        return []
    return [x.strip() for x in str(v).split(",") if x.strip()]

def _norm_tokens(s) -> list:
    return [t for t in re.split(r"[^a-z0-9]+", str(s).lower()) if len(t) >= 3]

def _infer_line_category(product_name, order_cats) -> str:
    """Assign one of the order's category set to a product line by name similarity.
    Literal containment wins; otherwise the category with the most significant
    tokens (len >= 3) appearing in the product name. Generic — no fixed names."""
    order_cats = [c for c in order_cats if c]
    if not order_cats:
        return ""
    if len(order_cats) == 1:
        return order_cats[0]
    name = str(product_name).lower()
    for c in order_cats:
        if str(c).lower() in name:
            return c
    name_toks = set(_norm_tokens(product_name))
    best, best_score = "", 0
    for c in order_cats:
        score = sum(1 for t in set(_norm_tokens(c)) if t in name_toks)
        if score > best_score:
            best, best_score = c, score
    return best

def _build_journey_wide(raw: pd.DataFrame, rep: SourceReport, colmap: dict, header_row: int) -> dict:
    """Wide base sheet: one row per customer with first/second/.../sixth order
    columns (multi-line orders comma-separated inside a cell). Reshapes to the
    line-grain long format and reuses the common journey pipeline."""
    body = _body(raw, header_row)
    arr = body.to_numpy()
    header = [str(x).replace("_", " ").strip().lower() for x in raw.iloc[header_row].tolist()]
    def colidx(norm):
        for j, h in enumerate(header):
            if h == norm:
                return j
        return None
    cust_j = colmap.get("customer_id")
    if cust_j is None:
        rep.err("Journey base sheet requires a customer id/name column.")
        return None
    date_j = {w: colidx(f"{w} order date") for w in _JW_WORDS}
    sku_j = {w: colidx(f"{w} purchased sku") for w in _JW_WORDS}
    prod_j = {w: colidx(f"{w} purchased short code") for w in _JW_WORDS}
    cat_j = {w: colidx(f"category {suf}") for w, suf in zip(_JW_WORDS, _JW_CAT_SUFFIX)}
    days_j = {a: colidx(f"days between {a}") for a in _JW_DAYS}
    depth_j = colidx("journey depth")
    if all(v is None for v in date_j.values()) or all(v is None for v in sku_j.values()):
        rep.err("Journey base sheet: expected '<order> order date' and '<order> purchased sku' columns.")
        return None
    fname = str(getattr(rep, "filename", "")).lower()
    channel = "D2C" if "d2c" in fname else "Unknown"

    rows = []
    n_unmapped = 0
    n_depth_mm = 0
    n_days_mm = 0
    for i in range(len(arr)):
        nm = clean_str(arr[i, cust_j])
        if not nm:
            continue
        cust_seq = []  # (order_number, parsed_date)
        for n, w in enumerate(_JW_WORDS, start=1):
            if date_j[w] is None:
                continue
            v = arr[i, date_j[w]]
            if is_blank(v):
                continue
            dt = parse_date(v)
            if dt is None:
                continue
            cust_seq.append((n, dt))
            skus = _split_csv_lines(arr[i, sku_j[w]]) if sku_j[w] is not None else []
            prods = _split_csv_lines(arr[i, prod_j[w]]) if prod_j[w] is not None else []
            cats = _split_csv_lines(arr[i, cat_j[w]]) if cat_j[w] is not None else []
            if not skus and not prods:
                skus, prods = [""], [""]
            if len(prods) != len(skus):
                if len(prods) == 1:
                    prods = prods * len(skus)
                else:
                    prods = (prods + skus)[:len(skus)]
            for k in range(len(skus)):
                sku = skus[k] if k < len(skus) else ""
                prod = prods[k] if k < len(prods) else sku
                cat = _infer_line_category(prod, cats)
                if not cat:
                    n_unmapped += 1
                rows.append((nm, f"{nm}-{n}", dt, sku, prod, cat, channel))
        # cross-checks (dates always take precedence; mismatches are warned)
        for (n1, d1), (n2, d2) in zip(cust_seq, cust_seq[1:]):
            if n2 != n1 + 1:
                continue
            alias = f"{n1}th and {n2}th" if False else {1: "1st and 2nd", 2: "2nd and 3rd", 3: "3rd and 4th",
                                                         4: "4th and 5th", 5: "5th and 6th"}[n1]
            dj = days_j.get(alias)
            if dj is None:
                continue
            sv = parse_number(arr[i, dj])
            if sv is None:
                continue
            try:
                if int(round(float(sv))) != (d2 - d1).days:
                    n_days_mm += 1
            except (TypeError, ValueError):
                pass
        if depth_j is not None and cust_seq:
            dv = parse_number(arr[i, depth_j])
            if dv is not None:
                try:
                    depth = int(round(float(dv)))
                    observed = len(cust_seq)
                    if depth < observed or (depth != 6 and depth > observed):
                        n_depth_mm += 1
                except (TypeError, ValueError):
                    pass
    if not rows:
        rep.err("Journey base sheet: no parseable orders found.")
        return None
    d = pd.DataFrame(rows, columns=["customer_id", "order_id", "order_date", "sku", "product", "category", "channel"])
    d["quantity"] = np.nan
    if n_unmapped:
        rep.warnings.append(f"{n_unmapped:,} order lines could not be assigned a category from the order's "
                            f"category list — bucketed as (Uncategorized).")
    if n_days_mm:
        rep.warnings.append(f"{n_days_mm:,} 'days between' values disagree with the order dates (dates take precedence).")
    if n_depth_mm:
        rep.warnings.append(f"{n_depth_mm:,} customers have a 'Journey Depth' that disagrees with the parsed "
                            f"order count (dates take precedence; depth 6 means 6+).")
    rep.warnings.append("Base sheet scope: the first 6 orders per customer only (deeper journeys are capped). "
                        f"Channel is set to {channel} per the export title.")
    return _journey_common(d, rep)

# ===========================================================================
# NPS
# ===========================================================================
def build_nps_model(raw: pd.DataFrame, rep: SourceReport, colmap: dict, header_row: int):
    for req in ["brand_score", "product_score"]:
        if req not in colmap:
            rep.err("NPS requires brand and product score columns (e.g. 'NPS Score For Brand'). Missing.")
            return None
    body = _body(raw, header_row)

    def s(canon):
        j = colmap.get(canon)
        return body.iloc[:, j] if j is not None else pd.Series([""] * len(body), index=body.index)

    d = pd.DataFrame(index=body.index)
    d["created_at"] = s("created_at").map(parse_date) if "created_at" in colmap else None
    d["customer_id"] = s("customer_id").map(clean_str)
    d["category"] = s("category").map(clean_str)
    d["variant"] = s("variant").map(clean_str)
    d["age"] = s("age").map(parse_number)
    d["skin_type"] = s("skin_type").map(clean_str)
    d["hair_type"] = s("hair_type").map(clean_str)
    d["brand_score"] = s("brand_score").map(parse_number)
    d["product_score"] = s("product_score").map(parse_number)
    d["migrated_from"] = s("migrated_from").map(clean_str)
    for c in ["like_brand", "dislike_brand", "like_product", "dislike_product"]:
        d[c] = s(c).map(clean_str)

    n0 = len(d)
    bad = (d["brand_score"].notna() & ((d["brand_score"] < 0) | (d["brand_score"] > 10))) | \
          (d["product_score"].notna() & ((d["product_score"] < 0) | (d["product_score"] > 10)))
    if bad.any():
        rep.warnings.append(f"{int(bad.sum())} NPS scores outside 0–10 excluded.")
    d = d[~bad].dropna(subset=["brand_score", "product_score"])
    if len(d) < n0:
        rep.warnings.append(f"{n0 - len(d)} responses without valid scores excluded from NPS metrics.")
    d = d.reset_index(drop=True)
    d["brand_score"] = d["brand_score"].round().astype(int)
    d["product_score"] = d["product_score"].round().astype(int)
    bins = [0, 19, 25, 35, 45, 60, 200]
    labels = ["≤19", "20-25", "26-35", "36-45", "46-60", "60+"]
    d["age_bucket"] = pd.cut(d["age"], bins=bins, labels=labels).astype("object")
    d["skin_type_1"] = d["skin_type"].map(lambda v: split_multi(v)[0] if v else "")
    d["hair_type_1"] = d["hair_type"].map(lambda v: split_multi(v)[0] if v else "")
    d["is_first_time"] = d["migrated_from"].str.lower().str.contains("first", na=False)
    if d["created_at"].notna().any():
        rep.date_min = str(d["created_at"].min())
        rep.date_max = str(d["created_at"].max())
    rep.entities = {"Responses": int(len(d)),
                    "Categories": int(d["category"].replace("", np.nan).nunique()),
                    "Unique customers": int(d["customer_id"].replace("", np.nan).nunique())}

    def themes(col):
        rows = []
        for i, v in enumerate(d[col]):
            for t in split_multi(v):
                rows.append((i, t))
        return pd.DataFrame(rows, columns=["idx", "theme"]) if rows else pd.DataFrame(columns=["idx", "theme"])

    return {"df": d,
            "themes_like": themes("like_product"), "themes_dislike": themes("dislike_product"),
            "themes_like_brand": themes("like_brand"), "themes_dislike_brand": themes("dislike_brand"),
            "has_like_brand": bool(d["like_brand"].any()), "has_dislike_brand": bool(d["dislike_brand"].any()),
            "has_migrated": bool(d["migrated_from"].any()),
            "has_demos": {"age": bool(d["age"].notna().any()),
                          "skin_type": bool(d["skin_type_1"].ne("").any()),
                          "hair_type": bool(d["hair_type_1"].ne("").any())}}

# ===========================================================================
# CS FEEDBACK
# ===========================================================================
def build_cs_model(raw: pd.DataFrame, rep: SourceReport, colmap: dict, header_row: int):
    body = _body(raw, header_row)

    def s(canon):
        j = colmap.get(canon)
        return body.iloc[:, j] if j is not None else pd.Series([""] * len(body), index=body.index)

    d = pd.DataFrame(index=body.index)
    d["created_at"] = s("created_at").map(parse_date)
    for c in ["customer_name", "order_name", "chat_status", "provided_resolution",
              "failure_type", "failure_reason", "failure_subreason",
              "products_ordered", "products_impacted", "category", "responsible_team",
              "remarks", "global_remark", "city", "state"]:
        d[c] = s(c).map(clean_str)
    d["order_count"] = s("order_count").map(parse_number)
    ft = s("fulfilled_time").map(parse_datetime)
    dt_ = s("delivery_time").map(parse_datetime)
    try:
        hours = (dt_ - ft).dt.total_seconds() / 3600.0
        d["fulfil_hours"] = hours.where((hours > 0) & (hours < 24 * 60))
        bad = hours.notna() & ~((hours > 0) & (hours < 24 * 60))
        if bad.any():
            rep.warnings.append(f"{int(bad.sum())} tickets have missing/inconsistent fulfilment→delivery timestamps (shown as —).")
    except Exception:
        d["fulfil_hours"] = np.nan
    if d["created_at"].isna().all():
        rep.warnings.append("⚠ No parseable ticket dates — date filters disabled.")
    for c in ["failure_type", "failure_reason", "failure_subreason", "category"]:
        d.loc[d[c] == "", c] = "Unspecified"
    team_col_present = "responsible_team" in colmap
    team_empty = d["responsible_team"].eq("").all()
    if team_col_present and team_empty:
        rep.warnings.append("⚠ Responsible team field is empty in this export — team-level CS analysis unavailable.")
    elif not team_col_present:
        rep.warnings.append("⚠ Responsible team column not present in this export.")
    if d["created_at"].notna().any():
        rep.date_min = str(d["created_at"].min())
        rep.date_max = str(d["created_at"].max())
    rep.entities = {"Tickets": int(len(d)), "Failure types": int(d["failure_type"].nunique()),
                    "Categories": int(d["category"].replace("Unspecified", np.nan).nunique())}
    return {"df": d.reset_index(drop=True), "team_empty": team_empty, "team_present": team_col_present}

# ===========================================================================
# AOP (wide multi-block sheet)
# ===========================================================================
AOP_BLOCK_ORDER = [
    ("revenue", lambda s: s == "revenue"),
    ("spend", lambda s: s == "spend"),
    ("rev_share", lambda s: "revenue" in s and "share" in s),
    ("spend_share", lambda s: "spend" in s and "share" in s),
    ("roas", lambda s: "roas" in s),
    ("mom_growth_rev", lambda s: "growth" in s and "revenue" in s),
    ("mom_growth_spend", lambda s: "growth" in s and "spend" in s),
    ("growth_gap", lambda s: "gap" in s),
    ("cqgr", lambda s: "cqgr" in s),
    ("fy_12m_cmgr", lambda s: "12-m" in s or "12m" in s),
    ("fy_6m_cmgr", lambda s: "6-m" in s or "6m" in s),
    ("yoy_quarter", lambda s: "yoy" in s or re.match(r"^q1.*vs.*q1", s)),
    ("seasonal", lambda s: "seasonal" in s),
]

def classify_aop_block(label: str):
    s = label.lower()
    for name, fn in AOP_BLOCK_ORDER:
        if fn(s):
            return name
    if re.match(r"^\d{4}\s*-\s*\d{4}$", s.strip()):
        return "fy"
    return None

def build_aop_model(raw: pd.DataFrame, rep: SourceReport):
    """Wide AOP sheet: row0 = block labels, row1 = meta names + month labels, rows+ = data.
    Parsed by block labels (never fixed column counts) into a long analytical model."""
    # locate meta row: first row whose first cell looks like 'SD Category'
    meta_row_i = None
    for i in range(min(5, len(raw))):
        first = str(raw.iloc[i, 0]).strip().lower()
        if "sd" in first and "categor" in first:
            meta_row_i = i
            break
    if meta_row_i is None:
        rep.err("Could not locate the AOP header (expected an 'SD Category' column). Check that this is the AOP export.")
        return None
    label_row_i = meta_row_i - 1
    ncol = raw.shape[1]
    label_row = [str(x).strip() for x in raw.iloc[label_row_i].tolist()] if label_row_i >= 0 else [""] * ncol
    meta_row = [str(x).strip() for x in raw.iloc[meta_row_i].tolist()]
    data = raw.iloc[meta_row_i + 1:].reset_index(drop=True)

    # meta columns = CONTIGUOUS prefix with a non-empty meta name and empty block label
    meta_cols = []
    for j in range(ncol):
        lab = label_row[j] if j < len(label_row) else ""
        m = meta_row[j] if j < len(meta_row) else ""
        if lab:
            break
        if m:
            meta_cols.append((j, m))
    if not meta_cols:
        rep.err("No metadata columns found in the AOP header.")
        return None
    meta_names = [m for _, m in meta_cols]
    meta_df = data[[j for j, _ in meta_cols]].copy()
    meta_df.columns = meta_names
    meta_df = meta_df.reset_index(drop=True)

    # blocks: non-empty cells in the label row start a block
    block_starts = [(str(x).strip(), j) for j, x in enumerate(label_row) if str(x).strip()]
    blocks = []
    for k, (lab, j) in enumerate(block_starts):
        end = block_starts[k + 1][1] - 1 if k + 1 < len(block_starts) else ncol - 1
        blocks.append((lab, j, end))

    long_rows = []
    fy_rows = []
    seasonal_rows = []
    singles = []
    months_seen = set()
    for lab, j0, j1 in blocks:
        kind = classify_aop_block(lab)
        hdrs = [meta_row[j] if j < len(meta_row) else "" for j in range(j0, j1 + 1)]
        if kind in ("fy_12m_cmgr", "fy_6m_cmgr", "yoy_quarter"):
            name = hdrs[0] if hdrs[0] else lab
            vals = [parse_number(v) for v in data.iloc[:, j0].tolist()[: len(data)]]
            singles.append({"kind": kind, "label": name, "values": pd.Series(vals).to_numpy()})
            continue
        if kind == "fy":
            names = [h if h else f"col{j0+k}" for k, h in enumerate(hdrs)]
            vals = data.iloc[:, j0:j1 + 1].values
            for r_i in range(len(data)):
                fy_rows.append({n: parse_number(vals[r_i, k]) for k, n in enumerate(names)} | {"fy": lab})
            continue
        if kind == "seasonal":
            names = [h if h else f"col{j0+k}" for k, h in enumerate(hdrs)]
            vals = data.iloc[:, j0:j1 + 1].values
            for r_i in range(len(data)):
                seasonal_rows.append({n: parse_number(vals[r_i, k]) for k, n in enumerate(names)})
            continue
        if kind is None:
            rep.warnings.append(f"⚠ Unknown AOP block {lab!r} (cols {j0}-{j1}) — skipped.")
            continue
        month_cols = {}
        for k in range(j1 - j0 + 1):
            mk = parse_month_label(hdrs[k])
            if mk:
                month_cols[j0 + k] = mk
        if not month_cols:
            # quarterly-labelled block (e.g. CQGR): keep quarter labels as-is
            qcols = [(j0 + k, hdrs[k].strip()) for k in range(j1 - j0 + 1)
                     if re.match(r"^q\d\s*\d{4}$", hdrs[k].strip(), re.I)]
            if qcols:
                arr = data.iloc[:, [c for c, _ in qcols]].values
                for r_i in range(len(data)):
                    for c_pos, (cj, ql) in enumerate(qcols):
                        long_rows.append({"_kind": "cqgr", "_meta_i": r_i,
                                          "month": ql.lower(), "value": parse_pct(arr[r_i, c_pos])})
                continue
            rep.warnings.append(f"⚠ AOP block {lab!r} has no parseable month headers — skipped.")
            continue
        months_seen.update(month_cols.values())
        is_pct = kind in ("rev_share", "spend_share", "mom_growth_rev", "mom_growth_spend", "growth_gap")
        arr = data.iloc[:, list(month_cols.keys())].values
        for r_i in range(len(data)):
            for c_pos, cj in enumerate(month_cols):
                v = parse_pct(arr[r_i, c_pos]) if is_pct else parse_number(arr[r_i, c_pos])
                long_rows.append({"_kind": kind, "_meta_i": r_i, "month": month_cols[cj], "value": v})

    long_df = pd.DataFrame(long_rows)
    if len(long_df):
        long_df = long_df.merge(meta_df.assign(_meta_i=meta_df.index), on="_meta_i", how="left")
        long_df = long_df.drop(columns=["_meta_i"]).rename(columns={"_kind": "block"})
    else:
        long_df = pd.DataFrame(columns=["block", "month", "value"] + meta_names)

    fy = pd.DataFrame(fy_rows).reset_index(drop=True)
    if len(fy):
        fy = fy.merge(meta_df.assign(_i=meta_df.index), left_index=True, right_on="_i", how="left").drop(columns=["_i"])
    seasonal = pd.DataFrame(seasonal_rows).reset_index(drop=True)
    if len(seasonal):
        seasonal = seasonal.merge(meta_df.assign(_i=meta_df.index), left_index=True, right_on="_i", how="left").drop(columns=["_i"])

    months = sorted(months_seen)
    cat_col = next((c for c in meta_names if "categor" in c.lower() and "sd" not in c.lower()), None)
    ch_col = next((c for c in meta_names if "channel" in c.lower()), None)
    total_rows = 0
    if ch_col:
        total_rows = int((meta_df[ch_col].astype(str).str.upper().str.strip() == "TOTAL").sum())
    if total_rows == 0:
        rep.warnings.append("⚠ No 'TOTAL' channel rows found in AOP — category totals will be summed from channel rows (verify no double counting).")
    if len(fy) and cat_col:
        unlabeled = []
        for fyv in fy["fy"].unique():
            cv = fy.loc[fy["fy"] == fyv, cat_col]
            if cv.isna().all() or cv.astype(str).str.strip().eq("").all():
                unlabeled.append(str(fyv))
        if unlabeled:
            rep.warnings.append("FY summary block(s) " + ", ".join(unlabeled)
                                + " in the AOP export carry no category/channel labels and are excluded from the FY table.")
    rep.row_count = int(len(meta_df))
    rep.date_min = months[0] if months else ""
    rep.date_max = months[-1] if months else ""
    rep.entities = {"Lines": int(len(meta_df)),
                    "Categories": int(meta_df[cat_col].nunique()) if cat_col else 0,
                    "Channel subs": int(meta_df[ch_col].nunique()) if ch_col else 0,
                    "Months": len(months)}
    return {"long": long_df, "meta": meta_df, "fy": fy, "seasonal": seasonal, "singles": singles,
            "months": months, "meta_names": meta_names, "total_row_found": total_rows > 0,
            "category_col": cat_col, "channel_sub_col": ch_col}

# ===========================================================================
# RETENTION FM (+ price-revision lookup block)
# ===========================================================================
_WINDOW_RE = re.compile(r"^(\d{2,3})\s*days?\s*%?\s*$", re.I)
_PRICE_NOTE_RE = re.compile(r"(decreased|increased|same)\s*-?\s*price\s*revision\s*[-–—]?\s*(.*)", re.I)
_DATE_ORD_RE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+),?\s+(\d{4})")
_NEW_VAR_RE = re.compile(r"new\s+.*variant\s+launch", re.I)

def parse_price_note(note: str):
    s = clean_str(note)
    if not s or s.upper() == "#REF!":
        return None, None, s
    if _NEW_VAR_RE.search(s):
        return "New Variant", None, s
    m = _PRICE_NOTE_RE.search(s)
    if m:
        typ = m.group(1).capitalize() + " Price"
        dm = _DATE_ORD_RE.search(clean_str(m.group(2)))
        d = None
        if dm:
            d = parse_date(f"{dm.group(1)} {dm.group(2)}, {dm.group(3)}")
        return typ, d, s
    low = s.lower()
    if "increas" in low:
        return "Increased Price", None, s
    if "decreas" in low:
        return "Decreased Price", None, s
    if "same" in low:
        return "Same Price", None, s
    return "Other", None, s

def build_retention_fm_model(raw: pd.DataFrame, rep: SourceReport, colmap: dict, header_row: int):
    from sources import _norm_name
    hdr = [clean_str(x) for x in raw.iloc[header_row].tolist()]
    body = _body(raw, header_row)

    win_cols = {}
    for j, h in enumerate(hdr):
        m = _WINDOW_RE.match(h.strip())
        if m:
            win_cols[j] = int(m.group(1))
    if not win_cols:
        rep.err("No retention window columns found (e.g. '30 Days %').")
        return None

    def getcol(name):
        for j, h in enumerate(hdr):
            if _norm_name(h) == _norm_name(name):
                return j
        return None

    j_onb = getcol("product onb date")
    j_cat = getcol("product category")
    j_sku = getcol("sku")
    j_note = getcol("lookup price thing")
    j_var = getcol("short code")
    j_ch = getcol("channel")
    j_cust = getcol("customer")
    if j_onb is None or j_sku is None or j_cust is None:
        rep.err(f"Retention FM needs 'product_onb_date', 'sku' and 'Customer' columns (found: onb={j_onb is not None}, sku={j_sku is not None}, customer={j_cust is not None}).")
        return None

    rows = []
    price_refs = {}
    total_row = None
    for i in range(len(body)):
        r = body.iloc[i]
        sku = clean_str(r[j_sku])
        cust = parse_number(r[j_cust])
        if sku == "":
            if not np.isnan(cust):
                total_row = cust
            continue
        onb = parse_date(r[j_onb])
        if onb is None:
            rep.warnings.append(f"Row {i + 2}: unparseable onboarding date — row skipped.")
            continue
        note = clean_str(r[j_note]) if j_note is not None else ""
        ctype, cdate, _ = parse_price_note(note)
        row = {
            "onb_date": onb, "cohort_month": month_of(onb),
            "category": clean_str(r[j_cat]) if j_cat is not None else "",
            "sku": sku,
            "variant": clean_str(r[j_var]) if j_var is not None else "",
            "channel": clean_str(r[j_ch]) if j_ch is not None else "",
            "customers": cust, "price_note": note,
            "price_type": ctype, "price_date": cdate,
        }
        for j, w in win_cols.items():
            # FM sheet stores %-numbers (0.54 means 0.54%); column names carry '%'
            row[f"w{w}"] = (parse_number(r[j]) / 100.0) if "%" in hdr[j] else parse_number(r[j])
        rows.append(row)
        if ctype and sku not in price_refs:
            price_refs[sku] = {"sku": sku, "product": clean_str(r[j_var]) if j_var is not None else "",
                               "change_type": ctype, "date": cdate, "note": note,
                               "scope": "", "season": ""}
    if not rows:
        rep.err("No retention data rows found in the main block.")
        return None
    rt = pd.DataFrame(rows)
    rt.loc[rt["category"] == "", "category"] = "(Uncategorized)"

    # right-side lookup block: a 2nd 'sku' header after the main block
    sku_positions = [j for j, h in enumerate(hdr) if h.strip().lower() == "sku"]
    if len(sku_positions) >= 2:
        ls = sku_positions[1]
        for i in range(len(body)):
            r = body.iloc[i]
            sku = clean_str(r[ls])
            if not sku:
                continue
            prod = clean_str(r[ls + 1]) if ls + 1 < len(hdr) else ""
            note = clean_str(r[ls + 2]) if ls + 2 < len(hdr) else ""
            scope = clean_str(r[ls + 3]) if ls + 3 < len(hdr) else ""
            season = clean_str(r[ls + 4]) if ls + 4 < len(hdr) else ""
            ctype, cdate, _ = parse_price_note(note)
            p = price_refs.get(sku, {"sku": sku, "product": "", "change_type": None, "date": None,
                                     "note": "", "scope": "", "season": ""})
            p["product"] = p.get("product") or prod
            p["change_type"] = p.get("change_type") or ctype
            p["date"] = p.get("date") or cdate
            p["note"] = p.get("note") or note
            p["scope"] = scope or p.get("scope", "")
            p["season"] = season or p.get("season", "")
            price_refs[sku] = p

    price = pd.DataFrame(price_refs.values())
    if len(price):
        price = price[["sku", "product", "change_type", "date", "note", "scope", "season"]].fillna("")
    else:
        price = pd.DataFrame(columns=["sku", "product", "change_type", "date", "note", "scope", "season"])
    if total_row is not None:
        rep.warnings.append(f"ℹ Sheet total row shows {total_row:,.0f} customers; SKU cohorts sum to {rt['customers'].sum():,.0f}. SKU-level rows are used for calculations.")
    rep.date_min = str(rt["onb_date"].min())
    rep.date_max = str(rt["onb_date"].max())
    rep.entities = {"SKUs": int(rt["sku"].nunique()), "Cohort months": int(rt["cohort_month"].nunique()),
                    "Customers": int(rt["customers"].sum())}
    return {"df": rt, "windows": sorted(win_cols.values()), "price": price, "total_customers": total_row}

# ===========================================================================
# NEW-TO-CATEGORY ORDER MOVEMENT
# ===========================================================================
def build_order_movement_model(raw: pd.DataFrame, rep: SourceReport, colmap: dict, header_row: int):
    hdr = [clean_str(x) for x in raw.iloc[header_row].tolist()]
    body = _body(raw, header_row)

    from sources import _norm_name
    def pos(name):
        for j, h in enumerate(hdr):
            if _norm_name(h) == _norm_name(name):
                return j
        return None

    name2canon = {"first order": "first_order", "sec order": "sec_order", "sec pct": "sec_pct",
                  "avg days to sec": "avg_days_to_sec", "third order": "third_order", "third pct": "third_pct",
                  "avg days to third": "avg_days_to_third", "fourth order": "fourth_order", "fourth pct": "fourth_pct",
                  "avg days to fourth": "avg_days_to_fourth", "fifth order": "fifth_order", "fifth pct": "fifth_pct",
                  "avg days to fifth": "avg_days_to_fifth", "sixth order": "sixth_order", "sixth pct": "sixth_pct",
                  "avg days to sixth": "avg_days_to_sixth"}
    names = list(name2canon.keys())
    specs = [(name2canon[n], pos(n)) for n in names]
    j_c = pos("onb month")
    missing = [name2canon[n] for n, (_, j) in zip(names, specs) if j is None]
    if j_c is None or missing:
        rep.err(f"Order-movement file missing expected column(s): {missing or 'onb_month'}.")
        return None

    rows = []
    for i in range(len(body)):
        r = body.iloc[i]
        cm = parse_month_label(r[j_c]) or month_of(parse_date(r[j_c]))
        if cm is None:
            continue
        row = {"cohort": cm}
        for k, j in specs:
            row[k] = parse_pct(r[j]) if k.endswith("_pct") else parse_number(r[j])
        rows.append(row)
    d = pd.DataFrame(rows)
    if not len(d):
        rep.err("No cohort rows parsed from the order-movement file.")
        return None
    n_recomp = 0
    for pre, pc in [("sec", "sec_pct"), ("third", "third_pct"), ("fourth", "fourth_pct"),
                    ("fifth", "fifth_pct"), ("sixth", "sixth_pct")]:
        cnt = f"{pre}_order"
        if cnt not in d.columns or d[cnt].isna().all():
            continue
        both = d[cnt].notna() & (d[cnt] > 0) & d["first_order"].notna() & (d["first_order"] > 0) & d[pc].notna()
        calc = d[cnt] / d["first_order"]
        n_recomp += int((both & ((calc - d[pc]).abs() > 0.02)).sum())
        d.loc[both, pc] = calc[both]
    if n_recomp:
        rep.warnings.append(f"ℹ {n_recomp} cohort percentage cells were recomputed from order counts (stored % differed by >2pp).")

    as_of = None
    for i in range(min(3, header_row)):
        ts = parse_datetime(str(raw.iloc[i, 0]))
        if ts and re.match(r"^\d{4}-\d{2}-\d{2}", clean_str(raw.iloc[i, 0])):
            as_of = ts.date()
            break
    if as_of is None:
        as_of = max(parse_date(c + "-28") for c in d["cohort"])
        rep.warnings.append("⚠ No export timestamp found in the file — cohort maturity is measured from the latest cohort month (results may overstate maturity).")
    rep.date_min = str(d["cohort"].min())
    rep.date_max = str(d["cohort"].max())
    rep.entities = {"Cohorts": int(len(d)), "New customers": int(d["first_order"].fillna(0).sum())}
    return {"df": d, "as_of": as_of}

# ===========================================================================
# MIGRATION / SEASONALITY SUMMARY SHEET (multi-block aggregate)
# ===========================================================================
def build_migr_seasonality_model(raw: pd.DataFrame, rep: SourceReport):
    """Parses the blocks of the 'Seasonality & Intra Category Migration' summary sheet.
    Blocks are located by their structural headers, not by position in the file."""
    def cell(i, j):
        return _cell(raw, i, j)
    nrows, ncols = len(raw), raw.shape[1]
    out = {"conclusions": []}

    # ---- Block 1: variant seasonality
    for i in range(nrows):
        if cell(i, 0) == "Variant Key":
            hdr = [cell(i, j) for j in range(ncols)]
            if "Total" in hdr and "Peak Season" in hdr:
                skip = {"", "Variant Key", "Total", "Peak Season", "Intended Season", "Season Match?", "Seasonality Strength"}
                season_cols = [j for j in range(ncols) if hdr[j] not in skip and not hdr[j].startswith("Avg Purchase Gap")]
                j_tot = hdr.index("Total")
                j_peak = hdr.index("Peak Season")
                j_gap = next(j for j, h in enumerate(hdr) if h.startswith("Avg Purchase Gap"))
                j_int = hdr.index("Intended Season")
                j_match = hdr.index("Season Match?")
                j_str = hdr.index("Seasonality Strength")
                rows = []
                for r in range(i + 1, nrows):
                    k = cell(r, 0)
                    if k == "":
                        break
                    rows.append({
                        "variant": k,
                        **{hdr[j]: parse_number(cell(r, j)) for j in season_cols},
                        "total_orders": parse_number(cell(r, j_tot)),
                        "peak_season": cell(r, j_peak),
                        "avg_purchase_gap_days": parse_number(cell(r, j_gap)),
                        "intended_season": cell(r, j_int),
                        "season_match": cell(r, j_match),
                        "seasonality_strength": cell(r, j_str),
                    })
                out["seasonality"] = pd.DataFrame(rows)
                break

    # ---- Block 2: V2V/V2C loyalty
    for i in range(nrows):
        if cell(i, 0) == "Variant Key":
            hdr = [cell(i, j) for j in range(ncols)]
            if "V2V Loyalty" in hdr:
                keep = ["V2V Loyalty", "V2C Loyalty", "Avg Purchase Days V2V", "Most Common 2nd order V2V",
                        "Avg Order Count V2V", "Avg Purchase Days V2C", "Most Common 2nd order V2C", "Avg Order Count V2C",
                        "Peak Season", "Intended Season", "Total"]
                rows = []
                for r in range(i + 1, nrows):
                    k = cell(r, 0)
                    if k == "":
                        break
                    row = {"variant": k}
                    for h in keep:
                        if h in hdr:
                            v = cell(r, hdr.index(h))
                            row[h] = v if h.startswith("Most Common") else parse_number(v)
                    rows.append(row)
                out["v2v_v2c_sheet"] = pd.DataFrame(rows)
                break
    if "v2v_v2c_sheet" in out and (out["v2v_v2c_sheet"]["V2V Loyalty"].isna().all() if len(out["v2v_v2c_sheet"]) else True):
        rep.warnings.append("⚠ The V2V/V2C loyalty block in the summary sheet is empty (formula errors / not populated) — variant-loyalty from this sheet is unavailable; use the Journey source for computed V2V/V2C.")

    # ---- Block 3: grammage transitions
    for i in range(nrows):
        if cell(i, 0) == "Starting Point" and i + 1 < nrows:
            sub = [cell(i + 1, j) for j in range(ncols)]
            if "Pack Size" in sub and "Repeat %" in sub:
                hdr = sub
                j = {h: hdr.index(h) for h in ["Category", "Pack Size", "Entry Grammage Context",
                                                "Total Next Purchases", "Repeated Exact Same Product",
                                                "Repeated Same Size (Any Variant)", "Repeat %",
                                                "Upsized To (Count)", "Upsized To (Destination)", "Upsize %",
                                                "Lateral Switch (Count)", "Lateral Switch (Destination)",
                                                "Downsized To (Count)", "Downsized To (Destination)", "Downsize %",
                                                "Dominant Next Move", "Retention Signal", "Upsize Opportunity", "Risk Flag"] if h in hdr}
                rows = []
                for r in range(i + 2, nrows):
                    k = cell(r, 0)
                    if k == "":
                        break
                    row = {"category": k, "pack_size": cell(r, j["Pack Size"])}
                    for h, jj in j.items():
                        if h == "Category":
                            continue
                        v = cell(r, jj)
                        if h in ("Repeat %", "Upsize %", "Downsize %"):
                            row[h] = parse_pct(v)
                        elif h in ("Total Next Purchases", "Repeated Exact Same Product", "Repeated Same Size (Any Variant)",
                                   "Upsized To (Count)", "Lateral Switch (Count)", "Downsized To (Count)"):
                            row[h] = parse_number(v)
                        else:
                            row[h] = v
                    rows.append(row)
                out["grammage"] = pd.DataFrame(rows)
                break

    # ---- quarterly upsize/downsize detail
    qrows = []
    for i in range(nrows):
        rowcells = [cell(i, j) for j in range(ncols)]
        if any(re.search(r"50G FACE MALAI", c, re.I) or re.search(r"30G FACE MALAI", c, re.I) for c in rowcells):
            for r in range(i + 1, nrows):
                size = cell(r, 0)
                if size == "":
                    break
                qrows.append({"pack_size": size, "period": cell(r, 1),
                              "total_next": parse_number(cell(r, 2)),
                              "repeated_same": parse_number(cell(r, 3)),
                              "moved": parse_number(cell(r, 4)),
                              "repeat_pct": parse_pct(cell(r, 5)),
                              "move_pct": parse_pct(cell(r, 6))})
            out["quarterly_moves"] = pd.DataFrame(qrows)
            break

    # ---- Block 4: order-frequency
    for i in range(nrows):
        if cell(i, 0) == "Starting Point" and i + 1 < nrows:
            sub = [cell(i + 1, j) for j in range(ncols)]
            if any(h.startswith("Unique Users") for h in sub):
                hdr = sub
                def jj(prefix):
                    return next((hdr.index(h) for h in hdr if h.startswith(prefix)), None)
                j_cat = next((k for k, h in enumerate(hdr) if h == "Category"), 0)
                j_var = next((k for k, h in enumerate(hdr) if h == "Variant"), 1)
                rows = []
                for r in range(i + 2, nrows):
                    k = cell(r, j_cat)
                    if k == "":
                        break
                    def num(prefix):
                        idx = jj(prefix)
                        return parse_number(cell(r, idx)) if idx is not None else np.nan
                    def txt(prefix):
                        idx = jj(prefix)
                        return cell(r, idx) if idx is not None else ""
                    pct_cell = txt("Drop Off %")
                    rows.append({
                        "category": k, "variant": cell(r, j_var),
                        "unique_users": num("Unique Users"),
                        "bought_once": num("Bought Once"),
                        "bought_twice": num("Bought Twice"),
                        "loyal_3_4": num("Mid Loyal"),
                        "loyal_5_6": num("High Loyal"),
                        "dropoff_pct": parse_pct(pct_cell) if pct_cell and not is_blank(pct_cell) else np.nan,
                        "dropoff_text": pct_cell,
                        "avg_days_1_2": num("Avg Days 1"),
                        "avg_days_2_3": num("Avg Days 2"),
                        "avg_gap": num("Overall Avg Gap"),
                        "retention_score_pct": parse_pct(txt("Retention Score")),
                    })
                out["order_freq"] = pd.DataFrame(rows)
                break

    # ---- conclusions
    for i in range(nrows):
        if cell(i, 0) == "CONCLUSION":
            j = i + 1
            empty_streak = 0
            while j < nrows:
                q, a = cell(j, 0), cell(j, 1)
                if q:
                    out["conclusions"].append((q, a))
                    empty_streak = 0
                else:
                    empty_streak += 1
                    if empty_streak > 2:
                        break
                j += 1
            break

    found = [k for k in out if k != "conclusions" and isinstance(out[k], pd.DataFrame) and len(out[k])]
    rep.entities = {k: int(len(out[k])) for k in found}
    if not found:
        rep.warnings.append("⚠ No recognizable blocks found in the summary sheet (layout may have changed).")
    return out
