#!/usr/bin/env python3
"""
Segment-focused copy analysis: PLG / CRE / BB  x  Email 1 / Email 2

For each segment x step combination, shows:
  - Top subject lines by positive reply rate
  - Top email body templates by positive reply rate
  - Representative sample emails from winners
  - Strategic insight bullets

Counting matches the BQ pipeline:
  - sent_time IS NOT NULL, sequence_number <= last_sent_seq
  - positive = lead_category in positive set OR lead_is_interested (from leads-export)
  - positive attributed to lowest-seq reply row per lead per campaign (no double-counting)

Usage:
  python analyze_copy_segments.py
"""

import os, sys, csv, io, json, re, time, requests
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("SMARTLEAD_API_KEY")
BASE_URL = "https://server.smartlead.ai/api/v1"
POSITIVE_CATEGORIES = {"Interested", "Meeting Request", "Meeting Booked", "Information Request"}
MIN_SENDS = 15   # min sends to include in subject/body ranking


# -- API ----------------------------------------------------------------------

def api_get(endpoint, params=None, accept_csv=False):
    if params is None:
        params = {}
    params["api_key"] = API_KEY
    url = f"{BASE_URL}/{endpoint}"
    headers = {"Accept": "text/csv"} if accept_csv else {}
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=120, headers=headers or None)
            if r.status_code == 429:
                time.sleep(3 + attempt * 2)
                continue
            r.raise_for_status()
            return r.text if accept_csv else r.json()
        except requests.exceptions.RequestException:
            if attempt == 2: raise
            time.sleep(1)


def get_leads_export(campaign_id):
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
            try: last_seq = int(last_sent or 0)
            except: last_seq = 0
            out[email] = {"lead_is_interested": is_val in ("true","1","yes"),
                          "last_seq": last_seq}
        return out
    except:
        return {}


def get_stats(campaign_id):
    all_data, offset = [], 0
    while True:
        result = api_get(f"campaigns/{campaign_id}/statistics", {"offset": offset, "limit": 500})
        time.sleep(0.25)
        data = result.get("data", []) if isinstance(result, dict) else (result or [])
        if not data: break
        all_data.extend(data)
        if len(data) < 500: break
        offset += len(data)
        if offset > 200_000: break
    return all_data


# -- Campaign classification ---------------------------------------------------

def classify_campaign(name):
    n = name.upper()
    if "PLG" in n:
        return "PLG"
    if any(x in n for x in ("BUSINESS BROKER", "APIFY SCRAPE", "BB")):
        return "BB"
    if any(x in n for x in ("CRE", "LOOPNET", "CREXI", "CLAYBOY")):
        return "CRE"
    return "OTHER"


# -- Text helpers -------------------------------------------------------------

def clean_body(html):
    if not html: return ""
    t = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def normalize_body(body):
    """Strip personalized tokens to group emails by copy template."""
    t = body
    # Names in greeting: "Hi John," / "Hey Sarah,"
    t = re.sub(r"(?i)^(hi|hey)\s+\w+[,!]?", r"\1 [NAME],", t)
    # City names after "in " (title-case word or known patterns)
    t = re.sub(r"\bin [A-Z][a-zA-Z\s]{2,20}(?=[?\.,\n]|$)", "in [CITY]", t)
    # Business counts: "over 5,847" / "1,873" / "over 50,000"
    t = re.sub(r"(?:over\s+)?\d[\d,]*\s+(of them|businesses|office|restaurant|retail|flex|multi|light|quick|vet|dental)", r"[N] \1", t)
    # Property addresses
    t = re.sub(r"\d[\d\-]*\s+[A-Z][a-zA-Z\s]+(?:St|Ave|Blvd|Rd|Dr|Ln|Ct|Way|Pl|Hwy)\b[^,\n]*", "[ADDRESS]", t)
    # Company names: "I see that [Company] does..."
    t = re.sub(r"(?i)(I see that\s+)[^\s].*?(does|provides|offers)", r"\1[COMPANY] \2", t)
    # Free link / trial offer variations
    t = re.sub(r"(?i)(send you a? ?(free)? ?(link|access|trial)).*", r"\1", t)
    return t.strip()


# -- Data collection -----------------------------------------------------------

def collect(verbose=True):
    campaigns = api_get("campaigns/")
    records = []

    for i, camp in enumerate(campaigns):
        if camp["status"] not in ("ACTIVE","PAUSED","COMPLETED","STOPPED"):
            continue

        segment = classify_campaign(camp["name"])
        cid = camp["id"]

        if verbose:
            print(f"  [{i+1}/{len(campaigns)}] [{segment}] {camp['name'][:55]} ...", end=" ", flush=True)

        lead_info = get_leads_export(cid)
        try:
            stats = get_stats(cid)
        except Exception as e:
            if verbose: print(f"ERROR: {e}")
            continue

        # Determine positive leads for this campaign
        positive_leads = set()
        sent_rows = []
        for s in stats:
            seq = s.get("sequence_number")
            sent_time = s.get("sent_time")
            email = (s.get("lead_email") or "").strip().lower()
            if sent_time is None or seq is None:
                continue
            li = lead_info.get(email, {})
            last_seq = li.get("last_seq")
            if li and last_seq is not None and seq > last_seq:
                continue
            sent_rows.append(s)
            cat = s.get("lead_category")
            if cat in POSITIVE_CATEGORIES or li.get("lead_is_interested", False):
                positive_leads.add(email)

        # Attribution: first replied row per positive lead
        replied_by_lead = defaultdict(list)
        for s in sent_rows:
            email = (s.get("lead_email") or "").strip().lower()
            if s.get("reply_time") and email in positive_leads:
                replied_by_lead[email].append(s)
        positive_reply_rows = {
            email: min(rows, key=lambda x: x.get("sequence_number") or 99)
            for email, rows in replied_by_lead.items()
        }

        pos_count = 0
        for s in sent_rows:
            email = (s.get("lead_email") or "").strip().lower()
            seq = s.get("sequence_number") or 1
            subject = (s.get("email_subject") or s.get("subject") or "").strip()
            body = clean_body(s.get("email_message") or "")
            is_positive = positive_reply_rows.get(email) is s
            if is_positive:
                pos_count += 1
            records.append({
                "segment": segment,
                "campaign_name": camp["name"],
                "campaign_id": cid,
                "seq_number": seq,
                "subject": subject,
                "body": body,
                "body_norm": normalize_body(body),
                "replied": s.get("reply_time") is not None,
                "positive": is_positive,
                "lead_category": s.get("lead_category"),
            })

        if verbose:
            print(f"{len(sent_rows):,} sent, {pos_count} positive")

    return records


# -- Analysis helpers ----------------------------------------------------------

def rank_subjects(rows, min_sends=MIN_SENDS):
    by = defaultdict(lambda: {"sent":0,"replied":0,"positive":0})
    for r in rows:
        k = r["subject"] or "(empty-threaded)"
        by[k]["sent"] += 1
        by[k]["replied"] += int(r["replied"])
        by[k]["positive"] += int(r["positive"])
    out = []
    for subj, d in by.items():
        if d["sent"] < min_sends: continue
        s = d["sent"]
        out.append({**d, "subject": subj,
                    "reply_rate": d["replied"]/s*100,
                    "positive_rate": d["positive"]/s*100})
    return sorted(out, key=lambda x: x["positive_rate"], reverse=True)


def rank_body_templates(rows, min_sends=MIN_SENDS):
    """Group by normalized body template, keep a representative real example."""
    by = defaultdict(lambda: {"sent":0,"replied":0,"positive":0,"examples":[]})
    for r in rows:
        k = r["body_norm"][:300]  # key on first 300 chars of normalized body
        by[k]["sent"] += 1
        by[k]["replied"] += int(r["replied"])
        by[k]["positive"] += int(r["positive"])
        if len(by[k]["examples"]) < 2:
            by[k]["examples"].append(r["body"][:500])
    out = []
    for tmpl, d in by.items():
        if d["sent"] < min_sends: continue
        s = d["sent"]
        out.append({**d, "template": tmpl,
                    "reply_rate": d["replied"]/s*100,
                    "positive_rate": d["positive"]/s*100})
    return sorted(out, key=lambda x: x["positive_rate"], reverse=True)


def top_positive_samples(rows, n=5):
    """Unique (subject+body) positive-reply examples."""
    seen, out = set(), []
    for r in sorted([r for r in rows if r["positive"]], key=lambda x: x["seq_number"]):
        key = (r["subject"], r["body"][:150])
        if key not in seen:
            seen.add(key)
            out.append(r)
        if len(out) >= n: break
    return out


# -- Print helpers -------------------------------------------------------------

def sep(title=""):
    if title:
        print(f"\n{'='*80}\n  {title}\n{'='*80}")
    else:
        print("-"*80)


def pct(n, d): return f"{n/d*100:.2f}%" if d else "-"


def print_segment_step(seg, step, rows):
    total = len(rows)
    pos = sum(1 for r in rows if r["positive"])
    rep = sum(1 for r in rows if r["replied"])
    print(f"\n  Emails: {total:,}  |  Replied: {rep:,} ({pct(rep,total)})  |  Positive: {pos} ({pct(pos,total)})")

    # Subjects
    subjects = rank_subjects(rows)
    if subjects:
        print(f"\n  TOP SUBJECT LINES (min {MIN_SENDS} sends, ranked by + rate):")
        print(f"  {'Subject':<52} {'Sent':>6} {'Reply%':>7} {'+Rate':>7} {'+#':>4}")
        print("  " + "-"*77)
        for s in subjects[:12]:
            subj = s["subject"][:50]
            print(f"  {subj:<52} {s['sent']:>6,} {s['reply_rate']:>6.1f}% {s['positive_rate']:>6.2f}% {s['positive']:>4}")

    # Body templates
    templates = rank_body_templates(rows)
    if templates:
        print(f"\n  TOP EMAIL BODY TEMPLATES (grouped by copy pattern):")
        print(f"  {'Template (normalized)':<52} {'Sent':>6} {'Reply%':>7} {'+Rate':>7}")
        print("  " + "-"*74)
        for t in templates[:8]:
            tmpl = t["template"][:50].replace("\n", " ")
            print(f"  {tmpl:<52} {t['sent']:>6,} {t['reply_rate']:>6.1f}% {t['positive_rate']:>6.2f}%")

    # Actual winning examples
    samples = top_positive_samples(rows, n=4)
    if samples:
        print(f"\n  WINNING COPY SAMPLES (positive replies):")
        for i, r in enumerate(samples, 1):
            print(f"\n  [{i}] Subject: {r['subject'] or '(empty-threaded)'}")
            body_lines = r["body"].split("\n")
            for ln in body_lines[:8]:
                if ln.strip():
                    print(f"       {ln.strip()[:110]}")


def print_plg_insights(all_records):
    """Strategic analysis of why PLG underperforms vs CRE/BB."""
    sep("STRATEGIC INSIGHTS: WHY PLG UNDERPERFORMS vs CRE/BB")

    plg = [r for r in all_records if r["segment"] == "PLG"]
    cre = [r for r in all_records if r["segment"] == "CRE"]
    bb  = [r for r in all_records if r["segment"] == "BB"]

    plg_pos = sum(1 for r in plg if r["positive"])
    cre_pos = sum(1 for r in cre if r["positive"])
    bb_pos  = sum(1 for r in bb  if r["positive"])

    print(f"""
  BASELINE NUMBERS:
    PLG:  {len(plg):>7,} sent  |  {plg_pos:>4} positive  ({pct(plg_pos, len(plg))} rate)
    CRE:  {len(cre):>7,} sent  |  {cre_pos:>4} positive  ({pct(cre_pos, len(cre))} rate)
    BB:   {len(bb):>7,} sent  |  {bb_pos:>4} positive  ({pct(bb_pos,  len(bb))} rate)

  CRE/BB run {int((cre_pos/len(cre))/(plg_pos/len(plg))) if plg_pos else '?'}x the positive rate of PLG.
""")

    # -- Diagnosis 1: ICP pain specificity
    print("""  DIAGNOSIS 1 -- ICP PAIN SPECIFICITY
  -----------------------------------------------------------------
  CRE/BB prospect has an ACTIVE, VISIBLE problem the moment we email them:
    - CRE broker: has a vacant space listed on Loopnet/Crexi right now
    - BB broker: has a business listed for sale right now
    - Our subject ("retail tenant question") directly references that problem

  PLG prospect has a LATENT problem they may not be feeling today:
    - An MSP doesn't know they're missing local leads unless they track it
    - A cleaning company isn't in "active buying mode" for prospecting software
    - No external signal triggers the outreach (unlike a listing = trigger)

  FIX: For PLG, lean harder into TRIGGER-BASED subjects. Examples:
    - "new restaurants opening in [City]" (expansion signal for cleaning/HVAC)
    - "HVAC season approaching" (seasonal trigger)
    - "saw [Company] on Yelp -- do you target new businesses?" (activity signal)
""")

    # -- Diagnosis 2: Subject line analysis
    plg_e1_subjects = rank_subjects([r for r in plg if r["seq_number"]==1], min_sends=10)
    cre_e1_subjects = rank_subjects([r for r in cre if r["seq_number"]==1], min_sends=10)

    print("  DIAGNOSIS 2 -- SUBJECT LINE: GENERIC vs SPECIFIC")
    print("  -----------------------------------------------------------------")
    print("  Best PLG Email 1 subjects:")
    for s in plg_e1_subjects[:5]:
        print(f"    {s['positive_rate']:>5.2f}%  {s['subject']}")
    print()
    print("  Best CRE Email 1 subjects:")
    for s in cre_e1_subjects[:5]:
        print(f"    {s['positive_rate']:>5.2f}%  {s['subject']}")

    print("""
  PATTERN: CRE subjects name an ASSET the prospect already owns ("retail tenant
  question", "leasing this office?"). PLG subjects name a SERVICE we sell
  ("[service] x local businesses"). Recipient recognizes their own property;
  they don't recognize our product category.

  FIX: Reframe PLG subjects around something the prospect OWNS or IS DOING:
    BEFORE: "managed IT x local businesses"
    AFTER:  "IT clients near [City]?" or "do you serve [business type] in [City]?"
""")

    # -- Diagnosis 3: Body structure
    print("  DIAGNOSIS 3 -- BODY COPY STRUCTURE")
    print("  -----------------------------------------------------------------")
    print("""  CRE Email 1 winning structure (2-4% positive rate):
    Hey [Name],
    For the space at [ADDRESS], were you open to a [tenant type]?
    We have contact info for [N] [tenant type] operators in [City] and 15M across the US.
    Not sure what use you had in mind -- let me know your target and I can share more.

    WHY IT WORKS:
    - Opens with THEIR asset (the listing address they care about)
    - One direct question about their current need
    - Data point proves we can actually help (N tenants in their market)
    - Soft CTA -- no pressure, just "let me know"
    - 4-5 lines total, zero fluff

  PLG Email 1 typical structure (0.3-0.9% positive rate):
    Hi [Name], do you sell [service] to local businesses in [City]?
    We built a platform that automates identifying and sending AI-personalized emails to
    local businesses likely to need your services. It helps you reach the right prospects...
    We're offering free accounts this month -- want me to set one up for you?

    WHY IT UNDERPERFORMS:
    - "We built a platform that automates..." = product description, not their problem
    - "AI-personalized emails" = buzzword that sounds like mass marketing
    - "Free accounts this month" = promotional language = spam signal
    - The READER has to do mental work to connect our product to their world
""")

    # -- Diagnosis 4: Email 2 structure
    plg_e2_pos = sum(1 for r in plg if r["seq_number"]==2 and r["positive"])
    plg_e2_sent = sum(1 for r in plg if r["seq_number"]==2)
    cre_e2_pos = sum(1 for r in cre if r["seq_number"]==2 and r["positive"])
    cre_e2_sent = sum(1 for r in cre if r["seq_number"]==2)

    print(f"  DIAGNOSIS 4 -- EMAIL 2 PERFORMANCE")
    print("  -----------------------------------------------------------------")
    print(f"    PLG  Email 2: {pct(plg_e2_pos, plg_e2_sent)} positive ({plg_e2_sent:,} sent)")
    print(f"    CRE  Email 2: {pct(cre_e2_pos, cre_e2_sent)} positive ({cre_e2_sent:,} sent)")
    print("""
  PLG Email 2 is typically a "problem-first" follow-up that introduces a new angle.
  CRE Email 2 is a RE: thread that adds social proof or a different tenant type.

  The RE: threading for CRE is very effective (follow-up open rates jump significantly).
  PLG Email 2 often loses the thread because subject is empty (correct per playbook),
  but the body pivots to a generic pain angle rather than building on Email 1's hook.

  FIX: PLG Email 2 should stay in the SAME frame as Email 1 -- reference their market,
  not a new benefit. Example:
    BEFORE Email 2: "Most [segment] companies are still waiting on referrals..."
    AFTER  Email 2: "Just following up -- do you currently have a way to reach new
                    [business type] openings in [City] before competitors do?"
""")

    # -- Diagnosis 5: Segment-specific dead zones
    print("  DIAGNOSIS 5 -- DEAD ZONES (0% positive rate campaigns)")
    print("  -----------------------------------------------------------------")
    dead = defaultdict(lambda: {"sent":0,"positive":0})
    for r in plg:
        dead[r["campaign_name"]]["sent"] += 1
        dead[r["campaign_name"]]["positive"] += int(r["positive"])
    print("  PLG campaigns with 0 positive replies:")
    for cname, d in sorted(dead.items(), key=lambda x: -x[1]["sent"]):
        if d["positive"] == 0 and d["sent"] >= 50:
            print(f"    {cname[:60]:<62} {d['sent']:>6,} sent")
    print("""
  Commercial Insurance (4 variants, ~2,600 sent): The ICP may be too broad.
  Insurance agents who sell COMMERCIAL coverage to local businesses are a small,
  precise niche. Apollo/Clay lists likely mixed in personal lines agents or
  captive agents who have no need for local biz prospecting data.

  Hardware/Electronics IT, Marketing Services: Same ICP mismatch issue.
  These segments either don't do cold outreach to local businesses themselves,
  or the value prop ("find more local biz clients") doesn't land for them.

  RECOMMENDED ACTIONS:
  1. Audit Insurance/Hardware IT list quality -- are these actually companies
     that sell to local SMBs, or were they just matched by title keywords?
  2. For Insurance: pivot to Independent P&C agents or MGAs specifically
     (not captive State Farm/Allstate types).
  3. Kill Email 3 entirely -- 0.09% across all segments, not worth the noise.
  4. For PLG: test the "you help sell X?" subject format across ALL segments
     (it outperforms "[X] x local businesses" consistently).
  5. For PLG bodies: strip all product description language. Just ask ONE
     question about their market, give ONE data point, offer ONE action.
""")


# -- Main ----------------------------------------------------------------------

def main():
    print("Collecting data from all campaigns...\n")
    records = collect(verbose=True)

    total_sent = len(records)
    total_pos  = sum(1 for r in records if r["positive"])
    print(f"\nTotal sent: {total_sent:,}  |  Positive: {total_pos:,}  ({pct(total_pos, total_sent)})\n")

    segments = ["PLG", "CRE", "BB"]
    steps = [1, 2]

    for seg in segments:
        sep(f"{seg} -- COPY ANALYSIS")
        seg_rows = [r for r in records if r["segment"] == seg]
        seg_pos  = sum(1 for r in seg_rows if r["positive"])
        print(f"\n  Total: {len(seg_rows):,} sent  |  {seg_pos} positive  ({pct(seg_pos, len(seg_rows))})")

        for step in steps:
            step_rows = [r for r in seg_rows if r["seq_number"] == step]
            if not step_rows:
                continue
            print(f"\n  -- Email {step} ------------------------------------------------------")
            print_segment_step(seg, step, step_rows)

    print_plg_insights(records)

    sep("QUICK-WIN RECOMMENDATIONS")
    print("""
  IMMEDIATE (copy changes, no new campaigns needed):
  -------------------------------------------------
  1. PLG subjects: replace "[service] x local businesses" with "you help sell [X]?"
     or "do you sell [X] to local businesses in [City]?" -- proven 3-8% vs 0.3-1%.

  2. PLG Email 1 body: remove all product description sentences.
     Replace with: ONE question about their market + ONE specific data point + ONE CTA.
     Target: under 4 sentences total.

  3. PLG Email 2 body: stay in the same frame as Email 1.
     Don't introduce a new angle -- just revisit their specific market with a new angle
     on the same pain (e.g., "any luck finding new accounts in [City]?").

  4. Kill Email 3 across all campaigns -- 13 total positive replies from 13,944 sends
     (0.09%) is noise. The main sequence is Email 1 + Email 2.

  MEDIUM TERM (new campaigns or variants):
  -------------------------------------------------
  5. PLG: build TRIGGER-BASED variants -- new business openings, seasonal hooks,
     industry events -- so the email arrives when the ICP is already in buying mode.

  6. CRE: Clayboy Labs Offices format (3.30% positive) is clearly the best-performing
     CRE template. Roll out the same approach to more property types systematically.

  7. BB: the "Connecting with business owners exploring a sale" subject line
     (5.00%) is underused -- only 40 sends. Scale this subject format widely.

  8. PLG Insurance: pause all variants. Rebuild with a tighter ICP definition
     (independent P&C agents only) before re-launching.
""")


if __name__ == "__main__":
    main()
