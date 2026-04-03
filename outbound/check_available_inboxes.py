#!/usr/bin/env python3
"""
Check inboxes available to add to a campaign.

- Queries BQ for healthy inboxes with message_per_day > 10 and no active campaigns
- Fetches current inboxes assigned to the target campaign
- Shows what can be added
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

def sl_get(path, params=None):
    p = {"api_key": KEY, **(params or {})}
    r = requests.get(f"{BASE}/{path.lstrip('/')}", params=p, timeout=30)
    if r.status_code == 429:
        time.sleep(5)
        r = requests.get(f"{BASE}/{path.lstrip('/')}", params=p, timeout=30)
    r.raise_for_status()
    return r.json()

# ── Step 0: BQ — all healthy inboxes (for msg/day lookup) ────────────────────
print("Querying BQ for all healthy inbox details...")
all_inbox_details = {}
for r in bq.query("""
    SELECT account_id, from_email, message_per_day,
        DATE_DIFF(CURRENT_DATE(), DATE(warmup_created_at), DAY) AS warmup_age_days
    FROM `tenant-recruitin-1575995920662.MARKETSEGMENTDATA.ALL_SMARTLEAD_ACCOUNTS`
    WHERE is_blacklisted = FALSE
      AND is_smtp_success = TRUE
      AND is_imap_success = TRUE
""").result():
    all_inbox_details[r["account_id"]] = dict(r)

# ── Step 1: BQ — healthy inboxes, no active campaigns, >10/day ────────────────
print("Querying BQ for available inboxes (message_per_day > 10)...")
rows = list(bq.query("""
    SELECT
        a.account_id,
        a.from_email,
        a.message_per_day,
        DATE_DIFF(CURRENT_DATE(), DATE(a.warmup_created_at), DAY) AS warmup_age_days
    FROM `tenant-recruitin-1575995920662.MARKETSEGMENTDATA.ALL_SMARTLEAD_ACCOUNTS` a
    LEFT JOIN (
        SELECT account_id, COUNT(*) AS cnt
        FROM `tenant-recruitin-1575995920662.MARKETSEGMENTDATA.ALL_SMARTLEAD_CAMPAIGN_ACCOUNTS`
        WHERE campaign_status = 'ACTIVE'
        GROUP BY account_id
    ) active ON active.account_id = a.account_id
    WHERE a.is_blacklisted = FALSE
      AND a.is_warmup_blocked = FALSE
      AND a.warmup_reputation IN ('100%', '100')
      AND a.is_smtp_success = TRUE
      AND a.is_imap_success = TRUE
      AND DATE_DIFF(CURRENT_DATE(), DATE(a.warmup_created_at), DAY) >= 14
      AND COALESCE(active.cnt, 0) = 0
      AND a.message_per_day > 10
    ORDER BY a.message_per_day DESC, a.from_email
""").result())

available_bq = {r["account_id"]: dict(r) for r in rows}
print(f"  Available (Tier 2, >10/day): {len(available_bq)}")

# ── Step 2: SmartLead — inboxes already in target campaign ────────────────────
print(f"\nFetching inboxes currently in campaign {TARGET_CID}...")
assigned_raw = sl_get(f"campaigns/{TARGET_CID}/email-accounts")
assigned_list = assigned_raw if isinstance(assigned_raw, list) else assigned_raw.get("data", [])
assigned_ids  = set()
for inbox in assigned_list:
    iid = inbox.get("id") or inbox.get("email_account_id")
    if iid:
        assigned_ids.add(iid)
print(f"  Already assigned: {len(assigned_ids)}")

# ── Step 3: Diff — what can be added ─────────────────────────────────────────
addable = {aid: info for aid, info in available_bq.items() if aid not in assigned_ids}

print(f"\n{'='*65}")
print(f"INBOXES AVAILABLE TO ADD TO CAMPAIGN {TARGET_CID}")
print(f"{'='*65}")
print(f"  Tier-2 healthy (>10/day):  {len(available_bq)}")
print(f"  Already in this campaign:  {len([x for x in assigned_ids if x in available_bq])}")
print(f"  Can be added:              {len(addable)}")
print()

if addable:
    print(f"{'Email':<45} {'msg/day':>8}  {'warmup_age':>10}")
    print("-" * 67)
    for info in sorted(addable.values(), key=lambda x: -x["message_per_day"]):
        print(f"  {info['from_email']:<43} {info['message_per_day']:>8}  {info['warmup_age_days']:>8}d")
else:
    print("  No inboxes available to add.")

# ── Step 4: Also show what's already in the campaign (for reference) ──────────
print(f"\n{'='*65}")
print("INBOXES ALREADY IN THIS CAMPAIGN")
print(f"{'='*65}")
for inbox in sorted(assigned_list, key=lambda x: x.get("from_email", "")):
    email = inbox.get("from_email") or inbox.get("email") or "?"
    iid   = inbox.get("id") or inbox.get("email_account_id")
    mpd   = all_inbox_details.get(iid, {}).get("message_per_day", "?")
    print(f"  {email:<45} {str(mpd):>8}/day")
