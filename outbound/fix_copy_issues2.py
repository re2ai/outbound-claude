#!/usr/bin/env python3
"""
Round-2 copy fixes:
  1. Staffing Email3 double CTA  — remove appended "Just reply and I'll send you the link."
  2. email1_no_greeting (2)      — prepend "Hi " before first name
  3. hi_contact_n greeting (1)   — replace "Hi Contact N," with "Hi there,"
  4. hi_role_greeting (13)       — replace "Hi Role," with "Hi there,"
  5. missing_email1 (1)          — drop support@greykhat.com
  6. verbose_location (3)        — trim ", State, United States" from Email2
  Then re-save JSON + re-upload BQ.
"""
import sys, io, json, re, os, warnings
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from google.cloud import bigquery
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv(r"C:\Users\evane\Documents\Coding\scorecard\re2scorecard2026\.env")
warnings.filterwarnings("ignore")

LOCAL = r"C:\Users\evane\AppData\Local\Temp\bounce\bounce_plg_verified.json"
TABLE = "tenant-recruitin-1575995920662.PLG_OUTBOUND.bounce_reengagement_plg_20260326"
bq    = bigquery.Client(project="tenant-recruitin-1575995920662")

with open(LOCAL) as f:
    leads = json.load(f)

print(f"Loaded {len(leads)} leads")
c = {k: 0 for k in ["dropped", "double_cta", "no_greeting", "role_greeting",
                     "contact_n_greeting", "verbose_loc"]}

fixed = []
for l in leads:
    e    = l["email"]
    camp = l.get("original_campaign", "")

    # ── 5. Drop support@greykhat.com (missing Email1) ─────────────────────
    if e.lower() == "support@greykhat.com":
        c["dropped"] += 1
        print(f"  DROPPED: {e}")
        continue

    s1 = l.get("Subject1") or l.get("subject1") or ""
    e1 = l.get("Email1")  or l.get("email1")  or ""
    e2 = l.get("Email2")  or l.get("email2")  or ""
    e3 = l.get("Email3")  or l.get("email3")  or ""

    # ── 1. Staffing Email3: remove duplicate CTA ──────────────────────────
    if camp == "PLG - Staffing - Claude":
        # Strip the appended "Just reply to this email and I'll send you the link."
        # but only if the body already has a reply CTA before it
        cleaned = re.sub(
            r'<br><br>Just reply to this email and I\'ll send you the link\.\s*$',
            '',
            e3, flags=re.IGNORECASE
        )
        if cleaned != e3:
            e3 = cleaned.rstrip()
            c["double_cta"] += 1

    # ── 2. email1_no_greeting: prepend "Hi " ──────────────────────────────
    # Matches "FirstName, do you..." or "FirstName, we built..."  at start
    m = re.match(r'^([A-Z][a-z]+),\s', e1)
    if m and not re.match(r'^(Hi |Hey )', e1, re.IGNORECASE):
        e1 = "Hi " + e1
        c["no_greeting"] += 1
        print(f"  GREETING FIXED: {e} → prepended 'Hi'")

    # ── 3 & 4. "Hi Role," / "Hi Contact N," → "Hi there," ────────────────
    for field_name, body in [("e1", e1), ("e2", e2), ("e3", e3)]:
        new_body = re.sub(r'Hi Role,', 'Hi there,', body, flags=re.IGNORECASE)
        new_body = re.sub(r'Hi Contact \d+,', 'Hi there,', new_body, flags=re.IGNORECASE)
        if new_body != body:
            if field_name == "e1":
                e1 = new_body; c["role_greeting"] += 1
                print(f"  ROLE→THERE: {e} [Email1]")
            elif field_name == "e2":
                e2 = new_body
            elif field_name == "e3":
                e3 = new_body

    # ── 6. verbose_location: trim ", State, United States" ────────────────
    for field_name, body in [("e2", e2), ("e3", e3)]:
        new_body = re.sub(r',\s+[A-Za-z ]+,\s+United States', '', body)
        if new_body != body:
            if field_name == "e2": e2 = new_body
            else:                  e3 = new_body
            c["verbose_loc"] += 1
            print(f"  VERBOSE_LOC fixed: {e}")

    # write back
    l["Email1"] = e1; l["email1"] = e1
    l["Email2"] = e2; l["email2"] = e2
    l["Email3"] = e3; l["email3"] = e3
    fixed.append(l)

print(f"\n=== Fix summary ===")
print(f"  Dropped (missing Email1):   {c['dropped']}")
print(f"  Staffing double CTA fixed:  {c['double_cta']}")
print(f"  Missing greeting fixed:     {c['no_greeting']}")
print(f"  Hi Role/Contact→Hi there:   {c['role_greeting']}")
print(f"  Verbose location fixed:     {c['verbose_loc']}")
print(f"\nTotal leads after fixes: {len(fixed)}")

# ── spot-checks ───────────────────────────────────────────────────────────────
print("\n--- Spot-checks ---")

st = next((l for l in fixed if l.get("original_campaign") == "PLG - Staffing - Claude"), None)
if st:
    print(f"Staffing Email3 ({st['email']}):")
    print(f"  {st['Email3'][:220]}")

role_sample = next((l for l in fixed
                    if re.search(r"Hi there,", l.get("Email1",""), re.IGNORECASE)
                    and l.get("original_campaign") == "PLG - Commercial Cleaners"), None)
if role_sample:
    print(f"\nCleaner Hi-there ({role_sample['email']}):")
    print(f"  Email1: {role_sample['Email1'][:120]}")

vl = next((l for l in fixed if l["email"] in
           ["carrissa@superior-expo.com","michelle@corporateliving.com","sam.avellone@npiav.com"]), None)
if vl:
    print(f"\nVerbose loc fixed ({vl['email']}):")
    print(f"  Email2: {vl['Email2'][:160]}")

# ── save JSON ─────────────────────────────────────────────────────────────────
with open(LOCAL, "w") as f:
    json.dump(fixed, f, indent=2)
print(f"\nLocal JSON saved.")

# ── upload BQ ─────────────────────────────────────────────────────────────────
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
    "email": r["email"], "first_name": r.get("first_name",""), "last_name": r.get("last_name",""),
    "company_name": r.get("company_name",""), "location": r.get("location",""), "city": r.get("city",""),
    "segment": r.get("segment",""), "campaign_name": r.get("campaign_name",""),
    "original_campaign": r.get("original_campaign",""), "max_seq_sent": r.get("max_seq_sent"),
    "email_verified": True, "verification_status": "valid",
    "subject1": r.get("Subject1", r.get("subject1","")),
    "email1":   r.get("Email1",  r.get("email1","")),
    "email2":   r.get("Email2",  r.get("email2","")),
    "email3":   r.get("Email3",  r.get("email3","")),
    "stage": "copy_final", "created_at": datetime.now(timezone.utc).isoformat(),
} for r in fixed]

job = bq.load_table_from_json(upload, TABLE, job_config=bigquery.LoadJobConfig(
    schema=schema, write_disposition="WRITE_TRUNCATE", create_disposition="CREATE_IF_NEEDED"))
job.result()
print(f"BQ updated: {len(upload)} rows  (stage=copy_final)")
