#!/usr/bin/env python3
"""
Add inboxes to campaign 3065024 — PLG - Advertising/Billboard - SmartProspect.
Uses Tier 1 BQ inboxes (0 active campaigns, rep >90%, warmup >=14d).
Runs a dry-run check first, then assigns on confirmation.
"""
import sys, io, os, requests, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv(r"C:\Users\evane\Documents\Coding\scorecard\re2scorecard2026\.env")
KEY  = os.getenv("SMARTLEAD_API_KEY")
BASE = "https://server.smartlead.ai/api/v1"

CAMP_ID   = 3065024
CAMP_NAME = "PLG - Advertising/Billboard - SmartProspect"
N_TO_ADD  = 10  # target number of inboxes to add

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
print("Pulling Tier 1 available inboxes from BQ...")
client = bigquery.Client(project="tenant-recruitin-1575995920662")
rows = list(client.query("""
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
      AND CAST(REPLACE(a.warmup_reputation, '%', '') AS FLOAT64) > 90
      AND DATE_DIFF(CURRENT_DATE(), DATE(a.warmup_created_at), DAY) >= 14
    GROUP BY 1, 2, 3, 4, 5
    HAVING active_campaigns = 0
    ORDER BY
      CAST(REPLACE(warmup_reputation, '%', '') AS FLOAT64) DESC,
      warmup_age_days DESC,
      message_per_day DESC
""").result())
print(f"  {len(rows)} Tier 1 inboxes available in BQ")

# ── 2. Get inboxes already in campaign ───────────────────────────────────────
print(f"\nFetching inboxes currently assigned to campaign {CAMP_ID}...")
existing_resp = sl_get(f"campaigns/{CAMP_ID}/email-accounts")
existing = existing_resp if isinstance(existing_resp, list) else existing_resp.get("data", [])
existing_ids     = {i.get("id") or i.get("email_account_id") for i in existing}
existing_domains = set()
for inbox in existing:
    email = inbox.get("from_email", "")
    domain = email.split("@")[-1] if "@" in email else ""
    existing_domains.add(domain)

print(f"  Currently assigned: {len(existing)} inboxes")
if existing:
    for i in sorted(existing, key=lambda x: x.get("from_email", "")):
        email = i.get("from_email") or "?"
        print(f"    {email}")

# ── 3. Select inboxes with domain diversity (max 2 per domain) ───────────────
selected = []
for inbox in rows:
    if len(selected) >= N_TO_ADD:
        break
    iid    = inbox["account_id"]
    email  = inbox["from_email"]
    domain = email.split("@")[-1] if "@" in email else ""
    already_in_camp = sum(1 for s in selected if s["from_email"].split("@")[-1] == domain)
    already_in_camp += (1 if domain in existing_domains else 0)
    if already_in_camp >= 2:
        continue
    selected.append(dict(inbox))

# ── 4. Preview ────────────────────────────────────────────────────────────────
print(f"\n{'='*65}")
print(f"PLAN: Add {len(selected)} inboxes to: {CAMP_NAME}")
print(f"{'='*65}")
if selected:
    print(f"{'Email':<45} {'rep':>6}  {'mpd':>5}  {'age':>5}")
    print("-" * 65)
    for s in selected:
        print(f"  {s['from_email']:<43} {str(s['warmup_reputation']):>6}  {s['message_per_day']:>5}  {s['warmup_age_days']:>4}d")
else:
    print("  No eligible inboxes found.")
    sys.exit(0)

if len(selected) < N_TO_ADD:
    print(f"\n  WARNING: Only found {len(selected)} eligible inboxes (target was {N_TO_ADD})")

# ── 5. Confirm and assign ─────────────────────────────────────────────────────
print(f"\nProceed with assignment? [y/N] ", end="", flush=True)
answer = input().strip().lower()
if answer != "y":
    print("Aborted.")
    sys.exit(0)

ids_to_add = [s["account_id"] for s in selected]
resp = sl_post(f"campaigns/{CAMP_ID}/email-accounts", {"email_account_ids": ids_to_add})
print(f"\nAssignment response: {resp}")
print(f"\nDone. Added {len(ids_to_add)} inboxes to campaign {CAMP_ID}.")
