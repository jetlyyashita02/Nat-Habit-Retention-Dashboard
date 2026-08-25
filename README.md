# 🧴 Nat Habit — Retention Dashboard

Interactive analytics for a raw order dump of **155k+ unique orders (Jan 2024 → Jun 2026)**:
customer journeys, variant seasonality, V2V/V2C loyalty, grammage migration and
**formula-driven business conclusions** — as an app (Streamlit) *and* as a
formula-only Excel workbook (no macros).

[![CI](https://github.com/jetlyyashita02/Nat-Habit-Moisturisers-dashboard/actions/workflows/ci.yml/badge.svg)](https://github.com/jetlyyashita02/Nat-Habit-Moisturisers-dashboard/actions)
[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://share.streamlit.io/jetlyyashita02/Nat-Habit-Moisturisers-dashboard/app.py)

---

## 🚀 Quick start (local)

```bash
git clone https://github.com/jetlyyashita02/Nat-Habit-Moisturisers-dashboard.git
cd Nat-Habit-Retention-Dashboard
pip install -r requirements.txt
streamlit run app.py
```

The app opens with a bundled 655-customer sample. Load your real dump two ways:

1. **Sidebar uploader** — drop the CSV (wide journey format *or* raw order-level export; auto-detected), or
2. **No-upload mode** — copy your file to `data/raw_dump.csv`; it loads automatically on next start (recommended for the full 155k file).

> The Excel workbook (`Moisturisers_Formula_Driven_Dashboard.xlsx`) needs no Python at all:
> open it, paste your dump over the **DATA** sheet, press **F9** — every tile, table and
> conclusion sentence recomputes. Rebuild it anytime with `python build_excel.py`.

## 🭹 How to use the app

| Tab | What you do there |
|---|---|
| **📊 Dashboard** | Set filters in the sidebar (Category, Variant SKU, From/To month, Journey depth, Geo region) → seasonality tiles, gel counts, totals and V2V/V2C loyalty tiles update instantly |
| **🏁 Conclusions** | The six business conclusion blocks, computed live from the current data — numbers *and* verdict words (YES/NO · STRONG/MODERATE/WEAK · DOWNSIZE ALERT · FOCUS) |
| **🧾 Interactive Table** | Searchable, paginated customer journeys (wide view) or order-items (long view) + CSV download |
| **🧴 Variant Summary** | Per-variant seasonality (purchase-month buckets, peak, match, strength) + order frequency & retention |
| **🔁 Migration & Grammage** | Entry SKU → 2nd-order transitions, variant-migration heatmap, upsize/lateral/downsize rollup |
| **📖 Definitions** | Every metric definition + the full SKU-code decoder |

**Filter semantics:** Category / Variant / month filters apply to each customer's
**first (entry) order** (cohort style, matching the summary workbook); Journey depth =
total orders per customer; Geo region maps city → North/West/South/East/Rest of India
(edit `REGION_MAP` in `etl.py`).

## ☁️ Host it free on Streamlit Community Cloud

1. Push this repo to GitHub (steps below).
2. Go to **[share.streamlit.io](https://share.streamlit.io)** → sign in with GitHub →
   **New app** → pick the repo → main branch → app file `app.py` → **Deploy**.
3. You get a public URL like `https://<your-app>.streamlit.app` — filters, uploader
   (up to 200 MB) and exports all work in the browser. Co-workers can drop the CSV
   straight into the sidebar — nothing installs on their machines.

## 🌐 Static version for GitHub Pages (like a shareable report link)

`docs/index.html` is a **fully self-contained HTML dashboard** — same filters,
tiles, conclusions and tables, computed entirely in the visitor's browser.
Host it exactly like a GitHub Pages report:

1. Push this repo to GitHub (below).
2. Repo → **Settings → Pages** → Source: *Deploy from a branch* → Branch: `main` → folder **`/docs`** → Save.
3. Your link goes live at `https://YOUR-USERNAME.github.io/Nat-Habit-Retention-Dashboard/`.

The page ships with the bundled sample and has a **📂 Load your CSV** button —
anyone can open the link and load the full 155k dump **locally in their browser**
(nothing is uploaded anywhere, so it stays private). GitHub Pages is free on
public repos (private repos need GitHub Pro for Pages).

## ⬆️ Put it on GitHub

```bash
# 1. create an EMPTY repo named e.g. Nat-Habit-Retention-Dashboard on github.com (do NOT add a README there)
# 2. then, from this folder:
git init
git add .
git commit -m "Moisturisers interactive dashboard (Streamlit + formula-driven Excel)"
git branch -M main
git remote add origin https://github.com/jetlyyashita02/Nat-Habit-Moisturisers-dashboard.git
git push -u origin main
```

After pushing, replace `YOUR-USERNAME` in the badges above with your GitHub username.

> 🔒 **Privacy:** keep the repo **private** if you plan to commit real customer data.
> By default `.gitignore` excludes `data/raw_dump.csv` so the full dump never leaves
> your machine — only the anonymised sample is committed.

## 📁 Repo structure

```
app.py                 Streamlit UI — filters, tiles, tables, charts, exports
etl.py                 Loaders (wide journey + raw order-level), SKU decoder, journey builder
metrics.py             Tiles, V2V/V2C loyalty, seasonality, transitions, conclusions
build_excel.py         Rebuilds the formula-driven Excel workbook
data/   Bundled samples: journey dump, sales aggregate, NPS raw, CS feedback,
        AOP plan, retention sheet, new-to-category movement
Moisturisers_Formula_Driven_Dashboard.xlsx   Paste-driven Excel version
docs/index.html        Static browser dashboard for GitHub Pages (self-contained)
tests/test_smoke.py    CI smoke test · .github/workflows/ci.yml runs it on every push
```

## 🧾 Metric definitions

- **Seasonality tiles** — orders counted by the variant's *intended* season line
  (CWDM/HDDM/HHDM/DM); **Peak Season** = largest bucket.
- **Purchase timing** — orders bucketed by calendar month: Cold Winter Dec–Feb ·
  Hot Dry Mar–May · Hot Humid Jun–Sep · Post-Monsoon Oct–Nov.
- **V2V Loyalty %** — customers with ≥2 orders whose 2nd order repeats an entry
  *variant*; **V2C** — 2nd order stays in an entry *category*.
- **Avg Purchase Days V2V/V2C** — mean days order 1 → 2 in those groups;
  **Avg Order Count** — mean total orders of those groups.
- **Seasonality Strength** — Highly ≥ 40 % of orders in peak season · Moderately
  30–40 % · Evergreen < 30 %.
- **Grammage moves** — Repeat exact SKU · Upsized (larger) · Lateral (same size,
  other category) · Downsized (smaller).
- The app analyses every item in multi-item orders (contains semantics); the Excel
  workbook uses the first SKU code of each cell (primary item) — small deltas possible.

## 🔤 SKU decoder

`FC-<LINE>-<VARIANT>-<SIZE>` — e.g. `FC-HDDM-FB-050` = Face Malai · Hot-Dry line ·
Flax Bakuchi · 50 g.

| Line | Category | Intended season |
|---|---|---|
| CWDM | Face Malai | Cold Winter (Dec–Feb) — FW Flax Walnut, TP Tomato Patchouli, BT Winter Blackseed |
| HDDM | Face Malai | Hot Dry (Mar–May) — FB Flax Bakuchi, TR Tomato Rosehip, PT Pomegranate Tulsi |
| HHDM | Face Malai | Hot Humid (Jun–Sep) — FC Flax Carrot, TV Tomato Vetiver, GAT GreenApple Tulsi |
| DM | Face Malai | Non-seasonal concern — PG Turmeric Nutmeg, NR Cocoa Mogra, DP Honey Multi-Nut, AA Clove Tea-Tree |
| AC | Active Gel | NT Neem TeaTree, AC Aloe Cactus, OV Olive Vit-E, OK Orange Kiwi, BT Beetroot Tomato |
| HG | Aloe Vera Gel | PA pure aloe — 40 g / 80 g |

## ⚡ Performance

Vectorised end-to-end; measured on a 155k-customer / 230k-row replica:
cohort filter 0.35 s · loyalty 2.7 s · all summary tables < 1 s · full journey
export ~3 s. The Excel workbook's formulas were verified cell-by-cell against this
engine via headless recalculation.

## 📄 License

MIT — see [LICENSE](LICENSE).
