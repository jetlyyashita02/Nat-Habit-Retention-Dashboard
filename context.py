"""
context.py — single shared builder for the dashboard context (ctx).

Used by:
  * app.py                  (Executive Overview)
  * pages/8_Insights.py     (cross-page synthesis)
  * make_static_dashboard.py (final static HTML export)

Keeping the ctx construction in ONE place guarantees the overview, the
Insights page and the static export always show the same numbers for the
same uploaded data. Nothing business-specific is hardcoded here — every
value comes from the currently loaded sources.
"""
from __future__ import annotations

import pandas as pd

import sources
from calculations import (aop_monthly, category_contribution, channel_contribution,
                          cs_kpis, derived_price_changes, fm_retention_table,
                          migration_analysis, nps_score_stats, price_flags,
                          sales_filter, sales_kpis, v2v_v2c_analysis)

MODEL_KEYS = ["sales", "category_sales", "journey", "nps", "cs", "aop",
              "retention_fm", "order_movement"]


def build_context(as_of=None, price_threshold: float = 0.05) -> tuple[dict, dict]:
    """Load all sources and compute the shared context.

    Returns (ctx, models):
      ctx     — precomputed aggregates, safe to pass to conclusions.executive_*(),
                conclusions.insight_bundle() and the per-page conclusion functions.
      models  — the raw model dicts keyed by source name (None when unavailable).
    """
    as_of = as_of or pd.Timestamp.now().date()
    models = {k: None for k in MODEL_KEYS}
    for k in MODEL_KEYS:
        try:
            m, rep, meta = sources.get_model(k)
            models[k] = m
        except Exception:
            models[k] = None

    ctx: dict = {"as_of": as_of, "price_threshold": price_threshold}

    # --- sales / revenue -------------------------------------------------
    sales = models["sales"]
    if sales is not None:
        sdf = sales["df"]
        months = sorted(sdf["month"].unique())
        ctx["sales_months"] = months
        if months:
            last = sales_kpis(sales_filter(sdf, months=[months[-1]]))
            prev = sales_kpis(sales_filter(sdf, months=[months[-2]])) if len(months) > 1 else None
            ctx["sales_kpis"], ctx["sales_prev_kpis"] = last, prev
            ctx["cat_contrib"] = category_contribution(sdf)
            ctx["chan_contrib"] = channel_contribution(sdf)
            try:
                from calculations import variant_contribution
                ctx["var_contrib"] = variant_contribution(sdf)
            except Exception:
                ctx["var_contrib"] = None

    # --- customer journey: migration + V2V/V2C + computed retention ------
    journey = models["journey"]
    if journey is not None:
        try:
            ctx["mig"] = migration_analysis(journey, "category")
        except Exception:
            ctx["mig"] = None
        try:
            ctx["vv"] = v2v_v2c_analysis(journey)
        except Exception:
            ctx["vv"] = None
        try:
            from calculations import journey_retention
            ctx["jr"] = journey_retention(journey, "category", as_of=as_of)
        except Exception:
            ctx["jr"] = None
        try:
            o = journey["orders"]
            if "channel" in o.columns:
                ctx["journey_channels"] = sorted({str(c).upper().strip() for c in o["channel"].dropna().unique()})
        except Exception:
            pass

    # --- nps / cs ---------------------------------------------------------
    nps = models["nps"]
    if nps is not None:
        nd = nps["df"]
        ctx["brand_nps"] = nps_score_stats(nd["brand_score"])
        ctx["product_nps"] = nps_score_stats(nd["product_score"])
        ctx["nps_model"] = nps
    cs = models["cs"]
    if cs is not None:
        ctx["cs_kpis"] = cs_kpis({"df": cs["df"]})
        ctx["cs_df"] = cs["df"]

    # --- aop (plan) --------------------------------------------------------
    aop = models["aop"]
    if aop is not None:
        try:
            am = aop_monthly(aop)
            ctx["aop_monthly"] = am
            ctx["aop_roas"] = am.dropna(subset=["revenue"])
        except Exception:
            pass

    # --- retention FM ------------------------------------------------------
    fm = models["retention_fm"]
    if fm is not None:
        try:
            vals, mat = fm_retention_table(fm["df"], fm["windows"], as_of)
            ctx["fm"] = {"vals": vals, "mature": mat, "df": fm["df"],
                         "windows": fm["windows"], "price": fm.get("price")}
        except Exception:
            pass

    # --- new-to-category ----------------------------------------------------
    ntc = models["order_movement"]
    if ntc is not None:
        ctx["ntc"] = {"df": ntc["df"], "as_of": ntc["as_of"], "maturity_days": 90}

    # --- price: detected from sales (Source B) ------------------------------
    if sales is not None:
        try:
            det = derived_price_changes(sales["df"], threshold=price_threshold)
            ctx["price_detected"] = det
            ctx["price_flags"] = price_flags(det, threshold=price_threshold)
        except Exception:
            ctx["price_detected"] = pd.DataFrame()
            ctx["price_flags"] = None

    return ctx, models
