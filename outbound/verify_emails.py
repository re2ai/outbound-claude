#!/usr/bin/env python3
"""
Email verification via Zerobounce before loading leads into SmartLead.

Uses the batch endpoint (/v2/validatebatch) — 100 emails per request.
Far fewer HTTP calls than single-email endpoint, no Cloudflare rate limit issues.

Usage:
  python verify_emails.py --file /tmp/ins_v3_enriched.json --out /tmp/ins_v3_verified.json

Reads a list of enriched contacts, verifies each email via Zerobounce,
writes two output files:
  {out}              — contacts with status=valid (safe to send)
  {out}.catchall.json — catch_all contacts (optional, your call)
  {out}.removed.json  — invalid/unknown/spamtrap (do not send)

RESUME BEHAVIOR (default):
  If output files already exist, loads them and skips already-verified emails.
  Re-running the same command is free — only pays for new emails.
  Pass --no-resume to force a full re-run.

Status meanings:
  valid       → confirmed deliverable. Send.
  catch_all   → domain accepts all mail, can't fully verify. Risky but usable.
  invalid     → hard bounce guaranteed. Never send.
  unknown     → server timed out / can't verify. Skip.
  spamtrap    → spam trap address. Never send.
  do_not_mail → role address (info@, admin@) or known bad. Skip.
  abuse       → known complainer. Skip.

Cost: 1 credit per email. Check credits first:
  python verify_emails.py --credits
"""

import os
import sys
import json
import time
import argparse
import requests
from collections import Counter
from dotenv import load_dotenv

load_dotenv()

ZB_KEY  = os.getenv("ZEROBOUNCE_API_KEY")
ZB_BASE = "https://api.zerobounce.net/v2"
BATCH_SIZE = 100  # max per Zerobounce batch endpoint

SEND_STATUSES  = {"valid"}
RISKY_STATUSES = {"catch_all", "catch-all"}


def get_credits():
    r = requests.get(f"{ZB_BASE}/getcredits", params={"api_key": ZB_KEY}, timeout=10)
    r.raise_for_status()
    return int(r.json().get("Credits", 0))


def verify_batch_api(emails):
    """
    Verify up to 100 emails in one POST to /v2/validatebatch.
    Returns dict of {email: {status, sub_status}}.
    """
    payload = {
        "api_key": ZB_KEY,
        "email_batch": [{"email_address": e} for e in emails],
    }
    r = requests.post(f"{ZB_BASE}/validatebatch", json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()

    results = {}
    for item in data.get("email_batch", []):
        addr = item.get("address", "")
        results[addr] = {
            "status":     item.get("status", "unknown").lower(),
            "sub_status": item.get("sub_status", ""),
        }
    return results


def load_existing(out_path):
    """Load already-verified contacts from existing output files. Returns (valid, risky, removed, done_emails)."""
    valid, risky, removed = [], [], []
    catchall_path = out_path.replace(".json", "") + ".catchall.json"
    removed_path  = out_path.replace(".json", "") + ".removed.json"

    for path, bucket in [(out_path, valid), (catchall_path, risky), (removed_path, removed)]:
        try:
            with open(path) as f:
                for c in json.load(f):
                    if c.get("_zb_status") != "error":
                        bucket.append(c)
        except FileNotFoundError:
            pass

    done = {c["email"] for bucket in (valid, risky, removed) for c in bucket if c.get("email")}
    return valid, risky, removed, done


def save_outputs(out_path, valid, risky, removed, include_catchall=False):
    catchall_path = out_path.replace(".json", "") + ".catchall.json"
    removed_path  = out_path.replace(".json", "") + ".removed.json"

    safe = valid + (risky if include_catchall else [])
    with open(out_path, "w") as f:
        json.dump(safe, f, indent=2)
    with open(catchall_path, "w") as f:
        json.dump(risky, f, indent=2)
    with open(removed_path, "w") as f:
        json.dump(removed, f, indent=2)


def verify_contacts(contacts, valid, risky, removed):
    """Verify all contacts using batch endpoint. Appends to valid/risky/removed in place."""
    total = len(contacts)
    processed = 0

    for chunk_start in range(0, total, BATCH_SIZE):
        chunk = contacts[chunk_start:chunk_start + BATCH_SIZE]
        emails = [c["email"] for c in chunk if c.get("email")]

        if not emails:
            removed.extend({**c, "_zb_status": "no_email"} for c in chunk)
            processed += len(chunk)
            continue

        try:
            results = verify_batch_api(emails)

            for contact in chunk:
                email = contact.get("email", "")
                if not email:
                    removed.append({**contact, "_zb_status": "no_email"})
                    continue

                res = results.get(email, {})
                status     = res.get("status", "unknown")
                sub_status = res.get("sub_status", "")
                contact_out = {**contact, "_zb_status": status, "_zb_sub_status": sub_status}

                if status in SEND_STATUSES:
                    valid.append(contact_out)
                elif status in RISKY_STATUSES:
                    risky.append(contact_out)
                else:
                    removed.append(contact_out)

            processed += len(chunk)
            print(f"  [{processed}/{total}] valid={len(valid)} catchall={len(risky)} removed={len(removed)}")
            time.sleep(0.5)  # small pause between batch requests

        except Exception as e:
            print(f"  Batch error on chunk {chunk_start}-{chunk_start+len(chunk)}: {e} — skipping (will retry next run)")
            time.sleep(3)


def main():
    parser = argparse.ArgumentParser(description="Verify emails via Zerobounce (batch mode)")
    parser.add_argument("--file",            help="Input JSON file (list of contact dicts with 'email' field)")
    parser.add_argument("--out",             help="Output path for valid contacts")
    parser.add_argument("--include-catchall", action="store_true",
                        help="Include catch_all in valid output")
    parser.add_argument("--no-resume",       action="store_true",
                        help="Ignore existing output and re-verify everything")
    parser.add_argument("--credits",         action="store_true", help="Check remaining credits and exit")
    args = parser.parse_args()

    if not ZB_KEY:
        print("ZEROBOUNCE_API_KEY not set in .env")
        sys.exit(1)

    if args.credits:
        print(f"Zerobounce credits remaining: {get_credits()}")
        return

    if not args.file or not args.out:
        parser.print_help()
        sys.exit(1)

    with open(args.file) as f:
        contacts = json.load(f)
    print(f"Loaded {len(contacts)} contacts from {args.file}")

    if args.no_resume:
        valid, risky, removed, done = [], [], [], set()
    else:
        valid, risky, removed, done = load_existing(args.out)
        if done:
            print(f"Resuming: {len(done)} already verified (skipping)")

    to_verify = [c for c in contacts if c.get("email") not in done]
    if not to_verify:
        print("All contacts already verified.")
    else:
        credits = get_credits()
        print(f"Credits remaining: {credits}")
        print(f"Verifying {len(to_verify)} contacts in batches of {BATCH_SIZE} (~{-(-len(to_verify)//BATCH_SIZE)} requests, est. cost ~${len(to_verify)*0.008:.2f})\n")
        if credits < len(to_verify):
            print(f"WARNING: Only {credits} credits — autopay may top up as we go.\n")

        verify_contacts(to_verify, valid, risky, removed)

    save_outputs(args.out, valid, risky, removed, args.include_catchall)

    total = len(valid) + len(risky) + len(removed)
    skipped = len(contacts) - len(to_verify)
    print(f"\n=== Results ===")
    print(f"Valid (safe to send):  {len(valid):>5}" + (f" ({len(valid)/total*100:.1f}%)" if total else ""))
    print(f"Catch-all (risky):     {len(risky):>5}" + (f" ({len(risky)/total*100:.1f}%)" if total else ""))
    print(f"Removed (skip):        {len(removed):>5}" + (f" ({len(removed)/total*100:.1f}%)" if total else ""))
    if skipped:
        print(f"Skipped (already done): {skipped}")
    print(f"\nValid list:   {args.out}")
    catchall_path = args.out.replace(".json","") + ".catchall.json"
    removed_path  = args.out.replace(".json","") + ".removed.json"
    print(f"Catch-all:    {catchall_path}")
    print(f"Removed:      {removed_path}")

    if total:
        print("\nStatus breakdown:")
        for s, n in Counter(c.get("_zb_status") for c in valid + risky + removed).most_common():
            print(f"  {s}: {n}")


if __name__ == "__main__":
    main()
