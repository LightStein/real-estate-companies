# Data Pipeline Runbook

## Quick Start — Refresh All Data

```bash
git clone git@github.com:LightStein/real-estate-companies.git
cd real-estate-companies
pip install requests beautifulsoup4 playwright
playwright install chromium

# Full pipeline (takes ~3 hours total)
python3 scraper.py          # Scrape yell.ge + bia.ge → companies.csv
python3 filter.py           # Remove architects/designers → companies_builders.csv
python3 classify.py         # Check websites → companies_verified.csv + companies_dropped.csv
python3 facebook_check.py   # Find & check FB pages → fb_verified.csv + fb_dropped.csv
python3 prioritize.py       # Score & rank → companies_prioritized.csv
```

The final output is `companies_prioritized.csv` and `companies.json`.

---

## Pipeline Steps (detailed)

### Step 1: Scrape (`scraper.py`) — ~2 hours

Scrapes two Georgian business directories:

| Source | What | How | Time |
|--------|------|-----|------|
| yell.ge | Category 339 (სამშენებლო კომპანიები), 9 pages | Parse `SR_div_*` containers on listing pages | ~2 min |
| bia.ge | Subcategory 2568 under construction (64), ~3,700 companies | Collect from paginated listings (500/page), then visit each detail page for `tel:` links | ~2 hours |

**Output:** `companies.csv` — all phone numbers with company name, website, source.

**Resumable:** Yes. If interrupted, restart — it skips already-saved phone numbers (dedup by normalized phone).

**To add a new source:** Add a `scrape_xxx()` function and append it to the `scrapers` list in `main()`.

### Step 2: Filter by name (`filter.py`) — instant

Removes companies whose name contains architect/design/finance/studio keywords but NOT builder keywords.

**Output:** `companies_builders.csv` (kept) + `companies_rejected.csv` (dropped)

**To adjust:** Edit `EXCLUDE_PATTERNS` and `INCLUDE_PATTERNS` in the script.

### Step 3: Classify by website (`classify.py`) — ~15 min

Fetches each company's website and scores the content for construction vs non-construction keywords.

**Output:** `companies_verified.csv` + `companies_dropped.csv` + `companies_no_website.csv`

**Cache:** `website_cache.csv` — delete to re-check all sites.

### Step 4: Facebook check (`facebook_check.py`) — ~1.5 hours

1. Re-fetches bia.ge and yell.ge detail pages to find Facebook URLs
2. Uses Playwright to fetch each FB page and classify from `og:description`

**Output:** `fb_verified.csv` + `fb_dropped.csv` + `fb_unknown.csv`

**Cache:** `fb_urls_cache.csv` (company→FB URL mapping), `fb_class_cache.csv` (FB page classification). Delete to re-check.

### Step 5: Facebook activity (`fb_activity.py`) — ~10 min

Uses Playwright to check each known Facebook page for last post date and like count.

**Output:** `fb_activity_cache.csv`

**How it works:** Reads `aria-label` attributes on the FB page for dates like "March 26, 2024", extracts like count from `og:description`.

### Step 6: Google Maps check (`gmaps_check.py`) — ~1.5 hours

Uses Playwright to search Google Maps for each company and extract rating, review count, open/closed status, and category.

**Output:** `gmaps_cache.csv`

**How it works:** Searches `google.com/maps/search/COMPANY_NAME+სამშენებლო+თბილისი`, parses `role="article"` elements and `aria-label` attributes.

### Step 7: Prioritize (`prioritize.py`) — ~1 min

Combines all signals into a score and assigns priority tiers A-E.

**Scoring:**
| Signal | Points |
|--------|--------|
| Website alive (HEAD request) | +3 |
| Website dead | -2 |
| Has Facebook page | +1 |
| FB posted in last 6 months | +5 |
| FB posted in last 12 months | +3 |
| FB posted 1-2 years ago | +1 |
| FB dormant (2+ years) | -2 |
| FB 1000+ likes (only if recent posts) | +1 |
| Google Maps open | +3 |
| Google Maps permanently closed | -5 |
| Google Maps rated 4+★ with 3+ reviews | +2 |
| Google Maps has reviews | +1 |
| Google Maps has rating | +1 |
| Listed on both yell.ge AND bia.ge | +2 |
| Multiple phone numbers | +1 |
| Has mobile number | +1 |
| Has landline | +1 |

**Tiers:** A (7+), B (5-6), C (4), D (2-3), E (0-1)

**Output:** `companies_prioritized.csv` — also rebuilds `companies.json` (run the JSON export separately if needed).

### JSON export

```bash
python3 -c "
import csv, json, re
# ... (see the inline script in the git history, or run prioritize.py which outputs CSV,
# then use the json export script from the repo)
"
```

Or just use the `companies.json` that's already in the repo.

---

## Cache Files

All cache files are safe to delete for a full refresh:

| File | What | Delete to... |
|------|------|-------------|
| `website_cache.csv` | Website content classification | Re-analyze all websites |
| `liveness_cache.csv` | Website HEAD check results | Re-check if sites are up |
| `fb_urls_cache.csv` | Company → Facebook URL mapping | Re-discover FB pages from bia/yell |
| `fb_class_cache.csv` | FB page content classification | Re-classify FB pages |
| `fb_activity_cache.csv` | FB last post date + likes | Re-check FB activity |
| `gmaps_cache.csv` | Google Maps rating/status/reviews | Re-scan all companies on Maps |

---

## Dependencies

```
python3 >= 3.10
requests
beautifulsoup4
playwright (+ chromium browser: `playwright install chromium`)
```

---

## Common Tasks

### Add a new scraping source

1. Add a function `scrape_xxx(store: CompanyStore)` in `scraper.py`
2. Append `("xxx", scrape_xxx)` to the `scrapers` list in `main()`
3. The `CompanyStore` handles dedup — just call `store.add_company(name, phones, website, "xxx")`

### Re-score with different weights

Edit the scoring section in `prioritize.py` (search for "Score each company"). Adjust point values, then re-run.

### Add a new signal

1. Create a new check script (like `gmaps_check.py`) that outputs a cache CSV
2. Load it in `prioritize.py` (add to the data loading section)
3. Add scoring logic in the scoring loop
4. Re-run `prioritize.py`

### Refresh just Google Maps data

```bash
rm gmaps_cache.csv
python3 gmaps_check.py    # ~1.5 hours
python3 prioritize.py     # ~1 min, rebuilds CSV
# Then rebuild JSON and push
```

### Refresh just Facebook data

```bash
rm fb_activity_cache.csv
python3 fb_activity.py    # ~10 min
python3 prioritize.py
```
