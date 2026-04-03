# Resquared Campaign Playbook
## End-to-End Guide — PLG, CRE, and BB Campaigns

This document is the single source of truth for building any new campaign from scratch.
Follow every phase in order. Never skip steps. Never launch without completing the checklist.

CRE and BB campaigns skip Apollo phases — see **CRE/BB-SPECIFIC RULES** section for their flow divergences.

---

## MANDATORY RULE — Checklist Before Every Transition

**Before advancing to any next phase, switching topics, or resuming after a break:**
Run through this checklist out loud. Do not skip. Do not assume steps were done in a previous session.

```
□ Leads enriched and verified (BillionVerify done, deliverables-only)
□ Copy generated for all leads (no empty Email1/Email2/Email3 fields)
□ 3-pass copy QA completed (Phase 5B) — user signed off
□ BigQuery table created and populated (Phase 5C or 8B)
□ Campaign doc created in Drive and validated by user (Phase 5C)
□ SmartLead campaign created and fully configured (Phase 6A–6G)
□ Manual UI steps done: OOO restart ON + AI categorization set (Step 6B-UI)
□ Campaign launched and status confirmed ACTIVE (Phase 8)
```

If any box is unchecked, complete it before moving on.
This rule applies even if the user changes the subject — finish the open phase first, or explicitly confirm with the user to park it.

---

---

## PHASE 0 — Strategy & Segment Selection

Before touching any API, answer these questions:

### Is this segment actually a Resquared buyer?
Read `ICP_DEFINITIONS.md` for full definitions. The one test that matters:
> **Does this company actively cold call or cold email local businesses (restaurants, retail, offices, contractors) to sell their service?**

If they wait on referrals, inbound, carrier assignment, or enterprise leads → NOT our buyer.

### Check historical data before picking a segment
Pull `SEARCH_LOG.md` and campaign stats. Ask:
- What positive reply rate have we seen from this segment before?
- How much TAM is left? (Has this keyword been exhausted in Apollo?)
- What copy angle worked / didn't work?
- Are there any existing contacts in HubSpot from this segment already?

### Benchmark reply rates — always pull live, never assume
Do not use hardcoded numbers. Pull actual all-time positive reply rates per campaign:

```python
# smartlead_pull.py has get_plg_campaign_breakdown() — use it
# Or query directly:
from smartlead_pull import get_all_campaigns, get_campaign_statistics, aggregate_stats

for c in get_all_campaigns():
    if c['name'].upper().split(' - ')[0] not in ('PLG', 'SLG'): continue  # skip non-taxonomy campaigns
    if c['status'] not in ('ACTIVE','PAUSED','COMPLETED'): continue
    stats = get_campaign_statistics(c['id'])  # all-time, no date filter
    agg = aggregate_stats(stats)
    if agg['sent'] > 50:  # only campaigns with meaningful volume
        pos_rate = agg['positive'] / agg['sent'] * 100
        print(f"{c['name']}: {pos_rate:.2f}% positive ({agg['positive']}/{agg['sent']})")
```

Positive = `lead_category` in `{'Interested', 'Meeting Request', 'Meeting Booked', 'Information Request'}`
AND `reply_time` is not null. SmartLead pre-classifies all leads even without replies — always check both.

### Decide: PLG or SLG (CRE/BB)?
- **PLG:** self-serve buyer, lower ACV, high volume → trial link on reply
- **SLG:** higher ACV, needs demo, relationship → CRE or Business Brokers pipeline

When in doubt, default to PLG. Only proceed with SLG on explicit user confirmation (Claude must ask).

**All campaigns must follow the naming taxonomy:** `{Strategy} - {ICP} - {Channel} - {Approach} - {CTA} - {Version}`
See `CLAUDE.md` → **CAMPAIGN NAMING TAXONOMY** for valid values and guidance on choosing Approach and CTA.
Claude must propose Approach and CTA, explain the reasoning, and get user approval before creating the campaign.

**One campaign = one BigQuery table. The sample pull and the full pull go into the SAME table.
Never create a second table for the same campaign — append to the existing one.**

---

## CRE / BB CAMPAIGN — SPECIFIC RULES

CRE and BB campaigns diverge from the PLG flow in several important ways. Read this section first
before starting any SLG campaign. Everything not listed here follows the standard phases below.

### Input source
CRE/BB leads come as a **CSV file** (from LoopNet, Crexi, or an existing enriched database).
**Skip Phases 1–4 entirely** (no Apollo search, no Apollo enrichment, no dedup against Apollo tables).

### Step CRE-1 — Email deliverability check (BillionVerify only)
Run BillionVerify on the raw CSV before doing anything else:
```bash
python verify_emails.py --file /tmp/{segment}_raw.csv --out /tmp/{segment}_verified.json
```
Remove undeliverable contacts. Proceed with verified contacts only.

### Step CRE-2 — Listing enrichment (default ON — always encourage user to run this)
Before generating copy, ask the user:
> "Do you want me to update the listings for each broker? This pulls their current active listings from
> LoopNet/Crexi and uses them to personalize the copy. It usually improves reply rate significantly —
> I'd recommend it."

**Default: run unless user explicitly says no.**

```bash
python listing_enrich.py --file /tmp/{segment}_verified.json --out /tmp/{segment}_enriched.json
```

- Searches LoopNet, Crexi, and broker websites for each rep's current active listing
- Scores by type: retail (best) > mixed-use > office > other > industrial (worst)
- Outputs listing address, type, size, price, details, and URL per contact
- Resume-safe (use `--limit N` to test on a small batch first)
- Use the enriched output as input to copy generation

If user skips enrichment, proceed with `_verified.json` as the copy gen input.

### Step CRE-3 — Copy generation
Follow Phase 5 as normal, using CRE-specific templates and CTAs:
- Email 1: personalized to the broker's listing (if enriched) — address, type, size
- Email 2: follow-up referencing listing data, reply-based CTA
- Email 3: new subject/trigger, brief last touch

### Step CRE-4 — BigQuery sync (SLG tables, not PLG)
After loading leads, sync to the **SLG** dataset — NOT PLG_OUTBOUND:
```bash
python bq_sync.py contacts \
  --file /tmp/{segment}_enriched.json \
  --segment {segment} \
  --dataset SLG_OUTBOUND

python bq_sync.py enroll \
  --campaign-id {id} \
  --campaign-name "SLG - CRE - Email - HyperPersonal - Demo - v1" \
  --segment {segment} \
  --dataset SLG_OUTBOUND
```
Tables: `SLG_OUTBOUND.SLG_CONTACTS`, `SLG_OUTBOUND.SLG_CAMPAIGN_ENROLLMENTS`

---

## PHASE 1 — Build the Apollo List

### Step 1A — Free discovery (no credits)
Use `POST /v1/mixed_people/api_search` to pull all candidate IDs.

```python
# Auth: X-Api-Key header (NOT query param — Apollo deprecated that)
headers = {"X-Api-Key": APOLLO_API_KEY, "Content-Type": "application/json"}

payload = {
    "person_titles": ["owner", "principal", "agent", "producer", "president",
                      "founder", "partner", "managing partner", "agency owner"],
    "organization_num_employees_ranges": ["1,50"],
    "organization_locations": ["United States"],
    "q_keywords": "YOUR EXACT KEYWORD HERE",  # See keyword guidance below
    "per_page": 100,
    "page": 1,
    "has_email": True,  # Free filter — ~50% accurate but cuts list size
}
```

**Rate limits:** 50 req/min, 200/hr, 600/24hr. At 100/page, max ~60K contacts/24hr.
**Returns:** id, first_name, title, has_email, organization.name (obfuscated — not full email)

Loop all pages until empty. Save all IDs to `/tmp/{segment}_candidates.json`.
Track page count and TAM estimate in `SEARCH_LOG.md`.

### Step 1B — Keyword selection (CRITICAL — this determines list quality)
Bad keyword = wasted credits enriching wrong people.

Rules:
1. **Never use a broad industry term alone.** "commercial insurance" catches wholesale brokers, benefits consultants, captive agents.
2. **Use the most specific phrase that describes exactly your ICP.** "independent insurance agent" >> "commercial insurance"
3. **Test on free api_search first.** Check first 10 results for ICP fit before enriching.
4. **Estimate TAM via binary search** — page through without enriching to count total results.
5. **When a keyword is exhausted, try variants.** For insurance: "commercial lines agent", "P&C insurance agent", "business insurance broker" → each is a separate TAM pool.

### Step 1C — Post-filter before enriching
Apply these filters to free api_search results BEFORE spending enrichment credits:
- `has_email: True` (still only ~50-68% accurate, but cuts waste)
- Exclude captive/franchise brands from company name
- Exclude disqualifying title keywords (e.g., "personal lines", "life insurance", "health insurance")

---

## PHASE 2 — Deduplication (Before Enriching)

Run dedup BEFORE enrichment to avoid wasting credits on people we've already contacted.

### Check 1 — SmartLead history
Pull all existing campaign leads and compare Apollo IDs or emails:

```python
# Get all leads from all PLG campaigns
# Compare by email domain OR apollo_id
# Flag anyone whose company domain already appears in SmartLead
# Strategy: same company = usually skip, but can target different person if first contact was 6+ months ago
```

### Check 2 — HubSpot domain check
Pull all HubSpot contacts/deals and extract domains. Exclude any Apollo candidate whose
organization domain matches a HubSpot deal (don't cold email active deals or customers):

```python
# Query: airbyte_prod.hubspot_contacts for existing emails/domains
# Exclude: any domain matching an existing HubSpot deal or customer
# Keep: companies with no HubSpot record at all
```

Save deduplicated candidate list with a clear count:
- Total candidates from api_search
- Removed (already in SmartLead)
- Removed (in HubSpot as deal/customer)
- **Net new: X contacts available to enrich**

---

## PHASE 3 — TAM Tracking

Update `SEARCH_LOG.md` IMMEDIATELY after every search. Never leave this stale.

Required fields per entry:
```markdown
### Search vN (YYYY-MM-DD)
**Keyword**: `exact keyword used`
**Filters**: person_titles, org size, location, has_email
**TAM**: ~X contacts (estimated via page count × per_page)
**Candidates pulled (free)**: X contacts → saved to `/tmp/segment_vN_candidates.json`
**Post-dedup net new**: X contacts
**Enriched**: X contacts (at ~$0.024/contact on Basic plan)
**Verified emails returned**: X contacts (yield %)
**Credits used**: ~X of 2,500 monthly
**Saved to**: `/tmp/segment_vN_enriched.json`
**Status**: CURRENT / EXHAUSTED
**Remaining TAM**: X contacts on pages N–M not yet pulled
**Next keywords to try**: "...", "..."
```

This is how we know what to pull next without repeating ourselves.

---

## PHASE 4 — Enrichment + Verification

### Step 4A — Enrich via Apollo
Enrich only candidates that passed Phase 2 dedup.

```python
# POST /v1/people/match with {"id": apollo_id}
# Returns: full name, verified email, company, domain, city, state, title, LinkedIn
# Cost: 1 credit per call (regardless of whether email is returned)
# Yield reality: ~68% return verified email on our segments
# Save incrementally — don't lose work if script dies
# Filter output: only keep records with non-null email
```

**Credit budget:** Apollo Basic = 2,500/month at $59/mo ($0.024/contact)
**Save to:** `/tmp/{segment}_enriched.json`

### Step 4B — Verify emails via BillionVerify (MANDATORY before loading to SmartLead)
Apollo's "verified" flag is NOT SMTP-verified. Without this step, expect 3–11% bounce rates
which will damage sending domain reputation.

```bash
# Check credits first
python verify_emails.py --credits

# Verify the enriched list (filters to valid-only by default)
python verify_emails.py \
  --file /tmp/{segment}_enriched.json \
  --out  /tmp/{segment}_verified.json

# Optional: include catch_all if you want more volume (riskier)
python verify_emails.py --file ... --out ... --include-catchall
```

**Status guide (BillionVerify):**
- `is_deliverable=True, is_catchall=False` → valid → send ✓
- `is_catchall=True` → risky, domain accepts all mail — use `--include-catchall` if needed
- `is_deliverable=False` → never send, auto-removed

**Credentials:** `BillionVerify_API_KEY` in `.env`. Top up at billionverify.com — credits shown at start of script.
**Use `/tmp/{segment}_verified.json` as input to all downstream steps** (copy gen, SmartLead load, BQ sync).

---

## PHASE 5 — Copy Development

This is the most important phase. Bad copy wastes every contact on the list.
**Get approval on copy direction and samples BEFORE generating for the full list.**

### Email 1 — The first touch (PLAIN TEXT, no links, no HTML)

**UNIVERSAL RULE — Email 1 is ALWAYS plain text. No exceptions. PLG and non-PLG alike.**

Email 1 must be stored as plain text with `\n` line breaks. When loading into SmartLead,
convert `\n\n` to `<br><br>` and `\n` to `<br>` ONLY at load time — the stored copy itself
must contain zero HTML tags. SmartLead's `send_as_plain_text: true` setting handles rendering,
but if the stored body contains `<a href>`, `<img>`, or any HTML beyond `<br>` line breaks,
it will trigger HTML rendering in some email clients and destroy deliverability.

**Structure (in order):**
1. One qualifying question OR personalized opening (see LLM guidance below)
2. One-line platform pitch — specific to their vertical, not generic
3. The offer: "free accounts this month"
4. CTA

**Hard rules:**
- Under 65 words total
- **ZERO links in Email 1. No exceptions. No `<a href>`, no plain-text URLs, no trackable links, nothing.**
- **ZERO HTML in Email 1. No `<b>`, `<i>`, `<img>`, `<div>`, nothing. Plain text only.**
- `<br>` tags are inserted ONLY at SmartLead load time (converting from `\n`). Never in stored copy.
- NO em dashes
- Plain text style — reads like a human typed it quickly
- ONE specific vertical mentioned (not "local businesses" — say "restaurants", "retailers", "contractors")
- NO "I hope this finds you well", no filler openers
**PLG CTAs** — goal is to get them to ask for the trial link (do NOT send the link):
  - ✅ "Should I send you one?" (winner)
  - ✅ "Want me to send over the results?"
  - ❌ "Want the link?" (sounds phishing-adjacent)
  - ❌ "Are you the best person to reach out to?" (worst tested — 0.254% positive)

**CRE/BB CTAs** — goal is a reply, interest signal, or demo request:
  - ✅ "Open to a quick demo?"
  - ✅ "Let me know if you'd like to discuss."
  - ✅ "Happy to connect if this is relevant."
  - ❌ Hard sells, urgency pressure, or forced scheduling links

**Subject line format:** `"[service type] x local [specific vertical]"`
- ✅ "window cleaning x local medical offices" → 4.76% reply
- ✅ "cleaning x local restaurants"
- ❌ "janitorial supplies in Dallas" → 0.00%
- No location in subject. No company name in subject unless it's a Blunt-style template.

### LLM Copywriting — How to get non-garbage output

The single biggest failure mode: LLM rewrites the whole email and produces generic slop.
**Lock everything except what the LLM is specifically allowed to personalize.**

**What the LLM should write:** ONE thing. Either:
- One opening question (1 sentence, max 15 words)
- One personalized observation about their company/city/niche

**What the LLM must NOT do:**
- Rewrite the template
- Add compliments ("I love what you're doing")
- Start with "I noticed" or "With a name like" or "As a [title]"
- Use em dashes, semicolons, or any punctuation that reads as AI
- Make claims it can't verify

**System prompt structure (proven):**
```
Write ONE [opening question/observation] for a cold email to [ICP description].
[Constraint]: One sentence. Max 15 words. Must be a question. / Must be a statement.

Decision tree for personalization:
- [Signal A in company name/data] → [specific angle]
- [Signal B in company name/data] → [specific angle]
- [Default] → [fallback question]

Rules: [list of explicit bans]
Output: sentence only. No explanation.
```

**For insurance example:**
```
Decision tree:
- "Commercial" in name → "Is commercial your main focus or do you write personal lines too?"
- "Family" / "personal" in name → "Do you write commercial accounts in addition to personal?"
- City + industry in name → "Are you working [industry] accounts in [city]?"
- Neutral name → "Commercial or personal lines — where's most of your book?"
```

**After LLM output — always:**
- Verify no em dashes, no "I noticed", no compliments
- Verify Email 1 is pure plain text — no HTML tags, no links of any kind
- Spot-check 10-20 samples before generating full list
- ALL emails stored as plain text with `\n` line breaks. Convert to `<br>` ONLY at SmartLead load time.
- NO links or HTML in Email 2 or 3 — pure plain text, reply-based CTAs only.

**Models:** Use `gpt-5-mini` (ID: `gpt-5-mini-2025-08-07`) for bulk generation.
Use `ThreadPoolExecutor(max_workers=8)` for parallel API calls.
Set `max_completion_tokens: 2000` (reasoning model, uses ~900 tokens for reasoning).

### Web Enrichment (Clay-style, for richer personalization)

For campaigns where a specific real-world reference dramatically improves reply rate
(e.g., Signage best performer mentioned a specific open business by name), use LLM-based
web search to find a real, verifiable detail about the prospect:

**Approach:**
1. For each contact, construct a web search query based on their company + city + vertical
2. Use OpenAI with web search tool OR a search API (Serper, Brave) to retrieve real info
3. Feed that result into the LLM as context for generating the personalized line
4. **Validate output** — if LLM hallucinates (invents info not in search results), fall back to generic

**Example use cases by segment:**
- CRE broker → find a current open listing they have (search their website)
- Insurance agent → find a niche they specialize in from their website/reviews
- Signage company → find a recent install they posted about (LinkedIn/website)
- Catering → find a corporate client type they mention on their site

**Cost:** ~$0.01-0.03/contact. Worth it for any segment with meaningful TAM where it lifts reply rate.

**Implementation:** `web_enrich.py` — run BEFORE generate_emails.py. Uses OpenAI Responses API with web_search tool.
```bash
python web_enrich.py --file /tmp/{segment}_verified.json --segment {segment} --out /tmp/{segment}_enriched.json
python generate_emails.py --file /tmp/{segment}_enriched.json --segment {segment} --out /tmp/{segment}_emails.json
```
Model: `o4-mini` via `POST /v1/responses` with `tools: [{"type": "web_search"}]`.
**Never use gpt-4 family — always check latest model docs before picking a model.**
Output stored in `web_detail` field. generate_emails.py uses it as opener if present, falls back to decision tree question if empty.

### Email 2 — Follow-up (plain text, no links, day +3)

Email 2 is plain text, stored with `\n` line breaks like Email 1. No HTML, no links.
The goal is to surface the data/value and get a reply — NOT to send a link directly.

**Sequence threading:** Email 2 has NO subject line. SmartLead sends it as a reply in the same thread as Email 1.

**PLG approach** — reference the city data, ask them to reply for access:
```
I ran a quick search in {city} this morning.

Made a list of {businesses} that look like they could use your services.

Just reply and I'll send you the data.
```

**CRE/BB approach** — reference listings or local data, ask to discuss:
```
Ran a quick search for retail spaces in {city} that match what your tenants are looking for.

Let me know if you'd like to take a look — happy to walk you through it.
```

Do NOT use stale time phrases ("before the end of Q1", "before the holidays"). Keep it timeless.

**City resolution rule (always apply in this order):**
```
city = COALESCE(NULLIF(TRIM(city),''), NULLIF(TRIM(company_city),''), 'your area')
```
Never leave `{city}` blank — if both `city` and `company_city` are missing, fall back to `"your area"`.

**Business count rule — use real data, display as friendly rounded number:**
- Query `business_sources.us_companies_list__30m_us_business_std` for `COUNT(*) WHERE city = '{city}'`
- Round using this logic (never show raw count):
  - Find the largest "nice" breakpoint ≤ count → `floor_bp`
  - Find the smallest "nice" breakpoint > count → `ceil_bp`
  - If `count / ceil_bp >= 0.97` → display as `"almost {ceil_bp:,}"`
  - Otherwise → display as `"over {floor_bp:,}"`
- Nice breakpoints: 50, 100, 150, 200, 250, 300, 400, 500, 750, 1,000, 1,500, 2,000, 2,500, 3,000, 5,000, 7,500, 10,000, 15,000, 20,000, 25,000, 30,000, 50,000, 75,000, 100,000, 150,000, 200,000+
- Examples: 290 → "over 250" | 982 → "almost 1,000" | 30,231 → "over 30,000"
- If city has no match in BQ → fall back to `"thousands of businesses"`

Template (mail-merge, no LLM needed — plain text, \n line breaks):
```
I ran a quick search in {city} myself this morning.

Made a list of {businesses} that look like they could use your services.

Just reply and I'll send you the data.
```

### Email 3 — Last touch (plain text, no links, day +8)

Email 3 is plain text, stored with `\n` line breaks. No HTML, no links.

**Sequence threading:** Email 3 HAS its own subject line — a new angle/trigger. This starts a fresh thread (not a reply to Email 1), making it feel like a separate outreach rather than a third follow-up. Pick a subject that's different from Email 1's angle.

**Subject line:** Different trigger from Email 1. Examples:
- Email 1: `"cleaning x local restaurants"` → Email 3: `"local restaurant contacts in {city}"`
- Email 1: `"IT services x local businesses"` → Email 3: `"MSP leads in {city}"`
- Email 1: `"retail listings in {city}"` → Email 3: `"{city} tenant prospects"`

**PLG approach** — brief, last shot, reply to get the link:
```
Since I'm guessing you're busy, leaving this here for when you have a moment.

The data for {city} is ready on our end. Just reply and I'll send you access.
```

**CRE/BB approach** — brief, low pressure, invite reply:
```
Last note from me — if timing isn't right, no worries at all.

If you'd ever want to see how we can help with {city} leads, just reply and we can find 5 minutes.
```

### Custom fields for SmartLead leads
All campaigns (PLG, CRE, BB) use 4 custom fields per lead:
- `Subject1` — Email 1 subject (personalized per lead)
- `Subject3` — Email 3 subject (new trigger, different angle from Subject1) — CRE/BB also use this
- `Email1` — full Email 1 body (**plain text stored with `\n`, converted to `<br>` at load time**)
- `Email2` — full Email 2 body (**plain text stored with `\n`, converted to `<br>` at load time**)
- `Email3` — full Email 3 body (**plain text stored with `\n`, converted to `<br>` at load time**)

**CRITICAL:** NO email (1, 2, or 3) may contain `<a href>`, `<img>`, or any HTML of any kind.
ALL bodies are stored as plain text with `\n` and converted to `<br>` ONLY at SmartLead load time.
This is universal across PLG, CRE, and BB. HTML in emails triggers rendering issues and spam filters.

---

## PHASE 5B — Copy QA (3-Pass Check)

Run this after generating all copy. **Do NOT load leads to SmartLead until all 3 passes complete or user signs off.**

### The 3-Pass Process

**Pass 1 — Run automated check + show user all issues found.**
If any issues: present the full list to the user, get feedback on what to fix and how, then apply fixes.

**Pass 2 — Re-run automated check after Pass 1 fixes.**
If any issues remain: present them again, get user confirmation on each fix, apply.

**Pass 3 — Re-run automated check after Pass 2 fixes.**
If any issues remain: present to user. User decides whether to fix or accept and proceed to launch.

After 3 passes, proceed to Phase 6 regardless of minor remaining issues (user has been informed).

### Unified Copy Check Rules (applies to ALL campaigns: PLG, BB, CRE)

These rules apply unless the user explicitly says to skip a specific rule for this campaign.

For CRE campaigns, apply to all body fields: `Email1`, `Email1a`, `Email1b`, `Email2`, `Email3`.
For PLG/BB campaigns, apply to: `Email1`, `Email2`, `Email3`.

```
CONTENT COMPLETENESS
□ Subject1 is present and non-empty
□ Subject3 is present and non-empty (Email 3 needs its own subject)
□ Email1, Email2, Email3 all present and non-empty
□ Email1 body ≥ 80 chars (too short = not a real email)
□ Email2/3 body ≥ 40 chars (too short = blank or placeholder only)
□ Email1 body ≤ ~400 chars / ~65 words (over-long = LLM rewrote template)
□ Email2/3 body ≤ ~600 chars / ~100 words (keep follow-ups tight)

GREETING & FIRST NAME
□ Email1 starts with "Hi " or "Hey " (must have a greeting)
□ Greeting is not "Hi Role," or "Hi Contact 1," (LLM used field name, not value)
□ Greeting is not "Hey there," (first_name fallback failed — check first_name field)
□ first_name is not "there", all-caps (DAVID), all-lowercase (farzad), or a company/role name
□ No "I noticed", "I hope this finds you well", or AI-sounding openers

LINKS & HTML (zero tolerance)
□ No <a href> tags in any email body or subject
□ No raw URLs (https:// or http://) in any email body or subject
□ No HTML tags of any kind in any email body (<b>, <i>, <div>, <img>, etc.)
□ No <br> tags in stored copy — line breaks must be \n (converted at load time)

COPY QUALITY
□ No em dashes (—) in any field
□ No repeated CTAs — "just reply" / "let me know" / "open to a demo" appears max 1x per email
□ No repetitive phrases across an email ("your listing at your listing", same sentence twice)
□ CTA is present in Email2 and Email3 (must contain reply invitation or interest ask)
□ Subject1 is not generic: not "subject", "subject1", "test", "n/a", "follow up", "last note"
□ Subject3 is not generic and is meaningfully different from Subject1

PERSONALIZATION ACCURACY
□ No unfilled placeholders: {{...}}, [CITY], [NAME], [COMPANY], [SERVICE], [TYPE]
□ No JSON blob leaked into copy: {"reasoning", "confidence":, "output":
□ City is consistent across Email1/2/3 — if Email1 mentions {city}, Email2/3 use the same city
□ Business type is consistent across Email1/2/3 — same vertical throughout
□ If listing_address is present (CRE): no "your listing at your listing" artifacts
□ No raw street addresses in copy (digits + street name) unless address-specific copy is intentional
□ No "United States" — use city name only (e.g. "Austin", not "Austin, Texas, United States")
□ No verbose state+country combos: "Austin, Texas, United States" → "Austin"

TIMING & FRESHNESS
□ No stale time phrases: "before the end of the year", "before the end of Q1",
  "ahead of the holidays", "before the holidays", "end of year", "end of quarter"

ENCODING
□ No encoding artifacts (\ufffd replacement characters)
```

### Running the Check

Use `check_copy.py` (or the segment-specific equivalent) and pass the lead JSON file:
```bash
python check_copy.py --file /tmp/{segment}_emails.json
```

If no dedicated script exists for the campaign type, apply the above rules manually by spot-checking
10+ leads and scanning for each category.

---

## PHASE 5C — Campaign Document (Create Before Phase 6)

**Trigger:** Leads are enriched + verified, copy is generated, 3-pass QA is done, and BigQuery table is populated.
**Do this before touching SmartLead.** User must validate the doc before campaign setup begins.

### What to include
Create a Google Doc in the Drive folder: https://drive.google.com/drive/folders/19nk7hRcP5wPt9GdlDZy8z_jqwdwPHszG

Name format: `MM.DD.YY - {ICP} Campaign`  (e.g. `04.03.26 - HVAC Campaign`)

The doc must contain (in this order):

```
{Date} - {ICP} Campaign

Target:      one-sentence description of the audience
Source:      where leads came from (Apollo keywords / Clay table / list name)
Size:        N contacts — how they were filtered/deduped

SmartLead Campaigns:
  {Campaign Name} (ID: XXXXXXX) — N leads | N inboxes | N/day
  (one row per campaign if split)

BigQuery Table: {table_name}  (dataset: PLG_OUTBOUND or SLG_OUTBOUND)

---

Business Count Tiers (if applicable)
  Tier → value used

---

Messaging

Email 1 — plain text, no HTML, no links
Subject: {subject}
{body}

Email 1 Fallback — no city (if applicable)
{body}

Email 2 — HTML, no links
Subject: same thread (no new subject)
{body}

Email 3 — HTML, no links
Subject: {subject3}
{body}

---

Data Fields
  field_name  →  source / derivation
```

Keep it compact — only include what's relevant. Omit sections that don't apply (e.g. no Fallback if every lead has a city).

### Style rules
- No bullet overload — plain readable text
- Tables only for multi-row data (campaign split, tiers)
- Show actual email copy exactly as stored (with `{placeholders}`)
- No explanatory prose — just the facts

### After creating
Send the Google Doc link to the user with a one-line summary:
> "Here's the campaign doc: [link]. Please validate before I set up SmartLead."

**Do not proceed to Phase 6 until the user confirms the doc looks correct.**

---

## PHASE 6 — SmartLead Campaign Setup

**Full checklist. Do every step. Do not skip.**

### Step 6A — Create campaign
```
POST /campaigns/create
Body: {"name": "{Strategy} - {ICP} - {Channel} - {Approach} - {CTA} - {Version}"}
```
**Naming rule:** Always follow the taxonomy. Confirm the exact name with the user before creating.
Examples: `PLG - IT Solutions - Email - DataDriven - Access - v1` | `SLG - CRE - Email - HyperPersonal - Demo - v1`

### Step 6B — Apply ALL settings in ONE call (order matters)
```
POST /campaigns/{id}/settings
Body:
{
  "send_as_plain_text": true,          ← REQUIRED. Plain text = better deliverability
  "force_plain_text": true,            ← REQUIRED. Forces plain text as content type (failsafe guard)
  "enable_ai_esp_matching": true,      ← REQUIRED. 15-20% deliverability improvement
  "track_settings": ["DONT_TRACK_EMAIL_OPEN", "DONT_TRACK_LINK_CLICK"],  ← REQUIRED. Open tracking injects pixel = spam filter risk
  "stop_lead_settings": "REPLY_TO_AN_EMAIL",  ← Stop sequence when lead replies
  "follow_up_percentage": 50           ← 50% new leads / 50% follow-ups (Erik's standard)
}
```
⚠️ `send_as_plain_text` and `track_settings` MUST be in the same call or they reset each other.
⚠️ `track_settings` values: POST as `DONT_TRACK_EMAIL_OPEN` / `DONT_TRACK_LINK_CLICK`
   (API stores internally as `DONT_EMAIL_OPEN` / `DONT_LINK_CLICK` — both work for reads)
⚠️ Do NOT use `track_settings` in isolation — always include `send_as_plain_text: true` in same call.
⚠️ `force_plain_text` accepted by API (returns 200) but not visible in GET /campaigns/{id} response — it applies internally.

### Step 6B-UI — Manual UI settings (API cannot set these)

Two settings are **not available via API** and must be toggled manually in the SmartLead dashboard
for every new campaign, immediately after Step 6B. Do this before loading leads.

**1. Automatically restart OOO leads**
> Campaign settings → Lead Management → "Automatically restart ai-categorised OOO when lead returns" → **ON**

When SmartLead AI detects an out-of-office auto-reply, it pauses that lead's sequence.
This toggle resumes the sequence automatically once the lead is back — without manual intervention.
Without it, OOO leads sit paused forever and never receive their follow-ups.

**2. AI lead categorization**
> Must be configured in the **old SmartLead UI** — the new UI caps at 5 categories.
> Set up all reply categories (Interested, Meeting Request, Meeting Booked, Information Request,
> Not Interested, OOO, Wrong Person, Unsubscribe) so SmartLead auto-tags every reply correctly.
> This powers BQ reporting and determines which leads count as "positive" in campaign stats.

⚠️ Neither setting is exposed in `GET /campaigns/{id}` — you cannot verify them via API.
   Always do this step manually and confirm in the UI before launching.

### Step 6C — Set schedule
```
POST /campaigns/{id}/schedule
Body:
{
  "timezone": "America/New_York",
  "days_of_the_week": [1, 2, 3, 4, 5],   ← Mon-Fri only
  "start_hour": "09:00",
  "end_hour": "19:00",
  "min_time_btw_emails": 30,
  "max_new_leads_per_day": N              ← See sizing formula below

}
```

### Step 6D — Load sequences
```
POST /campaigns/{id}/sequences
Body: {"sequences": [
  {
    "seq_number": 1,
    "seq_delay_details": {"delay_in_days": 0},
    "subject": "{{Subject1}}",
    "email_body": "<div>{{Email1}}</div><div><br></div>"
  },
  {
    "seq_number": 2,
    "seq_delay_details": {"delay_in_days": 3},
    "subject": "",
    "email_body": "<div>{{Email2}}</div>"
  },
  {
    "seq_number": 3,
    "seq_delay_details": {"delay_in_days": 5},
    "subject": "{{Subject3}}",
    "email_body": "<div>{{Email3}}</div>"
  }
]}
```
**Sequence timing:** Day 0 → Day 3 → Day 8 (total 8-day sequence).
- +3 days for Email 2: standard lower-bound, matches "you had time to see it" window.
- +5 days for Email 3: industry best practice is 5-7 days for the final touch (avoids appearing pushy).
- Avoid sequences under 7 days total — compresses into spam-trigger territory.

**Subject threading rules:**
- Email 2: subject MUST be empty → SmartLead sends as a reply in the same thread as Email 1.
- Email 3: subject MUST be set (`{{Subject3}}`) → SmartLead starts a new thread. This is intentional — Email 3 uses a different angle/trigger, and arriving as a fresh email improves open rate.
- If Email 3 subject is empty, it threads as a third reply, which looks robotic and reduces opens.
⚠️ Sequence body: trailing `<div><br></div>` after Email1 adds spacing before auto-appended signature.
⚠️ NO `%signature%` in body — it renders as literal text via API. Signature auto-appends.
⚠️ To UPDATE existing sequences: include the `"id"` field from `GET /campaigns/{id}/sequences`.
   Omitting `id` = creates new sequences, does not update existing ones.

### Step 6E — Inbox selection and assignment

**MANDATORY audit before assigning any inbox:**

1. **Use BigQuery as source of truth** — always rebuild before inbox selection:
   ```bash
   python build_all_smartlead_accounts.py  # in scorecard/re2scorecard2026/
   ```
   The SmartLead API's `campaign_count` field is unreliable. Use `ALL_SMARTLEAD_CAMPAIGN_ACCOUNTS`
   to get true campaign membership counts. An inbox showing `campaign_count: 0` via API may still
   be assigned to campaigns per BQ.

2. **Ready inbox criteria** (ALL must be true):
   1. **Warmup started > 14 days ago:** `TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), TIMESTAMP(warmup_created_at), DAY) > 14`
      - If `warmup_created_at` is null, fall back to `created_at`
   2. **Warmup status is ACTIVE:** `warmup_status = 'ACTIVE'`
      - INACTIVE warmup = do not use, regardless of age or reputation
   3. **Warmup reputation > 90%** — prioritize 100% first, then fill with >90% if needed. Never use ≤ 90%.
   4. **Active campaigns = 0** — prefer inboxes in no campaign. If more inboxes are needed, allow up to 1 active campaign; when doing so, **prioritize inboxes attached to the oldest campaigns** (they are closest to finishing).
   5. `is_smtp_success: true` and `is_imap_success: true`
   6. `blocked_reason: null`

   **Canonical BQ query — Tier 1 (preferred, 0 active campaigns):**
   ```sql
   SELECT
     a.account_id, a.from_email, a.message_per_day, a.warmup_reputation,
     TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), TIMESTAMP(a.warmup_created_at), DAY) as warmup_age_days,
     COUNTIF(ca.campaign_status = 'ACTIVE') as active_campaigns
   FROM `tenant-recruitin-1575995920662.MARKETSEGMENTDATA.ALL_SMARTLEAD_ACCOUNTS` a
   LEFT JOIN `tenant-recruitin-1575995920662.MARKETSEGMENTDATA.ALL_SMARTLEAD_CAMPAIGN_ACCOUNTS` ca
     ON a.account_id = ca.account_id
   WHERE a.warmup_status = 'ACTIVE'
     AND a.is_smtp_success = TRUE AND a.is_imap_success = TRUE
     AND a.blocked_reason IS NULL
     AND CAST(REPLACE(a.warmup_reputation, '%', '') AS FLOAT64) > 90
   GROUP BY 1,2,3,4,5
   HAVING active_campaigns = 0 AND warmup_age_days > 14
   ORDER BY warmup_reputation DESC, warmup_age_days DESC
   ```

   **Tier 2 — fallback (max 1 active campaign, only if Tier 1 is insufficient):**
   ```sql
   -- Same query but HAVING active_campaigns = 1
   -- Join to ALL_SMARTLEAD_CAMPAIGN_ACCOUNTS to get the campaign's created_at
   -- ORDER BY campaign_created_at ASC (oldest campaign first)
   ```

3. **Hard blocks:**
   - ANY inbox with `blocked_reason` set = dead, do not use

4. **Assign:**
   ```
   POST /campaigns/{id}/email-accounts
   Body: {"email_account_ids": [id1, id2, ...]}
   ```

5. **Inbox count + daily rate sizing — three rules, pick the closest round number that wins on balance:**

   - **Rule A (leads-based):** `total_leads/5  ≤  daily  ≤  total_leads/4`
   - **Rule B (capacity-based):** `inbox_capacity/2  ≤  daily  ≤  inbox_capacity * 3/4`
     where `inbox_capacity = sum of message_per_day across all assigned inboxes`
   - **Rule C (timing-based):** days to first-email all leads (`total_leads / daily`) should leave minimal overlap with the follow-up delay (Email 1→2 gap). Aim for overlap ≤ 2 days.
     - `days_to_complete = total_leads / daily`
     - `overlap = days_to_complete - email2_delay_days`
     - Prefer overlap < 2 days; never exceed 3 days

   **How to pick:**
   1. Compute Rule A and Rule B ranges. Find the intersection.
   2. If no intersection, try adding more inboxes to shift Rule B up, or accept the closest boundary value.
   3. Apply Rule C as the tiebreaker between candidates — prefer the higher daily value if it meaningfully reduces overlap.
   4. Round to the nearest clean number (50s or 100s). Use the round number that wins on balance across all three rules.

   **Example — 1,366 leads, 20 inboxes, 355/day capacity, Email 1→2 delay = 3 days:**
   - Rule A: 273–341/day
   - Rule B (355 capacity): 178–266/day → no full overlap with Rule A
   - Candidates: 250 (Rule B ✓, Rule A ✗) vs 300 (Rule A ✓, Rule B slightly over)
   - Rule C at 250: 1,366/250 = 5.5 days → 2.5 days overlap ✗
   - Rule C at 300: 1,366/300 = 4.6 days → 1.6 days overlap ✓
   - **Decision: 300/day** — satisfies Rule A, Rule C; minor Rule B breach acceptable

   Target: 10+ inboxes per campaign for meaningful volume.
   If no safe inboxes available → request new inbox provisioning. Do NOT steal from active campaigns.

### Step 6F — Verify signatures on assigned inboxes
**Only apply signatures to inboxes that don't already have one.** Run with `--only-missing` flag:

```
python smartlead_update_signatures.py -k $SMARTLEAD_API_KEY --only-missing
```

Signature format: `Full Name<br>Job Title @ Resquared (re2.ai)`

| First name | Title |
|---|---|
| Griffin | CEO & Founder |
| Tyler | Co-founder |
| Jalen | Operations Specialist |
| Leonardo | Manager |
| Paul | Operations Specialist |
| Harold | Outbound Specialist |
| Erik | Operations Specialist |

To add a new person: add their `"firstname": "Title"` entry to `NAME_TO_JOB_TITLE` in `smartlead_update_signatures.py`.

Signature auto-appends to every send. Never add signature variable to sequence body.

### Step 6G — Build custom fields before loading leads

Before uploading leads to SmartLead, pre-render all custom fields in Python/BQ. Follow these rules in order:

**1. Resolve city:**
```python
city = (lead.get("city") or "").strip() or (lead.get("company_city") or "").strip() or "your area"
```

**2. Get business count from BQ and display as friendly number:**
```python
# Query once per unique city, not per lead
sql = """
    SELECT city, COUNT(*) as cnt
    FROM `tenant-recruitin-1575995920662.business_sources.us_companies_list__30m_us_business_std`
    WHERE city IN UNNEST(@cities)
    GROUP BY city
"""
# Then apply rounding:
BREAKPOINTS = [50,100,150,200,250,300,400,500,750,1000,1500,2000,2500,3000,
               5000,7500,10000,15000,20000,25000,30000,50000,75000,100000,
               150000,200000,250000,300000,500000]

def friendly_count(n):
    if not n or n <= 0: return None
    floor_bp = max((b for b in BREAKPOINTS if b <= n), default=None)
    ceil_bp  = min((b for b in BREAKPOINTS if b > n),  default=None)
    if floor_bp is None: return None
    if ceil_bp and n / ceil_bp >= 0.97:
        return f"almost {ceil_bp:,}"
    return f"over {floor_bp:,}"

count_str = friendly_count(city_counts.get(city))  # e.g. "over 30,000" or "almost 1,000"
businesses = f"{count_str} businesses" if count_str else "thousands of businesses"
```

**3. Build Email2 with real city + count baked in (plain text, no links):**
```python
email2 = (
    f"I ran a quick search in {city} myself this morning.\n\n"
    f"Made a list of {businesses} that look like they could use your services.\n\n"
    f"Just reply and I'll send you the data."
)
```

**Then load to SmartLead:**
```
POST /campaigns/{id}/leads
Body:
{
  "lead_list": [
    {
      "email": "contact@domain.com",
      "first_name": "John",
      "last_name": "Smith",
      "company_name": "Smith Insurance Agency",
      "location": "Austin, Texas",
      "custom_fields": {
        "Subject1": "insurance x local restaurants",
        "Subject3": "local restaurant contacts in Austin",
        "Email1": "John\n\nOpening question here.\n\nPitch + CTA.",
        "Email2": "plain text email 2 with \\n line breaks, no HTML, no links",
        "Email3": "plain text email 3 with \\n line breaks, no HTML, no links"
      }
    }
  ],
  "settings": {
    "ignore_global_block_list": false,
    "ignore_unsubscribe_list": false
  }
}
```
⚠️ NEVER use `{{companyName}}` or other camelCase native SmartLead vars -- they don't map reliably.
⚠️ Native vars that DO work: `{{firstName}}`, `{{lastName}}`, `{{email}}`, `{{location}}`
⚠️ **All emails line break conversion at load time:** ALL bodies (Email1, Email2, Email3) stored as
   plain text with `\n`. At load time, convert `\n\n` -> `<br><br>` and remaining `\n` -> `<br>`.
   No email body may contain HTML tags or links in stored form.
⚠️ **Lead update endpoint:** `POST /campaigns/{id}/leads/{lead_id}` with `{"email": "...", "custom_fields": {...}}`.
   Use this to fix custom fields after load (e.g. blank city). Update sequentially with 0.3s delay + retry on 429.
⚠️ **Test leads:** When testing the update endpoint or verifying lead structure, always use a single
   known test lead (e.g. by filtering on a specific email). Never run a bulk update on the full campaign
   just to test — fix the script on one lead first, then apply to the rest.

---

## PHASE 7 — Pre-Launch QA

Run every check before `status: START`.

**Copy QA** (must be completed in Phase 5B before reaching here — 3-pass check done, user signed off)

```
CAMPAIGN SETUP
□ Campaign name follows taxonomy: {Strategy} - {ICP} - {Channel} - {Approach} - {CTA} - {Version}
□ Strategy is PLG or SLG (not "CRE" or "BB" directly in Strategy position)
□ Settings: send_as_plain_text=True, force_plain_text=True, enable_ai_esp_matching=True
□ Settings: track_settings = ["DONT_EMAIL_OPEN", "DONT_LINK_CLICK"]
□ Settings: follow_up_percentage=50, stop_lead_settings=REPLY_TO_AN_EMAIL
□ Schedule: Mon-Fri, 9am-7pm ET, max_new_leads_per_day set (see 3-rule sizing formula)

SEQUENCES
□ 3 sequences loaded with correct delays (day 0, +3, +8 total)
□ Email 1: subject = {{Subject1}}
□ Email 2: subject = EMPTY (threads as reply to Email 1)
□ Email 3: subject = {{Subject3}} (starts a new thread — different angle from Email 1)
□ All 3 sequences use {{Email1}}, {{Email2}}, {{Email3}} in body

INBOXES
□ BQ tables rebuilt before inbox selection (build_all_smartlead_accounts.py)
□ Inboxes: all 4 rules pass — account >14d, warmup >14d, warmup ACTIVE, 0 active campaigns (per BQ)
□ Inboxes: none are in any CRE campaign (verified via BQ campaign_name check)
□ AI categorization: enabled manually in SmartLead OLD interface → AI & Automation tab → SmartLead AI → enable all categories (new UI limits to 5 categories only; API not available)
□ Signatures set on all inboxes
□ Warmup ON on all inboxes (POST /email-accounts/{id}/warmup {"warmup_enabled": true})

LEADS & COPY
□ Leads loaded with all custom fields populated — Subject1, Subject3, Email1, Email2, Email3
  (spot-check 5 leads via GET /campaigns/{id}/leads)
□ ALL email bodies are PLAIN TEXT — zero links, zero HTML tags in any body
□ All bodies stored with \n line breaks (converted to <br> at load time)
□ Phase 5B 3-pass copy check completed and user signed off
```

---

## PHASE 8 — Launch

```
POST /campaigns/{id}/status
Body: {"status": "START"}
```

Log in `SEARCH_LOG.md`:
- Campaign ID
- Number of leads loaded
- Number of contacts remaining in enriched pool (so we can feed more if it works)
- Inboxes assigned and their capacity/day

---

## PHASE 8B — Sync to BigQuery (run after every lead load)

After loading leads into SmartLead, immediately sync to BigQuery so we have a source of truth
that's not on anyone's local machine.

**Route to the correct dataset based on campaign type:**

**PLG campaigns → `PLG_OUTBOUND`:**
```bash
python bq_sync.py contacts \
  --file /tmp/{segment}_enriched.json \
  --segment {segment} \
  --keyword "exact keyword used" \
  --dataset PLG_OUTBOUND

python bq_sync.py enroll \
  --campaign-id {id} \
  --campaign-name "PLG - IT Solutions - Email - DataDriven - Access - v1" \
  --segment {segment} \
  --dataset PLG_OUTBOUND
```
Tables: `PLG_CONTACTS`, `PLG_CAMPAIGN_ENROLLMENTS`

**CRE / BB campaigns → `SLG_OUTBOUND`:**
```bash
python bq_sync.py contacts \
  --file /tmp/{segment}_enriched.json \
  --segment {segment} \
  --dataset SLG_OUTBOUND

python bq_sync.py enroll \
  --campaign-id {id} \
  --campaign-name "SLG - CRE - Email - HyperPersonal - Demo - v1" \
  --segment {segment} \
  --dataset SLG_OUTBOUND
```
Tables: `SLG_CONTACTS`, `SLG_CAMPAIGN_ENROLLMENTS`

**BQ project:** `tenant-recruitin-1575995920662`

**Use for deduplication before new searches:**
```sql
-- Has this email domain been in any of our campaigns?
SELECT DISTINCT smartlead_campaign_name, segment
FROM `tenant-recruitin-1575995920662.PLG_OUTBOUND.PLG_CAMPAIGN_ENROLLMENTS`
WHERE SPLIT(email, '@')[OFFSET(1)] = 'targetdomain.com'

-- Same check for SLG campaigns:
SELECT DISTINCT smartlead_campaign_name, segment
FROM `tenant-recruitin-1575995920662.SLG_OUTBOUND.SLG_CAMPAIGN_ENROLLMENTS`
WHERE SPLIT(email, '@')[OFFSET(1)] = 'targetdomain.com'
```

---

## PHASE 9 — Monitoring

### Daily check (every session start)
1. Inbox health: `GET /email-accounts` → flag any new `blocked_reason` → remove from campaigns immediately
2. Campaign status: all expected campaigns ACTIVE
3. 7-day sends + positive replies via `smartlead_pull.py`
4. 7-day signups via BigQuery:
   ```sql
   SELECT COUNT(*), REGEXP_EXTRACT(pageUrl, r'utm_campaign=([^&]+)') as campaign
   FROM `airbyte_prod.hubspot_form_submissions`
   WHERE TIMESTAMP_MILLIS(submittedAt) >= TIMESTAMP('{7_days_ago}')
     AND (LOWER(pageUrl) LIKE '%/resquared-trial-redirect%' OR LOWER(pageUrl) LIKE '%plg%')
     AND LOWER(COALESCE(JSON_VALUE(values, '$[0].value'), '')) NOT LIKE '%test%'
     AND LOWER(COALESCE(JSON_VALUE(values, '$[0].value'), '')) NOT LIKE '%re2.ai%'
   GROUP BY 2 ORDER BY 1 DESC
   ```
   ⚠️ Always query BigQuery directly — plg_daily.py only queries single-day and may silently zero out.

### When to feed more leads
- Campaign has <50 leads in queue
- Reply rate is positive (≥0.5% positive rate)
- Go back to enriched pool, take next batch, load via Phase 6G

### When to kill a campaign
- 200+ sends with 0 positive replies → reconsider copy or ICP quality
- Inbox bounce rate >5% → remove those inboxes, investigate domain health

### Positive reply definition
```python
POSITIVE_CATEGORIES = {'Interested', 'Meeting Request', 'Meeting Booked', 'Information Request'}
is_positive = r.get('reply_time') and r.get('lead_category') in POSITIVE_CATEGORIES
# reply_time MUST be present — SmartLead pre-classifies all leads, even unreplied ones
```

---

## Quick Reference — API Cheat Sheet

**SmartLead:** `https://server.smartlead.ai/api/v1` | Auth: `?api_key=KEY`
**Apollo:** `https://api.apollo.io/v1` | Auth: `X-Api-Key: KEY` header
**BigQuery project:** `tenant-recruitin-1575995920662` | Dataset: `airbyte_prod`

| What | Endpoint |
|------|---------|
| Create campaign | `POST /campaigns/create` |
| All settings | `POST /campaigns/{id}/settings` |
| Schedule | `POST /campaigns/{id}/schedule` |
| Sequences | `POST /campaigns/{id}/sequences` |
| Assign inboxes | `POST /campaigns/{id}/email-accounts` |
| Remove inboxes | `DELETE /campaigns/{id}/email-accounts` + body |
| Load leads | `POST /campaigns/{id}/leads` |
| Start campaign | `POST /campaigns/{id}/status {"status":"START"}` |
| Stop campaign | `POST /campaigns/{id}/status {"status":"STOP"}` |
| Delete campaign | `DELETE /campaigns/{id}` (must be STOPPED first) |
| All inboxes | `GET /email-accounts?limit=100&offset=N` |
| Campaign leads | `GET /campaigns/{id}/leads?limit=N&offset=N` |
| Sequences | `GET /campaigns/{id}/sequences` |
| 7-day stats | `GET /campaigns/{id}/statistics?sent_time_start_date=...` |
| Set signature | `POST /email-accounts/{id} {"signature": "..."}` |
| Set warmup | `POST /email-accounts/{id}/warmup {"warmup_enabled": true}` |
| Apollo free | `POST /v1/mixed_people/api_search` |
| Apollo enrich | `POST /v1/people/match {"id": "apollo_id"}` |
