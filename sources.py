"""
sources.py — shared data-loading, header/column identification, validation & caching.

Architecture:
  * every CSV is read as a raw 2-D grid (header=None) — flat exports, the wide
    AOP sheet and the multi-block summary sheet are all handled uniformly
  * each source type has structural ANCHORS that locate its header row
  * canonical columns are fuzzy-matched to the header cells (case/underscore/
    punctuation insensitive)
  * get_source(key): upload (if present) wins over the bundled sample
"""
from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path

import pandas as pd
import streamlit as st

from formatting import SourceReport, clean_str

DATA_DIR = Path(__file__).parent / "data"

# ---------------------------------------------------------------------------
# raw grid reading
# ---------------------------------------------------------------------------
def read_csv_any(raw: bytes) -> pd.DataFrame:
    """CSV bytes -> raw 2-D grid as DataFrame (integer columns, str cells)."""
    df = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            df = pd.read_csv(io.BytesIO(raw), encoding=enc, dtype=str,
                             keep_default_na=False, header=None)
            break
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    if df is None:
        df = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False,
                         on_bad_lines="skip", header=None)
    df = df.dropna(how="all").reset_index(drop=True)
    return df

def read_csv_path(path: str | Path) -> pd.DataFrame:
    return read_csv_any(Path(path).read_bytes())

def md5_bytes(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()

# ---------------------------------------------------------------------------
# column alias maps (canonical -> accepted variants, normalised)
# ---------------------------------------------------------------------------
ALIASES = {
    "sales": {
        "order_date": ["order date", "date", "order month", "month", "sale date", "transaction date"],
        "sku": ["sku", "sku code", "product code", "item", "code"],
        "channel": ["order source", "channel", "source", "sales channel"],
        "product": ["product", "product variant", "variant", "product name", "short code"],
        "category": ["category", "product category", "cat"],
        "orders": ["orders", "order count", "no of orders", "order cnt"],
        "customers": ["customers", "customer count", "unique customers", "no of customers", "cust count"],
        "quantity": ["quantity", "qty", "units", "units sold", "volume"],
        "revenue": ["revenue", "revenue inr", "rev", "amount", "net revenue", "sales value", "value"],
    },
    "category_sales": {
        "order_date": ["order date", "date", "order month", "month", "sale date", "transaction date"],
        "sku": ["sku", "sku code", "product code", "item", "code"],
        "channel": ["order source", "channel", "source", "sales channel"],
        "product": ["product", "product variant", "variant", "product name", "short code"],
        "category": ["category", "product category", "cat"],
        "orders": ["orders", "order count", "no of orders", "order cnt"],
        "customers": ["customers", "customer count", "unique customers", "no of customers", "cust count"],
        "quantity": ["quantity", "qty", "units", "units sold", "volume"],
        "revenue": ["revenue", "revenue inr", "rev", "amount", "net revenue", "sales value", "value"],
    },
    "journey": {
        "customer_id": ["customer id", "customer", "cust id", "cust", "member id", "user id", "name"],
        "order_id": ["order id", "order number", "order no", "invoice id", "order"],
        "order_date": ["order date", "date", "order datetime", "purchase date"],
        "sku": ["sku", "sku code", "product code"],
        "product": ["product", "product variant", "variant", "product name", "item name"],
        "category": ["category", "product category", "cat"],
        "channel": ["channel", "order source", "source"],
        "quantity": ["quantity", "qty", "units"],
    },
    "nps": {
        "id": ["id", "response id", "survey id"],
        "created_at": ["created at", "created at date", "date", "response date", "submitted at"],
        "customer_id": ["customer id", "customer"],
        "category": ["product category", "category", "product categories"],
        "variant": ["product variant", "variant", "product"],
        "age": ["age"],
        "skin_type": ["skin type"],
        "hair_type": ["hair type"],
        "brand_score": ["nps score for brand", "brand nps", "brand score", "nps brand"],
        "product_score": ["nps score for product", "product nps", "product score", "nps product"],
        "migrated_from": ["brand customer migrated from", "migrated from", "brand migrated from", "previous brand"],
        "like_brand": ["what do you like about nat habit", "what do you like about nathabit", "like brand"],
        "dislike_brand": ["what do you not like about nat habit", "dislike brand"],
        "like_product": ["like product", "what do you like", "likes"],
        "dislike_product": ["not like product", "what do you not like", "dislikes"],
    },
    "cs": {
        "id": ["id", "ticket id", "chat id"],
        "created_at": ["created at", "date", "ticket date"],
        "customer_name": ["customer name", "customer"],
        "order_name": ["order name", "order id", "order"],
        "order_count": ["order count"],
        "chat_status": ["chat status", "status", "resolution status"],
        "provided_resolution": ["provided resolution", "resolution"],
        "failure_type": ["failure type", "issue type"],
        "failure_reason": ["failure reason", "reason"],
        "failure_subreason": ["failure subreason", "subreason", "sub reason"],
        "products_ordered": ["products ordered", "products"],
        "products_impacted": ["products impacted", "impacted product", "impacted products"],
        "category": ["product impacted category", "category", "product category"],
        "responsible_team": ["responsible team", "team"],
        "remarks": ["remarks", "remark", "case remarks"],
        "global_remark": ["global remark", "global remarks", "customer remark"],
        "fulfilled_time": ["fulfilled time", "fulfilment time"],
        "delivery_time": ["delivery time", "delivered time"],
        "city": ["city"],
        "state": ["state"],
    },
    "retention_fm": {
        "onb_date": ["product onb date", "onb date", "onboarding date", "launch date"],
        "category": ["product category", "category"],
        "sku": ["sku", "sku code"],
        "price_note": ["lookup price thing", "price revision", "price change"],
        "variant": ["short code", "variant", "product variant"],
        "channel": ["channel", "order source"],
        "customers": ["customer", "customers", "customer count"],
    },
    "order_movement": {
        "cohort": ["onb month", "onb_month", "cohort", "cohort month", "month"],
        "first_order": ["first order", "new customers", "new orders"],
        "sec_order": ["sec order", "second order"],
        "sec_pct": ["sec pct", "second order pct", "second order %", "sec %"],
        "avg_days_sec": ["avg days to sec", "avg days 2nd"],
        "third_order": ["third order"],
        "third_pct": ["third pct", "third order pct", "third order %"],
        "avg_days_third": ["avg days to third"],
        "fourth_order": ["fourth order"],
        "fourth_pct": ["fourth pct", "fourth order pct", "fourth order %"],
        "avg_days_fourth": ["avg days to fourth"],
        "fifth_order": ["fifth order"],
        "fifth_pct": ["fifth pct", "fifth order pct", "fifth order %"],
        "avg_days_fifth": ["avg days to fifth"],
        "sixth_order": ["sixth order"],
        "sixth_pct": ["sixth pct", "sixth order pct", "sixth order %"],
        "avg_days_sixth": ["avg days to sixth"],
    },
}

REQUIRED = {
    "sales": ["order_date", "category", "revenue"],
    "category_sales": ["order_date", "category", "revenue"],
    "journey": ["customer_id", "order_date", "category"],
    "nps": ["brand_score", "product_score"],
    "cs": ["created_at"],
    "retention_fm": ["onb_date", "sku", "customers"],
    "order_movement": ["cohort", "first_order"],
}

SAMPLE_FILES = {
    "sales": "sample_sales.csv",
    "category_sales": "sample_sales_moisturisers.csv",
    "journey": "sample_journey_d2c.csv",
    "nps": "sample_nps.csv",
    "cs": "sample_cs.csv",
    "aop": "sample_aop.csv",
    "retention_fm": "sample_retention.csv",
    "order_movement": "sample_new_to_category.csv",
    "migr_seasonality": "sample_migr_seasonality.csv",
}

SAMPLE_LABELS = {
    "sales": "Sales / Revenue — all categories, 25 Jul – 23 Aug 2026 (export)",
    "category_sales": "Category-scoped sales — Moisturisers, 25 Jul – 23 Aug 2026 (export)",
    "journey": "Customer Journey — base sheet (D2C, all users, Moisturisers, Jan 2024 – Jun 2026)",
    "nps": "NPS Raw Data",
    "cs": "CS Feedback",
    "aop": "AOP (plan)",
    "retention_fm": "Retention FM",
    "order_movement": "New-to-Category Order Movement",
    "migr_seasonality": "Seasonality & Migration Summary Sheet",
}

def _norm_name(s) -> str:
    s = clean_str(s).lower()
    s = re.sub(r"[_/\-\.\(\)\[\]\u2019'\u2013]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

# ---------------------------------------------------------------------------
# header-row anchors (structural, not business-specific)
# ---------------------------------------------------------------------------
WIDE_MARKERS = ["first order date", "first purchased sku", "first purchased short code", "second order date"]

def journey_is_wide(df: pd.DataFrame, header_row: int) -> bool:
    """True for the wide 'base sheet' format: >=2 exact wide-format marker headers."""
    if header_row is None:
        return False
    header = {str(x).replace("_", " ").strip().lower() for x in df.iloc[header_row].tolist()}
    return sum(m in header for m in WIDE_MARKERS) >= 2

def _header_matches(key: str, low_cells: set[str]) -> bool:
    if key in ("sales", "category_sales"):
        return (any(a in low_cells for a in ["revenue", "rev"])
                and any(a in low_cells for a in ["order date", "date", "month", "order month"]))
    if key == "journey":
        cust = any(a in low_cells for a in ["customer id", "customer", "cust id", "user id", "member id", "name"])
        dated = (any(a in low_cells for a in ["order date", "date", "purchase date"])
                 or any("order date" in a for a in low_cells))
        return cust and dated
    if key == "nps":
        return any("nps" in a for a in low_cells)
    if key == "cs":
        return "created at" in low_cells or any("failure" in a for a in low_cells)
    if key == "retention_fm":
        return any("onb" in a for a in low_cells) and any(
            "days" in a and "%" in a for a in low_cells)
    if key == "order_movement":
        return "onb month" in low_cells or "cohort month" in low_cells
    return False

def detect_header(df: pd.DataFrame, key: str) -> int | None:
    """Row index of the header row, located via structural anchors."""
    for i in range(min(12, len(df))):
        cells = set()
        for v in df.iloc[i].tolist():
            n = _norm_name(v)
            if n:
                cells.add(n)
        if _header_matches(key, cells):
            return i
    return None

def find_columns(df: pd.DataFrame, key: str, header_row: int) -> dict:
    """canonical -> column INDEX, fuzzy-matched against the header row cells."""
    header = [_norm_name(v) for v in df.iloc[header_row].tolist()]
    found = {}
    for canon, variants in ALIASES[key].items():
        vnorm = [_norm_name(v) for v in variants]
        hit = None
        for j, h in enumerate(header):
            if h in vnorm:
                hit = j
                break
        if hit is None:  # substring fallback (single unambiguous candidate)
            cands = []
            for vn in vnorm:
                for j, h in enumerate(header):
                    if h and (vn in h or h in vn) and len(h) > 2:
                        cands.append(j)
            if len(set(cands)) == 1:
                hit = cands[0]
        if hit is not None and hit not in found.values():
            found[canon] = hit
    return found

# ---------------------------------------------------------------------------
# cached raw frame per (source, file hash)
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _cached_frame(source: str, file_hash: str, raw: bytes) -> pd.DataFrame:
    return read_csv_any(raw)

@st.cache_data(show_spinner=False)
def _cached_sample_frame(source: str, file_mtime: int) -> pd.DataFrame:
    return read_csv_path(DATA_DIR / SAMPLE_FILES[source])

def _upload_bytes(source: str) -> bytes | None:
    up = st.session_state.get(f"upload_{source}")
    if up is None:
        return None
    try:
        return up.getvalue()
    except Exception:
        return None

def get_source(key: str):
    """Return (raw_grid_df, SourceReport). Priority: pasted text (NPS) > upload > sample."""
    rep = SourceReport(key=key, label=SAMPLE_LABELS.get(key, key))
    if key == "nps":
        pasted = st.session_state.get("nps_pasted_raw")
        if pasted and str(pasted).strip():
            rep.is_sample = False
            rep.filename = "pasted NPS data"
            df = read_csv_any(str(pasted).encode("utf-8"))
            rep.row_count = int(len(df))
            return df, rep
    raw = _upload_bytes(key)
    if raw is not None:
        rep.is_sample = False
        try:
            name = st.session_state[f"upload_{key}"].name
        except Exception:
            name = "uploaded.csv"
        rep.filename = name
        df = _cached_frame(key, md5_bytes(raw), raw)
    else:
        path = DATA_DIR / SAMPLE_FILES[key]
        if not path.exists():
            rep.err(f"Sample file missing: {path.name}. Please upload a CSV.")
            return None, rep
        rep.filename = path.name
        rep.is_sample = True
        rep.is_demo = False
        df = _cached_sample_frame(key, path.stat().st_mtime_ns)
    rep.row_count = int(len(df))
    return df, rep

def get_model(key: str):
    """
    One-stop: raw grid + detected header + column map + internal model + report.
    Returns (model, report, meta) where meta = {'header_row': i, 'colmap': {...}, 'raw': df}.
    model is None when the source cannot be parsed (report.errors explains why).
    """
    import etl
    raw, rep = get_source(key)
    if raw is None:
        return None, rep, {}
    meta = {"raw": raw, "header_row": None, "colmap": {}}
    if key == "aop":
        model = etl.build_aop_model(raw, rep)
        return model, rep, meta
    if key == "migr_seasonality":
        model = etl.build_migr_seasonality_model(raw, rep)
        return model, rep, meta
    hr = detect_header(raw, key)
    if hr is None:
        rep.err("Header row not recognized. Check that the file is a "
                f"{SAMPLE_LABELS.get(key, key)} export (first rows should contain its standard column names).")
        return None, rep, meta
    colmap = find_columns(raw, key, hr)
    meta["header_row"], meta["colmap"] = hr, colmap
    reqs = list(REQUIRED.get(key, []))
    if key == "journey" and journey_is_wide(raw, hr):
        # wide "base sheet" format (one row per customer, first..sixth order columns)
        reqs = ["customer_id"]
    missing = [r for r in reqs if r not in colmap]
    if missing:
        hints = {"sales": {"order_date": "a date column (e.g. 'order date')", "category": "'category'", "revenue": "'revenue'"},
                 "journey": {"customer_id": "'customer_id'", "order_date": "an 'order date' column", "category": "'category'"},
                 "nps": {"brand_score": "'NPS Score For Brand'", "product_score": "'NPS Score For Product'"},
                 "cs": {"created_at": "'created_at'"},
                 "retention_fm": {"onb_date": "'product_onb_date'", "sku": "'sku'", "customers": "'Customer'"},
                 "order_movement": {"cohort": "'onb_month'", "first_order": "'first_order'"},
                 "category_sales": {"order_date": "a date column (e.g. 'order date')", "category": "'category'", "revenue": "'rev'/'revenue'"}}.get(key, {})
        rep.err("Missing required column(s): " + ", ".join(f"{m} (expected {hints.get(m, m)})" for m in missing)
                + " — the parts of this page that depend on them will be disabled.")
    builders = {"sales": etl.build_sales_model, "category_sales": etl.build_sales_model,
                "journey": etl.build_journey_model,
                "nps": etl.build_nps_model, "cs": etl.build_cs_model,
                "retention_fm": etl.build_retention_fm_model,
                "order_movement": etl.build_order_movement_model}
    model = builders[key](raw, rep, colmap, hr)
    return model, rep, meta

# ---------------------------------------------------------------------------
# per-page upload widget (consistent UX across all pages)
# ---------------------------------------------------------------------------
def page_uploader(key: str, help_text: str = ""):
    up = st.file_uploader(
        "Upload CSV",
        type=["csv"],
        key=f"upload_{key}",
        help=help_text or f"Replace the {SAMPLE_LABELS.get(key, key)} reference data with a fresh export.",
    )
    _, rep = get_source(key)
    if up is not None:
        st.caption("✅ Using **uploaded file**")
    else:
        tag = "⚪ Using **sample data** (no upload)" + (" — *synthetic demo*" if rep.is_demo else "")
        st.caption(tag)
    return rep

# ---------------------------------------------------------------------------
# shared sidebar filter helpers
# ---------------------------------------------------------------------------
def sidebar_filters(key_prefix: str, options: dict, selected: dict | None = None,
                    multi: dict | None = None, reset_key: str | None = None):
    sel = {}
    for name, opts in options.items():
        opts = list(opts)
        if not opts:
            sel[name] = "All" if not (multi and name in multi) else []
            continue
        if multi and name in multi:
            sel[name] = st.multiselect(name, opts, default=selected.get(name) if selected else [],
                                       key=f"{key_prefix}_f_{name}")
        else:
            cur = selected.get(name) if selected else None
            idx = (["All"] + opts).index(cur) if cur in opts else 0
            sel[name] = st.selectbox(name, ["All"] + opts, index=idx,
                                     key=f"{key_prefix}_f_{name}")
    if reset_key is not None:
        if st.button("↺ Reset filters", key=f"{key_prefix}_reset"):
            for k in list(st.session_state.keys()):
                if k.startswith(f"{key_prefix}_f_"):
                    del st.session_state[k]
            st.rerun()
    return sel

def month_options(df: pd.DataFrame) -> list[str]:
    if "month" not in df.columns:
        return []
    return sorted([m for m in df["month"].dropna().unique() if m])
