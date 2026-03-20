# Resquared Outbound -- Master Context

---

## NOTE FOR GRIFFIN — PLAYBOOK UPDATES (2026-03-20)

Hey Griffin! A bunch of rules were tightened in `CAMPAIGN_PLAYBOOK.md` during the Local Marketing campaign launch. Key things that changed:

1. **Sequence subjects:** Email 2 and Email 3 subjects must be **empty** (not "follow up" / "last note") so SmartLead threads them as replies. If set, it starts a new thread.
2. **Sequence timing:** Now Day 0 → +3 → +5 (total 8 days). Previously was +3/+4.
3. **Settings:** Add `"force_plain_text": true` to the settings call alongside `send_as_plain_text`.
4. **Min time between emails:** 30 minutes (was 10).
5. **Inbox selection — 4 rules (BQ is source of truth, not the API):**
   - Account created > 14 days ago
   - Warmup started > 14 days ago
   - Warmup status = ACTIVE (INACTIVE = skip)
   - 0 active campaigns per BQ join (API `campaign_count` is unreliable)
   - Run `build_all_smartlead_accounts.py` before every inbox selection run
6. **Daily send sizing — three rules together:**
   - Rule A: daily = 1/5 to 1/4 of total leads
   - Rule B: daily = 1/2 to 3/4 of inbox capacity
   - Rule C: days-to-complete should leave ≤2 days overlap with the Email 1→2 gap
   - Pick the closest round number that wins on balance. See playbook Step 6E for worked example.
7. **AI categorization:** Must be done in the **old SmartLead UI** (new UI caps at 5 categories). API doesn't support this.

Full details in `CAMPAIGN_PLAYBOOK.md` Step 6B–6E and the QA checklist.

---

## HOW TO START A SESSION (Read This First)

When a user opens this repo with Claude Code, they may not know the system. Offer two paths:

**Path 1: Step-by-Step (Recommended)**
- Human-in-the-loop. Claude proposes, human confirms at every checkpoint.
- Follow `stepbystep.txt` for the full workflow.
- Best for anyone -- no prior knowledge of the system needed.
- Every intermediate result goes to a BigQuery table for human review before proceeding.

**Path 2: Autopilot**
- For experienced operators who know the pipeline.
- Follow `CAMPAIGN_PLAYBOOK.md` end-to-end with minimal checkpoints.
- Still pause before spending Apollo credits and before launching SmartLead campaigns.

Ask the user which path they prefer, or suggest step-by-step if they seem new.
If the user just says "run a campaign" or gives a segment name, default to step-by-step
and walk them through it.

---

## UNIVERSAL EMAIL RULES (Read This Before Any Campaign Work)

**Email 1 is ALWAYS plain text. No HTML. No links. No exceptions. PLG and non-PLG alike.**

- Email 1 body is stored as plain text with `\n` line breaks. Zero HTML tags in stored copy.
- At SmartLead load time ONLY, convert `\n\n` to `<br><br>` and `\n` to `<br>`.
- NEVER put `<a href>`, `<img>`, `<b>`, `<div>`, or any HTML in Email 1. This has ruined campaigns.
- ZERO links of any kind in Email 1. No URLs, no signup links, no tracking links. Nothing.

**Emails 2 and 3 CAN be HTML** because they contain `<a href>` signup links. Store these with `<br>` tags directly.

This rule is absolute and applies to every campaign, every segment, every variant.

---

## WHAT RESQUARED IS (Read This First, Every Session)

Resquared (re2.ai) is a **local business intelligence and prospecting platform**.

**WE DO NOT SELL TO LOCAL BUSINESSES.**

We sell to companies that **SELL TO local businesses. B2B vendors whose customers are local businesses.**

Examples of buyers:
- Janitorial company → uses Resquared to find restaurants/offices to pitch cleaning contracts
- MSP/IT company → finds new local businesses to offer managed IT services
- Commercial insurance agent → finds local restaurants, retailers, and offices in their area who are likely in the market for commercial coverage
- Payment processor/ISO → finds new retailers/restaurants to sign up for POS/merchant services
- Signage company → finds businesses opening that need storefront signs
- CRE broker → finds retail tenants for their spaces

**NEVER suggest Google Maps scraping to find Resquared's customers. Resquared IS Google Maps data for local businesses. We sell that. Our buyers are B2B companies who live on LinkedIn and Apollo.**

**Ideal client:** A company actively doing cold outreach (cold email, cold calls, door-to-door) to local businesses. Not companies waiting on referrals.

---

## Segment Structure

### Sales Segments (NOT PLG)
- **CRE** — Commercial real estate brokers/landlords (retail focus)
- **Business Brokers** — Buy/sell local businesses

### PLG Segments (self-serve → landing.re2.ai/resquared-trial-redirect)
Low-budget segments stay PLG. High-budget promising segments move to sales.

Active PLG campaigns in SmartLead:
- Janitorial / Cleaning
- IT Solutions (MSP)
- Security
- Event/Corporate Catering
- Commercial Cleaners
- Local Marketing Agencies / Web Design
- Merchant Services
- Signage

**SmartLead rule:** ALL campaigns WITHOUT "PLG" in the name = CRE. No exceptions.

---

## Campaign Playbook

**→ See `CAMPAIGN_PLAYBOOK.md` for the full end-to-end workflow.**
This is the required reading before starting any new campaign. Covers: strategy, Apollo list building, deduplication, TAM tracking, enrichment, LLM copywriting (with prompt guidelines), web enrichment, SmartLead setup checklist, inbox selection, launch, and monitoring.

---

## Apollo API — Confirmed Architecture (Tested)

### Auth
Header: `X-Api-Key: YOUR_KEY` (NOT query param — Apollo deprecated that)

### Step 1: Free Discovery (no credits consumed)
```
POST https://api.apollo.io/v1/mixed_people/api_search
```
Returns per contact (obfuscated, no email):
- `id` — Apollo ID (critical, use this for enrichment)
- `first_name`
- `last_name_obfuscated` (useless)
- `title`
- `has_email` — boolean, 68% true for our insurance segment
- `organization.name` — company name

Rate limits: 50 req/min, 200 req/hour, 600 req/24hr
At 100 per page → can pull ~60K contacts/24hrs at max rate

### Step 2: Full Enrichment (1 credit per contact)
```
POST https://api.apollo.io/v1/people/match
Body: {"id": "<apollo_id>"}
```
Returns everything in one call:
- Full name (first + last)
- Verified email (if Apollo has it — 68% of our segment do)
- Company name
- Company domain/website
- LinkedIn URL
- City, state
- Title

**Confirmed working test result:**
```
Name: Christi Whalen
Email: ctwhalen@zimmerinsure.com  ← verified
Company: Zimmer Insurance Group
Domain: zimmerinsure.com
City: Lincoln, Nebraska
```

### Deprecated Endpoints (do not use)
- `POST /v1/people/search` — deprecated, returns 422
- `POST /v1/mixed_people/search` — deprecated, returns 422
- `POST /v1/mixed_companies/api_search` — 404, doesn't exist

---

## Cost Comparison: Apollo vs Clay

### 1,000 contacts with 100% email coverage:
| Approach | Plan cost | Credits used | Total | Per contact |
|----------|-----------|-------------|-------|-------------|
| Apollo only | $59/mo Basic (2,500 credits included) | 1,000 of 2,500 | **$59** | $0.059 |
| Clay + Prospeo | $149/mo Starter (24K credits) | ~2,000 of 24K | **$149** | $0.149 |

**Apollo is 2.5x cheaper for building tables with emails.**

### Why Apollo wins:
- 1 credit = discovery + full contact + verified email in a single API call
- Clay = 2 separate operations (find person + enrich email) each consuming credits, at markup
- Apollo Basic minimum: $59/mo vs Clay Starter minimum: $149/mo

### Apollo plan costs (confirmed):
- Free: 390 credits/mo
- Basic: $59/mo → 2,500 credits → $0.024/contact
- Professional: $99/mo → 4,000 credits → $0.025/contact
- Credit add-on pricing: **check in Apollo account settings** (determines if we can one-shot 14K table)

### Full 14K insurance table cost:
- At Professional ($99/mo, 4K credits): ~3.5 months → ~$350 total
- Or one-shot with credit add-ons if priced at ~$0.025/credit → ~$350 one-time

---

---

## Segment TAM (segment_data.json)

| Segment | Clay TAM | SmartLead Sent | Positive Replies | Notes |
|---------|----------|---------------|-----------------|-------|
| IT Security (MSP) | 13,105 | 764 | 8 | 12K+ untouched in Clay |
| Catering | 8,334 | 11 | 1 | Barely started |
| Cleaning/Janitorial | 7,740 | 266 | 2 | Mostly exhausted |
| Merchant Services | 10,649 | 171 | 1 | Mostly untouched |
| Insurance ICP | 1,032 | 8 | 0* | *Clay undercounts — Apollo has 14K+ |
| Facilities Services | 2,307 | 14 | 1 | Small |
| Signage | 2,209 | 48 | 1 | Small |

---

## APIs & Keys (all in .env)

| Service | Env var | Notes |
|---------|---------|-------|
| Apollo | `APOLLO_API_KEY` | Use X-Api-Key header, NOT query param |
| SmartLead | `SMARTLEAD_API_KEY` | Query param: ?api_key= |
| HubSpot | `HUBSPOT_ACCESS_TOKEN` | |
| Slack | `slackwebhook` | Notifications |
| Clay | `CLAY` | Outbound enrichment FROM Clay only — no inbound API |
