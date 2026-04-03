#!/usr/bin/env python3
"""
Generate email copy for PLG - HVAC - Email - DataDriven - Access - v1.

Reads hvac_verified.json, queries BQ for city business counts,
outputs hvac_emails.json with all custom fields per contact.

All emails stored as plain text with \\n line breaks — NO HTML, NO links.
<br> conversion happens ONLY at SmartLead load time.

Usage:
  python generate_hvac_emails.py \
    --file C:/Users/evane/Documents/hvac_verified.json \
    --out  C:/Users/evane/Documents/hvac_emails.json
"""

import os
import json
import argparse
from dotenv import load_dotenv

load_dotenv()

try:
    from google.cloud import bigquery
    bq = bigquery.Client(project="tenant-recruitin-1575995920662")
except Exception as e:
    print(f"BigQuery init failed: {e}")
    bq = None

# ── Business count logic (Step 6G) ─────────────────────────────────────────────

BREAKPOINTS = [
    50, 100, 150, 200, 250, 300, 400, 500, 750, 1000, 1500, 2000, 2500, 3000,
    5000, 7500, 10000, 15000, 20000, 25000, 30000, 50000, 75000, 100000,
    150000, 200000, 250000, 300000, 500000
]

def friendly_count(n):
    if not n or n <= 0:
        return None
    floor_bp = max((b for b in BREAKPOINTS if b <= n), default=None)
    ceil_bp  = min((b for b in BREAKPOINTS if b > n),  default=None)
    if floor_bp is None:
        return None
    if ceil_bp and n / ceil_bp >= 0.97:
        return f"almost {ceil_bp:,}"
    return f"over {floor_bp:,}"


def fetch_city_counts(cities):
    """Query BQ for business counts per city. Returns dict {city_lower: count}."""
    if not bq or not cities:
        return {}
    cities_clean = [c for c in cities if c and c != "your area"]
    if not cities_clean:
        return {}
    query = """
        SELECT city, COUNT(*) as cnt
        FROM `tenant-recruitin-1575995920662.business_sources.us_companies_list__30m_us_business_std`
        WHERE city IN UNNEST(@cities)
        GROUP BY city
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("cities", "STRING", cities_clean)]
    )
    rows = bq.query(query, job_config=job_config).result()
    return {row["city"].lower(): row["cnt"] for row in rows}


# ── Email templates ─────────────────────────────────────────────────────────────

def resolve_city(contact):
    city = (contact.get("city") or "").strip()
    if not city:
        city = (contact.get("company_city") or "").strip()
    return city or "your area"


def build_emails(contact, city, businesses):
    first_name = (contact.get("first_name") or "").strip()
    greeting   = first_name if first_name else "Hi"

    subject1 = "commercial HVAC x local offices"
    subject3 = f"HVAC contacts in {city}"

    email1 = (
        f"Hi {first_name}, do you sell commercial HVAC to offices and restaurants in {city}?\n\n"
        f"We have contact info for {businesses} in {city} you can email on autopilot.\n\n"
        f"If it's something of interest, I can send you a link to test it out for free."
    )

    email2 = (
        f"I ran a quick search in {city} this morning.\n\n"
        f"Made a list of {businesses} that look like they could use your HVAC services.\n\n"
        f"Want me to send you the link to take a look?"
    )

    email3 = (
        f"{greeting}, what type of commercial clients are you targeting in {city} -- "
        f"offices, restaurants, or both?\n\n"
        f"We have a free trial you can test out -- just let me know and I'll send the link."
    )

    return subject1, subject3, email1, email2, email3


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--out",  required=True)
    args = parser.parse_args()

    with open(args.file, encoding="utf-8", errors="ignore") as f:
        raw = f.read()
    # Strip control characters that break JSON parsing
    import re
    raw = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', raw)
    contacts = json.loads(raw)
    print(f"Loaded {len(contacts)} contacts from {args.file}")

    # Collect unique cities and fetch BQ counts in one query
    cities = list(set(resolve_city(c) for c in contacts))
    print(f"Fetching BQ business counts for {len(cities)} unique cities...")
    city_counts = fetch_city_counts(cities)
    print(f"  Got counts for {len(city_counts)} cities")

    results = []
    no_city = 0
    for contact in contacts:
        city = resolve_city(contact)
        if city == "your area":
            no_city += 1

        raw_count = city_counts.get(city.lower())
        if raw_count:
            businesses = "over 50,000 businesses" if raw_count > 30000 else f"{raw_count:,} businesses"
        else:
            businesses = "thousands of businesses"

        s1, s3, e1, e2, e3 = build_emails(contact, city, businesses)

        results.append({
            **contact,
            "city_resolved": city,
            "businesses_str": businesses,
            "Subject1": s1,
            "Subject3": s3,
            "Email1":   e1,
            "Email2":   e2,
            "Email3":   e3,
        })

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\nGenerated {len(results)} contacts")
    print(f"  No city fallback: {no_city}")
    print(f"  BQ count resolved: {len(results) - no_city}")
    print(f"Saved to: {args.out}")

    # Spot-check 3 samples
    print("\n--- Spot check (3 samples) ---")
    for c in results[:3]:
        print(f"\n{c['first_name']} {c.get('last_name','')} | {c.get('company_name','')} | {c['city_resolved']}")
        print(f"Subject1: {c['Subject1']}")
        print(f"Email1:\n{c['Email1']}")
        print(f"Email2:\n{c['Email2']}")
        print(f"Subject3: {c['Subject3']}")
        print(f"Email3:\n{c['Email3']}")


if __name__ == "__main__":
    main()
