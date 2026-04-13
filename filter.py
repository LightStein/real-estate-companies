#!/usr/bin/env python3
"""
Filter companies.csv to keep only companies likely to buy wood/lumber.

Removes: architects, interior designers, design studios, landscape designers,
         pure consulting/finance firms.
Keeps:   builders, contractors, renovators, developers, material traders,
         and any company whose name also signals building work.
"""

import csv
import re
import sys

INPUT = "companies.csv"
OUTPUT = "companies_builders.csv"
REJECTED = "companies_rejected.csv"
FIELDS = ["company_name", "phone", "phone_normalized", "website", "source"]

# Words that signal the company does NOT buy building materials.
# Matched case-insensitively against company name.
EXCLUDE_PATTERNS = [
    # Architects
    "არქიტექტ",       # architect (Georgian)
    "architect",

    # Design / interior / studios (pure design, not build)
    "დიზაინ",          # design
    "ინტერიერ",        # interior
    "interior",
    "design",

    # Studios (usually design/art, not construction)
    "სტუდი",           # studi(o)
    "studio",

    # Landscape / greening
    "ლანდშაფტ",        # landscape
    "გამწვანებ",        # greening/landscaping

    # Pure finance / investment / brokerage (not developers who build)
    "საინვესტიციო",    # investment (adj.)
    "ინვესტმენტ",      # investment (noun)
    "ფინანს",          # financ(e/ial)
    "financial",
    "საბროკერო",       # brokerage

    # Real estate agents (sell, don't build)
    "რეალტ",           # realt(or/y)
    "ბროკერ",          # broker
    "სააგენტო",        # agency
    "real estate",
]

# Words that signal the company DOES do building/construction work.
# If a company name matches both an exclude AND an include pattern,
# it is KEPT (benefit of the doubt — they build too).
INCLUDE_PATTERNS = [
    # Georgian building-related
    "მშენ",            # build / construction root
    "სამშენებლო",      # construction (adj.)
    "მშენებლობ",       # construction (noun)
    "ბეტონ",           # concrete
    "ცემენტ",          # cement
    "აგურ",            # brick
    "ბლოკ",            # block
    "მეტალ",           # metal
    "ფოლად",           # steel
    "რკინ",            # iron
    "სახურავ",         # roof
    "იატაკ",           # floor
    "კარ-ფანჯ",        # doors-windows
    "ფანჯარ",          # window
    "კარებ",           # doors
    "სანტექნ",         # plumbing
    "ელექტრ",          # electr-
    "კოტეჯ",           # cottage
    "სახლ",            # house
    "შენობ",           # building (noun)
    "მონოლით",         # monolith
    "კარკას",          # frame
    "რემონტ",          # repair/renovation
    "მოპირკეთ",        # finishing
    "თაბაშ",           # plaster/gypsum
    "ხის",             # wooden
    "ხე-ტყ",           # wood-timber
    "საყოფაცხოვრებ",   # household/residential
    "დეველოპმენტ",     # development
    "დეველოპერ",       # developer
    "ქონსთრაქშენ",     # construction (transliterated)

    # English building-related
    "build",
    "construct",
    "concrete",
    "steel",
    "roof",
    "plumb",
    "electr",
    "house",
    "develop",         # developer/development
    "renovation",
    "repair",
]


def should_exclude(name: str) -> bool:
    """Return True if this company should be excluded (non-builder)."""
    nl = name.lower()
    is_excluded = any(p in nl for p in EXCLUDE_PATTERNS)
    if not is_excluded:
        return False
    # Check if it also has building signals → keep it
    is_builder = any(p in nl for p in INCLUDE_PATTERNS)
    return not is_builder


def main():
    kept = 0
    rejected = 0

    with (
        open(INPUT, "r", encoding="utf-8") as fin,
        open(OUTPUT, "w", newline="", encoding="utf-8") as fout,
        open(REJECTED, "w", newline="", encoding="utf-8") as frej,
    ):
        reader = csv.DictReader(fin)
        writer_out = csv.DictWriter(fout, fieldnames=FIELDS)
        writer_rej = csv.DictWriter(frej, fieldnames=FIELDS)
        writer_out.writeheader()
        writer_rej.writeheader()

        for row in reader:
            name = row.get("company_name", "")
            if should_exclude(name):
                writer_rej.writerow(row)
                rejected += 1
            else:
                writer_out.writerow(row)
                kept += 1

    print(f"Kept:     {kept} entries  →  {OUTPUT}")
    print(f"Rejected: {rejected} entries  →  {REJECTED}")
    print(f"\nReview {REJECTED} to make sure nothing good was dropped.")


if __name__ == "__main__":
    main()
