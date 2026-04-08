#!/usr/bin/env python3
"""
Analyze copy performance across ALL Smartlead campaigns ever.

Counting methodology — matches the BQ pipeline (build_all_smartlead_emails.py):
  - "Sent" = stats rows where sent_time IS NOT NULL AND sequence_number <= last_sent_seq
  - "Positive reply" = per unique (campaign, lead_email):
      lead_category IN positive set  OR  lead_is_interested = True  (from leads-export CSV)
    A lead is counted as positive AT MOST ONCE per campaign, on the email row that has
    reply_time IS NOT NULL. If multiple rows have reply_time, we take sequence_number = 1
    as the representative email (the one that started the conversation).
  - lead_category is the same for every stat row belonging to a lead, so we must
    deduplicate at the lead level before counting positives.

Outputs:
  1. Campaign-level copy performance
  2. Subject line performance (exact + normalized pattern)
  3. Sequence step breakdown
  4. ICP breakdown
  5. Sample positive-reply emails

Usage:
  python analyze_copy_performance.py              # full analysis, print report
  python analyze_copy_performance.py --dump       # also save raw data to copy_data.json
"""

import os
import sys
import csv
import io
import json
import re
import time
import requests
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("SMARTLEAD_API_KEY")
BASE_URL = "https://server.smartlead.ai/api/v1"

POSITIVE_CATEGORIES = {"Interested", "Meeting Request", "Meeting Booked", "Information Request"}
MIN_SENDS_FOR_RATE = 20


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def api_get(endpoint, params=None, accept_csv=False):
    if params is None:
        params = {}
    params["api_key"] = API_KEY
    url = f"{BASE_URL}/{endpoint}"
    headers = {"Accept": "text/csv"} if accept_csv else {}
    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, timeout=120, headers=headers or None)
            if resp.status_code == 429:
                time.sleep(2 + attempt * 2)
                continue
            resp.raise_for_status()
            return resp.text if accept_csv else resp.json()
        except requests.exceptions.RequestException:
            if attempt == 2:
                raise
            time.sleep(1)


def get_all_campaigns():
    return api_get("campaigns/")


def get_leads_export(campaign_id):
    """Fetch leads-export CSV → dict keyed by lowercase email.
    Returns {email: {lead_is_interested, last_email_sequence_number_to_lead}}.
    """
    try:
        text = api_get(f"campaigns/{campaign_id}/leads-export", accept_csv=True)
        time.sleep(0.25)
        reader = csv.DictReader(io.StringIO(text))
        out = {}
        for r in reader:
            rk = {k.strip().lower().replace(" ", "_"): v for k, v in r.items()}
            email = (rk.get("email") or "").strip().lower()
            if not email:
                continue
            is_val = (rk.get("is_interested") or "").strip().lower()
            last_sent = rk.get("last_email_sequence_sent") or "0"
            try:
                last_seq = int(last_sent or 0)
            except (TypeError, ValueError):
                last_seq = 0
            out[email] = {
                "lead_is_interested": is_val in ("true", "1", "yes"),
                "last_email_sequence_number_to_lead": last_seq,
            }
        return out
    except Exception as e:
        return {}


def get_all_stats_for_campaign(campaign_id):
    """Pull ALL per-email statistics for a campaign (paginated)."""
    all_data = []
    offset = 0
    while True:
        result = api_get(f"campaigns/{campaign_id}/statistics", {"offset": offset, "limit": 500})
        time.sleep(0.25)
        data = result.get("data", []) if isinstance(result, dict) else (result or [])
        if not data:
            break
        all_data.extend(data)
        if len(data) < 500:
            break
        offset += len(data)
        if offset > 200_000:
            break
    return all_data


# ---------------------------------------------------------------------------
# Text cleanup
# ---------------------------------------------------------------------------

def clean_body(html_body):
    if not html_body:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", html_body, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_subject(subject):
    """Remove highly-personalized tokens to group similar subjects."""
    if not subject:
        return "(empty - threaded reply)"
    s = subject.strip().lower()
    s = re.sub(r"\b\d[\d\-]*\s+[a-z][a-z\s]+(?:st|ave|blvd|rd|dr|ln|ct|way|pl)\b", "[ADDRESS]", s)
    s = re.sub(r"\bin [a-z][a-z\s]+\b", "in [CITY]", s)
    s = re.sub(r"\bfor [a-z][a-z\s]{2,20}\b", "for [COMPANY]", s)
    return s


# ---------------------------------------------------------------------------
# Data collection  (matches BQ pipeline logic)
# ---------------------------------------------------------------------------

def collect_all_data(campaigns, verbose=True):
    """
    For each campaign:
      1. Fetch leads-export CSV → get lead_is_interested + last_sent_seq per lead
      2. Fetch all statistics rows
      3. Apply sent filters (sent_time not null, seq <= last_sent_seq)
      4. Determine positive at LEAD level (deduplicated):
           positive = lead_category in POSITIVE_CATEGORIES OR lead_is_interested
         Mark positive on the row with reply_time; for copy attribution use the
         FIRST replied row (seq=1 if available, else min seq).
      5. Emit one record per sent email row with is_positive flag.

    Returns list of record dicts.
    """
    records = []

    for i, camp in enumerate(campaigns):
        if camp["status"] not in ("ACTIVE", "PAUSED", "COMPLETED", "STOPPED"):
            continue

        if verbose:
            print(f"  [{i+1}/{len(campaigns)}] {camp['name'][:55]} ...", end=" ", flush=True)

        cid = camp["id"]
        cname = camp["name"]
        parts = [p.strip() for p in cname.split("-")]
        strategy = parts[0].upper() if parts else "?"
        icp = parts[1].strip() if len(parts) > 1 else "?"

        # Step 1: leads export
        lead_info = get_leads_export(cid)

        # Step 2: statistics
        try:
            stats = get_all_stats_for_campaign(cid)
        except Exception as e:
            if verbose:
                print(f"ERROR: {e}")
            continue

        # Step 3 & 4: filter to sent rows; build lead-level positive map
        # positive_leads: set of (campaign_id, email) pairs that are positive
        positive_leads = set()
        sent_rows = []

        for s in stats:
            seq_num = s.get("sequence_number")
            sent_time = s.get("sent_time")
            email = (s.get("lead_email") or "").strip().lower()

            # Filter unsent: must have sent_time and sequence_number
            if sent_time is None or seq_num is None:
                continue

            # Filter unsent: seq > last_sent_seq for this campaign (scheduled but not delivered)
            li = lead_info.get(email, {})
            last_seq = li.get("last_email_sequence_number_to_lead")
            if li and last_seq is not None and seq_num > last_seq:
                continue

            sent_rows.append(s)

            # Determine positivity at lead level
            cat = s.get("lead_category")
            is_interested = li.get("lead_is_interested", False)
            if cat in POSITIVE_CATEGORIES or is_interested:
                positive_leads.add(email)

        # Step 5: build records
        # For copy attribution of positive replies: we want the reply row (reply_time not null).
        # If a lead replied multiple times across emails, use the first replied row.
        # We'll mark is_positive on ALL rows so campaign-level counts stay correct;
        # but for subject/body analysis we attribute the positive to the specific replied email.

        # Build replied rows by lead (for positive attribution)
        replied_rows_by_lead = defaultdict(list)
        for s in sent_rows:
            if s.get("reply_time") and (s.get("lead_email") or "").strip().lower() in positive_leads:
                replied_rows_by_lead[(s.get("lead_email") or "").strip().lower()].append(s)

        # For each positive lead, pick the best reply row (lowest seq_number)
        positive_reply_rows = {}  # email -> stat row that gets the positive credit
        for email, rows in replied_rows_by_lead.items():
            best = min(rows, key=lambda x: x.get("sequence_number") or 99)
            positive_reply_rows[email] = best

        positives_in_camp = 0
        for s in sent_rows:
            email = (s.get("lead_email") or "").strip().lower()
            seq_num = s.get("sequence_number") or 1
            subject = (s.get("email_subject") or s.get("subject") or "").strip()
            body = clean_body(s.get("email_message") or "")
            is_replied = s.get("reply_time") is not None
            is_opened = (s.get("open_count") or 0) > 0

            # A row gets is_positive=True only if it's THE row attributed to the positive reply
            is_positive = (positive_reply_rows.get(email) is s)
            if is_positive:
                positives_in_camp += 1

            records.append({
                "campaign_id": cid,
                "campaign_name": cname,
                "strategy": strategy,
                "icp": icp,
                "seq_number": seq_num,
                "subject": subject,
                "body": body,
                "opened": is_opened,
                "replied": is_replied,
                "positive": is_positive,
                "lead_email": email,
                "lead_category": s.get("lead_category"),
            })

        if verbose:
            print(f"{len(sent_rows):,} sent, {positives_in_camp} positive replies")

    return records


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------

def campaign_analysis(records):
    by_camp = defaultdict(lambda: {"sent": 0, "opened": 0, "replied": 0, "positive": 0,
                                    "name": "", "strategy": "", "icp": ""})
    for r in records:
        k = r["campaign_id"]
        d = by_camp[k]
        d["name"] = r["campaign_name"]
        d["strategy"] = r["strategy"]
        d["icp"] = r["icp"]
        d["sent"] += 1
        d["opened"] += int(r["opened"])
        d["replied"] += int(r["replied"])
        d["positive"] += int(r["positive"])

    result = []
    for cid, d in by_camp.items():
        s = d["sent"]
        result.append({**d,
            "open_rate": d["opened"] / s * 100 if s else 0,
            "reply_rate": d["replied"] / s * 100 if s else 0,
            "positive_rate": d["positive"] / s * 100 if s else 0,
        })
    return sorted(result, key=lambda x: x["positive_rate"], reverse=True)


def subject_analysis(records, min_sends=MIN_SENDS_FOR_RATE):
    by_subj = defaultdict(lambda: {"sent": 0, "opened": 0, "replied": 0, "positive": 0,
                                    "campaigns": set()})
    for r in records:
        k = r["subject"] or "(empty - threaded reply)"
        d = by_subj[k]
        d["sent"] += 1
        d["opened"] += int(r["opened"])
        d["replied"] += int(r["replied"])
        d["positive"] += int(r["positive"])
        d["campaigns"].add(r["campaign_name"])

    result = []
    for subj, d in by_subj.items():
        if d["sent"] < min_sends:
            continue
        s = d["sent"]
        result.append({"subject": subj, "sent": s,
            "opened": d["opened"], "replied": d["replied"], "positive": d["positive"],
            "open_rate": d["opened"] / s * 100, "reply_rate": d["replied"] / s * 100,
            "positive_rate": d["positive"] / s * 100,
            "campaigns": sorted(d["campaigns"]),
        })
    return sorted(result, key=lambda x: x["positive_rate"], reverse=True)


def normalized_subject_analysis(records, min_sends=MIN_SENDS_FOR_RATE):
    by_pat = defaultdict(lambda: {"sent": 0, "opened": 0, "replied": 0, "positive": 0,
                                   "examples": []})
    for r in records:
        pat = normalize_subject(r["subject"])
        d = by_pat[pat]
        d["sent"] += 1
        d["opened"] += int(r["opened"])
        d["replied"] += int(r["replied"])
        d["positive"] += int(r["positive"])
        if len(d["examples"]) < 3 and r["subject"] not in d["examples"]:
            d["examples"].append(r["subject"])

    result = []
    for pat, d in by_pat.items():
        if d["sent"] < min_sends:
            continue
        s = d["sent"]
        result.append({"pattern": pat, "sent": s,
            "opened": d["opened"], "replied": d["replied"], "positive": d["positive"],
            "open_rate": d["opened"] / s * 100, "reply_rate": d["replied"] / s * 100,
            "positive_rate": d["positive"] / s * 100, "examples": d["examples"],
        })
    return sorted(result, key=lambda x: x["positive_rate"], reverse=True)


def sequence_step_analysis(records):
    by_step = defaultdict(lambda: {"sent": 0, "opened": 0, "replied": 0, "positive": 0})
    for r in records:
        d = by_step[r["seq_number"]]
        d["sent"] += 1
        d["opened"] += int(r["opened"])
        d["replied"] += int(r["replied"])
        d["positive"] += int(r["positive"])

    result = []
    for step in sorted(by_step):
        d = by_step[step]
        s = d["sent"]
        result.append({"step": step, **d,
            "open_rate": d["opened"] / s * 100 if s else 0,
            "reply_rate": d["replied"] / s * 100 if s else 0,
            "positive_rate": d["positive"] / s * 100 if s else 0,
        })
    return result


def icp_analysis(records, min_sends=MIN_SENDS_FOR_RATE):
    by_icp = defaultdict(lambda: {"sent": 0, "opened": 0, "replied": 0, "positive": 0,
                                   "campaigns": set()})
    for r in records:
        d = by_icp[r["icp"]]
        d["sent"] += 1
        d["opened"] += int(r["opened"])
        d["replied"] += int(r["replied"])
        d["positive"] += int(r["positive"])
        d["campaigns"].add(r["campaign_name"])

    result = []
    for icp, d in by_icp.items():
        if d["sent"] < min_sends:
            continue
        s = d["sent"]
        result.append({"icp": icp, "campaigns": len(d["campaigns"]), "sent": s,
            "opened": d["opened"], "replied": d["replied"], "positive": d["positive"],
            "open_rate": d["opened"] / s * 100, "reply_rate": d["replied"] / s * 100,
            "positive_rate": d["positive"] / s * 100,
        })
    return sorted(result, key=lambda x: x["positive_rate"], reverse=True)


def lead_category_breakdown(records):
    """Show all lead_category values and their counts (for diagnostics)."""
    from collections import Counter
    cats = Counter(r["lead_category"] for r in records)
    return cats.most_common()


def top_positive_emails(records, top_n=20):
    positives = [r for r in records if r["positive"]]
    seen = set()
    unique = []
    for r in positives:
        key = (r["campaign_name"], r["subject"], r["body"][:200])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique[:top_n]


# ---------------------------------------------------------------------------
# Report printing
# ---------------------------------------------------------------------------

def pct(n, d):
    return f"{n/d*100:.2f}%" if d > 0 else "-"


def print_section(title):
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_report(records):
    total = len(records)
    total_positive = sum(1 for r in records if r["positive"])
    total_replied = sum(1 for r in records if r["replied"])
    total_opened = sum(1 for r in records if r["opened"])

    print_section("OVERALL SUMMARY")
    print(f"  Total emails (sent, filtered):  {total:,}")
    print(f"  Opened:                         {total_opened:,}  ({pct(total_opened, total)})")
    print(f"  Replied:                        {total_replied:,}  ({pct(total_replied, total)})")
    print(f"  Positive replies (unique leads):{total_positive:,}  ({pct(total_positive, total)})")

    # Lead category breakdown (diagnostics)
    print_section("LEAD CATEGORY VALUES (all categories in the data)")
    cats = lead_category_breakdown(records)
    for cat, count in cats:
        replied_with_cat = sum(1 for r in records if r["lead_category"] == cat and r["replied"])
        print(f"  {str(cat):<35} {count:>8,} rows  |  {replied_with_cat:>6,} with reply_time")

    print_section("CAMPAIGN PERFORMANCE (ranked by positive reply rate)")
    camps = campaign_analysis(records)
    print(f"  {'Campaign':<55} {'Sent':>7} {'Reply%':>8} {'+Replies':>9} {'Rate+':>7}")
    print("  " + "-" * 92)
    for c in camps:
        if c["sent"] < 5:
            continue
        name = c["name"][:53]
        print(f"  {name:<55} {c['sent']:>7,} {c['reply_rate']:>7.1f}% "
              f"{c['positive']:>9,} {c['positive_rate']:>6.2f}%")

    print_section("ICP PERFORMANCE (ranked by positive reply rate, min 20 sends)")
    icps = icp_analysis(records)
    print(f"  {'ICP':<30} {'Camps':>5} {'Sent':>8} {'Reply%':>8} {'+Reply%':>9}")
    print("  " + "-" * 65)
    for row in icps:
        print(f"  {row['icp']:<30} {row['campaigns']:>5} {row['sent']:>8,} "
              f"{row['reply_rate']:>7.1f}% {row['positive_rate']:>8.2f}%")

    print_section("SEQUENCE STEP BREAKDOWN")
    steps = sequence_step_analysis(records)
    print(f"  {'Step':<8} {'Sent':>8} {'Reply%':>8} {'+Reply%':>9} {'+Replies':>10}")
    print("  " + "-" * 48)
    for row in steps:
        label = f"Email {row['step']}"
        print(f"  {label:<8} {row['sent']:>8,} {row['reply_rate']:>7.1f}% "
              f"{row['positive_rate']:>8.2f}% {row['positive']:>10,}")

    print_section("SUBJECT LINE PERFORMANCE (exact, min 20 sends, ranked by + rate)")
    subjects = subject_analysis(records)
    print(f"  {'Subject':<55} {'Sent':>7} {'Reply%':>7} {'+Rate':>6} {'+ #':>5}")
    print("  " + "-" * 84)
    for row in subjects[:40]:
        subj = row["subject"][:53]
        print(f"  {subj:<55} {row['sent']:>7,} {row['reply_rate']:>6.1f}% "
              f"{row['positive_rate']:>5.2f}% {row['positive']:>5}")

    print_section("SUBJECT PATTERN ANALYSIS (normalized, min 20 sends)")
    patterns = normalized_subject_analysis(records)
    print(f"  {'Pattern':<55} {'Sent':>7} {'Reply%':>7} {'+Rate':>6}")
    print("  " + "-" * 78)
    for row in patterns[:30]:
        pat = row["pattern"][:53]
        print(f"  {pat:<55} {row['sent']:>7,} {row['reply_rate']:>6.1f}% "
              f"{row['positive_rate']:>5.2f}%")
        if row["examples"]:
            print(f"    e.g.: {row['examples'][0]}")

    print_section("SAMPLE POSITIVE-REPLY EMAILS (unique copy snippets)")
    top_pos = top_positive_emails(records, top_n=25)
    for i, r in enumerate(top_pos, 1):
        print(f"\n  [{i}] Campaign: {r['campaign_name']}")
        print(f"      Subject:  {r['subject'] or '(empty - threaded)'}")
        print(f"      Step:     Email {r['seq_number']}")
        body_preview = r["body"].replace("\n", " / ")[:350]
        print(f"      Body:     {body_preview}")

    print_section("KEY INSIGHTS")
    best_icp = icps[0] if icps else None
    best_camp = camps[0] if camps else None
    best_subj = subjects[0] if subjects else None
    best_step = max(steps, key=lambda x: x["positive_rate"]) if steps else None

    if best_icp:
        print(f"  * Best ICP by +rate:      '{best_icp['icp']}' "
              f"({best_icp['positive_rate']:.2f}%, {best_icp['sent']:,} sent)")
    if best_camp:
        print(f"  * Best campaign by +rate: '{best_camp['name'][:60]}' "
              f"({best_camp['positive_rate']:.2f}%, {best_camp['sent']:,} sent)")
    if best_subj:
        print(f"  * Best subject by +rate:  '{best_subj['subject'][:60]}' "
              f"({best_subj['positive_rate']:.2f}% - {best_subj['positive']}/{best_subj['sent']})")
    if best_step:
        print(f"  * Best sequence step:     Email {best_step['step']} "
              f"({best_step['positive_rate']:.2f}% +rate, {best_step['sent']:,} sent)")

    plg = [r for r in records if "PLG" in r["strategy"].upper() or "PLG" in r["campaign_name"].upper()]
    cre_bb = [r for r in records if r not in plg]
    if plg:
        plg_pos = sum(1 for r in plg if r["positive"])
        print(f"  * PLG +rate:              {pct(plg_pos, len(plg))} ({plg_pos}/{len(plg):,} sent)")
    if cre_bb:
        cre_pos = sum(1 for r in cre_bb if r["positive"])
        print(f"  * CRE/BB +rate:           {pct(cre_pos, len(cre_bb))} ({cre_pos}/{len(cre_bb):,} sent)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    dump_json = "--dump" in sys.argv

    print("Fetching all campaigns...")
    campaigns = get_all_campaigns()
    active = [c for c in campaigns if c["status"] in ("ACTIVE", "PAUSED", "COMPLETED", "STOPPED")]
    print(f"Found {len(campaigns)} campaigns total, {len(active)} with data worth pulling.\n")

    print("Pulling leads-export + statistics for all campaigns (all time)...")
    print("(This includes sent-time filtering and lead-level deduplication - matches BQ pipeline)\n")
    records = collect_all_data(campaigns, verbose=True)

    total_sent = len(records)
    total_positive = sum(1 for r in records if r["positive"])
    total_replied = sum(1 for r in records if r["replied"])
    print(f"\nTotal sent (filtered): {total_sent:,}")
    print(f"Total replied:         {total_replied:,}")
    print(f"Total positive:        {total_positive:,}")

    if dump_json:
        out_path = "copy_data.json"
        with open(out_path, "w") as f:
            # Remove body from dump to keep size manageable, or include it
            json.dump(records, f, indent=2)
        print(f"Raw data saved to {out_path}")

    print_report(records)


if __name__ == "__main__":
    main()
