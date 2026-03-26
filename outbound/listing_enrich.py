#!/usr/bin/env python3
"""
listing_enrich.py — Refresh CRE broker listing data via OpenAI web search.

Searches for each individual rep's current active listings by parsing their
name from their email address. One search per contact, not per company.

Scores listings by type preference:
  1 = retail (best for Resquared copy)
  2 = mixed-use
  3 = office
  4 = other / land / multifamily
  5 = industrial / warehouse / flex (worst)

Output: JSON file, one record per input contact row.

Usage:
  python listing_enrich.py --file relaunch_campaign_20260325.csv --out /tmp/listing_test.json [--limit 20]

Resume-safe. Uses ThreadPoolExecutor(max_workers=5).
"""

import os
import sys
import re
import json
import csv
import argparse
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv()

OPENAI_KEY = os.getenv("OPENAI_API_KEY")
MODEL = "gpt-5.4"
MAX_WORKERS = 5

TYPE_SCORE = {
    "retail": 1,
    "mixed-use": 2,
    "office": 3,
    "other": 4,
    "multifamily": 4,
    "land": 4,
    "industrial": 5,
    "warehouse": 5,
    "flex": 5,
}

PROMPT_PASS1 = """I need to find a CURRENTLY LIVE, ACTIVE commercial real estate listing for this broker:

Name: {name}{title_line}
Company: {company}
Website: {domain}{location_line}{type_hint_line}

These people were scraped from LoopNet so they definitely have active listings. Try ALL of the following search strategies until you find one:

1. Search LoopNet by name: site:loopnet.com "{name}"
2. Search LoopNet by company: site:loopnet.com "{company}"
3. Search Crexi: site:crexi.com "{name}" OR site:crexi.com "{company}"
4. Search the company website: site:{domain} listings OR site:{domain} properties
5. Search broadly: "{name}" "{company}" commercial real estate listing for lease
6. Search: "{company}" commercial properties available 2025 OR 2026

The listing MUST be currently active and available — not sold, not closed, not under contract.

Return in this exact format (no extra lines, no markdown):
address: [full property address including city and state]
type: [one of: retail, office, industrial, mixed-use, multifamily, warehouse, flex, land, other]
size: [square footage or acreage]
price: [asking price or rent per SF/yr if available, else "not listed"]
details: [1-2 other key specs — anchor tenants, traffic count, year built, etc. — under 15 words]
date: [listing date, date posted, or last updated if shown anywhere on the listing — else "not found"]
url: [direct URL to the listing page]

Prefer retail, strip mall, or shopping center listings. Office is acceptable too.

If after trying all strategies you truly cannot find any currently active listing, output exactly:
NONE"""

PROMPT_PASS2 = """I'm looking for ANY currently active commercial real estate listing for:

Company: {company}
Website: {domain}{location_line}

They are a commercial real estate firm. Try every angle:

1. Go directly to {domain} and find their properties/listings page
2. Search: site:loopnet.com "{company}"
3. Search: site:crexi.com "{company}"
4. Search: "{company}" available for lease OR for sale commercial
5. Search: "{company}" commercial real estate properties 2025 OR 2026
6. Search the company name with any US city + "available"

The listing MUST be currently active — not sold, not expired, not closed.

I just need ONE listing — any commercial property type is fine. Return in this exact format:
address: [full property address including city and state]
type: [one of: retail, office, industrial, mixed-use, multifamily, warehouse, flex, land, other]
size: [square footage or acreage]
price: [asking price or rent per SF/yr if available, else "not listed"]
details: [1-2 other key specs — under 15 words]
date: [listing date, date posted, or last updated if shown — else "not found"]
url: [direct URL to the listing page]

If you genuinely cannot find any active listing at all, output exactly:
NONE"""


def parse_name_from_email(email: str) -> str:
    """
    Best-effort first+last from email local part.
    john.roberson@  → John Roberson
    bbroadbent@     → B Broadbent
    jmatthew@       → J Matthew
    frank@          → Frank
    """
    local = email.split("@")[0].lower()
    # Remove common prefixes/generic aliases
    if local in ("info", "admin", "contact", "hello", "sales", "office"):
        return ""

    # dot/underscore/hyphen separated → capitalize each word
    if re.search(r"[._-]", local):
        parts = re.split(r"[._-]", local)
        return " ".join(p.capitalize() for p in parts if p)

    # camelCase → split
    split = re.sub(r"([a-z])([A-Z])", r"\1 \2", local)
    if " " in split:
        return split.title()

    # initial+lastname pattern: single letter then 4+ chars (e.g. bbroadbent → B Broadbent)
    m = re.match(r"^([a-z])([a-z]{3,})$", local)
    if m:
        return f"{m.group(1).upper()} {m.group(2).capitalize()}"

    # just capitalize what we have
    return local.capitalize()


def domain_to_company(domain: str) -> str:
    name = domain.split(".")[0]
    name = re.sub(r"[-_]", " ", name)
    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    return name.title()


def parse_type_score(raw_type: str) -> int:
    t = raw_type.lower().strip()
    for key, score in TYPE_SCORE.items():
        if key in t:
            return score
    return 4


def call_openai(prompt: str) -> dict:
    """Single Responses API call. Returns parsed listing dict or {'listing_found': False}."""
    r = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
        json={
            "model": MODEL,
            "tools": [{"type": "web_search_preview"}],
            "input": prompt,
        },
        timeout=120,
    )
    r.raise_for_status()

    text = ""
    for item in r.json().get("output", []):
        if item.get("type") == "message":
            for block in item.get("content", []):
                if block.get("type") == "output_text":
                    text = block.get("text", "").strip()

    # Strip citation markdown
    text = re.sub(r"\s*\(\[.*?\]\(https?://.*?\)\)", "", text)
    text = re.sub(r"\s*\[.*?\]\(https?://.*?\)", "", text)
    text = re.sub(r"\[\d+\]", "", text).strip()

    if not text or text.upper().startswith("NONE"):
        return {"listing_found": False}

    parsed = {}
    for line in text.splitlines():
        for field in ("address", "type", "details", "url"):
            if line.lower().startswith(f"{field}:"):
                parsed[field] = line.split(":", 1)[1].strip()
                break

    if not parsed.get("address"):
        return {"listing_found": False}

    listing_type = parsed.get("type", "other").lower()
    return {
        "listing_found": True,
        "listing_address": parsed.get("address", ""),
        "listing_type": listing_type,
        "listing_type_score": parse_type_score(listing_type),
        "listing_size": parsed.get("size", ""),
        "listing_price": parsed.get("price", ""),
        "listing_details": parsed.get("details", ""),
        "listing_date": parsed.get("date", ""),
        "listing_url": parsed.get("url", ""),
    }


def search_listing(email: str, name: str, company: str, domain: str,
                   location: str = "", contact_title: str = "", property_type_hint: str = "") -> dict:
    title_line = f"\nTitle: {contact_title}" if contact_title else ""
    location_line = f"\nLocation: {location}" if location else ""
    type_hint_line = f"\nProperty type specialty (from their LoopNet profile): {property_type_hint}" if property_type_hint else ""

    # Pass 1: rep-level search
    try:
        result = call_openai(PROMPT_PASS1.format(
            name=name, company=company, domain=domain,
            title_line=title_line, location_line=location_line, type_hint_line=type_hint_line,
        ))
        if result.get("listing_found"):
            result["search_pass"] = 1
            return result
    except Exception:
        pass

    # Pass 2: company-level, any type
    try:
        result = call_openai(PROMPT_PASS2.format(
            company=company, domain=domain, location_line=location_line,
        ))
        if result.get("listing_found"):
            result["search_pass"] = 2
            return result
    except Exception as e:
        return {"listing_found": False, "error": str(e)}

    return {"listing_found": False}


def load_csv(filepath: str) -> list[dict]:
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="Input CSV path")
    parser.add_argument("--out", required=True, help="Output JSON path")
    parser.add_argument("--limit", type=int, default=0, help="Max contacts to process (0 = all)")
    parser.add_argument("--stages", nargs="+", default=[], help="Filter by funnel_stage values (space-separated)")
    args = parser.parse_args()

    if not OPENAI_KEY:
        print("OPENAI_API_KEY not set")
        sys.exit(1)

    rows = load_csv(args.file)
    print(f"Loaded {len(rows)} contacts")

    # Build contact records
    contacts = []
    for row in rows:
        email = (row.get("email") or "").strip().lower()
        if not email:
            continue
        domain = (row.get("domain") or "").strip().lower()
        company = (row.get("company_name") or "").strip() or domain_to_company(domain)
        # Prefer real name from CSV, fall back to email parsing
        name = (row.get("contact_name") or "").strip() or parse_name_from_email(email)
        city = (row.get("city") or "").strip()
        state = (row.get("state") or "").strip()
        location = f"{city}, {state}".strip(", ") if city or state else ""
        contacts.append({
            "email": email,
            "domain": domain,
            "company": company,
            "name": name,
            "location": location,
            "contact_title": (row.get("contact_title") or "").strip(),
            "property_type_hint": (row.get("property_type") or "").strip(),
            **{k: row.get(k, "") for k in ("segment_master", "segment_sub", "stage", "funnel_stage")},
        })

    if args.stages:
        before = len(contacts)
        contacts = [c for c in contacts if c.get("funnel_stage") in args.stages]
        print(f"Filtered to stages {args.stages}: {len(contacts)} of {before} contacts")

    if args.limit:
        contacts = contacts[: args.limit]
        print(f"Limiting to {args.limit} contacts for this run")

    # Resume: skip already-done
    already_done = {}
    if os.path.exists(args.out):
        with open(args.out) as f:
            existing = json.load(f)
        already_done = {c["email"]: c for c in existing if c.get("email")}
        print(f"Resuming: {len(already_done)} already enriched")

    to_process = [c for c in contacts if c["email"] not in already_done]
    total = len(to_process)
    print(f"Searching listings for {total} contacts (model={MODEL}, workers={MAX_WORKERS})...\n")

    output = list(already_done.values())
    found = 0
    type_counts = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(
                search_listing, c["email"], c["name"], c["company"], c["domain"],
                c.get("location", ""), c.get("contact_title", ""), c.get("property_type_hint", "")
            ): c
            for c in to_process
        }
        completed = 0
        for future in as_completed(futures):
            contact = futures[future]
            completed += 1
            try:
                result = future.result()
            except Exception as e:
                result = {"listing_found": False, "error": str(e)}

            record = {**contact, **result}
            output.append(record)

            if result.get("listing_found"):
                found += 1
                t = result.get("listing_type", "other")
                type_counts[t] = type_counts.get(t, 0) + 1
                score = result.get("listing_type_score", 4)
                score_label = {1: "RETAIL", 2: "MIXED-USE", 3: "OFFICE", 4: "other", 5: "INDUSTRIAL"}.get(score, "?")
                p = f"p{result.get('search_pass', '?')}"
                print(
                    f"  [{completed}/{total}] FOUND [{score_label}][{p}] {contact['name']} @ {contact['company']}: "
                    f"{result.get('listing_address', '')}"
                )
            else:
                print(f"  [{completed}/{total}] none   {contact['name']} @ {contact['company']}")

            if completed % 10 == 0 or completed == total:
                with open(args.out, "w") as f:
                    json.dump(output, f, indent=2)

    with open(args.out, "w") as f:
        json.dump(output, f, indent=2)

    # Write CSV
    csv_out = str(Path(args.out).with_suffix(".csv"))
    csv_cols = [
        "email", "name", "contact_title", "domain", "company", "location",
        "property_type_hint", "segment_master", "segment_sub", "stage", "funnel_stage",
        "listing_found", "listing_type", "listing_type_score", "search_pass",
        "listing_address", "listing_size", "listing_price", "listing_details",
        "listing_date", "listing_url",
    ]
    with open(csv_out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(output)

    hit_rate = found / total * 100 if total else 0
    print(f"\n{'='*60}")
    print(f"Results: {found}/{total} listings found ({hit_rate:.0f}% hit rate)")
    print(f"Type breakdown: {json.dumps(type_counts, indent=2)}")
    print(f"JSON: {args.out}")
    print(f"CSV:  {csv_out}")

    found_records = [r for r in output if r.get("listing_found")]
    found_records.sort(key=lambda x: x.get("listing_type_score", 99))
    print(f"\nSample results (best listings first):")
    for r in found_records[:10]:
        score_label = {1: "RETAIL", 2: "MIXED-USE", 3: "OFFICE", 4: "other", 5: "INDUSTRIAL"}.get(
            r.get("listing_type_score", 4), "?"
        )
        print(f"\n  [{score_label}] {r['name']} @ {r['company']} ({r['domain']})")
        print(f"    Address: {r.get('listing_address', '')}")
        print(f"    Size:    {r.get('listing_size', '')}")
        print(f"    Price:   {r.get('listing_price', '')}")
        print(f"    Details: {r.get('listing_details', '')}")
        print(f"    Date:    {r.get('listing_date', '')}")
        print(f"    URL:     {r.get('listing_url', '')}")


if __name__ == "__main__":
    main()
