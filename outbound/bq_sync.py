#!/usr/bin/env python3
"""
BigQuery sync for PLG outbound contacts and campaign enrollments.

Two functions:
  1. upsert_contacts()       — write Apollo-enriched contacts to PLG_OUTBOUND.PLG_CONTACTS
  2. record_enrollments()    — write SmartLead campaign enrollment records to PLG_OUTBOUND.PLG_CAMPAIGN_ENROLLMENTS

Run after every enrichment batch and after every SmartLead lead load.
This is the source of truth — not local JSON files, not SmartLead alone.

Usage:
  python bq_sync.py contacts  --file /tmp/ins_v3_enriched.json --segment insurance --keyword "independent insurance agent"
  python bq_sync.py enroll    --campaign-id 2986711 --campaign-name "PLG - Commercial Insurance - Blunt - Claude" --segment insurance --variant blunt
  python bq_sync.py backfill  # syncs all current SmartLead PLG campaign leads from API
"""

import os
import sys
import json
import argparse
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

try:
    from google.cloud import bigquery
    bq = bigquery.Client(project="tenant-recruitin-1575995920662")
except Exception as e:
    print(f"BigQuery init failed: {e}")
    bq = None

PROJECT   = "tenant-recruitin-1575995920662"
DATASET   = "PLG_OUTBOUND"
CONTACTS  = f"{PROJECT}.{DATASET}.PLG_CONTACTS"
ENROLLMENTS = f"{PROJECT}.{DATASET}.PLG_CAMPAIGN_ENROLLMENTS"

SMARTLEAD_KEY = os.getenv("SMARTLEAD_API_KEY")
SL_BASE = "https://server.smartlead.ai/api/v1"
SL_P = {"api_key": SMARTLEAD_KEY}

NOW = datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def sl_get(endpoint, params=None):
    p = {**SL_P, **(params or {})}
    r = requests.get(f"{SL_BASE}/{endpoint}", params=p, timeout=30)
    r.raise_for_status()
    return r.json()


def bq_merge_contacts(rows):
    """
    Upsert rows into PLG_CONTACTS using a temp table + MERGE on apollo_id (or email if no apollo_id).
    Skips rows with no email.
    """
    rows = [r for r in rows if r.get("email")]
    if not rows:
        print("  No rows with email — nothing to write.")
        return

    # Temp table name
    tmp = f"{PROJECT}.{DATASET}._tmp_contacts_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    schema = [
        bigquery.SchemaField("apollo_id",       "STRING"),
        bigquery.SchemaField("first_name",      "STRING"),
        bigquery.SchemaField("last_name",       "STRING"),
        bigquery.SchemaField("email",           "STRING"),
        bigquery.SchemaField("company_name",    "STRING"),
        bigquery.SchemaField("company_domain",  "STRING"),
        bigquery.SchemaField("title",           "STRING"),
        bigquery.SchemaField("city",            "STRING"),
        bigquery.SchemaField("state",           "STRING"),
        bigquery.SchemaField("linkedin_url",    "STRING"),
        bigquery.SchemaField("segment",         "STRING"),
        bigquery.SchemaField("apollo_keyword",  "STRING"),
        bigquery.SchemaField("enriched_at",     "TIMESTAMP"),
        bigquery.SchemaField("discovered_at",   "TIMESTAMP"),
    ]

    # Write temp table
    job_cfg = bigquery.LoadJobConfig(schema=schema, write_disposition="WRITE_TRUNCATE")
    job = bq.load_table_from_json(rows, tmp, job_config=job_cfg)
    job.result()
    print(f"  Loaded {len(rows)} rows to temp table.")

    # MERGE into PLG_CONTACTS (match on apollo_id if present, else email)
    merge_sql = f"""
    MERGE `{CONTACTS}` T
    USING `{tmp}` S
    ON (S.apollo_id IS NOT NULL AND T.apollo_id = S.apollo_id)
       OR (S.apollo_id IS NULL AND T.email = S.email)
    WHEN MATCHED THEN UPDATE SET
      first_name     = COALESCE(S.first_name, T.first_name),
      last_name      = COALESCE(S.last_name, T.last_name),
      email          = COALESCE(S.email, T.email),
      company_name   = COALESCE(S.company_name, T.company_name),
      company_domain = COALESCE(S.company_domain, T.company_domain),
      title          = COALESCE(S.title, T.title),
      city           = COALESCE(S.city, T.city),
      state          = COALESCE(S.state, T.state),
      linkedin_url   = COALESCE(S.linkedin_url, T.linkedin_url),
      segment        = COALESCE(S.segment, T.segment),
      apollo_keyword = COALESCE(S.apollo_keyword, T.apollo_keyword),
      enriched_at    = COALESCE(S.enriched_at, T.enriched_at)
    WHEN NOT MATCHED THEN INSERT ROW
    """
    job = bq.query(merge_sql)
    result = job.result()
    print(f"  MERGE complete.")

    # Drop temp table
    bq.delete_table(tmp, not_found_ok=True)


def bq_insert_enrollments(rows):
    """Append enrollment rows. Deduped by apollo_id+campaign_id in queries — inserts are append-only."""
    if not rows:
        return
    job_cfg = bigquery.LoadJobConfig(
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
    )
    job = bq.load_table_from_json(rows, ENROLLMENTS, job_config=job_cfg)
    job.result()
    print(f"  Wrote {len(rows)} enrollment rows.")


# ─────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────

def cmd_contacts(args):
    """Load enriched contacts from a local JSON file into PLG_CONTACTS."""
    print(f"Loading contacts from {args.file}...")
    with open(args.file) as f:
        raw = json.load(f)

    rows = []
    for c in raw:
        rows.append({
            "apollo_id":      c.get("id") or c.get("apollo_id"),
            "first_name":     c.get("first_name"),
            "last_name":      c.get("last_name"),
            "email":          c.get("email"),
            "company_name":   c.get("company") or c.get("company_name"),
            "company_domain": c.get("domain") or c.get("company_domain"),
            "title":          c.get("title"),
            "city":           c.get("city"),
            "state":          c.get("state"),
            "linkedin_url":   c.get("linkedin") or c.get("linkedin_url"),
            "segment":        args.segment,
            "apollo_keyword": args.keyword,
            "enriched_at":    NOW,
            "discovered_at":  NOW,
        })

    print(f"  {len(rows)} contacts to upsert ({sum(1 for r in rows if r['email'])} with email).")
    bq_merge_contacts(rows)
    print("Done.")


def cmd_enroll(args):
    """
    Pull all leads from a SmartLead campaign and record enrollments in PLG_CAMPAIGN_ENROLLMENTS.
    Skips any email already recorded for this campaign_id.
    """
    print(f"Recording enrollments for campaign {args.campaign_id}...")

    # Get existing enrollments for this campaign to avoid dupes
    existing_sql = f"""
        SELECT email FROM `{ENROLLMENTS}`
        WHERE smartlead_campaign_id = {args.campaign_id}
    """
    try:
        existing = {row.email for row in bq.query(existing_sql).result()}
        print(f"  {len(existing)} already recorded for this campaign.")
    except Exception:
        existing = set()

    # Pull all leads from SmartLead
    # Response: {"total_leads": N, "data": [{"lead": {...}, "status": ..., ...}], ...}
    leads = []
    offset = 0
    while True:
        result = sl_get(f"campaigns/{args.campaign_id}/leads", {"limit": 100, "offset": offset})
        batch = result.get("data", []) if isinstance(result, dict) else result
        if not batch:
            break
        leads.extend(batch)
        if len(batch) < 100:
            break
        offset += 100

    print(f"  {len(leads)} leads in SmartLead campaign.")

    rows = []
    for item in leads:
        lead = item.get("lead", item)  # nested under "lead" key
        email = lead.get("email", "")
        if not email or email in existing:
            continue
        cf = lead.get("custom_fields") or {}
        rows.append({
            "apollo_id":               cf.get("apollo_id") or None,
            "email":                   email,
            "smartlead_campaign_id":   args.campaign_id,
            "smartlead_campaign_name": args.campaign_name,
            "segment":                 args.segment,
            "enrolled_at":             item.get("created_at") or NOW,
            "copy_variant":            args.variant or None,
        })

    bq_insert_enrollments(rows)
    print(f"Done. {len(rows)} new enrollments recorded.")


def cmd_backfill(args):
    """
    Pull all current PLG SmartLead campaigns and record any missing enrollments.
    Useful for catching up on campaigns that were loaded before bq_sync existed.
    """
    print("Backfilling enrollments from all active PLG campaigns...")
    camps = sl_get("campaigns/")
    plg_camps = [c for c in camps if "PLG" in c.get("name","").upper()
                 and c.get("status") in ("ACTIVE","PAUSED","COMPLETED")]

    for c in plg_camps:
        print(f"\n  [{c['id']}] {c['name']}")
        # Guess segment from name
        name_lower = c["name"].lower()
        if "insurance" in name_lower:       segment = "insurance"
        elif "janitorial" in name_lower:    segment = "janitorial"
        elif "catering" in name_lower:      segment = "catering"
        elif "it solution" in name_lower:   segment = "it_msp"
        elif "cleaners" in name_lower:      segment = "commercial_cleaners"
        elif "signage" in name_lower:       segment = "signage"
        elif "web design" in name_lower:    segment = "web_design"
        elif "marketing" in name_lower:     segment = "local_marketing"
        else:                               segment = "unknown"

        variant = None
        if "blunt" in name_lower:           variant = "blunt"
        elif "more capacity" in name_lower: variant = "more_capacity"
        elif "claude" in name_lower:        variant = "claude"

        # Fake an args-like object
        class A: pass
        a = A()
        a.campaign_id   = c["id"]
        a.campaign_name = c["name"]
        a.segment       = segment
        a.variant       = variant
        cmd_enroll(a)

    print("\nBackfill complete.")


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Sync PLG data to BigQuery")
    sub = parser.add_subparsers(dest="command")

    # contacts
    p_contacts = sub.add_parser("contacts", help="Upload enriched contacts from a JSON file")
    p_contacts.add_argument("--file",    required=True, help="Path to enriched JSON (list of contact dicts)")
    p_contacts.add_argument("--segment", required=True, help="ICP segment name e.g. insurance")
    p_contacts.add_argument("--keyword", required=True, help="Apollo keyword used to find these contacts")

    # enroll
    p_enroll = sub.add_parser("enroll", help="Record campaign enrollments for one SmartLead campaign")
    p_enroll.add_argument("--campaign-id",   required=True, type=int)
    p_enroll.add_argument("--campaign-name", required=True)
    p_enroll.add_argument("--segment",       required=True)
    p_enroll.add_argument("--variant",       default=None, help="Copy variant e.g. blunt, claude, more_capacity")

    # backfill
    sub.add_parser("backfill", help="Backfill enrollments from all current PLG SmartLead campaigns")

    args = parser.parse_args()
    if not bq:
        print("BigQuery not available. Check gcloud credentials.")
        sys.exit(1)

    if args.command == "contacts":
        cmd_contacts(args)
    elif args.command == "enroll":
        cmd_enroll(args)
    elif args.command == "backfill":
        cmd_backfill(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
