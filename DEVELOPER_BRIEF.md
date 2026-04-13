# Wood Sales Lead Management — Mobile Web App Brief

## What this is

A mobile-first web app for a wood/lumber salesperson to cold-call Georgian construction companies. The data comes from a scraping + scoring pipeline that collected ~1,750 phone numbers across ~1,440 companies from Georgian business directories (yell.ge, bia.ge), then filtered out non-builders and scored each company by activity signals.

The salesperson opens this on their Android phone, sees a prioritized list, taps to call, and tracks progress.

---

## Data Schema

The main data file is `companies_prioritized.csv` (will be updated once Google Maps scoring finishes). Here are the fields:

| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `priority` | string | `A`, `B`, `C` | Priority tier. A = call first, C = call last |
| `score` | integer | `10`, `3`, `-1` | Numeric score (higher = better lead). Range roughly -5 to 15 |
| `company_name` | string | `კრაფტი` | Company name, mostly in Georgian (UTF-8) |
| `phone` | string | `(595) 55 83 83` | Original phone number as scraped |
| `phone_normalized` | string | `+995595558383` | E.164 format, always starts with `+995` |
| `website` | string | `http://www.kraft.ge` | Company website URL (may be empty) |
| `facebook` | string | `https://www.facebook.com/geokraft` | Facebook page URL (may be empty) |
| `source` | string | `yell.ge` or `bia.ge` | Which directory it was scraped from |
| `signals` | string | `website_live; fb_posted_recently; has_mobile` | Semicolon-separated list of scoring signals |

### Upcoming fields (Google Maps scan in progress):
| Field | Type | Example |
|-------|------|---------|
| `gmaps_rating` | float | `4.5` |
| `gmaps_reviews` | integer | `12` |
| `gmaps_status` | string | `open`, `permanently_closed`, `found`, `not_found` |
| `gmaps_category` | string | `სამშენებლო კომპანია` |

### Data volumes

- ~1,750 phone number entries (rows)
- ~1,440 unique companies (one company can have multiple phones)
- Priority A: ~110 companies / ~250 phones
- Priority B: ~300 companies / ~440 phones
- Priority C: ~1,030 companies / ~1,070 phones

---

## Scoring Signals Explained

Each company gets a numeric score based on these signals (stored in the `signals` field):

| Signal | Points | Meaning |
|--------|--------|---------|
| `website_live` | +3 | Company website responds to HTTP requests right now |
| `website_dead` | -2 | Website was listed but doesn't load (might be out of business) |
| `has_facebook` | +1 | Has a known Facebook business page |
| `fb_posted_recently` | +5 | Facebook page has posts from the last 6 months |
| `fb_posted_this_year` | +3 | Facebook page has posts from the last 12 months |
| `fb_posted_2yrs` | +1 | Last Facebook post was 1-2 years ago |
| `fb_dormant` | -2 | No Facebook posts in 2+ years |
| `fb_NNN_likes` | +1 | Facebook page has 1,000+ likes (only if also has recent posts) |
| `gmaps_open` | +3 | Google Maps shows the business as open |
| `gmaps_CLOSED` | -5 | Google Maps says "permanently closed" |
| `gmaps_X.X★_Nrev` | +1/+2 | Has Google Maps rating and reviews |
| `multi_source` | +2 | Listed on both yell.ge AND bia.ge (more established) |
| `N_phones` | +1 | Company has multiple phone numbers |
| `has_mobile` | +1 | Has a mobile number (someone will answer) |
| `has_landline` | +1 | Has a landline (has a physical office) |

Priority tiers:
- **A** (score ≥ 5): Strong signals of active business — call first
- **B** (score 2-4): Some signals — good leads
- **C** (score ≤ 1): No online presence — try last, may be inactive

---

## Desired Mobile App Features

### Core (MVP)

1. **Prioritized company list**
   - Default sort: by score descending (A → B → C)
   - Show: company name, priority badge (A/B/C), score, first phone number
   - Color coding: A = green, B = yellow, C = gray

2. **Company detail card** (tap to expand or separate screen)
   - Company name
   - All phone numbers with individual **call buttons** (`tel:+995...` links)
   - **Add to contacts** button (vCard / Android intent)
   - Website link (opens browser)
   - Facebook link (opens FB app or browser)
   - Google Maps link: `https://www.google.com/maps/search/COMPANY_NAME+თბილისი`
   - Score breakdown (show signals as tags/chips)
   - Source badge (yell.ge / bia.ge)

3. **Call tracking**
   - Mark a company as: "Called", "No Answer", "Interested", "Not Interested", "Call Back Later"
   - Status persists (localStorage or backend)
   - Filter list by status: "Not yet called", "Call back", "Interested"

4. **Search & filter**
   - Search by company name
   - Filter by priority (A/B/C)
   - Filter by call status
   - Filter by has website / has Facebook

### Nice to Have

5. **Notes per company** — free text field to jot down call notes
6. **Call back reminders** — set a date/time to call back, push notification
7. **Export** — export "Interested" companies as CSV or share via WhatsApp
8. **Stats dashboard** — "Called 45/1442 today, 12 interested, 8 no answer"
9. **Offline support** — PWA with service worker, works without internet
10. **Multi-user** — if multiple salespeople share the list, sync state via backend

---

## Technical Recommendations

### Simplest approach (static PWA)
- Single HTML/JS/CSS app, no backend needed
- Load CSV via fetch or embed as JSON
- Use localStorage for call status and notes
- Host on GitHub Pages or Netlify (free)
- Add PWA manifest for "Add to Home Screen" on Android
- Total data is ~200KB as JSON — easily fits in memory

### If you need multi-user / backend
- Supabase or Firebase for auth + realtime DB
- Store call statuses and notes in the cloud
- Still keep the company data as static JSON (it doesn't change often)

### Key technical notes
- All text is Georgian UTF-8 — make sure the font supports Georgian script (system fonts on Android do)
- Phone numbers are in E.164 format (`+995XXXXXXXXX`) — use `tel:` links for calling
- The `signals` field is semicolon-separated — split and render as chips/tags
- Company names can be long (some are 80+ chars) — truncate with ellipsis in list view
- ~1,750 rows is tiny — no pagination needed, just virtual scrolling or render all

---

## Data Files

| File | Description |
|------|-------------|
| `companies_prioritized.csv` | Main data file — sorted by score, ready to use |
| `companies_final.csv` | Same data without priority/score columns |
| `gmaps_cache.csv` | Google Maps data (rating, reviews, status) — join on company_name |
| `fb_activity_cache.csv` | Facebook activity data — join on fb_url |
| `website_cache.csv` | Website classification results |
| `liveness_cache.csv` | Website up/down status |

The developer should primarily use `companies_prioritized.csv` and optionally join with `gmaps_cache.csv` for Maps data.

---

## Sample Data (first 5 rows)

```csv
priority,score,company_name,phone,phone_normalized,website,facebook,source,signals
A,10,თეგიმი,+995555202020,+995555202020,,https://www.facebook.com/tegimi2,yell.ge,has_facebook; fb_posted_recently; multi_source; 3_phones; has_mobile
A,9,ბაკო,264 54 54,+995322645454,http://www.bako.ge,https://www.facebook.com/bakogroup/,yell.ge,website_live; has_facebook; multi_source; 3_phones; has_mobile; has_landline
A,9,კრაფტი,(595) 55 83 83,+995595558383,,https://www.facebook.com/geokraft,bia.ge,has_facebook; fb_posted_recently; fb_1441_likes; 2_phones; has_mobile
A,9,მოზაიკ დეველოპმენტი,(555) 88 60 00,+995555886000,,https://www.facebook.com/mosaic.ge,bia.ge,has_facebook; fb_posted_recently; 2_phones; has_mobile; has_landline
A,8,ახალი სახლი,(595) 04 41 11,+995595044111,https://akhalisakhli.com,,yell.ge,website_live; has_facebook; multi_source; 2_phones; has_mobile
```
