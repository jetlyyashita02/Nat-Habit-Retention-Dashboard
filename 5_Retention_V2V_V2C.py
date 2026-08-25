"""📈 Retention & Metabase view — V2V % / V2C % in % format + retention curves."""
import io

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import etl
import metrics as M
import sources as S

st.set_page_config(page_title="Retention & V2V/V2C", page_icon="📈", layout="wide")
st.title("📈 Retention — Metabase view (V2V % & V2C %)")
st.caption("Same format as the Retention FM sheet: customers acquired, repeat "
           "rates and V2V / V2C in % — computed live from the journey dump, "
           "plus the uploaded retention curves.")

RET_DAYS = [15, 30, 60, 90, 120, 180, 240, 300, 360]


@st.cache_data(show_spinner="Loading…")
def _j(b: bytes):
    return etl.load_any(io.BytesIO(b))[0]


@st.cache_data(show_spinner="Loading sample…")
def _j_s():
    return etl.load_journey_csv("data/sample_journeys.csv")


@st.cache_data(show_spinner="Loading…")
def _ret(b: bytes):
    return S.load_retention(b)


@st.cache_data(show_spinner="Loading sample…")
def _ret_s():
    return S.load_retention("data/retention_fm_feb26.csv")


j_up = st.sidebar.file_uploader("Journey CSV (for V2V/V2C + computed curves)",
                                type=["csv"], key="j_up5")
long_df = _j(j_up.getvalue()) if j_up else _j_s()
r_up = st.sidebar.file_uploader("Retention sheet CSV (SKU × day-window %)",
                                type=["csv"], key="ret_up5")
ret, side = _ret(r_up.getvalue()) if r_up else _ret_s()
S.show_warnings(long_df, ret)

# ------------------------------------------------- metabase-style table
st.header("Metabase table — category & variant level")


def metabase_table(level: str):
    d = long_df
    prim = d[(d["order_seq"] == 1) & (d["item_seq"] == 1)]
    depth = d.groupby("customer")["journey_depth"].first()
    pairs = (prim[prim["order_seq"] == 1][["customer", level]].rename(columns={level: "e"})
             .merge(prim[d["order_seq"] == 2][["customer", level]]
             .rename(columns={level: "n"}), on="customer", how="inner"))
    gaps12 = d[d["order_seq"] == 2].drop_duplicates("customer").set_index("customer")["gap_days"]
    gaps23 = d[d["order_seq"] == 3].drop_duplicates("customer").set_index("customer")["gap_days"]
    rows = []
    for key, g in prim.groupby(level):
        custs = g["customer"].unique()
        n = len(custs)
        if not n:
            continue
        dep = depth.reindex(custs)
        pg = pairs[pairs["e"] == key]
        v2v = 100 * (pg["n"] == pg["e"]).mean() if len(pg) else None
        v2c = 100 * (pg["n"] == pg["e"]).mean() if len(pg) else None  # same-level repeat
        rows.append({
            level: key, "Customers Acquired": n,
            "2nd order %": 100 * (dep >= 2).mean(),
            "3rd order %": 100 * (dep >= 3).mean(),
            "4th order %": 100 * (dep >= 4).mean(),
            f"{level} repeat % (V2V)": v2v,
            "Avg days 1→2": gaps12.reindex(custs).mean(),
            "Avg days 2→3": gaps23.reindex(custs).dropna().mean() if (depth.reindex(custs) >= 3).any() else None,
        })
    return pd.DataFrame(rows).sort_values("Customers Acquired", ascending=False)


tab_cat, tab_var = st.tabs(["Category level", "Variant level"])
for tab, level in [(tab_cat, "category"), (tab_var, "variant")]:
    with tab:
        t = metabase_table(level)
        if len(t):
            tt = t.copy()
            for c in ["2nd order %", "3rd order %", "4th order %",
                      f"{level} repeat % (V2V)"]:
                tt[c] = tt[c].round(1)
            cfg = {c: st.column_config.NumberColumn(c, format="%.1f%%")
                   for c in ["2nd order %", "3rd order %", "4th order %",
                             f"{level} repeat % (V2V)"]}
            st.dataframe(tt, hide_index=True, width='stretch',
                         column_config=cfg)
            st.download_button(f"⬇ Download {level} table", tt.to_csv(index=False),
                               f"metabase_{level}.csv", key=f"dl_mb_{level}")
            st.plotly_chart(px.bar(tt.head(15), x=level, y="2nd order %",
                                   title=f"2nd-order rate by {level}",
                                   color_discrete_sequence=["#E8604A"])
                            .update_layout(height=340), width='stretch')

# ------------------------------------------------- computed curves
st.header("Computed retention curves (from journey data)")
st.caption("Share of each entry cohort that reordered within N days of their first order.")


def computed_curves(level):
    d = long_df
    prim = d[(d["order_seq"] == 1) & (d["item_seq"] == 1)][["customer", level, "order_date"]]
    second = d[d["order_seq"] == 2].drop_duplicates("customer")[["customer", "order_date"]]
    m = prim.merge(second, on="customer", how="left", suffixes=("_1", "_2"))
    m["gap"] = (m["order_date_2"] - m["order_date_1"]).dt.days
    rows = []
    for key, g in m.groupby(level):
        row = {level: key, "Customers": len(g)}
        for days in RET_DAYS:
            row[f"{days}d"] = round(100 * (g["gap"] <= days).mean(), 2)
        rows.append(row)
    return pd.DataFrame(rows).sort_values("Customers", ascending=False)


lvl = st.radio("Curve level", ["category", "variant"], horizontal=True, key="curve_lvl")
curves = computed_curves(lvl)
if len(curves):
    cfg = {f"{d_}d": st.column_config.NumberColumn(f"{d_}d", format="%.2f%%")
           for d_ in RET_DAYS}
    st.dataframe(curves, hide_index=True, width='stretch', column_config=cfg)
    st.download_button("⬇ Download computed curves", curves.to_csv(index=False),
                       "computed_retention.csv", key="dl_curves")
    melted = curves.melt(id_vars=[lvl, "Customers"], var_name="window", value_name="%")
    melted["window"] = melted["window"].str.replace("d", "", regex=False).astype(int)
    top = curves.head(8)[lvl].tolist()
    st.plotly_chart(px.line(melted[melted[lvl].isin(top)], x="window", y="%",
                            color=lvl, markers=True,
                            title=f"Retention curves — top {len(top)} by cohort size")
                    .update_layout(height=420), width='stretch')

# ------------------------------------------------- uploaded sheet
st.header("Uploaded retention sheet (reference format)")
if len(ret):
    day_cols = ret.attrs.get("day_cols") or S.RET_DAY_COLS
    cols = ["sku", "short_code", "channel", "Customer"] + day_cols
    have = [c for c in cols if c in ret.columns]
    show = ret[have].copy()
    cfg = {c: st.column_config.NumberColumn(c, format="%.2f%%")
           for c in day_cols if c in show.columns}
    st.dataframe(show, hide_index=True, width='stretch', column_config=cfg)
    melt = ret.melt(id_vars=["sku"], value_vars=[c for c in day_cols if c in ret.columns],
                    var_name="window", value_name="%")
    melt["window"] = (melt["window"].str.extract(r"(\d+)").astype(float))
    st.plotly_chart(px.line(melt, x="window", y="%", color="sku", markers=True,
                            title="Retention curves by SKU (uploaded sheet)")
                    .update_layout(height=440), width='stretch')
    st.download_button("⬇ Download sheet data", ret.to_csv(index=False),
                       "retention_sheet.csv", key="dl_ret")
