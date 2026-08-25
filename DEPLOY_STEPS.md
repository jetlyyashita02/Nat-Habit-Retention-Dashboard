# 🚀 Deploy Steps — Nat Habit Retention Dashboard (final package)

You have TWO products in this download:

| Product | File(s) | Where it lives |
|---|---|---|
| **A. Public dashboard** (shareable link) | `index.html` | GitHub Pages — your existing repo |
| **B. Full analytics app** (8 pages, uploads, quarterly insights) | everything else | Streamlit Cloud (free) or your computer |

---

## A · Update your public dashboard link (2 minutes)

> Your live link: https://jetlyyashita02.github.io/Nat-Habit-Retention-Dashboard/

1. Open https://github.com/jetlyyashita02/Nat-Habit-Retention-Dashboard
2. Click **Add file** → **Upload files**
3. From this unzipped folder, drag the single file **`index.html`**
   (same name = it replaces the old one)
4. Click the green **Commit changes** button
5. Wait 1 minute → open your link → if it looks unchanged, press **Ctrl + Shift + R**

✅ Done — the public dashboard now has **6 tabs**:
- 🏠 **Overview** — filters, tiles, 12 dynamic conclusions (works on the bundled sample)
- 🔁 **Migration** — category/variant/SKU matrices, top flows, net gravity (works on the sample)
- 📄 **Quarterly Insights** — the auto-written QBR narrative for any category × quarter (works on the sample)
- 💰 **Sales & Revenue** — click 📂 and load your sales CSV (private, in-browser)
- 🗣️ **NPS & CS** — click 📂 and load your NPS + CS CSVs (private, in-browser)
- 🆕 **New-to-Category** — click 📂 and load your order-movement CSV (private, in-browser)

Note: the first three tabs work instantly with the bundled sample; the last three
activate when you load your own CSVs — nothing is uploaded anywhere.

> Do NOT upload anything else to this public repo — only `index.html` is
> public-safe. Pages setting stays: Branch `main`, folder `/ (root)`.

---

## B · Deploy the full app — pick ONE

### Option B1 · Free cloud link (recommended, no install)

1. Put ALL files from this folder into a GitHub repo:
   - GitHub → **+** → **New repository** → name `nat-habit-analytics` →
     select **Private** → **Create**
   - On the next screen click **"uploading an existing file"**
   - Open this unzipped folder, **select everything inside** (Ctrl+A) and drag it
     into the upload area → **Commit changes**
   - *(If dragging folders doesn't work in your browser, install the free
     **GitHub Desktop** app: File → Add local repository → choose this folder →
     Publish repository — it uploads folders reliably.)*
2. Go to **https://share.streamlit.io** → sign in with GitHub → **New app**
3. Pick: repo `nat-habit-analytics` · branch `main` · file **`app.py`** → **Deploy**
4. In ~2 minutes you get a private link like `https://nat-habit-analytics.streamlit.app`
   — all 8 pages work in the browser; teammates can upload fresh CSVs on any page.

### Option B2 · Run on your own computer

```
1. Install Python from python.org (if not already)
2. Open a terminal/command prompt in this folder:
      pip install -r requirements.txt
      streamlit run app.py
3. Browser opens automatically at http://localhost:8501
```

Tip: drop your full 155k dump at **`data/raw_dump.csv`** — it loads automatically,
no uploader needed.

---

## After deploying — using it with fresh data

- Every page has its own **📂 CSV uploader** in the sidebar — export a fresh CSV
  from your sheet, drop it in, the page rebuilds instantly.
- Format changes (renamed columns, different date styles, extra columns) are
  handled automatically — 12 automated checks verify numbers stay identical.
- New SKU codes decode themselves from product names; review them in the
  **Decoder registry** expander (Interactive Table tab).
- Date conventions (day-first) are pinned in **`data/config.json`**.

## Troubleshooting

| Problem | Fix |
|---|---|
| Public link shows 404 / old version | Wait 2 min → Ctrl + Shift + R |
| Pages site blank | Repo → Settings → Pages → Branch `main`, folder `/ (root)`, Save |
| Streamlit Cloud app won't start | Check `requirements.txt` uploaded; app file must be `app.py` |
| A page says "could not find column" | The loader tells you which column — rename it closer to the original export or check `DEPLOY_STEPS` warnings shown on-page |
