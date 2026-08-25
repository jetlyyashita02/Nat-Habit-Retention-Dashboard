"""
Data-source loaders (robust build).
Every loader accepts a CSV in *any reasonable spelling* of the expected sheet:
renamed / reordered / extra columns, shifted headers, mixed date formats,
₹/comma/%/Cr-L numbers — and always outputs the same canonical schema.
Warnings about any fuzzy fallback are attached to df.attrs["warnings"].
"""
from __future__ import annotations

import io
import pathlib
import re

import pandas as pd

import robust as R


def _read(src):
    if isinstance(src, bytes):
        return pd.read_csv(io.BytesIO(src))
    return pd.read_csv(src)


# ------------------------------------------------------------------ sales
def load_sales(src) -> pd.DataFrame:
    raw = _read(src)
    raw.columns = [str(c).strip() for c in raw.columns]
    w = []
    i_date = R.find_col(raw.columns, ["order_date", "date", "order date", "created_at",
                                      "created", "purchase date"])
    i_sku = R.find_col(raw.columns, ["sku", "sku code", "sku_code"])
    i_name = R.find_col(raw.columns, ["short_code", "short code", "product", "product name",
                                      "variant", "item"], contains=True)
    i_cat = R.find_col(raw.columns, ["product_category", "category", "product category"])
    i_chan = R.find_col(raw.columns, ["order_source", "channel", "source", "platform"])
    i_ord = R.find_col(raw.columns, ["orders", "order count", "no of orders", "num orders"])
    i_cust = R.find_col(raw.columns, ["customers", "customer count", "unique customers"])
    i_qty = R.find_col(raw.columns, ["qty", "quantity", "units", "units sold"])
    i_rev = R.find_col(raw.columns, ["rev", "revenue", "sales", "amount", "gmv"],
                       contains=True)
    missing = [lbl for lbl, i in [("date", i_date), ("sku", i_sku), ("revenue", i_rev)] if i is None]
    if missing:
        raise ValueError(f"Sales sheet: could not find column(s) {missing}. "
                         f"Found: {list(raw.columns)}")

    def col(i, default=None):
        return raw.iloc[:, i] if i is not None else default

    n = len(raw)
    orders = R.flex_num(col(i_ord, pd.Series([1] * n)))
    df = pd.DataFrame({
        "order_date": R.flex_dates(
            col(i_date),
            dayfirst=R.load_config()["dayfirst"].get("sales", True)),
        "sku": col(i_sku).astype(str).str.strip(),
        "product": (col(i_name, col(i_sku)).astype(str).str.strip()),
        "category": (col(i_cat, pd.Series(["Unknown"] * n)).astype(str).str.strip()),
        "channel": (col(i_chan, pd.Series(["Unknown"] * n)).astype(str).str.strip()),
        "orders": orders.fillna(1),
        "customers": (R.flex_num(col(i_cust, orders)).fillna(orders)),
        "qty": R.flex_num(col(i_qty, orders)).fillna(orders),
        "rev": R.flex_num(col(i_rev)),
    })
    df = df[df["order_date"].notna() & df["rev"].notna()].copy()
    df["month"] = df["order_date"].dt.to_period("M").astype(str)
    df["unit_price"] = df["rev"] / df["qty"].replace(0, pd.NA)
    for lbl, i, dflt in [("product name", i_name, "sku code"), ("category", i_cat, None),
                         ("channel", i_chan, None), ("orders", i_ord, None),
                         ("customers", i_cust, "orders"), ("qty", i_qty, "orders")]:
        if i is None and dflt is not None:
            R.warn(df, f"Sales: '{lbl}' column not found — defaulted to {dflt}.", w)
    return R.attach(df, w)


# ------------------------------------------------------------------ NPS raw
def load_nps(src) -> pd.DataFrame:
    df = _read(src)
    df.columns = [str(c).strip() for c in df.columns]
    w = []
    i_created = R.find_col(df.columns, ["created_at", "date", "submitted", "response date"])
    i_brand = R.find_col(df.columns, ["nps score for brand", "brand nps", "nps brand"],
                         contains=True)
    i_prod = R.find_col(df.columns, ["nps score for product", "product nps"],
                        contains=True)
    ren = {}
    if i_created is not None:
        ren[df.columns[i_created]] = "created_at"
    if i_brand is not None:
        ren[df.columns[i_brand]] = "NPS Score For Brand"
    if i_prod is not None:
        ren[df.columns[i_prod]] = "NPS Score For Product"
    if ren:
        df = df.rename(columns=ren)
        got = set(ren.values())
        want = {"created_at", "NPS Score For Brand"}
        if not want.issubset(got | set(df.columns)):
            R.warn(df, f"NPS: fuzzy-mapped columns {list(ren.items())}", w)
    if "created_at" in df:
        df["created_at"] = R.flex_dates(
            df["created_at"], dayfirst=R.load_config()["dayfirst"].get("nps", True))
    for c in ["NPS Score For Brand", "NPS Score For Product", "age"]:
        if c in df:
            df[c] = R.flex_num(df[c])

    def split_multi(col):
        if col not in df:
            return pd.Series([[]] * len(df), index=df.index)
        return df[col].fillna("").astype(str).apply(
            lambda s: [x.strip() for x in re.split(r"[|;,/]", s) if x.strip()
                       and x.strip().lower() not in ("nan", "")])

    like_c = R.find_col(df.columns, ["what do you like about nat habit", "like product",
                                     "likes", "what do you like"], contains=True)
    dis_c = R.find_col(df.columns, ["what do you not like about nat habit",
                                    "not like product", "dislikes",
                                    "what do you not like"], contains=True)
    likes = pd.Series([[]] * len(df), index=df.index)
    dis = likes.copy()
    like_cols = [c for c in df.columns
                 if like_c is not None and (c == df.columns[like_c])
                 or (isinstance(c, str) and ("like" in c.lower() and "not" not in c.lower()))]
    dis_cols = [c for c in df.columns
                if isinstance(c, str) and "not like" in c.lower()]
    for c in like_cols:
        likes = likes + split_multi(c)
    for c in dis_cols:
        dis = dis + split_multi(c)
    df["_likes"], df["_dislikes"] = likes, dis
    if not len(like_cols):
        R.warn(df, "NPS: no like/dislike columns found — driver charts will be empty.", w)
    return R.attach(df, w)


def nps_score(scores: pd.Series):
    s = scores.dropna()
    if not len(s):
        return None
    return round(100 * ((s >= 9).mean() - (s <= 6).mean()), 1)


# ------------------------------------------------------------------ CS FB
def load_cs(src) -> pd.DataFrame:
    df = _read(src)
    df.columns = [str(c).strip() for c in df.columns]
    w = []
    i_created = R.find_col(df.columns, ["created_at", "ticket date", "date"])
    i_ful = R.find_col(df.columns, ["fulfilled_time", "fulfil"], contains=True)
    i_del = R.find_col(df.columns, ["delivery_time", "deliver"], contains=True)
    if i_created is not None:
        df["created_at_dt"] = R.flex_dates(
            df.iloc[:, i_created],
            dayfirst=R.load_config()["dayfirst"].get("cs", True))
    for i, name in [(i_ful, "fulfilled_time_dt"), (i_del, "delivery_time_dt")]:
        if i is not None:
            df[name] = R.flex_dates(df.iloc[:, i], dayfirst=False)
    if "created_at_dt" in df and "delivery_time_dt" in df:
        df["ship_hours"] = ((df["delivery_time_dt"] - df["created_at_dt"])
                            .dt.total_seconds() / 3600)
    return R.attach(df, w)


# ------------------------------------------------------------------ AOP
def load_aop(src) -> dict:
    if isinstance(src, (str, pathlib.Path)):
        raw = pd.read_csv(src, header=None)
    else:
        raw = pd.read_csv(io.BytesIO(src) if isinstance(src, (bytes, bytearray))
                          else src, header=None)
    w = []

    # header row = row with the most month-like cells; block row = the row above
    hdr_row = max(range(min(8, len(raw))),
                  key=lambda i: sum(1 for v in raw.iloc[i] if R.month_label(v)))
    if sum(1 for v in raw.iloc[hdr_row] if R.month_label(v)) < 6:
        raise ValueError("AOP sheet: couldn't find a header row of month labels "
                         f"(scanned first {min(8, len(raw))} rows).")
    block_row = hdr_row - 1 if hdr_row > 0 else None

    # descriptor span = columns before the first month-labelled header cell
    hdr = raw.iloc[hdr_row].tolist()
    first_month_col = next(i for i, v in enumerate(hdr) if R.month_label(v))
    meta_cols = list(range(first_month_col))
    meta = raw.iloc[hdr_row + 1:, meta_cols].copy()
    meta.columns = [str(x).strip() for x in raw.iloc[hdr_row, meta_cols]]
    meta = meta.reset_index(drop=True)

    # block spans: contiguous runs of month columns sharing one ffilled label
    labels = (raw.iloc[block_row].ffill() if block_row is not None
              else pd.Series([None] * raw.shape[1]))
    month_blocks = {}
    runs = []
    cur_lab, cur = None, []
    for i in range(first_month_col, raw.shape[1]):
        lab = labels.iloc[i] if pd.notna(labels.iloc[i]) else None
        m = R.month_label(hdr[i])
        if lab != cur_lab:
            if len(cur) >= 3:
                runs.append((str(cur_lab).strip() if cur_lab else None, cur))
            cur_lab, cur = lab, []
        if m:
            cur.append((i, m))
    if len(cur) >= 3:
        runs.append((str(cur_lab).strip() if cur_lab else None, cur))
    for lab, cols in runs:
        if lab is None:
            continue
        if lab in month_blocks:                      # longest run wins
            if len(cols) > len(month_blocks[lab][0]):
                month_blocks[lab] = ([i for i, _ in cols], [m for _, m in cols])
        else:
            month_blocks[lab] = ([i for i, _ in cols], [m for _, m in cols])

    # positional fallback if labels absent / unreadable
    if not any(k in month_blocks for k in ("Revenue", "Spend")):
        month_cols = [i for i, v in enumerate(hdr) if R.month_label(v)]
        groups, cur = [], [month_cols[0]]
        for a, b in zip(month_cols, month_cols[1:]):
            if b - a <= 2:
                cur.append(b)
            else:
                groups.append(cur); cur = [b]
        groups.append(cur)
        if len(groups) >= 2:
            month_blocks["Revenue"] = (groups[0], [R.month_label(hdr[i]) for i in groups[0]])
            month_blocks["Spend"] = (groups[1], [R.month_label(hdr[i]) for i in groups[1]])
            w.append("AOP: block labels unreadable — first two monthly blocks "
                     "assumed to be Revenue and Spend positionally.")
    if "Revenue" not in month_blocks or "Spend" not in month_blocks:
        raise ValueError("AOP sheet: could not identify Revenue/Spend blocks. "
                         "Ensure the block-label row sits directly above the months.")

    def melt(name):
        cols, months = month_blocks[name]
        block = raw.iloc[hdr_row + 1:, cols].reset_index(drop=True)
        block.columns = months
        long = block.melt(var_name="month", value_name="value")
        long["value"] = R.flex_num(long["value"])
        tiled = pd.concat([meta] * len(months), ignore_index=True).iloc[:len(long)]
        out = pd.concat([tiled, long.reset_index(drop=True)], axis=1)
        return out[out["month"].notna()]

    rev, spend = melt("Revenue"), melt("Spend")
    roas = (melt("ROAS") if "ROAS" in month_blocks else pd.DataFrame())
    revshare = (melt("Revenue Share %") if "Revenue Share %" in month_blocks
                else pd.DataFrame())
    return {"meta_cols": list(meta.columns), "revenue": R.attach(rev, []),
            "spend": R.attach(spend, []), "roas": R.attach(roas, []),
            "rev_share": R.attach(revshare, []),
            "month_blocks": list(month_blocks), "single_blocks": [],
            "warnings": w}


# ------------------------------------------------------------------ retention
def load_retention(src) -> tuple[pd.DataFrame, pd.DataFrame]:
    if isinstance(src, (str, pathlib.Path)):
        raw = pd.read_csv(src, header=None)
    else:
        raw = pd.read_csv(io.BytesIO(src) if isinstance(src, (bytes, bytearray))
                          else src, header=None)
    w = []
    # locate the real header row: the one containing a 'sku'-like cell
    hdr_row = 0
    for i in range(min(5, len(raw))):
        row = [str(v).lower() for v in raw.iloc[i] if pd.notna(v)]
        if any("sku" in v for v in row):
            hdr_row = i
            break
    hdr = [str(v).strip() if pd.notna(v) else "" for v in raw.iloc[hdr_row]]

    # day-window columns discovered from headers: '15 Days %', '30d %', '60 days'
    day_cols = {}
    for i, h in enumerate(hdr):
        m = re.search(r"(\d{1,3})\s*(?:d\b|day)", h.lower())
        if m:
            day_cols[int(m.group(1))] = i
    day_cols = dict(sorted(day_cols.items()))
    if not day_cols:
        raise ValueError("Retention sheet: no day-window columns found "
                         "(expected headers like '15 Days %', '30d %'…).")

    i_sku = next((i for i, h in enumerate(hdr) if "sku" in h.lower() and "short" not in h.lower()), 0)
    i_name = next((i for i, h in enumerate(hdr)
                   if "short" in h.lower() or "product" in h.lower()), None)
    i_chan = next((i for i, h in enumerate(hdr) if "channel" in h.lower()), None)
    i_cust = next((i for i, h in enumerate(hdr) if "customer" in h.lower()), None)
    i_cat = next((i for i, h in enumerate(hdr) if "categ" in h.lower()), None)
    i_price = next((i for i, h in enumerate(hdr) if "price" in h.lower()), None)
    i_onb = next((i for i, h in enumerate(hdr) if "onb" in h.lower() or "date" in h.lower()), None)

    body = raw.iloc[hdr_row + 1:]
    main = pd.DataFrame({
        "product_onb_date": (body.iloc[:, i_onb] if i_onb is not None else ""),
        "product_category": (body.iloc[:, i_cat] if i_cat is not None else ""),
        "sku": body.iloc[:, i_sku],
        "Lookup Price thing": (body.iloc[:, i_price] if i_price is not None else ""),
        "short_code": (body.iloc[:, i_name] if i_name is not None else ""),
        "channel": (body.iloc[:, i_chan] if i_chan is not None else ""),
        "Customer": R.flex_num(body.iloc[:, i_cust]) if i_cust is not None else None,
    })
    for d, i in day_cols.items():
        main[f"{d} Days %"] = R.flex_num(body.iloc[:, i])
    main = main[main["sku"].notna()].reset_index(drop=True)
    main.attrs["day_cols"] = [f"{d} Days %" for d in day_cols]

    # side table: trailing columns forming a vertical SKU list
    side = None
    used = set([i_sku, i_name, i_chan, i_cust, i_cat, i_price, i_onb, *day_cols.values()])
    for start in range(max(used, default=0) + 1, raw.shape[1]):
        vals = body.iloc[:, start].dropna().astype(str).str.strip()
        if len(vals) and re.match(r"^[A-Z]{2,4}-", vals.iloc[0]):
            ncol = min(5, raw.shape[1] - start)
            side = body.iloc[:, start:start + ncol].dropna(how="all").reset_index(drop=True)
            side.columns = ["sku", "product", "price_note", "scope", "season_tag"][:ncol]
            side = side[side["sku"].notna()]
            break

    def price_kind(note):
        if not isinstance(note, str) or not note.strip():
            return "—"
        n = note.lower()
        if "increas" in n:
            return "Increased"
        if "decreas" in n:
            return "Decreased"
        if "same" in n:
            return "Same"
        if "launch" in n:
            return "Launch / New"
        return "Other"
    if side is not None:
        side["change_type"] = side["price_note"].apply(price_kind)
    if len(main) == 0:
        raise ValueError("Retention sheet: found day columns but no data rows.")
    return R.attach(main, w), side


# canonical default day columns (page display)
RET_DAY_COLS = ["15 Days %", "30 Days %", "60 Days %", "90 Days %", "120 Days %",
                "180 Days %", "240 Days %", "300 Days %", "360 Days %"]


# ------------------------------------------------------------------ movement
def load_movement(src) -> pd.DataFrame:
    if isinstance(src, (str, pathlib.Path)):
        raw = pd.read_csv(src, header=None)
    else:
        raw = pd.read_csv(io.BytesIO(src) if isinstance(src, (bytes, bytearray))
                          else src, header=None)
    hdr_row = None
    for i in range(min(8, len(raw))):
        if str(raw.iloc[i, 0]).strip().lower().startswith(("onb", "cohort", "month")):
            hdr_row = i
            break
    if hdr_row is None:
        raise ValueError("Movement sheet: couldn't find the cohort/onb_month header row "
                         f"(scanned first {min(8, len(raw))} rows).")
    df = raw.iloc[hdr_row + 1:].copy()
    df.columns = [str(c).strip() for c in raw.iloc[hdr_row]]
    w = []
    first_col = df.columns[0]
    df["onb_month"] = R.flex_dates(df[first_col])
    df = df[df["onb_month"].notna()].copy()
    df["month"] = df["onb_month"].dt.to_period("M").astype(str)
    for c in df.columns:
        if c not in ("month", "onb_month"):
            df[c] = R.flex_num(df[c])
    if first_col != "onb_month":
        w.append(f"Movement: cohort column '{first_col}' used as onb_month.")
    return R.attach(df, w)


def show_warnings(*dfs):
    """Surface loader fuzzy-fallback warnings in the Streamlit UI."""
    try:
        import streamlit as st
    except ImportError:
        return
    seen = set()
    for d in dfs:
        if d is None or not hasattr(d, "attrs"):
            continue
        for msg in d.attrs.get("warnings", []):
            if msg not in seen:
                seen.add(msg)
                st.warning(msg, icon="⚠️")
