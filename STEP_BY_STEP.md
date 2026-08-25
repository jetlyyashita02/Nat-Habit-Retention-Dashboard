# 🪜 Step-by-Step: Get Your Dashboard Live on GitHub Pages

Goal: a shareable link like `https://YOUR-USERNAME.github.io/moisturisers-dashboard/`
that opens your interactive Moisturisers dashboard in any browser — same style as
`nokitkit-tt.github.io/nathabit-bodywash-report/`.

Time needed: ~10 minutes. Everything is free.

---

## STEP 1 — Create a GitHub account (2 min, one-time)

1. Go to **https://github.com/signup**
2. Enter email → password → username (this becomes part of your link, e.g. `nokitkit`)
3. Verify your email when GitHub sends it.

## STEP 2 — Download your dashboard files

1. In this workspace, download **`Moisturisers_Dashboard_GitHub_Repo.zip`**
2. **Unzip it** on your computer. You get a folder called `moisturiser_dashboard`
   containing: `docs/` (the dashboard page), `app.py`, `README.md`, etc.

> ⚠️ Important: for the website to work, the folder **`docs`** must end up at the
> top level of your GitHub repo (not nested inside another folder).

## STEP 3 — Create an empty repository on GitHub

1. Click the **+** (top-right) → **New repository**
2. Repository name: `moisturisers-dashboard`
3. Visibility: **Public** (required for free GitHub Pages — your real customer data
   is never in these files, only the small anonymised sample)
4. Do **NOT** tick "Add a README file"
5. Click **Create repository**

## STEP 4 — Upload the files (no coding, drag & drop)

1. On the page that opens ("…or push an existing repository"), click the link
   **"uploading an existing file"**
2. Open your unzipped `moisturiser_dashboard` folder, press **Ctrl+A** (select all
   files & folders inside it), then **drag them all** into the GitHub upload area
3. Wait for the upload to finish → type a name like `initial dashboard` → click
   **Commit changes**

*(Alternative for git users: `git init && git add . && git commit -m "dashboard" &&
git branch -M main && git remote add origin https://github.com/YOUR-USERNAME/moisturisers-dashboard.git && git push -u origin main`)*

## STEP 5 — Turn on GitHub Pages (this creates your link)

1. In your repo, click **Settings** (top tab)
2. Left sidebar → **Pages**
3. Under "Build and deployment":
   - Source: **Deploy from a branch**
   - Branch: **main** — Folder: **/ docs** ← must be `docs`, not root!
   - Click **Save**
4. Wait 1–2 minutes, refresh the Pages screen until it shows:
   🟢 **"Your site is live at https://YOUR-USERNAME.github.io/moisturisers-dashboard/"**

That green link is your dashboard — open it, bookmark it, share it.

## STEP 6 — Use the dashboard

1. **Open your link** — the dashboard loads instantly with the bundled sample
   (655 customers) so you can play with it right away.
2. Use the **6 dropdown filters** (Category, Variant SKU, From/To month, Journey
   depth, Geo region) — every tile, the conclusions, tables and the chart update
   instantly.
3. **Load your real 155k dump:** click **📂 Load your CSV** (top-right) → choose
   your raw CSV → it parses **inside your browser only** (nothing is uploaded to
   GitHub or anywhere else — completely private). The whole dashboard rebuilds on
   your real data in a few seconds.
4. Search journeys in the **JOURNEYS** table, page through, and **⬇ Export
   filtered CSV** to hand the slice to anyone.
5. Read the auto-written answers under **FORMULA-DRIVEN CONCLUSIONS** — they
   re-write themselves for every filter combination.

## STEP 7 — Updating later

- **New data month?** Nothing to re-upload — just open the link and load the new
  CSV with the 📂 button.
- **Want to change the bundled sample or branding?** Edit `docs/index.html` (or
  ask for changes here), then re-upload the file in your repo
  (repo → `docs` → `index.html` → ✏️ pencil → upload new file → Commit).
  Pages redeploys automatically in ~1 minute.

---

## 🔧 Troubleshooting

| Problem | Fix |
|---|---|
| Link shows **404** | Wait 2 min and refresh; check STEP 5 folder is `/docs`, branch `main` |
| Pages says "not available" | Repo is **Private** — free Pages needs Public (or GitHub Pro) |
| Upload fails on a file | Make sure you dragged the *contents* of `moisturiser_dashboard`, not the zipped file itself |
| CSV won't load | It must be the journey-format CSV (columns `first_purchased_sku`, `first_order_date`, `Name`, `city`, …). Export it fresh from your source sheet. |
| Tiles all zero after filters | You picked conflicting filters (e.g. Variant outside the Category) — click **Reset filters** |

## 📊 Which version to use when

| Version | Where | Best for |
|---|---|---|
| **GitHub Pages link** | `docs/index.html` | Sharing a live link; anyone can open it and load the real CSV privately |
| **Streamlit app** (`app.py`) | locally or Streamlit Cloud | Fullest analytics (migration heatmap, order-frequency tab, file format auto-detect) |
| **Excel workbook** (`Moisturisers_Formula_Driven_Dashboard.xlsx`) | any computer | Teammates who live in Excel — paste dump in DATA sheet, press F9 |
