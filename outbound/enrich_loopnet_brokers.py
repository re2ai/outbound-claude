#!/usr/bin/env python3
"""
enrich_loopnet_brokers.py — Enrich CRE broker CSV with LoopNet listing data.

Pipeline:
  Phase 0: Derive names from ALL email patterns (first.last, flast, first@)
  Phase 1: Google search → LoopNet listing URLs + profile URL (with fallback strategies)
  Phase 2: Fetch listing detail pages → parse all data
  Phase 3: Score and assemble

Parallel: 4 concurrent workers for Google, 3 for listing fetches.
Resume-safe: checkpoints every 25 rows.

Usage:
  python outbound/enrich_loopnet_brokers.py --input outbound/cre_enrichment_3950.csv
  python outbound/enrich_loopnet_brokers.py --input outbound/cre_enrichment_3950.csv --resume
  python outbound/enrich_loopnet_brokers.py --input outbound/cre_enrichment_3950.csv --limit 100
  python outbound/enrich_loopnet_brokers.py --input outbound/cre_enrichment_3950.csv --workers 6
"""

import os
import re
import csv
import json
import time
import argparse
import threading
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
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

client = Hyperbrowser(api_key=os.getenv("HYPERBROWSER_API_KEY"))

OUT_DIR = Path("/tmp/loopnet_enrichment")
OUT_DIR.mkdir(exist_ok=True)
CHECKPOINT_FILE = OUT_DIR / "checkpoint.json"
RESULTS_FILE = OUT_DIR / "results.json"

MAX_LISTINGS_PER_BROKER = 5
MAX_RETRIES = 2

# Thread-safe checkpoint
_lock = threading.Lock()


# ─── Common first names (to distinguish first@ from flast@) ──────────────────
COMMON_FIRST_NAMES = {
    "aaron", "adam", "alan", "alex", "allen", "amanda", "amy", "andrew", "andy",
    "angela", "ann", "anna", "anne", "anthony", "ashley", "austin", "barbara",
    "barry", "becky", "ben", "benjamin", "beth", "bill", "billy", "bob", "bobby",
    "bonnie", "brad", "brandon", "brenda", "brent", "brett", "brian", "brittany",
    "brock", "brooke", "bruce", "bryan", "carl", "carlos", "carol", "carolyn", "casey",
    "chad", "charles", "charlie", "chase", "cheryl", "chris", "christian",
    "christina", "christine", "chuck", "cindy", "clay", "cliff", "cody", "cole",
    "colin", "colton", "connie", "corey", "cory", "craig", "curt", "curtis",
    "dale", "dan", "dana", "daniel", "danny", "darren", "dave", "david", "dawn",
    "dean", "debbie", "deborah", "dennis", "derek", "diane", "dick", "don",
    "donald", "donna", "doug", "douglas", "drew", "dustin", "earl", "ed", "eddie",
    "edward", "eileen", "elaine", "elizabeth", "ellen", "emily", "emma", "eric",
    "erik", "erin", "ernest", "eugene", "evan", "frank", "fred", "gary", "gene",
    "geoff", "george", "gerald", "glen", "glenn", "gordon", "grace", "grant",
    "greg", "gregory", "gus", "hal", "hank", "harold", "harry", "heath", "heather",
    "helen", "henry", "howard", "hunter", "jack", "jacob", "jake", "james",
    "jamie", "jane", "janet", "janice", "jared", "jason", "jay", "jean", "jeff",
    "jeffrey", "jen", "jennifer", "jenny", "jeremy", "jerry", "jesse", "jessica",
    "jessie", "jill", "jim", "jimmy", "joan", "joe", "joel", "john", "johnny",
    "jon", "jonathan", "jordan", "jose", "joseph", "josh", "joshua", "joyce",
    "juan", "judy", "julie", "justin", "kaitlyn", "karen", "karl", "kash", "kate",
    "katherine", "kathleen", "kathy", "katie", "keith", "kelly", "ken", "kenneth",
    "kent", "kevin", "kim", "kirk", "kris", "kristen", "kristin", "kurt", "kyle",
    "lance", "larry", "laura", "lauren", "lee", "leon", "linda", "lisa", "logan",
    "lori", "louis", "lucas", "luis", "luke", "lynn", "marc", "marcus", "margaret",
    "maria", "marie", "marilyn", "mark", "martha", "martin", "marty", "mary",
    "matt", "matthew", "max", "megan", "melanie", "melissa", "michael", "michelle",
    "mike", "miles", "mitchell", "molly", "monica", "morgan", "nancy", "nathan",
    "neil", "nick", "nicole", "noah", "norm", "pam", "pat", "patricia", "patrick",
    "paul", "paula", "pedro", "penny", "pete", "peter", "phil", "philip", "rachel",
    "ralph", "randy", "ray", "raymond", "rebecca", "renee", "rex", "rich",
    "richard", "rick", "rita", "rob", "robert", "robin", "rod", "roger", "ron",
    "ronald", "ross", "roy", "russell", "ruth", "ryan", "sam", "samuel", "sandra",
    "sandy", "sara", "sarah", "scott", "sean", "seth", "shane", "shannon",
    "sharon", "shawn", "sheila", "shelley", "sherry", "shirley", "sid", "stacy",
    "stan", "stephanie", "stephen", "steve", "steven", "stuart", "sue", "susan",
    "tammy", "tara", "ted", "teresa", "terri", "terry", "theresa", "thomas",
    "tim", "timothy", "tina", "todd", "tom", "tommy", "tony", "tracy", "travis",
    "troy", "tyler", "vince", "virginia", "wade", "walter", "warren", "wayne",
    "wendy", "wes", "wesley", "whitney", "will", "william", "zachary",
}

GENERIC_EMAILS = {"info", "admin", "office", "contact", "sales", "support", "hello",
                   "team", "leasing", "management", "mail", "general", "inquiries"}
GENERIC_DOMAINS = {"gmail.com", "yahoo.com", "hotmail.com", "aol.com", "outlook.com",
                    "icloud.com", "comcast.net", "att.net", "msn.com", "live.com"}


# ─── Phase 0: Name derivation ────────────────────────────────────────────────

def derive_name(row: dict) -> str | None:
    """Extract a searchable name from CSV row."""
    name = row.get("contact_name", "").strip()
    if name:
        return name

    local = row["email"].split("@")[0].lower()
    local = re.sub(r'\d+$', '', local)  # strip trailing numbers

    if local in GENERIC_EMAILS:
        return None

    # first.last@domain → "First Last"
    if "." in local:
        parts = local.split(".")
        if len(parts) == 2 and parts[0].isalpha() and parts[1].isalpha():
            return f"{parts[0].title()} {parts[1].title()}"
        if len(parts) == 3 and all(p.isalpha() for p in parts):
            return f"{parts[0].title()} {parts[2].title()}"
        # Handle hyphenated: mblunt-daniel → look at first part
        if "-" in local:
            subparts = local.replace("-", ".").split(".")
            if len(subparts) >= 2 and all(p.isalpha() for p in subparts):
                return f"{subparts[0].title()} {subparts[-1].title()}"

    # Whole local part is a common first name → treat as first name only
    if local in COMMON_FIRST_NAMES:
        return local.title()

    # flast@domain → single letter + 3+ letters = initial + surname
    m = re.match(r'^([a-z])([a-z]{3,})$', local)
    if m:
        initial, surname = m.group(1), m.group(2)
        # BUT check if the whole thing is actually a first name (e.g. "brock", "jason")
        if local in COMMON_FIRST_NAMES:
            return local.title()
        return f"{initial.upper()} {surname.title()}"

    # Two-letter prefix + surname (e.g. "gc@" → too short, skip)
    if local.isalpha() and len(local) >= 4:
        return local.title()

    return None


def get_last_name(name: str) -> str | None:
    """Extract last name from a derived name."""
    if not name:
        return None
    parts = name.split()
    if len(parts) >= 2:
        return parts[-1]
    return None


def build_search_queries(row: dict) -> list[str]:
    """Build prioritized list of LOOSE Google search queries. No hard quotes on names."""
    queries = []
    name = derive_name(row)
    company = row.get("company_name", "").strip()
    domain = row.get("domain", "").strip()
    clean_domain = ""
    if domain and domain not in GENERIC_DOMAINS:
        clean_domain = domain.replace(".com", "").replace(".net", "").replace(".org", "").replace("-", " ").replace(".", " ").strip()

    last = get_last_name(name)

    # 1. Full name + loopnet (loose — no quotes on name, let Google fuzzy match)
    if name and " " in name and len(name.split()[0]) > 1:
        queries.append(f'{name} loopnet broker')

    # 2. Last name + company + loopnet (for flast@ patterns)
    if last and company:
        queries.append(f'{last} {company} loopnet')
    elif last and clean_domain:
        queries.append(f'{last} {clean_domain} loopnet')

    # 3. Full name + site:loopnet.com (tighter but still no quotes on name)
    if name and " " in name and len(name.split()[0]) > 1:
        queries.append(f'{name} site:loopnet.com')

    # 4. First name + company (for first-name-only emails)
    if name and " " not in name:
        if company:
            queries.append(f'{name} {company} loopnet broker')
        elif clean_domain:
            queries.append(f'{name} {clean_domain} loopnet broker')

    # 5. Company name + loopnet
    if company:
        queries.append(f'{company} loopnet broker listings')

    # 6. Domain as company proxy
    if clean_domain and not company:
        queries.append(f'{clean_domain} loopnet broker')

    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            deduped.append(q)
    return deduped


# ─── Phase 1: Google search ──────────────────────────────────────────────────

class OutOfCreditsError(Exception):
    pass


def _fetch_google(query: str) -> str:
    """Single Google search, returns markdown."""
    encoded = query.replace('"', '%22').replace(' ', '+')
    url = f"https://www.google.com/search?q={encoded}&num=20"
    for attempt in range(MAX_RETRIES + 1):
        try:
            result = client.web.fetch(FetchParams(
                url=url,
                stealth="auto",
                navigation=FetchNavigationOptions(wait_until="networkidle", timeout_ms=25000),
                outputs=FetchOutputOptions(markdown=True),
            ))
            return result.data.markdown if result.data else ""
        except Exception as e:
            if "402" in str(e) or "credit" in str(e).lower():
                raise OutOfCreditsError("Hyperbrowser credits exhausted. Add credits and --resume.")
            if attempt < MAX_RETRIES:
                time.sleep(2)
            else:
                return ""


def _parse_loopnet_from_markdown(md: str) -> tuple[list, str | None]:
    """Extract LoopNet listing URLs and profile URL from Google/Bing results markdown."""
    listing_urls = re.findall(
        r'https://www\.loopnet\.com/Listing/([^\s\)"/#]+)/(\d+)', md
    )
    listing_urls = list(dict.fromkeys(listing_urls))

    profiles = re.findall(
        r'(https://www\.loopnet\.com/commercial-real-estate-brokers/profile/[^\s\)"#]+)', md
    )
    profile_url = profiles[0].rstrip("/") if profiles else None

    return listing_urls, profile_url


def _name_from_profile_url(profile_url: str) -> str | None:
    """Extract real broker name from LoopNet profile URL slug."""
    m = re.search(r'/profile/([^/]+)/', profile_url)
    if m:
        return m.group(1).replace("-", " ").title()
    # Try without trailing slash
    m2 = re.search(r'/profile/([^/]+)$', profile_url)
    if m2:
        return m2.group(1).replace("-", " ").title()
    return None


def google_search_broker(row: dict) -> dict:
    """Multi-strategy search. Uses fallbacks and follows up on profile-only results."""
    queries = build_search_queries(row)
    best_profile = None
    all_listing_urls = []

    # Pass 1: Try all our search queries
    for query in queries:
        md = _fetch_google(query)
        if not md:
            continue

        listing_urls, profile_url = _parse_loopnet_from_markdown(md)
        if profile_url and not best_profile:
            best_profile = profile_url
        if listing_urls:
            all_listing_urls = listing_urls
            break  # Found listings, stop searching

    # Pass 2: If we found a profile but no listings, extract the REAL name from
    # the profile URL and search again. The profile URL has their actual LoopNet name
    # which is often different from what we derived from their email.
    if best_profile and not all_listing_urls:
        real_name = _name_from_profile_url(best_profile)
        if real_name:
            # Targeted search: their real LoopNet name + listing pages
            for follow_up in [
                f'{real_name} site:loopnet.com',
                f'{real_name} loopnet listing broker',
            ]:
                md = _fetch_google(follow_up)
                if not md:
                    continue
                listing_urls, prof = _parse_loopnet_from_markdown(md)
                if prof and not best_profile:
                    best_profile = prof
                if listing_urls:
                    all_listing_urls = listing_urls
                    break

    # Pass 3: For not-found results, try Bing as a different index
    if not all_listing_urls and not best_profile:
        name = derive_name(row)
        company = row.get("company_name", "").strip()
        search_parts = []
        if name:
            search_parts.append(name)
        if company:
            search_parts.append(company)
        if search_parts:
            bing_query = " ".join(search_parts) + " loopnet broker"
            bing_url = f"https://www.bing.com/search?q={bing_query.replace(' ', '+')}&count=20"
            md = None
            for attempt in range(MAX_RETRIES + 1):
                try:
                    result = client.web.fetch(FetchParams(
                        url=bing_url,
                        stealth="auto",
                        navigation=FetchNavigationOptions(wait_until="networkidle", timeout_ms=20000),
                        outputs=FetchOutputOptions(markdown=True),
                    ))
                    md = result.data.markdown if result.data else ""
                    break
                except Exception:
                    if attempt < MAX_RETRIES:
                        time.sleep(2)
            if md:
                listing_urls, prof = _parse_loopnet_from_markdown(md)
                if prof and not best_profile:
                    best_profile = prof
                if listing_urls:
                    all_listing_urls = listing_urls

    return {
        "listing_urls": all_listing_urls,
        "profile_url": best_profile,
        "google_results_count": len(all_listing_urls),
        "query_used": queries[0] if queries else None,
    }


# ─── Phase 2: Listing detail parsing ─────────────────────────────────────────

def fetch_listing_detail(slug: str, listing_id: str) -> dict | None:
    """Fetch and parse a LoopNet listing detail page with retry."""
    url = f"https://www.loopnet.com/Listing/{slug}/{listing_id}/"
    for attempt in range(MAX_RETRIES + 1):
        try:
            result = client.web.fetch(FetchParams(
                url=url,
                stealth="ultra",
                browser=FetchBrowserOptions(
                    solve_captchas=True,
                    location=FetchBrowserLocationOptions(country="US"),
                ),
                navigation=FetchNavigationOptions(wait_until="networkidle", timeout_ms=30000),
                outputs=FetchOutputOptions(markdown=True),
            ))
            md = result.data.markdown if result.data else ""
            if not md or len(md) < 500 or "access denied" in md.lower():
                return None
            return parse_listing_markdown(md, url, listing_id)
        except Exception as e:
            if "402" in str(e) or "credit" in str(e).lower():
                raise OutOfCreditsError("Hyperbrowser credits exhausted. Add credits and --resume.")
            if attempt < MAX_RETRIES:
                time.sleep(2)
    return None


def parse_listing_markdown(md: str, url: str, listing_id: str) -> dict:
    """Parse listing detail markdown into structured data."""
    listing = {
        "listing_id": listing_id,
        "url": url,
        "address": None,
        "city": None,
        "state": None,
        "zip": None,
        "building_name": None,
        "property_type": None,
        "total_sqft_available": None,
        "description": None,
        "date_on_market": None,
        "last_updated": None,
        "listing_broker_names": [],
        "listing_broker_company": None,
        "profile_urls": [],
        "spaces": [],
    }

    # Title line
    title_m = re.search(r'^# (.+)$', md, re.MULTILINE)
    if title_m:
        title = title_m.group(1).strip()
        listing["description"] = title

        for ptype in ["Office/Retail", "Retail", "Office", "Industrial", "Mixed-Use",
                       "Medical", "Flex", "Restaurant", "Warehouse"]:
            if ptype.lower() in title.lower():
                listing["property_type"] = ptype
                break

        sqft_m = re.search(r'([\d,]+(?:\s*-\s*[\d,]+)?)\s*SF', title)
        if sqft_m:
            listing["total_sqft_available"] = sqft_m.group(0).strip()

        csz_m = re.search(r'in\s+(.+?),\s*(\w{2})\s+(\d{5})', title)
        if csz_m:
            listing["city"] = csz_m.group(1).strip()
            listing["state"] = csz_m.group(2).strip()
            listing["zip"] = csz_m.group(3).strip()

        addr_in_title = re.search(r'(\d+[\w\s\-]+(?:St|Ave|Blvd|Dr|Rd|Way|Ct|Ln|Pl|Pkwy|Hwy))', title)
        if addr_in_title:
            before = title[:addr_in_title.start()].strip()
            if before and not before[0].isdigit():
                listing["building_name"] = before

    # Structured metadata
    addr_m = re.search(r'####\s*Address:\s*(.+)', md)
    if addr_m:
        listing["address"] = addr_m.group(1).strip()
        if not listing["city"]:
            csz2 = re.search(r',\s*([^,]+),\s*(\w{2})\s+(\d{5})', listing["address"])
            if csz2:
                listing["city"] = csz2.group(1).strip()
                listing["state"] = csz2.group(2).strip()
                listing["zip"] = csz2.group(3).strip()

    if not listing["address"]:
        slug_m = re.search(r'/Listing/([^/]+)/', url)
        if slug_m:
            listing["address"] = slug_m.group(1).replace("-", " ")

    dom_m = re.search(r'####\s*Date on Market:\s*(.+)', md)
    if dom_m:
        listing["date_on_market"] = dom_m.group(1).strip()

    upd_m = re.search(r'####\s*Last Updated:\s*(.+)', md)
    if upd_m:
        listing["last_updated"] = upd_m.group(1).strip()

    # Spaces table — dynamic header parsing
    lines = md.split("\n")
    header_idx = None
    for idx, line in enumerate(lines):
        if "|" in line and "Space" in line and "Size" in line:
            header_idx = idx
            break

    if header_idx is not None:
        raw_header = lines[header_idx].split("|")
        if raw_header and raw_header[0].strip() == "":
            raw_header = raw_header[1:]
        if raw_header and raw_header[-1].strip() == "":
            raw_header = raw_header[:-1]
        header_cells = [c.strip() for c in raw_header]

        col_map = {}
        for ci, name in enumerate(header_cells):
            if name:
                col_map[name.lower().replace(" ", "_").replace("-", "_")] = ci

        data_start = header_idx + 1
        if data_start < len(lines) and re.match(r'^[\s|:-]+$', lines[data_start]):
            data_start += 1

        for line in lines[data_start:]:
            if "|" not in line:
                break
            raw_cells = line.split("|")
            if raw_cells and raw_cells[0].strip() == "":
                raw_cells = raw_cells[1:]
            if raw_cells and raw_cells[-1].strip() == "":
                raw_cells = raw_cells[:-1]
            cells = [c.strip() for c in raw_cells]

            if not any("SF" in c for c in cells):
                continue

            def get_col(name):
                i = col_map.get(name)
                val = cells[i] if i is not None and i < len(cells) else None
                return val if val else None

            listing["spaces"].append({
                "space_name": get_col("space"),
                "size_sf": get_col("size"),
                "term": get_col("term"),
                "rental_rate": get_col("rental_rate"),
                "space_use": get_col("space_use"),
                "rent_type": get_col("rent_type"),
                "build_out": get_col("build_out"),
                "available": get_col("available"),
            })

    # Broker names + profiles
    broker_names = re.findall(
        r'####\s*\[([^\]]+)\]\(https://www\.loopnet\.com/commercial-real-estate-brokers/profile/', md
    )
    listing["listing_broker_names"] = broker_names

    profile_urls = re.findall(
        r'(https://www\.loopnet\.com/commercial-real-estate-brokers/profile/[^")\s]+)', md
    )
    listing["profile_urls"] = list(set(u.rstrip("/") for u in profile_urls))

    company_m = re.search(r'\[!\[([A-Z][^\]]+)\]\(https://images1\.loopnet\.com.*?\)\]\(https://www\.loopnet\.com/company/', md)
    if company_m:
        listing["listing_broker_company"] = company_m.group(1).strip()

    price_m = re.search(r'\$([\d,]+(?:\.\d+)?)\s*(?:/SF)?', listing.get("description") or "")
    if price_m:
        listing["price_from_title"] = f"${price_m.group(1)}"

    return listing


# ─── Scoring ──────────────────────────────────────────────────────────────────

def score_space(space_use, size_str, property_type):
    use = (space_use or property_type or "").lower()
    sqft = 0
    if size_str:
        nums = re.findall(r'[\d,]+', size_str)
        if nums:
            sqft = int(nums[0].replace(",", ""))
    is_retail = any(k in use for k in ["retail", "restaurant", "storefront", "shop"])
    is_office = any(k in use for k in ["office", "medical", "flex"])
    is_industrial = any(k in use for k in ["industrial", "warehouse", "manufacturing"])
    if is_retail and sqft and sqft < 5000: return 5
    if is_retail: return 4
    if is_office and sqft and sqft < 5000: return 3
    if is_office: return 2
    if is_industrial: return 1
    return 2 if sqft and sqft < 5000 else 1


def pick_best_space(listing):
    best, best_score = None, 0
    if listing["spaces"]:
        for sp in listing["spaces"]:
            s = score_space(sp.get("space_use"), sp.get("size_sf"), listing["property_type"])
            if s > best_score:
                best_score = s
                best = sp
    else:
        best_score = score_space(None, listing["total_sqft_available"], listing["property_type"])
    return best, best_score


# ─── Checkpoint ───────────────────────────────────────────────────────────────

def load_checkpoint():
    if CHECKPOINT_FILE.exists():
        try:
            with open(CHECKPOINT_FILE) as f:
                return json.load(f)
        except json.JSONDecodeError:
            print("WARNING: corrupt checkpoint, starting fresh")
    return {"processed_emails": [], "results": []}


def save_checkpoint(state):
    # Write to temp file then rename — atomic on most filesystems
    tmp = CHECKPOINT_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f)
    tmp.rename(CHECKPOINT_FILE)


# ─── Single broker enrichment ─────────────────────────────────────────────────

def enrich_broker(row: dict) -> dict:
    email = row["email"]
    name = derive_name(row)
    queries = build_search_queries(row)

    enriched = {
        "email": email,
        "domain": row.get("domain", ""),
        "company_name": row.get("company_name", ""),
        "contact_name": row.get("contact_name", ""),
        "contact_title": row.get("contact_title", ""),
        "segment_sub": row.get("segment_sub", ""),
        "funnel_stage": row.get("funnel_stage", ""),
        "derived_name": name,
        "search_term_used": queries[0] if queries else None,
        "search_type": "name" if name else "none",
        "loopnet_profile_url": None,
        "loopnet_listing_count": 0,
        "best_listing_url": None,
        "best_listing_id": None,
        "best_listing_address": None,
        "best_listing_city": None,
        "best_listing_state": None,
        "best_listing_zip": None,
        "best_listing_building_name": None,
        "best_listing_property_type": None,
        "best_listing_total_sqft": None,
        "best_listing_description": None,
        "best_listing_date_on_market": None,
        "best_listing_last_updated": None,
        "best_space_name": None,
        "best_space_sqft": None,
        "best_space_rent": None,
        "best_space_use": None,
        "best_space_term": None,
        "best_space_rent_type": None,
        "best_space_available": None,
        "listing_fit_score": 0,
        "listing_broker_names": None,
        "listing_broker_company": None,
        "all_listings_json": "[]",
        "loopnet_status": "no_searchable_name" if not queries else "not_on_loopnet",
        "enriched_at": datetime.now(timezone.utc).isoformat(),
    }

    if not queries:
        return enriched

    # Phase 1: Google search with fallbacks
    google = google_search_broker(row)
    enriched["loopnet_profile_url"] = google["profile_url"]
    enriched["loopnet_listing_count"] = google["google_results_count"]
    enriched["search_term_used"] = google.get("query_used")

    if not google["listing_urls"]:
        enriched["loopnet_status"] = "profile_only" if google["profile_url"] else "not_on_loopnet"
        return enriched

    # Phase 2: Fetch listings
    all_parsed = []
    best_score, best_listing, best_space = 0, None, None

    for slug, lid in google["listing_urls"][:MAX_LISTINGS_PER_BROKER]:
        parsed = fetch_listing_detail(slug, lid)
        if not parsed:
            continue
        all_parsed.append(parsed)
        sp, score = pick_best_space(parsed)
        if score > best_score:
            best_score, best_listing, best_space = score, parsed, sp

    # Phase 3: Assemble
    if best_listing:
        L = best_listing
        enriched.update({
            "best_listing_url": L["url"],
            "best_listing_id": L["listing_id"],
            "best_listing_address": L["address"],
            "best_listing_city": L["city"],
            "best_listing_state": L["state"],
            "best_listing_zip": L["zip"],
            "best_listing_building_name": L["building_name"],
            "best_listing_property_type": L["property_type"],
            "best_listing_total_sqft": L["total_sqft_available"],
            "best_listing_description": L["description"],
            "best_listing_date_on_market": L["date_on_market"],
            "best_listing_last_updated": L["last_updated"],
            "listing_broker_names": ", ".join(L["listing_broker_names"]) if L["listing_broker_names"] else None,
            "listing_broker_company": L["listing_broker_company"],
            "listing_fit_score": best_score,
        })
        if best_space:
            enriched.update({
                "best_space_name": best_space.get("space_name"),
                "best_space_sqft": best_space.get("size_sf"),
                "best_space_rent": best_space.get("rental_rate"),
                "best_space_use": best_space.get("space_use"),
                "best_space_term": best_space.get("term"),
                "best_space_rent_type": best_space.get("rent_type"),
                "best_space_available": best_space.get("available"),
            })
        if best_score >= 4:
            enriched["loopnet_status"] = "found_ideal"
        elif best_score >= 2:
            enriched["loopnet_status"] = "found_ok"
        else:
            enriched["loopnet_status"] = "found_industrial_only"

    # Condensed all listings
    condensed = []
    for pl in all_parsed:
        entry = {k: pl[k] for k in ["listing_id", "url", "address", "city", "state", "zip",
                                      "building_name", "property_type", "total_sqft_available",
                                      "date_on_market", "last_updated", "listing_broker_names",
                                      "listing_broker_company", "spaces"]}
        entry["description"] = (pl.get("description") or "")[:200]
        _, s = pick_best_space(pl)
        entry["fit_score"] = s
        condensed.append(entry)
    enriched["all_listings_json"] = json.dumps(condensed)

    return enriched


# ─── Main run ─────────────────────────────────────────────────────────────────

def run(input_csv, limit=0, resume=False, workers=4):
    with open(input_csv) as f:
        rows = list(csv.DictReader(f))
    print(f"Loaded {len(rows)} rows")

    state = load_checkpoint() if resume else {"processed_emails": [], "results": []}
    processed = set(state["processed_emails"])
    results = state["results"]
    if resume:
        print(f"Resuming: {len(processed)} done, {len(results)} results")

    to_process = [r for r in rows if r["email"] not in processed]
    if limit:
        to_process = to_process[:limit]
    print(f"To process: {len(to_process)} | Workers: {workers}")
    print()

    completed = 0
    batch_size = 25

    try:
        for batch_start in range(0, len(to_process), batch_size):
            batch = to_process[batch_start:batch_start + batch_size]
            batch_results = {}

            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(enrich_broker, row): row["email"] for row in batch}
                for future in as_completed(futures):
                    email = futures[future]
                    try:
                        enriched = future.result()
                        batch_results[email] = enriched
                        status = enriched["loopnet_status"]
                        score = enriched["listing_fit_score"]
                        name = enriched.get("derived_name") or email
                        ptype = enriched.get("best_listing_property_type") or "-"
                        completed += 1
                        print(f"  [{len(processed)+completed}/{len(rows)}] {name[:30]:30s} → {status} | score={score} | {ptype}")
                    except OutOfCreditsError:
                        raise
                    except Exception as e:
                        completed += 1
                        batch_results[email] = {
                            "email": email,
                            "loopnet_status": f"error: {e}",
                            "enriched_at": datetime.now(timezone.utc).isoformat(),
                        }
                        print(f"  [{len(processed)+completed}/{len(rows)}] {email} → ERROR: {e}")

            # Update state after each batch
            for email, enriched in batch_results.items():
                processed.add(email)
                results.append(enriched)

            with _lock:
                state["processed_emails"] = list(processed)
                state["results"] = results
                save_checkpoint(state)

            pct = (len(processed)) * 100 // len(rows)
            found = sum(1 for r in results if "found" in r.get("loopnet_status", ""))
            ideal = sum(1 for r in results if r.get("loopnet_status") == "found_ideal")
            print(f"  [checkpoint {pct}%] {len(processed)} done | {found} found | {ideal} ideal")
            print()

    except OutOfCreditsError as e:
        print(f"\n!!! {e}")
        print("Saving checkpoint — run with --resume after adding credits.")
        state["processed_emails"] = list(processed)
        state["results"] = results
        save_checkpoint(state)
        return

    # Final output
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)

    if results:
        csv_out = OUT_DIR / "enriched.csv"
        all_keys = set()
        for r in results:
            all_keys.update(r.keys())
        # Stable column order
        ordered = ["email", "domain", "company_name", "contact_name", "contact_title",
                    "derived_name", "segment_sub", "funnel_stage",
                    "loopnet_status", "listing_fit_score",
                    "loopnet_profile_url", "loopnet_listing_count",
                    "best_listing_url", "best_listing_address", "best_listing_city",
                    "best_listing_state", "best_listing_zip", "best_listing_building_name",
                    "best_listing_property_type", "best_listing_total_sqft",
                    "best_listing_description", "best_listing_date_on_market", "best_listing_last_updated",
                    "best_space_name", "best_space_sqft", "best_space_rent", "best_space_use",
                    "best_space_term", "best_space_rent_type", "best_space_available",
                    "listing_broker_names", "listing_broker_company",
                    "search_term_used", "search_type", "all_listings_json", "enriched_at"]
        fieldnames = [k for k in ordered if k in all_keys] + sorted(all_keys - set(ordered))
        with open(csv_out, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in results:
                writer.writerow(r)
        print(f"CSV: {csv_out}")

    statuses = {}
    for r in results:
        s = r.get("loopnet_status", "?")
        statuses[s] = statuses.get(s, 0) + 1
    print(f"\nTotal: {len(results)}")
    for s, c in sorted(statuses.items(), key=lambda x: -x[1]):
        print(f"  {s}: {c}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    run(args.input, limit=args.limit, resume=args.resume, workers=args.workers)


if __name__ == "__main__":
    main()
