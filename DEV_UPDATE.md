# Data Update — Google Maps Integration

## What changed

`companies.json` and `companies_prioritized.csv` have been updated with Google Maps data for all 1,442 companies. The priority distribution changed significantly:

| Priority | Before Maps | After Maps | Change |
|----------|-------------|------------|--------|
| A (call first) | 110 | **312** | +202 |
| B (good leads) | 303 | **1,037** | +734 |
| C (try last) | 1,029 | **93** | -936 |

Most of the C-tier companies that had zero signals now have Google Maps confirmation that they exist and are open.

## New fields in companies.json

```json
{
  "gmaps_rating": 5.0,
  "gmaps_reviews": 12,
  "gmaps_status": "open",
  "gmaps_category": "სამშენებლო კომპანია"
}
```

| Field | Values | Description |
|-------|--------|-------------|
| `gmaps_rating` | `0.0` - `5.0` | Google Maps star rating (0 = no rating) |
| `gmaps_reviews` | integer | Number of Google reviews |
| `gmaps_status` | `open`, `found`, `not_found`, `permanently_closed`, `error` | `open` = confirmed operating, `found` = on Maps but status unclear |
| `gmaps_category` | string | Google Maps business category (Georgian) |

## Also added previously

| Field | Example | Description |
|-------|---------|-------------|
| `phone.local` | `555 20 20 20` | Local Georgian dialing format (no +995) |
| `phone.type` | `mobile` / `landline` | Phone type |

## How to integrate

Pull the latest and replace your data source:

```bash
git pull origin master
```

The `companies.json` file is the single source of truth — 565 KB, 1,442 companies, sorted by priority score descending.

### Quick integration with Claude Code

```bash
claude --dangerously-skip-permissions "The companies.json file has been updated with new fields: gmaps_rating, gmaps_reviews, gmaps_status, gmaps_category. Also each phone now has 'local' (Georgian dial format like '555 20 20 20') and 'type' (mobile/landline). Update the app to: 1) Show Google Maps rating stars and review count on company cards 2) Show a green dot for gmaps_status=open, gray for found, red for permanently_closed 3) Use phone.local for display and phone.normalized for tel: links 4) Show a 'mobile'/'landline' label next to each phone number 5) Add a Google Maps button that opens google.com/maps/search/COMPANY_NAME+თბილისი"
```
