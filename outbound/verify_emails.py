#!/usr/bin/env python3
"""
Email verification via BillionVerify before loading leads into SmartLead.

Uses the bulk endpoint (/v1/verify/bulk) — 50 emails per request (API limit).
Auth: BV-API-KEY header.

Usage:
  python verify_emails.py --file /tmp/enriched.json --out /tmp/verified.json

Reads a list of enriched contacts, verifies each email via BillionVerify,
writes three output files:
  {out}               — contacts with is_deliverable=True, not catchall (safe to send)
  {out}.catchall.json — catch_all domains (risky but sometimes usable)
  {out}.removed.json  — undeliverable / unknown / disposable / role (do not send)

RESUME BEHAVIOR (default):
  If output files already exist, loads them and skips already-verified emails.
  Re-running the same command is free — only pays for new emails.
  Pass --no-resume to force a full re-run.

Status logic (using BillionVerify response fields):
  is_deliverable=True, is_catchall=False  → valid   → send
  is_catchall=True                        → risky   → catchall bucket (your call)
  is_deliverable=False                    → removed → never send
  error / timeout                         → removed → skip

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

BV_KEY   = os.getenv("BillionVerify_API_KEY") or os.getenv("BILLIONVERIFY_API_KEY")
BV_BASE  = "https://api.billionverify.com/v1"
BV_HDR   = {"BV-API-KEY": BV_KEY, "Content-Type": "application/json"}
BATCH_SIZE = 50  # BillionVerify bulk endpoint max


def get_credits():
    r = requests.get(f"{BV_BASE}/credits", headers=BV_HDR, timeout=10)
    r.raise_for_status()
    return int(r.json()["data"]["credits_balance"])


def verify_batch_api(emails):
    """
    Verify up to 50 emails in one POST to /v1/verify/bulk.
    Returns dict of {email: {is_deliverable, is_catchall, status, score}}.
    """
    r = requests.post(f"{BV_BASE}/verify/bulk", headers=BV_HDR,
                      json={"emails": emails}, timeout=60)
    r.raise_for_status()
    data = r.json()

    results = {}
    for item in data.get("data", {}).get("results", []):
        addr = item.get("email", "")
        results[addr] = {
            "is_deliverable": item.get("is_deliverable", False),
            "is_catchall":    item.get("is_catchall", False),
            "is_disposable":  item.get("is_disposable", False),
            "is_role":        item.get("is_role", False),
            "status":         item.get("status", "unknown"),
            "score":          item.get("score"),
            "reason":         item.get("reason", ""),
        }
    return results


def load_existing(out_path):
    """Load already-verified contacts from existing output files."""
    valid, risky, removed = [], [], []
    catchall_path = out_path.replace(".json", "") + ".catchall.json"
    removed_path  = out_path.replace(".json", "") + ".removed.json"

    for path, bucket in [(out_path, valid), (catchall_path, risky), (removed_path, removed)]:
        try:
            with open(path) as f:
                for c in json.load(f):
                    if c.get("_bv_status") != "error":
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
    """Verify all contacts using bulk endpoint. Appends to valid/risky/removed in place."""
    total = len(contacts)
    processed = 0

    for chunk_start in range(0, total, BATCH_SIZE):
        chunk = contacts[chunk_start:chunk_start + BATCH_SIZE]
        emails = [c["email"] for c in chunk if c.get("email")]

        if not emails:
            removed.extend({**c, "_bv_status": "no_email"} for c in chunk)
            processed += len(chunk)
            continue

        try:
            results = verify_batch_api(emails)

            for contact in chunk:
                email = contact.get("email", "")
                if not email:
                    removed.append({**contact, "_bv_status": "no_email"})
                    continue

                res = results.get(email, {})
                is_deliverable = res.get("is_deliverable", False)
                is_catchall    = res.get("is_catchall", False)
                bv_status      = res.get("status", "unknown")

                contact_out = {
                    **contact,
                    "_bv_status":      bv_status,
                    "_bv_deliverable": is_deliverable,
                    "_bv_catchall":    is_catchall,
                    "_bv_score":       res.get("score"),
                    "_bv_reason":      res.get("reason", ""),
                }

                if is_deliverable and not is_catchall:
                    valid.append(contact_out)
                elif is_catchall:
                    risky.append(contact_out)
                else:
                    removed.append(contact_out)

            processed += len(chunk)
            print(f"  [{processed}/{total}] valid={len(valid)} catchall={len(risky)} removed={len(removed)}")
            time.sleep(0.3)

        except Exception as e:
            print(f"  Batch error on chunk {chunk_start}-{chunk_start+len(chunk)}: {e} — skipping (will retry next run)")
            time.sleep(3)


def main():
    parser = argparse.ArgumentParser(description="Verify emails via BillionVerify (bulk mode)")
    parser.add_argument("--file",             help="Input JSON file (list of contact dicts with 'email' field)")
    parser.add_argument("--out",              help="Output path for valid contacts")
    parser.add_argument("--include-catchall", action="store_true",
                        help="Include catch_all domains in valid output")
    parser.add_argument("--no-resume",        action="store_true",
                        help="Ignore existing output and re-verify everything")
    parser.add_argument("--credits",          action="store_true", help="Check remaining credits and exit")
    args = parser.parse_args()

    if not BV_KEY:
        print("BillionVerify_API_KEY not set in .env")
        sys.exit(1)

    if args.credits:
        credits = get_credits()
        print(f"BillionVerify credits remaining: {credits:,}")
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
        n = len(to_verify)
        batches = -(-n // BATCH_SIZE)
        print(f"Credits remaining: {credits:,}")
        print(f"Verifying {n} contacts in batches of {BATCH_SIZE} (~{batches} requests)\n")
        if credits < n:
            print(f"WARNING: Only {credits:,} credits but {n} emails to verify — top up at billionverify.com\n")

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

    catchall_path = args.out.replace(".json", "") + ".catchall.json"
    removed_path  = args.out.replace(".json", "") + ".removed.json"
    print(f"\nValid list:   {args.out}")
    print(f"Catch-all:    {catchall_path}")
    print(f"Removed:      {removed_path}")

    if total:
        print("\nStatus breakdown:")
        for s, n in Counter(c.get("_bv_status") for c in valid + risky + removed).most_common():
            print(f"  {s}: {n}")


if __name__ == "__main__":
    main()
