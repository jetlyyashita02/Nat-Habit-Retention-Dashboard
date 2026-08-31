"""
generate_samples.py — creates two SYNTHETIC demo files used ONLY when no
real upload is present:
    data/sample_sales.csv   (Sales/Revenue aggregate, monthly SKU × channel)
    data/sample_journey.csv (customer × order level, for computed retention/migration)

Both are derived from the SAME product universe as the real reference files
(categories, SKUs, channels, the Feb-2026 price revisions logged in the
Retention FM) so every page of the dashboard can be exercised end-to-end.
They are clearly marked DEMO in the UI and in the README. Regenerate with:
    python data/generate_samples.py
"""
import calendar
import datetime as dt
import random

import pandas as pd

random.seed(42)
OUT_SALES = "sample_sales.csv"
OUT_JOURNEY = "sample_journey.csv"

# ---------------- product universe (matches the real reference files) ------
FM = [  # (sku, product, gram)
    ("FC-CWDM-FW-030", "Flax Walnut (Cold) 35+ Face Malai - 30g", 30),
    ("FC-HHDM-GAT-030", "GreenApple Tulsi (Hot Humid) 13-19 Yrs Face Malai - 30g", 30),
    ("FC-HHDM-TV-030", "Tomato Vetiver (Hot Humid) 20-35 Yrs Face Malai - 30g", 30),
    ("FC-HHDM-FC-030", "Flax Carrot (Hot Humid) 35+ Face Malai - 30g", 30),
    ("FC-DM-NR-030", "Cocoa Mogra (Overnight) Face Malai - 30g", 30),
    ("FC-HDDM-PT-030", "Pomegranate Tulsi (Hot Dry) 13-19 Yrs Face Malai - 30g", 30),
    ("FC-HDDM-FB-030", "Flax Bakuchi (Hot Dry) 35+ Face Malai - 30g", 30),
    ("FC-DM-PG-030", "Turmeric Nutmeg (Pigmentation) Face Malai - 30g", 30),
    ("FC-HDDM-TR-030", "Tomato Rosehip (Hot Dry) 20-35 Yrs Face Malai - 30g", 30),
    ("FC-DM-AA-030", "Clove Tea-Tree (Anti-Acne) Face Malai - 30g", 30),
    ("FC-DM-DP-030", "Honey Multi-Nut (Dry & Peeling Skin) Face Malai - 30g", 30),
    ("FC-CWDM-BT-030", "Winter Blackseed Tulsi (Cold) 13-19 Yrs Face Malai - 30g", 30),
    ("FC-CWDM-TP-030", "Tomato Patchouli (Cold) 20-35 Yrs Face Malai - 30g", 30),
    ("FC-HDDM-FB-050", "Flax Bakuchi (Hot Dry) 35+ Face Malai - 50g", 50),
    ("FC-DM-NR-050", "Cocoa Mogra (Overnight) Face Malai - 50g", 50),
    ("FC-DM-PG-050", "Turmeric Nutmeg (Pigmentation) Face Malai - 50g", 50),
    ("FC-HHDM-FC-050", "Flax Carrot (Hot Humid) 35+ Face Malai - 50g", 50),
    ("FC-HDDM-TR-050", "Tomato Rosehip (Hot Dry) 20-35 Yrs Face Malai - 50g", 50),
    ("FC-HHDM-TV-050", "Tomato Vetiver (Hot Humid) 20-35 Yrs Face Malai - 50g", 50),  # launched Feb-26
]
GEL = [
    ("AG-DM-NT-050", "Neem TeaTree Active Gel - 50g", 50),
    ("AG-DM-AC-050", "Aloe Cactus Hydra Lift Active Gel - 50g", 50),
    ("AG-DM-ON-050", "Olive Vit-E Night Active Gel - 50g", 50),
    ("AG-DM-BT-050", "Beetroot Tomato Vit-A Active Gel - 50g", 50),
    ("AG-DM-OK-050", "Orange Kiwi Vit-C Active Gel - 50g", 50),
]
ALOE = [("AVG-80", "Aloe Vera Gel - 80g", 80)]
NETRAA = [("PN-15", "Pure Netraa Eye Serum - 15ml", 15)]
SERUM = [
    ("FS-03", "Face Serum Vitamin-C Brightening - 30ml", 30),
    ("FS-04", "Face Serum Hyaluronic Hydra - 30ml", 30),
]

PRODUCTS = ([(s, p, "Face Malai", g) for s, p, g in FM] +
            [(s, p, "Active Gel", g) for s, p, g in GEL] +
            [(s, p, "Aloe Vera Gel", g) for s, p, g in ALOE] +
            [(s, p, "Pure Netraa", g) for s, p, g in NETRAA] +
            [(s, p, "FACE SERUM", g) for s, p, g in SERUM])

BASE_PRICE = {
    "Face Malai": {30: 449.0, 50: 649.0},
    "Active Gel": {50: 449.0},
    "Aloe Vera Gel": {80: 749.0},
    "Pure Netraa": {15: 899.0},
    "FACE SERUM": {30: 999.0},
}

# Feb-2026 revisions exactly as logged in the Retention FM sheet
INC_FEB26 = {"FC-DM-AA-030": 1.08}                                   # increased
DEC_FEB26 = {s: 0.95 for s in ["FC-CWDM-FW-030", "FC-HHDM-TV-030", "FC-HHDM-FC-030", "FC-HDDM-PT-030",
                               "FC-HDDM-FB-030", "FC-CWDM-BT-030", "FC-CWDM-TP-030",
                               "FC-HDDM-FB-050", "FC-HHDM-FC-050", "FC-HDDM-TR-050"]}
# one extra move outside the FM log so detection isn't perfectly matched
EXTRA_MOVES = {("AG-DM-OK-050", (2025, 11)): 1.06}

CHANNELS = ["D2C", "NYKAA", "AMAZON", "FLIPKART", "MYNTRA", "BLINKIT", "INSTAMART",
            "ZEPTO", "RETAIL", "Bigbasket", "Firstcry"]
CH_W = [0.42, 0.14, 0.14, 0.10, 0.05, 0.05, 0.03, 0.03, 0.02, 0.01, 0.01]

# monthly demand weights by season (Dec-Feb / Mar-May / Jun-Sep / Oct-Nov)
def season_w(month: int, variant: str) -> float:
    winter, presummer, summer, monsoon = 1.0, 1.0, 1.0, 1.0
    key = variant.split(" ")[0]
    prof = {
        "Turmeric": (1.5, 0.9, 0.7, 0.9), "Flax": (1.0, 1.1, 0.9, 1.1),
        "Pomegranate": (0.6, 1.3, 1.1, 0.7), "Cocoa": (1.3, 1.2, 1.0, 1.1),
        "Tomato": (1.1, 1.2, 1.0, 0.9), "Honey": (1.2, 1.0, 0.8, 0.9),
        "GreenApple": (0.8, 1.0, 1.0, 1.2), "Clove": (1.0, 1.1, 0.9, 1.0),
        "Winter": (1.6, 0.4, 0.3, 0.8), "Neem": (1.0, 1.0, 1.0, 1.0),
        "Aloe": (0.9, 1.2, 1.1, 1.0), "Olive": (1.2, 1.0, 0.8, 0.9),
        "Beetroot": (1.1, 1.0, 0.9, 1.0), "Orange": (1.0, 1.1, 0.9, 1.0),
    }
    w = prof.get(key, (1, 1, 1, 1))
    if month in (12, 1, 2):
        return w[0]
    if month in (3, 4, 5):
        return w[1]
    if month in (6, 7, 8, 9):
        return w[3]
    return w[2]

MONTHS = []
y, m = 2024, 1
while (y, m) <= (2026, 8):
    MONTHS.append((y, m))
    m += 1
    if m == 13:
        y, m = y + 1, 1

def price_on(sku, cat, gram, ym):
    p = BASE_PRICE[cat][gram]
    for (s, mo), f in EXTRA_MOVES.items():
        if s == sku and ym > mo:
            p *= f
    factor = 1.0
    if ym > (2026, 2):
        factor = INC_FEB26.get(sku, DEC_FEB26.get(sku, 1.0))
    elif ym == (2026, 2):
        # month of the revision: blend old + new price
        factor = 0.5 + 0.5 * INC_FEB26.get(sku, DEC_FEB26.get(sku, 1.0))
    return p * factor

def available(sku, ym):
    if sku == "FC-HHDM-TV-050" and ym < (2026, 2):
        return False
    if sku.startswith("FS-") and ym < (2026, 7):
        return False
    return True

def gen_sales():
    rows = []
    for (y, m) in MONTHS:
        ym = (y, m)
        growth = 1.0 + 0.55 * (MONTHS.index(ym) / len(MONTHS))  # steady portfolio growth
        for sku, product, cat, gram in PRODUCTS:
            if not available(sku, ym):
                continue
            w = season_w(m, product) * random.uniform(0.85, 1.15) * growth
            for ch, chw in zip(CHANNELS, CH_W):
                if ch in ("BLINKIT", "ZEPTO", "INSTAMART") and ym < (2025, 8):
                    continue
                if ch == "RETAIL" and ym < (2025, 11):
                    continue
                qty = max(0, int(random.gauss(w * chw * (1200 if gram == 30 else 700), 120)))
                if qty == 0:
                    continue
                up = price_on(sku, cat, gram, ym)
                real = up * random.uniform(0.985, 1.015)          # realized ≈ list ±1.5%
                orders = int(qty * random.uniform(0.55, 0.75))
                customers = int(orders * random.uniform(0.82, 0.95))
                rows.append({
                    "order_date": f"{y:04d}-{m:02d}-01", "SKU": sku, "order_source": ch,
                    "product": product, "category": cat, "orders": orders,
                    "customers": customers, "quantity": qty,
                    "revenue": round(qty * real, 0),
                })
    df = pd.DataFrame(rows)
    df.to_csv(OUT_SALES, index=False)
    print(f"{OUT_SALES}: {len(df)} rows, months {df['order_date'].min()}..{df['order_date'].max()}, "
          f"revenue ₹{df['revenue'].sum()/1e6:,.1f}M")

# ---------------- journey (customer × order) --------------------------------
ENTRY_CAT_W = {"Face Malai": 0.55, "Active Gel": 0.20, "Aloe Vera Gel": 0.12,
               "Pure Netraa": 0.08, "FACE SERUM": 0.05}
FIRST_MONTHS = []  # Jan-25 .. Aug-26
_y, _m = 2025, 1
while len(FIRST_MONTHS) < 20:
    FIRST_MONTHS.append((_y, _m))
    _m += 1
    if _m == 13:
        _y, _m = _y + 1, 1

def cat_for_ym(ym):
    items = list(ENTRY_CAT_W.items())
    if ym < (2026, 7):
        items = [(k, v) for k, v in items if k != "FACE SERUM"]
        tot = sum(v for _, v in items)
        items = [(k, v / tot) for k, v in items]
    r = random.random(); acc = 0
    for k, v in items:
        acc += v
        if r <= acc:
            return k
    return items[-1][0]

def variant_for(cat):
    prods = [(s, p) for s, p, c, g in PRODUCTS if c == cat]
    return random.choice(prods)

def gen_journey():
    rows = []
    cid = 0
    oid = 10000
    for (y, m) in FIRST_MONTHS:
        vol = int(350 + 950 * (FIRST_MONTHS.index((y, m)) / len(FIRST_MONTHS)))
        for _ in range(vol):
            cid += 1
            cat = cat_for_ym((y, m))
            sku, prod = variant_for(cat)
            ch = random.choices(CHANNELS, CH_W)[0]
            d1 = dt.date(y, m, random.randint(1, 26 if (y, m) == (2026, 8) else 28))
            rows.append((cid, f"ORD-{oid}", d1, sku, prod, cat, ch, 1)); oid += 1
            # repeat behaviour
            propensity = random.random()
            # price-increase effect: Clove Tea-Tree repeat propensity drops after the revision
            if sku == "FC-DM-AA-030" and d1 >= dt.date(2026, 2, 2):
                propensity *= 0.55
            if propensity > 0.72:
                continue
            gap = max(5, int(random.lognormvariate(4.1, 0.55)))
            d2 = d1 + dt.timedelta(days=gap)
            if d2 > dt.date(2026, 8, 26):
                continue
            r = random.random()
            if r < 0.30:                      # V2V: same variant
                s2, p2 = sku, prod
            elif r < 0.55:                    # V2C: same category, different variant
                s2, p2 = variant_for(cat)
                if s2 == sku:
                    s2, p2 = variant_for(cat)
            else:                             # cross-category
                c2 = cat_for_ym((d2.year, d2.month))
                s2, p2 = variant_for(c2)
            rows.append((cid, f"ORD-{oid}", d2, s2, p2, c2 if r >= 0.55 else cat, ch, 1)); oid += 1
            if r < 0.15:                      # multi-line order (2nd line same order)
                s3, p3 = variant_for(cat if r < 0.55 else c2)
                rows.append((cid, f"ORD-{oid-1}", d2, s3, p3, cat if r < 0.55 else c2, ch, 1))
            if propensity < 0.30 and random.random() < 0.45:   # 3rd order
                g3 = max(4, int(random.lognormvariate(3.8, 0.5)))
                d3 = d2 + dt.timedelta(days=g3)
                if d3 <= dt.date(2026, 8, 26):
                    s4, p4 = variant_for(cat if random.random() < 0.6 else cat_for_ym((d3.year, d3.month)))
                    rows.append((cid, f"ORD-{oid}", d3, s4, p4, cat, ch, 1)); oid += 1
    df = pd.DataFrame(rows, columns=["customer_id", "order_id", "order_date", "sku", "product", "category", "channel", "quantity"])
    df["order_date"] = df["order_date"].map(lambda d: d.isoformat())
    df.to_csv(OUT_JOURNEY, index=False)
    print(f"{OUT_JOURNEY}: {len(df)} rows, {df['customer_id'].nunique()} customers, "
          f"{df['order_id'].nunique()} orders, {df['order_date'].min()}..{df['order_date'].max()}")

if __name__ == "__main__":
    import os
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    gen_sales()
    gen_journey()
