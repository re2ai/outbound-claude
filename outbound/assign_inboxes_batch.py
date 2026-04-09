#!/usr/bin/env python3
"""
Batch inbox assignment across multiple campaigns.
Pulls Tier 1 available inboxes from BQ, distributes with domain diversity,
assigns via SmartLead API, and updates daily rates where needed.
"""
import sys, io, os, requests, time, math
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv(r"C:\Users\evane\Documents\Coding\scorecard\re2scorecard2026\.env")
KEY  = os.getenv("SMARTLEAD_API_KEY")
BASE = "https://server.smartlead.ai/api/v1"

# ── Campaign targets: (campaign_id, name, inboxes_to_add, new_daily or None) ──
TARGETS = [
    (2996922, "CRE - Loopnet Repush 2",                   1,  None),   # add 1, no daily change
    (3066249, "PLG - Local Marketing - Claude",           30,  None),   # add 30, keep 350
    (3060221, "Business Brokers - Repush 03.19",          30,  None),   # add 30, keep 500
    (3090801, "Business Brokers - Bounce Re-engagement",  14,   150),   # has 1 already, add 14 → 15 total, daily→150
    (3065024, "PLG - Advertising/Billboard - SmartProspect", 15, None), # add 15, keep 200
]

def sl_get(path, params=None):
    p = {"api_key": KEY, **(params or {})}
    r = requests.get(f"{BASE}/{path.lstrip('/')}", params=p, timeout=30)
    if r.status_code == 429:
        time.sleep(5); r = requests.get(f"{BASE}/{path.lstrip('/')}", params=p, timeout=30)
    r.raise_for_status()
    return r.json()

def sl_post(path, body):
    r = requests.post(f"{BASE}/{path.lstrip('/')}", params={"api_key": KEY}, json=body, timeout=30)
    if r.status_code == 429:
        time.sleep(5); r = requests.post(f"{BASE}/{path.lstrip('/')}", params={"api_key": KEY}, json=body, timeout=30)
    r.raise_for_status()
    return r.json()

# ── 1. Pull available Tier 1 inboxes from BQ ─────────────────────────────────
print("Pulling available inboxes from BQ (Tier 1 — 0 active campaigns)...")
client = bigquery.Client(project="tenant-recruitin-1575995920662")
q = """
SELECT
  a.account_id, a.from_email, a.message_per_day, a.warmup_reputation,
  DATE_DIFF(CURRENT_DATE(), DATE(a.warmup_created_at), DAY) AS warmup_age_days,
  COUNTIF(ca.campaign_status = 'ACTIVE') AS active_campaigns
FROM MARKETSEGMENTDATA.ALL_SMARTLEAD_ACCOUNTS a
LEFT JOIN MARKETSEGMENTDATA.ALL_SMARTLEAD_CAMPAIGN_ACCOUNTS ca
  ON a.account_id = ca.account_id
WHERE a.warmup_status = 'ACTIVE'
  AND a.is_smtp_success = TRUE AND a.is_imap_success = TRUE
  AND (a.is_warmup_blocked IS NULL OR a.is_warmup_blocked = FALSE)
  AND (a.is_blacklisted IS NULL OR a.is_blacklisted = FALSE)
  AND CAST(REPLACE(a.warmup_reputation, '%', '') AS FLOAT64) > 90
  AND DATE_DIFF(CURRENT_DATE(), DATE(a.warmup_created_at), DAY) >= 14
GROUP BY 1, 2, 3, 4, 5
HAVING active_campaigns = 0
ORDER BY
  CAST(REPLACE(warmup_reputation, '%', '') AS FLOAT64) DESC,
  message_per_day DESC,
  warmup_age_days DESC
"""
all_available = [dict(r) for r in client.query(q).result()]
print(f"  {len(all_available)} Tier 1 inboxes available")

# Track which inboxes are consumed across campaigns
used_ids = set()

# ── 2. Per-campaign assignment ────────────────────────────────────────────────
for camp_id, camp_name, n_to_add, new_daily in TARGETS:
    print(f"\n{'='*65}")
    print(f"Campaign: {camp_name} (id={camp_id})")
    print(f"  Adding {n_to_add} inboxes" + (f" + updating daily to {new_daily}" if new_daily else ""))

    # Get currently assigned inboxes so we don't dupe domains already in campaign
    existing_resp = sl_get(f"campaigns/{camp_id}/email-accounts")
    existing = existing_resp if isinstance(existing_resp, list) else existing_resp.get("data", [])
    existing_ids  = {i.get("id") or i.get("email_account_id") for i in existing}
    existing_domains = set()
    for inbox in existing:
        email = inbox.get("from_email", "")
        domain = email.split("@")[-1] if "@" in email else ""
        existing_domains.add(domain)

    print(f"  Currently assigned: {len(existing)} inboxes | existing domains: {len(existing_domains)}")

    # Select inboxes: domain diversity (max 2 per domain per campaign), not already used globally
    domain_count = {}  # domain -> count assigned to THIS campaign
    selected = []

    for inbox in all_available:
        if len(selected) >= n_to_add:
            break
        iid = inbox["account_id"]
        if iid in used_ids:
            continue
        email = inbox["from_email"]
        domain = email.split("@")[-1] if "@" in email else ""
        # Count how many of this domain are already in campaign (existing + selected so far)
        already_in_camp = sum(1 for s in selected if s["from_email"].split("@")[-1] == domain)
        already_in_camp += (1 if domain in existing_domains else 0)
        if already_in_camp >= 2:
            continue
        selected.append(inbox)
        domain_count[domain] = domain_count.get(domain, 0) + 1

    if len(selected) < n_to_add:
        print(f"  WARNING: only found {len(selected)} eligible inboxes (needed {n_to_add})")

    print(f"  Selected {len(selected)} inboxes:")
    for s in selected:
        print(f"    {s['from_email']:<45} rep={s['warmup_reputation']}  mpd={s['message_per_day']}")

    # Assign to campaign
    ids_to_add = [s["account_id"] for s in selected]
    if ids_to_add:
        resp = sl_post(f"campaigns/{camp_id}/email-accounts", {"email_account_ids": ids_to_add})
        print(f"  Assignment response: {resp}")
        for iid in ids_to_add:
            used_ids.add(iid)
    else:
        print("  Nothing to assign.")

    # Update daily rate if specified
    if new_daily:
        camp = sl_get(f"campaigns/{camp_id}")
        cron = camp.get("scheduler_cron_value") or {}
        resp2 = sl_post(f"campaigns/{camp_id}/schedule", {
            "timezone":              cron.get("tz", "America/New_York"),
            "days_of_the_week":      cron.get("days", [1, 2, 3, 4, 5]),
            "start_hour":            cron.get("startHour", "09:00"),
            "end_hour":              cron.get("endHour", "19:00"),
            "min_time_btw_emails":   camp.get("min_time_btwn_emails", 30),
            "max_new_leads_per_day": new_daily,
        })
        print(f"  Daily rate updated to {new_daily}: {resp2.get('ok') or 'ok'}")

    time.sleep(0.5)

print(f"\n{'='*65}")
print(f"Done. Total inboxes consumed from Tier 1: {len(used_ids)}")
