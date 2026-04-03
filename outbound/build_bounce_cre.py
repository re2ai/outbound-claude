#!/usr/bin/env python3
"""
Build CRE Bounce Re-engagement leads.

Source campaigns (active CRE):
  2996922 - CRE - Loopnet Repush 2
  2952772 - CRE - Loopnet Repush
  2780527 - CRE - Crexi - List 1

Rules:
  seq=1 → use body1/body2 as Email1/2, generate fresh Email3
  seq=2 → generate new Email1 (address hook), reuse body2 as Email2, generate Email3
  seq=3 → skip

Custom fields in SmartLead: subject1, body1, body2, body3
"""
import sys, io, os, json, re, time, warnings, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
warnings.filterwarnings('ignore')
from dotenv import load_dotenv
load_dotenv(r"C:\Users\evane\Documents\Coding\scorecard\re2scorecard2026\.env")
from google.cloud import bigquery
from datetime import datetime, timezone

KEY   = os.getenv("SMARTLEAD_API_KEY")
bq    = bigquery.Client(project="tenant-recruitin-1575995920662")
CAMP_IDS = [2996922, 2952772, 2780527]
LOCAL    = r"C:\Users\evane\AppData\Local\Temp\bounce\bounce_cre_raw.json"
TABLE    = "tenant-recruitin-1575995920662.SLG_OUTBOUND.bounce_reengagement_cre_20260401"
os.makedirs(r"C:\Users\evane\AppData\Local\Temp\bounce", exist_ok=True)

# ── Step 1: BQ — bounced leads + seq count ────────────────────────────────────
print("Querying BQ...")
bq_rows = {}
for r in [dict(x) for x in bq.query("""
    SELECT lead_email AS email, campaign_id, campaign_name,
           MAX(sequence_number) AS max_seq_sent,
           MAX(sent_time) AS last_sent_time
    FROM `tenant-recruitin-1575995920662.MARKETSEGMENTDATA.ALL_SMARTLEAD_EMAILS`
    WHERE lead_category = 'Sender Originated Bounce'
      AND campaign_id IN (2996922, 2952772, 2780527)
      AND lead_email IS NOT NULL AND TRIM(lead_email) != ''
    GROUP BY lead_email, campaign_id, campaign_name
""").result()]:
    em = r["email"].lower().strip()
    # Keep latest campaign per email
    if em not in bq_rows or r["last_sent_time"] > bq_rows[em]["last_sent_time"]:
        bq_rows[em] = r

skip    = sum(1 for v in bq_rows.values() if v["max_seq_sent"] >= 3)
include = {e: r for e, r in bq_rows.items() if r["max_seq_sent"] < 3}
print(f"  Unique bounced: {len(bq_rows)} | skip (seq>=3): {skip} | include: {len(include)}")

# ── Step 2: SmartLead — pull all leads + custom fields ───────────────────────
print("Pulling SmartLead leads...")
sl = {}
for cid in CAMP_IDS:
    offset, count = 0, 0
    print(f"  Campaign {cid}...", end=" ", flush=True)
    while True:
        resp = requests.get(f"https://server.smartlead.ai/api/v1/campaigns/{cid}/leads",
            params={"api_key": KEY, "limit": 100, "offset": offset}, timeout=30).json()
        batch = resp.get("data", resp) if isinstance(resp, dict) else resp
        if not batch: break
        for item in batch:
            lead = item.get("lead", item)
            em = (lead.get("email") or "").lower().strip()
            cf = lead.get("custom_fields") or {}
            sl[em] = {
                "first_name":   lead.get("first_name", ""),
                "last_name":    lead.get("last_name", ""),
                "company_name": lead.get("company_name", ""),
                "location":     lead.get("location", ""),
                "subject1": cf.get("subject1", "") or cf.get("Subject1", ""),
                "body1":    cf.get("body1", "")    or cf.get("Email1", ""),
                "body2":    cf.get("body2", "")    or cf.get("Email2", ""),
            }
            count += 1
        if len(batch) < 100: break
        offset += 100
        time.sleep(0.2)
    print(f"{count}")
print(f"  Total: {len(sl)}")

# ── helpers ───────────────────────────────────────────────────────────────────

def normalize(text):
    if not text: return ""
    if "<br" in text: return text
    return text.replace("\n\n", "<br><br>").replace("\n", "<br>")

def extract_address(body1):
    """Extract address from 'I saw your listing for [ADDRESS] and'"""
    m = re.search(r"listing for (.+?)(?:\s+and\s+|\s*\n|\s*<br)", body1 or "", re.IGNORECASE)
    return m.group(1).strip() if m else None

def extract_space_type(body2):
    """Extract space type from 'for the X SF of [TYPE] Space Available'"""
    m = re.search(r"for the .+? of (.+?) Space Available", body2 or "", re.IGNORECASE)
    return m.group(1).strip() if m else None

def build_new_email1(fn, address, body1):
    """Fresh Email1 for seq=2 leads — hooks on their listing address."""
    name = fn.strip() if fn else "there"
    # Try to get address; fall back to "your listing"
    loc = address if address else "your listing"
    return (
        f"Hey {name}, are you still looking for tenants for {loc}?<br><br>"
        f"We currently work with the biggest CRE companies helping them get local businesses "
        f"for their commercial spaces.<br><br>"
        f"Would that make sense for you?"
    )

def build_email3(fn):
    """Fresh Email3 for all leads — soft close."""
    name = fn.strip() if fn else "there"
    return (
        f"Hey {name}, maybe finding tenants for your listing is not top priority right now, "
        f"but if it ever comes handy to have an automated way to get them all in your inbox "
        f"in a few clicks, just reply."
    )

def build_new_subject(address):
    """Subject for seq=2 new Email1."""
    if address:
        return f"Tenants for {address}"
    return "Finding tenants for your listing"

# ── Step 3: build lead records ────────────────────────────────────────────────
print("\nBuilding lead records...")
leads      = []
issues     = []
seq1_count = 0
seq2_count = 0

for email, bq_row in include.items():
    d = sl.get(email)
    if not d:
        issues.append(f"NOT_IN_SL: {email}")
        continue

    fn    = d["first_name"]
    body1 = normalize(d["body1"])
    body2 = normalize(d["body2"])
    subj1 = d["subject1"]
    seq   = bq_row["max_seq_sent"]

    if not body1:
        issues.append(f"NO_BODY1: {email}")
        continue

    email3 = build_email3(fn)

    if seq == 1:
        email1  = body1
        email2  = body2
        subject = subj1
        seq1_count += 1
    else:  # seq == 2
        address = extract_address(body1)
        email1  = build_new_email1(fn, address, body1)
        email2  = body2
        subject = build_new_subject(address)
        seq2_count += 1

    leads.append({
        "email":             email,
        "first_name":        fn,
        "last_name":         d["last_name"],
        "company_name":      d["company_name"],
        "location":          d["location"],
        "original_campaign": bq_row["campaign_name"],
        "max_seq_sent":      seq,
        "Subject1":          subject,
        "Email1":            email1,
        "Email2":            email2,
        "Email3":            email3,
    })

print(f"  seq=1: {seq1_count} | seq=2: {seq2_count} | issues: {len(issues)}")
if issues:
    for i in issues[:10]: print(f"    {i}")

# ── Step 4: spot check ────────────────────────────────────────────────────────
print("\n=== SPOT CHECK seq=1 ===")
for l in [x for x in leads if x["max_seq_sent"] == 1][:2]:
    print(f"\n  {l['email']} | {l['company_name']}")
    print(f"  Subject1: {l['Subject1']}")
    print(f"  Email1:   {l['Email1'][:200]}")
    print(f"  Email2:   {l['Email2'][:150]}")
    print(f"  Email3:   {l['Email3']}")

print("\n=== SPOT CHECK seq=2 (new Email1) ===")
for l in [x for x in leads if x["max_seq_sent"] == 2][:2]:
    print(f"\n  {l['email']} | {l['company_name']}")
    print(f"  Subject1 (NEW): {l['Subject1']}")
    print(f"  Email1   (NEW): {l['Email1']}")
    print(f"  Email2 (reuse): {l['Email2'][:150]}")
    print(f"  Email3   (NEW): {l['Email3']}")

# ── Step 5: consistency checks ────────────────────────────────────────────────
print("\n=== CONSISTENCY CHECKS ===")
check_issues = []
for l in leads:
    e1, e2, e3, s1 = l["Email1"], l["Email2"], l["Email3"], l["Subject1"]
    if not s1: check_issues.append(f"MISSING_SUBJECT: {l['email']}")
    if not e1: check_issues.append(f"MISSING_E1: {l['email']}")
    if not e2: check_issues.append(f"MISSING_E2: {l['email']}")
    if not e3: check_issues.append(f"MISSING_E3: {l['email']}")
    if re.search(r"https?://|<a\s", e1+e2+e3, re.IGNORECASE):
        check_issues.append(f"LINK_FOUND: {l['email']}")
    if l["max_seq_sent"] == 2:
        if "we have a platform" in e1.lower() or "i saw your listing for" in e1.lower():
            check_issues.append(f"SEQ2_OLD_BODY1: {l['email']}")
    if "free account" in (e1+e2+e3).lower() or "send you the link" in (e1+e2+e3).lower():
        check_issues.append(f"PLG_LANGUAGE: {l['email']}")
    if "\n" in e1+e2+e3:
        check_issues.append(f"RAW_NEWLINE: {l['email']}")

if check_issues:
    print(f"  Issues: {len(check_issues)}")
    for i in check_issues[:15]: print(f"    {i}")
else:
    print("  All clean!")

# ── Step 6: save JSON + BQ ────────────────────────────────────────────────────
with open(LOCAL, "w") as f:
    json.dump(leads, f, indent=2)
print(f"\nLocal JSON: {LOCAL}")

schema = [
    bigquery.SchemaField("email","STRING"), bigquery.SchemaField("first_name","STRING"),
    bigquery.SchemaField("last_name","STRING"), bigquery.SchemaField("company_name","STRING"),
    bigquery.SchemaField("location","STRING"), bigquery.SchemaField("original_campaign","STRING"),
    bigquery.SchemaField("max_seq_sent","INT64"), bigquery.SchemaField("subject1","STRING"),
    bigquery.SchemaField("email1","STRING"), bigquery.SchemaField("email2","STRING"),
    bigquery.SchemaField("email3","STRING"), bigquery.SchemaField("stage","STRING"),
    bigquery.SchemaField("created_at","TIMESTAMP"),
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
