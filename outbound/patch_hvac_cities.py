#!/usr/bin/env python3
"""
Patch hvac_emails.json — fix two city issues:
1. city == "United States"  → use "your area"
2. LinkedIn metro/region strings (e.g. "Greater Boston") → extract core city,
   re-query BQ for count, regenerate all 5 copy fields.

Only touches the affected contacts; leaves all others unchanged.
"""

import json, re, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from google.cloud import bigquery
bq = bigquery.Client(project="tenant-recruitin-1575995920662")

# ── Metro city mapping ──────────────────────────────────────────────────────────
METRO_MAP = {
    "Washington DC-Baltimore Area":         "Washington DC",
    "Greater Boston":                        "Boston",
    "Los Angeles Metropolitan Area":         "Los Angeles",
    "Salt Lake City Metropolitan Area":      "Salt Lake City",
    "Detroit Metropolitan Area":             "Detroit",
    "Cincinnati Metropolitan Area":          "Cincinnati",
    "Grand Rapids Metropolitan Area":        "Grand Rapids",
    "Greater Minneapolis-St. Paul Area":     "Minneapolis",
    "Greater Chicago Area":                  "Chicago",
    "Dallas-Fort Worth Metroplex":           "Dallas",
    "Atlanta Metropolitan Area":             "Atlanta",
    "Charlotte Metro":                       "Charlotte",
    "Denver Metropolitan Area":              "Denver",
    "Kansas City Metropolitan Area":         "Kansas City",
    "Knoxville Metropolitan Area":           "Knoxville",
    "New York City Metropolitan Area":       "New York",
    "Miami-Fort Lauderdale Area":            "Miami",
    "San Francisco Bay Area":                "San Francisco",
    "Buffalo-Niagara Falls Area":            "Buffalo",
    "Iowa City-Cedar Rapids Area":           "Cedar Rapids",
    "Johnson City-Kingsport-Bristol Area":   "Johnson City",
    "Boise Metropolitan Area":               "Boise",
    "Des Moines Metropolitan Area":          "Des Moines",
    "Nashville Metropolitan Area":           "Nashville",
    "Memphis Metropolitan Area":             "Memphis",
    "Oklahoma City Metropolitan Area":       "Oklahoma City",
    "Omaha Metropolitan Area":               "Omaha",
    "Peoria Metropolitan Area":              "Peoria",
    "Greater Anchorage Area":                "Anchorage",
    "Greater Bend Area":                     "Bend",
    "Greater Charlottesville Area":          "Charlottesville",
    "Greater Cleveland":                     "Cleveland",
    "Greater Houston":                       "Houston",
    "Greater Indianapolis":                  "Indianapolis",
    "Greater Los Angeles":                   "Los Angeles",
    "Greater Milwaukee":                     "Milwaukee",
    "Greater Myrtle Beach Area":             "Myrtle Beach",
    "Greater New Orleans Region":            "New Orleans",
    "Greater Orlando":                       "Orlando",
    "Greater Philadelphia":                  "Philadelphia",
    "Greater Phoenix Area":                  "Phoenix",
    "Greater Pittsburgh Region":             "Pittsburgh",
    "Greater Portsmouth Area":               "Portsmouth",
    "Greater Sacramento":                    "Sacramento",
    "Greater Seattle Area":                  "Seattle",
    "Greater St. Louis":                     "St. Louis",
    "Greater Tucson Area":                   "Tucson",
    "Lancaster County":                      "Lancaster",
    "Los Angeles County":                    "Los Angeles",
    "Orange County":                         "Orange County",
    "Providence County":                     "Providence",
    "San Diego County":                      "San Diego",
    "Waco Area":                             "Waco",
}

def clean_city(raw_city):
    """Return the canonical city to use in copy, or 'your area' if unusable."""
    if not raw_city or raw_city.strip() in ("", "United States"):
        return "your area"
    return METRO_MAP.get(raw_city.strip(), raw_city.strip())


def fetch_city_counts(cities):
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


def businesses_str(city, city_counts):
    raw_count = city_counts.get(city.lower()) if city != "your area" else None
    if raw_count:
        return "over 50,000 businesses" if raw_count > 30000 else f"{raw_count:,} businesses"
    return "thousands of businesses"


def build_emails(contact, city, biz):
    first_name = (contact.get("first_name") or "").strip()
    greeting   = first_name if first_name else "Hi"

    subject1 = "commercial HVAC x local offices"
    subject3 = f"HVAC contacts in {city}"

    email1 = (
        f"Hi {first_name}, do you sell commercial HVAC to offices and restaurants in {city}?\n\n"
        f"We have contact info for {biz} in {city} you can email on autopilot.\n\n"
        f"If it's something of interest, I can send you a link to test it out for free."
    )
    email2 = (
        f"I ran a quick search in {city} this morning.\n\n"
        f"Made a list of {biz} that look like they could use your HVAC services.\n\n"
        f"Want me to send you the link to take a look?"
    )
    email3 = (
        f"{greeting}, what type of commercial clients are you targeting in {city} -- "
        f"offices, restaurants, or both?\n\n"
        f"We have a free trial you can test out -- just let me know and I'll send the link."
    )
    return subject1, subject3, email1, email2, email3


# ── Load ───────────────────────────────────────────────────────────────────────
IN_FILE  = "C:/Users/evane/Documents/hvac_emails.json"
OUT_FILE = "C:/Users/evane/Documents/hvac_emails.json"

with open(IN_FILE, encoding="utf-8", errors="ignore") as f:
    raw = f.read()
raw = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', raw)
leads = json.loads(raw)
print(f"Loaded {len(leads)} contacts")

# ── Identify affected contacts ──────────────────────────────────────────────────
def needs_patch(lead):
    city = (lead.get("city") or "").strip()
    if city == "United States":
        return True
    if city in METRO_MAP:
        return True
    return False

affected = [l for l in leads if needs_patch(l)]
print(f"Affected contacts: {len(affected)}")

# ── Fetch BQ counts for cleaned cities ─────────────────────────────────────────
cleaned_cities = list(set(clean_city(l.get("city","")) for l in affected))
print(f"Fetching BQ counts for {len(cleaned_cities)} cleaned cities...")
city_counts = fetch_city_counts(cleaned_cities)
print(f"  Got counts for {len(city_counts)} cities")

# ── Patch ──────────────────────────────────────────────────────────────────────
patched = 0
for lead in leads:
    if not needs_patch(lead):
        continue

    old_city = (lead.get("city") or "").strip()
    new_city = clean_city(old_city)
    biz      = businesses_str(new_city, city_counts)
    s1, s3, e1, e2, e3 = build_emails(lead, new_city, biz)

    lead["city_resolved"]  = new_city
    lead["businesses_str"] = biz
    lead["Subject1"]       = s1
    lead["Subject3"]       = s3
    lead["Email1"]         = e1
    lead["Email2"]         = e2
    lead["Email3"]         = e3
    patched += 1

print(f"Patched {patched} contacts")

# ── Save ───────────────────────────────────────────────────────────────────────
with open(OUT_FILE, "w", encoding="utf-8") as f:
    json.dump(leads, f, indent=2, ensure_ascii=False)
print(f"Saved to {OUT_FILE}")

# ── Spot-check 5 patched ───────────────────────────────────────────────────────
print("\n--- Spot check (patched contacts) ---")
shown = 0
for lead in leads:
    if not needs_patch(lead):
        continue
    old_city = (lead.get("city") or "").strip()
    print(f"\n{lead['first_name']} | old city: \"{old_city}\" → resolved: \"{lead['city_resolved']}\"")
    print(f"  Subject1: {lead['Subject1']}")
    print(f"  Email1 line 1: {lead['Email1'].split(chr(10))[0]}")
    print(f"  businesses_str: {lead['businesses_str']}")
    shown += 1
    if shown >= 5:
        break
