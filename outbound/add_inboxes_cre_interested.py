#!/usr/bin/env python3
"""
Add 14 inboxes to SLG_CRE_Email_hyperpersonal_interested_v1 (campaign 3093339).

Selected: alternating users and domains, all 15-day warm, 15/day each.
"""
import os, sys, io, requests, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from dotenv import load_dotenv
load_dotenv(r"C:\Users\evane\Documents\Coding\scorecard\re2scorecard2026\.env")
from google.cloud import bigquery

KEY        = os.getenv("SMARTLEAD_API_KEY")
BASE       = "https://server.smartlead.ai/api/v1"
TARGET_CID = 3093339
bq         = bigquery.Client(project="tenant-recruitin-1575995920662")

TARGET_EMAILS = [
    "carlson@re2local.com",
    "griffin@tryre2hub.com",
    "erik@tryre2labs.com",
    "harold@tryresquaredsolutions.com",
    "tyler@useresquaredlabs.com",
    "carlson@useresquaredonline.com",
    "erik@re2local.com",
    "griffin@tryre2labs.com",
    "harold@useresquaredlabs.com",
    "tyler@tryre2hub.com",
    "carlson@tryresquaredsolutions.com",
    "erik@useresquaredonline.com",
    "griffin@useresquaredlabs.com",
    "harold@tryre2hub.com",
]

def api(method, path, **kwargs):
    url = f"{BASE}/{path.lstrip('/')}"
    params = kwargs.pop("params", {})
    params["api_key"] = KEY
    r = getattr(requests, method)(url, params=params, timeout=30, **kwargs)
    if r.status_code == 429:
        time.sleep(5)
        r = getattr(requests, method)(url, params=params, timeout=30, **kwargs)
    return r

# ── Step 1: Resolve account IDs from BQ ───────────────────────────────────────
print("Resolving account IDs from BQ...")
emails_str = ", ".join(f"'{e}'" for e in TARGET_EMAILS)
rows = list(bq.query(f"""
    SELECT account_id, from_email, message_per_day,
        DATE_DIFF(CURRENT_DATE(), DATE(warmup_created_at), DAY) AS warmup_age_days
    FROM `tenant-recruitin-1575995920662.MARKETSEGMENTDATA.ALL_SMARTLEAD_ACCOUNTS`
    WHERE LOWER(from_email) IN ({emails_str})
""").result())

found = {r["from_email"].lower(): dict(r) for r in rows}

print(f"\n{'Email':<45} {'ID':>12}  {'msg/day':>8}  {'warmup_age':>10}")
print("-" * 80)
inbox_ids = []
missing = []
for email in TARGET_EMAILS:
    info = found.get(email.lower())
    if info:
        inbox_ids.append(info["account_id"])
        print(f"  {email:<43} {info['account_id']:>12}  {info['message_per_day']:>8}  {info['warmup_age_days']:>8}d")
    else:
        missing.append(email)
        print(f"  {email:<43} NOT FOUND IN BQ")

if missing:
    print(f"\nERROR: {len(missing)} inbox(es) not found in BQ. Aborting.")
    sys.exit(1)

print(f"\nResolved {len(inbox_ids)} inbox IDs. Total new capacity: {len(inbox_ids)*15}/day")

# ── Step 2: Confirm before adding ─────────────────────────────────────────────
print(f"\nAbout to add {len(inbox_ids)} inboxes to campaign {TARGET_CID}.")
confirm = input("Proceed? (yes/no): ").strip().lower()
if confirm != "yes":
    print("Aborted.")
    sys.exit(0)

# ── Step 3: Add inboxes to campaign ───────────────────────────────────────────
print(f"\nAdding inboxes to campaign {TARGET_CID}...")
r = api("post", f"campaigns/{TARGET_CID}/email-accounts", json={"email_account_ids": inbox_ids})
print(f"  Status: {r.status_code}")
print(f"  Response: {r.text[:200]}")

if r.status_code in (200, 201):
    print(f"\nDone! {len(inbox_ids)} inboxes added to campaign {TARGET_CID}.")
    print(f"  Additional capacity: +{len(inbox_ids)*15}/day")
    print(f"  New total estimate: ~575/day (21 existing + 14 new)")
else:
    print(f"\nERROR adding inboxes: {r.status_code} {r.text}")
