#!/usr/bin/env python3
import sys, io, json, re
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

with open(r"C:\Users\evane\AppData\Local\Temp\bounce\bounce_plg_verified.json") as f:
    leads = json.load(f)

issues = defaultdict(list)

for l in leads:
    e    = l["email"]
    camp = l.get("original_campaign", "")
    s1   = (l.get("Subject1") or l.get("subject1") or "")
    e1   = (l.get("Email1")  or l.get("email1")  or "")
    e2   = (l.get("Email2")  or l.get("email2")  or "")
    e3   = (l.get("Email3")  or l.get("email3")  or "")

    # ── MISSING CONTENT ────────────────────────────────────────────────────
    if not s1.strip(): issues["missing_subject1"].append(f"{e}")
    if not e1.strip(): issues["missing_email1"].append(f"{e}")
    if not e2.strip(): issues["missing_email2"].append(f"{e}")
    if not e3.strip(): issues["missing_email3"].append(f"{e}")

    # ── VERY SHORT BODIES ──────────────────────────────────────────────────
    if e1 and len(e1) < 80:
        issues["short_email1"].append(f"{e}: {repr(e1[:60])}")
    if e2 and len(e2) < 40:
        issues["short_email2"].append(f"{e}: {repr(e2[:60])}")
    if e3 and len(e3) < 40:
        issues["short_email3"].append(f"{e}: {repr(e3[:60])}")

    # ── GREETING ISSUES ────────────────────────────────────────────────────
    for field, body in [("Email1", e1), ("Email2", e2), ("Email3", e3)]:
        if re.search(r"Hi Role[,\.]", body, re.IGNORECASE):
            issues["hi_role_greeting"].append(f"{e} [{field}]")
        if re.search(r"Hi Contact \d", body, re.IGNORECASE):
            issues["hi_contact_n_greeting"].append(f"{e} [{field}]")
    if e1 and not re.match(r"^(Hi |Hey )", e1.strip(), re.IGNORECASE):
        issues["email1_no_greeting"].append(f"{e}: {repr(e1[:50])}")

    # ── LINKS / URLS STILL IN COPY ─────────────────────────────────────────
    for field, body in [("Email1", e1), ("Email2", e2), ("Email3", e3)]:
        if re.search(r"<a\s", body, re.IGNORECASE):
            issues["link_tag_present"].append(f"{e} [{field}]")
        m = re.search(r"https?://\S+", body)
        if m:
            issues["url_present"].append(f"{e} [{field}]: {m.group()[:60]}")

    # ── RAW \\n IN EMAIL2/3 (should be <br>) ───────────────────────────────
    for field, body in [("Email2", e2), ("Email3", e3)]:
        if "\n" in body:
            issues["raw_newline"].append(f"{e} [{field}]")

    # ── EMAIL1 HAS NON-BR HTML TAGS ────────────────────────────────────────
    m = re.search(r"<(?!br[\s/>])[a-zA-Z][^>]*>", e1, re.IGNORECASE)
    if m:
        issues["email1_html_tags"].append(f"{e}: {m.group()[:50]}")

    # ── DUPLICATE CTA ──────────────────────────────────────────────────────
    for field, body in [("Email2", e2), ("Email3", e3)]:
        n = len(re.findall(r"just reply", body, re.IGNORECASE))
        if n > 1:
            issues["double_cta"].append(f"{e} [{field}] ({n}x)")

    # ── RAW STREET ADDRESS STILL IN COPY ──────────────────────────────────
    for field, body in [("Email1", e1), ("Email2", e2), ("Email3", e3)]:
        if re.search(r"\bin \d{2,} [A-Z][a-z]", body):
            issues["raw_address"].append(f"{e} [{field}]: {re.search(r'in \\d[^<.?!]{0,40}', body).group()[:50]}")

    # ── STALE TIME PHRASES ─────────────────────────────────────────────────
    stale = ["before the end of the year", "before the end of q1",
             "ahead of the holidays", "before the holidays", "end of year"]
    for field, body in [("Email1", e1), ("Email2", e2), ("Email3", e3)]:
        for phrase in stale:
            if phrase in body.lower():
                issues["stale_phrase"].append(f"{e} [{field}]: \"{phrase}\"")

    # ── "UNITED STATES" IN COPY ────────────────────────────────────────────
    for field, body in [("Email2", e2), ("Email3", e3)]:
        if "United States" in body:
            issues["verbose_location"].append(f"{e} [{field}]")

    # ── UNFILLED PLACEHOLDERS ──────────────────────────────────────────────
    for field, body in [("Subject1", s1), ("Email1", e1), ("Email2", e2), ("Email3", e3)]:
        ph = re.findall(r"\{\{[^}]+\}\}", body)
        if ph:
            issues["unfilled_placeholder"].append(f"{e} [{field}]: {ph}")
        if re.search(r"\[CITY\]|\[COMPANY\]|\[SERVICE\]|\[NAME\]", body, re.IGNORECASE):
            issues["unfilled_bracket"].append(f"{e} [{field}]")

    # ── JSON BLOB LEAKED INTO COPY ─────────────────────────────────────────
    for field, body in [("Email1", e1), ("Email2", e2), ("Email3", e3)]:
        if re.search(r'\{"reasoning"', body) or re.search(r'"confidence":', body):
            issues["json_leaked"].append(f"{e} [{field}]")

    # ── CTA MISSING IN EMAIL2 / EMAIL3 ────────────────────────────────────
    for field, body in [("Email2", e2), ("Email3", e3)]:
        if body and "reply" not in body.lower():
            issues["missing_cta"].append(f"{e} [{field}]")

    # ── ENCODING ARTIFACTS ────────────────────────────────────────────────
    for field, body in [("Email1", e1), ("Email2", e2), ("Email3", e3)]:
        if "\ufffd" in body:
            issues["encoding_fffd"].append(f"{e} [{field}]")

    # ── SUSPICIOUS SUBJECT (blank/generic) ────────────────────────────────
    if s1.lower().strip() in ["subject", "subject1", "test", "n/a"]:
        issues["generic_subject"].append(f"{e}: \"{s1}\"")

# ─── report ──────────────────────────────────────────────────────────────────
print("=" * 62)
print(f"COPY CONSISTENCY CHECK  |  {len(leads)} leads")
print("=" * 62)

total = sum(len(v) for v in issues.values())
if total == 0:
    print("\nALL CLEAN - no issues found!\n")
else:
    print(f"\nFound {total} issues in {len(issues)} categories:\n")
    for cat, items in sorted(issues.items()):
        print(f"  [{len(items):3}]  {cat}")
        for item in items[:5]:
            print(f"          {item}")
        if len(items) > 5:
            print(f"          ... and {len(items)-5} more")
        print()
