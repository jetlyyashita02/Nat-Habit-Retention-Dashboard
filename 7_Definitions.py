"""Page 7 — Definitions & Methodology: every metric's formula, denominator and
data requirement, so different users read the dashboard the same way."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st

from formatting import init_page

init_page("Definitions & Methodology", "📖",
          "Formulas, denominators, data requirements and known limitations — one page, no ambiguity.")

st.markdown("""
## Core concepts

| Term | Definition in this dashboard |
|---|---|
| **Customer** | A unique `customer id` wherever the source provides one. Aggregate files (e.g. the sales CSV) carry *customer counts* per row; these are "touch counts" and cannot be de-duplicated across rows/categories/channels. |
| **Order** | One transaction identified by `order id`. If a file has no order id, each row is treated as one order (flagged in the validation panel). |
| **Order line** | A row within an order (multi-item orders have several lines). Migration & retention use the **primary line** per order = the line with the largest quantity. This prevents inflating migration through many-to-many combinations of items in one order. |
| **Variant** | The `product`/`short code` level (e.g. "Flax Carrot (Hot Humid) 35+ Face Malai - 30g"). |
| **SKU** | The `sku` code (e.g. `FC-HHDM-FC-030`). |
| **Category** | Normalized `category` value (trimmed, case-insensitive); blank categories are bucketed as "(Uncategorized)" and reported, never silently dropped. |

## V2V and V2C (computed from journey data)

Both use the **same denominator**: customers with a qualifying (observed) second order.

```
V2V % = customers whose 2nd order is the SAME VARIANT as their 1st order
        / customers with an observed 2nd order

V2C % = customers whose 2nd order stays in the SAME CATEGORY (any variant)
        / customers with an observed 2nd order
```

They are **separate metrics** and are never computed with the same formula.
By construction **V2C ≥ V2V**. If a source cannot distinguish variant from category
(no variant field), variant-level V2V is disabled and stated explicitly — it is not fabricated.

## Retention

**Metabase table (Retention FM sheet).** Rows are acquired SKUs (or categories, aggregated
customer-weighted). Columns are 15/30/60/90/120/180/240/300/360-day windows.
**Denominator = the sheet's `Customer` column** (customers acquired in that row's cohort).
The sheet stores %-numbers (e.g. `0.54` = 0.54%); the dashboard displays them as `0.54%`.

**Computed retention (journey data).** For each customer:
1. first (primary-line) order defines the acquisition cohort (month × entity);
2. **denominator** = customers acquired in the cohort;
3. retained @ W days = the customer made *any* further primary-line order within W days of the first;
4. % = retained ÷ acquired.

**Cohort maturity.** A cohort × window cell is *mature* only when
`cohort start + W ≤ as-of date`. Immature cells are displayed as **"Not mature"** —
never converted to 0% — so immature cohorts are never compared as if they underperformed.
The as-of date is a sidebar control (default: today).

## Migration

* Entry entity = the (primary line of the) **first** order; destination = the **second** order.
* Repeat/stay % = customers whose 2nd order is in the same entity ÷ **customers acquired** (entry).
* Switch % = customers whose 2nd order is in a different entity ÷ customers acquired.
* **Net migration (per category)** = customers gained (1st order elsewhere → 2nd order here)
  − customers lost (1st order here → 2nd order elsewhere). Only customers with an observed 2nd order are included.
* Average days 1→2 = mean gap between first and second order dates (primary lines).

## NPS

```
NPS = % Promoters (score 9-10) − % Detractors (score 0-6)
```
computed on raw 0-10 responses (Brand and Product separately). It is **not** the average score.
Likes/dislikes are split on `|` / `;` delimiters and each individual selection is counted once
(the full string is never counted as one response). "Brand Customer Migrated From" values
containing "first" are treated as first-time customers and shown separately from competitors.

## CS

* Resolved % = tickets whose status is Resolved/Closed/Solved ÷ all tickets.
* Fulfilment time = `delivery_time − fulfilled_time` (hours); median and % > 72h are reported
  only over tickets where both timestamps are valid.
* Responsible-team analysis is shown **only if the field is populated**; otherwise the dashboard
  states "Responsible team is not available in this export."

## Revenue, AOP, ROAS, AOV

```
Revenue Share (category) = category revenue / total filtered revenue
AOV = revenue / orders
ROAS = revenue / spend
Revenue / customer = revenue / customer touch counts
```

**AOP vs actuals.** The AOP sheet is the *plan* (booked actuals for past months + future plan).
It is displayed in its own section, labelled **AOP / Plan**, and is never summed with or mixed
into actual sales. The "actual ↔ plan split" control marks the boundary month.

* **Monthly aggregates** use the channel **TOTAL** rows, and — when no category filter is
  active — exclude category rows whose label starts with "total" (grand-total rows such as
  "Total Gel Moisturizers") so the aggregate is not double-counted. Selecting a category filter
  always uses that category's rows only.
* **FY table:** in some exports only the first FY block carries category/channel labels; later
  FY blocks are unlabeled placeholders and are then reported as a data warning, not filled in.
* **Quarterly/summary columns** in the AOP grid (e.g. "Q2 2025") are kept in the long model but
  excluded from the monthly chart/table.

## Price changes

* **Source A (explicit):** parsed from price-revision notes in the Retention FM sheet
  (e.g. "Decreased-Price Revision - 2nd February, 2026" → type Decreased, date 2026-02-02;
  "New 50g Variant Launch" → type New Variant).
* **Source B (detected):** realized unit price per SKU-month = `revenue ÷ quantity` (quantity > 0).
  MoM change = (current − previous) / previous. |change| ≥ threshold (default 5%, configurable)
  is flagged. Realized price includes discounts/promos — it is **not** necessarily list/MRP.
* **Price × retention** cross-checks are observational and worded as *potential relationships
  requiring validation* — the dashboard does not claim causation.

## New-to-category order movement

* The source is cohort-level: first order, 2nd–6th order counts, % and average days.
* Percentages are **recomputed from the order counts** when counts are present (more robust
  than the mixed `%` / bare-number formats found in exports); mismatches > 2pp are reported.
* A cohort is **mature** when `as-of − cohort start ≥ maturity window` (default 90 days).
  KPI averages are weighted by first-order volume over mature cohorts only; immature cohorts
  are flagged and their low repeat rates are not interpreted as churn.
* The as-of date is taken from the file's export timestamp when present.

## Data handling & validation

* Every uploader reports: rows, date range, entity counts, and warnings
  (missing columns, unparseable dates, empty fields, duplicates, multi-line orders…).
* Missing *optional* columns degrade the affected views only — the rest of the page still works.
* Missing *required* columns disable the affected analysis with a clear explanation.
* Nothing is hardcoded: categories, SKUs, channels, months, thresholds and conclusions all
  come from the uploaded data.

## What this dashboard CANNOT compute from the current sources

| Metric | Why |
|---|---|
| Exact revenue per customer / true unique-customer revenue | aggregate sales CSV has no customer id |
| Migration *reasons* | sources record where customers move, not why |
| V2V/V2C from the Retention FM sheet alone | the sheet has no per-customer order sequence (journey data required) |
| Profitability / margin | no cost data in any source |
| NPS causal drivers | survey themes are associations, not validated root causes |
""")
