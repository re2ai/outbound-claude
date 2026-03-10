#!/usr/bin/env python3
"""
Generate Email1/Subject1/Email2/Email3 custom fields for verified contacts.

Two modes depending on segment:

WEB-ENRICH MODE (it_msp, catering, cleaning, signage):
  Requires web_enrich.py to have run first. Uses structured fields
  (service, smb_type, smb_guess) to fill a fixed template. No GPT needed.

DECISION-TREE MODE (insurance):
  GPT writes ONE opening question via decision tree prompt.
  Python assembles rest of Email1 from fixed template.

Both modes: Email2 and Email3 are pure Python mail-merge. No LLM.

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
import urllib.parse
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv()

OPENAI_KEY = os.getenv("OPENAI_API_KEY")
UTM = "claude-v1"
TRIAL_URL = "https://landing.re2.ai/resquared-trial-redirect?utm_source=email&utm_medium=link&utm_campaign={utm}&email={email}"
MAX_WORKERS = 8

# ── Segment config ─────────────────────────────────────────────────────────────

SEGMENTS = {

    # ── Web-enrich mode segments ───────────────────────────────────────────────
    # These use service/smb_type/smb_guess fields from web_enrich.py.
    # No GPT call needed per contact.

    "it_msp": {
        "mode": "web_enrich",
        "segment_label": "managed IT",
        "default_service": "managed IT support",
        "default_smb_type": "offices",
        "default_smb_guess": "professional offices",
        "subject_template": "managed IT x local {smb_type}",
    },
    "catering": {
        "mode": "web_enrich",
        "segment_label": "corporate catering",
        "default_service": "corporate catering",
        "default_smb_type": "tech companies",
        "default_smb_guess": "tech companies",
        "subject_template": "catering x local {smb_type}",
    },
    "cleaning": {
        "mode": "web_enrich",
        "segment_label": "commercial cleaning",
        "default_service": "commercial cleaning",
        "default_smb_type": "restaurants",
        "default_smb_guess": "restaurants",
        "subject_template": "cleaning x local {smb_type}",
    },
    "signage": {
        "mode": "web_enrich",
        "segment_label": "signage",
        "default_service": "signage",
        "default_smb_type": "new businesses",
        "default_smb_guess": "new business openings",
        "subject_template": "signage x local {smb_type}",
    },

    "merchant": {
        "mode": "web_enrich",
        "segment_label": "merchant services",
        "default_service": "merchant services",
        "default_smb_type": "restaurants",
        "default_smb_guess": "restaurants",
        "subject_template": "merchant services x local {smb_type}",
    },

    # ── Decision-tree mode segments ────────────────────────────────────────────
    # GPT writes ONE opening question. Python assembles rest.

    "insurance": {
        "mode": "decision_tree",
        "segment_label": "commercial insurance",
        "subject_template": "commercial insurance x local {vertical}",
        "default_vertical": "restaurants",
        "pitch_line": "We have about 1,000 local businesses in {city} that could be a match.",
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

    Hi {{firstName}},

    What types of [smb_type] do you do [service] for? Mainly [smb_guess]?

    We have about 1,000 [smb_type] in [city] that could be a match. We built an app
    that uses AI to find [segment_label] companies leads and use AI to email them.

    Do you want me to set up a free account for [company] and send you the login to test?
    """
    first_name = (contact.get("first_name") or "").strip()
    service  = (contact.get("service")   or cfg["default_service"]).strip()
    smb_type = (contact.get("smb_type")  or cfg["default_smb_type"]).strip()
    smb_guess = (contact.get("smb_guess") or cfg["default_smb_guess"]).strip()
    city     = (contact.get("city")      or "your area").strip()
    company  = (contact.get("company")   or "your company").strip()
    label    = cfg["segment_label"]

    opening = f"Do you do {service} for {smb_type} mainly, or more general SMB?"
    greeting = f"Hi {first_name}," if first_name else "Hi,"

    return (
        f"{greeting}<br><br>"
        f"{opening}<br><br>"
        f"We have about 1,000 {smb_type} in {city} that could be a match. "
        f"We built an app that uses AI to find {label} companies leads and use AI to email them.<br><br>"
        f"Do you want me to set up a free account for {company} and send you the login to test?"
    )


def build_email1_decision_tree(contact, cfg, opening_question):
    """
    Decision-tree mode Email1.

    {{firstName}},

    [opening_question]

    [pitch_line]

    Free accounts this month.

    Should I send you one?
    """
    first_name = (contact.get("first_name") or "").strip()
    city  = (contact.get("city") or "your area").strip()
    pitch = cfg["pitch_line"].format(city=city)
    greeting = first_name if first_name else "Hi"

    return (
        f"{greeting},<br><br>"
        f"{opening_question}<br><br>"
        f"{pitch}<br><br>"
        f"Free accounts this month.<br><br>"
        f"Should I send you one?"
    )


def build_subject(contact, cfg):
    if cfg["mode"] == "web_enrich":
        smb_type = (contact.get("smb_type") or cfg["default_smb_type"]).strip()
        return cfg["subject_template"].format(smb_type=smb_type)
    else:
        return cfg["subject_template"].format(vertical=cfg.get("default_vertical", "restaurants"))


def build_email2(contact):
    city  = (contact.get("city") or "your area").strip()
    email = urllib.parse.quote(contact.get("email", ""), safe="")
    url   = TRIAL_URL.format(utm=UTM, email=email)
    return (
        f"I ran a quick search in {city} myself this morning.<br>"
        f"I made a target list of 200 businesses and their contact email that I think would be "
        f"interested in your services before the end of Q1.<br><br>"
        f"You can access all the local business data for {city}.<br><br>"
        f'<a href="{url}">Access {city} Lead Data</a><br><br>'
        f"This is for a free account to try it yourself. Would love your feedback."
    )


def build_email3(contact):
    city  = (contact.get("city") or "your area").strip()
    email = urllib.parse.quote(contact.get("email", ""), safe="")
    url   = TRIAL_URL.format(utm=UTM, email=email)
    return (
        f"Since I'm guessing you're busy, I'll just leave this here so you can check the data "
        f"whenever you have a moment.<br><br>"
        f"You can access all the local business data for {city}.<br><br>"
        f'<a href="{url}">Access {city} Lead Data</a>'
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
