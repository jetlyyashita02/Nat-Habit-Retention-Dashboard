"""
make_retention_dashboard.py — build journey.html, the interactive retention
deep-dive dashboard (single self-contained file, same spirit as the
Seasonality & Migration reference dashboard — clickable charts, live filters,
auto-detected insights, journey explorer).

What it does
------------
Reads the customer journey base sheet (D2C · Moisturisers · first 6 orders)
through the same etl pipeline as the app, adds the customer→city map from the
raw export, and emits retention.html with:

  * the FULL per-customer journey embedded as compact JSON (152k customers)
  * client-side filtering: category / variant / size / entry month range /
    journey depth / region / city / repeaters — charts and tables are
    clickable and SET the matching filter
  * live KPIs, auto-detected "deep-cut insights" (clickable), retention
    curves with cohort-maturity N/A rule, repurchase-gap distribution,
    V2V/V2C loyalty, seasonality (intended line vs calendar timing),
    geography × season heatmaps, switching behaviour, a sortable variant
    summary, and a paginated Journey explorer with CSV export
  * zero external references (works offline and on GitHub Pages)

Next month: drop the new base sheet in uploads/ (or data/) and re-run:
    python make_retention_dashboard.py
Nothing business-specific is hardcoded — every number is computed from the
loaded sheet. (City→region is a documented classification, see footer.)
"""
from __future__ import annotations

import html as _html
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import numpy as np
import pandas as pd

import sources
import _live_part

ROOT = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# methodology tables (NOT business results — documented in the dashboard footer)
# ---------------------------------------------------------------------------
# calendar season by month number: Cold Winter Dec–Feb · Hot Dry Mar–May ·
# Hot Humid Jun–Sep · Post-Monsoon Oct–Nov
CAL_SEASON = {12: 0, 1: 0, 2: 0, 3: 1, 4: 1, 5: 1, 6: 2, 7: 2, 8: 2, 9: 2, 10: 3, 11: 3}
SEASON_NAMES = ["Cold Winter", "Hot Dry", "Hot Humid", "Post-Monsoon"]
SEASON_ICONS = ["❄", "", "🌧", "🍂"]

# intended season line from the SKU code (FC-<LINE>-<VARIANT>-<SIZE>)
SKU_LINE = {
    "CWDM": 0,  # Cold Winter
    "HDDM": 1,  # Hot Dry
    "HHDM": 2,  # Hot Humid
    "DM": 3,    # non-seasonal concern-led
    "AC": 4,    # Active Gel line (not seasonal)
    "HG": 5,    # Aloe Vera Gel line (not seasonal)
}
LINE_NAMES = ["Cold Winter", "Hot Dry", "Hot Humid", "Concern-led", "Active Gel", "Aloe Vera Gel"]
# intended timing windows (calendar months) for on-season lift
LINE_WINDOW = {0: [12, 1, 2], 1: [3, 4, 5], 2: [6, 7, 8, 9], 3: [], 4: [], 5: []}

# major-city → region classification (documented methodology; the rest of
# India's 400+ smaller cities are grouped as "Rest of India")
CITY_REGION = {
    # North
    "New Delhi": 0, "Gurgaon": 0, "Ghaziabad": 0, "Noida": 0, "Greater Noida": 0,
    "Gautam Buddha Nagar": 0, "Faridabad": 0, "Agra": 0, "Kanpur": 0, "Lucknow": 0,
    "Dehradun": 0, "Chandigarh": 0, "Ludhiana": 0, "Ambala": 0, "Jammu": 0,
    "Jaipur": 0, "Jodhpur": 0, "Udaipur": 0, "Meerut": 0, "Bareilly": 0,
    "Prayagraj": 0, "Allahabad": 0, "Varanasi": 0, "Moradabad": 0, "Aligarh": 0,
    "Haridwar": 0, "Shimla": 0, "Amritsar": 0, "Patiala": 0, "Rajkot": 0,
    # West
    "Mumbai": 1, "Pune": 1, "Thane": 1, "Navi Mumbai": 1, "Nashik": 1,
    "Ahmedabad": 1, "Surat": 1, "Vadodara": 1, "Indore": 1, "Bhopal": 1,
    "Goa": 1, "Palghar": 1, "Aurangabad": 1, "Nagpur": 1, "Hubli": 1,
    "Mangalore": 1, "Hubli-Dharwad": 1,
    # South
    "Bengaluru": 2, "Chennai": 2, "Hyderabad": 2, "Secunderabad": 2,
    "Coimbatore": 2, "Ernakulam": 2, "Trivandrum": 2, "Thiruvananthapuram": 2,
    "Mysuru": 2, "Mysore": 2, "Visakhapatnam": 2, "Tambaram": 2, "Madurai": 2,
    "Kochi": 2, "Tirupati": 2, "Vijayawada": 2, "Guntur": 2, "Sri City": 2,
    # East
    "Kolkata": 3, "Bhubaneswar": 3, "Guwahati": 3, "Ranchi": 3, "Patna": 3,
    "Jamshedpur": 3, "Siliguri": 3, "Rourkela": 3, "Asansol": 3, "Darjeeling": 3,
}
REGION_NAMES = ["North", "West", "South", "East", "Rest of India"]


def _clean_variant_name(product: str) -> str:
    """'Tomato Patchouli (Cold) 13 - 19 Yrs Face Malai' → 'Tomato Patchouli'."""
    s = str(product)
    s = re.split(r"\s*\(", s)[0]
    s = re.split(r"\s+-\s+", s)[0]
    for tail in ("Face Malai", "Active Gel", "Aloe Vera Gel"):
        s = re.sub(rf"\s+{re.escape(tail)}$", "", s)
    s = s.strip(" -–—")
    return s or "(unknown)"


def _size_of_sku(sku: str) -> int:
    m = re.search(r"-(\d{3,4})$", str(sku))
    return int(m.group(1)) if m else 0


def _line_of_sku(sku: str) -> int:
    parts = str(sku).split("-")
    if len(parts) >= 3 and parts[1] in SKU_LINE:
        return SKU_LINE[parts[1]]
    return 3  # unknown → concern-led bucket


def _size_of_name(name: str) -> int:
    """'Aloe Vera Gel - 80 gms' → 80 · '…Face Malai - 30g' → 30 · no size → 0.
    Age tags like '20 - 35 Yrs' never match (no g/ml unit)."""
    m = re.search(r"(\d{2,4})\s*(?:gms?|ml)\b", str(name), re.I)
    return int(m.group(1)) if m else 0


def _line_of_name(name: str):
    """Season tag in the product name → intended line, else None (use code)."""
    s = str(name)
    if "(Cold)" in s:
        return 0
    if "(Hot Dry)" in s:
        return 1
    if "(Hot Humid)" in s:
        return 2
    return None


# ---------------------------------------------------------------------------
# data prep
# ---------------------------------------------------------------------------
def build_data() -> dict:
    journey, _, _ = sources.get_model("journey")
    d = journey["df"].copy()
    d["order_date"] = pd.to_datetime(d["order_date"])

    # customer → city from the raw base sheet (one row per customer)
    raw = sources.read_csv_path("data/sample_journey_d2c.csv")
    hr = sources.detect_header(raw, "journey")
    body = raw.iloc[hr + 1:]
    name = body.iloc[:, 0].astype(str).str.strip()
    city = body.iloc[:, 30].astype(str).str.strip()
    city = city.where(city.ne("") & (city.str.lower() != "nan"), "NA")
    cust_city = dict(zip(name, city))

    d["city"] = d["customer_id"].map(cust_city).fillna("NA")
    d["region"] = d["city"].map(lambda c: CITY_REGION.get(c, 4))
    d["sku"] = d["sku"].fillna("")
    d["product"] = d["product"].fillna(d["sku"])
    d["variant"] = d["product"].map(_clean_variant_name)
    d["om"] = d["order_date"].dt.month

    # tables -----------------------------------------------------------------
    months = sorted(d["order_date"].dt.strftime("%Y-%m").unique())
    month_lbl = [pd.Period(m).strftime("%b '%y") for m in months]
    m_of = {m: i for i, m in enumerate(months)}

    cats = sorted(d.loc[d["category"] != "", "category"].unique().tolist())
    c_of = {c: i for i, c in enumerate(cats)}
    variants = sorted(d["variant"].unique().tolist())
    v_of = {v: i for i, v in enumerate(variants)}

    # Product name is the reliable key in this sheet: the SKU code column
    # disagrees with the product name in ~13% of rows, so every metric is keyed
    # on the product name. The code (mode code per product) is used only as the
    # fallback source for intended line / size when the name carries neither.
    prods = {0: {"n": "(unknown)", "raw": "", "v": -1, "c": -1, "s": 0, "l": -1, "code": ""}}
    prod_idx = {}
    var_first = {}
    next_i = 1  # 0 is reserved for the sentinel
    for r in d.groupby("product", observed=True):
        pname, g = r
        if pname == "":
            continue
        vname = _clean_variant_name(pname)
        vi = int(v_of[vname])
        cat_mode = g["category"].mode()
        ci = int(c_of.get(cat_mode.iat[0], -1)) if len(cat_mode) else -1
        codes = g["sku"][g["sku"] != ""]
        mode_code = str(codes.mode().iat[0]) if len(codes) else ""
        li = _line_of_name(pname)
        li = int(li if li is not None else _line_of_sku(mode_code))
        sz = int(_size_of_name(pname) or _size_of_sku(mode_code))
        prod_idx[pname] = next_i
        if vi not in var_first:
            var_first[vi] = next_i
        prods[next_i] = {
            "n": f"{vname} {sz}{'g' if sz <= 100 else 'ml'}" if sz else vname,
            "raw": str(pname).strip(),
            "v": vi,
            "c": ci,
            "s": sz,
            "l": li,
            "code": mode_code,
        }
        next_i += 1

    cities = d["city"].value_counts().index.tolist()  # most common first
    ci_of = {c: i for i, c in enumerate(cities)}

    # per-customer records -----------------------------------------------------
    d = d.sort_values(["customer_id", "order_date", "order_id"]).reset_index(drop=True)

    A_city, A_region, A_month, A_cat, A_var, A_size, A_depth, A_repeat, A_entry = \
        [], [], [], [], [], [], [], [], []
    A_items, A_itemcat, A_gaps = [], [], []
    n_cust = 0
    for cust, g in d.groupby("customer_id", observed=True):
        g = g.sort_values(["order_date", "order_id"])
        # sort=False keeps chronological (date, id) order — the model's is_first/is_second
        # reference. Lexicographic id order can misorder customers' orders.
        orders = list(g.groupby("order_id", sort=False, observed=True))
        first = orders[0][1].iloc[0]
        entry_month = m_of[first["order_date"].strftime("%Y-%m")]
        gap_list = []
        item_list = []
        cat_list = []
        for oid, og in orders:
            item_list.append([int(prod_idx.get(p, 0)) for p in og["product"]])
            cat_list.append([int(c_of.get(cat, -1)) for cat in og["category"]])
            gv = og["days_to_prev"].iloc[0]
            gap_list.append(int(gv) if pd.notna(gv) else -1)
        n_cust += 1
        fp = int(prod_idx.get(first["product"], 0))
        A_city.append(int(ci_of.get(first["city"], 0)))
        A_region.append(int(first["region"]))
        A_month.append(int(entry_month))
        A_cat.append(int(c_of.get(first["category"], 0)))
        A_var.append(int(v_of.get(first["variant"], 0)))
        A_size.append(int(prods[fp]["s"]))
        A_depth.append(len(orders))
        A_repeat.append(1 if len(orders) >= 2 else 0)
        A_entry.append(str(first["order_date"].date()))
        A_items.append(item_list)
        A_itemcat.append(cat_list)
        A_gaps.append(gap_list[1:])  # gap before order 1 is undefined

    data = {
        "asOf": str(d["order_date"].max().date()),
        "months": months,
        "monthLbl": month_lbl,
        "cities": cities,
        "regions": REGION_NAMES,
        "cats": cats,
        "vars": variants,
        "lines": LINE_NAMES,
        "lineWindow": {str(k): v for k, v in LINE_WINDOW.items()},
        "seasons": SEASON_NAMES,
        "calSeason": {str(k): v for k, v in CAL_SEASON.items()},
        "prods": prods,
        "varFirstProd": var_first,
        "custCity": A_city,
        "custRegion": A_region,
        "custMonth": A_month,
        "custCat": A_cat,
        "custVar": A_var,
        "custSize": A_size,
        "custDepth": A_depth,
        "custRepeat": A_repeat,
        "custEntry": A_entry,
        "custItems": A_items,
        "custItemCat": A_itemcat,
        "custGaps": A_gaps,
        "nCustomers": n_cust,
        "nOrders": int(d["is_primary"].sum()),
    }
    return data


def build() -> tuple[str, dict]:
    data = build_data()
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    page = PAGE_TEMPLATE.replace("@@DATA@@", "const DATA = " + blob + ";")
    page = page.replace("@@LIVE_CSS@@", _live_part.LIVE_CSS)
    page = page.replace("@@LIVE_JS@@", _live_part.LIVE_JS)
    page = page.replace("@@LIVE_WIRE@@", LIVE_WIRE_JS)
    return page, data



LIVE_WIRE_JS = r"""
(function(){
  const el = document.getElementById("jLivePanel");
  const out = document.getElementById("jLiveOut");
  if(!el || !out || typeof LIVE === "undefined") return;
  LIVE.attach("jLivePanel",
    [{key:"journey", label:"Journey CSV (long form)", hint:"customer_id, order_date, category (+ product, sku, quantity, order_id)", params:{asOf: DATA.asOf}},
     {key:"any", label:"Any other CSV", hint:"generic structural analysis"}],
    function(parts){
      let html = "";
      if(parts.journey){
        const c = parts.journey;
        html += '<div class="kpis" style="margin:12px 0 4px">' + c.kpis.map(k =>
          '<div class="kpi"><div class="l">' + esc(k.label) + '</div><div class="v" style="font-size:19px">' + esc(k.value) + '</div><div class="s">' + esc(k.sub) + '</div></div>'
        ).join("") + '</div>';
        const mx = Math.max(1, ...c.net.map(x => Math.abs(x.net)));
        const netBars = c.net.map(x => {
          const half = Math.max(2, Math.round(Math.abs(x.net) / mx * 48));
          return '<div style="display:flex;align-items:center;gap:8px;margin:5px 0;font-size:12px">'
            + '<div style="width:150px;flex:none;text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(x.entity) + '</div>'
            + '<div style="flex:1;height:15px;background:#eef2f7;border-radius:4px;position:relative"><div style="position:absolute;top:0;bottom:0;left:' + (x.net >= 0 ? 50 : 50 - half) + '%;width:' + half + '%;background:' + (x.net >= 0 ? "var(--grn)" : "var(--red)") + ';border-radius:3px"></div></div>'
            + '<div style="width:96px;flex:none;font-weight:600;color:' + (x.net >= 0 ? "var(--grn)" : "var(--red)") + '">' + (x.net >= 0 ? "+" : "\u2212") + Math.abs(x.net) + ' <span style="color:var(--mut);font-weight:400">(' + x.g + "\u2191 " + x.l + "\u2193)</span></div></div>";
        }).join("");
        const vRows = c.v2c.rows.map(r => '<tr style="border-bottom:1px solid #f1f5f9"><td style="padding:5px 6px">' + r[0] + '</td><td style="text-align:right;padding:5px 6px">' + r[1] + '</td><td style="text-align:right;padding:5px 6px">' + r[2] + '</td><td style="text-align:right;padding:5px 6px">' + r[3] + '</td></tr>').join("");
        html += '<div class="grid g2" style="margin-top:12px">'
              + '<div class="card" style="background:#fbfdfc"><h3>Net migration by category (gained \u2212 lost)</h3><div class="hd">customers whose 1st \u2192 2nd order crossed categories \u00b7 primary line per order</div>' + netBars + '</div>'
              + '<div class="card" style="background:#fbfdfc"><h3>V2V / V2C by entry category</h3><div class="hd">denominator = customers with a qualifying 2nd order</div>'
              + '<table style="width:100%;border-collapse:collapse;font-size:12.5px"><tr style="color:var(--mut);border-bottom:1px solid var(--line)">'
              + '<th style="text-align:left;padding:5px 6px">Entry category</th><th style="text-align:right;padding:5px 6px">Qualifying</th><th style="text-align:right;padding:5px 6px">V2V</th><th style="text-align:right;padding:5px 6px">V2C</th></tr>' + vRows + '</table></div></div>';
        if(c.jr.length || c.cuts.length){
          html += '<div class="card" style="background:#fbfdfc;margin-top:14px"><h3>Same-category retention</h3>'
                + '<div class="chips" style="margin:2px 0 8px">' + c.jr.map(x =>
                  '<div class="chip" style="background:#f1f5f7;color:var(--ink)">' + esc(x.label) + " \u00b7 " + esc(x.vlabel) + '</div>').join("") + '</div>'
                + '<div class="note">' + c.cuts.map(t => esc(t.text)).join("<br>") + '</div></div>';
        }
      }
      out.innerHTML = html;
      if(parts.any && parts.any.profile){
        const w = document.createElement("div");
        out.appendChild(w);
        LIVE.renderProfile(w, parts.any.profile);
      }
      if(html || (parts.any && parts.any.profile)) out.style.display = "";
    },
    function(){ out.style.display = "none"; out.innerHTML = ""; }
  );
})();
"""
"""
(function(){
  const el = document.getElementById("jLivePanel");
  const out = document.getElementById("jLiveOut");
  if(!el || !out || typeof LIVE === "undefined") return;
  LIVE.attach("jLivePanel",
    [{key:"journey", label:"Journey CSV (long form)", hint:"customer_id, order_date, category (+ product, sku, quantity, order_id)", params:{asOf: DATA.asOf}},
     {key:"any", label:"Any other CSV", hint:"generic structural analysis"}],
    function(parts){
      let html = "";
      if(parts.journey){
        const c = parts.journey;
        html += '<div class="kpis" style="margin:12px 0 4px">' + c.kpis.map(k =>
          '<div class="kpi"><div class="l">' + esc(k.label) + '</div><div class="v" style="font-size:19px">' + esc(k.value) + '</div><div class="s">' + esc(k.sub) + '</div></div>'
        ).join("") + '</div>';
        html += '<div class="grid g2" style="margin-top:12px">'
              + '<div class="card" style="background:#fbfdfc"><h3>Net migration by category (gained &minus; lost)</h3><div class="hd">customers whose 1st &rarr; 2nd order crossed categories · primary line per order</div><div id="jln"></div></div>'
              + '<div class="card" style="background:#fbfdfc"><h3>V2V / V2C by entry category</h3><div class="hd">denominator = customers with a qualifying 2nd order</div><div id="jlv"></div></div></div>';
        if(c.jr.length || c.cuts.length){
          html += '<div class="card" style="background:#fbfdfc;margin-top:14px"><h3>Same-category retention</h3><div id="jlr"></div><div class="note" id="jlc"></div></div>';
        }
        out.innerHTML = html;
        // net migration bars
        const nl = document.getElementById("jln");
        if(nl){
          const mx = Math.max.apply(1, c.net.map(x => Math.abs(x.net)));
          nl.innerHTML = c.net.map(x => {
            const half = Math.max(2, Math.round(Math.abs(x.net) / mx * 48));
            return '<div style="display:flex;align-items:center;gap:8px;margin:5px 0;font-size:12px">'
              + '<div style="width:150px;flex:none;text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(x.entity) + '</div>'
              + '<div style="flex:1;height:15px;background:#eef2f7;border-radius:4px;position:relative"><div style="position:absolute;top:0;bottom:0;left:' + (x.net >= 0 ? 50 : 50 - half) + '%;width:' + half + '%;background:' + (x.net >= 0 ? "var(--grn)" : "var(--red)") + ';border-radius:3px"></div></div>'
              + '<div style="width:96px;flex:none;font-weight:600;color:' + (x.net >= 0 ? "var(--grn)" : "var(--red)") + '">' + (x.net >= 0 ? "+" : "\u2212") + Math.abs(x.net) + ' <span style="color:var(--mut);font-weight:400">(' + x.g + '\u2191 ' + x.l + '\u2193)</span></div></div>';
          }).join("");
        }
        const vl = document.getElementById("jlv");
        if(vl){
          vl.innerHTML = '<table style="width:100%;border-collapse:collapse;font-size:12.5px"><tr style="color:var(--mut);border-bottom:1px solid var(--line)">'
            + '<th style="text-align:left;padding:5px 6px">Entry category</th><th style="text-align:right;padding:5px 6px">Qualifying</th><th style="text-align:right;padding:5px 6px">V2V</th><th style="text-align:right;padding:5px 6px">V2C</th></tr>'
            + c.v2c.rows.map(r => '<tr style="border-bottom:1px solid #f1f5f9"><td style="padding:5px 6px">' + r[0] + '</td><td style="text-align:right;padding:5px 6px">' + r[1] + '</td><td style="text-align:right;padding:5px 6px">' + r[2] + '</td><td style="text-align:right;padding:5px 6px">' + r[3] + '</td></tr>').join("")
            + '</table>';
        }
        const rl = document.getElementById("jlr");
        if(rl){
          rl.innerHTML = '<div class="chips" style="margin:2px 0 8px">' + c.jr.map(x =>
            '<div class="chip" style="background:#f1f5f7;color:var(--ink)">' + esc(x.label) + ' \u00b7 ' + esc(x.vlabel) + '</div>').join("") + '</div>';
        }
        const cl = document.getElementById("jlc");
        if(cl) cl.innerHTML = c.cuts.map(t => esc(t.text)).join("<br>");
      }
      if(parts.any && parts.any.profile){
        const w = document.createElement("div");
        out.appendChild(w);
        LIVE.renderProfile(w, parts.any.profile);
      }
      if(html || (parts.any && parts.any.profile)) out.style.display = "";
    },
    function(){ out.style.display = "none"; out.innerHTML = ""; }
  );
})();
"""

# ---------------------------------------------------------------------------
# page template (vanilla JS, no external refs)
# ---------------------------------------------------------------------------
PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>🔁 Retention & Repeat Behaviour — Moisturisers (D2C)</title>
<style>
@@LIVE_CSS@@
  :root{
    --bg:#f5f7f9; --card:#fff; --ink:#16232e; --mut:#64748b; --line:#e2e8f0;
    --acc:#0b6e4f; --chipbg:#e9f5f0;
    --cw:#0284c7; --hd:#d97706; --hh:#0d9488; --pm:#7c3aed; --cn:#64748b; --ac:#475569;
    --grn:#15803d; --red:#b91c1c; --amber:#b45309;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;font-size:13.5px}
  .wrap{max-width:1280px;margin:0 auto;padding:20px 22px 70px}
  header h1{font-size:22px;margin:0 0 4px}
  header .sub{color:var(--mut);font-size:12.5px;margin-bottom:12px}
  .chips{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}
  .chip{font-size:11px;background:var(--chipbg);color:var(--acc);border-radius:999px;padding:3px 10px;font-weight:600}
  .chip.g{background:#eef2f7;color:var(--mut)}
  /* filters */
  .fbar{position:sticky;top:0;z-index:20;background:#fff;border:1px solid var(--line);border-radius:12px;padding:10px 12px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px;box-shadow:0 2px 8px rgba(15,23,42,.06)}
  .fbar label{font-size:10.5px;color:var(--mut);text-transform:uppercase;letter-spacing:.4px;display:block;margin-bottom:2px}
  .fbar select,.fbar input{font-size:12.5px;padding:5px 8px;border:1px solid var(--line);border-radius:8px;background:#fff;min-width:104px}
  .fbar .cell{display:flex;flex-direction:column}
  .fbar button{margin-top:14px;font-size:12px;border:1px solid var(--line);background:#fff;border-radius:8px;padding:5px 12px;cursor:pointer}
  .fbar button:hover{background:#f1f5f9}
  .showing{font-size:12px;color:var(--mut);margin:0 2px 14px}
  .showing b{color:var(--ink)}
  /* sections */
  section{margin:26px 0}
  section>h2{font-size:16.5px;margin:0 0 2px}
  section>.sdesc{color:var(--mut);font-size:12px;margin:0 0 12px}
  .grid{display:grid;gap:14px}
  .g2{grid-template-columns:1fr 1fr}
  .g3{grid-template-columns:repeat(3,1fr)}
  .g4{grid-template-columns:repeat(4,1fr)}
  @media(max-width:1000px){.g2,.g3,.g4{grid-template-columns:1fr}}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
  .card h3{margin:0 0 4px;font-size:13.5px}
  .card .hd{font-size:11px;color:var(--mut);margin-bottom:8px}
  .note{font-size:11px;color:var(--mut);margin-top:8px;line-height:1.45}
  /* KPIs */
  .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin-bottom:6px}
  .kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
  .kpi .l{font-size:10.5px;color:var(--mut);text-transform:uppercase;letter-spacing:.4px}
  .kpi .v{font-size:22px;font-weight:700;margin-top:3px}
  .kpi .s{font-size:11px;color:var(--mut);margin-top:2px}
  /* insights */
  .insrow{display:grid;grid-template-columns:1fr 1fr;gap:10px}
  @media(max-width:900px){.insrow{grid-template-columns:1fr}}
  .ins{display:flex;gap:10px;align-items:flex-start;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:11px 13px;cursor:pointer;transition:border-color .15s}
  .ins:hover{border-color:var(--acc)}
  .ins .em{font-size:17px;line-height:1.2}
  .ins .tx{font-size:12.5px;line-height:1.45}
  .ins .ap{font-size:10.5px;color:var(--acc);font-weight:700;margin-left:auto;white-space:nowrap}
  /* bars & charts */
  .barchart{display:flex;align-items:flex-end;gap:3px;height:150px;padding-top:8px}
  .bcol{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;gap:3px;cursor:pointer;min-width:0}
  .bcol .bv{font-size:9.5px;color:var(--mut);height:11px}
  .bcol .bb{width:100%;border-radius:4px 4px 0 0;min-height:2px;transition:opacity .12s}
  .bcol .bl{font-size:9px;color:var(--mut);white-space:nowrap;overflow:hidden;max-width:100%}
  .bcol:hover .bb{opacity:.75}
  .bcol.sel .bb{outline:2px solid var(--ink);outline-offset:1px}
  .bcol.na .bb{background:repeating-linear-gradient(45deg,#e2e8f0,#e2e8f0 4px,#f1f5f9 4px,#f1f5f9 8px)!important;cursor:not-allowed}
  .hbars .hb{display:grid;grid-template-columns:170px 1fr 92px;gap:8px;align-items:center;margin:6px 0;font-size:12px;cursor:pointer}
  .hbars .hb:hover .tr{outline:2px solid var(--ink);outline-offset:1px}
  .hbars .tr{background:#f1f5f9;border-radius:6px;height:16px;overflow:hidden}
  .hbars .fl{height:100%;border-radius:6px}
  .hbars .vl{font-variant-numeric:tabular-nums;color:var(--mut);text-align:right;font-size:11.5px}
  .legend{display:flex;gap:12px;flex-wrap:wrap;font-size:11px;color:var(--mut);margin-top:8px}
  .legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:4px;vertical-align:-1px}
  /* tables */
  table{border-collapse:collapse;width:100%;font-size:12px}
  th{font-size:10.5px;text-transform:uppercase;letter-spacing:.3px;color:var(--mut);text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);cursor:pointer;user-select:none;white-space:nowrap}
  th.num,td.num{text-align:right;font-variant-numeric:tabular-nums}
  td{padding:6px 8px;border-bottom:1px solid #f1f5f9}
  tbody tr{cursor:pointer}
  tbody tr:hover{background:#f8fafc}
  .heat td{font-variant-numeric:tabular-nums;text-align:center;border:2px solid #fff}
  .na-pill{display:inline-block;font-size:10px;font-weight:700;background:#eef1f5;color:var(--mut);border-radius:999px;padding:1px 7px}
  .pill{display:inline-block;font-size:10.5px;border-radius:999px;padding:1px 8px;font-weight:600}
  .pill.g{background:#e8f5ec;color:var(--grn)} .pill.r{background:#fdeceb;color:var(--red)}
  .pill.n{background:#eef1f5;color:var(--mut)} .pill.b{background:#e0f2fe;color:#0369a1}
  .tile{border:1px solid var(--line);border-radius:10px;padding:10px 12px;cursor:pointer}
  .tile:hover{border-color:var(--acc)}
  .tile .n{font-size:20px;font-weight:700}
  .tile .t{font-size:11px;color:var(--mut);margin-top:2px;line-height:1.4}
  .tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
  @media(max-width:900px){.tiles{grid-template-columns:repeat(2,1fr)}}
  /* explorer */
  .pager{display:flex;gap:8px;align-items:center;margin:8px 0;font-size:12px}
  .pager button{border:1px solid var(--line);background:#fff;border-radius:8px;padding:4px 12px;cursor:pointer}
  .xrow td:first-child{font-weight:600}
  .tl{background:#f8fafc;border-radius:8px;padding:8px 12px;font-size:12px;margin:2px 0 6px}
  .tl .o{margin:4px 0}
  .tl .o b{font-size:11px;color:var(--mut)}
  details.defs{background:#fff;border:1px solid var(--line);border-radius:12px;padding:14px 18px}
  details.defs summary{cursor:pointer;font-weight:700;font-size:13.5px}
  details.defs ul{margin:8px 0 0;padding-left:18px;font-size:12px;color:#334155;line-height:1.6}
  .small{font-size:11px;color:var(--mut)}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>🔁 Retention & Repeat Behaviour — Moisturisers (D2C)</h1>
  <div class="sub" id="scopeLine"></div>
</header>
<div class="chips" id="headChips"></div>

<div class="fbar" id="fbar">
  <div class="cell"><label>Category</label><select id="fCat"></select></div>
  <div class="cell"><label>Variant</label><select id="fVar"></select></div>
  <div class="cell"><label>Entry size</label><select id="fSize"></select></div>
  <div class="cell"><label>Entry from</label><select id="fFrom"></select></div>
  <div class="cell"><label>Entry to</label><select id="fTo"></select></div>
  <div class="cell"><label>Journey depth</label><select id="fDepth"></select></div>
  <div class="cell"><label>Region</label><select id="fRegion"></select></div>
  <div class="cell"><label>Repeaters</label><select id="fRepeat"><option value="-1">All</option><option value="1">Repeaters (2+)</option><option value="0">One-timers</option></select></div>
  <div class="cell" style="min-width:130px"><label>City search</label><input id="fCity" type="text" placeholder="type a city…"></div>
  <button id="fReset">↺ Reset all</button>
</div>
<div class="showing" id="showing"></div>

<div class="kpis" id="kpis"></div>

<section>
  <h2>📂 Live data — analyse your own journey export in your browser</h2>
  <p class="sdesc">the charts and explorer below run on the <b>bundled base sheet</b>; drop your own CSV(s) here and the same rules (V2V/V2C, net migration, repeat rate, same-category retention, primary-line tie-break) are recomputed client-side — nothing is uploaded anywhere</p>
  <div class="card">
    <div id="jLivePanel"></div>
    <div id="jLiveOut" style="display:none;margin-top:12px"></div>
  </div>
</section>

<section>
  <h2>⚡ Deep-cut insights</h2>
  <p class="sdesc">auto-detected from the current cohort · click a card to apply the filter behind the finding</p>
  <div class="insrow" id="insights"></div>
</section>

<section>
  <h2>Retention &amp; repurchase</h2>
  <p class="sdesc">the 1st→2nd order step is the funnel — curves show who comes back, how fast, and in what mix</p>
  <div class="grid g2">
    <div class="card"><h3 id="retCurveTitle">Retention curve — share of entry customers with a 2nd order within X days</h3>
      <div class="hd">mature cohorts only (cohort month + X ≤ as-of) · <span class="na-pill">N/A</span> = not yet observable, never 0%</div>
      <div class="barchart" id="retCurve"></div>
    </div>
    <div class="card"><h3>Repeat rate by entry month</h3>
      <div class="hd">share of entry customers with a 2nd order · click a bar to filter · hatched = immature cohort (observed &lt; 90 days)</div>
      <div class="barchart" id="repeatByMonth"></div>
    </div>
  </div>
  <div class="grid g2" style="margin-top:14px">
    <div class="card"><h3>Repurchase gap distribution</h3>
      <div class="hd">days between consecutive orders of the same customer (all order-to-order gaps in the cohort)</div>
      <div class="barchart" id="gapDist"></div>
    </div>
    <div class="card"><h3>Loyalty metrics</h3>
      <div class="hd">V2V = 2nd order is the same product as the entry order (incl. size) · V2C = 2nd order stays in the entry category</div>
      <div id="loyGrid" class="grid g3" style="grid-template-columns:repeat(3,1fr)"></div>
      <div class="note" id="loyNote"></div>
    </div>
  </div>
</section>

<section>
  <h2>Demand over time</h2>
  <p class="sdesc">when the cohort actually orders · click a bar to filter entries to that month</p>
  <div class="grid g2">
    <div class="card"><h3>Orders by month <span class="small" style="font-weight:400">〰 3-mo trend</span></h3>
      <div class="hd">all orders placed by cohort customers</div>
      <div class="barchart" id="ordersByMonth"></div>
    </div>
    <div class="card"><h3>Category mix</h3>
      <div class="hd">orders touching each moisturiser line · click a slice to filter</div>
      <div style="display:flex;gap:18px;align-items:center;flex-wrap:wrap">
        <svg id="catDonut" width="170" height="170" viewBox="0 0 42 42"></svg>
        <div id="catLegend"></div>
      </div>
    </div>
  </div>
</section>

<section>
  <h2>Seasonality</h2>
  <p class="sdesc">intended season line (product season tag, else SKU code) vs actual calendar purchase timing</p>
  <div class="tiles" id="seasonTiles" style="margin-bottom:14px"></div>
  <div class="card"><h3>Purchase timing of cohort orders</h3>
    <div class="hd">orders by calendar season · Cold Winter Dec–Feb · Hot Dry Mar–May · Hot Humid Jun–Sep · Post-Monsoon Oct–Nov · click to filter entries to that season's months</div>
    <div class="barchart" id="seasonBars" style="height:120px"></div>
  </div>
</section>

<section>
  <h2>Portfolio &amp; cohort shape</h2>
  <p class="sdesc">every bar and chip is clickable — it sets the matching filter</p>
  <div class="grid g2">
    <div class="card"><h3>Top variants by orders</h3><div class="hd">colour = intended season line · click to filter</div><div class="hbars" id="topVars"></div></div>
    <div class="card"><h3>Journey depth</h3><div class="hd">customers by total orders (depth 6 = 6+) · click to filter</div><div class="hbars" id="depthBars"></div></div>
  </div>
  <div class="grid g2" style="margin-top:14px">
    <div class="card"><h3>Customers by region</h3><div class="hd">click to filter</div><div class="hbars" id="regionBars"></div></div>
    <div class="card"><h3>Top cities — click to filter</h3><div id="cityChips" style="display:flex;gap:6px;flex-wrap:wrap"></div></div>
  </div>
</section>

<section>
  <h2>Geography × seasonality</h2>
  <p class="sdesc">where each season sells · click any row to filter that region</p>
  <div class="grid g2">
    <div class="card"><h3>Region × purchase timing</h3><div class="hd">share of each region's orders by calendar season — darker = stronger skew</div><div id="heatCal"></div></div>
    <div class="card"><h3>Region × season line</h3><div class="hd">share of each region's orders by the variant's intended season line</div><div id="heatLine"></div></div>
  </div>
  <div class="grid g2" style="margin-top:14px">
    <div class="card"><h3>Affinity index</h3><div class="hd">region share of a segment ÷ national share · 1.00 = exactly average</div><div id="affinity" class="hbars"></div></div>
    <div class="card"><h3>Region loyalty</h3><div class="hd">click a row to filter</div><div id="regionLoy"></div></div>
  </div>
</section>

<section>
  <h2>Switching behaviour</h2>
  <p class="sdesc">entry order → 2nd order, primary (first) product of each order</p>
  <div class="grid g2">
    <div class="card"><h3>Most common transitions</h3><div class="hd">click a row to filter to that entry variant</div><div id="transitions"></div></div>
    <div class="card"><h3>Size &amp; format flows</h3><div class="hd">how the 2nd order compares to the entry SKU</div><div class="tiles" id="flowTiles" style="grid-template-columns:repeat(2,1fr)"></div><div class="note" id="flowNote"></div></div>
  </div>
</section>

<section>
  <h2>Variant summary</h2>
  <p class="sdesc">one row per entry variant · click a header to sort · click a row to filter by that variant</p>
  <div class="card" style="overflow-x:auto"><div id="varTable"></div></div>
</section>

<section>
  <h2>Journey explorer</h2>
  <p class="sdesc">the filtered cohort, customer by customer · click a row to expand its full timeline</p>
  <div class="card">
    <div class="pager">
      <button id="pgPrev">⬅ Prev</button><span id="pgLbl"></span><button id="pgNext">Next ➡</button>
      <span style="flex:1"></span><button id="pgExport">⬇ Export filtered CSV</button>
    </div>
    <div id="explorer" style="overflow-x:auto"></div>
  </div>
</section>

<details class="defs" open>
  <summary>📖 Definitions, filters &amp; SKU decoder</summary>
  <ul>
    <li><b>Cohort semantics:</b> Category / Variant / Size / From–To filters apply to each customer's <b>first (entry) order</b>; Depth, Region, City and Repeaters apply to the whole journey. Metrics, charts and tables all recompute for the selected cohort.</li>
    <li><b>Seasons (calendar):</b> Cold Winter Dec–Feb · Hot Dry Mar–May · Hot Humid Jun–Sep · Post-Monsoon Oct–Nov. <b>Intended line</b> is read from the SKU code; on-season lift = share of a variant's orders inside its intended window ÷ that window's baseline share of all orders. <b>Strength:</b> Highly ≥40% of orders in the peak calendar season · Moderately 30–40% · Evergreen &lt;30%.</li>
    <li><b>Loyalty:</b> V2V % — repeat customers whose 2nd order repeats an entry <i>variant</i>; V2C % — 2nd order stays in an entry <i>category</i> (same denominator). Retention curve — share of entry customers with any 2nd order within X days; a cohort is mature only when cohort-month + X ≤ as-of (otherwise <b>N/A, never 0%</b>).</li>
    <li><b>Flows:</b> Same product = identical SKU · Upsized = larger size · Lateral = same size, different product · Downsized = smaller size (primary SKU vs primary SKU).</li>
    <li><b>Geography:</b> heat cells show each region's order share per calendar season / intended line — darker means a stronger skew. Affinity index = region's share of a segment ÷ national share (1.00× = exactly average; gel-line and winter-line affinities shown). Major metros are classified to North/West/South/East; the remaining ~400 smaller cities are grouped as <b>Rest of India</b> (documented classification, not a business result).</li>
    <li><b>SKU code</b> <code>FC-&lt;LINE&gt;-&lt;VARIANT&gt;-&lt;SIZE&gt;</code> — e.g. <code>FC-HDDM-FB-050</code> = Face Malai · Hot Dry · Flax Bakuchi · 50g. Lines: CWDM Cold Winter · HDDM Hot Dry · HHDM Hot Humid · DM non-seasonal concern · AC Active Gel · HG Aloe Vera Gel.</li>
    <li><b>Scope &amp; provenance:</b> the customer journey base sheet (D2C channel, Moisturisers categories, all users, first 6 orders per customer). Multi-item orders count for every item in tiles/loyalty and by their first SKU in transitions. Same-day items merge into one order. All figures recompute in-browser from the embedded per-customer data — nothing is uploaded anywhere.</li>
  </ul>
</details>

<div class="small" id="foot" style="margin-top:14px"></div>
</div>

<script>
@@DATA@@
</script>
<script>
"use strict";
/* ================= state ================= */
const S = {cat:-1, var:-1, size:-1, from:-1, to:-1, depth:-1, region:-1, repeat:-1, city:-1, cityQ:""};
const N = DATA.nCustomers;
const LINE_COLOR = ["#0284c7","#d97706","#0d9488","#64748b","#475569","#7c3aed"];
const SEASON_COLOR = ["#0284c7","#d97706","#0d9488","#7c3aed"];
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const pct = (x, d=1) => (x==null || isNaN(x)) ? "—" : (x*100).toFixed(d) + "%";
const fmtI = x => (x==null||isNaN(x)) ? "—" : Math.round(x).toLocaleString("en-US");
const monthIdx = m => DATA.months.indexOf(m);
const monthName = m => DATA.monthLbl[monthIdx(m)] ?? m;
function seasonOf(m){ return DATA.calSeason[String(m===12?12:m)]; }
function daysFromEntry(c, k){ // cumulative day offset of order k (0-based)
  let d = 0; for(let i=0;i<k;i++) d += (DATA.custGaps[c][i] > 0 ? DATA.custGaps[c][i] : 0); return d;
}
function orderDate(c, k){
  const base = new Date(DATA.custEntry[c]);
  base.setDate(base.getDate() + daysFromEntry(c, k));
  return base;
}
function matches(c){
  if(S.cat >= 0 && DATA.custCat[c] !== S.cat) return false;
  if(S.var >= 0 && DATA.custVar[c] !== S.var) return false;
  if(S.size >= 0 && DATA.custSize[c] !== S.size) return false;
  const mo = DATA.custMonth[c];
  if(S.from >= 0 && mo < S.from) return false;
  if(S.to >= 0 && mo > S.to) return false;
  if(S.depth >= 0 && DATA.custDepth[c] !== S.depth) return false;
  if(S.region >= 0 && DATA.custRegion[c] !== S.region) return false;
  if(S.repeat >= 0 && DATA.custRepeat[c] !== S.repeat) return false;
  if(S.city >= 0 && DATA.custCity[c] !== S.city) return false;
  if(S.cityQ){ const q = S.cityQ.toLowerCase(); if(!DATA.cities[DATA.custCity[c]].toLowerCase().includes(q)) return false; }
  return true;
}
function filtered(){
  const out = [];
  for(let c=0;c<N;c++) if(matches(c)) out.push(c);
  return out;
}
/* baseline window shares (all orders in the dataset, by calendar month) */
function baselineWindowShare(months){
  let tot = 0, win = 0;
  for(let c=0;c<N;c++){
    const items = DATA.custItems[c];
    for(let k=0;k<items.length;k++){
      const d = orderDate(c,k); const m = d.getMonth()+1;
      tot++;
      if(months.includes(m)) win++;
    }
  }
  return tot ? win/tot : 0;
}
/* ================= filter UI ================= */
function fillSel(id, label, arr, sel, valMap){
  const el = document.getElementById(id);
  let h = `<option value="-1">${label}</option>`;
  arr.forEach((v,i)=>{ h += `<option value="${valMap?valMap(v,i):i}" ${i===sel?"selected":""}>${v}</option>`; });
  el.innerHTML = h;
}
function initFilters(){
  const sel = (id, fn) => document.getElementById(id).addEventListener("change", e => { fn(parseInt(e.target.value,10)); apply(); });
  fillSel("fCat","All",DATA.cats,S.cat); sel("fCat", v=>S.cat=v);
  fillSel("fVar","All",DATA.vars,S.var); sel("fVar", v=>S.var=v);
  const sizes = [...new Set(DATA.custSize)].filter(s=>s>0).sort((a,b)=>a-b);
  const sizeLbl = s => s<=100 ? s+"g" : s+"ml";
  fillSel("fSize","All",sizes.map(sizeLbl),S.size, (v,i)=>sizes[i]); sel("fSize", v=>S.size=v);
  const allM = DATA.monthLbl.map((l,i)=>({l,i}));
  const hF = `<option value="-1">All</option>` + allM.map(o=>`<option value="${o.i}">${o.l}</option>`).join("");
  document.getElementById("fFrom").innerHTML = hF;
  document.getElementById("fTo").innerHTML = hF;
  sel("fFrom", v=>{S.from=v; if(S.to>=0 && S.to<S.from) S.to=v; syncRange(); apply();});
  sel("fTo", v=>{S.to=v; if(S.from>=0 && S.from>S.to) S.from=v; syncRange(); apply();});
  const dEl = document.getElementById("fDepth");
  dEl.innerHTML = `<option value="-1">All</option>` + [1,2,3,4,5,6].map(dd=>
    `<option value="${dd}" ${S.depth===dd?"selected":""}>${dd} order${dd>1?"s":""}</option>`).join("");
  sel("fDepth", v=>S.depth=v);
  fillSel("fRegion","All",DATA.regions,S.region); sel("fRegion", v=>S.region=v);
  sel("fRepeat", v=>S.repeat=v);
  document.getElementById("fCity").addEventListener("input", e=>{ S.cityQ=e.target.value.trim(); S.city=-1; apply(); });
  document.getElementById("fReset").onclick = ()=>{
    Object.assign(S,{cat:-1,var:-1,size:-1,from:-1,to:-1,depth:-1,region:-1,repeat:-1,city:-1,cityQ:""});
    syncAll(); apply();
  };
  syncAll();
}
function syncAll(){
  const set = (id,v)=>{ document.getElementById(id).value = v; };
  set("fCat",S.cat); set("fVar",S.var); set("fSize",S.size); set("fDepth",S.depth);
  set("fRegion",S.region); set("fRepeat",S.repeat);
  document.getElementById("fCity").value = S.cityQ;
  syncRange();
}
function syncRange(){
  document.getElementById("fFrom").value = S.from;
  document.getElementById("fTo").value = S.to;
}
/* ================= header / KPIs ================= */
function computeCohort(F){
  const C = {n:F.length, orders:0, rep:0, v2v:0, v2c:0, gaps:[], v2vDays:[], v2cDays:[],
             v2vOrders:[], v2cOrders:[], trans:{}, flows:{same:0,up:0,lat:0,down:0},
             seasonOrders:[0,0,0,0], lineOrders:[0,0,0,0,0,0],
             catTouch:new Array(DATA.cats.length).fill(0),
             ordersByMonth:new Array(DATA.months.length).fill(0),
             depth:[0,0,0,0,0,0], region:[0,0,0,0,0], city:{},
             retByMonth:[], variant:{}};
  for(const c of F){
    C.orders += DATA.custDepth[c];
    C.depth[DATA.custDepth[c]-1]++;
    C.region[DATA.custRegion[c]]++;
    const city = DATA.cities[DATA.custCity[c]];
    C.city[city] = (C.city[city]||0)+1;
    const items = DATA.custItems[c];
    const itcat = DATA.custItemCat[c];
    const gaps = DATA.custGaps[c];
    for(let k=0;k<items.length;k++){
      const d = orderDate(c,k);
      const mi = monthIdx(`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}`);
      if(mi>=0) C.ordersByMonth[mi]++;
      const s = seasonOf(d.getMonth()+1);
      C.seasonOrders[s]++;
      const lines = new Set(); items[k].forEach(i=>{ if(i>0) lines.add(DATA.prods[i].l); });
      lines.forEach(l=>C.lineOrders[l]++);
      const cats = new Set(); itcat[k].forEach(cj=>{ if(cj>=0) cats.add(cj); });
      cats.forEach(cat=>C.catTouch[cat]++);
    }
    if(gaps.length){
      gaps.forEach(g=>{ if(g>0) C.gaps.push(g); });
      // loyalty (primary = first line of each order; identical to the model's
      // v2v_v2c_analysis: V2V = same product name — NaN product never matches;
      // V2C = same per-row category, counted even when the product is unparseable)
      const s1 = items[0][0], s2 = items[1][0];
      const c1 = itcat[0][0], c2 = itcat[1][0];
      const g12 = gaps[0];
      if(s1>0 && s2>0){
        const k1 = DATA.prods[s1], k2 = DATA.prods[s2];
        if(k1.raw === k2.raw){ C.v2v++; if(g12>0) C.v2vDays.push(g12); C.v2vOrders.push(DATA.custDepth[c]); }
        const key = k1.n + " → " + k2.n;
        C.trans[key] = (C.trans[key]||0)+1;
        if(s1 === s2) C.flows.same++;
        else if(k2.s > k1.s) C.flows.up++;
        else if(k2.s < k1.s) C.flows.down++;
        else C.flows.lat++;
      }
      if(c1>=0 && c2>=0 && c1===c2){ C.v2c++; if(g12>0) C.v2cDays.push(g12); C.v2cOrders.push(DATA.custDepth[c]); }
    }
    if(gaps.length) C.rep++;
    // retention by entry month (maturity aware)
    const em = DATA.custMonth[c];
    if(!C.retByMonth[em]) C.retByMonth[em] = {n:0, r:0};
    C.retByMonth[em].n++;
    if(gaps.length && gaps[0] > 0) C.retByMonth[em].r++;
    // variant stats
    const v = DATA.custVar[c];
    if(!C.variant[v]) C.variant[v] = {seas:[0,0,0,0], n:0, rep:0, d12:[]};
    C.variant[v].n++;
    if(gaps.length){ C.variant[v].rep++; if(gaps[0]>0) C.variant[v].d12.push(gaps[0]); }
    for(let k=0;k<items.length;k++){
      const d = orderDate(c,k);
      C.variant[v].seas[seasonOf(d.getMonth()+1)]++;
    }
  }
  return C;
}
function median(a){ if(!a.length) return null; const s=[...a].sort((x,y)=>x-y); const m=s.length>>1; return s.length%2?s[m]:(s[m-1]+s[m])/2; }
function quant(a,q){ if(!a.length) return null; const s=[...a].sort((x,y)=>x-y); const p=(s.length-1)*q; const b=Math.floor(p); return s[b]+(s[b+1]!=null?(s[b+1]-s[b])*(p-b):0); }
function renderHeader(F,C){
  const asOf = DATA.asOf;
  document.getElementById("scopeLine").textContent =
    "Customer journey base sheet · D2C channel · Moisturisers · all users · first 6 orders per customer · " +
    DATA.months[0] + " → " + DATA.months[DATA.months.length-1] + " · as-of " + asOf;
  document.getElementById("headChips").innerHTML =
    `<span class="chip">🧴 ${fmtI(N)} customers · ${fmtI(DATA.nOrders)} orders</span>` +
    `<span class="chip">❄ intended lines: product season tags, else SKU code</span>` +
    `<span class="chip">🔁 ${fmtI(DATA.custRepeat.reduce((a,b)=>a+b,0))} repeat buyers overall (${pct(DATA.custRepeat.reduce((a,b)=>a+b,0)/N)})</span>` +
    `<span class="chip g">charts &amp; tables are clickable — they set filters</span>`;
  const rep = C.rep, repR = rep/C.n;
  const v2v = rep ? C.v2v/rep : null, v2c = rep ? C.v2c/rep : null;
  const med = median(C.gaps), q1 = quant(C.gaps,.25), q3 = quant(C.gaps,.75);
  const kpis = [
    ["Customers in cohort", fmtI(C.n), "entry orders only"],
    ["Total orders", fmtI(C.orders), `avg ${(C.orders/C.n).toFixed(2)} per customer`],
    ["Repeat buyers", fmtI(rep), "2+ moisturiser orders"],
    ["Repeat rate", pct(repR), `V2V ${pct(v2v,1)} · V2C ${pct(v2c,1)}`],
    ["Median repurchase gap", med==null?"—":fmtI(med)+" d", med==null?"":`p25 ${fmtI(q1)} d · p75 ${fmtI(q3)} d`],
    ["Months with orders", C.ordersByMonth.filter(x=>x>0).length, `${monthName(DATA.months[0])} → ${monthName(DATA.months[DATA.months.length-1])}`],
  ];
  document.getElementById("kpis").innerHTML = kpis.map(k=>
    `<div class="kpi"><div class="l">${k[0]}</div><div class="v">${k[1]}</div><div class="s">${k[2]}</div></div>`).join("");
  document.getElementById("showing").innerHTML =
    `Showing <b>${fmtI(C.n)}</b> of <b>${fmtI(N)}</b> loaded customers (${pct(C.n/N)}) · <b>${fmtI(C.orders)}</b> moisturiser orders · orders span ${monthName(DATA.months[0])} → ${monthName(DATA.months[DATA.months.length-1])}` +
    (Object.values(S).some(v=>v!==-1 && v!=="") || S.cityQ ? " · <b>filtered</b> — click ↺ Reset all to clear" : " · No filters — showing the full loaded cohort");
}
/* ================= insights ================= */
function renderInsights(F,C){
  const out = [];
  const minN = 30;
  // 1 · most seasonal variant (on-season lift)
  let best = null;
  for(const v in C.variant){
    const vs = C.variant[v]; if(vs.n < minN) continue;
    const line = DATA.prods[firstProdOfVariant(+v)].l;
    const win = DATA.lineWindow[String(line)]; if(!win || !win.length) continue;
    const tot = vs.seas.reduce((a,b)=>a+b,0); if(!tot) continue;
    const inWin = win.reduce((a,m)=>a+vs.seas[seasonOf(m)],0);
    const base = baselineWindowShare(win); if(!base) continue;
    const lift = (inWin/tot)/base;
    if(!best || lift > best.lift) best = {v:+v, lift, share:inWin/tot, win};
  }
  if(best){
    const vn = DATA.vars[best.v], line = DATA.lines[DATA.prods[firstProdOfVariant(best.v)].l];
    out.push({em:"📈", html:`<b>${esc(vn)}</b> is the most seasonal — <b>${pct(best.share)}</b> of its orders land in its intended ${line} window (<b>${best.lift.toFixed(1)}×</b> baseline).`,
      fn:()=>{S.var=best.v; syncAll(); apply();}});
  }
  // 2 · best-repeating region
  let br = null;
  DATA.regions.forEach((r,ri)=>{
    const n = C.region[ri]; if(n < minN) return;
    const sub = F.filter(c=>DATA.custRegion[c]===ri);
    const rr = sub.filter(c=>DATA.custRepeat[c]).length/n;
    if(!br || rr > br.rr) br = {r, ri, rr, n, v2v: null};
  });
  const repR = C.rep/C.n;
  if(br && br.rr > repR){
    out.push({em:"🔁", html:`<b>${br.r}</b> repeats best — <b>${pct(br.rr)}</b> repeat rate vs <b>${pct(repR)}</b> overall (${fmtI(br.n)} customers).`,
      fn:()=>{S.region=br.ri; syncAll(); apply();}});
  }
  // 3 · entry-season repeat effect
  let bs = null;
  for(let s=0;s<4;s++){
    let n=0, r=0;
    for(const c of F){
      if(seasonOf(orderDate(c,0).getMonth()+1)===s){ n++; if(DATA.custRepeat[c]) r++; }
    }
    if(n < minN) continue;
    if(!bs || r/n > bs.rr) bs = {s, rr:r/n, n};
  }
  if(bs){
    out.push({em:"🗓️", html:`Customers entering in <b>${DATA.seasons[bs.s]}</b> repeat at <b>${pct(bs.rr)}</b> vs <b>${pct(repR)}</b> overall.`,
      fn:()=>applySeasonMonths(bs.s)});
  }
  // 4 · best-repeating entry month
  let bm = null;
  for(const em in C.retByMonth){
    const rb = C.retByMonth[em]; if(rb.n < minN) continue;
    const d0 = new Date(DATA.months[em]+"-01");
    const dA = new Date(DATA.asOf);
    if((dA - d0)/86400000 < 90) continue; // immature
    const rr = rb.r/rb.n;
    if(!bm || rr > bm.rr) bm = {em:+em, rr, n:rb.n};
  }
  if(bm){
    out.push({em:"📅", html:`<b>${monthName(DATA.months[bm.em])}</b> entrants repeat best — <b>${pct(bm.rr)}</b> (${fmtI(bm.n)} customers).`,
      fn:()=>{S.from=bm.em; S.to=bm.em; syncAll(); apply();}});
  }
  // 5 · top city concentration
  const topCity = Object.entries(C.city).sort((a,b)=>b[1]-a[1])[0];
  if(topCity && topCity[1]/C.n >= 0.1){
    const ci = DATA.cities.indexOf(topCity[0]);
    out.push({em:"📍", html:`<b>${esc(topCity[0])}</b> drives <b>${pct(topCity[1]/C.n)}</b> of the cohort (${fmtI(topCity[1])} customers).`,
      fn:()=>{S.city=ci; syncAll(); apply();}});
  }
  // 6 · size-flow pressure
  const tot = C.flows.same+C.flows.up+C.flows.lat+C.flows.down;
  if(tot >= minN){
    if(C.flows.down > C.flows.up){
      out.push({em:"📉", html:`Downsize pressure — <b>${pct(C.flows.down/tot)}</b> of 2nd orders are a smaller size than entry, vs <b>${pct(C.flows.up/tot)}</b> upsized (${fmtI(tot)} transitions).`,
        fn:()=>{S.repeat=1; syncAll(); apply();}});
    } else {
      out.push({em:"📈", html:`Upsize momentum — <b>${pct(C.flows.up/tot)}</b> of 2nd orders move to a larger size vs <b>${pct(C.flows.down/tot)}</b> downsize (${fmtI(tot)} transitions).`,
        fn:()=>{S.repeat=1; syncAll(); apply();}});
    }
  }
  // 7 · fastest repeat
  if(C.v2vDays.length >= minN){
    const m = median(C.v2vDays);
    out.push({em:"⚡", html:`Fastest loop — median time from 1st to a repeat <b>variant</b> order is <b>${fmtI(m)} days</b> (${fmtI(C.v2vDays.length)} V2V transitions).`,
      fn:()=>{S.repeat=1; syncAll(); apply();}});
  }
  document.getElementById("insights").innerHTML = out.slice(0,6).map(i=>
    `<div class="ins" data-i="${out.indexOf(i)}"><span class="em">${i.em}</span><span class="tx">${i.html}</span><span class="ap">apply ↗</span></div>`).join("") ||
    `<div class="note">Not enough data in this cohort for auto-detected findings.</div>`;
  out.slice(0,6).forEach((i,ix)=>{
    const el = document.querySelector(`.ins[data-i="${ix}"]`);
    if(el) el.onclick = i.fn;
  });
}
function firstProdOfVariant(v){ return DATA.varFirstProd[String(v)] ?? 0; }
function seasonRange(s){ // [first, last] month index in the data whose calendar season is s
  let a = -1, b = -1;
  DATA.months.forEach((m,i)=>{ if(seasonOf(+m.slice(5,7))===s){ if(a<0) a=i; b=i; } });
  return [a,b];
}
function applySeasonMonths(s){
  const [a,b] = seasonRange(s);
  if(a>=0){ S.from=a; S.to=b; syncAll(); apply(); }
}
/* ================= chart helpers ================= */
function barChart(el, items, opts={}){
  // items: {label, value, sub, na, color, sel, onClick}
  const max = Math.max(...items.map(i=>i.value||0), 1);
  el.innerHTML = "";
  items.forEach(it=>{
    const col = document.createElement("div");
    col.className = "bcol" + (it.na?" na":"") + (it.sel?" sel":"");
    const h = it.na ? 8 : Math.max(2, (it.value||0)/max*100);
    col.innerHTML = `<div class="bv">${it.na?"":(it.vlabel??(it.value||0))}</div>
      <div class="bb" style="height:${h}%;background:${it.color||"#0b6e4f"}"></div>
      <div class="bl">${it.label}</div>`;
    col.title = it.title || it.label;
    if(!it.na && it.onClick) col.onclick = it.onClick;
    el.appendChild(col);
  });
}
function hbarList(el, items, max){
  el.innerHTML = "";
  items.forEach(it=>{
    const row = document.createElement("div");
    row.className = "hb";
    const w = max ? (it.value/max*100) : 0;
    row.innerHTML = `<div>${it.label}</div><div class="tr"><div class="fl" style="width:${w}%;background:${it.color||"#0b6e4f"}"></div></div><div class="vl">${it.val}</div>`;
    if(it.onClick) row.onclick = it.onClick;
    el.appendChild(row);
  });
}
/* ================= sections ================= */
function renderRetCurve(F,C){
  const windows = [30,60,90,120,180,270,365];
  const asOf = new Date(DATA.asOf);
  const items = windows.map(w=>{
    let n=0, r=0;
    for(const c of F){
      const d0 = new Date(DATA.custEntry[c]);
      if((asOf - d0)/86400000 < w) continue; // immature for this customer (N/A, never 0%)
      n++;
      const g = DATA.custGaps[c];
      if(g.length && g[0] > 0 && g[0] <= w) r++;
    }
    const na = n < 10;
    return {label:w+"d", value: na?0:(r/n*100), na, vlabel: na?"":pct(r/n,0),
      title: na ? `${w}d: N/A — cohort not yet observable` : `${w}d: ${fmtI(r)} of ${fmtI(n)} entry customers`,
      onClick: null, color:"#0b6e4f"};
  });
  barChart(document.getElementById("retCurve"), items);
  const first = items.find(i=>!i.na);
  document.getElementById("retCurveTitle").innerHTML = "Retention curve — " +
    (first ? `only <b>${pct(first.value/100,1)}</b> of entry customers return within ${first.label}` : "not yet observable") +
    " · the 1st→2nd step is the bottleneck";
}
function renderRepeatByMonth(F,C){
  const asOf = new Date(DATA.asOf);
  const items = DATA.months.map((m,i)=>{
    const rb = C.retByMonth[i];
    const d0 = new Date(m+"-01");
    const mature = (asOf - d0)/86400000 >= 90;
    const v = rb ? rb.r/rb.n : 0;
    return {label:DATA.monthLbl[i], value: v*100, vlabel: mature ? pct(v,0) : "",
      na: !mature || !rb || rb.n < 5, sel: S.from===i && S.to===i,
      title: mature ? `${monthName(m)}: ${pct(v)} repeat (${rb?rb.n:0} customers)` : `${monthName(m)}: immature cohort (observed < 90 days)`,
      onClick: mature ? ()=>{S.from=i; S.to=i; syncAll(); apply();} : null, color:"#0b6e4f"};
  });
  barChart(document.getElementById("repeatByMonth"), items);
}
function renderGapDist(F,C){
  const buckets = [[1,14,"0–14"],[15,30,"15–30"],[31,60,"31–60"],[61,90,"61–90"],[91,120,"91–120"],
                   [121,180,"121–180"],[181,270,"181–270"],[271,365,"271–365"],[366,1e9,"365+"]];
  const counts = buckets.map(()=>0);
  C.gaps.forEach(g=>{ buckets.forEach((b,bi)=>{ if(g>=b[0] && g<=b[1]) counts[bi]++; }); });
  const total = counts.reduce((a,b)=>a+b,0);
  barChart(document.getElementById("gapDist"), buckets.map((b,i)=>({
    label:b[2], value:counts[i], vlabel: counts[i]?fmtI(counts[i]):"",
    title:`${b[2]} days: ${fmtI(counts[i])} gaps (${total?pct(counts[i]/total):"0%"})`,
    color:"#0b6e4f",
  })));
}
function renderLoyalty(F,C){
  const rep = C.rep;
  const v2v = rep?C.v2v/rep:null, v2c = rep?C.v2c/rep:null;
  const md = a => a.length? median(a) : null;
  const cells = [
    [pct(v2v,1), "V2V loyalty", "2nd order repeats entry product (incl. size)"],
    [pct(v2c,1), "V2C loyalty", "2nd order stays in entry category"],
    [md(C.v2vDays)==null?"—":fmtI(md(C.v2vDays))+" d", "Avg days to repeat · V2V", "median gap for V2V customers"],
    [md(C.v2cDays)==null?"—":fmtI(md(C.v2cDays))+" d", "Avg days to repeat · V2C", "median gap for V2C customers"],
    [C.v2vOrders.length?(C.v2vOrders.reduce((a,b)=>a+b,0)/C.v2vOrders.length).toFixed(2):"—", "Avg orders per V2V customer", "depth of variant-loyal repeaters"],
    [C.v2cOrders.length?(C.v2cOrders.reduce((a,b)=>a+b,0)/C.v2cOrders.length).toFixed(2):"—", "Avg orders per V2C customer", "depth of category-loyal repeaters"],
  ];
  document.getElementById("loyGrid").innerHTML = cells.map(c=>
    `<div class="kpi"><div class="v" style="font-size:19px">${c[0]}</div><div class="l" style="margin-top:4px">${c[1]}</div><div class="s">${c[2]}</div></div>`).join("");
  let note = "";
  const tk = Object.entries(C.trans).sort((a,b)=>b[1]-a[1]);
  if(tk.length){
    let bestV2V="", bestV2C="";
    for(const [k,n] of tk){
      const [a,b] = k.split(" → ");
      if(!bestV2V && a===b){ bestV2V = a; }
      if(!bestV2C) { const ai = prodByLabel(a), bi = prodByLabel(b); if(ai && bi && ai.c===bi.c && a!==b) bestV2C = b; }
    }
    note = `<b>${fmtI(rep)}</b> repeat customers · most common 2nd order — V2V: <b>${esc(bestV2V||"none")}</b> · V2C: <b>${esc(bestV2C||"none")}</b>`;
  }
  document.getElementById("loyNote").innerHTML = note;
}
function prodByLabel(lab){
  for(const k in DATA.prods){ if(DATA.prods[k].n===lab) return DATA.prods[k]; }
  return null;
}
function renderOrdersByMonth(F,C){
  const items = DATA.months.map((m,i)=>{
    const v = C.ordersByMonth[i];
    return {label:DATA.monthLbl[i], value:v, vlabel: v?fmtI(v):"", na:false,
      sel: S.from===i && S.to===i,
      title:`${monthName(m)}: ${fmtI(v)} orders`,
      onClick: ()=>{S.from=i; S.to=i; syncAll(); apply();}, color:"#0b6e4f"};
  });
  barChart(document.getElementById("ordersByMonth"), items);
  // 3-month trend overlay note
  const tot = C.orders;
  const last3 = C.ordersByMonth.slice(-3).reduce((a,b)=>a+b,0);
  const prev3 = C.ordersByMonth.slice(-6,-3).reduce((a,b)=>a+b,0);
  const g = prev3 ? (last3-prev3)/prev3 : null;
  const card = document.getElementById("ordersByMonth").closest(".card");
  let trend = card.querySelector(".trend");
  if(!trend){ trend = document.createElement("div"); trend.className="note trend"; card.appendChild(trend); }
  trend.innerHTML = g==null ? "" : `3-month trend: ${g>=0?"up":"down"} <b>${pct(Math.abs(g),0)}</b> (last 3 mo ${fmtI(last3)} vs previous 3 ${fmtI(prev3)}).`;
}
function renderCatMix(F,C){
  const tot = C.catTouch.reduce((a,b)=>a+b,0);
  const colors = ["#0b6e4f","#3b82f6","#8b5cf6"];
  let off = 0, legend = "";
  const svg = document.getElementById("catDonut");
  let circles = "";
  C.catTouch.forEach((v,i)=>{
    const frac = tot ? v/tot : 0;
    if(frac===0) return;
    circles += `<circle cx="21" cy="21" r="15.9155" fill="none" stroke="${colors[i%3]}" stroke-width="6"
      stroke-dasharray="${(frac*100).toFixed(2)} ${(100-frac*100).toFixed(2)}" stroke-dashoffset="${(25-off*100).toFixed(2)}"
      style="cursor:pointer" data-cat="${i}"></circle>`;
    off += frac;
    legend += `<div style="margin:4px 0;font-size:12px"><i style="display:inline-block;width:10px;height:10px;border-radius:3px;background:${colors[i%3]};margin-right:6px"></i>${esc(DATA.cats[i])} <b>${fmtI(v)}</b> (${pct(frac,0)})</div>`;
  });
  svg.innerHTML = circles + `<text x="21" y="20" text-anchor="middle" font-size="6" font-weight="700">${fmtI(tot)}</text>
    <text x="21" y="26" text-anchor="middle" font-size="3.4" fill="#64748b">orders touching line</text>`;
  svg.querySelectorAll("circle[data-cat]").forEach(cg=>{
    cg.onclick = ()=>{ S.cat = +cg.dataset.cat; syncAll(); apply(); };
  });
  document.getElementById("catLegend").innerHTML = legend;
}
function renderSeason(F,C){
  const totLine = C.lineOrders.slice(0,4).reduce((a,b)=>a+b,0);
  const tiles = [
    {i:0, icon:"❄", name:"Cold Winter", months:"Dec–Feb", line:"Cold Winter"},
    {i:1, icon:"☀", name:"Hot Dry", months:"Mar–May", line:"Hot Dry"},
    {i:2, icon:"🌧", name:"Hot Humid", months:"Jun–Sep", line:"Hot Humid"},
    {i:3, icon:"◉", name:"Concern-led", months:"non-seasonal", line:"Concern"},
  ];
  document.getElementById("seasonTiles").innerHTML = tiles.map(t=>{
    const v = C.lineOrders[t.i];
    return `<div class="tile${t.i<3?"":" style='cursor:default'"}" data-l="${t.i}">
      <div class="n" style="color:${LINE_COLOR[t.i]}">${fmtI(v)}</div>
      <div class="t"><b>${t.icon} ${t.name}</b> variant orders<br>${totLine?pct(v/totLine,1):"—"} of intent orders · ${t.months} line${t.i<3?" · click to filter entries":""}</div>
    </div>`;
  }).join("");
  document.querySelectorAll("#seasonTiles .tile").forEach(tl=>{
    const l = +tl.dataset.l;
    if(l<3) tl.onclick = ()=>applySeasonMonths(l);
  });
  const tot = C.seasonOrders.reduce((a,b)=>a+b,0);
  barChart(document.getElementById("seasonBars"), DATA.seasons.map((s,i)=>({
    label:s, value:C.seasonOrders[i], vlabel: tot?pct(C.seasonOrders[i]/tot,0):"",
    title:`${s}: ${fmtI(C.seasonOrders[i])} orders (${tot?pct(C.seasonOrders[i]/tot,0):"0%"})`,
    color:SEASON_COLOR[i],
    onClick: ()=>applySeasonMonths(i),
  })));
}
function renderPortfolio(F,C){
  // top variants by orders (order-level, any item)
  const vOrd = {};
  for(const c of F){
    const seen = new Set();
    DATA.custItems[c].forEach(o=>o.forEach(sk=>{ seen.add(sk); }));
    seen.forEach(sk=>{
      if(sk===0) return; // unparseable line
      const v = DATA.prods[sk].v;
      if(!vOrd[v]) vOrd[v] = {n:0, line: DATA.prods[sk].l};
      vOrd[v].n++;
    });
  }
  const top = Object.entries(vOrd).map(([v,o])=>({v:+v, ...o})).sort((a,b)=>b.n-a.n).slice(0,10);
  hbarList(document.getElementById("topVars"), top.map(t=>({
    label:`${DATA.vars[t.v]}`, value:t.n, val:`${fmtI(t.n)} (${pct(t.n/C.orders,0)})`,
    color:LINE_COLOR[t.line], onClick:()=>{S.var=t.v; syncAll(); apply();},
  })), top.length?top[0].n:1);
  hbarList(document.getElementById("depthBars"), [1,2,3,4,5,6].map(d=>({
    label:`${d} order${d>1?"s":""}`, value:C.depth[d-1],
    val:`${fmtI(C.depth[d-1])} (${pct(C.depth[d-1]/C.n,0)})`, color:"#0b6e4f",
    onClick:()=>{S.depth=d; syncAll(); apply();},
  })), Math.max(...C.depth,1));
  hbarList(document.getElementById("regionBars"), DATA.regions.map((r,ri)=>({
    label:r, value:C.region[ri], val:`${fmtI(C.region[ri])} (${pct(C.region[ri]/C.n,0)})`,
    color:"#3b82f6", onClick:()=>{S.region=ri; syncAll(); apply();},
  })), Math.max(...C.region,1));
  const topCities = Object.entries(C.city).sort((a,b)=>b[1]-a[1]).slice(0,12);
  document.getElementById("cityChips").innerHTML = topCities.map(([ct,n])=>{
    const ci = DATA.cities.indexOf(ct);
    return `<span class="pill ${S.city===ci?"b":"n"}" data-ci="${ci}" style="cursor:pointer;font-size:11.5px">${esc(ct)} <b>${fmtI(n)}</b></span>`;
  }).join(" ");
  document.querySelectorAll("#cityChips .pill").forEach(p=>{
    p.onclick = ()=>{ S.city = +p.dataset.ci; syncAll(); apply(); };
  });
}
function heatTable(elId, rows, cols, rowLabels, foot){
  const maxv = Math.max(...rows.map(r=>Math.max(...r)), 0.0001);
  let h = `<table class="heat" style="font-size:11.5px"><tr><th></th>${cols.map(c=>`<th class="num">${c}</th>`).join("")}</tr>`;
  rows.forEach((r,ri)=>{
    h += `<tr style="cursor:pointer" data-r="${ri}"><td><b>${rowLabels[ri]}</b></td>` +
      r.map(v=>{
        const a = v===0 ? 0 : 0.15 + 0.75*(v/maxv);
        return `<td style="background:rgba(11,110,79,${a.toFixed(2)});color:${a>0.45?"#fff":"var(--ink)"}">${v?pct(v,0):"—"}</td>`;
      }).join("") + "</tr>";
  });
  if(foot) h += `<tr style="background:#f8fafc"><td><b>All India</b></td>${foot.map(v=>`<td>${v?pct(v,0):"—"}</td>`).join("")}</tr>`;
  h += "</table>";
  const el = document.getElementById(elId);
  el.innerHTML = h;
  el.querySelectorAll("tr[data-r]").forEach(tr=>{ tr.onclick = ()=>{ S.region=+tr.dataset.r; syncAll(); apply(); }; });
}
function renderGeo(F,C){
  const rCal = DATA.regions.map(()=>[0,0,0,0]);
  const rLine = DATA.regions.map(()=>[0,0,0,0]);
  const ai = [0,0,0,0];
  for(const c of F){
    const ri = DATA.custRegion[c];
    DATA.custItems[c].forEach((o,k)=>{
      const d = orderDate(c,k);
      const s = seasonOf(d.getMonth()+1);
      rCal[ri][s]++; ai[s]++;
      const lines = new Set(o.filter(sk=>sk>0).map(sk=>DATA.prods[sk].l));
      for(let l=0;l<4;l++) if(lines.has(l)) rLine[ri][l]++;
    });
  }
  const share = r => { const t=r.reduce((a,b)=>a+b,0); return t?r.map(v=>v/t):r; };
  const aiT = ai.reduce((a,b)=>a+b,0);
  heatTable("heatCal", rCal.map(share), DATA.seasons, DATA.regions, aiT?ai.map(v=>v/aiT):ai);
  heatTable("heatLine", rLine.map(share),
    DATA.lines.slice(0,4).map((l,i)=>`${["❄","☀","","◉"][i]} ${l}`),
    DATA.regions, null);
  const gelCats = DATA.cats.map((c,i)=>i).filter(i=>/gel/i.test(DATA.cats[i]));
  const nat = window.__nat || (window.__nat = (()=>{
    const o = {gels:0, all:0, cw:0};
    for(let c=0;c<N;c++){
      const itcat = DATA.custItemCat[c];
      DATA.custItems[c].forEach((o2,k)=>{
        o.all++;
        o2.forEach((sk,j)=>{ if(itcat[k][j]>=0 && gelCats.includes(itcat[k][j])) o.gels++; });
        if(new Set(o2.map(sk=>DATA.prods[sk].l)).has(0)) o.cw++;
      });
    }
    return o;
  })());
  const affRows = DATA.regions.map((r,ri)=>{
    let gels=0, all=0, cw=0;
    for(const c of F){
      if(DATA.custRegion[c]!==ri) continue;
      const itcat = DATA.custItemCat[c];
      DATA.custItems[c].forEach((o2,k)=>{
        all++;
        o2.forEach((sk,j)=>{ if(itcat[k][j]>=0 && gelCats.includes(itcat[k][j])) gels++; });
        if(new Set(o2.map(sk=>DATA.prods[sk].l)).has(0)) cw++;
      });
    }
    const aff = (seg, natSeg) => (all>0 && nat.all>0 && natSeg>0) ? (seg/natSeg)/(all/nat.all) : 0;
    return {r, ri, affGels:aff(gels,nat.gels), affCW:aff(cw,nat.cw)};
  });
  const amax = Math.max(...affRows.map(a=>Math.max(a.affGels,a.affCW)),1);
  hbarList(document.getElementById("affinity"),
    [{label:"1.00 avg", value:1, val:"1.00×", color:"#cbd5e1"},
     ...affRows.map(a=>({label:a.r, value:a.affGels, val:`${a.affGels.toFixed(2)}×`, color:"#3b82f6"})),
     ...affRows.map(a=>({label:a.r+" · ❄ winter line", value:a.affCW, val:`${a.affCW.toFixed(2)}×`, color:"#0284c7"}))],
    Math.max(amax,1));
  let h = `<table><tr><th>Region</th><th class="num">Cust</th><th class="num">Orders</th><th class="num">Repeat %</th><th class="num">V2V %</th><th class="num">V2C %</th></tr>`;
  DATA.regions.forEach((r,ri)=>{
    const sub = F.filter(c=>DATA.custRegion[c]===ri);
    const rep = sub.filter(c=>DATA.custRepeat[c]).length;
    let v2v=0, v2c=0;
    sub.forEach(c=>{
      const it = DATA.custItems[c]; if(it.length<2) return;
      const cc = DATA.custItemCat[c];
      if(it[0][0]>0 && it[1][0]>0 && DATA.prods[it[0][0]].raw===DATA.prods[it[1][0]].raw) v2v++;
      if(cc[0][0]>=0 && cc[1][0]>=0 && cc[0][0]===cc[1][0]) v2c++;
    });
    h += `<tr data-ri="${ri}"><td><b>${r}</b></td><td class="num">${fmtI(sub.length)}</td><td class="num">${fmtI(sub.reduce((a,c)=>a+DATA.custDepth[c],0))}</td>
      <td class="num">${sub.length?pct(rep/sub.length):"—"}</td>
      <td class="num">${rep?pct(v2v/rep):"—"}</td><td class="num">${rep?pct(v2c/rep):"—"}</td></tr>`;
  });
  h += "</table>";
  const rl = document.getElementById("regionLoy");
  rl.innerHTML = h;
  rl.querySelectorAll("tr[data-ri]").forEach(tr=>{ tr.onclick=()=>{ S.region=+tr.dataset.ri; syncAll(); apply(); }; });
}

function renderSwitching(F,C){
  const tk = Object.entries(C.trans).sort((a,b)=>b[1]-a[1]).slice(0,10);
  const max = tk.length? tk[0][1]:1;
  document.getElementById("transitions").innerHTML = tk.length ?
    `<div class="hbars">` + tk.map(([k,n])=>`<div class="hb" data-k="${esc(k)}">
      <div style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(k)}">${esc(k)}</div>
      <div class="tr"><div class="fl" style="width:${(n/max*100).toFixed(1)}%;background:#0b6e4f"></div></div>
      <div class="vl">${fmtI(n)} (${pct(n/C.rep,1)})</div></div>`).join("") + "</div>"
    : `<div class="note">No transitions in this cohort.</div>`;
  document.querySelectorAll("#transitions .hb").forEach(rw=>{
    rw.onclick = ()=>{
      const a = rw.dataset.k.split(" → ")[0];
      const sk = prodByLabel(a);
      if(sk){ S.var = sk.v; syncAll(); apply(); }
    };
  });
  const tot = C.flows.same+C.flows.up+C.flows.lat+C.flows.down;
  const tiles = [
    ["🔁", C.flows.same, "Same-product repeat", "identical product name", "#0b6e4f"],
    ["📈", C.flows.up, "Upsized", "larger size on 2nd order", "#3b82f6"],
    ["↔", C.flows.lat, "Lateral switch", "same size, other product", "#d97706"],
    ["📉", C.flows.down, "Downsized", "smaller size on 2nd order", "#b91c1c"],
  ];
  document.getElementById("flowTiles").innerHTML = tiles.map(t=>
    `<div class="tile"><div class="n" style="color:${t[4]}">${fmtI(t[1])}</div>
     <div class="t"><b>${t[0]} ${t[2]}</b><br>${tot?pct(t[1]/tot,1)+" of transitions":"—"} · ${t[3]}</div></div>`).join("");
  document.getElementById("flowNote").textContent =
    `Measured on ${fmtI(tot)} customers with a 2nd order (entry primary product vs 2nd-order primary product).`;
}
function renderVarTable(F,C){
  if(!window.__varSort){ window.__varSort = {col:"total", dir:-1}; }
  const rows = [];
  const allSeasonTotals = [0,0,0,0];
  for(const c of F){ DATA.custItems[c].forEach((o,k)=>{ allSeasonTotals[seasonOf(orderDate(c,k).getMonth()+1)]++; }); }
  const totAll = allSeasonTotals.reduce((a,b)=>a+b,0);
  for(const v in C.variant){
    const vs = C.variant[v];
    const total = vs.seas.reduce((a,b)=>a+b,0);
    const pk = vs.seas.indexOf(Math.max(...vs.seas));
    const pkPct = total? vs.seas[pk]/total : 0;
    const sku0 = firstProdOfVariant(+v);
    const line = DATA.prods[sku0].l;
    const win = DATA.lineWindow[String(line)];
    let match = "—", strength = "—", lift = null;
    if(win && win.length){
      const inWin = win.reduce((a,m)=>a+vs.seas[seasonOf(m)],0);
      const base = baselineWindowShare(win);
      lift = base && total ? (inWin/total)/base : null;
      const peakSeason = DATA.seasons[pk];
      const lineSeason = DATA.lines[line];
      match = (lineSeason===peakSeason) ? "Matches" : "No Match";
      strength = pkPct>=0.4 ? "Highly Seasonal" : (pkPct>=0.3 ? "Moderately Seasonal" : "Evergreen");
    } else {
      strength = pkPct>=0.4 ? "Highly Seasonal" : (pkPct>=0.3 ? "Moderately Seasonal" : "Evergreen");
    }
    const d12 = vs.d12.length? vs.d12.reduce((a,b)=>a+b,0)/vs.d12.length : null;
    rows.push({v:+v, name:DATA.vars[v], cat:DATA.cats[DATA.prods[sku0].c],
      cw:vs.seas[0], hd:vs.seas[1], hh:vs.seas[2], pm:vs.seas[3], total,
      peak:DATA.seasons[pk], peakPct:pkPct, intended:DATA.lines[line], match, strength,
      lift, n:vs.n, rep: vs.n? vs.rep/vs.n : null, d12});
  }
  const {col, dir} = window.__varSort;
  rows.sort((a,b)=>{
    const x=a[col], y=b[col];
    if(x==null) return 1; if(y==null) return -1;
    return (typeof x==="string"? x.localeCompare(y) : x-y)*dir;
  });
  const th = (label, key, num=true) => `<th class="${num?"num":""}" data-k="${key}">${label}<span style="opacity:.5"> ◆</span></th>`;
  let h = `<table><tr><th data-k="name">Variant ◆</th><th data-k="cat">Category ◆</th>${th("❄ CW","cw")}${th("☀ HD","hd")}${th("🌧 HH","hh")}${th("🍂 PM","pm")}${th("Total","total")}
    <th data-k="peak">Peak ◆</th>${th("Peak %","peakPct")}<th data-k="intended">Intended ◆</th><th data-k="match">Match ◆</th><th data-k="strength">Strength ◆</th>${th("On-season lift","lift")}${th("Entry users","n")}${th("Repeat %","rep")}${th("Avg d 1→2","d12")}</tr><tbody>`;
  rows.forEach(r=>{
    const liftTxt = r.lift==null ? "—" : `<b>${r.lift.toFixed(2)}×</b>`;
    h += `<tr data-v="${r.v}" style="${S.var===r.v?"outline:2px solid var(--ink);outline-offset:-2px":""}">
      <td><b>${esc(r.name)}</b></td><td>${esc(r.cat)}</td>
      <td class="num">${r.cw}</td><td class="num">${r.hd}</td><td class="num">${r.hh}</td><td class="num">${r.pm}</td>
      <td class="num"><b>${r.total}</b></td><td>${r.peak}</td><td class="num">${pct(r.peakPct,1)}</td>
      <td>${r.intended}</td>
      <td>${r.match==="Matches"?`<span class="pill g">Matches</span>`:r.match==="No Match"?`<span class="pill r">No Match</span>`:"—"}</td>
      <td>${r.strength==="Evergreen"?`<span class="pill n">Evergreen</span>`:r.strength==="Highly Seasonal"?`<span class="pill b">${r.strength}</span>`:`<span class="pill n">${r.strength}</span>`}</td>
      <td class="num">${liftTxt}</td><td class="num">${fmtI(r.n)}</td><td class="num">${pct(r.rep,1)}</td><td class="num">${r.d12==null?"—":fmtI(r.d12)}</td></tr>`;
  });
  h += "</tbody></table>";
  const el = document.getElementById("varTable");
  el.innerHTML = h;
  el.querySelectorAll("th[data-k]").forEach(thEl=>{
    thEl.onclick = ()=>{
      const k = thEl.dataset.k;
      if(window.__varSort.col===k) window.__varSort.dir*=-1; else window.__varSort={col:k,dir:-1};
      renderVarTable(F,C);
    };
  });
  el.querySelectorAll("tr[data-v]").forEach(tr=>{
    tr.onclick = ()=>{ S.var=+tr.dataset.v; syncAll(); apply(); };
  });
}
/* ================= journey explorer ================= */
let PAGE = 0; const PSIZE = 50;
function renderExplorer(F){
  const pg = Math.min(PAGE, Math.max(0, Math.ceil(F.length/PSIZE)-1));
  const slice = F.slice(pg*PSIZE, pg*PSIZE+PSIZE);
  let h = `<table><tr><th>Customer</th><th>City</th><th>Region</th><th>Entry</th><th class="num">Depth</th><th>Repeat?</th><th>Order SKUs (1→6)</th><th>Gaps (days)</th></tr><tbody>`;
  slice.forEach(c=>{
    const items = DATA.custItems[c];
    const skusTxt = items.map(o=>o.map(sk=>DATA.prods[sk].n).join(", ")).join(" → ");
    const gaps = DATA.custGaps[c].filter(g=>g>0).join(", ");
    h += `<tr class="xrow" data-c="${c}"><td>${esc(c)}</td><td>${esc(DATA.cities[DATA.custCity[c]])}</td><td>${DATA.regions[DATA.custRegion[c]]}</td>
      <td>${DATA.months[DATA.custMonth[c]]}</td><td class="num">${DATA.custDepth[c]}</td>
      <td>${DATA.custRepeat[c]?"<span class='pill g'>✅</span>":"—"}</td>
      <td style="max-width:430px">${esc(skusTxt)}</td><td class="num" style="white-space:nowrap">${gaps}</td></tr>`;
  });
  h += "</tbody></table>";
  const el = document.getElementById("explorer");
  el.innerHTML = h;
  document.getElementById("pgLbl").textContent = `${fmtI(F.length)} rows · page ${pg+1} / ${Math.max(1,Math.ceil(F.length/PSIZE))}`;
  document.getElementById("pgPrev").disabled = pg===0;
  document.getElementById("pgNext").disabled = pg*PSIZE+PSIZE >= F.length;
  el.querySelectorAll("tr.xrow").forEach(tr=>{
    tr.onclick = ()=>{
      const c = tr.dataset.c;
      const next = tr.nextElementSibling;
      if(next && next.classList.contains("xdetail")){ next.remove(); return; }
      const items = DATA.custItems[c];
      let t = `<div class="tl">`;
      items.forEach((o,k)=>{
        const d = orderDate(c,k);
        const s = seasonOf(d.getMonth()+1);
        const gap = k ? (DATA.custGaps[c][k-1]>0?` <span class="small">(+${DATA.custGaps[c][k-1]}d)</span>`:"") : "";
        t += `<div class="o"><b>Order ${k+1} · ${d.toISOString().slice(0,10)} · ${DATA.seasons[s]}</b>${gap} — ${o.map(sk=>esc(DATA.prods[sk].n)).join(", ")}</div>`;
      });
      t += `</div>`;
      const row = document.createElement("tr");
      row.innerHTML = `<td class="xdetail" colspan="8" style="padding:4px 8px">${t}</td>`;
      tr.after(row);
    };
  });
}
function exportCSV(F){
  const head = ["customer","city","region","entry_month","depth","repeat","order1","order2","order3","order4","order5","order6","gaps_days"];
  const lines = [head.join(",")];
  F.forEach(c=>{
    const items = DATA.custItems[c].map(o=>o.map(sk=>DATA.prods[sk].n).join("; "));
    const gaps = DATA.custGaps[c].filter(g=>g>0).join("; ");
    const row = [c, DATA.cities[DATA.custCity[c]], DATA.regions[DATA.custRegion[c]], DATA.months[DATA.custMonth[c]],
      DATA.custDepth[c], DATA.custRepeat[c]? "yes":"no",
      items[0]||"", items[1]||"", items[2]||"", items[3]||"", items[4]||"", items[5]||"", gaps];
    lines.push(row.map(v=>`"${String(v).replace(/"/g,'""')}"`).join(","));
  });
  const blob = new Blob([lines.join("\n")], {type:"text/csv"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "retention_cohort.csv";
  a.click();
  URL.revokeObjectURL(a.href);
}
/* ================= apply ================= */
let LAST = null;
function apply(){
  const F = filtered();
  const C = computeCohort(F);
  LAST = {F, C};
  renderHeader(F,C);
  renderInsights(F,C);
  renderRetCurve(F,C);
  renderRepeatByMonth(F,C);
  renderGapDist(F,C);
  renderLoyalty(F,C);
  renderOrdersByMonth(F,C);
  renderCatMix(F,C);
  renderSeason(F,C);
  renderPortfolio(F,C);
  renderGeo(F,C);
  renderSwitching(F,C);
  renderVarTable(F,C);
  PAGE = 0;
  renderExplorer(F);
}
document.getElementById("pgPrev").onclick = ()=>{ PAGE=Math.max(0,PAGE-1); renderExplorer(LAST.F); };
document.getElementById("pgNext").onclick = ()=>{ PAGE+=1; renderExplorer(LAST.F); };
document.getElementById("pgExport").onclick = ()=>exportCSV(LAST.F);
document.getElementById("foot").textContent =
  `Generated ${new Date().toISOString().slice(0,10)} by make_retention_dashboard.py from the customer journey base sheet — ${N} customers, ${DATA.nOrders} orders. All numbers recompute in-browser from the embedded per-customer data; nothing is uploaded anywhere.`;
initFilters();
apply();
</script>
<script>
@@LIVE_JS@@
</script>
<script>
@@LIVE_WIRE@@
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# verification
# ---------------------------------------------------------------------------
class _TagCheck(HTMLParser):
    VOID = {"meta", "br", "img", "input", "hr", "rect", "line", "polyline", "path", "col", "link", "circle"}

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


def verify(page: str, data: dict) -> list[str]:
    errs = []
    if re.search(r"(?:src|href)\s*=\s*['\"]https?://", page):
        errs.append("external reference found")
    pc = _TagCheck()
    pc.feed(page)
    if pc.stack:
        errs.append(f"unclosed tags: {pc.stack[:5]}")
    errs.extend(pc.errors[:5])
    for marker in ("fCat", "fReset", "insights", "retCurve", "repeatByMonth", "gapDist",
                   "loyGrid", "ordersByMonth", "catDonut", "seasonTiles", "seasonBars",
                   "topVars", "depthBars", "regionBars", "cityChips", "heatCal", "heatLine",
                   "affinity", "regionLoy", "transitions", "flowTiles", "varTable",
                   "explorer", "pgExport"):
        if f'id="{marker}"' not in page:
            errs.append(f"missing element #{marker}")
    m = re.search(r"const DATA = (\{.*?\});\n</script>", page, re.S)
    if not m:
        errs.append("DATA blob not found")
    else:
        try:
            emb = json.loads(m.group(1))
            if emb["nCustomers"] != data["nCustomers"]:
                errs.append("customer count mismatch")
            if len(emb["custItems"]) != data["nCustomers"]:
                errs.append("custItems length mismatch")
            if len(emb["custEntry"]) != data["nCustomers"]:
                errs.append("custEntry length mismatch")
        except Exception as e:
            errs.append(f"DATA blob parse failed: {e}")
    return errs


def main() -> None:
    page, data = build()
    errs = verify(page, data)
    if errs:
        print("VERIFICATION FAILED:")
        for e in errs:
            print("  -", e)
        raise SystemExit(1)
    out = ROOT / "journey.html"
    out.write_text(page, encoding="utf-8")
    rep = sum(data["custRepeat"])
    print(f"OK  wrote {out} ({out.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"OK  {data['nCustomers']:,} customers · {data['nOrders']:,} orders · {rep:,} repeat buyers")
    print(f"OK  months {data['months'][0]} → {data['months'][-1]} · as-of {data['asOf']}")
    print(f"OK  zero external references · tags balanced · all sections present")


if __name__ == "__main__":
    main()
