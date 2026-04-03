#!/usr/bin/env python3
"""
Fix all copy issues identified in the PLG re-engagement campaign:
  1. Commercial Cleaners (86): raw street address → "your area" in Email1 + Email2
  2. IT Solutions (67): raw street address → "your area" in Email3
  3. Commercial Landscaping (35): regenerate missing Email2 body
  4. Staffing (21): add <br><br> after greeting in Email3
  5. Security (2): trim verbose "City, State, United States" → just city
  6. Stale phrases (various): remove "before the end of the year / Q1", "ahead of the holidays"
  7. Drop scott@sba.gov (Janitorial - wrong ICP)
  Then re-upload to BQ + sync local JSON.
"""
import re, json, os, warnings
from google.cloud import bigquery
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv(r"C:\Users\evane\Documents\Coding\scorecard\re2scorecard2026\.env")
warnings.filterwarnings("ignore")

LOCAL = r"C:\Users\evane\AppData\Local\Temp\bounce\bounce_plg_verified.json"
TABLE = "tenant-recruitin-1575995920662.PLG_OUTBOUND.bounce_reengagement_plg_20260326"
bq = bigquery.Client(project="tenant-recruitin-1575995920662")

with open(LOCAL) as f:
    leads = json.load(f)

print(f"Loaded {len(leads)} leads")
counters = {k: 0 for k in [
    "dropped", "cleaners_addr", "it_addr", "landscaping_e2",
    "staffing_br", "security_loc", "stale_eoy", "stale_q1", "stale_holidays"
]}

# ─── helpers ──────────────────────────────────────────────────────────────────

def looks_like_address(s):
    """Return True if string looks like a street address rather than a city name."""
    if not s:
        return False
    return bool(re.search(r'\d{2,}', s))  # contains digits → street address

def fix_address_in_text(text, old_loc, replacement="your area"):
    """Replace all occurrences of old_loc in text with replacement."""
    if not text or not old_loc:
        return text
    return text.replace(old_loc, replacement)

def fix_verbose_location(text):
    """
    'Navarre, Ohio, United States' → 'Navarre'
    'Oakdale, California, United States' → 'Oakdale'
    """
    if not text:
        return text
    return re.sub(r',\s+[A-Za-z ]+,\s+United States', '', text)

def fix_stale_phrases(text):
    """Remove time-sensitive phrases that are now stale (March 2026)."""
    if not text:
        return text
    # "... before the end of the year."
    text = re.sub(
        r'\s*before the end of the year\.?',
        '.',
        text, flags=re.IGNORECASE
    )
    # "... before the end of Q1."
    text = re.sub(
        r'\s*before the end of Q1\.?',
        '.',
        text, flags=re.IGNORECASE
    )
    # "Ahead of the holidays its free ... I won't flood your inbox again."
    text = re.sub(
        r'Ahead of the holidays[^<]*(?:I\'ll keep an eye out for your sign-up,?\s*but otherwise,?\s*I won\'t flood your inbox again\.?\s*)?',
        '',
        text, flags=re.IGNORECASE
    )
    # clean up doubled periods or stray whitespace
    text = re.sub(r'\.{2,}', '.', text)
    text = re.sub(r'\s+\.', '.', text)
    # clean up trailing/leading <br> created by removals
    text = re.sub(r'(<br\s*/?>)+\s*$', '', text.strip(), flags=re.IGNORECASE)
    return text

def fix_staffing_email3(text):
    """'Hi Name,Last one' → 'Hi Name,<br><br>Last one'"""
    if not text:
        return text
    return re.sub(
        r'(Hi [^,<]+,)(?!<br>|<br/>|\s*<br)',
        r'\1<br><br>',
        text
    )

def get_landscaping_service(lead):
    """Extract the service type from Email1 subject or body for landscaping leads."""
    subject = lead.get("Subject1", "")
    # Subject1 usually is like "Company x local businesses" or "landscape design x..."
    m = re.search(r'^(.+?)\s+x\s+', subject, re.IGNORECASE)
    if m:
        svc = m.group(1).strip()
        # Remove company name prefix if present (format: "CompanyName service x...")
        # Often Subject1 is "Company x local businesses" — use Email1 for service
    # Fall back to extracting from Email1 body
    e1 = lead.get("Email1", "")
    m2 = re.search(r'do you sell (.+?) to (?:retail|local) businesses', e1, re.IGNORECASE)
    if m2:
        return m2.group(1).strip()
    return "landscaping services"

# ─── process each lead ────────────────────────────────────────────────────────

fixed = []
for lead in leads:
    camp = lead.get("original_campaign", "")

    # ── 1. Drop scott@sba.gov ─────────────────────────────────────────────────
    if lead.get("email", "").lower() == "scott@sba.gov":
        counters["dropped"] += 1
        print(f"  DROPPED: {lead['email']} ({camp})")
        continue

    city = lead.get("city", "") or ""

    # ── 2. Commercial Cleaners: raw address in Email1 + Email2 ────────────────
    if camp == "PLG - Commercial Cleaners" and looks_like_address(city):
        for field in ["Email1", "Email2"]:
            old = lead.get(field, "")
            if old and city in old:
                lead[field] = fix_address_in_text(old, city, "your area")
                counters["cleaners_addr"] += 1

    # ── 3. IT Solutions: raw address in Email3 ────────────────────────────────
    if camp == "PLG - IT Solutions" and looks_like_address(city):
        old = lead.get("Email3", "")
        if old and city in old:
            lead["Email3"] = fix_address_in_text(old, city, "your area")
            counters["it_addr"] += 1

    # ── 4. Commercial Landscaping: regenerate Email2 body ─────────────────────
    if camp == "PLG - Commercial Landscaping Companies":
        e2 = lead.get("Email2", "")
        # Detect empty body (only the CTA)
        stripped = re.sub(r'<br\s*/?>', '', e2, flags=re.IGNORECASE).strip()
        if not stripped or stripped == "Just reply to this email and I'll send you the link.":
            service = get_landscaping_service(lead)
            city_disp = city if city and not looks_like_address(city) else "your area"
            lead["Email2"] = (
                f"I ran a quick search in {city_disp} this morning.<br><br>"
                f"Made a list of local businesses that look like they could use {service} "
                f"— there are quite a few of them.<br><br>"
                f"Just reply to this email and I'll send you the link."
            )
            counters["landscaping_e2"] += 1

    # ── 5. Staffing: missing <br><br> after greeting in Email3 ────────────────
    if camp == "PLG - Staffing - Claude":
        old = lead.get("Email3", "")
        fixed_e3 = fix_staffing_email3(old)
        if fixed_e3 != old:
            lead["Email3"] = fixed_e3
            counters["staffing_br"] += 1

    # ── 6. Security: verbose "City, State, United States" in Email2 ───────────
    if camp == "PLG - Security Campaign":
        for field in ["Email2", "Email3"]:
            old = lead.get(field, "")
            fixed_loc = fix_verbose_location(old)
            if fixed_loc != old:
                lead[field] = fixed_loc
                counters["security_loc"] += 1

    # ── 7. Stale time references across all leads ─────────────────────────────
    for field in ["Email1", "Email2", "Email3"]:
        old = lead.get(field, "")
        if not old:
            continue
        if "before the end of the year" in old.lower():
            lead[field] = fix_stale_phrases(old)
            counters["stale_eoy"] += 1
        elif "before the end of q1" in old.lower():
            lead[field] = fix_stale_phrases(old)
            counters["stale_q1"] += 1
        elif "ahead of the holidays" in old.lower():
            lead[field] = fix_stale_phrases(old)
            counters["stale_holidays"] += 1

    fixed.append(lead)

print(f"\n=== Fix summary ===")
print(f"  Dropped (wrong ICP):                 {counters['dropped']}")
print(f"  Commercial Cleaners addr fixed:      {counters['cleaners_addr']} fields")
print(f"  IT Solutions Email3 addr fixed:      {counters['it_addr']} leads")
print(f"  Landscaping Email2 regenerated:      {counters['landscaping_e2']} leads")
print(f"  Staffing Email3 <br> fixed:          {counters['staffing_br']} leads")
print(f"  Security verbose location fixed:     {counters['security_loc']} fields")
print(f"  Stale 'end of year' removed:         {counters['stale_eoy']} fields")
print(f"  Stale 'end of Q1' removed:           {counters['stale_q1']} fields")
print(f"  Stale 'holidays' removed:            {counters['stale_holidays']} fields")
print(f"\nTotal leads after fixes: {len(fixed)}")

# ─── spot-check ───────────────────────────────────────────────────────────────
print("\n--- Spot-checks ---")

# Cleaners: should say "your area"
c = next((l for l in fixed if l.get("original_campaign") == "PLG - Commercial Cleaners"
          and looks_like_address(l.get("city",""))), None)
if c:
    print(f"Cleaners ({c['email']})")
    print(f"  Email1: {c['Email1'][:120]}")
    print(f"  Email2: {c['Email2'][:120]}")

# IT Solutions: Email3 should say "your area"
it = next((l for l in fixed if l.get("original_campaign") == "PLG - IT Solutions"
           and looks_like_address(l.get("city",""))), None)
if it:
    print(f"\nIT Solutions ({it['email']})")
    print(f"  Email3: {it['Email3'][:160]}")

# Landscaping: Email2 should have full body
la = next((l for l in fixed if l.get("original_campaign") == "PLG - Commercial Landscaping Companies"), None)
if la:
    print(f"\nLandscaping ({la['email']})")
    print(f"  Email2: {la['Email2'][:200]}")

# Staffing: Email3 should have <br><br> after greeting
st = next((l for l in fixed if l.get("original_campaign") == "PLG - Staffing - Claude"), None)
if st:
    print(f"\nStaffing ({st['email']})")
    print(f"  Email3: {st['Email3'][:180]}")

# Security: verbose location gone
se = next((l for l in fixed if l.get("original_campaign") == "PLG - Security Campaign"), None)
if se:
    print(f"\nSecurity ({se['email']})")
    print(f"  Email2: {se['Email2'][:200]}")

# IT Solutions: stale phrase gone from Email2
it2 = next((l for l in fixed if l.get("original_campaign") == "PLG - IT Solutions"), None)
if it2:
    print(f"\nIT Solutions stale check ({it2['email']})")
    print(f"  Email2: {it2['Email2'][:220]}")

# ─── save local JSON ──────────────────────────────────────────────────────────
with open(LOCAL, "w") as f:
    json.dump(fixed, f, indent=2)
print(f"\nLocal JSON saved: {LOCAL}")

# ─── upload to BQ ─────────────────────────────────────────────────────────────
schema = [
    bigquery.SchemaField("email", "STRING"), bigquery.SchemaField("first_name", "STRING"),
    bigquery.SchemaField("last_name", "STRING"), bigquery.SchemaField("company_name", "STRING"),
    bigquery.SchemaField("location", "STRING"), bigquery.SchemaField("city", "STRING"),
    bigquery.SchemaField("segment", "STRING"), bigquery.SchemaField("campaign_name", "STRING"),
    bigquery.SchemaField("original_campaign", "STRING"), bigquery.SchemaField("max_seq_sent", "INT64"),
    bigquery.SchemaField("email_verified", "BOOL"), bigquery.SchemaField("verification_status", "STRING"),
    bigquery.SchemaField("subject1", "STRING"), bigquery.SchemaField("email1", "STRING"),
    bigquery.SchemaField("email2", "STRING"), bigquery.SchemaField("email3", "STRING"),
    bigquery.SchemaField("stage", "STRING"), bigquery.SchemaField("created_at", "TIMESTAMP"),
]

upload = [{
    "email": r["email"], "first_name": r.get("first_name", ""), "last_name": r.get("last_name", ""),
    "company_name": r.get("company_name", ""), "location": r.get("location", ""), "city": r.get("city", ""),
    "segment": r.get("segment", ""), "campaign_name": r.get("campaign_name", ""),
    "original_campaign": r.get("original_campaign", ""), "max_seq_sent": r.get("max_seq_sent"),
    "email_verified": True, "verification_status": "valid",
    "subject1": r.get("Subject1", r.get("subject1", "")),
    "email1": r.get("Email1", r.get("email1", "")),
    "email2": r.get("Email2", r.get("email2", "")),
    "email3": r.get("Email3", r.get("email3", "")),
    "stage": "copy_fixed", "created_at": datetime.now(timezone.utc).isoformat(),
} for r in fixed]

job = bq.load_table_from_json(upload, TABLE, job_config=bigquery.LoadJobConfig(
    schema=schema, write_disposition="WRITE_TRUNCATE", create_disposition="CREATE_IF_NEEDED"))
job.result()
print(f"BQ updated: {len(upload)} rows  (stage=copy_fixed)")
