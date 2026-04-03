#!/usr/bin/env python3
"""
Find which SmartLead campaigns each inbox is assigned to.
"""
import os, sys, io, requests, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from dotenv import load_dotenv
load_dotenv(r"C:\Users\evane\Documents\Coding\scorecard\re2scorecard2026\.env")

KEY  = os.getenv("SMARTLEAD_API_KEY")
BASE = "https://server.smartlead.ai/api/v1"

TARGET_EMAILS = [
    "leonardo@topre2sales.com",
    "jalen@topre2sales.com",
    "tyler@topre2sales.com",
    "leonardo@tryresquaredsales.com",
    "tyler@tryresquaredsales.com",
    "jalen@tryresquaredsales.com",
    "tyler@useresquaredsales.com",
    "leonardo@useresquaredsales.com",
    "jalen@useresquaredsales.com",
]

def get(path, params=None):
    p = {"api_key": KEY, **(params or {})}
    r = requests.get(f"{BASE}/{path.lstrip('/')}", params=p, timeout=30)
    if r.status_code == 429:
        time.sleep(5)
        r = requests.get(f"{BASE}/{path.lstrip('/')}", params=p, timeout=30)
    r.raise_for_status()
    return r.json()

# Step 1: find account IDs for target emails (paginated)
print("Fetching all email accounts...")
accounts = []
offset = 0
while True:
    page = get("email-accounts", {"limit": 100, "offset": offset})
    if not page:
        break
    accounts.extend(page)
    if len(page) < 100:
        break
    offset += 100
print(f"  Total accounts: {len(accounts)}")
target_ids = {}
for a in accounts:
    email = a.get("from_email") or a.get("email") or ""
    if email.lower() in [e.lower() for e in TARGET_EMAILS]:
        target_ids[a["id"]] = email
        print(f"  Found: {email}  (id={a['id']})")

if not target_ids:
    print("ERROR: None of the target emails found in SmartLead accounts.")
    sys.exit(1)

# Step 2: check every campaign for these inboxes
print(f"\nFetching all campaigns...")
campaigns = get("campaigns/")
print(f"  Total campaigns: {len(campaigns)}")

# inbox_id -> list of campaign names
results = {eid: [] for eid in target_ids}

for camp in campaigns:
    cid   = camp["id"]
    cname = camp["name"]
    cstat = camp.get("status", "?")
    try:
        inboxes = get(f"campaigns/{cid}/email-accounts")
        inbox_list = inboxes if isinstance(inboxes, list) else inboxes.get("data", [])
        for inbox in inbox_list:
            iid = inbox.get("id") or inbox.get("email_account_id")
            if iid in target_ids:
                results[iid].append(f"{cname}  [{cstat}]")
    except Exception as e:
        print(f"  WARN: campaign {cid} ({cname}): {e}")
    time.sleep(0.15)

# Step 3: print results
print("\n" + "="*70)
print("INBOX → CAMPAIGNS")
print("="*70)
for iid, campaigns_assigned in results.items():
    email = target_ids[iid]
    print(f"\n{email}")
    if campaigns_assigned:
        for c in campaigns_assigned:
            print(f"  → {c}")
    else:
        print("  (not assigned to any campaign)")
