#!/usr/bin/env python3
"""
Build BB Bounce Re-engagement leads from Business Brokers - Repush 03.19 (ID: 3060221).

Rules:
  seq=1  → use body1/body2/body3 from SmartLead as Email1/2/3
  seq=2  → generate fresh Email1 from body2 context; reuse body2/body3 as Email2/3
  seq=3  → skip

New Email1 template (seq=2):
  "[Name], we have [type] business owners in [city] who may be exploring a sale.

  Would you be interested in connecting with them? Let me know."

Subject: "[type] owners in [city]"
"""
import sys, io, json, re, os, warnings, time, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
warnings.filterwarnings('ignore')
from dotenv import load_dotenv
load_dotenv(r"C:\Users\evane\Documents\Coding\scorecard\re2scorecard2026\.env")
from google.cloud import bigquery
from datetime import datetime, timezone

key    = os.getenv("SMARTLEAD_API_KEY")
bq     = bigquery.Client(project="tenant-recruitin-1575995920662")
CID    = 3060221
TABLE  = "tenant-recruitin-1575995920662.PLG_OUTBOUND.bounce_reengagement_bb_20260326"
LOCAL  = r"C:\Users\evane\AppData\Local\Temp\bounce\bounce_bb_verified.json"
os.makedirs(r"C:\Users\evane\AppData\Local\Temp\bounce", exist_ok=True)

# ── Step 1: BQ — get bounced leads + seq count ────────────────────────────────
print("Querying BQ...")
bq_rows = {r["email"]: r["max_seq_sent"] for r in [dict(x) for x in bq.query("""
    SELECT lead_email AS email, MAX(sequence_number) AS max_seq_sent
    FROM `tenant-recruitin-1575995920662.MARKETSEGMENTDATA.ALL_SMARTLEAD_EMAILS`
    WHERE lead_category = 'Sender Originated Bounce'
      AND campaign_id = 3060221
    GROUP BY lead_email
""").result()]}
skip    = sum(1 for v in bq_rows.values() if v >= 3)
include = {e: s for e, s in bq_rows.items() if s < 3}
print(f"  Total bounced: {len(bq_rows)} | skip (seq>=3): {skip} | include: {len(include)}")

# ── Step 2: SmartLead — pull all leads + custom fields ───────────────────────
print("Pulling SmartLead leads...")
sl = {}
offset = 0
while True:
    resp = requests.get(f"https://server.smartlead.ai/api/v1/campaigns/{CID}/leads",
        params={"api_key": key, "limit": 100, "offset": offset}, timeout=30).json()
    batch = resp.get("data", resp) if isinstance(resp, dict) else resp
    if not batch: break
    for item in batch:
        lead = item.get("lead", item)
        em = (lead.get("email") or "").lower().strip()
        cf = lead.get("custom_fields") or {}
        sl[em] = {
            "first_name":   lead.get("first_name", ""),
            "last_name":    lead.get("last_name",  ""),
            "company_name": lead.get("company_name", ""),
            "location":     lead.get("location", ""),
            "subject1": cf.get("subject1", ""),
            "body1":    cf.get("body1", ""),
            "body2":    cf.get("body2", ""),
            "body3":    cf.get("body3", ""),
        }
    if len(batch) < 100: break
    offset += 100
    time.sleep(0.25)
print(f"  SmartLead leads pulled: {len(sl)}")

# ── Step 3: helpers ───────────────────────────────────────────────────────────

def normalize(text):
    """Convert \n line breaks to <br> for SmartLead."""
    if not text: return ""
    if "<br" in text: return text
    return text.replace("\n\n", "<br><br>").replace("\n", "<br>")

def extract_type_city(body2):
    """
    Extract business type and city from body2.
    Pattern: "...about [TYPE] owners in [CITY] who may be..."
    Returns (type, city) or (None, None).
    """
    m = re.search(r"about (.+?) owners in (.+?) who", body2 or "", re.IGNORECASE)
    if m:
        btype = m.group(1).strip()
        city  = m.group(2).strip()
        # strip trailing state (e.g. "Charleston, South Carolina" → "Charleston")
        city = city.split(",")[0].strip()
        return btype, city
    return None, None

def build_new_email1(first_name, btype, city):
    """Fresh Email1 for seq=2 leads."""
    name = first_name.strip() if first_name else "there"
    return (
        f"{name}, we have {btype} business owners in {city} "
        f"who may be exploring a sale.<br><br>"
        f"Would you be interested in connecting with them? Let me know."
    )

def build_new_subject(btype, city):
    return f"{btype} owners in {city}"

# ── Step 4: build lead records ────────────────────────────────────────────────
print("\nBuilding lead records...")
leads        = []
issues       = []
seq1_count   = 0
seq2_count   = 0
missing_copy = 0

for email, seq in include.items():
    d = sl.get(email)
    if not d:
        issues.append(f"NOT_IN_SL: {email}")
        continue

    fn      = d["first_name"]
    body1   = normalize(d["body1"])
    body2   = normalize(d["body2"])
    body3   = normalize(d["body3"])
    subj1   = d["subject1"]

    if not body1 and seq == 1:
        issues.append(f"NO_BODY1: {email}")
        missing_copy += 1
        continue

    if seq == 1:
        # Use existing copy as-is
        email1  = body1
        email2  = body2
        email3  = body3
        subject = subj1
        seq1_count += 1

    else:  # seq == 2
        # Extract type + city from body2
        btype, city = extract_type_city(body2)
        if not btype or not city:
            issues.append(f"CANT_EXTRACT_TYPE_CITY: {email} | body2={body2[:80]}")
            # fallback: use body1 modified
            email1  = body1
            subject = subj1
        else:
            email1  = build_new_email1(fn, btype, city)
            subject = build_new_subject(btype, city)

        email2 = body2
        email3 = body3
        seq2_count += 1

    leads.append({
        "email":            email,
        "first_name":       fn,
        "last_name":        d["last_name"],
        "company_name":     d["company_name"],
        "location":         d["location"],
        "original_campaign":"Business Brokers - Repush 03.19",
        "max_seq_sent":     seq,
        "Subject1":         subject,
        "Email1":           email1,
        "Email2":           email2,
        "Email3":           email3,
    })

print(f"  seq=1 leads: {seq1_count}")
print(f"  seq=2 leads: {seq2_count}")
print(f"  Total built: {len(leads)}")
if issues:
    print(f"\n  ISSUES ({len(issues)}):")
    for i in issues[:10]: print(f"    {i}")

# ── Step 5: spot-check ────────────────────────────────────────────────────────
print("\n=== SPOT-CHECK seq=1 ===")
s1_samples = [l for l in leads if l["max_seq_sent"] == 1][:3]
for l in s1_samples:
    print(f"\n  {l['email']} | {l['company_name']}")
    print(f"  Subject1: {l['Subject1']}")
    print(f"  Email1:   {l['Email1'][:200]}")
    print(f"  Email2:   {l['Email2'][:150]}")
    print(f"  Email3:   {l['Email3'][:150]}")

print("\n=== SPOT-CHECK seq=2 (new Email1) ===")
s2_samples = [l for l in leads if l["max_seq_sent"] == 2][:3]
for l in s2_samples:
    print(f"\n  {l['email']} | {l['company_name']}")
    print(f"  Subject1 (NEW): {l['Subject1']}")
    print(f"  Email1   (NEW): {l['Email1']}")
    print(f"  Email2 (reuse): {l['Email2'][:150]}")
    print(f"  Email3 (reuse): {l['Email3'][:150]}")

# ── Step 6: consistency checks ────────────────────────────────────────────────
print("\n=== CONSISTENCY CHECKS ===")
check_issues = []
for l in leads:
    e1, e2, e3, subj = l["Email1"], l["Email2"], l["Email3"], l["Subject1"]
    if not subj:   check_issues.append(f"MISSING_SUBJECT: {l['email']}")
    if not e1:     check_issues.append(f"MISSING_E1: {l['email']}")
    if not e2:     check_issues.append(f"MISSING_E2: {l['email']}")
    if not e3:     check_issues.append(f"MISSING_E3: {l['email']}")
    # seq=2 new Email1 should NOT contain "reached out a few days ago"
    if l["max_seq_sent"] == 2 and "reached out a few days ago" in e1.lower():
        check_issues.append(f"SEQ2_OLD_HOOK_IN_E1: {l['email']}")
    # seq=2 Email2 SHOULD contain "reached out a few days ago"
    if l["max_seq_sent"] == 2 and "reached out a few days ago" not in e2.lower():
        check_issues.append(f"SEQ2_MISSING_FOLLOWUP_IN_E2: {l['email']}")
    # Email1 should not say "reached out a few days ago" for seq=1 either
    if l["max_seq_sent"] == 1 and "reached out a few days ago" in e1.lower():
        check_issues.append(f"SEQ1_FOLLOWUP_IN_E1: {l['email']}")
    # No links
    if re.search(r"https?://|<a\s", e1 + e2 + e3, re.IGNORECASE):
        check_issues.append(f"LINK_FOUND: {l['email']}")
    # seq=2 - city/type in new Email1 should match city/type in Email2
    if l["max_seq_sent"] == 2:
        btype2, city2 = extract_type_city(e2)
        if btype2 and city2:
            if city2.lower() not in e1.lower():
                check_issues.append(f"CITY_MISMATCH E1/E2: {l['email']} | E1 city? E2 city={city2}")
            if btype2.lower() not in e1.lower():
                check_issues.append(f"TYPE_MISMATCH E1/E2: {l['email']} | type={btype2}")

if check_issues:
    print(f"  Issues found: {len(check_issues)}")
    for i in check_issues[:20]: print(f"    {i}")
else:
    print("  All checks passed!")

# ── Step 7: save JSON + BQ ────────────────────────────────────────────────────
with open(LOCAL, "w") as f:
    json.dump(leads, f, indent=2)
print(f"\nLocal JSON saved: {LOCAL}")

schema = [
    bigquery.SchemaField("email","STRING"), bigquery.SchemaField("first_name","STRING"),
    bigquery.SchemaField("last_name","STRING"), bigquery.SchemaField("company_name","STRING"),
    bigquery.SchemaField("location","STRING"),
    bigquery.SchemaField("original_campaign","STRING"), bigquery.SchemaField("max_seq_sent","INT64"),
    bigquery.SchemaField("subject1","STRING"), bigquery.SchemaField("email1","STRING"),
    bigquery.SchemaField("email2","STRING"), bigquery.SchemaField("email3","STRING"),
    bigquery.SchemaField("stage","STRING"), bigquery.SchemaField("created_at","TIMESTAMP"),
]
upload = [{
    "email": r["email"], "first_name": r["first_name"], "last_name": r["last_name"],
    "company_name": r["company_name"], "location": r["location"],
    "original_campaign": r["original_campaign"], "max_seq_sent": r["max_seq_sent"],
    "subject1": r["Subject1"], "email1": r["Email1"],
    "email2": r["Email2"], "email3": r["Email3"],
    "stage": "copy_built", "created_at": datetime.now(timezone.utc).isoformat(),
} for r in leads]

job = bq.load_table_from_json(upload, TABLE, job_config=bigquery.LoadJobConfig(
    schema=schema, write_disposition="WRITE_TRUNCATE", create_disposition="CREATE_IF_NEEDED"))
job.result()
print(f"BQ saved: {len(upload)} rows → {TABLE}")
