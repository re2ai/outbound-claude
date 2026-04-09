# Resquared Campaign Playbook
## End-to-End Guide — PLG, CRE, and BB Campaigns

This document is the single source of truth for building any new campaign from scratch.
Follow every phase in order. Never skip steps. Never launch without completing the checklist.

CRE and BB campaigns skip Apollo phases — see **CRE/BB-SPECIFIC RULES** section for their flow divergences.

---

## MANDATORY RULE — Step-by-Step Execution (All Campaigns)

**Guide the user through every campaign one step at a time. This applies to PLG, CRE, and BB alike.**

At every step:
1. State which step/phase you are on and what it does
2. Show key outputs (contact counts, verification yield, copy samples, etc.)
3. Flag any deviations from playbook defaults
4. Ask: **"Ready to move to [next step/phase]?"** before proceeding

If a step was skipped or done out of order, call it out explicitly:
> "We skipped [step name]. Do you want to go back and run it, or continue without it?"

Do not move to the next step without explicit confirmation from the user.

**Before advancing to any next phase, switching topics, or resuming after a break:**
Also run through this checklist. Do not skip. Do not assume steps were done in a previous session.

```
□ Leads enriched and verified (BillionVerify done, deliverables-only)
□ Copy generated for all leads (no empty Email1/Email2/Email3 fields)
□ 3-pass copy QA completed (Phase 5B) — user signed off
□ Full lead+copy BQ table written (Phase 5C) — user confirmed before proceeding
□ Campaign doc created in Drive and validated by user (Phase 5D)
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
Do not use hardcoded numbers. Pull actual all-time positive reply rates per campaign.

**Segment benchmarks (from 226K emails, April 2026):**
| Segment | Positive rate | Email 1 | Email 2 |
|---|---|---|---|
| CRE | 2.50% | 2.37% | 2.73% |
| BB | 2.40% | 2.83% | 2.16% |
| PLG | 0.37% | 0.54% | 0.28% |

These are the baselines to beat. Any new campaign variant below these rates needs copy revision.
For detailed copy analysis by segment, run: `python analyze_copy_segments.py` (outbound/).

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
CRE leads come from **BigQuery** — `tenant-recruitin-1575995920662.MARKETSEGMENTDATA.CRE_FORECASTING_V1`.
**Skip Phases 1–4 entirely** (no Apollo search, no Apollo enrichment, no dedup against Apollo tables).

### Step CRE-0 — Contact selection from BigQuery

Query only contacts that are eligible for new campaigns. Always run the **sizing query first**, then pull the full list.

#### Sizing query (run first — check table freshness)
```sql
SELECT
  pipeline_stage_for_rule,
  COUNT(*) AS contacts,
  COUNT(DISTINCT domain) AS companies
FROM `tenant-recruitin-1575995920662.MARKETSEGMENTDATA.CRE_FORECASTING_V1`
WHERE earliest_eligible_date <= CURRENT_DATE()
  AND pipeline_stage_for_rule IN ('never_reached', 'smartlead_only', 'positive_reply')
GROUP BY pipeline_stage_for_rule
ORDER BY contacts DESC
```

Also check big CRE override separately:
```sql
SELECT
  can_reenroll,
  COUNT(*) AS contacts,
  COUNT(DISTINCT domain) AS companies
FROM `tenant-recruitin-1575995920662.MARKETSEGMENTDATA.CRE_FORECASTING_V1`
WHERE pipeline_stage_for_rule = 'big_cre_override'
GROUP BY can_reenroll
```

**Table freshness check:** If `earliest_eligible_date` returns significantly more contacts than `can_reenroll = TRUE`, the table is stale. Run `build_cre_forecasting_table_v2.py` to rebuild before pulling the final list. `can_reenroll` is a pre-computed snapshot — `earliest_eligible_date <= CURRENT_DATE()` is always the authoritative gate.

#### Contact pull query
```sql
SELECT
  email,
  first_name,
  last_name,
  domain,
  company_name,
  pipeline_stage_for_rule,
  days_since_last_contact,
  earliest_eligible_date
FROM `tenant-recruitin-1575995920662.MARKETSEGMENTDATA.CRE_FORECASTING_V1`
WHERE earliest_eligible_date <= CURRENT_DATE()
  AND pipeline_stage_for_rule IN ('never_reached', 'smartlead_only', 'positive_reply',
                                   'big_cre_override')
ORDER BY domain, days_since_last_contact DESC
```

**Stage rules — what's in scope for new campaigns:**
| Stage | Cooldown | Include? |
|---|---|---|
| `never_reached` | Always eligible | Yes |
| `smartlead_only` | 60 days since last contact | Yes |
| `positive_reply` | 60 days since last reply/contact | Yes |
| `big_cre_override` | 30 days (jll.com, cbre.com, colliers.com, etc.) | Yes — include in pull, consider separate campaign |
| `has_deal` / `demo` / `proposal` / `verbal_commit` | — | **Never** |
| `closed_won` | — | **Never** |
| `churned` | 180 days | **Never in new campaigns** |

**Big CRE override note:** These 13 large brokerages (jll, cbre, colliers, etc.) have hundreds of contacts each and a 30-day cooldown. They can be included in the main campaign or run as a separate campaign depending on volume. Always flag the count to the user before including them.

**One contact per company (default):**
- After the query, deduplicate to **1 contact per domain**. Pick the contact with the highest `days_since_last_contact` (longest rested). If it's `never_reached`, pick any.
- Only include a second contact per domain if the campaign needs more volume and the first pass leaves you short. Never enroll 3+ from the same domain unless explicitly requested.

**Bi-weekly cadence — standard operating model for CRE:**
Every two weeks, pull a fresh batch of ~5,400 contacts and split into two campaigns:
- **Campaign A** — 2,700 contacts, enroll Sunday night → Email 1 lands Monday
- **Campaign B** — 2,700 contacts, enroll the following Sunday night → Email 1 lands the next Monday

Name them accordingly:
- `SLG - CRE - Email - {Approach} - {CTA} - v{N}a` (Week 1)
- `SLG - CRE - Email - {Approach} - {CTA} - v{N}b` (Week 2)

When starting a new CRE campaign, always ask the user:
> "Is this a new bi-weekly batch? If so, I'll split the ~5,400 contacts into two 2,700-contact campaigns
> (Week 1 and Week 2). Should I proceed with that split?"

If the batch is smaller than expected after verification/dedup, split evenly and flag the yield shortfall.

Save output to `/tmp/cre_{date}_bq_raw.json`.
After splitting, save as `/tmp/cre_{date}_A_bq_raw.json` and `/tmp/cre_{date}_B_bq_raw.json`.

### Step CRE-1 — Email deliverability check (BillionVerify)
Run BillionVerify even though these emails came from SmartLead/HubSpot — emails go stale.
```bash
python verify_emails.py --file /tmp/cre_{date}_bq_raw.json --out /tmp/cre_{date}_verified.json
```
Remove undeliverable contacts. Proceed with verified contacts only.

### Step CRE-2 — Listing enrichment (default ON — always encourage user to run this)
Before generating copy, ask the user:
> "Do you want me to update the listings for each broker? This pulls their current active listings from
> LoopNet/Crexi and uses them to personalize the copy. It usually improves reply rate significantly —
> I'd recommend it."

**Default: run unless user explicitly says no.**

```bash
python listing_enrich.py --file /tmp/cre_{date}_verified.json --out /tmp/cre_{date}_enriched.json
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
- Email 3: new subject/trigger, brief last touch (see Email 3 warning in Phase 5)

---

### CRE TIMING & SEASONAL GUIDANCE

> **Note:** Weekly cadence guidance is consistent with general B2B outreach research. Seasonal windows
> align with known CRE retail leasing cycles. Neither has been validated against our own send data yet —
> treat as directional, not benchmarks. Worth A/B testing when volume allows.

#### Weekly cadence — enroll so Email 1 lands Monday or Tuesday

CRE brokers follow a predictable weekly rhythm:

| Day(s) | Broker Mode | Use for |
|---|---|---|
| Mon–Tue (8–10am NY) | Reviewing pipeline, planning week | **Email 1** — best window |
| Wednesday | Operational focus | Acceptable but not ideal for Email 1 |
| Thu–Fri | Week-closing mode | **Email 2** lands here naturally (3-day gap) |

**Practical rule:** Enroll new contacts Sunday night or Monday morning so Email 1 hits Monday/Tuesday.
Email 2 (Day +3) then lands Thursday/Friday — fine for a follow-up, not ideal for a first impression.
This costs nothing — it's just enrollment scheduling.

#### Seasonal windows — check the calendar before launching

Always check the current month before building a CRE campaign. Adjust copy framing accordingly:

| Period | CRE Cycle | Outreach Strategy | Copy angle |
|---|---|---|---|
| **Jan–Mar** | Q1 pipeline build | Good window — brokers setting H1 targets | "Q1 leasing" framing |
| **Apr–Jun** | Peak retail leasing season (H2 openings) | **Best window of the year** | Urgency around H2 tenant placement |
| **Jul** | Pre-summer slowdown | Compensate with volume, not frequency | Keep it brief, lower expectations |
| **Aug–Sep** | Q3 ramp-up | Second best window | "Back from summer" energy — fresh pipeline |
| **Oct–Nov** | Q4 push / year-end deals | Moderate — focus on quick wins | Year-end urgency framing |
| **Dec** | Holiday slowdown | Avoid or very low volume | Hold for January |

**How to use this in copy:**
- Apr–Jun: "Are you filling any spaces for H2 openings?" or "Q2 is usually when tenants start moving — are you sourcing for any retail space?"
- Aug–Sep: "Coming off summer — are you actively leasing any retail right now?"
- Jan–Mar: "Starting Q1 outreach — are you working on any retail spaces this quarter?"
- Jul / Dec: No seasonal hook — use the standard generic inquiry format (e.g. `"retail tenant question"`)

Do NOT use seasonal framing if it sounds forced. The generic inquiry subject lines are proven at scale
and are always the safe fallback.

---

### CRE COPY INTELLIGENCE (data-backed, 229K emails analyzed)

**What the numbers show:**
- Best CRE Email 1: **2.37% positive rate** (69K sent)
- Best CRE Email 2: **2.73% positive rate** (64K sent) — Email 2 outperforms Email 1 for CRE
- Email 3: **0.09% positive rate** across all segments — effectively dead weight

#### CRE — Subject Lines That Win

Rank subjects by positive reply rate from 137K CRE emails sent:

| Subject format | + Rate | Example |
|---|---|---|
| `retail leasing question` | 11.11% | exact phrase |
| `retail tenant question` | 6.99% | exact phrase |
| `retail tenant inquiry` | 6.40% | exact phrase |
| `tenant fit for [property_type]?` | 5.66% | "tenant fit for retail?" |
| `office tenant inquiry` | 4.40% | exact phrase |
| `tenant for this office?` | 4.12% | exact phrase |
| `office space available?` | 3.75% | exact phrase |
| `leasing this office?` | 3.51% | exact phrase |
| `your listing at [ADDRESS]` | ~2-4% | HyperPersonal, address-specific |

**Rule:** Subject must reference an ASSET the broker owns (their listing/space), not what we sell.
Do NOT use: `"commercial real estate x local businesses"`, `"tenant sourcing services"`, etc.

For HyperPersonal campaigns (listing enrichment done): `"your listing at [ADDRESS]"` is the gold standard.
For non-enriched campaigns: use the generic inquiry format — `"retail tenant question"` is proven at scale.

#### CRE — Email 1 Winning Structure

**Best performing template (12.5% on small n, 5-7% at scale):**
```
Hi [Name],

What type of retail tenant did you have in mind for [ADDRESS]?

We have [N] retail tenants in [City] looking for space — happy to share the list if it's useful.

[Sender]
```

**Standard HyperPersonal template (2-4% positive at scale):**
```
Hey [Name],

For the space available at [ADDRESS], were you open to a [tenant type]?

We have contact info for over [N] [tenant type] operators in [City] and 15M local biz across the US.

Not sure what use you had in mind! Let me know what type of use you are targeting and I can share more info!

[Sender]
```

**Why it works:**
- Opens with THEIR listing address — not what we sell
- One question about their current need (not a product pitch)
- One data point proving we can actually help
- Soft CTA — "let me know" / no pressure
- 4-5 lines, zero fluff, zero buzzwords

**What to avoid:**
- ❌ Any sentence describing the platform ("We built a tool that...")
- ❌ "AI-powered" / "automated" / "platform" language
- ❌ Urgency pressure ("limited spots", "this month only")

#### CRE — Email 2 Winning Structure

**Dominant winner (4.56–4.87% positive across hundreds of sends):**
```
Hi [Name],

Just following up on [ADDRESS], [City, State].

Is it still available?

Are you looking for a national or local tenant? If you are looking for a local operator let me know and I can share more.

[Sender]
```

**Why it works:**
- Zero pitch — just a status question on their listing
- "Is it still available?" is the most natural question a real tenant rep would ask
- Opens a conversation rather than repeating the offer
- Ultra-short — 4 lines

**Avoid for CRE Email 2:**
- ❌ Introducing a new value angle ("Did you know we also have...")
- ❌ Generic follow-up language ("Just circling back", "Wanted to touch base")
- ❌ Restating the platform pitch from Email 1

---

### BB COPY INTELLIGENCE (data-backed, 16K emails analyzed)

**What the numbers show:**
- BB Email 1: **2.83% positive rate** (8,388 sent)
- BB Email 2: **2.16% positive rate** (6,727 sent)
- Niche business-type subjects outperform generic 4x (small samples but consistent signal)

#### BB — Subject Lines That Win

| Subject format | + Rate | Notes |
|---|---|---|
| `you help sell car wash?` | 13.33% | niche — small n |
| `you help sell cafes?` | 13.33% | niche — small n |
| `you help sell hvac?` | 12.50% | niche — small n |
| `you help sell flooring?` | 11.11% | niche — small n |
| `you sell Construction businesses?` | 10.53% | niche variant |
| `you help sell roofing?` | 5.41% | growing sample |
| `you help sell pizzerias?` | 4.76% | solid volume |
| `Connecting with business owners exploring a sale` | 5.00% | **underused — only 40 sends, scale this** |
| `you help sell businesses?` | 3.21% | generic but 1,370 sends = high volume |

**Rule:** Use the specific business type (`car wash`, `cafe`, `flooring`) whenever the list is segmented by type.
`"you help sell businesses?"` is the fallback for unsegmented lists — still decent at 3.21%.
`"Connecting with business owners exploring a sale"` at 5.00% is massively underused — prioritize scaling this.

#### BB — Email 1 Winning Structure

**Top performer (proven across positive replies):**
```
[Name], we have [business type] business owners in [City] who may be exploring a sale.

Would you be interested in connecting with them? Let me know.

[Sender]
```

**HyperPersonal variant (when you have their listing from BizBuySell/Focal5):**
```
[Name], noticed your listing for a [business type] on [source].

We have a platform that connects you with [business type] business owners in [City] who may be exploring a sale.

Would you be interested in connecting with them? Let me know.

[Sender]
```

**Why it works:**
- Zero product description — pure value proposition in one line
- References a specific business type and city they operate in
- Single low-friction ask: "Would you be interested?"
- Reads like a real business referral, not a SaaS pitch

#### BB — Email 2 Winning Structure

**Dominant winner (2.03% positive across 4,630 sends):**
```
[Name], reached out a few days ago about [business type] owners in [City] who may be exploring a sale.

Would you be interested in connecting with them? Let me know.

[Sender]
```

Pure callback. Same offer, same frame, no new pitch. This is intentional — consistency outperforms novelty for BB Email 2.

---

### PLG COPY INTELLIGENCE (data-backed, 229K emails analyzed)

**Benchmarks:**
- PLG Email 1: **0.54% positive rate** (vs CRE 2.37%, BB 2.71%) — ~5x gap driven by framing, not just volume
- PLG Email 2: **0.28% positive rate** — follow-up barely moves the needle with current copy
- Email 3: **0.09% positive rate** — effectively dead weight across all segments (see Email 3 warning)

**Root cause of PLG underperformance vs CRE/BB:**
CRE/BB subjects reference THE PROSPECT'S ASSET (their listing, their niche). PLG subjects previously referenced OUR PRODUCT ("managed IT x local offices"). CRE/BB opens with a concrete real-world hook. PLG opened with a platform description. The fix: make PLG copy feel like CRE/BB — reference the prospect's market, frame the data as something they can test live, and let the reply → free trial flow do the closing.

**Key copy rules for PLG (all segments):**

1. **Subject line = question about their market, not a label for our product**
   - Before: `"managed IT x local offices"` (product framing)
   - After: `"do you serve offices in Austin?"` (prospect's market framing)
   - The question subject drives curiosity the same way CRE's asset-reference does

2. **Remove ALL product description language from Email 1**
   - ❌ `"We built an app that uses AI to find [label] companies leads and use AI to email them."`
   - ❌ Any sentence that explains what Resquared is before they ask
   - ✅ Let them discover the platform when they get the trial link — not before

3. **Use EXACT business counts (not rounded)**
   - ❌ `"about 1,000 restaurants"` — sounds estimated, generic
   - ✅ `"1,847 restaurants"` — reads as real data they can verify
   - Source: `business_sources.us_companies_list__30m_us_business_std` per city (baked in at lead load time)
   - Fallback if count unavailable: omit count phrase rather than guess

4. **CTA = test for free, not "want the list?"**
   - ❌ `"Want the list?"` — sounds like a data broker selling a CSV
   - ❌ `"Do you want me to set up a free account?"` — passive, SaaS-y
   - ✅ `"Free to test how you can reach them? Reply and I'll send you access to test it for free -- no card needed."`
   - ✅ `"Free to check how you can reach them? Reply and I'll send you access to test it for free -- no card needed."`
   - The "test for free / check for free" framing directly connects: reply → get link → test live → no risk

---

#### PLG Email 1 Templates by Segment

**HYPER_PERSONAL framing** — IT/MSP, Catering
*(Use when web_enrich.py found a specific client type they serve.)*

```
Hi {first_name},

I see {company} does {service} for {smb_type} in {city}.

There are {smb_count} {smb_type} in {city} you could be reaching right now.

Free to test how you can reach them? Reply and I'll send you access to test it for free -- no card needed.
```

Subject: `"do you serve {smb_type} in {city}?"`

**RECURRENT framing** — Commercial Cleaning, Signage, Merchant Services, HVAC
*(Frame demand as constant and ongoing. NOT "new openings" or "new businesses"
-- prospects should feel there are always businesses needing their services, not
that leads will dry up once new-opening activity slows down.)*

```
Hi {first_name},

Do you do {service} for {smb_type} in {city}?

There are {smb_count} {smb_type} in {city} that always need services like yours.

Free to check how you can reach them? Reply and I'll send you access to test it for free -- no card needed.
```

Subject examples:
- Cleaning: `"do you clean restaurants in Austin?"`
- Signage: `"do you do signage for businesses in Dallas?"`
- Merchant: `"do you serve restaurants in Chicago?"`
- HVAC: `"do you do HVAC for commercial buildings in Denver?"`

**Why "always" matters for recurrent segments:**
HVAC, cleaning, signage, and merchant services have CONTINUOUS demand -- existing businesses need HVAC maintenance, cleaning contracts, new signs, and payment processing all the time. Framing around "new openings" implicitly caps the TAM to businesses that opened recently. "There are always X businesses that need your services" is both more accurate and more motivating.

---

#### PLG Email 2 Winning Structure

Email 2 is plain text, no links. Goal: reinforce city data, remind about free trial, get a reply.

```
I ran a quick search in {city} this morning.

There are {smb_count} {smb_type} in {city} that look like they could use your services.

Just reply and I'll send you access to test it for free -- no card needed.
```

Keep it short. No new pitch. The "access link" mention + "no card needed" is the only CTA needed.

---

#### PLG Subject Line Guidance

| Segment | Preferred subject format | Example |
|---------|-------------------------|---------|
| IT/MSP | `"do you serve {smb_type} in {city}?"` | `"do you serve offices in Austin?"` |
| Catering | `"do you cater for {smb_type} in {city}?"` | `"do you cater for tech companies in SF?"` |
| Cleaning | `"do you clean {smb_type} in {city}?"` | `"do you clean restaurants in Chicago?"` |
| Signage | `"do you do signage for businesses in {city}?"` | `"do you do signage for businesses in Dallas?"` |
| Merchant | `"do you serve {smb_type} in {city}?"` | `"do you serve restaurants in Miami?"` |
| HVAC | `"do you do HVAC for {smb_type} in {city}?"` | `"do you do HVAC for commercial buildings in Denver?"` |

**What these subject lines do (same mechanic as CRE's asset-reference subjects):**
- They reference THE PROSPECT'S MARKET, not our product
- The question format creates an open loop — the answer is obvious ("yes") which primes engagement
- City inclusion adds specificity that generic subjects lack

---

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
  - ✅ "Reply and I'll send you access to test it for free -- no card needed." (current template)
  - ✅ "Should I send you one?" (tested winner in earlier campaigns)
  - ❌ "Want the list?" (sounds like a data broker selling a CSV)
  - ❌ "Want the link?" (sounds phishing-adjacent)
  - ❌ "Are you the best person to reach out to?" (worst tested — 0.254% positive)

**CRE CTAs** — goal is to get them to tell you what tenant type they want:
  - ✅ "Let me know what type of use you are targeting and I can share more info!"
  - ✅ "Are you looking for a national or local tenant? If local, let me know."
  - ✅ "Not sure what use you had in mind — let me know if you are looking local."
  - ❌ "Open to a quick demo?" (too transactional for CRE — they want tenants, not a demo)
  - ❌ Hard sells, urgency pressure, or forced scheduling links

**BB CTAs** — goal is a simple yes/no on connecting with sellers:
  - ✅ "Would you be interested in connecting with them? Let me know."
  - ✅ "Let me know if this is something you'd want to explore."
  - ❌ Long pitches, product descriptions, or platform language

**Subject line format by segment:**

*CRE:* Reference the broker's asset — their listing or property type.
  - ✅ `"retail tenant question"` → 6.99% positive at scale
  - ✅ `"retail leasing question"` → 11.11% positive
  - ✅ `"your listing at [ADDRESS]"` → HyperPersonal, address-specific (2-4%)
  - ✅ `"office space available?"` → 3.75% positive
  - ❌ `"commercial real estate x local businesses"` → product-framing, not asset-framing
  - No generic "[service] x local businesses" format for CRE

*BB:* Name the specific business type they sell.
  - ✅ `"you help sell [business type]?"` → 5-13% for niche types
  - ✅ `"Connecting with business owners exploring a sale"` → 5.00%, underused
  - ✅ `"you help sell businesses?"` → 3.21% fallback for unsegmented lists
  - ❌ Generic subject lines that don't reference the business type

*PLG:* See Phase 5 PLG subject line guidance below.

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

**CRE approach** — reference their specific listing, ask a status question (proven 4.56–4.87% positive):
```
Hi {first_name},

Just following up on {listing_address}, {listing_city_state}.

Is it still available?

Are you looking for a national or local tenant? If you are looking for a local operator let me know and I can share more.

{sender_name}
{sender_title} @ Resquared (re2.ai)
```

Do NOT restate the pitch. Do NOT introduce a new angle. A simple status question on their listing
outperforms every other CRE Email 2 approach. Email 2 outperforms Email 1 for CRE (2.73% vs 2.37%).

**BB approach** — pure callback, same offer, same frame (proven 2.03% positive across 4,630 sends):
```
{first_name}, reached out a few days ago about {business_type} owners in {city} who may be exploring a sale.

Would you be interested in connecting with them? Let me know.

{sender_name}
{sender_title} @ Resquared (re2.ai)
```

Do NOT introduce new content. Consistency beats novelty for BB Email 2.

Do NOT use stale time phrases ("before the end of Q1", "before the holidays"). Keep it timeless.

**City resolution rule (always apply in this order):**
```
city = COALESCE(NULLIF(TRIM(city),''), NULLIF(TRIM(company_city),''), 'your area')
```
Never leave `{city}` blank — if both `city` and `company_city` are missing, fall back to `"your area"`.

**Business count rule — use the EXACT count from BQ:**
- Query `business_sources.us_companies_list__30m_us_business_std` for `COUNT(*) WHERE city = '{city}'`
- Store the raw integer as `smb_count` on the contact. Do NOT round or apply `friendly_count()`.
- The exact number (e.g. `1,847`) reads as real data and is more credible than rounded estimates.
- If city has no match in BQ → **omit the count line entirely**. Do not substitute any placeholder ("thousands of businesses", "hundreds of businesses", etc.).

Template (mail-merge, no LLM needed — plain text, \n line breaks):
```
I ran a quick search in {city} this morning.

There are {smb_count} {smb_type} in {city} that look like they could use your services.

Just reply and I'll send you access to test it for free -- no card needed.
```
If `smb_count` is not available for this city, omit the count line — do not substitute a placeholder.

### Email 3 — Last touch (plain text, no links, day +8)

> ⚠️ **DATA WARNING — Email 3 returns 0.09% positive rate across 13,944 sends (13 total positive replies).
> This is statistically dead weight. Strongly consider running 2-email sequences only.
> Only include Email 3 if the user explicitly requests it, and note the yield is near zero.**

Email 3 is plain text, stored with `\n` line breaks. No HTML, no links.

**Sequence threading:** Email 3 HAS its own subject line — a new angle/trigger. This starts a fresh thread (not a reply to Email 1), making it feel like a separate outreach rather than a third follow-up. Pick a subject that's different from Email 1's angle.

**Subject line:** Different trigger from Email 1. Examples:
- Email 1: `"do you clean restaurants in {city}?"` → Email 3: `"local restaurant contacts in {city}"`
- Email 1: `"do you serve offices in {city}?"` → Email 3: `"MSP leads in {city}"`
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

## PHASE 5C — Save Full Lead+Copy Table to BigQuery (MANDATORY — Before Drive Doc)

**This step is required before creating the campaign doc and before touching SmartLead.**
The BQ table is the source of truth for every campaign. It must exist so the user can query and validate copy before anything goes live.

### Table naming
```
{segment_slug}_{YYYYMMDD}_v{n}
```
Examples: `pest_control_20260408_v1`, `pest_control_clay_20260408_v1`, `hvac_20260403_v1`

For Clay-sourced campaigns, append `_clay` to the segment slug: `pest_control_clay_20260408_v1`
For Apollo-sourced campaigns: `pest_control_20260408_v1`

Dataset: `PLG_OUTBOUND` for PLG campaigns, `SLG_OUTBOUND` for CRE/BB.

### Required schema (minimum — add extra fields if you have them)
```
apollo_id           STRING    — Apollo person ID (null for Clay contacts)
first_name          STRING
last_name           STRING
email               STRING
title               STRING
city                STRING    — raw city from source
state               STRING
linkedin_url        STRING
company_name        STRING
company_domain      STRING
segment             STRING    — e.g. pest_control, hvac, catering
source              STRING    — apollo | clay | list
campaign_name       STRING    — full SmartLead campaign name
smartlead_campaign_id INT64   — null until campaign is created; update after Step 6A
city_resolved       STRING    — city used in copy (fallback: 'your area')
smb_count           INT64     — BQ business count used in copy (null = fallback used)
email_verified      BOOL      — BillionVerify is_deliverable
verification_status STRING    — BillionVerify status field
ab_variant          INT64     — 0, 1, or 2 (inferred from Email1 opener)
subject1            STRING
subject3            STRING
email1              STRING    — plain text, \n line breaks (NOT converted to <br> here)
email2              STRING
email3              STRING
enrolled_at         TIMESTAMP — set when leads are loaded to SmartLead
created_at          TIMESTAMP — set when this row is written
```

### How to write it
```python
from google.cloud import bigquery
bq = bigquery.Client(project='tenant-recruitin-1575995920662')
TABLE = 'tenant-recruitin-1575995920662.PLG_OUTBOUND.{table_name}'
# Create table with schema, then:
job = bq.load_table_from_json(rows, TABLE,
    job_config=bigquery.LoadJobConfig(schema=SCHEMA, write_disposition='WRITE_TRUNCATE'))
job.result()
```

### After writing
Tell the user:
> "BQ table `{table_name}` is ready in PLG_OUTBOUND — {N} rows. You can query it to validate copy before I set up SmartLead."

**Do not proceed to Phase 5C (Drive doc) or Phase 6 until user confirms.**

⚠️ **If `smartlead_campaign_id` is not yet known** (campaign not created yet): write the table with `NULL` for that field, then run an UPDATE after Step 6A:
```sql
UPDATE `tenant-recruitin-1575995920662.PLG_OUTBOUND.{table_name}`
SET smartlead_campaign_id = {id}
WHERE smartlead_campaign_id IS NULL
```

---

## PHASE 5D — Campaign Document (Create After BQ Table Is Confirmed)

**Trigger:** BQ table written, user has confirmed it looks correct.
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

Email 2 — plain text, no links
Subject: same thread (no new subject)
{body}

Email 3 — plain text, no links
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

1. **Use BigQuery as source of truth** — rebuild BQ accounts data before inbox selection if EITHER condition is true:
   - A campaign was launched since the last BQ refresh, OR
   - The last BQ refresh was more than 1 day ago

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

4. **Inbox diversity — apply after filtering, before finalizing the selection:**
   - **Spread across domains:** avoid picking multiple inboxes from the same domain (e.g. 3× `@domain.com`). Prefer one inbox per domain; only use a second from the same domain if the pool is too small.
   - **Spread across usernames:** avoid patterns that look like a bulk sender (e.g. `email1@`, `email2@`, `email3@`). Prefer inboxes with real first/last name usernames.
   - If the eligible pool is too uniform (same domain or robotic usernames), flag it to the user before assigning — do not silently use a bad set.

5. **Assign:**
   ```
   POST /campaigns/{id}/email-accounts
   Body: {"email_account_ids": [id1, id2, ...]}
   ```

6. **Inbox count + daily rate sizing — three rules, pick the closest round number that wins on balance:**

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
   After sizing, re-check diversity (rule 4): if hitting the inbox count requires reusing domains or robotic usernames, flag to user rather than silently degrading quality.

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
# Use exact count -- do NOT round. Omit count line if city has no BQ match.
smb_count = city_counts.get(city)  # raw integer or None
```

**3. Build Email2 with real city + count baked in (plain text, no links):**
```python
count_line = (
    f"There are {smb_count} {smb_type} in {city} that look like they could use your services.\n\n"
    if smb_count else ""
)
email2 = (
    f"I ran a quick search in {city} this morning.\n\n"
    f"{count_line}"
    f"Just reply and I'll send you access to test it for free -- no card needed."
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
        "Subject1": "do you write commercial insurance in Austin?",
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
