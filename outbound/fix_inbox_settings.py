#!/usr/bin/env python3
"""
For a target list of inboxes:
  1. Remove their domains from MARKETSEGMENTDATA.SMARTLEAD_BLACKLISTED_DOMAINS (BQ)
  2. Set message_per_day=10 on each account via the SmartLead API

After running, refresh the dashboard:
  python scorecard/re2scorecard2026/build_all_smartlead_accounts.py
  python scorecard/re2scorecard2026/generate_smartlead_dashboard.py
"""
import os, sys, requests, time

# Force UTF-8 output and flush immediately so nothing is swallowed on crash
sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)

print("Loading env...", flush=True)
from dotenv import load_dotenv
load_dotenv(r"C:\Users\evane\Documents\Coding\scorecard\re2scorecard2026\.env")

print("Importing BigQuery...", flush=True)
from google.cloud import bigquery

KEY  = os.getenv("SMARTLEAD_API_KEY")
BASE = "https://server.smartlead.ai/api/v1"
BQ_TABLE = "tenant-recruitin-1575995920662.MARKETSEGMENTDATA.SMARTLEAD_BLACKLISTED_DOMAINS"

if not KEY:
    print("ERROR: SMARTLEAD_API_KEY not found in .env", flush=True)
    sys.exit(1)
print(f"SmartLead key loaded: {KEY[:6]}...", flush=True)

TARGET_EMAILS = [
    "jalen@topresquared.com",
    "tyler@topresquared.com",
    "leonardo@topresquared.com",
    "jalen@topresquaredai.com",
    "tyler@topresquaredai.com",
    "leonardo@topresquaredai.com",
    "jalen@tryre2ai.com",
    "tyler@tryre2ai.com",
    "leonardo@tryre2ai.com",
    "jalen@tryresquared.com",
    "tyler@tryresquared.com",
    "leonardo@tryresquared.com",
    "jalen@trustre2sales.com",
    "tyler@trustre2sales.com",
    "leonardo@trustre2sales.com",
    "jalen@byre2sales.com",
    "tyler@byre2sales.com",
    "leonardo@byre2sales.com",
    "jalen@webre2sales.com",
    "tyler@webre2sales.com",
    "leonardo@webre2sales.com",
    "jalen@onresquaredsales.com",
    "tyler@onresquaredsales.com",
    "leonardo@onresquaredsales.com",
    "jalen@getresquaredsales.com",
    "tyler@getresquaredsales.com",
    "leonardo@getresquaredsales.com",
    "jalen@webre2tech.com",
    "tyler@webre2tech.com",
    "leonardo@webre2tech.com",
    "jalen@tryre2tech.com",
    "tyler@tryre2tech.com",
    "leonardo@tryre2tech.com",
    "jalen@trustresquaredsales.com",
    "tyler@trustresquaredsales.com",
    "leonardo@trustresquaredsales.com",
    "jalen@topresquaredsales.com",
    "tyler@topresquaredsales.com",
    "leonardo@topresquaredsales.com",
    "jalen@topre2techai.com",
    "tyler@topre2techai.com",
    "leonardo@topre2techai.com",
    "jalen@there2sales.com",
    "tyler@there2sales.com",
    "leonardo@there2sales.com",
    "jalen@getre2tech.com",
    "tyler@getre2tech.com",
    "leonardo@getre2tech.com",
    "jalen@byresquaredsales.com",
    "tyler@byresquaredsales.com",
    "leonardo@byresquaredsales.com",
    "jalen@aire2tech.com",
    "tyler@aire2tech.com",
    "leonardo@aire2tech.com",
    "jalen@webresquaredsales.com",
    "tyler@webresquaredsales.com",
    "leonardo@webresquaredsales.com",
    "jalen@useresquaredsales.com",
    "tyler@useresquaredsales.com",
    "leonardo@useresquaredsales.com",
    "jalen@usere2tech.com",
    "tyler@usere2tech.com",
    "leonardo@usere2tech.com",
    "jalen@usere2sales.com",
    "tyler@usere2sales.com",
    "leonardo@usere2sales.com",
    "jalen@tryresquaredsales.com",
    "tyler@tryresquaredsales.com",
    "leonardo@tryresquaredsales.com",
    "jalen@trustre2tech.com",
    "tyler@trustre2tech.com",
    "leonardo@trustre2tech.com",
    "jalen@topre2tech.com",
    "tyler@topre2tech.com",
    "leonardo@topre2tech.com",
    "jalen@topre2sales.com",
    "tyler@topre2sales.com",
    "leonardo@topre2sales.com",
    "jalen@theresquaredsales.com",
    "tyler@theresquaredsales.com",
    "leonardo@theresquaredsales.com",
    "jalen@there2tech.com",
    "tyler@there2tech.com",
    "leonardo@there2tech.com",
    "jalen@onre2tech.com",
    "tyler@onre2tech.com",
    "leonardo@onre2tech.com",
    "jalen@onre2sales.com",
    "tyler@onre2sales.com",
    "leonardo@onre2sales.com",
    "jalen@getre2sales.com",
    "tyler@getre2sales.com",
    "leonardo@getre2sales.com",
    "jalen@byre2tech.com",
    "tyler@byre2tech.com",
    "leonardo@byre2tech.com",
    "jalen@airesquaredsales.com",
    "tyler@airesquaredsales.com",
    "leonardo@airesquaredsales.com",
    "jalen@aire2sales.com",
    "tyler@aire2sales.com",
]

TARGET_DOMAINS = sorted({e.split("@")[1].lower() for e in TARGET_EMAILS})
TARGET_EMAIL_SET = {e.lower() for e in TARGET_EMAILS}


# ── helpers ───────────────────────────────────────────────────────────────────

def sl_get(path, params=None, retries=3):
    p = {"api_key": KEY, **(params or {})}
    url = f"{BASE}/{path.lstrip('/')}"
    for attempt in range(retries):
        try:
            r = requests.get(url, params=p, timeout=60)
            if r.status_code == 429:
                time.sleep(10)
                continue
            r.raise_for_status()
            return r.json()
        except requests.exceptions.Timeout:
            wait = 10 * (attempt + 1)
            print(f"  Timeout on attempt {attempt+1}/{retries}, retrying in {wait}s...", flush=True)
            time.sleep(wait)
    raise Exception(f"GET {path} failed after {retries} attempts")


def sl_update_account(account_id, payload):
    r = requests.post(
        f"{BASE}/email-accounts/{account_id}",
        params={"api_key": KEY},
        json=payload,
        timeout=30,
    )
    if r.status_code == 429:
        time.sleep(5)
        r = requests.post(
            f"{BASE}/email-accounts/{account_id}",
            params={"api_key": KEY},
            json=payload,
            timeout=30,
        )
    r.raise_for_status()
    return r.json()


# ── Part 1: Remove domains from BQ blacklist ──────────────────────────────────

print("=" * 60, flush=True)
print("PART 1 — Remove domains from BQ blacklist", flush=True)
print("=" * 60, flush=True)

print("Connecting to BigQuery...", flush=True)
try:
    bq = bigquery.Client(project="tenant-recruitin-1575995920662")
    print("  BigQuery connected.", flush=True)
except Exception as e:
    print(f"  ERROR connecting to BigQuery: {e}", flush=True)
    sys.exit(1)

print(f"Checking {len(TARGET_DOMAINS)} domains against blacklist...", flush=True)
try:
    placeholders = ", ".join(f"'{d}'" for d in TARGET_DOMAINS)
    existing = list(bq.query(
        f"SELECT domain FROM `{BQ_TABLE}` WHERE domain IN ({placeholders})"
    ).result())
    blacklisted_domains = {r.domain for r in existing}
except Exception as e:
    print(f"  ERROR querying BQ: {e}", flush=True)
    sys.exit(1)

print(f"  Domains in target list:       {len(TARGET_DOMAINS)}", flush=True)
print(f"  Of those, currently blacklisted: {len(blacklisted_domains)}", flush=True)

if not blacklisted_domains:
    print("  (none of these domains are in the blacklist — nothing to remove)", flush=True)
else:
    for domain in sorted(blacklisted_domains):
        try:
            job = bq.query(f"DELETE FROM `{BQ_TABLE}` WHERE domain = '{domain}'")
            job.result()
            print(f"  Removed: {domain}", flush=True)
        except Exception as e:
            print(f"  ERROR removing {domain}: {e}", flush=True)
    print(f"\nRemoved {len(blacklisted_domains)} domain(s) from blacklist.", flush=True)
    print("Remember to run build_all_smartlead_accounts.py + generate_smartlead_dashboard.py after.", flush=True)


# ── Part 2: Update message_per_day=10 via SmartLead API ──────────────────────

print(flush=True)
print("=" * 60, flush=True)
print("PART 2 — Set message_per_day=10 in SmartLead", flush=True)
print("=" * 60, flush=True)

print("Fetching all email accounts...", flush=True)
accounts = []
offset = 0
while True:
    try:
        page = sl_get("email-accounts", {"limit": 100, "offset": offset})
    except Exception as e:
        print(f"  ERROR fetching accounts at offset {offset}: {e}", flush=True)
        sys.exit(1)
    if not page:
        break
    accounts.extend(page)
    print(f"  Fetched {len(accounts)} so far...", flush=True)
    if len(page) < 100:
        break
    offset += 100
print(f"  Total accounts fetched: {len(accounts)}", flush=True)

matched = []
for a in accounts:
    email = (a.get("from_email") or a.get("email") or "").lower()
    if email in TARGET_EMAIL_SET:
        matched.append({"id": a["id"], "email": email, "mpd": a.get("message_per_day")})

print(f"  Matched: {len(matched)} / {len(TARGET_EMAIL_SET)} target emails", flush=True)
not_found = TARGET_EMAIL_SET - {m["email"] for m in matched}
if not_found:
    print(f"  Not found in SmartLead ({len(not_found)}):", flush=True)
    for e in sorted(not_found):
        print(f"    {e}", flush=True)

print(f"\nUpdating {len(matched)} accounts → message_per_day=10 ...", flush=True)
ok, skipped, failed = 0, 0, []
for m in matched:
    if m["mpd"] == 10:
        print(f"  –  {m['email']}  already 10/day, skipping", flush=True)
        skipped += 1
        continue
    try:
        sl_update_account(m["id"], {"max_email_per_day": 10})
        print(f"  ✓  {m['email']}  (was {m['mpd']})", flush=True)
        ok += 1
    except Exception as e:
        print(f"  ✗  {m['email']}  ERROR: {e}", flush=True)
        failed.append(m["email"])
    time.sleep(0.3)

print(f"\n=== Done: {ok} updated, {skipped} already at 10 (skipped), {len(failed)} failed ===", flush=True)
if failed:
    print("Failed:", flush=True)
    for e in failed:
        print(f"  {e}", flush=True)
