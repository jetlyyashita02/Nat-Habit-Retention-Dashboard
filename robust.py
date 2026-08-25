"""
Robustness layer — tolerant header resolution, date & number parsing.
Design contract:
  * loaders output a CANONICAL schema regardless of how the sheet spells headers
  * every fuzzy fallback records a warning in df.attrs["warnings"] for the UI to show
  * when nothing sensible can be found, loaders raise a clear, actionable ValueError
"""
from __future__ import annotations

import re

import pandas as pd

MONTH_FULL = {"january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
              "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7,
              "jul": 7, "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
              "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12,
              "dec": 12}

_ORDINALS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3,
             "fourth": 4, "4th": 4, "fifth": 5, "5th": 5, "sixth": 6, "6th": 6,
             "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6}


def norm_header(h) -> str:
    """' First Purchased SKU ' -> 'firstpurchasedsku'"""
    return re.sub(r"[^a-z0-9]", "", str(h).lower())


def find_col(headers, aliases, *, contains=False, numeric_hint=None,
             exclude=("unit", "price", "share", "%", "id")):
    """Resolve a column by alias list against normalized headers.
    numeric_hint: sample row (pd.Series) — when multiple alias hits, prefer the
    column whose sample is numeric. Returns position or None."""
    norm = [norm_header(h) for h in headers]
    hits = []
    for a in aliases:
        an = norm_header(a)
        for i, h in enumerate(norm):
            if (h == an if not contains else an in h):
                hits.append(i)
    hits = list(dict.fromkeys(hits))
    if len(hits) > 1 and numeric_hint is not None:
        numeric = [i for i in hits
                   if pd.to_numeric(numeric_hint.iloc[i].astype(str)
                                    .str.replace(r"[₹,%\s]", "", regex=True)
                                    .str.replace(r"(?i)cr$", "e7", regex=True)
                                    .str.replace(r"(?i)l$", "e5", regex=True),
                                    errors="coerce").notna().mean() > 0.7]
        soft = [i for i in hits if not any(e in norm[i] for e in exclude)]
        hits = (numeric or soft or hits)[:1]
    return hits[0] if hits else None


def ordinal_slot(headers, kind, ordinal):
    """Find e.g. the 'third purchased sku' / '3rd order date' column regardless of
    exact spelling. kind in {'sku','date','name','code'}."""
    words_ord = [w for w, n in _ORDINALS.items() if n == ordinal]
    norm = [norm_header(h) for h in headers]
    kind_words = {"sku": ("sku",), "date": ("orderdate", "date"),
                  "name": ("shortcode", "productname", "name", "product"),
                  "code": ("shortcode",)}[kind]
    for i, h in enumerate(norm):
        if any(w in h for w in words_ord) and any(k in h for k in kind_words):
            if kind == "sku" and "short" in h:      # short_code is the name column
                continue
            return i
    return None


def flex_dates(series: pd.Series, *, dayfirst=None) -> pd.Series:
    """Parse a date column through a cascade: ISO, 'Jan 15, 2026', '15 Jan 2026',
    '15-01-2026', '01/15/2026', Excel serials, and finally pd.to_datetime."""
    def one(v):
        if pd.isna(v):
            return pd.NaT
        if isinstance(v, (pd.Timestamp,)):
            return v
        if isinstance(v, (int, float)) and 30000 < float(v) < 60000:  # excel serial
            return pd.Timestamp("1899-12-30") + pd.Timedelta(days=float(v))
        s = str(v).strip()
        fmts = ["%Y-%m-%d", "%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y",
                "%b %d, %Y, %H:%M", "%B %d, %Y, %H:%M", "%Y-%m-%d %H:%M:%S",
                "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y", "%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M"]
        for f in fmts:
            try:
                return pd.Timestamp(pd.to_datetime(s, format=f))
            except (ValueError, TypeError):
                continue
        try:
            return pd.Timestamp(pd.to_datetime(s, dayfirst=bool(dayfirst), errors="raise"))
        except (ValueError, TypeError, pd.errors.ParserError):
            return pd.NaT

    return series.apply(one)


def flex_num(series: pd.Series) -> pd.Series:
    DOC = "'\u20b91,234' to 1234; '12%' to 12; '2.5 Cr' to 2.5e7; '45 L' to 4.5e6"
    s = series.astype(str).str.strip()
    s = s.str.replace(r"\u20b9|,|\s", "", regex=True)
    s = s.str.replace(r"(?i)(cr|crore)s?$", "e7", regex=True)
    s = s.str.replace(r"(?i)(l|lakh)s?$", "e5", regex=True)
    s = s.str.replace("%", "", regex=False)
    s = s.replace({"": None, "nan": None, "None": None, "-": None,
                   "\u2014": None, "\u2013": None})
    return pd.to_numeric(s, errors="coerce")


def month_label(v):
    """'Jan'24' / 'May 2026' / 'January-24' / '2026-05' -> '2026-05'."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    if re.match(r"^\d{4}-\d{2}$", s):
        return s
    m = re.match(r"^([A-Za-z]{3,9})['\s\-/]*(\d{2,4})$", s)
    if m:
        mon = MONTH_FULL.get(m.group(1).lower())
        if mon:
            y = int(m.group(2))
            y = y + 2000 if y < 100 else y
            return f"{y}-{mon:02d}"
    m = re.match(r"^(\d{4})['\s\-/]*([A-Za-z]{3,9})$", s)
    if m:
        mon = MONTH_FULL.get(m.group(2).lower())
        if mon:
            return f"{m.group(1)}-{mon:02d}"
    return None


def warn(df_or_none, msg, sink: list):
    sink.append(msg)
    if df_or_none is not None and isinstance(df_or_none, pd.DataFrame):
        df_or_none.attrs.setdefault("warnings", []).append(msg)


def attach(df: pd.DataFrame, warnings: list) -> pd.DataFrame:
    df.attrs["warnings"] = warnings
    return df


def load_config() -> dict:
    """Pinned conventions per source — editable at data/config.json."""
    import json as _json
    import pathlib as _pl
    p = _pl.Path(__file__).resolve().parent / "data" / "config.json"
    try:
        return _json.loads(p.read_text())
    except Exception:
        return {"dayfirst": {"journey": True, "sales": True, "nps": True,
                             "cs": True}}
