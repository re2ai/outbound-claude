#!/usr/bin/env python3
"""
Phase 1 — Apollo free discovery + enrichment for PLG - Pest Control.

Step 1A: Free api_search (no credits) across multiple keywords.
          Saves all candidate IDs to ~/Documents/pest_control_candidates.json.

Step 1B: Enrich (1 credit/contact) via people/match.
          Saves to ~/Documents/pest_control_enriched.json.

Usage:
  # Step 1A — free discovery only (run first, review TAM):
  python apollo_pest_control.py --step discover

  # Step 1B — enrich (spend credits, run after reviewing discovery results):
  python apollo_pest_control.py --step enrich

  # Both in sequence:
  python apollo_pest_control.py --step all

Rate limits: 50 req/min, 200/hr, 600/24hr.
Apollo Basic plan: 2,500 credits/month at $59/mo.
"""

import os
import sys
import json
import time
import argparse
import requests
from dotenv import load_dotenv

load_dotenv(r"C:\Users\evane\Documents\Coding\scorecard\re2scorecard2026\.env")

APOLLO_KEY   = os.getenv("APOLLO_API_KEY")
CANDIDATES_F = os.path.expanduser("~/Documents/pest_control_candidates.json")
ENRICHED_F   = os.path.expanduser("~/Documents/pest_control_enriched.json")

BASE = "https://api.apollo.io/v1"
HEADERS = {"X-Api-Key": APOLLO_KEY, "Content-Type": "application/json"}

KEYWORDS = [
    "pest control",
    "exterminator",
    "pest management",
]

TITLES = [
    "owner", "founder", "president", "CEO", "managing director",
    "principal", "co-founder", "operator",
]

# National chains to exclude (company name contains any of these)
EXCLUDE_BRANDS = {
    "terminix", "orkin", "rollins", "rentokil", "servicemaster",
    "ehrlich", "arrow exterminators", "western exterminator",
    "anticimex", "massey services", "cook's pest",
}


def apollo_search_page(keyword, page):
    payload = {
        "person_titles": TITLES,
        "organization_num_employees_ranges": ["1,50"],
        "organization_locations": ["United States"],
        "q_keywords": keyword,
        "per_page": 100,
        "page": page,
        "has_email": True,
    }
    r = requests.post(f"{BASE}/mixed_people/api_search", headers=HEADERS, json=payload, timeout=30)
    if r.status_code == 429:
        print("  Rate limited — sleeping 15s...")
        time.sleep(15)
        r = requests.post(f"{BASE}/mixed_people/api_search", headers=HEADERS, json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()
    people = data.get("people", [])
    total  = data.get("pagination", {}).get("total_entries", 0)
    return people, total


def is_excluded(contact):
    company = (contact.get("organization", {}) or {}).get("name", "") or ""
    company_lower = company.lower()
    return any(brand in company_lower for brand in EXCLUDE_BRANDS)


def discover():
    """Phase 1A — free api_search across all keywords. No credits spent."""
    seen_ids = set()
    all_candidates = []

    # Resume: load existing if present
    if os.path.exists(CANDIDATES_F):
        with open(CANDIDATES_F) as f:
            existing = json.load(f)
        seen_ids = {c["id"] for c in existing}
        all_candidates = existing
        print(f"Resuming: {len(all_candidates)} candidates already saved.")

    for keyword in KEYWORDS:
        print(f"\n--- Keyword: '{keyword}' ---")
        page = 1
        keyword_new = 0

        while True:
            people, total = apollo_search_page(keyword, page)
            if not people:
                break

            new_this_page = 0
            for p in people:
                pid = p.get("id")
                if not pid or pid in seen_ids:
                    continue
                if is_excluded(p):
                    continue
                seen_ids.add(pid)
                all_candidates.append({
                    "id":         pid,
                    "first_name": p.get("first_name", ""),
                    "title":      p.get("title", ""),
                    "company":    (p.get("organization") or {}).get("name", ""),
                    "has_email":  p.get("has_email", False),
                    "keyword":    keyword,
                })
                new_this_page += 1

            keyword_new += new_this_page
            print(f"  Page {page}: {len(people)} results, {new_this_page} new unique -> total {len(all_candidates)}")

            # Save after every page
            with open(CANDIDATES_F, "w") as f:
                json.dump(all_candidates, f, indent=2)

            if len(people) < 100:
                break  # last page
            page += 1
            time.sleep(1.2)  # stay under 50 req/min

        print(f"  Keyword '{keyword}': {keyword_new} new candidates")

    print(f"\n=== Discovery complete ===")
    print(f"Total unique candidates: {len(all_candidates)}")
    print(f"Saved to: {CANDIDATES_F}")

    # Summary
    has_email = sum(1 for c in all_candidates if c.get("has_email"))
    print(f"has_email=True: {has_email} ({has_email/len(all_candidates)*100:.0f}%)" if all_candidates else "")

    return all_candidates


def enrich(candidates):
    """Phase 1B — people/match enrichment (1 credit per contact)."""
    # Load already-enriched
    already_done = {}
    if os.path.exists(ENRICHED_F):
        with open(ENRICHED_F) as f:
            existing = json.load(f)
        already_done = {c["apollo_id"]: c for c in existing if c.get("email")}
        print(f"Resuming: {len(already_done)} already enriched with email.")

    # Only enrich has_email=True candidates not yet done
    to_enrich = [
        c for c in candidates
        if c.get("has_email") and c["id"] not in already_done
    ]
    print(f"\nEnriching {len(to_enrich)} candidates (has_email=True, not yet done)...")
    print(f"Estimated credits: ~{len(to_enrich)} | Estimated with email: ~{int(len(to_enrich)*0.68)}")

    output = list(already_done.values())
    no_email = 0

    for i, candidate in enumerate(to_enrich, 1):
        try:
            r = requests.post(
                f"{BASE}/people/match",
                headers=HEADERS,
                json={"id": candidate["id"]},
                timeout=30,
            )
            if r.status_code == 429:
                print(f"  Rate limited at {i} — sleeping 15s...")
                time.sleep(15)
                r = requests.post(
                    f"{BASE}/people/match",
                    headers=HEADERS,
                    json={"id": candidate["id"]},
                    timeout=30,
                )
            r.raise_for_status()
            person = r.json().get("person", {}) or {}

            email = person.get("email")
            if not email:
                no_email += 1
                continue

            org = person.get("organization") or {}
            output.append({
                "apollo_id":    candidate["id"],
                "first_name":   person.get("first_name", ""),
                "last_name":    person.get("last_name", ""),
                "email":        email,
                "title":        person.get("title", ""),
                "company":      org.get("name", "") or person.get("organization_name", ""),
                "company_name": org.get("name", "") or person.get("organization_name", ""),
                "domain":       org.get("primary_domain", ""),
                "city":         person.get("city", ""),
                "state":        person.get("state", ""),
                "linkedin_url": person.get("linkedin_url", ""),
                "keyword":      candidate.get("keyword", ""),
            })

        except Exception as e:
            print(f"  ERROR {candidate['id']}: {e}")
            no_email += 1

        if i % 25 == 0 or i == len(to_enrich):
            with open(ENRICHED_F, "w") as f:
                json.dump(output, f, indent=2)
            print(f"  [{i}/{len(to_enrich)}] with_email={len(output)} no_email={no_email}")

        time.sleep(0.25)  # ~4/sec, well under 50/min

    with open(ENRICHED_F, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n=== Enrichment complete ===")
    print(f"Total with email: {len(output)}")
    print(f"No email returned: {no_email}")
    print(f"Yield: {len(output)/(len(output)+no_email)*100:.0f}%" if (len(output)+no_email) > 0 else "")
    print(f"Saved to: {ENRICHED_F}")
    return output


def main():
    if not APOLLO_KEY:
        print("APOLLO_API_KEY not set"); sys.exit(1)

    parser = argparse.ArgumentParser()
    parser.add_argument("--step", choices=["discover", "enrich", "all"], required=True)
    args = parser.parse_args()

    if args.step in ("discover", "all"):
        candidates = discover()
    else:
        if not os.path.exists(CANDIDATES_F):
            print(f"No candidates file found at {CANDIDATES_F}. Run --step discover first.")
            sys.exit(1)
        with open(CANDIDATES_F) as f:
            candidates = json.load(f)
        print(f"Loaded {len(candidates)} candidates from {CANDIDATES_F}")

    if args.step in ("enrich", "all"):
        enrich(candidates)


if __name__ == "__main__":
    main()
