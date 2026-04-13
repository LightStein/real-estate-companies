#!/usr/bin/env python3
"""
Search Google Maps for each company and extract:
  - Rating (1-5 stars)
  - Review count
  - Open/closed/permanently closed status
  - Category (confirms they're construction)

Outputs gmaps_cache.csv, then re-runs prioritize.py.
"""

import csv
import os
import re
import time
import random
from urllib.parse import quote

PRIORITIZED = "companies_prioritized.csv"
GMAPS_CACHE = "gmaps_cache.csv"
GMAPS_FIELDS = ["company_name", "gmaps_rating", "gmaps_reviews", "gmaps_status", "gmaps_category"]

def load_cache() -> dict[str, dict]:
    cache = {}
    if os.path.exists(GMAPS_CACHE):
        with open(GMAPS_CACHE, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cache[row["company_name"]] = row
    return cache


def save_entry(entry: dict):
    exists = os.path.exists(GMAPS_CACHE)
    with open(GMAPS_CACHE, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=GMAPS_FIELDS)
        if not exists:
            w.writeheader()
        w.writerow(entry)


def parse_gmaps_results(content: str, target_name: str) -> dict:
    """Parse Google Maps search results page."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(content, "html.parser")

    result = {
        "gmaps_rating": "",
        "gmaps_reviews": "0",
        "gmaps_status": "not_found",
        "gmaps_category": "",
    }

    # Extract from article elements (search result cards)
    articles = soup.find_all(attrs={"role": "article"})

    # Also get all aria-labels with ratings
    all_labels = []
    for el in soup.find_all(attrs={"aria-label": True}):
        all_labels.append(el["aria-label"])

    if not articles and not all_labels:
        return result

    # Check if we landed on a single business page (direct match)
    # Look for rating pattern in aria-labels: "X,X ვარსკვლავი" or "X ვარსკვლავი, N მიმოხილვა"
    for label in all_labels:
        m = re.match(r"(\d[,\.]\d)\s*ვარსკვლავი\s*[,.]?\s*(\d+)?\s*მიმოხილვა?", label)
        if m:
            result["gmaps_rating"] = m.group(1).replace(",", ".")
            if m.group(2):
                result["gmaps_reviews"] = m.group(2)
            result["gmaps_status"] = "found"
            break

    # Parse articles for the best match
    best_match = None
    for article in articles:
        text = article.get_text(strip=True)

        # Extract rating
        rating_match = re.search(r"(\d[,\.]\d)", text[:30])
        rating = rating_match.group(1).replace(",", ".") if rating_match else ""

        # Extract review count
        review_match = re.search(r"(\d+)\s*მიმოხილვა", text)
        reviews = review_match.group(1) if review_match else "0"

        # Extract category
        cat = ""
        for category in ["სამშენებლო კომპანია", "უძრავი ქონების დეველოპერი",
                         "სამშენებლო მასალების მაღაზია", "რეკონსტრუქტორი",
                         "სამშენებლო მოედანი", "construction company",
                         "building materials", "contractor"]:
            if category in text.lower():
                cat = category
                break

        # Check status
        status = "found"
        if "სამუდამოდ დაკეტილი" in text or "permanently closed" in text.lower():
            status = "permanently_closed"
        elif "დროებით დაკეტილი" in text or "temporarily closed" in text.lower():
            status = "temporarily_closed"
        elif "დახურულია" in text:
            status = "open"  # "closed now, opens at X" = active business
        elif "გახსნილია" in text or "ღიაა" in text:
            status = "open"

        if rating or cat or status != "found":
            if best_match is None or float(rating or "0") > float(best_match.get("gmaps_rating") or "0"):
                best_match = {
                    "gmaps_rating": rating,
                    "gmaps_reviews": reviews,
                    "gmaps_status": status,
                    "gmaps_category": cat,
                }

    if best_match:
        result.update(best_match)

    # Fallback: just check if anything was found
    if result["gmaps_status"] == "not_found" and articles:
        result["gmaps_status"] = "found"

    return result


def main():
    # Load companies
    with open(PRIORITIZED, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    companies = {}
    for r in rows:
        companies.setdefault(r["company_name"], r)

    print(f"Companies to check: {len(companies)}")

    cache = load_cache()
    to_check = [n for n in companies if n not in cache]
    print(f"Already cached: {len(cache)}, need to check: {len(to_check)}")

    if not to_check:
        print("All cached.")
        _print_summary(cache)
        return

    from playwright.sync_api import sync_playwright
    from bs4 import BeautifulSoup

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="ka-GE",
        )
        page = context.new_page()

        for i, name in enumerate(to_check):
            if i % 25 == 0:
                print(f"  [{i}/{len(to_check)}] searching Google Maps...")

            search = f"{name} სამშენებლო თბილისი"
            url = f"https://www.google.com/maps/search/{quote(search)}"

            try:
                page.goto(url, timeout=15000, wait_until="domcontentloaded")
                time.sleep(random.uniform(2, 4))
                content = page.content()
                result = parse_gmaps_results(content, name)
            except Exception:
                result = {
                    "gmaps_rating": "",
                    "gmaps_reviews": "0",
                    "gmaps_status": "error",
                    "gmaps_category": "",
                }

            entry = {"company_name": name, **result}
            cache[name] = entry
            save_entry(entry)

        browser.close()

    _print_summary(cache)


def _print_summary(cache):
    from collections import Counter
    statuses = Counter(v["gmaps_status"] for v in cache.values())
    has_rating = sum(1 for v in cache.values() if v["gmaps_rating"])
    has_reviews = sum(1 for v in cache.values() if int(v.get("gmaps_reviews", 0)) > 0)
    closed = sum(1 for v in cache.values() if "closed" in v["gmaps_status"])

    print(f"\n{'='*60}")
    print(f"Google Maps results ({len(cache)} companies):")
    for status, count in sorted(statuses.items()):
        print(f"  {status:25s}: {count}")
    print(f"\n  Has rating:       {has_rating}")
    print(f"  Has reviews:      {has_reviews}")
    print(f"  Permanently closed: {closed}")

    # Show top rated
    rated = [(v["company_name"], float(v["gmaps_rating"]), int(v.get("gmaps_reviews", 0)))
             for v in cache.values() if v["gmaps_rating"]]
    rated.sort(key=lambda x: (-x[1], -x[2]))

    print(f"\nTop rated on Google Maps:")
    for name, rating, reviews in rated[:15]:
        print(f"  {rating:.1f}★ ({reviews:>3} reviews) | {name}")


if __name__ == "__main__":
    main()
