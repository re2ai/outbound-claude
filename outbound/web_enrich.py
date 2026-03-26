#!/usr/bin/env python3
"""
Web enrichment pre-processing step before generate_emails.py.

For each contact, uses OpenAI Responses API (o4-mini + web_search) to find:
  - service: the specific service they offer most relevant to local SMB cold prospecting
  - smb_type: the local business type they sell to, in casual language (plural)
  - smb_guess: a specific guess for the follow-up question ("Mainly restaurants?")

These three fields get filled into the Email1 template in generate_emails.py.
Falls back to segment defaults if nothing specific is found.

Usage:
  python web_enrich.py --file /tmp/it_msp_verified.json --segment it_msp --out /tmp/it_msp_enriched.json

Resume-safe. Uses ThreadPoolExecutor(max_workers=5).
"""

import os
import sys
import re
import json
import argparse
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv()

OPENAI_KEY = os.getenv("OPENAI_API_KEY")
MODEL = "gpt-5.4"
MAX_WORKERS = 5

SEGMENT_CONFIG = {
    "it_msp": {
        "prompt": """Search for "{company}" in {city}. They are a managed IT / MSP company.

Find two things:
1. Their most specific service that local small businesses would hire them for. Examples: "point of sale setup", "network security", "managed IT support", "cybersecurity compliance", "structured cabling", "cloud migration". Pick the most specific one you find, not just "managed IT".
2. What types of local businesses they serve or target. Examples: "restaurants", "auto dealers", "dental offices", "retailers", "medical offices". Use casual plural nouns, not corporate language.

If you find both, output exactly this format (two lines, nothing else):
service: [specific service]
smb_type: [local business type, plural]

If you cannot find specific information, output exactly:
NONE""",
        "default_service": "managed IT support",
        "default_smb_type": "local businesses",
        "default_smb_guess": "restaurants",
        "segment_label": "managed IT",
    },
    "insurance": {
        "prompt": """Search for "{company}" in {city}. They are an independent insurance agency.

Find two things:
1. Their most specific product or specialty relevant to local small businesses. Examples: "general liability coverage", "business owners policies", "workers comp", "restaurant insurance", "contractor insurance". Pick the most specific one.
2. What types of local businesses they insure. Examples: "restaurants", "contractors", "retailers", "auto shops", "new business owners". Use casual plural nouns.

If you find both, output exactly this format (two lines, nothing else):
service: [specific product or specialty]
smb_type: [local business type, plural]

If you cannot find specific information, output exactly:
NONE""",
        "default_service": "commercial insurance",
        "default_smb_type": "local businesses",
        "default_smb_guess": "restaurants",
        "segment_label": "commercial insurance",
    },
    "catering": {
        "prompt": """Search for "{company}" in {city}. They are a corporate catering company.

Find two things:
1. Their most specific service. Examples: "box lunch delivery", "office catering", "executive dining", "corporate event catering". Pick the most specific one.
2. What types of corporate clients or offices they serve. Examples: "tech offices", "law firms", "hospitals", "corporate campuses". Use casual plural nouns.

If you find both, output exactly this format (two lines, nothing else):
service: [specific service]
smb_type: [client type, plural]

If you cannot find specific information, output exactly:
NONE""",
        "default_service": "corporate catering",
        "default_smb_type": "local offices",
        "default_smb_guess": "tech companies",
        "segment_label": "corporate catering",
    },
    "cleaning": {
        "prompt": """Search for "{company}" in {city}. They are a commercial cleaning company.

Find two things:
1. Their most specific service. Examples: "janitorial contracts", "restaurant kitchen cleaning", "medical office cleaning", "floor care", "post-construction cleaning".
2. What types of local businesses they clean. Examples: "restaurants", "medical offices", "retail stores", "office buildings". Use casual plural nouns.

If you find both, output exactly this format (two lines, nothing else):
service: [specific service]
smb_type: [local business type, plural]

If you cannot find specific information, output exactly:
NONE""",
        "default_service": "commercial cleaning",
        "default_smb_type": "local businesses",
        "default_smb_guess": "restaurants",
        "segment_label": "cleaning contracts",
    },
    "signage": {
        "prompt": """Search for "{company}" in {city}. They are a signage company.

Find two things:
1. Their most specific product or service. Examples: "storefront signs", "vehicle wraps", "LED signs", "exterior branding", "channel letters".
2. What types of local businesses they work with. Examples: "restaurants", "retailers", "new business openings", "auto dealers". Use casual plural nouns.

If you find both, output exactly this format (two lines, nothing else):
service: [specific product or service]
smb_type: [local business type, plural]

If you cannot find specific information, output exactly:
NONE""",
        "default_service": "signage",
        "default_smb_type": "local businesses",
        "default_smb_guess": "new business openings",
        "segment_label": "signage",
    },
}


def web_search_fields(contact, cfg):
    """
    Returns dict with service, smb_type, smb_guess.
    Falls back to segment defaults if nothing found.
    """
    company = (contact.get("company") or "").strip()
    city = (contact.get("city") or "their city").strip()

    service = cfg["default_service"]
    smb_type = cfg["default_smb_type"]
    smb_guess = cfg["default_smb_guess"]

    if not company:
        return {"service": service, "smb_type": smb_type, "smb_guess": smb_guess, "web_found": False}

    prompt = cfg["prompt"].format(company=company, city=city)

    try:
        r = requests.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
            json={"model": MODEL, "tools": [{"type": "web_search"}], "input": prompt},
            timeout=90,
        )
        r.raise_for_status()

        text = ""
        for item in r.json().get("output", []):
            if item.get("type") == "message":
                for block in item.get("content", []):
                    if block.get("type") == "output_text":
                        text = block.get("text", "").strip()

        # Strip citation markdown
        text = re.sub(r'\s*\(\[.*?\]\(https?://.*?\)\)', '', text)
        text = re.sub(r'\s*\[.*?\]\(https?://.*?\)', '', text)
        text = re.sub(r'\[\d+\]', '', text).strip()

        if text and text.upper() != "NONE":
            lines = text.strip().splitlines()
            found_service = None
            found_smb = None
            for line in lines:
                if line.lower().startswith("service:"):
                    found_service = line.split(":", 1)[1].strip().rstrip(".")
                elif line.lower().startswith("smb_type:"):
                    found_smb = line.split(":", 1)[1].strip().rstrip(".")
            if found_service and found_smb:
                smb_guess = found_smb  # use actual smb_type as the guess
                return {
                    "service": found_service,
                    "smb_type": found_smb,
                    "smb_guess": smb_guess,
                    "web_found": True,
                }
    except Exception as e:
        pass  # fall through to defaults

    return {"service": service, "smb_type": smb_type, "smb_guess": smb_guess, "web_found": False}


def process_contact(contact, cfg):
    fields = web_search_fields(contact, cfg)
    return {**contact, **fields}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file",    required=True)
    parser.add_argument("--segment", required=True, choices=list(SEGMENT_CONFIG.keys()))
    parser.add_argument("--out",     required=True)
    args = parser.parse_args()

    if not OPENAI_KEY:
        print("OPENAI_API_KEY not set"); sys.exit(1)

    cfg = SEGMENT_CONFIG[args.segment]

    with open(args.file) as f:
        contacts = json.load(f)

    # Resume: skip already-enriched
    already_done = {}
    if os.path.exists(args.out):
        with open(args.out) as f:
            existing = json.load(f)
        already_done = {c["email"]: c for c in existing if c.get("email") and "service" in c}
        print(f"Resuming: {len(already_done)} already enriched.")

    to_process = [c for c in contacts if c.get("email") and c["email"] not in already_done]
    total = len(to_process)
    print(f"Web enriching {total} contacts (segment={args.segment}, model={MODEL}, workers={MAX_WORKERS})...")

    output = list(already_done.values())
    errors = 0
    found = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(process_contact, c, cfg): c for c in to_process}
        completed = 0
        for future in as_completed(futures):
            contact = futures[future]
            completed += 1
            try:
                result = future.result()
                output.append(result)
                if result.get("web_found"):
                    found += 1
            except Exception as e:
                errors += 1
                output.append({**contact, **{k: cfg[f"default_{k}"] if f"default_{k}" in cfg else "" for k in ["service","smb_type","smb_guess"]}, "web_found": False})
                print(f"  ERROR {contact.get('email')}: {e}")

            if completed % 25 == 0 or completed == total:
                with open(args.out, "w") as f:
                    json.dump(output, f, indent=2)
                print(f"  [{completed}/{total}] web_found={found} default={completed-found-errors} errors={errors}")

    with open(args.out, "w") as f:
        json.dump(output, f, indent=2)

    hit_rate = found / total * 100 if total > 0 else 0
    print(f"\nDone: {found}/{total} got specific signal ({hit_rate:.0f}% hit rate) -> {args.out}")

    samples = [c for c in output if c.get("web_found")][:3]
    for s in samples:
        print(f"\n  {s.get('first_name')} at {s.get('company')} ({s.get('city')})")
        print(f"    service:  {s.get('service')}")
        print(f"    smb_type: {s.get('smb_type')}")


if __name__ == "__main__":
    main()
