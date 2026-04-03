#!/usr/bin/env python3
"""
Launch PLG Bounce Re-engagement campaign from the verified + fixed lead file.
Reads: bounce_plg_verified.json  (already clean — no further transforms applied)
Creates campaign → settings → schedule → sequences → inboxes → load leads → start
"""
import sys, io, os, json, time, warnings, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from dotenv import load_dotenv
load_dotenv(r"C:\Users\evane\Documents\Coding\scorecard\re2scorecard2026\.env")
warnings.filterwarnings("ignore")

# ─── config ───────────────────────────────────────────────────────────────────
LOCAL       = r"C:\Users\evane\AppData\Local\Temp\bounce\bounce_plg_verified.json"
CAMP_NAME   = "PLG - Bounce Re-engagement - Claude"
DAILY_RATE  = 100
INBOX_IDS   = [16971881, 16971835, 12492473, 12491931, 12491474]
# claire@prospectings.co, stella@prospectings.co,
# tyler@onre2ai.com, tyler@onresquared.com, tyler@getresquaredai.com

SL_KEY  = os.getenv("SMARTLEAD_API_KEY")
SL_BASE = "https://server.smartlead.ai/api/v1"

def sl_post(endpoint, body):
    r = requests.post(f"{SL_BASE}/{endpoint}", params={"api_key": SL_KEY},
                      json=body, timeout=30)
    r.raise_for_status()
    return r.json()

def sl_get(endpoint, params=None):
    p = {"api_key": SL_KEY, **(params or {})}
    r = requests.get(f"{SL_BASE}/{endpoint}", params=p, timeout=30)
    r.raise_for_status()
    return r.json()

# ─── load leads ───────────────────────────────────────────────────────────────
with open(LOCAL) as f:
    leads = json.load(f)
print(f"Loaded {len(leads)} leads from {LOCAL}")

# Sanity check: every lead must have Subject1, Email1, Email2, Email3
missing = [l['email'] for l in leads
           if not (l.get('Subject1') or l.get('subject1'))
           or not (l.get('Email1')  or l.get('email1'))
           or not (l.get('Email2')  or l.get('email2'))
           or not (l.get('Email3')  or l.get('email3'))]
if missing:
    print(f"ABORT — {len(missing)} leads missing copy fields: {missing[:5]}")
    sys.exit(1)
print(f"  All leads have Subject1 + Email1 + Email2 + Email3 — OK")

# ─── 1. create campaign ───────────────────────────────────────────────────────
print(f"\n[1] Creating campaign '{CAMP_NAME}'...")
resp = sl_post("campaigns/create", {"name": CAMP_NAME})
cid = resp.get("id")
if not cid:
    print(f"ABORT — create failed: {resp}")
    sys.exit(1)
print(f"  Campaign ID: {cid}")

# ─── 2. settings ─────────────────────────────────────────────────────────────
print(f"\n[2] Applying settings...")
sl_post(f"campaigns/{cid}/settings", {
    "send_as_plain_text":      True,
    "force_plain_text":        True,
    "enable_ai_esp_matching":  True,
    "track_settings":          ["DONT_TRACK_EMAIL_OPEN", "DONT_TRACK_LINK_CLICK"],
    "stop_lead_settings":      "REPLY_TO_AN_EMAIL",
    "follow_up_percentage":    50,
})
print(f"  Done.")

# ─── 3. schedule ──────────────────────────────────────────────────────────────
print(f"\n[3] Setting schedule (9-19 ET, M-F, 30min gap, {DAILY_RATE}/day)...")
sl_post(f"campaigns/{cid}/schedule", {
    "timezone":               "America/New_York",
    "days_of_the_week":       [1, 2, 3, 4, 5],
    "start_hour":             "09:00",
    "end_hour":               "19:00",
    "min_time_btw_emails":    30,
    "max_new_leads_per_day":  DAILY_RATE,
})
print(f"  Done.")

# ─── 4. sequences ─────────────────────────────────────────────────────────────
print(f"\n[4] Creating sequences (Day 0 / +3 / +5)...")
sl_post(f"campaigns/{cid}/sequences", {"sequences": [
    {
        "seq_number": 1,
        "seq_delay_details": {"delay_in_days": 0},
        "subject":    "{{Subject1}}",
        "email_body": "<div>{{Email1}}</div><div><br></div>",
    },
    {
        "seq_number": 2,
        "seq_delay_details": {"delay_in_days": 3},
        "subject":    "",
        "email_body": "<div>{{Email2}}</div>",
    },
    {
        "seq_number": 3,
        "seq_delay_details": {"delay_in_days": 5},
        "subject":    "",
        "email_body": "<div>{{Email3}}</div>",
    },
]})
print(f"  Done.")

# ─── 5. assign inboxes ────────────────────────────────────────────────────────
print(f"\n[5] Assigning {len(INBOX_IDS)} inboxes...")
sl_post(f"campaigns/{cid}/email-accounts", {"email_account_ids": INBOX_IDS})
# Re-apply daily rate after inbox assignment (SmartLead resets it)
sl_post(f"campaigns/{cid}/schedule", {
    "timezone":               "America/New_York",
    "days_of_the_week":       [1, 2, 3, 4, 5],
    "start_hour":             "09:00",
    "end_hour":               "19:00",
    "min_time_btw_emails":    30,
    "max_new_leads_per_day":  DAILY_RATE,
})
print(f"  Done. Daily rate re-confirmed at {DAILY_RATE}.")

# ─── 6. load leads ────────────────────────────────────────────────────────────
print(f"\n[6] Loading {len(leads)} leads in batches of 100...")
loaded = 0
errors = 0
for i in range(0, len(leads), 100):
    batch = leads[i:i+100]
    payload = {
        "lead_list": [
            {
                "email":        l["email"],
                "first_name":   l.get("first_name", ""),
                "last_name":    l.get("last_name",  ""),
                "company_name": l.get("company_name", ""),
                "location":     l.get("location", ""),
                "custom_fields": {
                    "Subject1": l.get("Subject1") or l.get("subject1", ""),
                    "Email1":   l.get("Email1")   or l.get("email1",   ""),
                    "Email2":   l.get("Email2")   or l.get("email2",   ""),
                    "Email3":   l.get("Email3")   or l.get("email3",   ""),
                },
            }
            for l in batch
        ],
        "settings": {
            "ignore_global_block_list": False,
            "ignore_unsubscribe_list":  False,
        },
    }
    try:
        sl_post(f"campaigns/{cid}/leads", payload)
        loaded += len(batch)
        print(f"  [{loaded}/{len(leads)}] loaded")
    except Exception as e:
        errors += len(batch)
        print(f"  ERROR batch {i}-{i+len(batch)}: {e}")
    time.sleep(0.5)

print(f"\n  Loaded: {loaded}  Errors: {errors}")

# ─── 7. spot-check ────────────────────────────────────────────────────────────
print(f"\n[7] Spot-checking 3 leads from SmartLead...")
time.sleep(2)
check = sl_get(f"campaigns/{cid}/leads", {"limit": 3, "offset": 0})
check_leads = check.get("data", check) if isinstance(check, dict) else check
for item in check_leads[:3]:
    ld = item.get("lead", item)
    cf = ld.get("custom_fields") or {}
    print(f"  {ld.get('email')} | Subject1: {cf.get('Subject1','')[:50]} | Email1: {cf.get('Email1','')[:50]}")

# ─── 8. START campaign ────────────────────────────────────────────────────────
print(f"\n[8] Starting campaign...")
start_resp = sl_post(f"campaigns/{cid}/status", {"status": "START"})
print(f"  Response: {start_resp}")

print(f"""
============================================================
  CAMPAIGN LAUNCHED
  Name:       {CAMP_NAME}
  ID:         {cid}
  Leads:      {loaded}
  Daily rate: {DAILY_RATE}/day
  Inboxes:    {len(INBOX_IDS)}
  Est. days:  {len(leads) // DAILY_RATE + 1}

  TODO (manual):
    - Enable AI categorization in SmartLead OLD UI
    - Run: python smartlead_update_signatures.py --only-missing
============================================================
""")
