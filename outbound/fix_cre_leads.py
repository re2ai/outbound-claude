#!/usr/bin/env python3
"""
Fix CRE_LEADS data issues:
  1. first_name = 'there' (761 rows) — reconstruct from email prefix using full_name validation
  2. "your listing at your listing" (72 rows) — Subject1/Email1/1a/1b with empty listing_address
  3. city_extracted = '' but derivable from listing_address (1 row: Indianapolis)

Usage:
  python fix_cre_leads.py --dry-run    # preview changes only
  python fix_cre_leads.py              # apply to BQ
"""

import re
import sys
import warnings
import argparse
from google.cloud import bigquery
from dotenv import load_dotenv

load_dotenv(r"C:\Users\evane\Documents\Coding\scorecard\re2scorecard2026\.env")
warnings.filterwarnings("ignore")

TABLE = "tenant-recruitin-1575995920662.SLG_OUTBOUND.CRE_LEADS"
bq = bigquery.Client(project="tenant-recruitin-1575995920662")

VOWELS = set("aeiouy")


def extract_first_name(email: str, full_name: str) -> str | None:
    """
    Try to recover a real first_name from the email prefix + full_name.

    full_name for these rows is always "X Rest" where X is one char and the
    first letter was accidentally split off (e.g. "D Anielle" → "Danielle",
    "J Ason" → "Jason").  We only accept the result when:
      - The email prefix (leading letters only) is 4–8 chars
      - Position 1 of the prefix is a vowel (filters out "Jherzog"-style initials)
      - The joined full_name (no space, lowercase) matches the email prefix

    Returns the recovered name (title-cased) or None.
    """
    if not email or not full_name:
        return None

    # Email prefix: leading letters only, lowercase
    prefix_match = re.match(r'^([a-zA-Z]{4,8})', email.split('@')[0])
    if not prefix_match:
        return None
    prefix = prefix_match.group(1).lower()

    # Position-1 must be a vowel (avoids "jherzog", "jsmith", "dstevenson" etc.)
    if len(prefix) < 2 or prefix[1] not in VOWELS:
        return None

    # Validate against full_name: must be "SingleChar Rest" and join must match prefix
    parts = full_name.strip().split(' ', 1)
    if len(parts) != 2 or len(parts[0]) != 1:
        return None
    joined = (parts[0] + parts[1]).lower()
    if joined != prefix:
        return None

    return prefix[0].upper() + prefix[1:].lower()


def fix_listing_copy(row: dict) -> dict:
    """
    For rows where listing_address is blank the template produced
    'Subject: your listing at your listing' and bodies with
    'at your listing'.  Clean both up.
    """
    changes = {}

    subj = row.get("Subject1", "")
    if "your listing at your listing" in subj:
        changes["Subject1"] = re.sub(
            r'\s*at your listing', '', subj
        ).strip()

    for field in ("Email1", "Email1a", "Email1b"):
        body = row.get(field, "") or ""
        if not body:
            continue
        # "at your listing were" → ", were"
        new_body = re.sub(
            r'\bat your listing\b',
            '',
            body
        )
        # Clean up double spaces or leading comma artifact
        new_body = re.sub(r'  +', ' ', new_body)
        new_body = re.sub(r' ,', ',', new_body)
        if new_body != body:
            changes[field] = new_body

    return changes


def fix_city_copy(row: dict, old_city: str, new_city: str) -> dict:
    """Replace 'in the area' with 'in {new_city}' in all email fields."""
    changes = {}
    for field in ("Email1", "Email1a", "Email1b", "Email2", "Email3"):
        body = row.get(field, "") or ""
        if not body:
            continue
        new_body = body.replace("in the area", f"in {new_city}")
        if new_body != body:
            changes[field] = new_body
    if changes:
        changes["city_extracted"] = new_city
    return changes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Print proposed changes without writing to BQ")
    args = parser.parse_args()
    dry_run = args.dry_run

    print(f"Loading CRE_LEADS from BQ{'  [DRY RUN]' if dry_run else ''}...")
    rows = list(bq.query(f"SELECT * FROM `{TABLE}`").result())
    schema = [field.name for field in bq.get_table(TABLE).schema]
    leads = [dict(row) for row in rows]
    print(f"Loaded {len(leads)} leads\n")

    counts = {"first_name": 0, "listing": 0, "city": 0, "unchanged": 0}
    fixed = []

    for lead in leads:
        changes = {}

        # ── 1. first_name = 'there' ────────────────────────────────────────
        if (lead.get("first_name") or "").strip().lower() == "there":
            recovered = extract_first_name(
                lead.get("email", ""),
                lead.get("full_name", "")
            )
            if recovered:
                changes["first_name"] = recovered
                # Also update greetings in email bodies
                for field in ("Email1", "Email1a", "Email1b"):
                    body = lead.get(field, "") or ""
                    if "Hey there," in body:
                        changes[field] = body.replace("Hey there,", f"Hey {recovered},", 1)
                counts["first_name"] += 1
                if dry_run and counts["first_name"] <= 10:
                    print(f"  [first_name] {lead['email']}")
                    print(f"    full_name={lead.get('full_name')!r}  =>  {recovered}")

        # ── 2. Empty listing_address → broken subject/body ────────────────
        if not (lead.get("listing_address") or "").strip():
            listing_changes = fix_listing_copy(lead)
            if listing_changes:
                changes.update(listing_changes)
                counts["listing"] += 1
                if dry_run and counts["listing"] <= 3:
                    print(f"\n  [listing] {lead['email']}")
                    print(f"    Subject1 before: {lead.get('Subject1')!r}")
                    print(f"    Subject1 after:  {listing_changes.get('Subject1', lead.get('Subject1'))!r}")
                    preview = listing_changes.get("Email1", lead.get("Email1", ""))[:150]
                    print(f"    Email1 preview: {preview!r}")

        # ── 3. city derivable from listing_address ────────────────────────
        city = (lead.get("city_extracted") or "").strip()
        addr = (lead.get("listing_address") or "").strip()
        if not city and addr:
            # Extract city: the title-case word immediately before "ST ZIPCODE"
            # (requires 2-letter all-caps state abbreviation followed by 5-digit zip)
            m = re.search(r'([A-Z][a-z]+)\s+[A-Z]{2}\s+\d{5}', addr)
            if m:
                extracted_city = m.group(1).strip()
                city_changes = fix_city_copy(lead, city, extracted_city)
                if city_changes:
                    changes.update(city_changes)
                    counts["city"] += 1
                    if dry_run:
                        print(f"\n  [city] {lead['email']}")
                        print(f"    listing_address={addr!r}  =>  city={extracted_city!r}")
                        body_preview = city_changes.get("Email1", lead.get("Email1", ""))[:200]
                        print(f"    Email1 preview: {body_preview!r}")

        if changes:
            lead.update(changes)
        else:
            counts["unchanged"] += 1

        fixed.append(lead)

    print(f"\n=== Fix summary ===")
    print(f"  first_name recovered:      {counts['first_name']}")
    print(f"  listing subject/body fixed: {counts['listing']}")
    print(f"  city extracted + emails:    {counts['city']}")
    print(f"  unchanged:                  {counts['unchanged']}")
    print(f"  total:                      {len(fixed)}")

    if dry_run:
        print("\n[DRY RUN] No changes written. Re-run without --dry-run to apply.")
        return

    # ── Upload to BQ (WRITE_TRUNCATE) ─────────────────────────────────────
    print("\nUploading to BQ...")
    schema_fields = bq.get_table(TABLE).schema

    # Convert Row objects to plain dicts matching original schema
    upload = []
    for lead in fixed:
        row = {}
        for field in schema_fields:
            val = lead.get(field.name)
            if val is None:
                val = "" if field.field_type == "STRING" else None
            # BQ JSON loader needs timestamps as ISO strings
            if field.field_type == "TIMESTAMP" and hasattr(val, "isoformat"):
                val = val.isoformat()
            row[field.name] = val
        upload.append(row)

    job = bq.load_table_from_json(
        upload, TABLE,
        job_config=bigquery.LoadJobConfig(
            schema=schema_fields,
            write_disposition="WRITE_TRUNCATE",
        )
    )
    job.result()
    print(f"Done. {len(upload)} rows written to {TABLE}")


if __name__ == "__main__":
    main()
