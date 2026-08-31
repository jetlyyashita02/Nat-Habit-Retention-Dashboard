"""
formatting.py — shared normalization, parsing and display utilities.

Conventions (documented in README + Definitions page):
  * Percentages are stored INTERNALLY as fractions (0.304 = 30.4%).
  * fmt_pct() renders them as "30.4%" — never as "0.304".
  * Money is INR, rendered compactly (₹1.24Cr / ₹45.6L / ₹12,345).
  * Months are ISO strings "YYYY-MM".
All parsing is defensive: bad values become NaN with a counter, never a crash.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# text cleaning
# ---------------------------------------------------------------------------
_EMB = {
    "\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-", "\u00a0": " ",
}

def clean_str(v) -> str:
    """Strip spaces / BOM / smart quotes from a scalar. NaN -> ''."""
    if v is None:
        return ""
    if isinstance(v, float) and np.isnan(v):
        return ""
    s = str(v)
    for k, val in _EMB.items():
        s = s.replace(k, val)
    return s.strip()

def clean_series(s: pd.Series) -> pd.Series:
    return s.map(clean_str)

def is_blank(v) -> bool:
    return clean_str(v) in ("", "-", "—", "--", "nan", "None", "null", "#REF!")

# ---------------------------------------------------------------------------
# numeric / percent parsing
# ---------------------------------------------------------------------------
_NUM_RE = re.compile(r"[-+]?\d[\d,]*\.?\d*")

def parse_number(v, default=np.nan):
    """Parse '1,234.5', '₹1,234', '237.0135685', ' 12 ' etc. -> float."""
    if v is None:
        return default
    if isinstance(v, (int, float, np.integer, np.floating)):
        return float(v) if not pd.isna(v) else default
    s = clean_str(v).replace("₹", "").replace(" ", "")
    if s in ("", "-", "—", "--"):
        return default
    m = _NUM_RE.search(s)
    if not m:
        return default
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return default

def parse_pct(v, assume_fraction_max: float = 1.5):
    """
    Parse a percentage cell into a FRACTION (0.304).

    Rules:
      * '30.4%'      -> 0.304  (explicit percent sign)
      * 30.4         -> 0.304  (bare number > assume_fraction_max => already a % number)
      * 0.304        -> 0.304  (bare number <= assume_fraction_max => fraction)
      * ''           -> NaN
    """
    n = parse_number(v)
    if np.isnan(n):
        return np.nan
    s = clean_str(v)
    if "%" in s:
        return n / 100.0
    if n > assume_fraction_max:
        return n / 100.0
    return n

# ---------------------------------------------------------------------------
# dates / months
# ---------------------------------------------------------------------------
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

def _expand_2y(yy: int) -> int:
    return yy if yy >= 70 else 2000 + yy

def parse_month_label(v):
    """
    'Jan'26' | 'Jan 2026' | 'Jan-26' | 'January 2026' | '2026-01' | '202601'
    -> 'YYYY-MM' or None
    """
    s = clean_str(v)
    if not s:
        return None
    s = s.replace("’", "'")
    m = re.match(r"^([A-Za-z]{3,9})\s*[-'/]?\s*'?(\d{2,4})$", s)
    if m:
        mon = _MONTHS.get(m.group(1)[:3].lower())
        if mon:
            y = _expand_2y(int(m.group(2)))
            return f"{y:04d}-{mon:02d}"
    m = re.match(r"^(\d{4})[-/](\d{1,2})$", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = re.match(r"^(\d{4})(\d{2})$", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return None

def parse_date(v):
    """
    Flexible date parsing. Returns datetime.date or None.
    Handles: 'Feb 1, 2026', '2026-08-03', '4-8-2026' (d-M-Y), 'Aug 3, 2026, 14:30',
    '2026-08-03 18:16:47', '3/8/2026', '03-Aug-2026'.
    """
    s = clean_str(v)
    if not s:
        return None
    fmts = [
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
        "%b %d, %Y, %H:%M", "%b %d, %Y",
        "%d-%m-%Y %H:%M", "%d-%m-%Y",
        "%d %b %Y, %H:%M", "%d %b %Y",
        "%m/%d/%Y %H:%M:%S", "%m/%d/%Y",
        "%d-%b-%Y", "%d %b %Y",
    ]
    for f in fmts:
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    # try pandas as last resort (handles many oddities)
    try:
        ts = pd.to_datetime(s, dayfirst=True, errors="raise")
        return ts.date()
    except Exception:
        return None

def parse_datetime(v):
    """Like parse_date but returns datetime (keeps time)."""
    s = clean_str(v)
    if not s:
        return None
    for f in ["%Y-%m-%d %H:%M:%S", "%b %d, %Y, %H:%M", "%b %d, %Y %H:%M",
              "%d-%m-%Y %H:%M", "%Y-%m-%d %H:%M"]:
        try:
            return datetime.strptime(s, f)
        except ValueError:
            pass
    try:
        ts = pd.to_datetime(s, dayfirst=True, errors="raise")
        return ts.to_pydatetime()
    except Exception:
        return None

def month_of(d) -> Optional[str]:
    if d is None:
        return None
    return f"{d.year:04d}-{d.month:02d}"

# ---------------------------------------------------------------------------
# display formatting
# ---------------------------------------------------------------------------
def fmt_pct(x, digits: int = 1, na: str = "—", signed: bool = False) -> str:
    """Fraction (0.304) -> '30.4%'. NaN/None -> na."""
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return na
    try:
        v = float(x) * 100.0
    except (TypeError, ValueError):
        return na
    sign = "+" if (signed and v > 0) else ""
    return f"{sign}{v:.{digits}f}%"

def fmt_pct_auto(x, na: str = "—") -> str:
    """Adaptive: 2 decimals under 10% (0.54%), 1 decimal otherwise (12.7%).
    Used for retention windows so small values keep precision."""
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return na
    return fmt_pct(x, digits=2 if abs(float(x) * 100) < 10 else 1, na=na)

def fmt_pct_cell(x, digits: int = 1, na: str = "—") -> str:
    """For table cells: NaN -> '—'."""
    return fmt_pct(x, digits, na=na)

def fmt_money(x, na: str = "—") -> str:
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return na
    x = float(x)
    neg = x < 0
    a = abs(x)
    if a >= 1e7:
        s = f"₹{a/1e7:,.2f}Cr"
    elif a >= 1e5:
        s = f"₹{a/1e5:,.1f}L"
    elif a >= 1e3:
        s = f"₹{a:,.0f}"
    else:
        s = f"₹{a:,.0f}"
    return ("-" + s) if neg else s

def fmt_int(x, na: str = "—") -> str:
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return na
    return f"{int(round(float(x))):,}"

def fmt_num(x, digits: int = 1, na: str = "—") -> str:
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return na
    return f"{float(x):,.{digits}f}"

def fmt_days(x, na: str = "—") -> str:
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return na
    return f"{float(x):.0f} d"

# ---------------------------------------------------------------------------
# downloads
# ---------------------------------------------------------------------------
def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")

# ---------------------------------------------------------------------------
# multi-select field splitting (likes/dislikes, demographics)
# ---------------------------------------------------------------------------
def split_multi(v, seps: str = "|;") -> list[str]:
    """'A|B ;C' -> ['A','B','C'] cleaned, de-duplicated, order preserved."""
    s = clean_str(v)
    if not s:
        return []
    parts = re.split(r"[|;]", s)
    out, seen = [], set()
    for p in parts:
        p = p.strip().strip(",").strip()
        if not p or p.lower() in ("no complaints- love the product!", "nan", "none"):
            continue
        key = p.lower()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out

# ---------------------------------------------------------------------------
# validation report
# ---------------------------------------------------------------------------
@dataclass
class SourceReport:
    key: str                      # 'sales', 'nps', ...
    label: str                    # human label
    filename: str = ""            # uploaded name or sample file name
    is_sample: bool = True
    is_demo: bool = False         # True when the sample is synthetic
    row_count: int = 0
    date_min: str = ""
    date_max: str = ""
    entities: dict = field(default_factory=dict)   # {'Categories': n, ...}
    warnings: list = field(default_factory=list)   # (⚠ messages)
    errors: list = field(default_factory=list)     # (✗ messages)

    @property
    def ok(self) -> bool:
        return not self.errors

    def warn(self, msg):
        self.warnings.append(msg)

    def err(self, msg):
        self.errors.append(msg)

# ---------------------------------------------------------------------------
# UI helpers (import streamlit lazily so pure functions stay testable)
# ---------------------------------------------------------------------------
def init_page(title: str, emoji: str = "📊", desc: str = ""):
    import streamlit as st
    st.set_page_config(page_title=f"{title} · Retention & Category Intelligence",
                       page_icon=emoji, layout="wide", initial_sidebar_state="expanded")
    st.title(f"{emoji} {title}")
    if desc:
        st.caption(desc)

def render_report(rep: SourceReport, title_prefix: str = "Data source"):
    import streamlit as st
    status = "📊" if not rep.is_sample else " sample data"
    if rep.is_demo:
        status += " · synthetic demo"
    with st.container(border=True):
        st.caption(f"**{title_prefix}**: {status} — `{rep.filename}` · {rep.row_count:,} rows"
                   + (f" · {rep.date_min} → {rep.date_max}" if rep.date_min else ""))
        if rep.entities:
            ent = " · ".join(f"{k}: {v:,}" if isinstance(v, int) else f"{k}: {v}"
                             for k, v in rep.entities.items())
            st.caption(ent)
        for w in rep.warnings:
            st.warning(w)
        for e in rep.errors:
            st.error(e)

def kpi_cards(cards: list):
    """cards: list of (label, value_str[, delta_str[, delta_value]])."""
    import streamlit as st
    cols = st.columns(min(len(cards), 6))
    for i, card in enumerate(cards[:6]):
        label, value = card[0], card[1]
        delta = card[2] if len(card) > 2 else None
        dval = card[3] if len(card) > 3 else None
        with cols[i % len(cols)]:
            if delta:
                st.metric(label, value, delta, delta_color="normal" if (dval is None or dval >= 0) else "inverse")
            else:
                st.metric(label, value)

def download_button(label: str, df: pd.DataFrame, filename: str):
    import streamlit as st
    st.download_button(label, data=df_to_csv_bytes(df), file_name=filename, mime="text/csv")

def section(title: str, desc: str = ""):
    import streamlit as st
    st.subheader(title)
    if desc:
        st.caption(desc)
