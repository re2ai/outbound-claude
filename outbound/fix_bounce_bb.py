#!/usr/bin/env python3
import sys, io, json, re, warnings
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
warnings.filterwarnings('ignore')
from dotenv import load_dotenv
load_dotenv(r"C:\Users\evane\Documents\Coding\scorecard\re2scorecard2026\.env")
from google.cloud import bigquery
from datetime import datetime, timezone

LOCAL = r"C:\Users\evane\AppData\Local\Temp\bounce\bounce_bb_verified.json"
TABLE = "tenant-recruitin-1575995920662.PLG_OUTBOUND.bounce_reengagement_bb_20260326"
bq = bigquery.Client(project="tenant-recruitin-1575995920662")

with open(LOCAL) as f:
    leads = json.load(f)

# ── helpers ───────────────────────────────────────────────────────────────────

def extract_type_city_relaxed(body1, body2, body3):
    # Standard: "about [TYPE] owners in [CITY] who"
    m = re.search(r"about (.+?) owners in (.+?) who", body2 or "", re.IGNORECASE)
    if m:
        btype = m.group(1).strip()
        city  = re.split(r",", m.group(2).strip())[0].strip()
        return btype, city

    # Type-only from body2: "about [TYPE] owners who/with"
    btype = None
    m2 = re.search(r"about (.+?) owners (?:who|with)", body2 or "", re.IGNORECASE)
    if m2:
        btype = m2.group(1).strip()

    # Type from body2 listing reference: "about your [TYPE] listing"
    if not btype:
        m2b = re.search(r"about (?:your )?(.+?) listing", body2 or "", re.IGNORECASE)
        if m2b:
            btype = m2b.group(1).strip()

    # City from body1: "owners in [CITY] who"
    city = None
    m3 = re.search(r"owners in (.+?) who", body1 or "", re.IGNORECASE)
    if m3:
        city = re.split(r",", m3.group(1).strip())[0].strip()

    # City from body3 if still missing
    if not city:
        m4 = re.search(r"owners in (.+?)(?:,| who)", body3 or "", re.IGNORECASE)
        if m4:
            city = re.split(r",", m4.group(1).strip())[0].strip()

    # Type from body1 listing: "listing for a/an [TYPE] business/on"
    if not btype:
        m5 = re.search(r"listing for (?:a|an) (.+?) (?:business|on)", body1 or "", re.IGNORECASE)
        if m5:
            btype = m5.group(1).strip()

    # Type from body1 connects: "connects you with [TYPE] owners in"
    if not btype:
        m6 = re.search(r"connects you with (.+?) owners in", body1 or "", re.IGNORECASE)
        if m6:
            t = m6.group(1).strip()
            if "business" not in t.lower():
                btype = t

    return btype or "business", city or "your area"


def clean_type(btype):
    """Remove trailing 'business' to avoid 'plumbing business business owners'."""
    return re.sub(r"\s+business$", "", btype.strip(), flags=re.IGNORECASE).strip()


def build_new_email1(fn, btype, city):
    name = fn.strip() if fn else "there"
    t = clean_type(btype)
    return (
        f"{name}, we have {t} business owners in {city} "
        f"who may be exploring a sale.<br><br>"
        f"Would you be interested in connecting with them? Let me know."
    )


def build_new_subject(btype, city):
    t = clean_type(btype)
    return f"{t} owners in {city}"


# ── apply fixes ───────────────────────────────────────────────────────────────
fixed_double   = 0
fixed_fallback = 0
unchanged      = 0

for l in leads:
    if l["max_seq_sent"] != 2:
        unchanged += 1
        continue

    e1 = l.get("Email1", "")
    e2 = l.get("Email2", "")
    e3 = l.get("Email3", "")
    fn = l.get("first_name", "")

    # Fix double-business
    if re.search(r"business business owners", e1, re.IGNORECASE):
        e1 = re.sub(r"business business owners", "business owners", e1, flags=re.IGNORECASE)
        l["Email1"] = e1
        fixed_double += 1

    # Fix leads that still have old body1 as Email1 (they already saw it)
    is_old_body1 = (
        "we have a platform that connects" in e1.lower() or
        "noticed your listing" in e1.lower() or
        "noticed you work with" in e1.lower()
    )
    if is_old_body1:
        btype, city = extract_type_city_relaxed(e1, e2, e3)
        l["Email1"]   = build_new_email1(fn, btype, city)
        l["Subject1"] = build_new_subject(btype, city)
        fixed_fallback += 1

print(f"Fixed double-business:      {fixed_double}")
print(f"Fixed fallback → new Email1: {fixed_fallback}")
print(f"Seq=1 unchanged:            {unchanged}")

# ── spot check ────────────────────────────────────────────────────────────────
print()
print("=== SPOT CHECK: previously failing seq=2 leads ===")
check_emails = [
    "saulgutterman@execbb.com", "ralph.ross@hedgestone.com",
    "courtney@preschoolbusinesssolutions.com", "stu@greencirclecap.com",
    "gurinder@maximforte.com", "rchamberlain@kw.com",
    "miamiplatinumrealtors@gmail.com", "eric@nashbb.com",
    "jared@wcibusinessbrokers.com", "cgeorgiopoulos@gmail.com",
]
for l in leads:
    if l["email"] in check_emails:
        print(f"  {l['email']}")
        print(f"  Subject1: {l['Subject1']}")
        print(f"  Email1:   {l['Email1']}")
        print(f"  Email2:   {l['Email2'][:100]}")
        print()

# ── final consistency check ───────────────────────────────────────────────────
print("=== FINAL CHECKS ===")
issues = []
for l in leads:
    e1, e2, e3, s1 = l["Email1"], l["Email2"], l["Email3"], l["Subject1"]
    if not s1:  issues.append(f"MISSING_SUBJECT: {l['email']}")
    if not e1:  issues.append(f"MISSING_E1: {l['email']}")
    if not e2:  issues.append(f"MISSING_E2: {l['email']}")
    if not e3:  issues.append(f"MISSING_E3: {l['email']}")
    if re.search(r"business business", e1, re.IGNORECASE):
        issues.append(f"DOUBLE_BUSINESS: {l['email']}")
    if l["max_seq_sent"] == 2:
        if ("we have a platform" in e1.lower() or
            "noticed your listing" in e1.lower() or
            "noticed you work with" in e1.lower()):
            issues.append(f"STILL_OLD_BODY1: {l['email']}")
    if re.search(r"https?://", e1 + e2 + e3):
        issues.append(f"LINK_FOUND: {l['email']}")

if issues:
    print(f"  Issues found: {len(issues)}")
    for i in issues[:20]:
        print(f"    {i}")
else:
    print("  All clean!")

# ── save ─────────────────────────────────────────────────────────────────────
with open(LOCAL, "w") as f:
    json.dump(leads, f, indent=2)

upload = [{
    "email": r["email"], "first_name": r["first_name"], "last_name": r["last_name"],
    "company_name": r["company_name"], "location": r["location"],
    "original_campaign": r["original_campaign"], "max_seq_sent": r["max_seq_sent"],
    "subject1": r["Subject1"], "email1": r["Email1"],
    "email2": r["Email2"], "email3": r["Email3"],
    "stage": "copy_final", "created_at": datetime.now(timezone.utc).isoformat(),
} for r in leads]

schema = [
    bigquery.SchemaField("email","STRING"), bigquery.SchemaField("first_name","STRING"),
    bigquery.SchemaField("last_name","STRING"), bigquery.SchemaField("company_name","STRING"),
    bigquery.SchemaField("location","STRING"), bigquery.SchemaField("original_campaign","STRING"),
    bigquery.SchemaField("max_seq_sent","INT64"), bigquery.SchemaField("subject1","STRING"),
    bigquery.SchemaField("email1","STRING"), bigquery.SchemaField("email2","STRING"),
    bigquery.SchemaField("email3","STRING"), bigquery.SchemaField("stage","STRING"),
    bigquery.SchemaField("created_at","TIMESTAMP"),
]
job = bq.load_table_from_json(upload, TABLE, job_config=bigquery.LoadJobConfig(
    schema=schema, write_disposition="WRITE_TRUNCATE", create_disposition="CREATE_IF_NEEDED"))
job.result()
print(f"\nBQ updated: {len(upload)} rows → {TABLE} (stage=copy_final)")
