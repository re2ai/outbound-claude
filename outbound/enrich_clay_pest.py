#!/usr/bin/env python3
"""
Enrich Clay pest control contacts that have no email.
Uses Apollo people/match with name + company + domain.
Input:  ~/Documents/clay_pest_to_enrich.json
Output: ~/Documents/clay_pest_enriched.json
"""
import os, sys, json, time, requests
from dotenv import load_dotenv

load_dotenv(r"C:\Users\evane\Documents\Coding\scorecard\re2scorecard2026\.env")
sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)

APOLLO_KEY = os.getenv("APOLLO_API_KEY")
BASE       = "https://api.apollo.io/v1"
HEADERS    = {"X-Api-Key": APOLLO_KEY, "Content-Type": "application/json"}

INPUT_F  = os.path.expanduser("~/Documents/clay_pest_to_enrich.json")
OUTPUT_F = os.path.expanduser("~/Documents/clay_pest_enriched.json")


def enrich_contact(c):
    payload = {}
    if c.get("full_name"):
        payload["name"] = c["full_name"]
    elif c.get("first_name") or c.get("last_name"):
        payload["name"] = f"{c.get('first_name','')} {c.get('last_name','')}".strip()
    if c.get("company"):
        payload["organization_name"] = c["company"]
    if c.get("domain"):
        payload["domain"] = c["domain"]
    if c.get("linkedin_url"):
        payload["linkedin_url"] = c["linkedin_url"]

    r = requests.post(f"{BASE}/people/match", headers=HEADERS, json=payload, timeout=30)
    if r.status_code == 429:
        print("  Rate limited — sleeping 15s...")
        time.sleep(15)
        r = requests.post(f"{BASE}/people/match", headers=HEADERS, json=payload, timeout=30)
    r.raise_for_status()
    return r.json().get("person") or {}


def main():
    if not APOLLO_KEY:
        print("APOLLO_API_KEY not set"); sys.exit(1)

    with open(INPUT_F) as f:
        contacts = json.load(f)
    print(f"Loaded {len(contacts)} contacts to enrich")

    # Resume from existing output
    already = {}
    if os.path.exists(OUTPUT_F):
        with open(OUTPUT_F) as f:
            existing = json.load(f)
        already = {c["source_name"]: c for c in existing}
        print(f"Resuming: {len(already)} already done")

    output = list(already.values())
    no_email = 0

    to_do = [c for c in contacts if c.get("full_name", c.get("first_name","")) not in already]
    print(f"To enrich: {len(to_do)}")
    print(f"Estimated credits: ~{len(to_do)}")

    for i, c in enumerate(to_do, 1):
        try:
            person = enrich_contact(c)
            email = person.get("email")
            if not email:
                no_email += 1
            else:
                org = person.get("organization") or {}
                output.append({
                    "source_name":   c.get("full_name", ""),
                    "source_company": c.get("company", ""),
                    "apollo_id":     person.get("id"),
                    "first_name":    person.get("first_name", "") or c.get("first_name", ""),
                    "last_name":     person.get("last_name", "") or c.get("last_name", ""),
                    "email":         email,
                    "title":         person.get("title", "") or c.get("title", ""),
                    "company":       org.get("name", "") or c.get("company", ""),
                    "company_name":  org.get("name", "") or c.get("company", ""),
                    "domain":        org.get("primary_domain", "") or c.get("domain", ""),
                    "city":          person.get("city", ""),
                    "state":         person.get("state", ""),
                    "linkedin_url":  person.get("linkedin_url", "") or c.get("linkedin_url", ""),
                    "keyword":       "clay_enriched",
                })
        except Exception as e:
            print(f"  ERROR {c.get('full_name')}: {e}")
            no_email += 1

        if i % 25 == 0 or i == len(to_do):
            with open(OUTPUT_F, "w") as f:
                json.dump(output, f, indent=2)
            print(f"  [{i}/{len(to_do)}] with_email={len(output)} no_email={no_email}")

        time.sleep(0.25)

    with open(OUTPUT_F, "w") as f:
        json.dump(output, f, indent=2)

    total = len(output) + no_email
    print(f"\n=== Done ===")
    print(f"With email: {len(output)}")
    print(f"No email:   {no_email}")
    print(f"Yield:      {len(output)/total*100:.0f}%" if total else "")
    print(f"Saved to:   {OUTPUT_F}")


if __name__ == "__main__":
    main()
