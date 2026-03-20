# Resquared PLG Campaign Playbook
## End-to-End Guide — Start to First Send

This document is the single source of truth for building a new PLG campaign from scratch.
Follow every phase in order. Never skip steps. Never launch without completing the checklist.

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
    if 'PLG' not in c['name'].upper(): continue
    if c['status'] not in ('ACTIVE','PAUSED','COMPLETED'): continue
    stats = get_campaign_statistics(c['id'])  # all-time, no date filter
    agg = aggregate_stats(stats)
    if agg['sent'] > 50:  # only campaigns with meaningful volume
        pos_rate = agg['positive'] / agg['sent'] * 100
        print(f"{c['name']}: {pos_rate:.2f}% positive ({agg['positive']}/{agg['sent']})")
```

Positive = `lead_category` in `{'Interested', 'Meeting Request', 'Meeting Booked', 'Information Request'}`
AND `reply_time` is not null. SmartLead pre-classifies all leads even without replies — always check both.

### Decide: PLG or Sales?
- PLG: self-serve buyer, lower ACV, high volume outreach → `landing.re2.ai/resquared-trial-redirect`
- Sales: higher ACV, needs demo, relationship → separate CRE pipeline

**All PLG campaigns MUST have "PLG" in the name. All campaigns WITHOUT "PLG" = CRE. No exceptions.**

**One campaign = one BigQuery table. The sample pull and the full pull go into the SAME table.
Never create a second table for the same campaign — append to the existing one.**

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
- CTAs ranked best to worst:
  - ✅ "Should I send you one?" (winner)
  - ✅ "Want me to send over the results?"
  - ❌ "Want the link?" (sounds phishing-adjacent — and signals there's a link coming, which there isn't)
  - ❌ "Are you the best person to reach out to?" (worst tested — 0.254% positive)

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
- Email 1 stored as plain text with `\n` line breaks. Convert to `<br>` ONLY at SmartLead load time.
- Emails 2 and 3 are HTML (they contain `<a href>` signup links) — store with `<br>` tags directly.

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

### Email 2 — Follow-up (HTML permitted, links OK, day +3)

Emails 2 and 3 CAN be HTML because they contain `<a href>` signup links. Store these with
`<br>` tags directly (not `\n`). This is the opposite of Email 1 which must be pure plain text.

Links are permissible in Email 2 and 3, but treat them as a deliberate choice — not a default. Ask: does this specific sequence benefit from a CTA link, or does it read better without one? A plain-text follow-up can outperform a linked one for certain ICPs. Only include a link if it adds clear value.

**City resolution rule (always apply in this order):**
```
city = COALESCE(NULLIF(TRIM(city),''), NULLIF(TRIM(company_city),''), 'your area')
```
Never leave `{city}` blank — if both `city` and `company_city` are missing, fall back to `"your area"`.

Template (mail-merge, no LLM needed):
```
I ran a quick search in {city} myself this morning.
I made a target list of 200 businesses and their contact email that I think would be
interested in your services before the end of Q1.<br><br>
You can access all the local business data for {city}.<br><br>
<a href="https://landing.re2.ai/resquared-trial-redirect?utm_source=email&utm_medium=smartlead&utm_campaign={campaign_name_slug}&utm_content=email2&email={url_encoded_email}">Access {city} Lead Data</a><br><br>
This is for a free account to try it yourself. Would love your feedback.
```

### Email 3 — Last touch (link permitted, day +8)

Template:
```
Since I'm guessing you're busy, I'll just leave this here so you can check the data
whenever you have a moment.<br><br>
You can access all the local business data for {city}.<br><br>
<a href="https://landing.re2.ai/resquared-trial-redirect?utm_source=email&utm_medium=smartlead&utm_campaign={campaign_name_slug}&utm_content=email3&email={url_encoded_email}">Access {city} Lead Data</a>
```

**UTM format:** `utm_source=email&utm_medium=smartlead&utm_campaign={campaign_name_slug}&utm_content=email2` (or `email3`) `&email={url_encoded_email}`
- `campaign_name_slug`: lowercase, hyphens, e.g. `PLG - Local Marketing - Claude` → `plg-local-marketing-claude`
- `utm_content`: `email2` for Email 2, `email3` for Email 3
- `email`: URL-encoded lead email for HubSpot attribution

### Custom fields for SmartLead leads
All PLG campaigns use 4 custom fields per lead:
- `Subject1` — the email subject (personalized per lead)
- `Email1` — full Email 1 body (**plain text stored with `\n`, converted to `<br>` at load time**)
- `Email2` — full Email 2 body (HTML with `<br>` line breaks, contains signup link)
- `Email3` — full Email 3 body (HTML with `<br>` line breaks, contains signup link)

**CRITICAL:** Email1 must NEVER contain `<a href>`, `<img>`, or any HTML besides `<br>` (added at load time).
This is a universal rule for ALL campaigns (PLG and non-PLG). HTML in Email 1 triggers rendering
issues and spam filters, destroying deliverability. This has ruined campaigns before.

---

## PHASE 6 — SmartLead Campaign Setup

**Full checklist. Do every step. Do not skip.**

### Step 6A — Create campaign
```
POST /campaigns/create
Body: {"name": "PLG - [Segment] - [Variant] - Claude"}
```
Naming rule: must contain "PLG". End with "- Claude" for AI-generated campaigns.

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
    "subject": "",
    "email_body": "<div>{{Email3}}</div>"
  }
]}
```
**Sequence timing:** Day 0 → Day 3 → Day 8 (total 8-day sequence).
- +3 days for Email 2: standard lower-bound, matches "you had time to see it" window.
- +5 days for Email 3: industry best practice is 5-7 days for the final touch (avoids appearing pushy).
- Avoid sequences under 7 days total — compresses into spam-trigger territory.

**Empty subjects on Email 2 & 3:** Leave subject empty so SmartLead sends them as replies in the same thread.
If a subject is set, SmartLead starts a new thread — which breaks the conversation context and looks robotic.
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

2. **Ready inbox criteria** (ALL 4 must be true):
   1. **Account created > 14 days ago:** `TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), TIMESTAMP(created_at), DAY) > 14`
   2. **Warmup started > 14 days ago:** `TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), TIMESTAMP(warmup_created_at), DAY) > 14`
      - If `warmup_created_at` is null, fall back to `created_at`
   3. **No active campaigns:** `COUNTIF(campaign_status = 'ACTIVE') = 0` per BQ join
      - Inboxes in only COMPLETED/PAUSED campaigns are fine — treat as available
   4. **Warmup status is ACTIVE:** `warmup_status = 'ACTIVE'`
      - INACTIVE warmup = do not use, regardless of age or reputation

   Additional health checks (exclude if failing):
   - `is_smtp_success: true` and `is_imap_success: true`
   - `blocked_reason: null`
   - `warmup_reputation ≥ 80%`

   **Canonical BQ query:**
   ```sql
   SELECT
     a.account_id, a.from_email, a.message_per_day, a.warmup_reputation,
     TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), TIMESTAMP(a.created_at), DAY) as account_age_days,
     TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), TIMESTAMP(a.warmup_created_at), DAY) as warmup_age_days,
     COUNTIF(ca.campaign_status = 'ACTIVE') as active_campaigns
   FROM `tenant-recruitin-1575995920662.MARKETSEGMENTDATA.ALL_SMARTLEAD_ACCOUNTS` a
   LEFT JOIN `tenant-recruitin-1575995920662.MARKETSEGMENTDATA.ALL_SMARTLEAD_CAMPAIGN_ACCOUNTS` ca
     ON a.account_id = ca.account_id
   WHERE a.warmup_status = 'ACTIVE'
   GROUP BY 1,2,3,4,5,6
   HAVING active_campaigns = 0 AND account_age_days > 14 AND warmup_age_days > 14
   ORDER BY warmup_age_days DESC, warmup_reputation DESC
   ```

3. **Hard blocks:**
   - ANY inbox in a CRE campaign = absolute no-touch (check `UPPER(campaign_name) NOT LIKE '%PLG%'`)
   - ANY inbox with `blocked_reason` set = dead, remove from all campaigns

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

### Step 6G — Load leads
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
        "Email1": "John<br><br>Opening question here.<br><br>Pitch + CTA.",
        "Email2": "...pre-rendered email 2 body...",
        "Email3": "...pre-rendered email 3 body..."
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
⚠️ **Email1 line break conversion at load time:** stored as plain text with `\n`. At load time,
   convert `\n\n` -> `<br><br>` and remaining `\n` -> `<br>`. Email1 must NEVER contain links or HTML tags.
⚠️ Email2/Email3 are stored with `<br>` tags already (they contain HTML links). Load as-is.
⚠️ **Lead update endpoint:** `POST /campaigns/{id}/leads/{lead_id}` with `{"email": "...", "custom_fields": {...}}`.
   Use this to fix custom fields after load (e.g. blank city). Update sequentially with 0.3s delay + retry on 429.
⚠️ **Test leads:** When testing the update endpoint or verifying lead structure, always use a single
   known test lead (e.g. by filtering on a specific email). Never run a bulk update on the full campaign
   just to test — fix the script on one lead first, then apply to the rest.

---

## PHASE 7 — Pre-Launch QA

Run every check before `status: START`.

```
□ Campaign name contains "PLG"
□ Settings: send_as_plain_text=True, force_plain_text=True, enable_ai_esp_matching=True
□ Settings: track_settings = ["DONT_EMAIL_OPEN", "DONT_LINK_CLICK"]
□ Settings: follow_up_percentage=50, stop_lead_settings=REPLY_TO_AN_EMAIL
□ Schedule: Mon-Fri, 9am-7pm ET, max_new_leads_per_day set (see 3-rule sizing formula)
□ 3 sequences loaded with correct delays (day 0, +3, +8 total)
□ Sequences: Email1 subject = {{Subject1}}, Email2 subject = empty, Email3 subject = empty
□ Sequences use {{Email1}}, {{Email2}}, {{Email3}} in body
□ BQ tables rebuilt before inbox selection (build_all_smartlead_accounts.py)
□ Inboxes: all 4 rules pass — account >14d, warmup >14d, warmup ACTIVE, 0 active campaigns (per BQ)
□ Inboxes: none are in any CRE campaign (verified via BQ campaign_name check)
□ AI categorization: enabled manually in SmartLead OLD interface (not the new UI — new UI limits to 5 categories only; old interface allows all categories) → AI & Automation tab → SmartLead AI → enable all categories ← API not available
□ Leads loaded with all 4 custom fields populated (spot-check 5 leads via GET /campaigns/{id}/leads)
□ Sample Email1 bodies reviewed -- no em dashes, no "I noticed", no AI-sounding openers
□ Email1 bodies are PLAIN TEXT with zero links and zero HTML (only <br> added at load time)
□ Email2/Email3 bodies are HTML with <br> tags and signup links
□ Signatures set on all inboxes
□ Warmup ON on all inboxes (POST /email-accounts/{id}/warmup {"warmup_enabled": true})
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

```bash
# Record contacts pulled from Apollo
python bq_sync.py contacts \
  --file /tmp/{segment}_enriched.json \
  --segment {segment} \
  --keyword "exact keyword used"

# Record SmartLead campaign enrollments
python bq_sync.py enroll \
  --campaign-id {id} \
  --campaign-name "PLG - Segment - Claude" \
  --segment {segment} \
  --variant claude   # or: blunt, more_capacity, etc.
```

**Tables in `PLG_OUTBOUND` dataset (project: `tenant-recruitin-1575995920662`):**
- `PLG_CONTACTS` — every Apollo contact ever pulled, deduped by apollo_id/email
- `PLG_CAMPAIGN_ENROLLMENTS` — every SmartLead enrollment, append-only

**Use for deduplication before new searches:**
```sql
-- Has this email domain been in any of our campaigns?
SELECT DISTINCT smartlead_campaign_name, segment
FROM `tenant-recruitin-1575995920662.PLG_OUTBOUND.PLG_CAMPAIGN_ENROLLMENTS`
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
