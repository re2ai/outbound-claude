#!/usr/bin/env python3
"""
Round-2 CRE_LEADS fixes:
  1. first_name OK but Email1 still says "Hey there," (18 rows — order bug from round 1)
  2. Additional recoverable names missed by vowel heuristic (33 rows: Scott, Steve, Brian, Greg, etc.)
  3. Role/company names used as first_name (JRealty, Community, WAM) → revert to 'there'
  4. Capitalization: DAVID → David, farzad → Farzad

Usage:
  python fix_cre_leads2.py --dry-run
  python fix_cre_leads2.py
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

# Common English first names missed by vowel heuristic (consonant at position 1)
# Only include names that are unambiguously first names at their email prefix length
EXTRA_NAMES = {
    "scott", "steve", "eric", "brian", "greg", "frank", "floyd",
    "andrus", "troy", "brad", "fred", "adam", "chad", "blake",
    "bruce", "brett", "brent", "craig", "drew", "clark", "clay",
    "clint", "cody", "cole", "cory", "grant", "kurt", "kyle",
    "mark", "paul", "rob", "ryan", "scott", "skip", "stan",
    "troy", "wade", "will",
}

# Role/company names that should never be used as a first_name
ROLE_NAMES = {"jrealty", "community", "wam"}

VOWELS = set("aeiouy")


def extract_first_name(email: str, full_name: str) -> str | None:
    """
    Recover a real first_name. Combines original vowel-heuristic with explicit name whitelist.
    Returns the recovered name or None.
    """
    if not email or not full_name:
        return None

    prefix_match = re.match(r'^([a-zA-Z]{3,8})', email.split('@')[0])
    if not prefix_match:
        return None
    prefix = prefix_match.group(1).lower()

    # Validate against full_name: must be "SingleChar Rest" and join must match prefix
    parts = full_name.strip().split(' ', 1)
    if len(parts) != 2 or len(parts[0]) != 1:
        return None
    joined = (parts[0] + parts[1]).lower()
    if joined != prefix:
        return None

    # Accept if position-1 is a vowel (original rule) OR prefix is in the whitelist
    position1_ok = len(prefix) >= 2 and prefix[1] in VOWELS
    whitelist_ok = prefix in EXTRA_NAMES

    if not position1_ok and not whitelist_ok:
        return None

    return prefix[0].upper() + prefix[1:].lower()


def fix_greeting(body: str, old_name: str, new_name: str) -> str:
    """Replace greeting in email body."""
    return body.replace(f"Hey {old_name},", f"Hey {new_name},", 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    dry_run = args.dry_run

    print(f"Loading CRE_LEADS{'  [DRY RUN]' if dry_run else ''}...")
    rows = list(bq.query(f"SELECT * FROM `{TABLE}`").result())
    schema_fields = bq.get_table(TABLE).schema
    leads = [dict(row) for row in rows]
    print(f"Loaded {len(leads)} leads\n")

    counts = {
        "greeting_fixed": 0,
        "new_name_recovered": 0,
        "role_name_reverted": 0,
        "capitalization_fixed": 0,
        "unchanged": 0,
    }
    fixed = []

    for lead in leads:
        changes = {}
        fn = (lead.get("first_name") or "").strip()

        # ── 1. Role/company names → revert to 'there' ──────────────────────
        if fn.lower() in ROLE_NAMES:
            changes["first_name"] = "there"
            for field in ("Email1", "Email1a", "Email1b"):
                body = lead.get(field, "") or ""
                if f"Hey {fn}," in body:
                    changes[field] = body.replace(f"Hey {fn},", "Hey there,", 1)
            counts["role_name_reverted"] += 1
            if dry_run:
                print(f"  [role] {lead['email']}  '{fn}' -> 'there'")

        # ── 2. Capitalization fixes ─────────────────────────────────────────
        elif fn == fn.upper() and len(fn) > 2 and fn.isalpha():
            # All-caps name like DAVID
            fixed_fn = fn.capitalize()
            changes["first_name"] = fixed_fn
            for field in ("Email1", "Email1a", "Email1b"):
                body = lead.get(field, "") or ""
                if f"Hey {fn}," in body:
                    changes[field] = body.replace(f"Hey {fn},", f"Hey {fixed_fn},", 1)
            counts["capitalization_fixed"] += 1
            if dry_run:
                print(f"  [caps] {lead['email']}  '{fn}' -> '{fixed_fn}'")

        elif fn and fn.lower() != "there" and fn[0].islower() and fn.replace(".", "").replace(" ", "").isalpha():
            # Lowercase name like farzad
            fixed_fn = fn.capitalize()
            changes["first_name"] = fixed_fn
            for field in ("Email1", "Email1a", "Email1b"):
                body = lead.get(field, "") or ""
                if f"Hey {fn}," in body:
                    changes[field] = body.replace(f"Hey {fn},", f"Hey {fixed_fn},", 1)
            counts["capitalization_fixed"] += 1
            if dry_run:
                print(f"  [lower] {lead['email']}  '{fn}' -> '{fixed_fn}'")

        # ── 3. first_name was fixed but greeting in body is still 'there' ──
        elif fn.lower() != "there":
            for field in ("Email1", "Email1a", "Email1b"):
                body = lead.get(field, "") or ""
                if body and "Hey there," in body and f"Hey {fn}," not in body:
                    changes[field] = body.replace("Hey there,", f"Hey {fn},", 1)
            if changes:
                counts["greeting_fixed"] += 1
                if dry_run and counts["greeting_fixed"] <= 5:
                    preview = changes.get("Email1", "")[:100]
                    print(f"  [greeting] {lead['email']}  first_name={fn!r}")
                    print(f"    Email1 preview: {preview!r}")

        # ── 4. Still 'there' — try expanded name recovery ──────────────────
        elif fn.lower() == "there":
            recovered = extract_first_name(
                lead.get("email", ""),
                lead.get("full_name", "")
            )
            if recovered:
                changes["first_name"] = recovered
                for field in ("Email1", "Email1a", "Email1b"):
                    body = lead.get(field, "") or ""
                    if "Hey there," in body:
                        changes[field] = body.replace("Hey there,", f"Hey {recovered},", 1)
                counts["new_name_recovered"] += 1
                if dry_run and counts["new_name_recovered"] <= 10:
                    print(f"  [name] {lead['email']}  full_name={lead.get('full_name')!r} => {recovered}")

        if changes:
            lead.update(changes)
        else:
            counts["unchanged"] += 1

        fixed.append(lead)

    print(f"\n=== Fix summary ===")
    print(f"  Greeting body fixed (was missed):  {counts['greeting_fixed']}")
    print(f"  New names recovered:               {counts['new_name_recovered']}")
    print(f"  Role names reverted to 'there':    {counts['role_name_reverted']}")
    print(f"  Capitalization fixed:              {counts['capitalization_fixed']}")
    print(f"  Unchanged:                         {counts['unchanged']}")
    print(f"  Total:                             {len(fixed)}")

    if dry_run:
        print("\n[DRY RUN] No changes written.")
        return

    print("\nUploading to BQ...")
    upload = []
    for lead in fixed:
        row = {}
        for field in schema_fields:
            val = lead.get(field.name)
            if val is None:
                val = "" if field.field_type == "STRING" else None
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
