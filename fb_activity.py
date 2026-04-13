#!/usr/bin/env python3
"""
Check Facebook page activity (last post date + likes) for companies
with known Facebook URLs. Updates the prioritization scoring.

Outputs fb_activity_cache.csv with: fb_url, last_post_date, likes, active
"""

import csv
import os
import re
import time
import random
from datetime import datetime, timedelta

FB_URL_CACHE = "fb_urls_cache.csv"
FB_ACTIVITY_CACHE = "fb_activity_cache.csv"

ACTIVITY_FIELDS = ["fb_url", "last_post_date", "likes", "active"]

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def parse_date(date_str: str) -> datetime | None:
    """Parse a Facebook date string like 'March 26, 2024'."""
    m = re.match(
        r"(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})",
        date_str, re.I,
    )
    if m:
        month = MONTH_MAP[m.group(1).lower()]
        day = int(m.group(2))
        year = int(m.group(3))
        try:
            return datetime(year, month, day)
        except ValueError:
            return None
    return None


def parse_likes(desc: str) -> int:
    """Extract follower/likes count from og:description."""
    # Patterns: "2,149 likes", "8 likes", "1.2K likes"
    m = re.search(r"([\d,]+)\s*(?:likes|followers|მოწონება)", desc, re.I)
    if m:
        return int(m.group(1).replace(",", ""))
    m = re.search(r"([\d.]+)K\s*(?:likes|followers)", desc, re.I)
    if m:
        return int(float(m.group(1)) * 1000)
    return 0


def load_activity_cache() -> dict[str, dict]:
    cache = {}
    if os.path.exists(FB_ACTIVITY_CACHE):
        with open(FB_ACTIVITY_CACHE, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cache[row["fb_url"]] = row
    return cache


def main():
    # Load known Facebook URLs
    fb_urls = set()
    if os.path.exists(FB_URL_CACHE):
        with open(FB_URL_CACHE, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["fb_url"]:
                    fb_urls.add(row["fb_url"])

    print(f"Facebook URLs to check: {len(fb_urls)}")

    cache = load_activity_cache()
    to_check = [u for u in fb_urls if u not in cache]
    print(f"Already cached: {len(cache)}, need to check: {len(to_check)}")

    if not to_check:
        print("All cached, skipping Playwright.")
    else:
        from playwright.sync_api import sync_playwright
        from bs4 import BeautifulSoup

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                locale="en-US",
            )
            page = context.new_page()

            for i, fb_url in enumerate(to_check):
                if i % 10 == 0:
                    print(f"  [{i}/{len(to_check)}] {fb_url[:50]}")

                last_post = ""
                likes = 0
                active = "unknown"

                try:
                    page.goto(fb_url, timeout=15000, wait_until="domcontentloaded")
                    time.sleep(random.uniform(2, 4))

                    content = page.content()
                    soup = BeautifulSoup(content, "html.parser")

                    # Extract dates from aria-labels
                    dates = []
                    for el in soup.find_all(attrs={"aria-label": True}):
                        label = el["aria-label"]
                        d = parse_date(label)
                        if d:
                            dates.append(d)

                    # Also from datetime attrs
                    for el in soup.find_all(attrs={"datetime": True}):
                        d = parse_date(el["datetime"])
                        if d:
                            dates.append(d)

                    if dates:
                        newest = max(dates)
                        last_post = newest.strftime("%Y-%m-%d")

                        months_ago = (datetime.now() - newest).days / 30
                        if months_ago <= 6:
                            active = "very_active"
                        elif months_ago <= 12:
                            active = "active"
                        elif months_ago <= 24:
                            active = "somewhat"
                        else:
                            active = "dormant"

                    # Extract likes from og:description
                    og = soup.find("meta", property="og:description")
                    if og:
                        likes = parse_likes(og.get("content", ""))

                except Exception:
                    active = "error"

                entry = {
                    "fb_url": fb_url,
                    "last_post_date": last_post,
                    "likes": str(likes),
                    "active": active,
                }
                cache[fb_url] = entry

                # Append to cache file
                exists = os.path.exists(FB_ACTIVITY_CACHE)
                with open(FB_ACTIVITY_CACHE, "a", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=ACTIVITY_FIELDS)
                    if not exists:
                        w.writeheader()
                        exists = True
                    w.writerow(entry)

            browser.close()

    # Summary
    activity_counts = {}
    total_likes = 0
    for url, info in cache.items():
        a = info["active"]
        activity_counts[a] = activity_counts.get(a, 0) + 1
        total_likes += int(info.get("likes", 0))

    print(f"\n{'='*60}")
    print(f"Facebook activity results ({len(cache)} pages):")
    for status, count in sorted(activity_counts.items()):
        print(f"  {status:15s}: {count}")
    print(f"  Total likes across all pages: {total_likes:,}")

    # Show most active
    active_entries = sorted(
        cache.values(),
        key=lambda x: (x["last_post_date"] or "0000"), reverse=True,
    )
    print(f"\nMost recently active:")
    for e in active_entries[:15]:
        print(f"  {e['last_post_date'] or 'no date':12s} | {e['likes']:>6s} likes | {e['active']:12s} | {e['fb_url'][:50]}")


if __name__ == "__main__":
    main()
