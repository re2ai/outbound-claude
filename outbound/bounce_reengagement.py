#!/usr/bin/env python3
"""
Bounce re-engagement campaign builder — 3 campaigns (PLG / BB / CRE).

Pulls leads with lead_category = 'Sender Originated Bounce' from BQ
(one per email, latest campaign), reuses their original Email1/Subject1,
strips links from Email2/Email3 and replaces with a reply CTA.

Bucket detection (from original campaign_name):
  PLG    → name contains 'PLG'
  BB     → name contains 'BROKER' or standalone 'BB'
  CRE    → name contains 'CRE'
  other  → anything that doesn't match the above

Any lead whose original campaign sent < 3 emails (max_seq_sent < 3) gets a
fresh no-link Email3 generated.

Usage:
  # Step 1 – pull, transform, save JSON files for review
  python bounce_reengagement.py --out-dir /tmp/bounce

  # Step 2 – launch PLG bucket (after reviewing bounce_plg.json)
  python bounce_reengagement.py --out-dir /tmp/bounce --skip-pull \
      --launch plg --daily-rate 200 --inbox-ids 12345,67890

  # Dry-run (no API calls)
  python bounce_reengagement.py --out-dir /tmp/bounce --dry-run
"""

import os
import sys
import json

# Windows: force UTF-8 stdout so emoji/Unicode in print() don't crash
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import time
import argparse
import re
import requests
from pathlib import Path
from dotenv import load_dotenv

# .env lives in the scorecard repo — search up from this file and also try known path
_HERE = Path(__file__).resolve().parent
load_dotenv(_HERE / ".env")
load_dotenv(Path(__file__).resolve().parents[2] / "scorecard" / "re2scorecard2026" / ".env")

try:
    from google.cloud import bigquery
    bq = bigquery.Client(project="tenant-recruitin-1575995920662")
except Exception as e:
    print(f"BigQuery init failed: {e}")
    bq = None

PROJECT = "tenant-recruitin-1575995920662"
SL_KEY  = os.getenv("SMARTLEAD_API_KEY")
SL_BASE = "https://server.smartlead.ai/api/v1"
SL_P    = {"api_key": SL_KEY}

CAMPAIGNS = {
    "plg": {
        "name": "PLG - Bounce Re-engagement - Claude",
        "file": "bounce_plg.json",
    },
    "bb": {
        "name": "Business Brokers - Bounce Re-engagement - Claude",
        "file": "bounce_bb.json",
    },
    "cre": {
        "name": "CRE - Bounce Re-engagement - Claude",
        "file": "bounce_cre.json",
    },
    "other": {
        "name": "Other - Bounce Re-engagement - Claude",
        "file": "bounce_other.json",
    },
}


# ── helpers ────────────────────────────────────────────────────────────────────

def sl_get(endpoint, params=None):
    p = {**SL_P, **(params or {})}
    r = requests.get(f"{SL_BASE}/{endpoint}", params=p, timeout=30)
    r.raise_for_status()
    return r.json()


def sl_post(endpoint, body):
    r = requests.post(f"{SL_BASE}/{endpoint}", params=SL_P, json=body, timeout=30)
    r.raise_for_status()
    return r.json()


def city_from_location(location):
    """'Austin, Texas' → 'Austin'"""
    if not location:
        return "your area"
    city = location.split(",")[0].strip()
    return city or "your area"


# Campaigns that used non-standard custom field names.
# Maps campaign_id (int) → {standard_field: actual_smartlead_field}
CAMPAIGN_FIELD_OVERRIDES = {
    3065024: {  # PLG - Advertising/Billboard - SmartProspect
        "Subject1": "bpdy1",
        "Email1":   "subject1",
        "Email2":   "email2_(2)",
        "Email3":   "email3",
    },
}


def bucket_for(campaign_name):
    name = (campaign_name or "").upper()
    if "PLG" in name:
        return "plg"
    if "BROKER" in name or " BB " in name or name.startswith("BB ") or name.endswith(" BB"):
        return "bb"
    if "CRE" in name:
        return "cre"
    return "other"


def strip_links(html):
    """Remove all <a href="...">...</a> tags."""
    return re.sub(r'<a\s[^>]*>.*?</a>', '', html, flags=re.IGNORECASE | re.DOTALL)


def clean_trailing_br(html):
    return re.sub(r'^(\s*<br\s*/?>\s*)+|(\s*<br\s*/?>\s*)+$', '', html.strip(),
                  flags=re.IGNORECASE)


def transform_email2(html):
    """
    Strip link + 'This is for a free account...' line from Email2.
    Replace with reply CTA.
    """
    body = strip_links(html)
    body = re.sub(
        r'<br\s*/?>\s*<br\s*/?>\s*This is for a free account.*',
        '',
        body,
        flags=re.IGNORECASE | re.DOTALL,
    )
    body = clean_trailing_br(body)
    return body + "<br><br>Just reply to this email and I'll send you the link."


def transform_email3(html):
    """Strip link from Email3, replace with reply CTA."""
    body = strip_links(html)
    body = clean_trailing_br(body)
    return body + "<br><br>Just reply and I'll send you the link."


def build_email3_no_link(city):
    """Fresh Email3 for leads that never received one."""
    return (
        f"Since I'm guessing you're busy, I'll just leave this here so you can check "
        f"the data whenever you have a moment.<br><br>"
        f"You can access all the local business data for {city} — "
        f"just reply and I'll send you the link."
    )


def convert_email1_linebreaks(body):
    """Convert \\n line breaks to <br> at load time if not already done."""
    if "<br" in body:
        return body
    return body.replace("\n\n", "<br><br>").replace("\n", "<br>")


# ── step 1: BQ pull ────────────────────────────────────────────────────────────

def pull_bounced_leads():
    """
    Return one row per unique lead_email with Sender Originated Bounce,
    picking the latest campaign they bounced from.

    Also returns max_seq_sent so we know if Email3 was ever sent.
    Schema: lead_email, campaign_id, campaign_name, max_seq_sent, last_sent_time
    """
    print("Querying BQ for Sender Originated Bounce leads...")
    query = f"""
    WITH per_lead_campaign AS (
      SELECT
        lead_email,
        campaign_id,
        campaign_name,
        MAX(sequence_number) AS max_seq_sent,
        MAX(sent_time)       AS last_sent_time
      FROM `{PROJECT}.MARKETSEGMENTDATA.ALL_SMARTLEAD_EMAILS`
      WHERE lead_category = 'Sender Originated Bounce'
        AND lead_email IS NOT NULL
        AND TRIM(lead_email) != ''
      GROUP BY lead_email, campaign_id, campaign_name
    ),
    ranked AS (
      SELECT
        *,
        ROW_NUMBER() OVER (
          PARTITION BY LOWER(TRIM(lead_email))
          ORDER BY last_sent_time DESC
        ) AS rn
      FROM per_lead_campaign
    )
    SELECT
      lead_email AS email,
      campaign_id,
      campaign_name,
      max_seq_sent,
      last_sent_time
    FROM ranked
    WHERE rn = 1
    ORDER BY campaign_name, email
    """
    rows = [dict(r) for r in bq.query(query).result()]
    print(f"  {len(rows)} unique bounced leads across "
          f"{len({r['campaign_id'] for r in rows})} campaigns.")
    return rows


# ── step 2: SmartLead custom field pull ────────────────────────────────────────

def pull_sl_custom_fields(campaign_ids):
    """
    For each campaign_id, pull all leads and return a dict:
      email_lower → {first_name, last_name, company_name, location,
                      Subject1, Email1, Email2, Email3}
    """
    print(f"Pulling SmartLead custom fields for {len(campaign_ids)} campaigns...")
    email_data = {}
    for cid in sorted(campaign_ids):
        print(f"  Campaign {cid}...", end=" ", flush=True)
        count = 0
        offset = 0
        while True:
            result = sl_get(f"campaigns/{cid}/leads", {"limit": 100, "offset": offset})
            batch = result.get("data", []) if isinstance(result, dict) else result
            if not batch:
                break
            for item in batch:
                lead = item.get("lead", item)
                email = (lead.get("email") or "").lower().strip()
                if not email:
                    continue
                cf = lead.get("custom_fields") or {}
                fmap = CAMPAIGN_FIELD_OVERRIDES.get(cid, {})
                email_data[email] = {
                    "first_name":   lead.get("first_name", ""),
                    "last_name":    lead.get("last_name", ""),
                    "company_name": lead.get("company_name", ""),
                    "location":     lead.get("location", ""),
                    "Subject1":     cf.get(fmap.get("Subject1", "Subject1"), ""),
                    "Email1":       cf.get(fmap.get("Email1",   "Email1"),   ""),
                    "Email2":       cf.get(fmap.get("Email2",   "Email2"),   ""),
                    "Email3":       cf.get(fmap.get("Email3",   "Email3"),   ""),
                }
                count += 1
            if len(batch) < 100:
                break
            offset += 100
        print(f"{count} leads")
    return email_data


# ── step 3: transform + bucket ─────────────────────────────────────────────────

def transform_and_bucket(bq_rows, sl_data):
    buckets = {k: [] for k in CAMPAIGNS}
    generated_email3 = 0
    missing_email1   = 0

    for row in bq_rows:
        email = (row["email"] or "").lower().strip()
        if not email:
            continue

        sl = sl_data.get(email, {})
        city = city_from_location(sl.get("location", ""))

        # Email copies — prefer SmartLead (live), fall back to nothing
        subject1    = sl.get("Subject1") or ""
        email1_raw  = sl.get("Email1")   or ""
        email2_orig = sl.get("Email2")   or ""
        email3_orig = sl.get("Email3")   or ""

        if not email1_raw:
            missing_email1 += 1

        email1 = convert_email1_linebreaks(email1_raw) if email1_raw else ""
        email2 = transform_email2(email2_orig) if email2_orig else ""

        # Email3: if they got it, transform it; if not, build fresh (no link)
        had_email3 = bool(email3_orig) or (row.get("max_seq_sent") or 0) >= 3
        if email3_orig:
            email3 = transform_email3(email3_orig)
        else:
            email3 = build_email3_no_link(city)
            generated_email3 += 1

        bucket = bucket_for(row.get("campaign_name", ""))
        buckets[bucket].append({
            "email":             email,
            "first_name":        sl.get("first_name", ""),
            "last_name":         sl.get("last_name", ""),
            "company_name":      sl.get("company_name", ""),
            "location":          sl.get("location", ""),
            "city":              city,
            "original_campaign": row.get("campaign_name", ""),
            "max_seq_sent":      row.get("max_seq_sent"),
            "Subject1":          subject1,
            "Email1":            email1,
            "Email2":            email2,
            "Email3":            email3,
        })

    total = sum(len(v) for v in buckets.values())
    print(f"\n  PLG: {len(buckets['plg'])} | BB: {len(buckets['bb'])} | "
          f"CRE: {len(buckets['cre'])} | Other: {len(buckets['other'])} | Total: {total}")
    if missing_email1:
        print(f"  WARN: {missing_email1} leads had no Email1 in SmartLead — "
              f"review these in the JSON before loading.")
    if generated_email3:
        print(f"  INFO: {generated_email3} leads had no Email3 — generated fresh (no-link).")
    return buckets


# ── step 4: campaign creation ──────────────────────────────────────────────────

def create_campaign(name):
    resp = sl_post("campaigns/create", {"name": name})
    cid = resp.get("id")
    if not cid:
        raise RuntimeError(f"Create failed: {resp}")
    print(f"  Created '{name}' → ID {cid}")
    return cid


def configure_campaign(cid, daily_rate):
    sl_post(f"campaigns/{cid}/settings", {
        "send_as_plain_text": True,
        "force_plain_text": True,
        "enable_ai_esp_matching": True,
        "track_settings": ["DONT_TRACK_EMAIL_OPEN", "DONT_TRACK_LINK_CLICK"],
        "stop_lead_settings": "REPLY_TO_AN_EMAIL",
        "follow_up_percentage": 50,
    })
    sl_post(f"campaigns/{cid}/schedule", {
        "timezone": "America/New_York",
        "days_of_the_week": [1, 2, 3, 4, 5],
        "start_hour": "09:00",
        "end_hour": "19:00",
        "min_time_btw_emails": 30,
        "max_new_leads_per_day": daily_rate,
    })
    sl_post(f"campaigns/{cid}/sequences", {"sequences": [
        {
            "seq_number": 1,
            "seq_delay_details": {"delay_in_days": 0},
            "subject": "{{Subject1}}",
            "email_body": "<div>{{Email1}}</div><div><br></div>",
        },
        {
            "seq_number": 2,
            "seq_delay_details": {"delay_in_days": 3},
            "subject": "",
            "email_body": "<div>{{Email2}}</div>",
        },
        {
            "seq_number": 3,
            "seq_delay_details": {"delay_in_days": 5},
            "subject": "",
            "email_body": "<div>{{Email3}}</div>",
        },
    ]})
    print(f"  Settings, schedule, sequences applied.")


def assign_inboxes(cid, inbox_ids, daily_rate):
    sl_post(f"campaigns/{cid}/email-accounts", {"email_account_ids": inbox_ids})
    # Re-set daily rate now inboxes are locked in
    sl_post(f"campaigns/{cid}/schedule", {
        "timezone": "America/New_York",
        "days_of_the_week": [1, 2, 3, 4, 5],
        "start_hour": "09:00",
        "end_hour": "19:00",
        "min_time_btw_emails": 30,
        "max_new_leads_per_day": daily_rate,
    })
    print(f"  {len(inbox_ids)} inboxes assigned, daily rate = {daily_rate}.")


def load_leads(cid, leads, batch_size=100):
    total = len(leads)
    loaded = 0
    for i in range(0, total, batch_size):
        batch = leads[i:i + batch_size]
        sl_post(f"campaigns/{cid}/leads", {
            "lead_list": [
                {
                    "email":        ld["email"],
                    "first_name":   ld["first_name"],
                    "last_name":    ld["last_name"],
                    "company_name": ld["company_name"],
                    "location":     ld["location"],
                    "custom_fields": {
                        "Subject1": ld["Subject1"],
                        "Email1":   ld["Email1"],
                        "Email2":   ld["Email2"],
                        "Email3":   ld["Email3"],
                    },
                }
                for ld in batch
            ],
            "settings": {
                "ignore_global_block_list": False,
                "ignore_unsubscribe_list": False,
            },
        })
        loaded += len(batch)
        print(f"  [{loaded}/{total}] leads loaded")
        time.sleep(0.5)


def bq_record_enrollments(cid, campaign_name, leads):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    rows = [{
        "apollo_id":               None,
        "email":                   ld["email"],
        "smartlead_campaign_id":   cid,
        "smartlead_campaign_name": campaign_name,
        "segment":                 "bounce_reengagement",
        "enrolled_at":             now,
        "copy_variant":            "reuse_no_link",
    } for ld in leads]
    table = f"{PROJECT}.PLG_OUTBOUND.PLG_CAMPAIGN_ENROLLMENTS"
    job = bq.load_table_from_json(
        rows, table,
        job_config=bigquery.LoadJobConfig(
            schema=[
                bigquery.SchemaField("apollo_id",               "STRING"),
                bigquery.SchemaField("email",                   "STRING"),
                bigquery.SchemaField("smartlead_campaign_id",   "INT64"),
                bigquery.SchemaField("smartlead_campaign_name", "STRING"),
                bigquery.SchemaField("segment",                 "STRING"),
                bigquery.SchemaField("enrolled_at",             "TIMESTAMP"),
                bigquery.SchemaField("copy_variant",            "STRING"),
            ],
            write_disposition="WRITE_APPEND",
        ),
    )
    job.result()
    print(f"  BQ: {len(rows)} enrollments recorded.")


def print_bucket_summary(key, leads):
    cfg = CAMPAIGNS[key]
    has_e1 = sum(1 for l in leads if l.get("Email1"))
    has_e3 = sum(1 for l in leads if l.get("Email3"))
    orig_camps = sorted({l["original_campaign"] for l in leads if l.get("original_campaign")})
    print(f"\n  [{key.upper()}] {cfg['name']}")
    print(f"    Leads: {len(leads)} | Email1: {has_e1} | Email3: {has_e3}")
    print(f"    From campaigns: {', '.join(orig_camps) or '(none)'}")
    if leads:
        s = leads[0]
        print(f"    Sample: {s['first_name']} {s['last_name']} <{s['email']}> ({s['city']})")
        print(f"    Subject1: {s.get('Subject1') or '(empty)'}")
        if s.get("Email2"):
            print(f"    Email2 tail: ...{s['Email2'][-100:]}")
        if s.get("Email3"):
            print(f"    Email3 tail: ...{s['Email3'][-100:]}")


def launch_bucket(bucket_key, leads, args):
    cfg = CAMPAIGNS[bucket_key]
    name = cfg["name"]
    inbox_ids = [int(x.strip()) for x in (args.inbox_ids or "").split(",") if x.strip()]

    print(f"\n── Launching {bucket_key.upper()} ({len(leads)} leads) ──")
    cid = create_campaign(name)
    configure_campaign(cid, args.daily_rate)
    if inbox_ids:
        assign_inboxes(cid, inbox_ids, args.daily_rate)
    else:
        print("  ⚠️  No --inbox-ids — assign inboxes manually before launching.")
    load_leads(cid, leads)
    bq_record_enrollments(cid, name, leads)

    print(f"\n  Campaign {cid} ready.")
    print(f"     Checklist:")
    print(f"       - Enable AI categorization in SmartLead OLD UI")
    print(f"       - python smartlead_update_signatures.py --only-missing")
    print(f"       - Spot-check: GET /campaigns/{cid}/leads?limit=5")
    print(f"       - Launch: POST /campaigns/{cid}/status {{\"status\":\"START\"}}")
    return cid


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Bounce re-engagement — 3 campaigns")
    parser.add_argument("--out-dir",    default="/tmp/bounce",
                        help="Directory to save/load lead JSON files")
    parser.add_argument("--launch",     default=None,
                        choices=["plg", "bb", "cre", "other", "all"],
                        help="Which bucket to launch (or 'all')")
    parser.add_argument("--dry-run",    action="store_true",
                        help="Pull + transform + print summary, no API calls")
    parser.add_argument("--daily-rate", type=int, default=None)
    parser.add_argument("--inbox-ids",  default="",
                        help="Comma-separated SmartLead inbox account IDs")
    parser.add_argument("--skip-pull",  action="store_true",
                        help="Skip BQ/SmartLead pull; load from existing JSON files")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    if not bq:
        print("BigQuery unavailable — run: gcloud auth application-default login")
        sys.exit(1)
    if not SL_KEY:
        print("SMARTLEAD_API_KEY not found in .env")
        sys.exit(1)

    # ── Pull + transform ───────────────────────────────────────────────────────
    all_files_exist = all(
        os.path.exists(os.path.join(args.out_dir, cfg["file"]))
        for cfg in CAMPAIGNS.values()
    )

    if args.skip_pull and all_files_exist:
        print(f"Loading existing files from {args.out_dir}/...")
        buckets = {}
        for key, cfg in CAMPAIGNS.items():
            with open(os.path.join(args.out_dir, cfg["file"])) as f:
                buckets[key] = json.load(f)
            print(f"  {key.upper()}: {len(buckets[key])} leads")
    else:
        bq_rows = pull_bounced_leads()
        if not bq_rows:
            print("No bounced leads found.")
            sys.exit(0)

        campaign_ids = {r["campaign_id"] for r in bq_rows if r.get("campaign_id")}
        sl_data = pull_sl_custom_fields(campaign_ids)
        buckets = transform_and_bucket(bq_rows, sl_data)

        for key, cfg in CAMPAIGNS.items():
            path = os.path.join(args.out_dir, cfg["file"])
            with open(path, "w") as f:
                json.dump(buckets[key], f, indent=2)
            print(f"  Saved {key.upper()} ({len(buckets[key])} leads) → {path}")

    # ── Summary ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("BOUNCE RE-ENGAGEMENT SUMMARY")
    print("=" * 60)
    for key in CAMPAIGNS:
        print_bucket_summary(key, buckets.get(key, []))

    if args.dry_run or not args.launch:
        if not args.launch:
            print(f"\nReview files in {args.out_dir}/, then run:")
            print(f"  --skip-pull --launch [plg|bb|cre|all] --daily-rate N --inbox-ids id1,id2")
        return

    # ── Launch ─────────────────────────────────────────────────────────────────
    if not args.daily_rate:
        print("--daily-rate required with --launch")
        sys.exit(1)

    to_launch = list(CAMPAIGNS.keys()) if args.launch == "all" else [args.launch]
    for key in to_launch:
        leads = buckets.get(key, [])
        if not leads:
            print(f"  {key.upper()}: no leads — skipping.")
            continue
        launch_bucket(key, leads, args)


if __name__ == "__main__":
    main()
