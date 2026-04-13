#!/usr/bin/env python3
"""
Visit company websites and classify whether they're actual builders
(potential wood buyers) or non-builders (architects, designers, etc.).

Reads companies_builders.csv, fetches each website, scores the content,
and writes two output files:
  - companies_verified.csv   (likely wood buyers)
  - companies_dropped.csv    (not wood buyers)
  - companies_no_website.csv (can't verify — no website)

Companies without websites are kept separately since we can't verify them.
"""

import csv
import os
import re
import random
import time
import sys

import requests
from bs4 import BeautifulSoup

INPUT = "companies_builders.csv"
OUT_VERIFIED = "companies_verified.csv"
OUT_DROPPED = "companies_dropped.csv"
OUT_NO_SITE = "companies_no_website.csv"
CACHE_FILE = "website_cache.csv"  # cache results so reruns are fast

FIELDS = ["company_name", "phone", "phone_normalized", "website", "source"]
CACHE_FIELDS = ["website", "classification", "reason"]

DELAY_MIN, DELAY_MAX = 1, 2

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

# ---------------------------------------------------------------------------
# Keywords for scoring page content
# ---------------------------------------------------------------------------

# Signals the company BUILDS things (positive score)
BUILDER_KEYWORDS = [
    # Georgian
    ("მშენებლობ", 3),       # construction
    ("სამშენებლო", 3),      # construction (adj)
    ("ბეტონ", 3),           # concrete
    ("ცემენტ", 2),          # cement
    ("აგურ", 3),            # brick
    ("ბლოკ", 2),            # block
    ("არმატურ", 3),         # rebar
    ("მეტალოკონსტრუქცი", 3),# metal structures
    ("ხის კონსტრუქცი", 4),  # wood structures
    ("სახურავ", 3),         # roof
    ("იატაკ", 2),           # floor
    ("კარ-ფანჯ", 2),        # doors-windows
    ("ფანჯარ", 2),          # window
    ("სანტექნიკ", 2),       # plumbing
    ("ელექტრომონტაჟ", 2),   # electrical work
    ("მონოლით", 3),         # monolith
    ("კარკას", 3),          # frame/skeleton
    ("საძირკვ", 3),         # foundation
    ("კედელ", 2),           # wall
    ("გადახურვ", 3),        # roofing/covering
    ("შელესვ", 2),          # plastering
    ("მოპირკეთებ", 2),      # finishing
    ("თაბაშირ", 2),         # plaster/gypsum
    ("რემონტ", 2),          # repair/renovation
    ("რეკონსტრუქცი", 2),   # reconstruction
    ("სამონტაჟო", 2),       # installation work
    ("კოტეჯ", 2),           # cottage
    ("სახლ", 2),            # house
    ("ბინ", 1),             # apartment
    ("საცხოვრებელ", 2),     # residential
    ("მიწის სამუშაო", 2),   # earthwork
    ("ექსკავატორ", 2),      # excavator
    ("ამწე", 2),            # crane
    ("ხარაჩო", 2),          # scaffolding
    ("ყალიბ", 2),           # formwork
    ("ხე-ტყ", 3),           # wood/timber
    ("ხის მასალ", 4),       # wood materials
    ("პარკეტ", 2),          # parquet
    ("ლამინატ", 2),         # laminate
    # English
    ("construction", 3),
    ("building", 2),
    ("concrete", 3),
    ("foundation", 3),
    ("roofing", 3),
    ("renovation", 2),
    ("contractor", 3),
    ("scaffolding", 2),
    ("excavat", 2),
    ("plumbing", 2),
    ("framing", 3),
    ("drywall", 2),
    ("masonry", 3),
    ("timber", 3),
    ("lumber", 3),
    ("carpentry", 3),
]

# Signals the company does NOT build (negative score)
NON_BUILDER_KEYWORDS = [
    # Georgian
    ("არქიტექტურ", -4),     # architecture
    ("საპროექტო", -3),      # design/project bureau
    ("პროექტირებ", -3),     # designing
    ("დიზაინ", -3),         # design
    ("ინტერიერ", -3),       # interior
    ("ლანდშაფტ", -3),       # landscape
    ("ვიზუალიზაცი", -3),   # visualization
    ("3d მოდელ", -3),       # 3d modeling
    ("რენდერ", -2),         # render
    ("საკონსულტაციო", -3),  # consulting
    ("აუდიტ", -3),          # audit
    ("სადაზღვევო", -3),     # insurance
    ("საბანკო", -3),        # banking
    ("იურიდიულ", -3),      # legal
    ("ადვოკატ", -3),        # lawyer
    ("უძრავი ქონებ", -2),  # real estate
    ("ბროკერ", -2),         # broker
    ("ტურიზმ", -3),         # tourism
    ("სასტუმრო", -2),       # hotel
    ("რესტორან", -3),       # restaurant
    ("კვება", -3),           # food/catering
    ("სილამაზ", -3),        # beauty
    ("სამედიცინო", -3),     # medical
    ("ფარმაცევტ", -3),      # pharma
    ("განათლებ", -3),       # education
    ("სასწავლ", -3),        # educational
    ("პროგრამირებ", -3),    # programming
    ("ვებ გვერდ", -3),      # web page
    # English
    ("architect", -4),
    ("interior design", -4),
    ("landscape design", -3),
    ("visualization", -3),
    ("consulting firm", -2),
    ("real estate agent", -3),
    ("insurance", -3),
    ("tourism", -3),
    ("restaurant", -3),
    ("beauty salon", -3),
    ("software development", -3),
]

# ---------------------------------------------------------------------------
# Website fetching & classification
# ---------------------------------------------------------------------------


def fetch_site(url: str) -> str | None:
    """Fetch a website and return its text content, or None on failure."""
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "ka-GE,ka;q=0.9,en;q=0.5",
    }
    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

    # Normalize URL
    if not url.startswith("http"):
        url = "http://" + url

    try:
        resp = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove script/style tags
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        text = soup.get_text(separator=" ", strip=True)
        # Also get meta description and title
        title = soup.find("title")
        meta_desc = soup.find("meta", attrs={"name": "description"})
        extra = ""
        if title:
            extra += " " + title.get_text()
        if meta_desc:
            extra += " " + (meta_desc.get("content", "") or "")

        return (extra + " " + text).lower()
    except Exception:
        return None


def classify_text(text: str) -> tuple[str, int, str]:
    """Classify page text. Returns (classification, score, reason)."""
    builder_score = 0
    non_builder_score = 0
    builder_hits = []
    non_builder_hits = []

    for keyword, weight in BUILDER_KEYWORDS:
        count = text.count(keyword.lower())
        if count > 0:
            builder_score += weight * min(count, 5)  # cap at 5 hits
            builder_hits.append(f"{keyword}({count})")

    for keyword, weight in NON_BUILDER_KEYWORDS:
        count = text.count(keyword.lower())
        if count > 0:
            non_builder_score += abs(weight) * min(count, 5)
            non_builder_hits.append(f"{keyword}({count})")

    total = builder_score - non_builder_score

    if total >= 2:
        reason = f"builder[{builder_score}]: {', '.join(builder_hits[:5])}"
        return ("builder", total, reason)
    elif total <= -2:
        reason = f"non-builder[{non_builder_score}]: {', '.join(non_builder_hits[:5])}"
        return ("non_builder", total, reason)
    else:
        hits = builder_hits[:3] + non_builder_hits[:3]
        reason = f"unclear[+{builder_score}/-{non_builder_score}]: {', '.join(hits) or 'no keywords'}"
        return ("unclear", total, reason)


def classify_by_name(name: str) -> tuple[str, str]:
    """Fallback: classify by company name alone."""
    nl = name.lower()

    non_builder_name = [
        "არქიტექტ", "architect", "დიზაინ", "design", "ინტერიერ", "interior",
        "სტუდი", "studio", "ლანდშაფტ", "landscape", "საინვესტიციო",
        "ინვესტმენტ", "financial", "ფინანს", "საბროკერო", "რეალტ",
        "ბროკერ", "სააგენტო",
    ]
    builder_name = [
        "მშენ", "build", "construct", "ქონსთრაქშენ", "ბეტონ", "ცემენტ",
        "კარკას", "მონოლით", "რემონტ", "სახლ", "კოტეჯ", "დეველოპმენტ",
        "დეველოპერ", "develop",
    ]

    is_non = any(w in nl for w in non_builder_name)
    is_bld = any(w in nl for w in builder_name)

    if is_non and not is_bld:
        return ("non_builder", "name filter")
    return ("keep", "from construction category")


# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------


def load_cache() -> dict[str, tuple[str, str]]:
    """Load previously classified websites."""
    cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cache[row["website"]] = (row["classification"], row["reason"])
    return cache


def save_cache_entry(website: str, classification: str, reason: str):
    """Append one entry to cache."""
    exists = os.path.exists(CACHE_FILE)
    with open(CACHE_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CACHE_FIELDS)
        if not exists:
            w.writeheader()
        w.writerow({"website": website, "classification": classification, "reason": reason})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    with open(INPUT, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print(f"Loaded {len(rows)} entries from {INPUT}")

    # Group by website for dedup (many phones → same company)
    websites = {}
    for r in rows:
        w = r["website"].strip()
        if w:
            websites.setdefault(w, []).append(r)

    unique_sites = list(websites.keys())
    print(f"Unique websites to check: {len(unique_sites)}")

    cache = load_cache()
    print(f"Already cached: {len(cache)}")

    # Classify each website
    site_class: dict[str, tuple[str, str]] = {}

    for i, site in enumerate(unique_sites):
        if site in cache:
            site_class[site] = cache[site]
            continue

        if (i + 1) % 20 == 0 or i == 0:
            cached_so_far = sum(1 for s in unique_sites[:i+1] if s in cache)
            print(f"  [{i + 1}/{len(unique_sites)}] checking {site[:50]}... "
                  f"(cached: {cached_so_far})")

        text = fetch_site(site)
        if text:
            cls, score, reason = classify_text(text)
            site_class[site] = (cls, reason)
        else:
            site_class[site] = ("unreachable", "site down or blocked")

        save_cache_entry(site, site_class[site][0], site_class[site][1])

    # Now write output files
    verified = []
    dropped = []
    no_website = []

    for row in rows:
        site = row["website"].strip()

        if not site:
            # No website — classify by name only
            cls, reason = classify_by_name(row["company_name"])
            if cls == "non_builder":
                dropped.append(row)
            else:
                no_website.append(row)
            continue

        cls, reason = site_class.get(site, ("unknown", ""))

        if cls == "non_builder":
            dropped.append(row)
        elif cls == "builder":
            verified.append(row)
        elif cls == "unreachable":
            # Site down — keep it (benefit of the doubt, from construction category)
            verified.append(row)
        else:
            # "unclear" — keep it
            verified.append(row)

    def write_csv(path, data):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(data)

    write_csv(OUT_VERIFIED, verified)
    write_csv(OUT_DROPPED, dropped)
    write_csv(OUT_NO_SITE, no_website)

    # Summary stats
    cls_counts = {}
    for site, (cls, reason) in site_class.items():
        cls_counts[cls] = cls_counts.get(cls, 0) + 1

    print(f"\n{'='*60}")
    print(f"Website classification results:")
    for cls, count in sorted(cls_counts.items()):
        print(f"  {cls:15s}: {count} sites")

    print(f"\n{'='*60}")
    print(f"Output files:")
    print(f"  {OUT_VERIFIED:30s}: {len(verified):5d} entries  (builders + unclear + unreachable)")
    print(f"  {OUT_DROPPED:30s}: {len(dropped):5d} entries  (non-builders by website or name)")
    print(f"  {OUT_NO_SITE:30s}: {len(no_website):5d} entries  (no website, kept from construction category)")
    print(f"  Total: {len(verified) + len(dropped) + len(no_website)}")

    # Show what got dropped
    dropped_names = sorted(set(r["company_name"] for r in dropped))
    print(f"\nDropped companies ({len(dropped_names)} unique names):")
    for n in dropped_names:
        # Find the reason
        site = next((r["website"] for r in dropped if r["company_name"] == n and r["website"]), "")
        if site and site in site_class:
            _, reason = site_class[site]
            print(f"  {n:45s} | {reason[:60]}")
        else:
            print(f"  {n:45s} | name filter")


if __name__ == "__main__":
    main()
