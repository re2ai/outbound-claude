#!/usr/bin/env python3
"""
Launch BB Bounce Re-engagement campaign in SmartLead.

291 verified leads from Business Brokers - Repush 03.19 bounce list.
Daily rate: 115/day | Min time between sends: 20 min | Day 0 / +3 / +5
"""
import sys, io, os, json, time, warnings, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
warnings.filterwarnings('ignore')
from dotenv import load_dotenv
load_dotenv(r"C:\Users\evane\Documents\Coding\scorecard\re2scorecard2026\.env")

KEY      = os.getenv("SMARTLEAD_API_KEY")
BASE     = "https://server.smartlead.ai/api/v1"
LOCAL    = r"C:\Users\evane\AppData\Local\Temp\bounce\bounce_bb_clean.json"
CAMP_NAME = "Business Brokers - Bounce Re-engagement - Claude"
DAILY_RATE = 115
MIN_TIME   = 20   # minutes between sends

INBOX_IDS = [
    16971875,  # lucy@prospectings.co
    12492128,  # tyler@useresquaredai.com
    12492568,  # tyler@useresquared.com
    12492029,  # tyler@tryresquaredai.com
    12491623,  # tyler@tryre2sales.com
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

# ── Step 1: Create campaign ───────────────────────────────────────────────────
print("Creating campaign...")
r = api("post", "campaigns/create", json={"name": CAMP_NAME})
camp = r.json()
cid = camp.get("id")
if not cid:
    print(f"ERROR creating campaign: {r.text[:200]}")
    sys.exit(1)
print(f"  Campaign created: id={cid}  name={CAMP_NAME}")

# ── Step 2: Settings ──────────────────────────────────────────────────────────
print("Configuring settings...")
r = api("post", f"campaigns/{cid}/settings", json={
    "send_as_plain_text":       True,
    "force_plain_text":         True,
    "enable_ai_esp_matching":   True,
    "track_settings":           ["DONT_TRACK_EMAIL_OPEN", "DONT_TRACK_LINK_CLICK"],
    "stop_lead_settings":       "REPLY_TO_AN_EMAIL",
    "follow_up_percentage":     50,
    "unsubscribe_text":         "",
})
print(f"  Settings: {r.status_code}")

# ── Step 3: Schedule ──────────────────────────────────────────────────────────
print("Setting schedule...")
r = api("post", f"campaigns/{cid}/schedule", json={
    "timezone":             "America/New_York",
    "days_of_the_week":     [1, 2, 3, 4, 5],   # Mon–Fri
    "start_hour":           "09:00",
    "end_hour":             "19:00",
    "min_time_btw_emails":  MIN_TIME,
    "max_new_leads_per_day": DAILY_RATE,
})
print(f"  Schedule: {r.status_code}")

# ── Step 4: Sequences ─────────────────────────────────────────────────────────
print("Adding sequences...")
sequences = [
    {"seq_number": 1, "seq_delay_details": {"delay_in_days": 0},
     "subject": "{{Subject1}}", "email_body": "{{Email1}}"},
    {"seq_number": 2, "seq_delay_details": {"delay_in_days": 3},
     "subject": "",             "email_body": "{{Email2}}"},
    {"seq_number": 3, "seq_delay_details": {"delay_in_days": 5},
     "subject": "",             "email_body": "{{Email3}}"},
]
r = api("post", f"campaigns/{cid}/sequences", json={"sequences": sequences})
print(f"  Sequences: {r.status_code}  {r.text[:80]}")

# ── Step 5: Add inboxes ───────────────────────────────────────────────────────
print("Adding inboxes...")
r = api("post", f"campaigns/{cid}/email-accounts", json={"email_account_ids": INBOX_IDS})
print(f"  Inboxes: {r.status_code}  {r.text[:80]}")

# ── Step 6: Load leads ────────────────────────────────────────────────────────
print("\nLoading leads...")
with open(LOCAL) as f:
    leads = json.load(f)

print(f"  Total to load: {len(leads)}")
ok = 0
failed = 0
for i, l in enumerate(leads):
    payload = {
        "lead_list": [{
            "email":        l["email"],
            "first_name":   l.get("first_name", ""),
            "last_name":    l.get("last_name", ""),
            "company_name": l.get("company_name", ""),
            "location":     l.get("location", ""),
            "custom_fields": {
                "Subject1": l.get("Subject1", l.get("subject1", "")),
                "Email1":   l.get("Email1",   l.get("email1", "")),
                "Email2":   l.get("Email2",   l.get("email2", "")),
                "Email3":   l.get("Email3",   l.get("email3", "")),
            }
        }],
        "settings": {
            "ignore_global_block_list":    True,
            "ignore_unsubscribe_list":     True,
            "ignore_community_bounce_list": False,
        }
    }
    r = api("post", f"campaigns/{cid}/leads", json=payload)
    if r.status_code in (200, 201):
        ok += 1
    else:
        failed += 1
        if failed <= 5:
            print(f"  FAILED {l['email']}: {r.status_code} {r.text[:80]}")
    if (i + 1) % 50 == 0:
        print(f"  [{i+1}/{len(leads)}] ok={ok} failed={failed}")
    time.sleep(0.3)

print(f"\n  Done: {ok} loaded, {failed} failed")
print(f"\n=== Campaign Ready ===")
print(f"  ID:         {cid}")
print(f"  Name:       {CAMP_NAME}")
print(f"  Leads:      {ok}")
print(f"  Daily rate: {DAILY_RATE}/day")
print(f"  Min delay:  {MIN_TIME} min")
print(f"  Inboxes:    {len(INBOX_IDS)}")
print(f"\n  ⚠️  Remember: enable AI categorization in old SmartLead UI")
print(f"  ⚠️  Then set campaign to ACTIVE to start sending")
