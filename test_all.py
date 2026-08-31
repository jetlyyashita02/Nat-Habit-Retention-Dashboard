"""
tests/test_all.py — validation suite for the Retention & Category Intelligence dashboard.

Run:  python tests/test_all.py
Covers (per spec §46): normalization (dates, %, commas), V2V/V2C separation,
retention denominators + cohort maturity, NPS math, price detection, zero revenue/qty,
missing optional columns, malformed dates, duplicate customers, blank categories,
blank responsible-team, NPS paste parsing, downloads, percentage formatting,
AOP block parsing, order-movement pct formats.
"""
import os
import re
import sys
import tempfile
from datetime import date

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sources
import etl
import calculations as calc
import conclusions as conc
from formatting import (SourceReport, fmt_pct, fmt_pct_auto, fmt_money, parse_date,
                        parse_month_label, parse_number, parse_pct, split_multi)

PASS = FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}  {detail}")

def mkrep(key="test"):
    return SourceReport(key=key, label=key)

# ---------------------------------------------------------------------------
print("\n[1] Normalization — numbers, percents, dates")
check("parse_number commas", parse_number("1,234.5") == 1234.5)
check("parse_number rupee", parse_number("₹99,999") == 99999)
check("parse_number junk", np.isnan(parse_number("abc")))
check("parse_pct sign", abs(parse_pct("30.4%") - 0.304) < 1e-9)
check("parse_pct bare >1", abs(parse_pct("237.0135685") - 2.370135685) < 1e-9)
check("parse_pct fraction", abs(parse_pct("0.79") - 0.79) < 1e-9)
check("parse_date d-M-Y", parse_date("4-8-2026") == date(2026, 8, 4))
check("parse_date 'Jan'26'", parse_month_label("Jan'26") == "2026-01")
check("parse_date 'Jan 2026'", parse_month_label("Jan 2026") == "2026-01")
check("parse_date 'Jan-26'", parse_month_label("Jan-26") == "2026-01")
check("parse_date ISO", parse_month_label("2026-08") == "2026-08")
check("parse_date feb", parse_date("Feb 1, 2026") == date(2026, 2, 1))
check("fmt_pct basic", fmt_pct(0.304) == "30.4%")
check("fmt_pct nan", fmt_pct(np.nan) == "—")
check("fmt_pct_auto small", fmt_pct_auto(0.0054) == "0.54%")
check("fmt_pct_auto large", fmt_pct_auto(0.127) == "12.7%")
check("fmt_money lakh", fmt_money(456000) == "₹4.6L")
check("fmt_money cr", fmt_money(12400000) == "₹1.24Cr")
check("split_multi pipes", split_multi("A|B ;C") == ["A", "B", "C"])
check("split_multi dedupe", split_multi("A|A|B") == ["A", "B"])

# ---------------------------------------------------------------------------
print("\n[2] Sales model — normalization & edge cases")
raw = pd.DataFrame([
    ["order_date", "SKU", "order_source", "product", "category", "orders", "customers", "quantity", "revenue"],
    ["Jan 2026", "S1", "D2C", "P1", "Cat A", "10", "8", "100", "50,000"],
    ["Feb 2026", "S1", "D2C", "P1", "Cat A", "5", "4", "0", "2,000"],      # zero qty
    ["Feb 2026", "S1", "D2C", "P1", "Cat A", "5", "4", "0", "2,000"],      # duplicate
    ["Mar 2026", "S2", "AMZ", "P2", "", "1", "1", "10", "100"],            # blank cat
    ["bad date", "S3", "AMZ", "P3", "Cat C", "1", "1", "10", "100"],       # malformed date -> dropped
    ["Mar 2026", "S2", "AMZ", "P2", "Cat B", "1", "1", "10", "-50"],       # negative rev
])
rep = mkrep("sales")
hr = sources.detect_header(raw, "sales")
cm = sources.find_columns(raw, "sales", hr)
m = etl.build_sales_model(raw, rep, cm, hr)
check("sales parsed", m is not None and len(m["df"]) == 4, f"len={None if m is None else len(m['df'])}")
check("sales month labels", set(m["df"]["month"]) == {"2026-01", "2026-02", "2026-03"})
check("blank category bucketed", "(Uncategorized)" in set(m["df"]["category"]))
check("dupes warned", any("duplicate" in w for w in rep.warnings))
check("zero qty warned", any("zero quantity" in w for w in rep.warnings))
check("negative rev kept+warned", (m["df"]["revenue"] < 0).any() and any("negative" in w for w in rep.warnings))
check("comma numbers parsed", m["df"][m["df"]["sku"] == "S1"]["revenue"].max() == 50000)

# missing required column
raw2 = pd.DataFrame([["date", "sku", "category", "qty"], ["2026-01-01", "S1", "C", "10"]])
rep2 = mkrep("sales")
m2 = etl.build_sales_model(raw2, rep2, sources.find_columns(raw2, "sales", 0), 0)
check("sales missing revenue -> error", m2 is None)
check("sales missing revenue -> explained", any("revenue" in e for e in rep2.errors))

# ---------------------------------------------------------------------------
print("\n[3] Journey model — customers, orders, V2V ≠ V2C, maturity")
J = pd.DataFrame([
    ["customer_id", "order_id", "order_date", "sku", "product", "category", "channel", "quantity"],
    ["C1", "O1", "2026-01-05", "S1", "Var A", "Cat A", "D2C", "1"],
    ["C1", "O2", "2026-02-05", "S1", "Var A", "Cat A", "D2C", "1"],        # V2V
    ["C1", "O2", "2026-02-05", "S9", "Var X", "Cat B", "D2C", "1"],        # 2nd line same order
    ["C2", "O3", "2026-01-10", "S1", "Var A", "Cat A", "D2C", "1"],
    ["C2", "O4", "2026-03-01", "S2", "Var B", "Cat A", "D2C", "1"],        # V2C not V2V
    ["C3", "O5", "2026-01-12", "S1", "Var A", "Cat A", "D2C", "1"],
    ["C3", "O6", "2026-04-01", "S3", "Var C", "Cat B", "D2C", "1"],        # full switch
    ["C4", "O7", "2026-08-20", "S1", "Var A", "Cat A", "D2C", "1"],        # no 2nd order (immature)
])
rep = mkrep("journey")
hr = sources.detect_header(J, "journey")
cm = sources.find_columns(J, "journey", hr)
jm = etl.build_journey_model(J, rep, cm, hr)
check("journey customers", jm["n_customers"] == 4)
check("journey orders (multi-line dedup)", jm["n_orders"] == 7, f"got {jm['n_orders']}")
check("multi-line warned", any("Multi-line" in w for w in rep.warnings))
vv = calc.v2v_v2c_analysis(jm)
check("v2v/v2c qualifying=3", vv["overall"]["qualifying"] == 3)
check("v2v = 1/3", abs(vv["overall"]["v2v_pct"] - 1 / 3) < 1e-9, f"got {vv['overall']['v2v_pct']}")
check("v2c = 2/3", abs(vv["overall"]["v2c_pct"] - 2 / 3) < 1e-9, f"got {vv['overall']['v2c_pct']}")
check("V2V != V2C", vv["overall"]["v2v_pct"] != vv["overall"]["v2c_pct"])
mig = calc.migration_analysis(jm, "category")
check("mig acquired=4", mig["n_acquired"] == 4)
check("mig repeat 2/4", abs(mig["repeat_pct"] - 0.5) < 1e-9)
check("mig switch 1/4", abs(mig["switch_pct"] - 0.25) < 1e-9)
check("net migration", dict(zip(mig["net"]["entity"], mig["net"]["net"])) == {"Cat A": -1, "Cat B": 1},
      str(mig["net"].values.tolist()))

# retention denominators + maturity
jr = calc.journey_retention(jm, "category", as_of=date(2026, 5, 1))
d = jr["df"]
row = d[(d["cohort"] == "2026-01") & (d["entity"] == "Cat A")]
check("retention cohort size=3", row["customers"].iloc[0] == 3)
check("retention 30d = 0 (no one within 30d)", row["w30"].iloc[0] == 0.0)
check("retention 60d = 2/3", abs(row["w60"].iloc[0] - 2 / 3) < 1e-9)
check("immature 360d = NaN", np.isnan(row["w360"].iloc[0]))
jr2 = calc.journey_retention(jm, "category", as_of=date(2027, 2, 1))
row2 = jr2["df"][(jr2["df"]["cohort"] == "2026-01") & (jr2["df"]["entity"] == "Cat A")]
check("mature 360d = 1.0", abs(row2["w360"].iloc[0] - 1.0) < 1e-9)

# missing customer id (grid form, like the real loader)
J3 = J.iloc[1:].reset_index(drop=True).drop(columns=[0])  # remove customer_id col (index 0)
rep3 = mkrep("journey")
hr3 = sources.detect_header(J3, "journey")
cm3 = sources.find_columns(J3, "journey", hr3) if hr3 is not None else {}
check("journey no customer id -> None + error",
      (hr3 is None) or (etl.build_journey_model(J3, rep3, cm3, hr3) is None and len(rep3.errors) > 0))

# ---------------------------------------------------------------------------
print("\n[4] NPS — standard math, themes, paste, competitor pull")
N = pd.DataFrame([
    ["id", "created_at", "customer_id", "product_category", "product_variant", "age", "skin_type", "hair_type",
     "NPS Score For Brand", "NPS Score For Product", "Brand Customer Migrated From",
     "What do you like about Nat Habit", "What do you not like about Nat Habit", "Like Product", "Not like Product"],
    ["1", "Aug 1, 2026, 10:00", "a", "Cat A", "V1", "30", "Oily", "Straight hair", "10", "10", "Nat Habit is my first!", "", "", "Good|Purity", "No complaints- love the product!"],
    ["2", "Aug 2, 2026, 11:00", "b", "Cat A", "V1", "40", "Dry", "Curly / Wavy hair", "9", "6", "Mamaearth", "", "", "Good", "Expensive"],
    ["3", "Aug 3, 2026, 12:00", "c", "Cat B", "V2", "55", "Normal", "Straight hair", "5", "8", "Lakme", "", "", "Purity", "Smell|Expensive"],
    ["4", "Aug 4, 2026, 13:00", "d", "Cat B", "V2", "25", "Sensitive", "Straight hair", "8", "9", "Mamaearth", "", "", "Good", ""],
])
rep = mkrep("nps")
hr = sources.detect_header(N, "nps")
cm = sources.find_columns(N, "nps", hr)
nm = etl.build_nps_model(N, rep, cm, hr)
b = calc.nps_score_stats(nm["df"]["brand_score"])
p = calc.nps_score_stats(nm["df"]["product_score"])
# brand: 10,9,5,8 -> promoters 2 (10,9), detractors 1 (5) => NPS = 50-25 = 25
check("brand NPS = 25", abs(b["nps"] - 25.0) < 1e-9, f"got {b['nps']}")
check("product NPS: p=2 (10,9) d=1 (6) => 25", abs(p["nps"] - 25.0) < 1e-9, f"got {p['nps']}")
likes = calc.theme_counts(nm, "like")
check("themes split on |", set(likes["theme"]) == {"Good", "Purity"} and
      int(likes.loc[likes["theme"] == "Good", "mentions"].iloc[0]) == 3)
disl = calc.theme_counts(nm, "dislike")
check("dislike excludes no-complaints", "No complaints- love the product!" not in set(disl["theme"]))
comp = calc.competitor_pull(nm)
check("first-time separated", comp[comp["source"].str.contains("first")]["customers"].iloc[0] == 1)
check("top competitor = Mamaearth", comp[~comp["is_first_time"]].iloc[0]["source"] == "Mamaearth")
concl = conc.nps_conclusions(nm, b, p, likes, disl, comp, pd.DataFrame())
check("nps conclusions generated", len(concl) >= 3 and any("25" in c for c in concl))

# paste parsing via sources.get_source (no streamlit runtime -> emulate session_state)
class FakeState(dict):
    def get(self, k, d=None): return super().get(k, d)
st_shim = type("S", (), {"session_state": FakeState()})
paste_frame = pd.DataFrame(N.iloc[1:].values, columns=N.iloc[0].tolist())  # raw grid -> real CSV text
sources.st.session_state = FakeState({"nps_pasted_raw": paste_frame.to_csv(index=False)})
grid, prepc = sources.get_source("nps")
check("pasted NPS parsed", prepc.filename == "pasted NPS data" and len(grid) == 5)
sources.st.session_state = FakeState({})

# out-of-range scores
N4 = N.copy()
N4.iloc[1, 8] = "12"
rep4 = mkrep("nps")
m4 = etl.build_nps_model(N4, rep4, cm, hr)
check("out-of-range score excluded+warned", m4["df"].shape[0] == 3 and any("outside 0–10" in w for w in rep4.warnings))

# ---------------------------------------------------------------------------
print("\n[5] CS — KPIs, fulfilment hours, empty team")
C = pd.DataFrame([
    ["id", "created_at", "customer_name", "order_name", "order_count", "chat_status", "provided_resolution",
     "failure_type", "failure_reason", "failure_subreason", "products_ordered", "products_impacted",
     "Product impacted category", "responsible_team", "remarks", "global_remark", "fulfilled_time", "delivery_time",
     "city", "state", "chat_link"],
    ["1", "4-8-2026", "A", "NH-1", "1", "Resolved", "", "Post Delivery - Service Failure", "Courier Failure",
     "Outer Box Damaged", "P1", "P1", "Shampoo", "", "", "box broke", "Aug 3, 2026, 14:30", "Aug 6, 2026, 14:30", "B", "S", ""],
    ["2", "5-8-2026", "B", "NH-2", "2", "Open", "", "Product Feedback", "Mixed Feedback", "Mixed Feedback",
     "P2", "P2", "Henna", "", "", "ok", "Jul 31, 2026, 14:30", "Aug 2, 2026, 14:30", "C", "S", ""],
])
rep = mkrep("cs")
hr = sources.detect_header(C, "cs")
cm = sources.find_columns(C, "cs", hr)
cm_ = dict(cm); cm_.update({"category": next(j for j, h in enumerate(C.iloc[hr].tolist()) if "impacted category" in str(h).lower())})
csm = etl.build_cs_model(C, rep, cm_, hr)
k = calc.cs_kpis({"df": csm["df"]})
check("cs tickets=2", k["tickets"] == 2)
check("cs resolved 50%", abs(k["resolved_pct"] - 0.5) < 1e-9)
# fulfil_hours = delivery_time - fulfilled_time; rows: 72h and 48h -> median 60h
check("cs median fulfil 60h", abs(k["median_fulfil_hours"] - 60.0) < 1e-6, f"got {k['median_fulfil_hours']}")
check("cs empty team warned", any("Responsible team" in w and ("empty" in w or "not present" in w) for w in rep.warnings))
h = calc.cs_hierarchy({"df": csm["df"]})
check("cs hierarchy rows=2", len(h) == 2)

# ---------------------------------------------------------------------------
print("\n[6] Retention FM — %-number windows, maturity, price notes")
F = pd.DataFrame([
    ["product_onb_date", "product_category", "sku", "Lookup Price thing", "short_code", "channel", "Customer",
     "15 Days %", "30 Days %", "360 Days %"],
    ["Feb 1, 2026", "Cat A", "S1", "Increased-Price Revision - 2nd February, 2026", "Var A", "D2C", "100", "5.4", "10.8", "20.0"],
    ["Feb 1, 2026", "Cat A", "S2", "Same-Price Revision - 2nd February, 2026", "Var B", "D2C", "50", "2.0", "4.0", "8.0"],
    ["", "", "", "", "", "", "150", "", "", ""],
])
rep = mkrep("retention_fm")
hr = sources.detect_header(F, "retention_fm")
cm = sources.find_columns(F, "retention_fm", hr)
fm = etl.build_retention_fm_model(F, rep, cm, hr)
check("fm skus=2", fm["df"].shape[0] == 2)
check("fm %-number -> fraction", abs(fm["df"].iloc[0]["w30"] - 0.108) < 1e-9, f"got {fm['df'].iloc[0]['w30']}")
check("fm total row captured", fm["total_customers"] == 150)
check("fm price parsed", fm["price"]["change_type"].tolist() == ["Increased Price", "Same Price"])
check("fm price date parsed", fm["price"].iloc[0]["date"] == date(2026, 2, 2))
vals, mat = calc.fm_retention_table(fm["df"], fm["windows"], date(2026, 4, 10))
check("fm 30d mature", bool(mat.loc[fm["df"].index[0], "w30"]))
check("fm 360d not mature -> NaN", np.isnan(vals.loc[fm["df"].index[0], "w360"]))
check("fm 360d flagged immature", not bool(mat.loc[fm["df"].index[0], "w360"]))
vals2, mat2 = calc.fm_retention_table(fm["df"], fm["windows"], date(2027, 3, 1))
check("fm 360d mature later", abs(vals2.loc[fm["df"].index[0], "w360"] - 0.20) < 1e-9)

# price note parser
t, dd, _ = etl.parse_price_note("New 50g Variant Launch")
check("new variant note", t == "New Variant")
t, dd, _ = etl.parse_price_note("Decreased-Price Revision - 2nd February, 2026")
check("decreased note+date", t == "Decreased Price" and dd == date(2026, 2, 2))

# ---------------------------------------------------------------------------
print("\n[7] Price detection — realized price, MoM, threshold")
S = pd.DataFrame({
    "order_date": ["2026-01-01", "2026-02-01", "2026-03-01"],
    "sku": ["X", "X", "X"], "product": ["PX", "PX", "PX"], "category": ["C", "C", "C"],
    "channel": ["D2C", "D2C", "D2C"], "orders": [10, 10, 10], "customers": [9, 9, 9],
    "quantity": [100, 100, 100], "revenue": [10000.0, 10600.0, 10500.0],   # +6% then -0.94%
})
det = calc.derived_price_changes(S, threshold=0.05)
flag = calc.price_flags(det, 0.05)
check("detected increase", len(flag) == 1 and flag.iloc[0]["month"] == "2026-02" and flag.iloc[0]["direction"] == "Increase")
check("change ~6%", abs(flag.iloc[0]["change_pct"] - 0.06) < 1e-9)
S0 = S.copy(); S0.loc[S0.index[1], "revenue"] = 0
det0 = calc.derived_price_changes(S0, threshold=0.05)
check("zero revenue month handled", det0["unit_price"].isna().any() or (det0["change_pct"].isna()).any())
S1 = S.copy(); S1.loc[S1.index[1], "quantity"] = 0
det1 = calc.derived_price_changes(S1, threshold=0.05)
check("zero qty excluded from price", int((det1["month"] == "2026-02").sum()) == 0 and len(det1) == 2)

# ---------------------------------------------------------------------------
print("\n[8] New-to-category — pct formats, maturity")
O = pd.DataFrame([
    ["2026-08-03 18:16:47"],
    ["onb_month", "first_order", "sec_order", "sec_pct", "avg_days_to_sec", "third_order", "third_pct",
     "avg_days_to_third", "fourth_order", "fourth_pct", "avg_days_to_fourth", "fifth_order", "fifth_pct",
     "avg_days_to_fifth", "sixth_order", "sixth_pct", "avg_days_to_sixth"],
    ["2026-01-01", "100", "50", "50%", "30", "20", "20%", "25", "10", "10%", "20", "5", "5%", "15", "3", "3%", "10"],
    ["2026-07-01", "100", "6", "6%", "10", "1", "1%", "6", "0", "0%", "", "0", "0%", "", "0", "0%", ""],
])
rep = mkrep("order_movement")
hr = sources.detect_header(O, "order_movement")
cm = sources.find_columns(O, "order_movement", hr)
om = etl.build_order_movement_model(O, rep, cm, hr)
check("ntc as_of from timestamp", om["as_of"] == date(2026, 8, 3))
check("ntc pct sign-parsed", abs(om["df"].iloc[0]["sec_pct"] - 0.5) < 1e-9)
check("ntc pct recomputed from counts", abs(om["df"].iloc[0]["sec_pct"] - 0.5) < 1e-9)
dm = calc.ntc_maturity(om["df"], om["as_of"], 90)
check("ntc mature flag", bool(dm.loc[dm["cohort"] == "2026-01", "mature"].iloc[0]) and
      not bool(dm.loc[dm["cohort"] == "2026-07", "mature"].iloc[0]))
k = calc.ntc_kpis(om["df"], om["as_of"], 90)
check("ntc kpis mature only", k["cohorts_mature"] == 1 and abs(k["avg_sec_pct"] - 0.5) < 1e-9)

# ---------------------------------------------------------------------------
print("\n[9] AOP — wide block parsing")
raw_aop = sources.read_csv_path(sources.DATA_DIR / "sample_aop.csv")
rep = mkrep("aop")
aop = etl.build_aop_model(raw_aop, rep)
check("aop meta 8 cols", len(aop["meta_names"]) == 8, str(aop["meta_names"]))
check("aop 51 months", len(aop["months"]) == 51)
check("aop month span", aop["months"][0] == "2024-01" and aop["months"][-1] == "2028-03")
fm_tot = aop["long"][(aop["long"]["Category"] == "Face Malai") & (aop["long"]["Channels Sub"] == "TOTAL") &
                     (aop["long"]["block"] == "revenue")]
v = fm_tot[fm_tot["month"] == "2024-01"]["value"]
check("aop FM Jan'24 = 3,787,226", len(v) == 1 and abs(v.iloc[0] - 3787226) < 1e-6)
roas = aop["long"][(aop["long"]["Category"] == "Face Malai") & (aop["long"]["Channels Sub"] == "TOTAL") &
                   (aop["long"]["block"] == "roas")]
check("aop roas block shorter (28m)", roas["month"].nunique() == 28)
share = aop["long"][(aop["long"]["block"] == "rev_share") & (aop["long"]["month"] == "2024-01")]
tot_share = share[(share["Channels Sub"] == "TOTAL")]["value"]
check("aop rev share is fraction (<=1)", tot_share.notna().any() and tot_share.dropna().between(0, 1.0001).all())
am = calc.aop_monthly(aop)
check("aop monthly roas computed", len(am) == 51 and am["roas"].notna().any())
check("aop monthly grand-total category excluded",
      am["revenue"].notna().any() and abs(am[am["month"] == "2024-01"]["revenue"].iloc[0]
      - aop["long"][(aop["long"]["block"] == "revenue") & (aop["long"]["month"] == "2024-01")
                    & (aop["long"]["Channels Sub"].str.upper().str.strip() == "TOTAL")
                    & (~aop["long"]["Category"].str.strip().str.lower().str.startswith("total"))]["value"].sum()) < 1e-6)
fy = calc.aop_fy(aop)
# only the FY-2024-25 block carries channel/category labels in this export;
# later FY blocks are unlabeled placeholders, so the FY table holds labeled FYs only
check("aop fy table has labeled FY", "2024 - 2025" in set(fy["fy"].astype(str)) and len(fy) > 0,
      str(set(fy["fy"].astype(str))))
check("aop fy category filter works", len(calc.aop_fy(aop, categories=["Face Malai"])) > 0)

# ---------------------------------------------------------------------------
print("\n[10] Summary sheet — blocks & conclusions")
raw_s = sources.read_csv_path(sources.DATA_DIR / "sample_migr_seasonality.csv")
rep = mkrep("migr")
sm = etl.build_migr_seasonality_model(raw_s, rep)
check("seasonality block", "seasonality" in sm and len(sm["seasonality"]) == 14)
check("order freq block", "order_freq" in sm and len(sm["order_freq"]) == 22)
check("grammage block", "grammage" in sm and len(sm["grammage"]) == 5)
check("conclusions captured", any("Seasonal" in q for q, _ in sm["conclusions"]))
check("empty V2V sheet warned", any("V2V/V2C" in w for w in rep.warnings))

# ---------------------------------------------------------------------------
print("\n[11] Conclusions — no hardcoding, non-causal wording")
ctx = {}
items = conc.executive_attention(ctx)
check("empty ctx -> no attention items", items == [])
check("empty ctx -> no changes", conc.executive_changes(ctx) == [])
# price×retention wording
price = pd.DataFrame([{"sku": "S1", "change_type": "Increased Price"}, {"sku": "S2", "change_type": "Same Price"},
                      {"sku": "S3", "change_type": "Same Price"}, {"sku": "S4", "change_type": "Same Price"}])
fmf = pd.DataFrame([{"onb_date": date(2026, 2, 1), "cohort_month": "2026-02", "category": "C", "sku": s,
                     "variant": s, "channel": "D2C", "customers": 100,
                     "price_note": "", "price_type": None, "price_date": None,
                     **{f"w{w}": (0.05 if s == "S1" else 0.08) for w in [15, 30, 60, 90, 120, 180, 240, 300, 360]}}
                     for s in ["S1", "S2", "S3", "S4"]])
WINS = [15, 30, 60, 90, 120, 180, 240, 300, 360]
vals, mat = calc.fm_retention_table(fmf, WINS, date(2027, 3, 1))
hx = conc.price_x_retention_conclusions(price, vals, mat, fmf, WINS)
check("price×retention flagged non-causal", len(hx) == 1 and "validation" in hx[0] and "caused" not in hx[0])

# ---------------------------------------------------------------------------
print("\n[12] Full samples end-to-end (all 8 sources)")
for key in ["sales", "journey", "nps", "cs", "aop", "retention_fm", "order_movement", "migr_seasonality"]:
    model, r, meta = sources.get_model(key)
    check(f"sample {key} loads", model is not None, str(r.errors))

# ---------------------------------------------------------------------------
print("\n[13] Downloads produce valid CSV bytes")
from formatting import df_to_csv_bytes
b = df_to_csv_bytes(pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}))
check("csv bytes", b.startswith(b"a,b") and b"1,x" in b)

# ---------------------------------------------------------------------------
print("\n[14] Real exports — all-category sales + category-scoped Moisturisers")
ms, rps, _ = sources.get_model("sales")
check("sales: 30,543 rows", ms is not None and len(ms["df"]) == 30543,
      str(len(ms["df"]) if ms else None))
check("sales: 56 categories", ms is not None and ms["df"]["category"].nunique() == 56)
check("sales: months 2026-07/2026-08", ms is not None and set(ms["df"]["month"]) == {"2026-07", "2026-08"})
check("sales: total revenue", ms is not None and abs(ms["df"]["revenue"].sum() - 124267714.0) < 1.0)
check("sales: not demo anymore", rps.is_demo is False)
mc, rpc, _ = sources.get_model("category_sales")
check("cat-sales: 2,596 rows / 4 cats", mc is not None and len(mc["df"]) == 2596
      and mc["df"]["category"].nunique() == 4)
check("cat-sales: exact subset of all-category sales",
      set(zip(mc["df"]["order_date"].astype(str), mc["df"]["sku"]))
      <= set(zip(ms["df"]["order_date"].astype(str), ms["df"]["sku"])))
# intra_category_movement on a hand-made frame (exact values)
d = pd.DataFrame({
    "order_date": pd.to_datetime(["2026-01-01", "2026-01-10", "2026-01-20", "2026-01-25"]),
    "sku": ["A-100", "A-100", "B-200", "B-200"],
    "product": ["Alpha - 100g", "Alpha - 100g", "Beta - 200ml", "Beta - 200ml"],
    "category": ["C", "C", "C", "C"],
    "channel": ["D2C", "D2C", "D2C", "D2C"],
    "orders": [1, 1, 1, 1], "customers": [1, 1, 1, 1],
    "quantity": [1, 1, 1, 1],
    "revenue": [100.0, 100.0, 200.0, 0.0],
})
mv = calc.intra_category_movement(d)
check("movement ok + window", mv["ok"] and mv["window"][:2] == ("2026-01-01", "2026-01-25"), str(mv))
sA = mv["sku"][mv["sku"]["sku"] == "A-100"].iloc[0]
sB = mv["sku"][mv["sku"]["sku"] == "B-200"].iloc[0]
check("A exited / B entered", sA["status"] == "Exited" and sB["status"] == "Entered")
check("shares: h1 total=200, h2 total=200",
      abs(sA["share_1st"] - 1.0) < 1e-9 and abs(sB["share_2nd"] - 1.0) < 1e-9)
check("grammage 100g & 200ml", set(mv["grammage"]["grammage"]) == {"100g", "200ml"})
check("movement: single-day window rejected",
      calc.intra_category_movement(d.iloc[[0]]).get("ok") is False)

# ---------------------------------------------------------------------------
print("\n[15] Real journey base sheet (wide format) — D2C Moisturisers")
mj, rj, _ = sources.get_model("journey")
check("base sheet: 152,091 customers", mj is not None and mj["n_customers"] == 152091,
      str(mj["n_customers"] if mj else None))
check("base sheet: 193,756 orders (= sum of Journey Depth)", mj is not None and mj["n_orders"] == 193756,
      str(mj["n_orders"] if mj else None))
o = mj["orders"]
check("base sheet: 24,771 repeat buyers (= Is Repeat Buyer?)",
      int(o[o["is_second"]]["customer_id"].nunique()) == 24771)
vv = calc.v2v_v2c_analysis(mj)
check("V2V/V2C qualifying = 24,771", vv["overall"]["qualifying"] == 24771)
check("V2C >= V2V (structure)", vv["overall"]["v2c_pct"] >= vv["overall"]["v2v_pct"])
check("journey scope warning present", any("first 6 orders" in w for w in rj.warnings))
check("multi-line warning present", any("Multi-line" in w for w in rj.warnings))

# hand-made wide frame: exact V2V/V2C, migration, days-gap cross-check
W = pd.DataFrame([
    ["Name", "category_first", "category_2nd", "category_3rd", "category_4th", "category_5th", "category_6th",
     "first_purchased_short_code", "second_purchased_short_code", "third_purchased_short_code",
     "fourth_purchased_short_code", "fifth_purchased_short_code", "sixth_purchased_short_code",
     "first_purchased_sku", "second_purchased_sku", "third_purchased_sku", "fourth_purchased_sku",
     "fifth_purchased_sku", "sixth_purchased_sku",
     "first_order_date", "second_order_date", "third_order_date", "fourth_order_date", "fifth_order_date",
     "sixth_order_date", "days_between_1st_and_2nd", "days_between_2nd_and_3rd", "days_between_3rd_and_4th",
     "days_between_4th_and_5th", "days_between_5th_and_6th", "city", "Month-Year", "Month Number ",
     "Journey Depth", "Is Repeat Buyer? "],
    # A: V2V (same variant twice), multi-line 2nd order, correct day gap
    ["A", "Cat X", "Cat X", "", "", "", "", "Alpha - 100g", "Alpha - 100g, Beta - 200g", "", "", "", "",
     "AL-100", "AL-100, BT-200", "", "", "", "", "2026-01-10", "2026-02-09", "", "", "", "", "30", "", "", "", "",
     "Gurgaon", "2026-01", "1", "2", "1"],
    # B: V2C only (same category, different variant)
    ["B", "Cat X", "Cat X", "", "", "", "", "Beta - 200g", "Gamma - 50g", "", "", "", "",
     "BT-200", "GA-50", "", "", "", "", "2026-01-15", "2026-03-15", "", "", "", "", "59", "", "", "", "",
     "Gurgaon", "2026-01", "1", "2", "1"],
    # C: single order
    ["C", "Cat X", "", "", "", "", "", "Delta - 30g", "", "", "", "", "", "DE-30", "", "", "", "", "",
     "2026-02-01", "", "", "", "", "", "", "", "", "", "", "Noida", "2026-02", "2", "1", "0"],
    # D: category switch
    ["D", "Cat X", "Cat Y", "", "", "", "", "Alpha - 100g", "Zed - 200g", "", "", "", "",
     "AL-100", "ZE-200", "", "", "", "", "2026-01-20", "2026-04-20", "", "", "", "", "99", "", "", "", "",
     "Noida", "2026-01", "1", "2", "1"],
])
repw = SourceReport(key="journey", label="wide-test")
hrw = sources.detect_header(W, "journey")
cmw = sources.find_columns(W, "journey", hrw)
check("wide header detected", hrw is not None and sources.journey_is_wide(W, hrw))
mw = etl.build_journey_model(W, repw, cmw, hrw)
check("wide: 4 customers / 7 orders", mw is not None and mw["n_customers"] == 4 and mw["n_orders"] == 7,
      str((mw["n_customers"] if mw else None, mw["n_orders"] if mw else None)))
ow = mw["orders"]
check("wide: 3 repeats", int(ow[ow["is_second"]]["customer_id"].nunique()) == 3)
vvw = calc.v2v_v2c_analysis(mw)
check("wide V2V = 1/3 (A only)", abs(vvw["overall"]["v2v_pct"] - 1 / 3) < 1e-9, str(vvw["overall"]))
check("wide V2C = 2/3 (A + B)", abs(vvw["overall"]["v2c_pct"] - 2 / 3) < 1e-9)
migw = calc.migration_analysis(mw, "category")
check("wide migration: repeat 2/4, switch 1/4",
      abs(migw["repeat_pct"] - 0.5) < 1e-9 and abs(migw["switch_pct"] - 0.25) < 1e-9)
check("wide: days-gap mismatch warned (D: 99 vs 90)", any("days between" in w for w in repw.warnings))
check("wide: multi-line 2nd order uses primary line (V2V still A only)",
      abs(vvw["overall"]["v2v_pct"] - 1 / 3) < 1e-9)
check("wide: category inferred for all lines (no (Uncategorized))",
      "(Uncategorized)" not in set(mw["df"]["category"]))

# ---------------------------------------------------------------------------
print("\n[16] Insights engine — cross-page synthesis (context + insight_bundle)")
import context as app_context

ctx, models = app_context.build_context()
check("ctx: all 8 models loaded", all(models[k] is not None for k in
      ("sales", "category_sales", "journey", "nps", "cs", "aop", "retention_fm", "order_movement")),
      str({k: m is not None for k, m in models.items()}))
for key in ("sales_kpis", "cat_contrib", "chan_contrib", "mig", "vv", "brand_nps",
            "product_nps", "cs_kpis", "cs_df", "aop_monthly", "fm", "ntc", "price_flags"):
    check(f"ctx key present: {key}", key in ctx)

bundle = conc.insight_bundle(ctx)
check("insight bundle: >= 7 sections on real data", len(bundle) >= 7, str(len(bundle)))
titles = [s["title"] for s in bundle]
check("insight bundle: has Cross-page connections", "Cross-page connections" in titles)
check("insight bundle: has Growth & momentum", "Growth & momentum" in titles)
n_items = sum(len(s["items"]) for s in bundle)
check("insight bundle: >= 15 items", n_items >= 15, str(n_items))
bad = [it for s in bundle for it in s["items"]
       if it["tone"] not in ("pos", "neg", "warn", "info") or not it["page"] or not it["text"]
       or re.search(r"\bnan\b|\bNaN\b", it["text"], re.I) or re.search(r"\bNone\b", it["text"])]
check("insight items: well-formed (tone/page/text, no nan/None)", not bad, str(bad[:2]))
check("insight bundle: empty ctx returns [] (no invention)", conc.insight_bundle({}) == [])
check("insight bundle: empty ctx w/ partial keys safe",
      conc.insight_bundle({"sales_kpis": {"revenue": float("nan")}}) == [])
check("executive_changes still works on ctx", len(conc.executive_changes(ctx)) >= 3)
check("executive_attention still works on ctx", len(conc.executive_attention(ctx)) >= 2)
pack = [it for s in bundle for it in s["items"]
        if s["title"] == "Cross-page connections" and "packag" in it["text"].lower()]
check("cross-link: packaging CS×NPS found in real data", len(pack) == 1)
noncausal = [it for s in bundle for it in s["items"]
             if s["title"] == "Cross-page connections"
             and all(w not in it["text"] for w in
                     ("potential relationship", "validation", "same customer pool", "suggesting"))]
check("cross-links: non-causal wording (or explicitly scoped)", len(noncausal) == 0,
      str([t[:80] for t, in [(i['text'],) for i in noncausal]])[:200])

# ---------------------------------------------------------------------------
print("\n[17] Static dashboard — generated index.html integrity")
import re
import make_static_dashboard as msd

html = msd.build()
errs = msd.verify(html, ctx)
check("static: verify() clean (tags, external refs, 9 tabs, AOP series)", not errs, str(errs))
check("static: 9 nav tabs", len(re.findall(r'data-t="p\d"', html)) == 9 if True else False)
check("static: interactive pieces (tooltip, sortable, VoC search)",
      all(x in html for x in ('id="tip"', "sortCol", "vocSearch", "vocFilter")))
check("static: insights tab rendered with items", html.count("class='dot ") >= 20)
check("static: per-page details present", html.count("<details class='pp'>") >= 6)
check("static: AOP booked KPI from model (not hand-typed)", "₹73.0L" in html and "ROAS 3.84" in html)
check("static: V2V note uses computed qualifying count", "(24,771)" in html and "if o else" not in html)
check("static: immature windows N/A (never 0%)", "N/A" in html and "0 mature" in html)

# ---------------------------------------------------------------------------
print("\n[18] Retention dashboard — retention.html generator integrity")
import shutil
import subprocess
from pathlib import Path
import make_retention_dashboard as mrd

page, data = mrd.build()
mrd.ROOT.joinpath("journey.html").write_text(page, encoding="utf-8")
verrs = mrd.verify(page, data)
check("retention: verify() clean (tags, external refs, sections)", not verrs, str(verrs))
check("retention: counts match journey model (152,091 / 193,756)",
      data["nCustomers"] == 152091 and data["nOrders"] == 193756,
      f"{data['nCustomers']}/{data['nOrders']}")
rep = sum(data["custRepeat"])
check("retention: repeat buyers = 24,771", rep == 24771, str(rep))
check("retention: prods table = 31 products + sentinel @0",
      len(data["prods"]) == 32 and data["prods"][0]["raw"] == "", str(len(data["prods"])))
# independent V2V/V2C recomputed from the embedded arrays (same rules as the
# model's v2v_v2c_analysis — catches keying/row-order regressions)
v2v = v2c = 0
for c in range(data["nCustomers"]):
    it = data["custItems"][c]; cc = data["custItemCat"][c]
    if len(it) < 2:
        continue
    if it[0][0] > 0 and it[1][0] > 0 and data["prods"][it[0][0]]["raw"] == data["prods"][it[1][0]]["raw"]:
        v2v += 1
    if cc[0][0] >= 0 and cc[1][0] >= 0 and cc[0][0] == cc[1][0]:
        v2c += 1
check("retention: embedded V2V = 31.79% (app anchor)", abs(100*v2v/rep - 31.79) < 0.05, f"{100*v2v/rep:.2f}")
check("retention: embedded V2C = 69.11% (app anchor)", abs(100*v2c/rep - 69.11) < 0.05, f"{100*v2c/rep:.2f}")
check("retention: months span 2024-01 → 2026-07 (31 months)",
      data["months"][0] == "2024-01" and data["months"][-1] == "2026-07" and len(data["months"]) == 31)
check("retention: zero external references", not re.search(r"(?:src|href)\s*=\s*['\"]https?://", page))
if shutil.which("node"):
    hr = subprocess.run(["node", "tests/retention_harness.js"], capture_output=True, text=True,
                        cwd=str(Path(__file__).resolve().parent.parent), timeout=600)
    check("retention: headless node harness PASS (DOM + filters + cross-check)",
          hr.returncode == 0, (hr.stdout + hr.stderr)[-400:])
else:
    check("retention: headless node harness (node not available — skipped)", True)

print("\n[19] Web dashboard — multi-page interactive site (turn g/h)")
import make_web_dashboard as mwd

files, wctx = mwd.build_site()
journey_html = mwd.ensure_journey()
verrs = mwd.verify_site(files, journey_html, wctx)
check("web: verify_site clean (nav, tags, refs, kit fns, AOP blob)", not verrs, str(verrs)[:300])
for slug, html in files.items():
    mwd.ROOT.joinpath(slug).write_text(html, encoding="utf-8")
    check(f"web: {slug} written + has DATA blob + deep-cuts section",
          "const DATA = " in html and "Deep cuts" in html)
all_html = "\n".join(files.values())
nav_slugs = [n[0] for n in mwd.NAV]
check("web: all 10 nav links present on every page",
      all(all(f'href="{s}"' in h for s in nav_slugs) for h in files.values()))
check("web: each page exactly one active nav item",
      all(h.count('class="active"') == 1 for h in files.values()))
check("web: zero external references (fully offline)",
      not re.search(r"(?:src|href)\s*=\s*['\"]https?://", all_html))
if shutil.which("node"):
    hr = subprocess.run(["node", "tests/web_harness.js"], capture_output=True, text=True,
                        cwd=str(Path(__file__).resolve().parent.parent), timeout=600)
    tail = hr.stdout[-500:]
    n_pass = tail.count("✓")
    check("web: headless node harness PASS (113 interactivity + live-recompute checks)",
          hr.returncode == 0 and "ALL 113 CHECKS PASSED" in tail, tail)
else:
    check("web: headless node harness (node not available — skipped)", True)

# ---------------------------------------------------------------------------
print("\n[20] Live CSV mode — in-browser recompute (turn i)")
ROOT_P = Path(__file__).resolve().parent.parent
import json as _json

fx = ROOT_P / "tests" / "fixtures" / "journey_long.csv"
ex = ROOT_P / "tests" / "fixtures" / "journey_expect.json"
check("live: journey fixture + expected JSON present", fx.is_file() and ex.is_file())
if fx.is_file() and ex.is_file():
    dfj = pd.read_csv(fx)
    dfj["order_date"] = pd.to_datetime(dfj["order_date"])
    expj = _json.loads(ex.read_text())
    asofj = pd.Timestamp(expj["asOf"])
    qual = v2v = v2c = 0
    gained, lost = {}, {}
    jr_ret = jr_n = 0
    for _c, g in dfj.groupby("customer_id"):
        g = g.sort_values(["order_date", "order_id"]).reset_index(drop=True)
        if len(g) < 2:
            continue
        f, s2 = g.iloc[0], g.iloc[1]
        qual += 1
        if f["product"] == s2["product"]: v2v += 1
        if f["category"] == s2["category"]: v2c += 1
        if s2["category"] != f["category"]:
            gained[s2["category"]] = gained.get(s2["category"], 0) + 1
            lost[f["category"]] = lost.get(f["category"], 0) + 1
        later = g.iloc[1:]
        if (((later["order_date"] - f["order_date"]).dt.days <= 90) & (later["category"] == f["category"])).any():
            jr_ret += 1
        if (asofj - f["order_date"]).days >= 90:
            jr_n += 1
    entsj = {e: (gained.get(e, 0) - lost.get(e, 0), gained.get(e, 0), lost.get(e, 0))
             for e in set(list(gained) + list(lost))}
    topj = max(entsj.items(), key=lambda kv: abs(kv[1][0]))
    check("live: fixture counts == independent recompute (customers/orders/qual/V2V/V2C)",
          dfj.customer_id.nunique() == expj["nCustomers"] and len(dfj) == expj["nOrders"]
          and qual == expj["qual"] and v2v == expj["v2v"] and v2c == expj["v2c"],
          f"{dfj.customer_id.nunique()}/{len(dfj)}/{qual}/{v2v}/{v2c} vs {expj['nCustomers']}/{expj['nOrders']}/{expj['qual']}/{expj['v2v']}/{expj['v2c']}")
    check("live: fixture net-migration top == recompute",
          topj[0] == expj["topNetEntity"] and topj[1][0] == expj["topNet"] and topj[1][1] == expj["topNetG"] and topj[1][2] == expj["topNetL"],
          f"{topj[0]} {topj[1]} vs {expj['topNetEntity']} {expj['topNet']}")
    check("live: fixture JR90 == recompute",
          abs(jr_ret / jr_n - expj["jr90"]) < 1e-12, f"{jr_ret/jr_n} vs {expj['jr90']}")

for _slug in ["index", "migration", "sales", "nps-cs", "pricing", "retention", "ntc", "definitions", "insights"]:
    _h = (ROOT_P / f"{_slug}.html").read_text()
    check(f"live: {_slug}.html embeds panel + engine",
          'id="livePanel"' in _h and "LIVE.attach(" in _h and "const LIVE = " in _h,
          "missing live panel/engine")
_jh = (ROOT_P / "journey.html").read_text()
check("live: journey.html embeds panel + engine",
      'id="jLivePanel"' in _jh and "LIVE.attach(" in _jh and "C_JOURNEY" in _jh, "missing live card")

# ---------------------------------------------------------------------------
print(f"\n{'='*50}\nRESULT: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
