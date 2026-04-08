#!/usr/bin/env python3
"""
Generate Email1/Subject1/Email2/Email3 custom fields for verified contacts.

UNIVERSAL RULE: ALL emails (1, 2, 3) are ALWAYS plain text with \\n line breaks.
No HTML. No links. No exceptions. Convert \\n\\n to <br><br> and \\n to <br>
ONLY at SmartLead load time.

PLG goal: get the reader to REPLY and ask for the trial link.
DO NOT send the link in any email. The link is sent only after they reply.

Two modes depending on segment:

WEB-ENRICH MODE (it_msp, catering, cleaning, signage, merchant, hvac):
  Requires web_enrich.py to have run first. Uses structured fields
  (service, smb_type, smb_count) to fill a fixed template. No GPT needed.
  Two framing variants:
    - "hyper_personal": opens with "I see {company} does {service} for {smb_type} in {city}"
      (IT/MSP, Catering -- prospect serves a known client type)
    - "recurrent": opens with "Do you do {service} for {smb_type} in {city}?"
      then frames demand as constant/ongoing -- NOT "new openings"
      (Cleaning, Signage, Merchant, HVAC -- demand never dries up)

DECISION-TREE MODE (insurance):
  GPT writes ONE opening question via decision tree prompt.
  Python assembles rest of Email1 from fixed template.

Both modes: Email2 and Email3 are pure Python mail-merge. No LLM.

smb_count field: must be the EXACT number from BQ
(business_sources.us_companies_list per city). Do NOT use friendly_count() rounding
for email copy -- the exact number reads as more credible. Fallback: omit count phrase.

Usage:
  # IT/MSP (run web_enrich.py first):
  python web_enrich.py   --file /tmp/it_msp_verified.json --segment it_msp --out /tmp/it_msp_enriched.json
  python generate_emails.py --file /tmp/it_msp_enriched.json  --segment it_msp  --out /tmp/it_msp_emails.json

  # Insurance (GPT decision tree, no web_enrich needed):
  python generate_emails.py --file /tmp/insurance_verified.json --segment insurance --out /tmp/insurance_emails.json

Uses ThreadPoolExecutor(max_workers=8). Resume-safe.
"""

import os
import sys
import json
import argparse
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv()

OPENAI_KEY = os.getenv("OPENAI_API_KEY")
MAX_WORKERS = 8

# ── Segment config ─────────────────────────────────────────────────────────────

SEGMENTS = {

    # ── Web-enrich mode segments ───────────────────────────────────────────────
    # These use service/smb_type/smb_guess fields from web_enrich.py.
    # No GPT call needed per contact.
    #
    # framing = "hyper_personal" → opener references the prospect's company
    #   ("I see {company} does {service} for {smb_type} in {city}")
    #   Best for: IT/MSP, Catering — prospects serve a specific known client type
    #
    # framing = "recurrent" → opener frames demand as constant/ongoing
    #   ("There are always {smb_count} {smb_type} in {city} that need your services")
    #   Best for: Cleaning, Signage, Merchant, HVAC — demand is always there,
    #   NOT tied to "new openings" — avoids the impression that leads dry up

    "it_msp": {
        "mode": "web_enrich",
        "framing": "hyper_personal",
        "segment_label": "managed IT",
        "default_service": "managed IT support",
        "default_smb_type": "offices",
        "default_smb_guess": "professional offices",
        "subject_template": "do you serve {smb_type} in {city}?",
    },
    "catering": {
        "mode": "web_enrich",
        "framing": "hyper_personal",
        "segment_label": "corporate catering",
        "default_service": "corporate catering",
        "default_smb_type": "tech companies",
        "default_smb_guess": "tech companies",
        "subject_template": "do you cater for {smb_type} in {city}?",
    },
    "cleaning": {
        "mode": "web_enrich",
        "framing": "recurrent",
        "segment_label": "commercial cleaning",
        "default_service": "commercial cleaning",
        "default_smb_type": "restaurants",
        "default_smb_guess": "restaurants",
        "subject_template": "do you clean {smb_type} in {city}?",
    },
    "signage": {
        "mode": "web_enrich",
        "framing": "recurrent",
        "segment_label": "signage",
        "default_service": "signage",
        "default_smb_type": "businesses",
        "default_smb_guess": "businesses",
        "subject_template": "do you do signage for businesses in {city}?",
    },
    "merchant": {
        "mode": "web_enrich",
        "framing": "recurrent",
        "segment_label": "merchant services",
        "default_service": "merchant services",
        "default_smb_type": "restaurants",
        "default_smb_guess": "restaurants",
        "subject_template": "do you serve {smb_type} in {city}?",
    },
    "hvac": {
        "mode": "web_enrich",
        "framing": "recurrent",
        "segment_label": "HVAC",
        "default_service": "HVAC",
        "default_smb_type": "commercial buildings",
        "default_smb_guess": "commercial buildings",
        "subject_template": "do you do HVAC for {smb_type} in {city}?",
    },

    # ── Decision-tree mode segments ────────────────────────────────────────────
    # GPT writes ONE opening question. Python assembles rest.

    "insurance": {
        "mode": "decision_tree",
        "segment_label": "commercial insurance",
        "subject_template": "do you write commercial insurance in {city}?",
        "system_prompt": """Write ONE opening question for a cold email to an independent commercial insurance agent.

Decision tree:
- "Commercial" in company name -> "Is commercial lines your main focus, or do you write personal lines too?"
- "Family" or "personal" in company name -> "Do you also write commercial accounts, or mainly personal lines?"
- City or industry in company name -> reference the niche: "Are you mostly working [niche] accounts in [city]?"
- Default -> "Commercial or personal lines -- where is most of your book these days?"

Rules:
- One sentence only. Max 15 words. No em dashes. No "I noticed". No compliments.
- Must be a question. Output the question only, nothing else.""",
    },
}


# ── GPT call (decision-tree mode only) ────────────────────────────────────────

def gpt_opening(contact, cfg):
    """Generate ONE opening question via GPT. Decision-tree mode only."""
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
        json={
            "model": "gpt-5-mini-2025-08-07",
            "max_completion_tokens": 2000,
            "messages": [
                {"role": "system", "content": cfg["system_prompt"]},
                {"role": "user", "content": (
                    f"Contact: {contact.get('first_name','there')}, "
                    f"{contact.get('title','')} at {contact.get('company','')} "
                    f"in {contact.get('city','their city')}."
                )},
            ],
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


# ── Email assembly ─────────────────────────────────────────────────────────────

def build_email1_web_enrich(contact, cfg):
    """
    Web-enrich mode Email1.

    IMPORTANT: Email1 is ALWAYS plain text with \\n line breaks.
    No HTML tags, no links. Convert to <br> ONLY at SmartLead load time.

    Two framing variants (set per segment via cfg["framing"]):

    HYPER_PERSONAL (it_msp, catering):
      Opens by referencing what the prospect's company does, then names the exact
      business count in their city. CTA frames this as "test for free, no card needed"
      -- connecting them asking for the link directly to free trial access.

    RECURRENT (cleaning, signage, merchant, hvac):
      Opens with a clarifying question about their service area, then frames demand
      as constant and ongoing -- NOT "new openings" or "new businesses". There are
      always {smb_count} businesses in {city} that need their services. Same CTA.

    smb_count field: use the EXACT number from BQ (business_sources.us_companies_list
    per city). Do NOT round. If smb_count is not available, omit the count line
    entirely -- do NOT substitute "thousands of businesses" or any placeholder.
    """
    first_name = (contact.get("first_name") or "").strip()
    service   = (contact.get("service")    or cfg["default_service"]).strip()
    smb_type  = (contact.get("smb_type")   or cfg["default_smb_type"]).strip()
    city      = (contact.get("city")       or "your area").strip()
    company   = (contact.get("company")    or "your company").strip()
    smb_count_raw = contact.get("smb_count")

    greeting = f"Hi {first_name}," if first_name else "Hi,"
    framing = cfg.get("framing", "hyper_personal")

    if framing == "hyper_personal":
        # IT/MSP, Catering: reference what the prospect's company does
        count_line = (
            f"There are {smb_count_raw} {smb_type} in {city} you could be reaching right now.\n\n"
            if smb_count_raw else ""
        )
        return (
            f"{greeting}\n\n"
            f"I see {company} does {service} for {smb_type} in {city}.\n\n"
            f"{count_line}"
            f"Reply and I'll send you access to test it for free -- no card needed."
        )
    else:
        # RECURRENT (cleaning, signage, merchant, hvac): demand is always there
        count_line = (
            f"There are {smb_count_raw} {smb_type} in {city} that always need services like yours.\n\n"
            if smb_count_raw else ""
        )
        return (
            f"{greeting}\n\n"
            f"Do you do {service} for {smb_type} in {city}?\n\n"
            f"{count_line}"
            f"Reply and I'll send you access to test it for free -- no card needed."
        )


def build_email1_decision_tree(contact, cfg, opening_question):
    """
    Decision-tree mode Email1.

    IMPORTANT: Email1 is ALWAYS plain text with \\n line breaks.
    No HTML tags, no links. Convert to <br> ONLY at SmartLead load time.

    {first_name},

    [opening_question — GPT-generated, one sentence, max 15 words]

    There are {smb_count} local businesses in {city} that could be a match.
    (If smb_count not available, omit the count line entirely — do not substitute a guess.)

    Reply and I'll send you access to test it for free -- no card needed.
    """
    first_name = (contact.get("first_name") or "").strip()
    city       = (contact.get("city") or "your area").strip()
    greeting   = first_name if first_name else "Hi"

    smb_count_raw = contact.get("smb_count")
    count_line = (
        f"There are {smb_count_raw} local businesses in {city} that could be a match.\n\n"
        if smb_count_raw else ""
    )

    return (
        f"{greeting},\n\n"
        f"{opening_question}\n\n"
        f"{count_line}"
        f"Reply and I'll send you access to test it for free -- no card needed."
    )


def build_subject(contact, cfg):
    smb_type = (contact.get("smb_type") or cfg.get("default_smb_type", "businesses")).strip()
    city     = (contact.get("city")     or "your area").strip()
    if cfg["mode"] == "web_enrich":
        return cfg["subject_template"].format(smb_type=smb_type, city=city)
    else:
        return cfg["subject_template"].format(city=city)


def build_email2(contact):
    """
    PLG Email 2 -- plain text, no links, no HTML.
    Goal: surface the city data, reinforce free trial, get a reply.
    NEVER send the trial link directly -- only on reply.
    """
    city      = (contact.get("city")     or "your area").strip()
    smb_type  = (contact.get("smb_type") or "businesses").strip()
    smb_count_raw = contact.get("smb_count")
    smb_count = str(smb_count_raw).strip() if smb_count_raw else "businesses"
    count_phrase = f"{smb_count} {smb_type}" if smb_count_raw else smb_type

    return (
        f"I ran a quick search in {city} this morning.\n\n"
        f"There are {count_phrase} in {city} that look like they could use your services.\n\n"
        f"Just reply and I'll send you access to test it for free -- no card needed."
    )


def build_email3(contact):
    """
    PLG Email 3 -- plain text, no links, no HTML.
    Brief last touch. Gets its own Subject3 (new angle) so it starts a fresh thread.
    """
    city = (contact.get("city") or "your area").strip()

    return (
        f"Leaving this here in case the timing wasn't right.\n\n"
        f"All the local business data for {city} is ready whenever you want to test it.\n\n"
        f"Just reply and I'll send over the access."
    )


# ── Worker ─────────────────────────────────────────────────────────────────────

def process_contact(contact, cfg):
    if cfg["mode"] == "web_enrich":
        email1 = build_email1_web_enrich(contact, cfg)
    else:
        opening = gpt_opening(contact, cfg)
        email1  = build_email1_decision_tree(contact, cfg, opening)

    return {
        **contact,
        "Subject1": build_subject(contact, cfg),
        "Email1":   email1,
        "Email2":   build_email2(contact),
        "Email3":   build_email3(contact),
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file",    required=True)
    parser.add_argument("--segment", required=True, choices=list(SEGMENTS.keys()))
    parser.add_argument("--out",     required=True)
    args = parser.parse_args()

    if not OPENAI_KEY:
        print("OPENAI_API_KEY not set"); sys.exit(1)

    cfg = SEGMENTS[args.segment]

    with open(args.file) as f:
        contacts = json.load(f)

    # Resume: skip already-generated
    already_done = {}
    if os.path.exists(args.out):
        with open(args.out) as f:
            existing = json.load(f)
        already_done = {c["email"]: c for c in existing if c.get("email") and "Email1" in c}
        print(f"Resuming: {len(already_done)} already generated.")

    to_process = [c for c in contacts if c.get("email") and c["email"] not in already_done]
    total = len(to_process)
    mode_note = "web_enrich (no GPT)" if cfg["mode"] == "web_enrich" else "decision_tree (GPT)"
    print(f"Generating {total} contacts (segment={args.segment}, mode={mode_note}, workers={MAX_WORKERS})...")

    output = list(already_done.values())
    errors = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(process_contact, c, cfg): c for c in to_process}
        completed = 0
        for future in as_completed(futures):
            contact = futures[future]
            completed += 1
            try:
                output.append(future.result())
            except Exception as e:
                errors += 1
                print(f"  ERROR {contact.get('email')}: {e}")

            if completed % 50 == 0 or completed == total:
                with open(args.out, "w") as f:
                    json.dump(output, f, indent=2)
                print(f"  [{completed}/{total}] done={len(output)} errors={errors}")

    with open(args.out, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nDone: {len(output)} generated ({errors} errors) -> {args.out}")

    if output:
        s = output[0]
        print(f"\nSample: {s.get('first_name')} at {s.get('company')} ({s.get('city')})")
        print(f"  Subject: {s.get('Subject1')}")
        print(f"  Email1 preview:\n{s.get('Email1','')[:400]}")


if __name__ == "__main__":
    main()
