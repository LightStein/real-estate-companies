#!/usr/bin/env python3
"""
Score and prioritize companies for cold-calling.

Signals used (higher = call first):
  +3  website is live right now (HEAD request succeeds)
  -2  website is dead (was listed but doesn't load)
  +2  has a Facebook page
  +1  Facebook description mentions construction keywords
  +2  listed on BOTH yell.ge and bia.ge (more established)
  +1  has multiple phone numbers (bigger company)
  +1  has a landline (has a physical office)
  +1  has a mobile number (someone will actually answer)

Outputs companies_prioritized.csv sorted by score (highest first),
with a 'priority' column: A (score>=5), B (2-4), C (<=1).
"""

import csv
import os
import re
import random
import time
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

INPUT = "companies_final.csv"
OUTPUT = "companies_prioritized.csv"
WEBSITE_CACHE = "website_cache.csv"
FB_URL_CACHE = "fb_urls_cache.csv"
FB_ACTIVITY_CACHE = "fb_activity_cache.csv"
LIVENESS_CACHE = "liveness_cache.csv"

OUT_FIELDS = [
    "priority", "score", "company_name", "phone", "phone_normalized",
    "website", "facebook", "source", "signals",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# ---------------------------------------------------------------------------
# Website liveness check (fast HEAD requests, parallel)
# ---------------------------------------------------------------------------


def check_site_alive(url: str) -> bool:
    """Quick HEAD request to check if a site is live."""
    if not url or "facebook.com" in url:
        return False
    if not url.startswith("http"):
        url = "http://" + url
    try:
        r = requests.head(
            url, timeout=5, allow_redirects=True,
            headers={"User-Agent": random.choice(USER_AGENTS)},
        )
        return r.status_code < 400
    except Exception:
        return False


def check_sites_parallel(urls: list[str], cache: dict[str, bool]) -> dict[str, bool]:
    """Check many sites in parallel, using cache."""
    to_check = [u for u in urls if u and u not in cache]
    print(f"  Checking {len(to_check)} websites (cached: {len(urls) - len(to_check)})...")

    results = dict(cache)

    if not to_check:
        return results

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(check_site_alive, url): url for url in to_check}
        done = 0
        for future in as_completed(futures):
            url = futures[future]
            try:
                results[url] = future.result()
            except Exception:
                results[url] = False
            done += 1
            if done % 50 == 0:
                alive = sum(1 for u in to_check[:done] if results.get(u))
                print(f"    {done}/{len(to_check)} checked, {alive} alive so far")

    # Save cache
    with open(LIVENESS_CACHE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["url", "alive"])
        for url, alive in results.items():
            w.writerow([url, "1" if alive else "0"])

    alive_count = sum(1 for u in to_check if results.get(u))
    print(f"  Done: {alive_count}/{len(to_check)} new sites are alive")

    return results


def load_liveness_cache() -> dict[str, bool]:
    cache = {}
    if os.path.exists(LIVENESS_CACHE):
        with open(LIVENESS_CACHE, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cache[row["url"]] = row["alive"] == "1"
    return cache


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    # Load company data
    with open(INPUT, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print(f"Loaded {len(rows)} entries from {INPUT}")

    # Group entries by company name
    company_entries: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        company_entries[r["company_name"]].append(r)

    print(f"Unique companies: {len(company_entries)}")

    # Load Facebook URL cache
    fb_urls: dict[str, str] = {}
    if os.path.exists(FB_URL_CACHE):
        with open(FB_URL_CACHE, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["fb_url"]:
                    fb_urls[row["company_name"]] = row["fb_url"]
    # Also get FB from website field
    for name, entries in company_entries.items():
        for e in entries:
            if "facebook.com" in e.get("website", ""):
                fb_urls[name] = e["website"]

    print(f"Companies with known Facebook: {len(fb_urls)}")

    # Load Facebook activity data
    fb_activity: dict[str, dict] = {}
    if os.path.exists(FB_ACTIVITY_CACHE):
        with open(FB_ACTIVITY_CACHE, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                fb_activity[row["fb_url"]] = row
        print(f"Facebook activity data: {len(fb_activity)} pages")

    # Collect all unique websites to check
    all_websites = set()
    for entries in company_entries.values():
        for e in entries:
            w = e["website"].strip()
            if w and "facebook.com" not in w:
                all_websites.add(w)

    print(f"Unique websites to check: {len(all_websites)}")

    # Check website liveness
    liveness_cache = load_liveness_cache()
    site_alive = check_sites_parallel(list(all_websites), liveness_cache)

    # Score each company
    scored: list[tuple[int, str, list[str], dict]] = []

    for name, entries in company_entries.items():
        score = 0
        signals = []

        # Website signals
        websites = [e["website"] for e in entries if e["website"] and "facebook.com" not in e["website"]]
        website = websites[0] if websites else ""

        if website:
            if site_alive.get(website, False):
                score += 3
                signals.append("website_live")
            else:
                score -= 2
                signals.append("website_dead")

        # Facebook signals
        fb_url = fb_urls.get(name, "")
        if fb_url:
            score += 1
            signals.append("has_facebook")

            # Facebook activity bonus — only recent posts are strong signals
            fb_info = fb_activity.get(fb_url, {})
            fb_status = fb_info.get("active", "")
            fb_likes = int(fb_info.get("likes", 0))

            if fb_status == "very_active":    # posted in last 6 months
                score += 5
                signals.append("fb_posted_recently")
            elif fb_status == "active":       # posted in last 12 months
                score += 3
                signals.append("fb_posted_this_year")
            elif fb_status == "somewhat":     # posted in last 24 months
                score += 1
                signals.append("fb_posted_2yrs")
            elif fb_status == "dormant":      # no posts in 2+ years
                score -= 2
                signals.append("fb_dormant")
            # "unknown" = no post date found — likes alone mean little
            # no bonus, no penalty

            # Likes only count if we also have post activity
            if fb_status in ("very_active", "active", "somewhat") and fb_likes >= 1000:
                score += 1
                signals.append(f"fb_{fb_likes}_likes")

        # Source signals
        sources = set(e["source"] for e in entries)
        if len(sources) > 1:
            score += 2
            signals.append("multi_source")

        # Phone signals
        phones = [e["phone_normalized"] for e in entries]
        if len(phones) > 1:
            score += 1
            signals.append(f"{len(phones)}_phones")

        has_mobile = any(p.startswith("+9955") for p in phones)
        has_landline = any(not p.startswith("+9955") for p in phones)

        if has_mobile:
            score += 1
            signals.append("has_mobile")
        if has_landline:
            score += 1
            signals.append("has_landline")

        scored.append((score, name, signals, {
            "website": website,
            "facebook": fb_url,
        }))

    # Sort by score descending
    scored.sort(key=lambda x: -x[0])

    # Write output: one row per phone number, sorted by company score
    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        w.writeheader()

        for score, name, signals, extra in scored:
            if score >= 5:
                priority = "A"
            elif score >= 2:
                priority = "B"
            else:
                priority = "C"

            for entry in company_entries[name]:
                w.writerow({
                    "priority": priority,
                    "score": score,
                    "company_name": name,
                    "phone": entry["phone"],
                    "phone_normalized": entry["phone_normalized"],
                    "website": extra["website"],
                    "facebook": extra["facebook"],
                    "source": entry["source"],
                    "signals": "; ".join(signals),
                })

    # Summary
    prio_counts = defaultdict(int)
    prio_companies = defaultdict(int)
    for score, name, signals, _ in scored:
        p = "A" if score >= 5 else ("B" if score >= 2 else "C")
        prio_companies[p] += 1
        prio_counts[p] += len(company_entries[name])

    print(f"\n{'='*60}")
    print(f"Output: {OUTPUT}")
    print(f"\n  Priority | Companies | Phone numbers | Description")
    print(f"  {'─'*55}")
    print(f"  A (5+)   | {prio_companies['A']:>6}    | {prio_counts['A']:>6}        | Call first — strong signals")
    print(f"  B (2-4)  | {prio_companies['B']:>6}    | {prio_counts['B']:>6}        | Good leads")
    print(f"  C (0-1)  | {prio_companies['C']:>6}    | {prio_counts['C']:>6}        | Low signal — try last")
    print(f"  {'─'*55}")
    print(f"  Total    | {len(scored):>6}    | {len(rows):>6}        |")

    # Show top 10
    print(f"\nTop 10 companies to call first:")
    for score, name, signals, extra in scored[:10]:
        phones = [e["phone_normalized"] for e in company_entries[name]]
        print(f"  [{score:>2}] {name[:40]:40s} | {', '.join(phones[:2]):30s} | {'; '.join(signals)}")


if __name__ == "__main__":
    main()
