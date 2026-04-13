#!/usr/bin/env python3
"""
Find Facebook pages for companies that have no website, then classify them.

Phase 1: Collect Facebook URLs from bia.ge and yell.ge detail pages.
Phase 2: Fetch each Facebook page and classify from og:description.
Phase 3: Write results.

Caches everything so reruns are fast.
"""

import csv
import os
import re
import random
import time

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# I/O files
# ---------------------------------------------------------------------------

INPUT = "companies_no_website.csv"
OUT_VERIFIED = "fb_verified.csv"
OUT_DROPPED = "fb_dropped.csv"
OUT_UNKNOWN = "fb_unknown.csv"       # no Facebook page found
FB_CACHE = "fb_urls_cache.csv"       # company_name -> fb_url
FB_CLASS_CACHE = "fb_class_cache.csv" # fb_url -> classification

FIELDS = ["company_name", "phone", "phone_normalized", "website", "source"]
DELAY = (1, 2)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

# Same keyword lists as classify.py (abbreviated for clarity)
BUILDER_KW = [
    "მშენებლობ", "სამშენებლო", "ბეტონ", "ცემენტ", "აგურ", "ბლოკ", "არმატურ",
    "სახურავ", "იატაკ", "ფანჯარ", "სანტექნიკ", "მონოლით", "კარკას", "საძირკვ",
    "კედელ", "გადახურვ", "შელესვ", "მოპირკეთებ", "თაბაშირ", "რემონტ",
    "სამონტაჟო", "კოტეჯ", "სახლ", "ბინ", "ხე-ტყ", "ხის მასალ", "პარკეტ",
    "construction", "building", "concrete", "renovation", "contractor",
    "roofing", "plumbing", "timber", "lumber", "carpentry", "foundation",
]

NON_BUILDER_KW = [
    "არქიტექტურ", "საპროექტო", "პროექტირებ", "დიზაინ", "ინტერიერ",
    "ლანდშაფტ", "ვიზუალიზაცი", "3d მოდელ", "საკონსულტაციო", "იურიდიულ",
    "ტურიზმ", "სასტუმრო", "რესტორან", "კვება", "სილამაზ", "სამედიცინო",
    "პროგრამირებ", "architect", "interior design", "landscape design",
    "tourism", "restaurant", "beauty salon", "software",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_session():
    s = requests.Session()
    s.headers.update({
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "ka-GE,ka;q=0.9,en;q=0.5",
    })
    return s


def fetch(session, url, timeout=10):
    session.headers["User-Agent"] = random.choice(USER_AGENTS)
    time.sleep(random.uniform(*DELAY))
    try:
        r = session.get(url, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        return r
    except Exception:
        return None


def load_csv_cache(path, key_field, val_fields):
    """Load a CSV cache as dict[key] = (val1, val2, ...)."""
    cache = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = row[key_field]
                vals = tuple(row[vf] for vf in val_fields)
                cache[key] = vals
    return cache


def append_csv(path, fieldnames, row_dict):
    exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if not exists:
            w.writeheader()
        w.writerow(row_dict)


# ---------------------------------------------------------------------------
# Phase 1: Find Facebook URLs from source site detail pages
# ---------------------------------------------------------------------------

def find_fb_urls_from_bia(session, company_names):
    """Re-fetch bia.ge listing to get company IDs, then detail pages for FB links."""
    print("\n  Phase 1a: Searching bia.ge detail pages for Facebook links...")

    # Collect company entries from listings (same as scraper.py)
    base = "http://www.bia.ge"
    entries = {}  # name -> detail_url

    for pg in range(1, 9):  # 8 pages of 500
        url = (f"{base}/Company/Industry/2568?ServiceCategoryId=64"
               f"&Filter.PageNumber={pg}&Filter.PageLimit=500")
        resp = fetch(session, url, timeout=20)
        if not resp:
            break
        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.find_all("li", class_="list-row-box")
        if not cards:
            break
        for card in cards:
            a = card.find("a", class_="title")
            if a:
                name = a.get_text(strip=True)
                href = a.get("href", "")
                if name in company_names and href:
                    entries[name] = base + href
        print(f"    Listing page {pg}: mapped {len(entries)} companies so far")
        if len(cards) < 500:
            break

    print(f"    Found {len(entries)} bia.ge detail URLs for target companies")

    # Now fetch detail pages for FB links
    fb_urls = {}
    for i, (name, detail_url) in enumerate(entries.items()):
        if i % 100 == 0:
            print(f"    [{i}/{len(entries)}] checking bia.ge detail pages...")

        resp = fetch(session, detail_url)
        if not resp:
            continue
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        for a in soup.find_all("a", href=re.compile(r"facebook\.com/")):
            href = a["href"]
            # Skip bia.ge's own FB and share links
            if "BIA" not in href and "share.php" not in href and "oauth" not in href:
                fb_urls[name] = href
                break

    return fb_urls


def find_fb_urls_from_yell(session, company_names):
    """Fetch yell.ge detail pages for Facebook links."""
    print("\n  Phase 1b: Searching yell.ge detail pages for Facebook links...")

    base = "https://www.yell.ge"
    fb_urls = {}

    # Collect company IDs from all listing pages
    company_ids = {}  # name -> company_id

    # Page 1
    resp = fetch(session, f"{base}/companies.php?lan=geo&rub=339", timeout=20)
    if not resp:
        return fb_urls
    soup = BeautifulSoup(resp.text, "html.parser")
    pm = re.search(r"გვერდი:\s*\d+\s*\((\d+)\)", soup.get_text())
    total_pages = int(pm.group(1)) if pm else 1

    _extract_yell_ids(soup, company_names, company_ids)

    for pg in range(2, total_pages + 1):
        url = (f"{base}/search.php?file=companies&rub=339&lan=geo&S_lan=geo"
               f"&s_b=1&o_b_n=0&sh_o_m=0&SR_pg={pg}&sort=PR&filter=0000000")
        resp = fetch(session, url)
        if not resp:
            break
        soup = BeautifulSoup(resp.text, "html.parser")
        _extract_yell_ids(soup, company_names, company_ids)

    print(f"    Found {len(company_ids)} yell.ge company IDs for target companies")

    # Fetch detail pages
    for i, (name, cid) in enumerate(company_ids.items()):
        if i % 50 == 0:
            print(f"    [{i}/{len(company_ids)}] checking yell.ge detail pages...")

        detail_url = f"{base}/company.php?lan=geo&id={cid}"
        resp = fetch(session, detail_url)
        if not resp:
            continue
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        for a in soup.find_all("a", href=re.compile(r"facebook\.com/")):
            href = a["href"]
            if "share.php" not in href and "oauth" not in href and "yell.ge" not in href:
                fb_urls[name] = href
                break

    return fb_urls


def _extract_yell_ids(soup, target_names, out_dict):
    for container in soup.find_all("div", id=re.compile(r"^SR_div_\d+")):
        cid = container["id"].replace("SR_div_", "")
        for a in container.find_all("a", href=re.compile(r"company\.php.*id=" + cid)):
            name = a.get_text(strip=True)
            if name and name in target_names and name not in out_dict:
                out_dict[name] = cid
                break


# ---------------------------------------------------------------------------
# Phase 2: Fetch Facebook pages and classify
# ---------------------------------------------------------------------------

def classify_fb_pages_batch(fb_urls_to_check, fb_class_cache):
    """Classify Facebook pages using Playwright (requests gets blocked)."""
    from playwright.sync_api import sync_playwright

    results = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            locale="ka-GE",
        )
        page = context.new_page()

        for i, fb_url in enumerate(fb_urls_to_check):
            if i % 20 == 0:
                print(f"  [{i}/{len(fb_urls_to_check)}] classifying FB pages...")

            time.sleep(random.uniform(1.5, 3))
            try:
                page.goto(fb_url, timeout=15000, wait_until="domcontentloaded")
                time.sleep(1)

                content = page.content()
                soup = BeautifulSoup(content, "html.parser")

                text_parts = []
                for meta in soup.find_all("meta"):
                    prop = meta.get("property", meta.get("name", ""))
                    cont = meta.get("content", "")
                    if cont and any(k in prop for k in ["description", "title"]):
                        text_parts.append(cont)

                text = " ".join(text_parts).lower()

                if not text or len(text) < 5:
                    cls, reason = "no_info", "no description on FB page"
                else:
                    builder_score = sum(1 for kw in BUILDER_KW if kw.lower() in text)
                    non_builder_score = sum(1 for kw in NON_BUILDER_KW if kw.lower() in text)

                    if builder_score > 0 and builder_score > non_builder_score:
                        hits = [kw for kw in BUILDER_KW if kw.lower() in text][:4]
                        cls, reason = "builder", f"FB: {', '.join(hits)}"
                    elif non_builder_score > 0 and non_builder_score > builder_score:
                        hits = [kw for kw in NON_BUILDER_KW if kw.lower() in text][:4]
                        cls, reason = "non_builder", f"FB: {', '.join(hits)}"
                    else:
                        cls, reason = "unclear", f"FB desc: {text[:80]}"

            except Exception:
                cls, reason = "unreachable", "could not fetch"

            results[fb_url] = (cls, reason)
            fb_class_cache[fb_url] = (cls, reason)
            append_csv(FB_CLASS_CACHE, ["fb_url", "classification", "reason"],
                       {"fb_url": fb_url, "classification": cls, "reason": reason})

        browser.close()

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    with open(INPUT, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    company_names = set(r["company_name"] for r in rows)
    print(f"Loaded {len(rows)} entries ({len(company_names)} unique companies) from {INPUT}")

    # Load caches
    fb_url_cache = load_csv_cache(FB_CACHE, "company_name", ("fb_url",))
    fb_class_cache = load_csv_cache(FB_CLASS_CACHE, "fb_url", ("classification", "reason"))
    print(f"Cached FB URLs: {len(fb_url_cache)}, Cached classifications: {len(fb_class_cache)}")

    session = get_session()

    # Phase 1: Find Facebook URLs (only for companies not in cache)
    names_to_find = company_names - set(fb_url_cache.keys())
    print(f"Need to find FB URLs for {len(names_to_find)} companies")

    if names_to_find:
        # Search bia.ge detail pages
        bia_fb = find_fb_urls_from_bia(session, names_to_find)
        for name, url in bia_fb.items():
            fb_url_cache[name] = (url,)
            append_csv(FB_CACHE, ["company_name", "fb_url"], {"company_name": name, "fb_url": url})
        print(f"  Found {len(bia_fb)} FB URLs from bia.ge")

        still_missing = names_to_find - set(bia_fb.keys())

        # Search yell.ge detail pages
        yell_fb = find_fb_urls_from_yell(session, still_missing)
        for name, url in yell_fb.items():
            fb_url_cache[name] = (url,)
            append_csv(FB_CACHE, ["company_name", "fb_url"], {"company_name": name, "fb_url": url})
        print(f"  Found {len(yell_fb)} FB URLs from yell.ge")

        # Mark the rest as not found
        all_found = set(bia_fb.keys()) | set(yell_fb.keys())
        for name in names_to_find - all_found:
            fb_url_cache[name] = ("",)
            append_csv(FB_CACHE, ["company_name", "fb_url"], {"company_name": name, "fb_url": ""})

    # Phase 2: Classify Facebook pages
    fb_urls_to_check = set()
    for name, (url,) in fb_url_cache.items():
        if url and url not in fb_class_cache:
            fb_urls_to_check.add(url)

    print(f"\nNeed to classify {len(fb_urls_to_check)} Facebook pages (using Playwright)")

    if fb_urls_to_check:
        classify_fb_pages_batch(list(fb_urls_to_check), fb_class_cache)

    # Phase 3: Write results
    verified = []
    dropped = []
    unknown = []

    for row in rows:
        name = row["company_name"]
        fb_url_tuple = fb_url_cache.get(name, ("",))
        fb_url = fb_url_tuple[0] if fb_url_tuple else ""

        if not fb_url:
            unknown.append(row)
            continue

        cls_tuple = fb_class_cache.get(fb_url, ("unclear", ""))
        cls = cls_tuple[0]

        if cls == "non_builder":
            dropped.append(row)
        else:
            # builder, unclear, unreachable, no_info → keep
            row_copy = dict(row)
            row_copy["website"] = fb_url  # Add FB URL as website
            verified.append(row_copy)

    def write_csv(path, data):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(data)

    write_csv(OUT_VERIFIED, verified)
    write_csv(OUT_DROPPED, dropped)
    write_csv(OUT_UNKNOWN, unknown)

    # Stats
    has_fb = sum(1 for _, (u,) in fb_url_cache.items() if u)
    cls_counts = {}
    for url, (cls, _) in fb_class_cache.items():
        cls_counts[cls] = cls_counts.get(cls, 0) + 1

    print(f"\n{'='*60}")
    print(f"Facebook URL discovery:")
    print(f"  Companies with FB page found: {has_fb}")
    print(f"  Companies with no FB page:    {len(company_names) - has_fb}")

    print(f"\nFacebook page classification:")
    for cls, count in sorted(cls_counts.items()):
        print(f"  {cls:15s}: {count}")

    print(f"\nOutput files:")
    print(f"  {OUT_VERIFIED:25s}: {len(verified):5d} entries (FB confirmed or unclear)")
    print(f"  {OUT_DROPPED:25s}: {len(dropped):5d} entries (FB says non-builder)")
    print(f"  {OUT_UNKNOWN:25s}: {len(unknown):5d} entries (no FB page found)")

    # Show dropped
    dropped_names = sorted(set(r["company_name"] for r in dropped))
    if dropped_names:
        print(f"\nDropped by Facebook ({len(dropped_names)} companies):")
        for n in dropped_names:
            fb = fb_url_cache.get(n, ("",))[0]
            cls_info = fb_class_cache.get(fb, ("", ""))[1] if fb else ""
            print(f"  {n:40s} | {cls_info[:50]}")


if __name__ == "__main__":
    main()
