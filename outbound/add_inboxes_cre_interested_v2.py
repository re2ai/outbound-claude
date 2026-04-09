#!/usr/bin/env python3
"""
Add 20 inboxes to SLG_CRE_Email_HyperPersonal_Interested_v1 (campaign 3093339).
Set max_leads_per_day to 500.

Selected pools:
  - 10x 38d inboxes (10/day each): tyler x9 + leonardo x1
  - 5x 20d inboxes (15/day each): erik x1 + tyler x4
  - 1x 16d inbox (15/day): erik x1
  - 4x 15d inboxes (10/day each): tyler x2 + leonardo x1 + jalen x1
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
    # 38d pool — 10/day each
    "tyler@getresquaredsales.com",
    "tyler@webre2tech.com",
    "tyler@topre2techai.com",
    "tyler@there2sales.com",
    "tyler@webresquaredsales.com",
    "tyler@useresquaredsales.com",
    "tyler@usere2tech.com",
    "tyler@usere2sales.com",
    "tyler@onresquaredsales.com",
    "leonardo@tryresquared.com",
    # 20d pool — 15/day each
    "erik@localbusinessre2.com",
    "tyler@joinre2business.com",
    "tyler@getre2leads.com",
    "tyler@clickre2.com",
    "tyler@getre2business.com",
    # 16d — 15/day
    "erik@clickresquaredai.com",
    # 15d pool — 10/day each
    "tyler@webre2sales.com",
    "leonardo@tryre2ai.com",
    "jalen@byre2tech.com",
    "tyler@tryre2ai.com",
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
        DATE_DIFF(CURRENT_DATE(), DATE(warmup_created_at), DAY) AS warmup_age_days,
        warmup_reputation
    FROM `tenant-recruitin-1575995920662.MARKETSEGMENTDATA.ALL_SMARTLEAD_ACCOUNTS`
    WHERE LOWER(from_email) IN ({emails_str})
""").result())

found = {r["from_email"].lower(): dict(r) for r in rows}

print(f"\n{'Email':<45} {'ID':>12}  {'msg/day':>8}  {'age':>6}  {'rep':>6}")
print("-" * 85)
inbox_ids = []
missing = []
for email in TARGET_EMAILS:
    info = found.get(email.lower())
    if info:
        inbox_ids.append(info["account_id"])
        print(f"  {email:<43} {info['account_id']:>12}  {info['message_per_day']:>8}  {info['warmup_age_days']:>4}d  {info['warmup_reputation']:>6}")
    else:
        missing.append(email)
        print(f"  {email:<43} NOT FOUND IN BQ")

if missing:
    print(f"\nERROR: {len(missing)} inbox(es) not found in BQ. Aborting.")
    sys.exit(1)

total_new_capacity = sum(found[e.lower()]["message_per_day"] for e in TARGET_EMAILS)
print(f"\nResolved {len(inbox_ids)} inboxes. Additional capacity: +{total_new_capacity}/day")
print(f"New total: ~{450 + total_new_capacity}/day | New leads/day (50%): ~{(450 + total_new_capacity)//2}/day")

# ── Step 2: Confirm ────────────────────────────────────────────────────────────
print(f"\nAbout to:")
print(f"  1. Add {len(inbox_ids)} inboxes to campaign {TARGET_CID}")
print(f"  2. Set max_leads_per_day to 500")
confirm = input("\nProceed? (yes/no): ").strip().lower()
if confirm != "yes":
    print("Aborted.")
    sys.exit(0)

# ── Step 3: Add inboxes ────────────────────────────────────────────────────────
print(f"\nAdding inboxes to campaign {TARGET_CID}...")
r = api("post", f"campaigns/{TARGET_CID}/email-accounts", json={"email_account_ids": inbox_ids})
print(f"  Status: {r.status_code}")
print(f"  Response: {r.text[:300]}")

if r.status_code not in (200, 201):
    print(f"\nERROR adding inboxes. Aborting before settings update.")
    sys.exit(1)

print(f"\n  {len(inbox_ids)} inboxes added.")

# ── Step 4: Update max_leads_per_day ──────────────────────────────────────────
print(f"\nUpdating max_leads_per_day to 500...")
r2 = api("post", f"campaigns/{TARGET_CID}", json={"max_leads_per_day": 500})
print(f"  Status: {r2.status_code}")
print(f"  Response: {r2.text[:300]}")

if r2.status_code in (200, 201):
    print(f"\nDone!")
    print(f"  Inboxes added: {len(inbox_ids)}")
    print(f"  max_leads_per_day: 500")
    print(f"  New capacity: ~{450 + total_new_capacity}/day total | ~{(450 + total_new_capacity)//2}/day new leads")
else:
    print(f"\nInboxes added OK but ERROR updating max_leads_per_day: {r2.status_code} {r2.text}")
