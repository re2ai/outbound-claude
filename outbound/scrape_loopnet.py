#!/usr/bin/env python3
"""
scrape_loopnet.py — Scrape LoopNet listing data for CRE enrichment.

Architecture: Hyperbrowser Fetch API with stealth="ultra".
This bypasses Akamai Enterprise WAF at the TLS fingerprint level.
No browser agents, no Playwright CDP, no profiles needed for public listing data.

Tested 2026-04-16: 579 results from Miami retail, full page content returned.

Full approach documented in: HYPERBROWSER_SKILL.md § Section 2 & § Section 11

Usage:
  python outbound/scrape_loopnet.py --city "Miami, FL" --limit 20
  python outbound/scrape_loopnet.py --city "Memphis, TN" --type office --limit 50
  python outbound/scrape_loopnet.py --city "Atlanta, GA" --pages 3
"""

import os
import re
import json
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from hyperbrowser import Hyperbrowser
from hyperbrowser.models.web.fetch import FetchParams
from hyperbrowser.models.web.common import (
    FetchBrowserOptions,
    FetchNavigationOptions,
    FetchBrowserLocationOptions,
    FetchOutputOptions,
)

HB_API_KEY = os.getenv("HYPERBROWSER_API_KEY")
client = Hyperbrowser(api_key=HB_API_KEY)

# Output paths
OUT_DIR = Path("/tmp/loopnet")
OUT_DIR.mkdir(exist_ok=True)


# ─── BigQuery output schema ────────────────────────────────────────────────────
# Target table: SLG_OUTBOUND.LOOPNET_LISTINGS
BQ_SCHEMA = {
    "listing_id":       "STRING",
    "url":              "STRING",
    "address":          "STRING",
    "city":             "STRING",
    "state":            "STRING",
    "zip":              "STRING",
    "property_type":    "STRING",
    "sqft_available":   "STRING",
    "asking_rent":      "STRING",
    "broker_names":     "STRING",     # comma-separated
    "broker_company":   "STRING",
    "property_name":    "STRING",
    "scraped_at":       "TIMESTAMP",
}


# ─── URL builder ────────────────────────────────────────────────────────────────
def build_search_url(city: str, property_type: str = "retail", page: int = 1) -> str:
    """
    Build LoopNet search URL.

    Pattern: https://www.loopnet.com/search/{type}-space/{city-slug}/for-lease/{page}/
    Confirmed working URL patterns (2026-04-16):
      - /search/retail-space/miami-fl/for-lease/
      - /search/office-space/memphis-tn/for-lease/2/
    """
    city_slug = city.lower().replace(", ", "-").replace(" ", "-")
    type_slug = property_type.lower().replace(" ", "-")
    url = f"https://www.loopnet.com/search/{type_slug}-space/{city_slug}/for-lease/"
    if page > 1:
        url += f"{page}/"
    return url


# ─── Fetch a single page ────────────────────────────────────────────────────────
def fetch_page(url: str, state: str = "FL") -> str | None:
    """
    Fetch a single LoopNet page using the Fetch API with stealth="ultra".
    Returns markdown content or None on failure.
    """
    result = client.web.fetch(FetchParams(
        url=url,
        stealth="ultra",
        browser=FetchBrowserOptions(
            solve_captchas=True,
            location=FetchBrowserLocationOptions(country="US", state=state),
        ),
        navigation=FetchNavigationOptions(
            wait_until="networkidle",
            timeout_ms=30000,
        ),
        outputs=FetchOutputOptions(markdown=True),
    ))

    if result.status != "completed" or result.error:
        print(f"  Fetch failed: {result.status} — {result.error}")
        return None

    md = result.data.markdown if result.data else None
    if not md or len(md) < 500:
        print(f"  Suspiciously short response ({len(md or '')} chars)")
        return None

    # Check for Akamai block in content
    if "access denied" in (md or "").lower():
        print("  BLOCKED: Access Denied in response")
        return None

    return md


# ─── Parse listings from markdown ────────────────────────────────────────────────
def parse_listings(md: str) -> list[dict]:
    """
    Extract listing data from LoopNet search results page markdown.

    LoopNet markdown structure (each listing):
      #### [STREET ADDRESS](https://www.loopnet.com/Listing/slug/ID/ "...")
      ###### [BUILDING NAME](url)   -- optional
      #### [X,XXX SF TYPE Available](url)
      ###### [CITY, ST ZIP](url)
      ...broker info, price, description...
    """
    # Find all unique listing IDs and their positions
    listing_pattern = r'https://www\.loopnet\.com/Listing/([^/]+)/(\d+)/'
    seen_ids = {}
    for m in re.finditer(listing_pattern, md):
        lid = m.group(2)
        if lid not in seen_ids:
            seen_ids[lid] = m.start()

    listings = []
    sorted_entries = sorted(seen_ids.items(), key=lambda x: x[1])

    for lid, pos in sorted_entries:
        block = md[max(0, pos - 200):pos + 1500]

        # Address: #### [123 Street Name](loopnet URL)
        addr_m = re.search(r'####\s*\[(\d+[^\]]+)\]\(https://www\.loopnet\.com/Listing/', block)
        if not addr_m:
            continue
        address = addr_m.group(1).strip()
        if re.match(r'^[\d,]+\s*SF', address):
            continue  # Skip sqft lines

        # URL
        url_m = re.search(r'(https://www\.loopnet\.com/Listing/[^")\s]+)', block[addr_m.start():])
        url = url_m.group(1).rstrip('/') if url_m else None

        # City/State/Zip
        csz_m = re.search(r'######\s*\[([^,\]]+),\s*(\w{2})\s*(\d{5})\]', block)
        city = csz_m.group(1).strip() if csz_m else None
        state = csz_m.group(2).strip() if csz_m else None
        zipcode = csz_m.group(3).strip() if csz_m else None

        # Square footage
        sqft_m = re.search(r'####\s*\[([\d,]+\s*(?:-\s*[\d,]+\s*)?SF[^\]]*)\]', block)
        sqft = sqft_m.group(1).strip() if sqft_m else None

        # Building/property name
        bldg_m = re.search(r'######\s*\[([A-Z][^\]]{3,50})\]\(https://www\.loopnet', block)
        bldg_name = None
        if bldg_m:
            candidate = bldg_m.group(1).strip()
            if not re.search(r'\b[A-Z]{2}\s+\d{5}\b', candidate):
                bldg_name = candidate

        # Price
        price_m = re.search(r'\$([\d,.]+)', block)
        price = f"${price_m.group(1)}" if price_m else None
        if not price and 'Price Upon Request' in block:
            price = 'Price Upon Request'

        # Broker names
        broker_section = block[block.find('!['):] if '![' in block else block[len(block) // 2:]
        brokers = re.findall(
            r'\[([A-Z][a-z]+ [A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\]\(https://www\.loopnet',
            broker_section
        )
        brokers = [b for b in brokers if b not in ('Virtual Tour',) and b != bldg_name
                   and not re.search(r'Plaza|Center|House|Building|Tower|Entrance', b)]
        brokers = list(dict.fromkeys(brokers))[:3]

        # Broker company (from logo image alt text)
        company_m = re.search(r'\[!\[([A-Z][^\]]+)\]', broker_section)
        broker_company = company_m.group(1).strip() if company_m else None

        listings.append({
            "listing_id": lid,
            "url": url,
            "address": address,
            "city": city,
            "state": state,
            "zip": zipcode,
            "property_name": bldg_name,
            "sqft_available": sqft,
            "asking_rent": price,
            "broker_names": ", ".join(brokers) if brokers else None,
            "broker_company": broker_company,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        })

    return listings


# ─── Main scrape flow ─────────────────────────────────────────────────────────
def scrape_city(city: str, property_type: str = "retail", max_pages: int = 1, limit: int = 0):
    """
    Scrape LoopNet search results for a city.
    Each page returns ~20-25 listings. Paginate to get more.
    """
    # Infer state abbreviation from city for proxy location
    state_map = {
        "FL": ["miami", "tampa", "orlando", "jacksonville", "fort lauderdale"],
        "TN": ["memphis", "nashville", "knoxville", "chattanooga"],
        "GA": ["atlanta", "savannah", "augusta"],
        "TX": ["houston", "dallas", "austin", "san antonio", "fort worth"],
        "NC": ["charlotte", "raleigh", "durham", "greensboro"],
        "IL": ["chicago"],
        "NY": ["new york", "brooklyn", "manhattan"],
        "CA": ["los angeles", "san francisco", "san diego", "sacramento"],
    }
    city_lower = city.lower()
    proxy_state = "FL"  # default
    for st, cities in state_map.items():
        if any(c in city_lower for c in cities):
            proxy_state = st
            break

    all_listings = []
    for page in range(1, max_pages + 1):
        url = build_search_url(city, property_type, page)
        print(f"Page {page}: {url}")

        md = fetch_page(url, state=proxy_state)
        if not md:
            print(f"  Failed to fetch page {page} — stopping pagination")
            break

        listings = parse_listings(md)
        print(f"  Parsed {len(listings)} listings")

        if not listings:
            print(f"  No listings found — end of results")
            break

        all_listings.extend(listings)

        if limit and len(all_listings) >= limit:
            all_listings = all_listings[:limit]
            print(f"  Reached limit ({limit})")
            break

        if page < max_pages:
            delay = 3
            print(f"  Waiting {delay}s before next page...")
            time.sleep(delay)

    # Deduplicate by listing_id
    seen = set()
    deduped = []
    for l in all_listings:
        if l["listing_id"] not in seen:
            seen.add(l["listing_id"])
            deduped.append(l)
    all_listings = deduped

    # Save
    city_slug = city.lower().replace(", ", "_").replace(" ", "_")
    out_file = OUT_DIR / f"{city_slug}_{property_type}.json"
    with open(out_file, "w") as f:
        json.dump(all_listings, f, indent=2)

    print(f"\nTotal: {len(all_listings)} unique listings → {out_file}")
    return all_listings


# ─── CLI ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Scrape LoopNet listing data via Hyperbrowser Fetch API")
    parser.add_argument("--city", default="Miami, FL", help="City to scrape (e.g. 'Memphis, TN')")
    parser.add_argument("--type", default="retail", help="Property type: retail, office, industrial")
    parser.add_argument("--pages", type=int, default=1, help="Number of search result pages")
    parser.add_argument("--limit", type=int, default=0, help="Max listings (0 = all)")
    args = parser.parse_args()

    print(f"LoopNet scrape: {args.city} | {args.type} | pages: {args.pages} | limit: {args.limit or 'all'}")
    print(f"Using: web.fetch(stealth='ultra') — Akamai bypass via TLS fingerprint spoofing\n")

    listings = scrape_city(args.city, args.type, max_pages=args.pages, limit=args.limit)

    if listings:
        print(f"\nSample ({min(5, len(listings))} of {len(listings)}):")
        for l in listings[:5]:
            print(f"  {l['address']}, {l.get('city') or '?'} — {l.get('sqft_available') or '?'} — {l.get('asking_rent') or '?'}")


if __name__ == "__main__":
    main()
