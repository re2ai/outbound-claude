#!/usr/bin/env python3
"""Re-pull Email2 from SmartLead for all 501 leads and re-transform cleanly."""
import re, warnings, json, os, requests, time
from google.cloud import bigquery
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv(r"C:\Users\evane\Documents\Coding\scorecard\re2scorecard2026\.env")
warnings.filterwarnings("ignore")

key = os.getenv("SMARTLEAD_API_KEY")
bq  = bigquery.Client(project="tenant-recruitin-1575995920662")
TABLE = "tenant-recruitin-1575995920662.PLG_OUTBOUND.bounce_reengagement_plg_20260326"
rows = [dict(r) for r in bq.query(f"SELECT * FROM `{TABLE}`").result()]
print(f"Loaded {len(rows)} rows from BQ")

# ── helpers ──────────────────────────────────────────────────────────────────

def strip_links(html):
    return re.sub(r"<a\s[^>]*>.*?</a>", "", html or "", flags=re.IGNORECASE | re.DOTALL)

def normalize(text):
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\n\n", "<br><br>")
    text = text.replace("\n", "<br>")
    text = re.sub(r"(<br>){3,}", "<br><br>", text, flags=re.IGNORECASE)
    return text

def clean_br(t):
    return re.sub(r"^(\s*<br\s*/?>\s*)+|(\s*<br\s*/?>\s*)+$", "", t.strip(), flags=re.IGNORECASE)

def transform_e2(raw):
    body = normalize(strip_links(raw))
    body = re.sub(r"<br\s*/?>\s*<br\s*/?>\s*This is for a free account.*", "", body,
                  flags=re.IGNORECASE | re.DOTALL)
    body = re.sub(r"<br\s*/?>\s*<br\s*/?>\s*Happy to send.*", "", body,
                  flags=re.IGNORECASE | re.DOTALL)
    body = clean_br(body)
    return body + "<br><br>Just reply to this email and I'll send you the link."

# ── campaign map ─────────────────────────────────────────────────────────────

CAMP_IDS = {
    "PLG - Commercial Cleaners":                  2747341,
    "PLG - IT Solutions":                         2785978,
    "PLG - Local Marketing - Claude":             3066249,
    "PLG - Insurance - Clean v2 - Claude":        3033907,
    "PLG - Web Design":                           2760865,
    "PLG - Event Catering":                       2911388,
    "PLG - Advertising/Billboard - SmartProspect":3065024,
    "PLG - Commercial Landscaping Companies":     2760085,
    "PLG - Staffing - Claude":                    3085386,
    "PLG - Commercial Insurance - Blunt - Claude":2986711,
    "PLG - Local Marketing Agencies":             2780890,
    "PLG - Security Campaign":                    2712115,
    "PLG - Janitorial":                           2947140,
    "PLG - Marketing Services":                   3005402,
    "PLG - Local Signage Businesses - copy":      2698429,
    "PLG - Commercial Insurance - Claude":        2980072,
    "PLG - IT Solutions - Web Enrich - Claude":   3012037,
}
FIELD_OVERRIDES = {3065024: {"Email2": "email2_(2)"}}

# ── build email->cid map ──────────────────────────────────────────────────────

email_to_cid = {}
for r in rows:
    cid = CAMP_IDS.get(r.get("original_campaign", ""))
    if cid:
        email_to_cid[r["email"]] = cid

# ── re-pull Email2 per campaign ───────────────────────────────────────────────

fixed_e2 = {}
for camp_name, cid in CAMP_IDS.items():
    camp_emails = {e for e, c in email_to_cid.items() if c == cid}
    if not camp_emails:
        continue
    e2_field = FIELD_OVERRIDES.get(cid, {}).get("Email2", "Email2")
    print(f"  {camp_name[:50]:50} | {len(camp_emails):3} leads | field={e2_field}", end=" ... ", flush=True)
    found = 0
    offset = 0
    while True:
        resp = requests.get(
            f"https://server.smartlead.ai/api/v1/campaigns/{cid}/leads",
            params={"api_key": key, "limit": 100, "offset": offset},
            timeout=30,
        ).json()
        batch = resp.get("data", resp) if isinstance(resp, dict) else resp
        if not batch:
            break
        for item in batch:
            lead = item.get("lead", item)
            email = (lead.get("email") or "").lower().strip()
            if email in camp_emails:
                cf = lead.get("custom_fields") or {}
                raw = cf.get(e2_field, "")
                fixed_e2[email] = transform_e2(raw)
                found += 1
        if len(batch) < 100:
            break
        offset += 100
        time.sleep(0.25)
    print(f"fixed {found}")

print(f"\nTotal re-pulled: {len(fixed_e2)}")

# ── patch rows ────────────────────────────────────────────────────────────────

patched = 0
for r in rows:
    if r["email"] in fixed_e2:
        r["email2"] = fixed_e2[r["email"]]
        patched += 1
print(f"Patched: {patched}")

# ── spot-check ────────────────────────────────────────────────────────────────

sample = next((r for r in rows if r["email"] == "ally@cc.media"), rows[0])
print(f"\nSample ({sample['email']}) email2:")
print(repr(sample.get("email2", "")[:300]))

# Simple broken check: first <br> should appear within first 100 chars
def is_broken(body):
    if not body:
        return False
    first_br = (body.lower() + "<br>").find("<br")
    return first_br > 120 and len(body) > 150

still_broken = [r for r in rows if is_broken(r.get("email2", ""))]
print(f"\nStill broken: {len(still_broken)}")
for r in still_broken[:3]:
    print(f"  {r['email']}: {r.get('email2','')[:100]}")

# ── upload to BQ ─────────────────────────────────────────────────────────────

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
    "subject1": r.get("subject1", ""), "email1": r.get("email1", ""),
    "email2": r.get("email2", ""), "email3": r.get("email3", ""),
    "stage": "copy_done", "created_at": datetime.now(timezone.utc).isoformat(),
} for r in rows]

job = bq.load_table_from_json(upload, TABLE, job_config=bigquery.LoadJobConfig(
    schema=schema, write_disposition="WRITE_TRUNCATE", create_disposition="CREATE_IF_NEEDED"))
job.result()
print(f"\nBQ updated: {len(upload)} rows.")

# ── sync local JSON ───────────────────────────────────────────────────────────

LOCAL = r"C:\Users\evane\AppData\Local\Temp\bounce\bounce_plg_verified.json"
with open(LOCAL) as f:
    local = json.load(f)
bq_map = {r["email"]: r for r in rows}
for l in local:
    b = bq_map.get(l["email"])
    if b:
        l["Email1"] = b["email1"]
        l["Email2"] = b["email2"]
        l["Email3"] = b["email3"]
with open(LOCAL, "w") as f:
    json.dump(local, f, indent=2)
print("Local JSON synced.")
