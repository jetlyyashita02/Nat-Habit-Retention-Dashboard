# Retention & Category Intelligence — Multi-Page Streamlit Dashboard

A reusable, upload-driven Streamlit app for monthly retention, category migration,
sales/revenue, NPS & customer-success, price-change, and new-to-category analysis.

**Transparency note:** no pre-existing dashboard was uploaded for this build — this is a
clean implementation of the specification, validated against the real source exports in
`uploads/`. All eight sources now load **real data**. The journey base sheet's scope, as
stated by its own title, is **D2C channel, Moisturisers categories, all users, first 6 orders
per customer, Jan 2024 – Jun 2026** — customer-level metrics reflect that scope and say so in
the UI.

---

## 1. Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

Open http://localhost:8501. The app is a multi-page Streamlit layout:

| Page | Content |
|---|---|
| `app.py` | Executive Overview (KPI cards, attention items, data-status table) |
| `pages/1_Migration.py` | Category / variant / SKU migration, net migration |
| `pages/2_Sales_Revenue.py` | Sales & revenue KPIs, contribution, Pareto, matrices + **AOP / Plan** section (never combined with actuals) |
| `pages/3_NPS_CS.py` | NPS (CSV upload **or** paste-in text), themes, competitor pull, CS hierarchy + Voice of Customer |
| `pages/4_Price_Changes.py` | Explicit price revisions + **detected** changes from realized-price MoM (configurable ± threshold) |
| `pages/5_Retention_V2V_V2C.py` | Retention FM (15–360 day windows) + V2V / V2C from journey data, cohort maturity → `N/A` |
| `pages/6_New_to_Category.py` | 2nd–6th order movement, curves, heatmap, maturity flags |
| `pages/7_Definitions.py` | Full metric definitions & methodology (the authoritative source) |
| `pages/8_Insights.py` | **Insights & Conclusions** — one page tying everything up: cross-page synthesis, cross-source connections, what changed / what needs attention, per-page conclusions |

### 1b. The final multi-page interactive dashboard (the GitHub deliverable)

The **ten separate, openable pages** at the repo root are the final deliverable — a real
multi-page site, not tabs. Each page is a self-contained HTML file (zero external
references, works offline and on GitHub Pages) that renders its charts, tables and
insights **client-side from an embedded data blob**, so everything is genuinely
interactive:

* **hover tooltips** with a crosshair on every chart (trend, bars, heatmaps)
* **click-to-drill** — bars, heat rows and cells set filters/highlights
* **sortable columns + live search** on every table
* **cross-filters** — e.g. click an NPS-by-category bar → the Voice-of-Customer panel
  re-filters to that category; click a top price mover → the Source-B table filters to
  that SKU
* **⚡ Deep cuts** on every page — auto-detected conclusions from the current CSVs
  (nothing handwritten), each linking to the page behind it

| Page | What it does |
|---|---|
| `index.html` | Executive overview: revenue vs AOP trend (plan dashed, actual bars — never combined), linked KPIs, attention items |
| `migration.html` | Net migration by category (gained/lost), sortable V2V/V2C table, searchable intra-category movement |
| `sales.html` | Category/channel contribution, Pareto ↔ Category×Month matrix cross-highlight, AOP/Plan KPIs |
| `nps-cs.html` | Score distributions, NPS by category → Voice-of-Customer cross-filter + search, competitor pull, CS failure table |
| `pricing.html` | Explicit revisions (Source A) + detected realized-price changes (Source B, ±threshold), top-mover cross-filter |
| `retention.html` | FM window table (immature = N/A, never 0%), V2V/V2C by category, journey-retention bars, CTA to the deep-dive |
| `ntc.html` | 2nd–6th order movement curve + cohort×order heatmap |
| `definitions.html` | Searchable formulas & definitions + what the sources cannot compute |
| `insights.html` | Top conclusions + per-section insight cards + full per-page detail |
| `journey.html` | The retention deep-dive (152,091 customers · 193,756 orders embedded; live filters, seasonality, geography, Journey explorer) |

```bash
python make_web_dashboard.py       # regenerate all pages + self-verify (one command)
node tests/web_harness.js          # headless interactivity + live-recompute test: 113 checks, no browser
```

`make_web_dashboard.py` reuses the same context/conclusions pipeline as the app and the
other dashboards, and re-runs `make_retention_dashboard.py` for `journey.html` only when
it is stale. It self-verifies before writing: tag balance, zero external references, all
10 nav links on every page, exactly one active link, kit functions present, and the
embedded AOP series matching the computed one with max-diff 0.0. Next month: upload the
7 new CSVs (or drop them in `data/`), re-run the command, commit. GitHub Pages: push →
Settings → Pages → deploy from `main` — `index.html` is the home page.

Also kept: `single-page.html` — the legacy single-file 9-tab version
(`python make_static_dashboard.py`), in case the one-document form is preferred.

### 1c. The retention deep-dive (`journey.html`)

A second self-contained dashboard, in the spirit of the Seasonality & Migration reference
dashboard: the **full per-customer journey embedded** (152,091 customers · 193,756 orders)
with live client-side recomputation — clickable filters (category / variant / entry size /
entry month range / journey depth / region / city search / repeaters) that **every chart,
bar, tile, heat row and table row sets for you**, auto-detected deep-cut insights (each with
its own "apply" filter), retention curves with the cohort-maturity N/A rule, repurchase-gap
distribution, V2V/V2C loyalty (31.8% / 69.1% — identical to the app's journey figures),
seasonality (intended line vs calendar timing), geography × season heatmaps with affinity
index, switching behaviour (top transitions + size flows), a sortable variant summary, and a
paginated Journey explorer with CSV export of the filtered cohort.

```bash
python make_retention_dashboard.py    # regenerate journey.html + self-verify
node tests/retention_harness.js       # headless DOM test (needs node, no browser)
```

Same discipline as everything else: nothing business-specific is hardcoded (city→region is a
documented classification, seasons/SKU-line decoder is documented methodology), and every
number recomputes in-browser from the embedded per-customer data. Because the source sheet's
SKU code column disagrees with the product name in ~13% of rows, all metrics are **keyed on
the product name**; the code is only the fallback source for intended line/size (documented
in the footer). Next month: drop the new base sheet in `data/` (or `uploads/`) and re-run.

### 1d. Live data — analyse your own CSV combinations in the browser (no regeneration)

Every page — including `journey.html` — has a **"📂 Live data"** panel near the top. Drop in
any version of that page's source (a new month's export, a different category scope, your own
extract) and the page **re-computes and re-renders its analysis client-side, in your browser**,
with exactly the same rules as the bundled pipeline:

* **Same metrics, same formulas** — the in-browser engine is a line-for-line port of
  `etl.py`/`calculations.py`: NPS = %promoters − %detractors, V2V/V2C on the primary line per
  order (largest quantity, first row on ties), AOP parsed as a wide multi-block grid and kept
  separate from actuals, FM cohort maturity → **N/A, never 0%**, NTC curve/heatmap with the
  90-day maturity rule, price movers = realized unit price MoM beyond ±5%.
* **Robust header detection** — leading junk/timestamp lines are skipped, header names are
  matched by alias (case, spaces, hyphens: `rev`/`revenue`, `qty`/`quantity`,
  `order_source`/`channel`, …). Missing optional columns degrade gracefully with warnings;
  a file that doesn't match the page's schema at all gets a **generic structural profile**
  (column stats + preview) instead of an error — nothing ever crashes.
* **Combinations** — the NPS+CS page accepts both files (and pasted NPS text) at once; the
  insights page accepts **all nine sources at once** and shows a "Live analysis of your
  uploads" card with every page's live deep cuts; the pricing page takes Sales + Retention FM
  together (Source A + Source B).
* **Reset** — "↺ Reset to bundled data" restores the embedded numbers instantly.
* **Privacy** — parsing and computation happen entirely in your browser (FileReader → JS);
  nothing is uploaded anywhere, and the page still works fully offline.

Verified: `node tests/web_harness.js` [11] feeds each page's **real sample CSVs through the
in-browser engine** and asserts the results equal the embedded (Python-pipeline) values —
sales KPIs/Pareto/matrix, AOP series, NPS score/distribution/VoC, CS table, FM windows +
lookup, NTC curve/heatmap, price movers — plus a customer-level journey fixture
(`tests/fixtures/journey_long.csv`) checked against an independent Python recomputation
(V2V/V2C, net migration, same-category 90-day retention), and a full panel end-to-end
(handle → banner → re-render → reset).

## 2. Where to upload

Every page has its own uploader at the top. Uploading a file **replaces that page's data and
recalculates everything** — no code edits. In the multi-page site the panel works two ways:
the **📂 Live data panel recomputes in your browser immediately** (section 1d), and
`python make_web_dashboard.py` bakes fresh uploads into new pages for GitHub. Priority per
source: **pasted text (NPS) > upload > sample file**. `data/sample_*.csv` are used only until
you upload real files; Sales and Journey samples are synthetic and labelled *DEMO*.

Expected columns (the parser matches header names flexibly — case, spaces, hyphens and the
aliases in brackets are all accepted):

| Source | Required | Also used (optional) |
|---|---|---|
| **Sales** | `order_date`/`date`, `category`, `revenue`/`rev` | `sku`, `product`/`short_code`/`variant`, `channel`/`order_source`, `orders`, `customers`, `qty`/`quantity` |
| **Category-scoped sales** (Page 1) | `order_date`, `category`, `revenue`/`rev` | same as Sales — single-category slice, e.g. Moisturisers |
| **Customer Journey** | long: `customer_id`, `order_date`, `category` — or wide base sheet: `Name` + `first/second/.../sixth order date` + `...purchased sku/short code` | long: `order_id`, `sku`, `product`/`variant`, `channel`, `quantity`; wide: multi-line orders comma-separated in the order cells, `days_between_*`, `Journey Depth`, `city`, `Month-Year` |
| **NPS** | `NPS Score For Brand`, `NPS Score For Product` | `created_at`, `customer_id`, `product_category`, `product_variant`, `age`, `skin_type`, `hair_type`, `Brand Customer Migrated From`, `What do you like…`, `What do you not like…`, `Like Product`, `Not like Product` |
| **CS feedback** | `created_at` | `chat_status`, `failure_type`, `failure_reason`, `failure_subreason`, `products_impacted`, `Product impacted category`, `responsible_team`, `remarks`, `global_remark`, `fulfilled_time`, `delivery_time`, `city`, `state` |
| **Retention FM** | `product onb date`, `sku`, `Customer` (cohort size) | `product_category`, `Lookup Price thing` (price-revision notes), `short_code`, `channel`, `<N> Days %` window columns (15–360) |
| **AOP** | wide multi-block grid with an `SD Category` column (block label row above it) | month columns `Jan'24…`, blocks: revenue, spend, shares, ROAS, growth, FY summary |
| **New-to-Category** | `onb_month`, `first_order` (new customers) | `sec_order`…`sixth_order`, `sec_pct`…`sixth_pct`, `avg_days_to_sec`… |
| **Summary sheet (migration/seasonality)** | — (parsed as a wide summary; blocks detected by label) | V2V/V2C, seasonality, order-frequency, grammage, conclusions blocks |

Uploaders **validate and warn** (missing columns, malformed dates, zero revenue/quantity,
duplicate rows, out-of-range NPS scores, empty responsible-team, multi-line orders) and
continue with whatever analysis is possible — they never crash the page and never fail
silently. Every major table has a **Download CSV** button.

## 3. Metric definitions (authoritative: page 7)

Key formulas, abbreviated:

* **NPS** = %promoters (9–10) − %detractors (0–6), computed per question (brand & product),
  standard method. Likes/dislikes are split on `|`, `;`, `,`, `/`, `&`, newlines;
  "no complaint"-style remarks are excluded from dislike themes.
* **V2V %** = customers whose 2nd order is the **same variant** as their 1st order, divided
  by customers with a qualifying 2nd order.
* **V2C %** = customers whose 2nd order stays in the **same category** (any variant), divided
  by the **same denominator**. Separate formulas — V2C ≥ V2V by construction. If the source
  cannot distinguish variant from category, V2V is disabled and stated, not fabricated.
* **Retention (FM sheet)** = window column ÷ 100 (stored as fractions internally, displayed
  like `30.4%`); denominator is the cohort's `Customer` count. Windows where
  `window > as_of − onb_date` are **not mature** and shown as **N/A** (never 0%).
* **Retention (journey)** = customers with a qualifying 2nd purchase within N days of their
  first purchase / acquired customers in the cohort; same maturity rule.
* **Price changes — Source A (explicit):** parsed from Retention FM `Lookup Price thing`
  notes (`Decreased/Increased/Same – Price Revision – <date>`, `New … Variant Launch`).
* **Price changes — Source B (detected):** realized unit price = revenue ÷ quantity per
  SKU-month (months with zero quantity are excluded, never priced as 0); flag when
  MoM change exceeds the configurable threshold (default ±5%). Labelled **detected signal
  from realized prices — not list/MRP**.
* **Migration** uses a **primary line per order** (largest quantity; first line on ties) so
  multi-item orders never inflate migration via many-to-many joins.
  Net migration per entity = customers gained − customers lost.
* **Intra-category movement** (Page 1, from the category-scoped sales export): revenue share
  of each SKU and grammage in the 1st vs 2nd half of the observed window (delta in
  percentage points), plus entered/exited SKUs. This export has **no customer ids**, so it is
  SKU/grammage-level revenue-share movement — a complement to, not a substitute for,
  customer-level migration. Grammage = size encoded in the SKU code (e.g. `-250`) plus the
  unit from the product name where present; unlabelled sizes merge with their unit when
  unambiguous.
* **AOP** is parsed as a **wide multi-block grid** (never a flat CSV), reshaped to long form.
  AOP figures are the *plan* (booked actuals + future plan) and are displayed in their own
  **AOP / Plan** section — never summed with actual sales. Monthly aggregates use channel
  TOTAL rows and, without a category filter, exclude grand-total category rows (labels
  starting with "total") to avoid double counting.
* **New-to-category** percentages are recomputed from counts when the sheet's pct columns are
  inconsistent; cohorts younger than the observation window are flagged **not mature**.
* **CS fulfilment time** = `delivery_time − fulfilled_time` (hours); median and % > 72h
  reported. If `responsible_team` is empty, the UI states it is unavailable in the export.
* Causality language is always qualified: price/retention overlaps are described as a
  *"potential relationship requiring further validation"*, never as cause-and-effect.

## 4. Files

```
app.py                      Executive Overview (KPIs, attention items, data status)
context.py                  Shared ctx builder — ONE place computing the context for the
                            overview, the Insights page and the static export (same numbers)
index.html                  ★ Multi-page site — Executive overview page (interactive:
                            AOP trend w/ crosshair, linked KPIs, attention) — generated
migration.html              ★ Site page 1 — net migration, V2V/V2C table, intra-category
sales.html                  ★ Site page 2 — contribution, Pareto↔matrix cross-highlight, AOP
nps-cs.html                 ★ Site page 3 — NPS distributions, dim→VoC cross-filter + search, CS
pricing.html                ★ Site page 4 — explicit + detected price changes, mover cross-filter
retention.html              ★ Site page 5 — FM windows (N/A rule), V2V/V2C, CTA to deep-dive
ntc.html                    ★ Site page 6 — order-movement curve + cohort×order heatmap
definitions.html            ★ Site page 7 — searchable definitions + "cannot compute" list
insights.html               ★ Site page 8 — top conclusions + per-section insight cards
journey.html                ★ Site page (deep-dive) — full per-customer journey embedded,
                            live filters, seasonality, geography, Journey explorer
make_web_dashboard.py       Regenerates the whole site (one command) + self-verifies every page;
                            inlines the live-data kit (panel UI + in-browser CSV engine)
single-page.html            Legacy single-file 9-tab dashboard (same data) — generated
make_static_dashboard.py    Regenerates single-page.html from the data models + self-verifies it
journey.html                Retention deep-dive dashboard (per-customer journey embedded,
                            live filters/charts/insights/explorer, self-contained) — generated
make_retention_dashboard.py Regenerates journey.html + self-verifies (verify + node harness)
pages/1_Migration.py        Migration analysis
pages/2_Sales_Revenue.py    Sales & Revenue + AOP/Plan
pages/3_NPS_CS.py           NPS & Customer Success
pages/4_Price_Changes.py    Price changes (explicit + detected)
pages/5_Retention_V2V_V2C.py Retention FM + V2V/V2C
pages/6_New_to_Category.py  New-to-category order movement
pages/7_Definitions.py      Definitions & methodology
pages/8_Insights.py         Insights & Conclusions (cross-page synthesis)
sources.py                  CSV loading, header detection, column aliasing, uploads, caching
etl.py                      Per-source normalization -> analytical models (validation included)
calculations.py             All metric computations (NPS, V2V/V2C, retention, price, AOP, NTC, CS)
conclusions.py              Data-driven attention items / conclusions (no hardcoded results)
formatting.py               Parsers (dates/%/money), formatters (30.4% style, ₹ Cr/L), CSV downloads
data/sample_*.csv           Sample files, all real exports: sales = all-category (25 Jul – 23 Aug
                            2026), sample_sales_moisturisers.csv = category-scoped slice,
                            sample_journey_d2c.csv = customer base sheet (D2C, Moisturisers,
                            Jan 2024 – Jun 2026, first 6 orders)
generate_samples.py         Legacy sample generator (pre-dates the real exports)
tests/test_all.py           Validation suite (205 checks, 20 sections, incl. retention + web site
                            + live-mode fixture recompute)
tests/fixtures/               journey_long.csv + journey_expect.json — customer-level fixture
                            cross-checking the in-browser journey engine vs Python
tests/app_test_all.py       Headless AppTest run for all 9 pages
tests/retention_harness.js  Headless node DOM harness for journey.html
tests/web_harness.js        Headless interactivity harness for the multi-page site + journey
                            (113 checks: [1]–[10] interactivity, [11] live recompute vs embedded,
                            [12] journey live card)
uploads/                    The six real source exports (read-only inputs)
requirements.txt            Dependencies
```

**Created for this build:** all of the above (the workspace started with only `uploads/`).

## 5. Assumptions

1. Sales file rows are already at SKU × channel × month grain; if a finer grain is uploaded
   the app aggregates (sums) it.
2. A customer's "first order" is the earliest dated order in the Journey file (ties → first
   row). Cohorts are onb-month cohorts as labelled in the sources.
3. Journey multi-line orders: one line is primary (largest quantity); the order is counted
   once (deduplicated) and multi-line orders are warned about.
4. Retention FM window columns are percentages in the sheet (e.g. `10.8` = 10.8%) — verified
   against the sheet header `<N> Days %`.
5. AOP month labels are normalized to `YYYY-MM`; the "actual ↔ plan" split month is a user
   control (default: latest month present in the sales data).
6. NPS pasted text is CSV (comma or semicolon separated, with or without a header row).
7. Sales samples are the real exports: all-category (25 Jul – 23 Aug 2026) and the
   Moisturisers slice; they are an exact subset relation (verified by test). The Sales window
   is a 30-day MTD span crossing July/August, so "latest month" KPIs are partial months.
8. The journey base sheet is **wide** (one row per customer, up to six orders per row). It is
   reshaped to order-line grain: multi-line orders are the comma-separated values in each
   order cell; the per-order **primary line** is the first line (the sheet carries no
   quantities), used for migration/retention so multi-line orders never inflate switches.
   Line categories are inferred by matching each product name against the order's own category
   list (literal containment, then token overlap) — no category names are hardcoded; lines
   that cannot be inferred are bucketed (Uncategorized) and counted in a warning.
   `days_between_*` and `Journey Depth` are cross-checked against the dates (dates win;
   mismatches are warned). The sheet carries no channel column; the channel label is taken
   from the export title (D2C).
9. Customer-level metrics (migration, V2V/V2C, journey retention) are therefore scoped to
   **D2C × Moisturisers × first 6 orders**. Deeper journeys, other channels, and other
   categories are not in this export.
10. The summary sheet's grammage-transition block could not be exactly reproduced from the
    base sheet (its entry-cohort definition is undocumented); both views agree on direction.
    The base-sheet-derived figures are computed fresh and labelled as such.
11. Percentages are stored as fractions internally and formatted for display (`30.4%`);
    money uses ₹ with L/Cr abbreviations.

## 6. Metrics the current sources CANNOT support (not fabricated)

| Metric | Why |
|---|---|
| V2V/V2C from the Retention FM sheet alone | no per-customer order sequence — journey data required |
| True MRP / list-price history | exports contain realized prices & revision notes only — detected changes are signals, not list prices |
| Attribution of NPS/CS outcomes to specific price changes | cross-source join keys insufficient — flagged as "potential relationship requiring further validation" |
| Responsible-team workload | `responsible_team` is empty in this export — stated in UI, not invented |
| V2V/V2C block of the Summary sheet | the V2V/V2C sheet in that export is empty — a data warning is shown |
| Channel-level AOP for FYs after FY 2024-25 in this export | later FY blocks carry no category/channel labels — warned, excluded |
| Same-day/real-time metrics | sources are EOM/period exports |
| Customer LTV | requires revenue per order in journey data, which the provided journey export does not carry |
| Customer-level migration / V2V / V2C from the sales exports | the two query exports are aggregated (date × sku × channel) with no customer/order ids — customer-level metrics use the journey base sheet instead; the Moisturisers slice is used for SKU/grammage-level intra-category movement |
| Customer-level metrics beyond D2C × Moisturisers × first 6 orders | the journey base sheet's stated scope — later orders, other channels and categories are not in the export |

## 7. Tests

```bash
python tests/test_all.py        # 191 checks: normalization, edge cases, exact metric values,
                                # all 8 sources end-to-end, real-export invariants (incl. the
                                # base sheet's own repeat-buyer / day-gap / depth columns),
                                # insights engine, static-dashboard integrity, retention
                                # dashboard (counts, V2V/V2C anchors, zero external refs),
                                # and the multi-page web site (self-verify + 68-check
                                # embedded headless node harness)
python tests/app_test_all.py    # headless AppTest run — all 9 Streamlit pages
node tests/retention_harness.js # headless DOM test of journey.html
```

Covers: date/percent/money parsing; blank categories; duplicate rows; zero quantity;
negative revenue; malformed dates; V2V ≠ V2C denominators; cohort maturity (N/A, not 0%);
NPS math on known values; theme splitting; paste-in parsing; out-of-range scores; CS
fulfilment; empty responsible-team warning; Retention FM % → fraction conversion; price-note
parsing; price detection threshold behaviour; new-to-category pct recomputation; AOP wide
block parsing (exact month-span and value checks); grand-total double-count guard;
non-causal conclusion wording; all-sample end-to-end smoke test; **insight bundle**
(sections, item well-formedness, no-invention on empty ctx, cross-link detection,
non-causal wording); **static dashboard** (9 tabs, zero external references, balanced tags,
AOP series max-diff 0.0, interactive pieces present); **retention dashboard** (model counts
152,091/193,756/24,771, product-keyed prods table, embedded V2V 31.79% / V2C 69.11% recomputed
independently from the embedded arrays, 31-month span, and the full 40-check headless node
harness for render + filter behaviour).
