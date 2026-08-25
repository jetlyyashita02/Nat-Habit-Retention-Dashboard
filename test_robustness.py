"""Robustness harness — deforms every input sheet and asserts the numbers
the dashboard reads stay IDENTICAL. Run: python tests/test_robustness.py"""
import io
import pathlib
import re
import sys

import pandas as pd

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import etl            # noqa: E402
import metrics as M   # noqa: E402
import sources as S   # noqa: E402

DATA = REPO / "data"
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok  " if cond else "  FAIL") + f" {name}" + (f"  [{detail}]" if detail and not cond else ""))


def to_csv_bytes(df):
    return df.to_csv(index=False).encode("utf-8")


# ------------------------------------------------------------------ journey
def journey_baseline():
    long = etl.load_journey_csv(DATA / "sample_journeys.csv")
    L = M.loyalty_metrics(long)
    return (long.customer.nunique(),
            long.drop_duplicates(["customer", "order_seq"]).shape[0],
            L["V2V Loyalty %"], L["V2C Loyalty %"])


def journey_mutations():
    raw = pd.read_csv(DATA / "sample_journeys.csv")

    # 1) renamed + case/space-mangled headers
    m1 = raw.copy()
    ren = {"Name": " Customer ID ", "city": "City",
           "first_purchased_sku": "1st Purchase SKU",
           "second_order_date": "2nd Order Date",
           "Journey Depth": "Total Orders", "Month-Year": "Entry Month"}
    m1 = m1.rename(columns=ren)
    yield "renamed headers", m1

    # 2) reordered columns + junk columns
    m2 = raw.copy()
    m2["__notes"] = "junk"
    m2[" unnamed helper"] = ""
    cols = list(m2.columns)
    order = cols[10:] + cols[:10]
    yield "reordered + junk columns", m2[order]

    # 3) ISO dates
    m3 = raw.copy()
    def iso(v):
        if pd.isna(v):
            return v
        d = pd.to_datetime(v, format="%b %d, %Y")
        return d.strftime("%Y-%m-%d")
    for c in m3.columns:
        if c.endswith("_order_date"):
            m3[c] = m3[c].apply(iso)
    yield "ISO date format", m3


def test_journey():
    print("JOURNEY")
    base = journey_baseline()
    for name, mut in journey_mutations():
        try:
            long = etl.load_journey_csv(io.BytesIO(to_csv_bytes(mut)))
            L = M.loyalty_metrics(long)
            got = (long.customer.nunique(),
                   long.drop_duplicates(["customer", "order_seq"]).shape[0],
                   L["V2V Loyalty %"], L["V2C Loyalty %"])
            check(f"journey: {name}", got == base, f"{got} != {base}")
        except Exception as e:
            check(f"journey: {name}", False, str(e)[:90])


# ------------------------------------------------------------------ sales
def test_sales():
    print("SALES")
    base = S.load_sales(DATA / "sales_rev_aggregate.csv")
    b = (round(base.rev.sum(), 2), int(base.orders.sum()), base.month.nunique())
    raw = pd.read_csv(DATA / "sales_rev_aggregate.csv")
    m = raw.rename(columns={"order_date": "Order Date", "sku": "SKU Code",
                            "order_source": "Channel", "short_code": "Product Name",
                            "product_category": "Category", "rev": "Revenue (₹)",
                            "qty": "Quantity", "orders": "No. of Orders",
                            "customers": "Unique Customers"})
    m["Order Date"] = pd.to_datetime(m["Order Date"]).dt.strftime("%d-%m-%Y")
    m["Revenue (₹)"] = m["Revenue (₹)"].apply(lambda v: f"₹{v:,.2f}")
    m["extra"] = ""
    m = m[["extra", "Product Name", "Channel", "Revenue (₹)", "SKU Code",
           "No. of Orders", "Order Date", "Category", "Unique Customers", "Quantity"]]
    try:
        got_df = S.load_sales(io.BytesIO(to_csv_bytes(m)))
        g = (round(got_df.rev.sum(), 2), int(got_df.orders.sum()), got_df.month.nunique())
        check("sales: renamed + ₹/comma + dd-mm-yyyy + reorder", g == b, f"{g} != {b}")
    except Exception as e:
        check("sales: mutations", False, str(e)[:90])


# ------------------------------------------------------------------ nps
def test_nps():
    print("NPS")
    base = S.load_nps(DATA / "nps_raw.csv")
    b = (S.nps_score(base["NPS Score For Brand"]),
         sum(len(x) > 0 for x in base["_likes"]))
    raw = pd.read_csv(DATA / "nps_raw.csv")
    m = raw.rename(columns={"NPS Score For Brand": "Brand NPS (0-10)",
                            "NPS Score For Product": "Product NPS",
                            "created_at": "Response Date"})
    m["Response Date"] = m["Response Date"].str.replace(",", "", regex=False)
    try:
        got = S.load_nps(io.BytesIO(to_csv_bytes(m)))
        g = (S.nps_score(got["NPS Score For Brand"]),
             sum(len(x) > 0 for x in got["_likes"]))
        check("nps: renamed score cols + date variant", g == b, f"{g} != {b}")
    except Exception as e:
        check("nps: mutations", False, str(e)[:90])


# ------------------------------------------------------------------ cs
def test_cs():
    print("CS")
    base = S.load_cs(DATA / "cs_fb.csv")
    b = round(base.ship_hours.median(), 4)
    raw = pd.read_csv(DATA / "cs_fb.csv")
    m = raw.rename(columns={"created_at": "Ticket Date",
                            "delivery_time": "Delivered On"})
    m["Ticket Date"] = pd.to_datetime(m["Ticket Date"], format="%d-%m-%Y").dt.strftime("%Y-%m-%d")
    try:
        got = S.load_cs(io.BytesIO(to_csv_bytes(m)))
        g = round(got.ship_hours.median(), 4)
        check("cs: renamed + ISO ticket dates", g == b, f"{g} != {b}")
    except Exception as e:
        check("cs: mutations", False, str(e)[:90])


# ------------------------------------------------------------------ aop
def test_aop():
    print("AOP")
    base = S.load_aop(DATA / "aop_data.csv")
    r = base["revenue"]

    def fm_h1(df):
        x = df[(df["Category"] == "Face Malai") & df["month"].between("2026-01", "2026-06")]
        return round(x["value"].sum(), 1)

    b = (fm_h1(r), r["month"].nunique())
    raw = pd.read_csv(DATA / "aop_data.csv", header=None)
    # 1) title row inserted above
    m1 = pd.concat([pd.DataFrame([["AOP PLAN FY26"] + [None] * (raw.shape[1] - 1)]),
                    raw], ignore_index=True)
    try:
        got = S.load_aop(io.BytesIO(to_csv_bytes(m1)))
        g = (fm_h1(got["revenue"]), got["revenue"]["month"].nunique())
        check("aop: title row above header", g == b, f"{g} != {b}")
    except Exception as e:
        check("aop: title row", False, str(e)[:90])
    # 2) full month names in header row
    m2 = raw.copy()
    m2.iloc[1] = [re.sub(r"^([A-Za-z]{3})[' ](\d{2})$", lambda mm: mm.group(0), v)
                  if isinstance(v, str) else v for v in m2.iloc[1]]
    hdr = list(m2.iloc[1])
    full = {"Jan": "January", "Feb": "February", "Mar": "March", "Apr": "April",
            "May": "May", "Jun": "June", "Jul": "July", "Aug": "August",
            "Sep": "September", "Oct": "October", "Nov": "November", "Dec": "December"}
    m2.iloc[1] = [re.sub(r"^([A-Za-z]{3})(')(\d{2})$",
                         lambda mm: f"{full.get(mm.group(1), mm.group(1))} 20{mm.group(3)}",
                         str(v)) if isinstance(v, str) else v for v in hdr]
    try:
        got = S.load_aop(io.BytesIO(to_csv_bytes(m2)))
        g = (fm_h1(got["revenue"]), got["revenue"]["month"].nunique())
        check("aop: full month names ('January 2026')", g == b, f"{g} != {b}")
    except Exception as e:
        check("aop: month names", False, str(e)[:90])


# ------------------------------------------------------------------ retention
def test_retention():
    print("RETENTION")
    main_b, side_b = S.load_retention(DATA / "retention_fm_feb26.csv")
    b = (int(main_b["Customer"].sum()), len(main_b),
         round(main_b[main_b.attrs["day_cols"]].sum().sum(), 2),
         None if side_b is None else len(side_b))
    raw = pd.read_csv(DATA / "retention_fm_feb26.csv", header=None)
    m = raw.copy()
    # rename day headers to '15d %', '30 days' style
    for i in range(m.shape[1]):
        v = str(m.iloc[0, i])
        mm = re.match(r"^(\d+) Days %$", v)
        if mm:
            m.iloc[0, i] = f"{mm.group(1)}d %"
    m.insert(4, "junk col", None)
    try:
        got_main, got_side = S.load_retention(io.BytesIO(to_csv_bytes(m)))
        g = (int(got_main["Customer"].sum()), len(got_main),
             round(got_main[got_main.attrs["day_cols"]].sum().sum(), 2),
             None if got_side is None else len(got_side))
        check("retention: renamed day windows + inserted column", g == b, f"{g} != {b}")
    except Exception as e:
        check("retention: mutations", False, str(e)[:90])


# ------------------------------------------------------------------ movement
def test_movement():
    print("MOVEMENT")
    base = S.load_movement(DATA / "order_movement_ntc.csv")
    b = (base["month"].nunique(), round(base["sec_pct"].mean(), 4))
    raw = pd.read_csv(DATA / "order_movement_ntc.csv", skiprows=1)
    m = raw.copy().rename(columns={"onb_month": "Cohort Month"})
    junk = pd.DataFrame([["export", None] + [None] * (m.shape[1] - 2)],
                        columns=m.columns)
    m = pd.concat([junk, junk, m], ignore_index=True)
    try:
        got = S.load_movement(io.BytesIO(to_csv_bytes(m)))
        g = (got["month"].nunique(), round(got["sec_pct"].mean(), 4))
        check("movement: renamed cohort col + junk rows above", g == b, f"{g} != {b}")
    except Exception as e:
        check("movement: mutations", False, str(e)[:90])




# ------------------------------------------------------------------ decoder
def test_decoder_autoregister():
    print("DECODER")
    import etl as E
    # clean registry for determinism
    E.OVERRIDES.clear()
    E.save_overrides()
    raw = pd.read_csv(DATA / "sample_journeys.csv")
    row = raw.iloc[0].copy()
    row["Name"] = 999999
    row["first_purchased_sku"] = "FC-ZZ-NEW-030"
    row["first_purchased_short_code"] = "New Botanical (Anti-Acne) Face Malai - 30g"
    row["second_purchased_sku"] = None
    for c in raw.columns:
        if c.startswith(("second", "third", "fourth", "fifth", "sixth")):
            row[c] = None
    row["Journey Depth"] = 1
    m = pd.concat([raw, row.to_frame().T], ignore_index=True)
    try:
        long = E.load_journey_csv(io.BytesIO(to_csv_bytes(m)))
        ok1 = 999999 in set(long["customer"])
        ok2 = "FC-ZZ-NEW-030" in E.OVERRIDES
        ok3 = long[long["customer"] == 999999]["sku_key"].iloc[0] == "New Botanical 30g"
        base = journey_baseline()
        ok4 = long.customer.nunique() == base[0] + 1
        check("decoder: unknown code auto-learned from name", ok1 and ok2 and ok3 and ok4)
        # and the learned code now decodes standalone
        check("decoder: learned code decodes standalone",
              E.parse_sku_code("FC-ZZ-NEW-030") is not None)
    except Exception as ex:
        check("decoder: auto-register", False, str(ex)[:90])
    finally:
        E.OVERRIDES.clear()
        E.save_overrides()

if __name__ == "__main__":
    test_journey()
    test_sales()
    test_nps()
    test_cs()
    test_aop()
    test_retention()
    test_movement()
    test_decoder_autoregister()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", *FAIL, sep="\n  - ")
        sys.exit(1)
    print("ALL ROBUSTNESS CHECKS PASSED — numbers identical under format changes")
