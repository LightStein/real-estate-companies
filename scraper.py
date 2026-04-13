#!/usr/bin/env python3
"""
Georgian Construction Company Phone Number Scraper

Scrapes company names, phone numbers, and websites from Georgian business
directories. Saves results incrementally to CSV with deduplication by phone.

Working sources:
  1. yell.ge  - Yellow pages directory, category 339 (სამშენებლო კომპანიები)
  2. bia.ge   - Business Information Agency, subcategory 2568

Sites tested but not scrapable:
  - info.ge: "Coming Soon" placeholder
  - pages.ge: Consistently times out
  - companyinfo.ge: Registry data only (no phone numbers)
  - 2gis.ge: CAPTCHA anti-bot protection
  - myhome.ge: Cloudflare anti-bot protection
  - ss.ge/services.ss.ge: SPA with no accessible endpoints
"""

import csv
import os
import re
import random
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CSV_FILE = "companies.csv"
CSV_FIELDS = ["company_name", "phone", "phone_normalized", "website", "source"]
DELAY_MIN, DELAY_MAX = 1, 3

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
]

# Domains to skip when extracting company websites
_SKIP_DOMAINS = {
    "yell.ge", "bia.ge", "facebook.com", "google.com", "instagram.com",
    "fontawesome.com", "cloudflare.com", "googleapis.com",
    "cdnjs.cloudflare.com", "twitter.com", "youtube.com", "linkedin.com",
    "follower.ge",  # bia.ge analytics tracker, not a company website
}

# ---------------------------------------------------------------------------
# Phone normalization
# ---------------------------------------------------------------------------


def normalize_phone(raw: str) -> str:
    """Normalize a Georgian phone number to +995XXXXXXXXX format."""
    digits = re.sub(r"[^\d]", "", raw)

    # Already international format +995XXXXXXXXX
    if digits.startswith("995") and len(digits) >= 12:
        return f"+{digits[:12]}"

    # 9-digit mobile: 5XX XX XX XX
    if len(digits) == 9 and digits.startswith("5"):
        return f"+995{digits}"

    # 9-digit Tbilisi landline: 322XXXXXX
    if len(digits) == 9 and digits.startswith("32"):
        return f"+995{digits}"

    # 7-digit Tbilisi landline (old format): 2XXXXXX
    if len(digits) == 7 and digits.startswith("2"):
        return f"+99532{digits}"

    # 6-digit Tbilisi local
    if len(digits) == 6:
        return f"+99532{digits}"

    # 10 digit with leading 0: 032XXXXXXX or 0XXXXXXXXX
    if len(digits) == 10 and digits.startswith("0"):
        return f"+995{digits[1:]}"

    # Partial country code
    if digits.startswith("995"):
        return f"+{digits}"

    # Generic local number
    if 6 <= len(digits) <= 9:
        return f"+995{digits}"

    return raw.strip()


def split_phones(text: str) -> list[str]:
    """Split a string that may contain multiple phone numbers."""
    text = text.replace(";", ",").replace("/", ",").replace("|", ",")
    phones = []
    for p in text.split(","):
        p = p.strip()
        if p and re.search(r"\d{5,}", re.sub(r"[^\d]", "", p)):
            phones.append(p)
    return phones


# ---------------------------------------------------------------------------
# CSV management (incremental save + dedup)
# ---------------------------------------------------------------------------


class CompanyStore:
    """Manages CSV writing and deduplication by normalized phone number."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.seen_phones: set[str] = set()
        self.total_saved = 0
        self._load_existing()

    def _load_existing(self):
        if not os.path.exists(self.filepath):
            with open(self.filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
                writer.writeheader()
            return

        with open(self.filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                norm = row.get("phone_normalized", "")
                if norm:
                    self.seen_phones.add(norm)
                    self.total_saved += 1

        print(f"  Loaded {self.total_saved} existing entries from {self.filepath}")

    def add(self, company_name: str, phone: str, website: str, source: str) -> bool:
        """Add a single phone entry. Returns True if new (not duplicate)."""
        norm = normalize_phone(phone)
        if norm in self.seen_phones:
            return False

        self.seen_phones.add(norm)
        self.total_saved += 1

        with open(self.filepath, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writerow({
                "company_name": company_name.strip(),
                "phone": phone.strip(),
                "phone_normalized": norm,
                "website": website.strip() if website else "",
                "source": source,
            })
        return True

    def add_company(self, name: str, phones: list[str], website: str, source: str) -> int:
        """Add a company with potentially multiple phones. Returns new entries added."""
        added = 0
        for phone in phones:
            if self.add(name, phone, website, source):
                added += 1
        return added


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def get_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ka-GE,ka;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    })
    return session


def fetch(session: requests.Session, url: str, timeout: int = 30) -> requests.Response | None:
    """Fetch a URL with rotating user agent and random delay."""
    session.headers["User-Agent"] = random.choice(USER_AGENTS)
    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

    try:
        resp = session.get(url, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        return resp
    except requests.RequestException as e:
        print(f"    [ERROR] {url}: {e}")
        return None


def soup_from(resp: requests.Response) -> BeautifulSoup:
    resp.encoding = "utf-8"
    return BeautifulSoup(resp.text, "html.parser")


def _extract_website(soup_scope, skip_domains: set[str] = _SKIP_DOMAINS) -> str:
    """Find the first external website link in a BeautifulSoup scope."""
    for a in soup_scope.find_all("a", href=True):
        href = a["href"]
        if href.startswith("http") and not any(d in href for d in skip_domains):
            return href
    return ""


# ===================================================================
# Site 1: yell.ge
# ===================================================================


def scrape_yell_ge(store: CompanyStore):
    """Scrape construction companies from yell.ge category 339.

    Page 1 uses companies.php?lan=geo&rub=339.
    Pages 2+ use search.php with SR_pg parameter (form-based pagination).
    Each page has ~25 company cards in SR_div_{id} containers.
    """
    print("\n" + "=" * 60)
    print("SCRAPING: yell.ge (სამშენებლო კომპანიები)")
    print("=" * 60)

    base = "https://www.yell.ge"
    session = get_session()
    total_new = 0

    # Page 1 — also discover total page count
    first_url = f"{base}/companies.php?lan=geo&rub=339"
    print(f"\n  Page 1: {first_url}")
    resp = fetch(session, first_url)
    if not resp:
        print("  Failed to fetch yell.ge, skipping")
        return

    soup = soup_from(resp)
    page_match = re.search(r"გვერდი:\s*(\d+)\s*\((\d+)\)", soup.get_text())
    total_pages = int(page_match.group(2)) if page_match else 1
    print(f"  Total pages: {total_pages}")

    page_new = _parse_yell_listing(soup, store)
    total_new += page_new
    print(f"  Page 1 done: +{page_new} new | Total: {store.total_saved}")

    # Pages 2+
    for pg in range(2, total_pages + 1):
        url = (f"{base}/search.php?file=companies&rub=339&lan=geo&S_lan=geo"
               f"&s_b=1&o_b_n=0&sh_o_m=0&SR_pg={pg}&sort=PR&filter=0000000")
        print(f"\n  Page {pg}/{total_pages}")
        resp = fetch(session, url)
        if not resp:
            print(f"  Failed page {pg}, stopping yell.ge")
            break

        soup = soup_from(resp)
        pm = re.search(r"გვერდი:\s*(\d+)\s*\((\d+)\)", soup.get_text())
        if pm and int(pm.group(1)) != pg:
            print(f"  Server returned page {pm.group(1)} instead of {pg}, stopping")
            break

        page_new = _parse_yell_listing(soup, store)
        total_new += page_new
        print(f"  Page {pg} done: +{page_new} new | Total: {store.total_saved}")

    print(f"\nyell.ge complete: {total_new} new companies added")


def _parse_yell_listing(soup: BeautifulSoup, store: CompanyStore) -> int:
    """Extract companies from a yell.ge listing page.

    Each company lives inside <div id="SR_div_{id}"> with:
      - Name in <a href="company.php?...id={id}">Name</a>
      - Phone in <div class="tel_font_companies">ტელ: ...</div>
      - Website in external <a> links
    """
    new_count = 0
    for container in soup.find_all("div", id=re.compile(r"^SR_div_\d+")):
        cid = container["id"].replace("SR_div_", "")

        # Company name
        name = ""
        for a in container.find_all("a", href=re.compile(r"company\.php.*id=" + cid)):
            t = a.get_text(strip=True)
            if t and len(t) > 1:
                name = t
                break
        if not name:
            continue

        # Phone numbers
        tel_div = container.find("div", class_="tel_font_companies")
        if not tel_div:
            continue
        tel_text = re.sub(r"^ტელ:\s*", "", tel_div.get_text(strip=True))
        phones = split_phones(tel_text)
        if not phones:
            continue

        # Website
        website = _extract_website(container)

        new_count += store.add_company(name, phones, website, "yell.ge")

    return new_count


# ===================================================================
# Site 2: bia.ge
# ===================================================================


def scrape_bia_ge(store: CompanyStore):
    """Scrape construction companies from bia.ge.

    Uses Industry subcategory 2568 (სამშენებლო კომპანიები) under category 64
    (Construction). ~3,700 companies.

    Phase 1: Collect company names + detail URLs from paginated listings (500/page).
    Phase 2: Visit each detail page to extract tel: links for phone numbers.
    """
    print("\n" + "=" * 60)
    print("SCRAPING: bia.ge (სამშენებლო კომპანიები)")
    print("=" * 60)

    base = "http://www.bia.ge"
    session = get_session()
    total_new = 0
    page_size = 500

    # Phase 1: collect company entries from listing pages
    entries: list[tuple[str, str]] = []  # (name, detail_url)
    pg = 1
    while True:
        url = (f"{base}/Company/Industry/2568?ServiceCategoryId=64"
               f"&Filter.PageNumber={pg}&Filter.PageLimit={page_size}")
        print(f"\n  Listing page {pg} (up to {page_size} per page)...")
        resp = fetch(session, url)
        if not resp:
            break

        soup = soup_from(resp)
        cards = soup.find_all("li", class_="list-row-box")
        if not cards:
            break

        for card in cards:
            a = card.find("a", class_="title")
            if a:
                name = a.get_text(strip=True)
                href = a.get("href", "")
                if name and href:
                    entries.append((name, base + href))

        # Total from pagination footer
        pag_div = soup.find("div", class_="paging-info")
        m = re.search(r"სულ:\s*([\d,]+)\s*კომპანია", pag_div.get_text() if pag_div else "")
        total = int(m.group(1).replace(",", "")) if m else 0
        print(f"  +{len(cards)} companies (collected {len(entries)}/{total})")

        if len(entries) >= total or len(cards) < page_size:
            break
        pg += 1

    print(f"\n  Collected {len(entries)} companies. Fetching detail pages for phone numbers...")

    # Phase 2: detail pages
    for i, (name, detail_url) in enumerate(entries):
        if i % 50 == 0:
            print(f"  [{i + 1}/{len(entries)}] {name}")

        resp = fetch(session, detail_url)
        if not resp:
            continue

        soup = soup_from(resp)

        # Primary: tel: href links (most reliable)
        phones = []
        for a in soup.find_all("a", href=re.compile(r"^tel:")):
            phone = a["href"].replace("tel:", "").strip()
            # Skip bia.ge's own support number
            if phone and phone != "+995322195555":
                phones.append(phone)

        # Fallback: +995 patterns in page text
        if not phones:
            for m in re.findall(r"\+995\s*\d[\d\s\-]{7,}", soup.get_text()):
                clean = m.strip()
                if "+995 32 219 55 55" not in clean:
                    phones.append(clean)

        website = _extract_website(soup)

        if phones:
            added = store.add_company(name, phones, website, "bia.ge")
            total_new += added

        if (i + 1) % 100 == 0:
            print(f"  Progress: {i + 1}/{len(entries)} | +{total_new} new | Total: {store.total_saved}")

    print(f"\nbia.ge complete: {total_new} new companies added")


# ===================================================================
# Main
# ===================================================================


def main():
    print("Georgian Construction Company Phone Number Scraper")
    print("=" * 60)
    print(f"Output file: {CSV_FILE}")
    print(f"Delay between requests: {DELAY_MIN}-{DELAY_MAX}s")

    store = CompanyStore(CSV_FILE)

    scrapers = [
        ("yell.ge", scrape_yell_ge),
        ("bia.ge", scrape_bia_ge),
    ]

    for site, fn in scrapers:
        try:
            fn(store)
        except Exception as e:
            print(f"\n  [ERROR] {site} crashed: {e}")
            import traceback
            traceback.print_exc()
            print(f"  Skipping {site}, continuing...")

    print("\n" + "=" * 60)
    print(f"DONE! Total unique phone numbers: {store.total_saved}")
    print(f"Results saved to: {CSV_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    main()
