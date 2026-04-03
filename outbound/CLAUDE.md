# Resquared Outbound -- Master Context

---

## NOTE FOR GRIFFIN — PLAYBOOK UPDATES (2026-03-20)

Hey Griffin! A bunch of rules were tightened in `CAMPAIGN_PLAYBOOK.md` during the Local Marketing campaign launch. Key things that changed:

1. **Sequence subjects:** Email 2 subject must be **empty** so SmartLead threads it as a reply to Email 1. Email 3 must have its own subject (`{{Subject3}}` — a new trigger/angle) so it starts a fresh thread. This is intentional for Email 3.
2. **Sequence timing:** Now Day 0 → +3 → +5 (total 8 days). Previously was +3/+4.
3. **Settings:** Add `"force_plain_text": true` to the settings call alongside `send_as_plain_text`.
4. **Min time between emails:** 30 minutes (was 10).
5. **Inbox selection — two tiers (BQ is source of truth, not the API):**

   **Tier 1 — "Available"** (inbox is healthy and ready to send):
   - `is_warmup_blocked = FALSE` — INACTIVE warmup_status auto-sets this to TRUE, so those are excluded
   - `warmup_reputation = '100%'` — anything below 100% means "Need warmup", skip
   - `is_smtp_success = TRUE` and `is_imap_success = TRUE` — must be connected
   - `warmup_created_at >= 14 days ago` — under 14 days = "Still warming up", skip
   - `is_blacklisted = FALSE`

   **Tier 2 — "Available for new campaigns"** (Available + not currently assigned):
   - All Tier 1 criteria above, plus:
   - `active_campaigns = 0` — count only ACTIVE status campaigns (not PAUSED) via BQ join; API `campaign_count` is unreliable

   Run `build_all_smartlead_accounts.py` (in `scorecard/re2scorecard2026`) before every inbox selection run — this refreshes `ALL_SMARTLEAD_ACCOUNTS` and `ALL_SMARTLEAD_CAMPAIGN_ACCOUNTS` in BQ. Never rely on a live API scan alone.

   **Reference query:**
   ```sql
   SELECT a.account_id, a.from_email, a.message_per_day,
     DATE_DIFF(CURRENT_DATE(), DATE(a.warmup_created_at), DAY) AS warmup_age_days
   FROM MARKETSEGMENTDATA.ALL_SMARTLEAD_ACCOUNTS a
   LEFT JOIN (
     SELECT account_id, COUNT(*) AS cnt
     FROM MARKETSEGMENTDATA.ALL_SMARTLEAD_CAMPAIGN_ACCOUNTS
     WHERE campaign_status = 'ACTIVE'
     GROUP BY account_id
   ) active ON active.account_id = a.account_id
   WHERE a.is_blacklisted = FALSE
     AND a.is_warmup_blocked = FALSE
     AND a.warmup_reputation IN ('100%', '100')
     AND a.is_smtp_success = TRUE
     AND a.is_imap_success = TRUE
     AND DATE_DIFF(CURRENT_DATE(), DATE(a.warmup_created_at), DAY) >= 14
     AND COALESCE(active.cnt, 0) = 0
   ORDER BY a.from_email
   ```
6. **Daily send sizing — three rules together:**
   - Rule A: daily = 1/5 to 1/4 of total leads
   - Rule B: daily = 1/2 to 3/4 of inbox capacity
   - Rule C: days-to-complete should leave ≤2 days overlap with the Email 1→2 gap
   - Pick the closest round number that wins on balance. See playbook Step 6E for worked example.
7. **Manual UI steps (API cannot set these — do both before launch):**
   - **OOO auto-restart:** Campaign settings → Lead Management → "Automatically restart ai-categorised OOO when lead returns" → ON. Without this, OOO leads sit paused forever and never get follow-ups.
   - **AI categorization:** Must be done in the **old SmartLead UI** (new UI caps at 5 categories). Set all reply categories so SmartLead auto-tags every reply. This powers BQ reporting and positive-reply tracking.
   - Neither setting is verifiable via API — always confirm manually in the UI.
8. **Schedule window:** 9:00–19:00 New York time (was 8:00–18:00).
9. **UTM format updated:** `utm_source=email&utm_medium=smartlead&utm_campaign={slug}&utm_content=email2` (or `email3`) `&email={url_encoded_email}`. Previously used `utm_medium=link&utm_campaign=claude-v1` — do not use that format going forward.
10. **City + business count must be baked in at lead load time (Step 6G):**
    - City: `COALESCE(city, company_city, 'your area')` — never leave blank
    - Business count: query `business_sources.us_companies_list__30m_us_business_std` per city, apply `friendly_count()` rounding → `"over X"` or `"almost X"`. Fallback: `"thousands of businesses"`.
    - Do NOT hardcode a number (e.g. "200 businesses") — always use real data.
    - Full logic + code in `CAMPAIGN_PLAYBOOK.md` Step 6G.
11. **Signatures — only apply if missing:** Run `smartlead_update_signatures.py --only-missing` during campaign launch. Only force-update all when titles change. Title map is in the script itself.
12. **Lead update endpoint exists:** `POST /campaigns/{id}/leads/{lead_id}` with `{"email": "...", "custom_fields": {...}}`. Sequential with 0.3s delay + retry on 429. Always test on one lead first before bulk-updating.
13. **Sequences endpoint replaces the full array — NEVER send a partial update.** `POST /campaigns/{id}/sequences` with a list that omits existing sequences will DELETE them. Always fetch current sequences first and include ALL of them (with their `id` fields) in every POST, even if you're only changing one. Omitting `id` creates a new sequence; including `id` updates existing.

Full details in `CAMPAIGN_PLAYBOOK.md` Step 6B–6G and the QA checklist.

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

## CAMPAIGN ACCESS RULES

Claude can create and manage **PLG, CRE, and BB** campaigns. Rules:

1. **Before creating a CRE or BB (SLG) campaign**, always confirm with the user:
   - "Just to confirm — you want a SLG campaign (CRE/BB), not a PLG one?" Briefly explain the difference if helpful.
   - Encourage PLG if the ICP fits the self-serve model — only proceed with SLG on explicit confirmation.
2. **Confirm the full campaign name** (following the taxonomy model, see below) before calling `POST /campaigns/create`.
3. **Before stopping, pausing, or deleting any campaign**, always confirm with the user first.
4. You may **READ stats** from any campaign at any time for analysis/reporting.
5. You may **NOTIFY the user** if any campaign has issues (blocked inboxes, high bounce rate, etc.).

---

## UNIVERSAL EMAIL RULES (Read This Before Any Campaign Work)

**ALL emails (1, 2, and 3) are ALWAYS plain text. No HTML. No links. No exceptions. PLG and non-PLG alike.**

- All email bodies are stored as plain text with `\n` line breaks. Zero HTML tags in stored copy.
- At SmartLead load time ONLY, convert `\n\n` to `<br><br>` and `\n` to `<br>`.
- NEVER put `<a href>`, `<img>`, `<b>`, `<div>`, or any HTML in any email body. This has ruined campaigns.
- ZERO links in any email. No URLs, no signup links, no tracking links. Nothing.
- **PLG goal:** get the reader to REPLY and ask for the trial link — do NOT send the link directly.
- **CRE/BB goal:** get the reader to REPLY and express interest or book a demo.

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

**SmartLead rule:** All campaign names must follow the taxonomy model — see **CAMPAIGN NAMING TAXONOMY** section below. PLG campaigns contain "PLG" in the Strategy field; SLG campaigns (CRE, BB) contain "SLG".

---

## CAMPAIGN NAMING TAXONOMY (Haroldo's Model)

All campaigns — PLG, CRE, BB — must follow this exact naming format:

```
{Strategy} - {ICP} - {Channel} - {Approach} - {CTA} - {Version}
```

| Component | Valid values |
|-----------|-------------|
| **Strategy** | `PLG`, `SLG` |
| **ICP** | `CRE`, `Business Brokers`, `Insurance`, `IT Solutions`, `Cleaning`, `Signage`, `Catering`, `Merchant Services`, `Security`, ... |
| **Channel** | `Email`, `LinkedIn`, `SMS` |
| **Approach** | `HyperPersonal`, `Trigger`, `ProblemFirst`, `SocialProof`, `DataDriven`, `OneLiner` |
| **CTA** | `Interested`, `Connect`, `Access`, `Demo` |
| **Version** | `v1` (default), `v2`, `v3`, ... — increment for repushes or copy variants |

**Examples:**
- `PLG - IT Solutions - Email - DataDriven - Access - v1`
- `SLG - CRE - Email - HyperPersonal - Demo - v1`
- `SLG - Business Brokers - Email - ProblemFirst - Connect - v1`
- `PLG - Insurance - Email - Trigger - Interested - v2`

### Approach — when to suggest each

| Approach | When to use | Best ICPs |
|----------|-------------|-----------|
| **HyperPersonal** | You have specific prospect data (listing address, company detail, recent event) | CRE, any segment with web enrichment |
| **Trigger** | A time-based or event hook exists (new listing, business opening, lease expiry) | CRE, Signage |
| **ProblemFirst** | ICP has a well-known pain you can name in the subject or opener | Insurance, IT Solutions, BB |
| **SocialProof** | Resquared has specific results to cite for that ICP | Any segment with proven reply rates |
| **DataDriven** | City/business count data is the hook ("over 500 businesses in Austin") | All PLG (BQ count available) |
| **OneLiner** | Re-engagement, large TAM, or audience needing brevity | Any re-push or large-volume segment |

### CTA — when to suggest each

| CTA | Copy style | Best for |
|-----|-----------|----------|
| **Access** | "Just reply and I'll send you access" | PLG only — trial link sent on reply |
| **Demo** | "Open to a quick demo?" | SLG — CRE, BB — sales conversation |
| **Interested** | "Let me know if you're interested" | Soft ask — warming audiences or large TAM |
| **Connect** | "Open to a quick chat?" | BB, LinkedIn-adjacent networking |

**Claude's role on naming:** When starting a new campaign, propose an Approach and CTA based on the ICP, available data, and external references. Explain the reasoning briefly, then let the user confirm or adjust. Do not finalize the campaign name or call `POST /campaigns/create` until the user has approved the full name.

---

## BigQuery — Source of Truth

**BQ is always the most trusted data source. Always prefer it over live API calls.**

BQ data goes through processing the raw API does not: `is_blacklisted` flag, warmup detail enrichment and normalization, proper field typing. Live API fields like `campaign_count` are known to be unreliable and must not be used for decisions.

### Inbox / Account tables (`MARKETSEGMENTDATA`)

| Table | Purpose |
|-------|---------|
| `ALL_SMARTLEAD_ACCOUNTS` | All email accounts with warmup details, blacklist flag |
| `ALL_SMARTLEAD_CAMPAIGN_ACCOUNTS` | Campaign–inbox assignments with campaign status |
| `SMARTLEAD_BLACKLISTED_DOMAINS` | Domains to skip |

Refresh with: `python build_all_smartlead_accounts.py` (in `scorecard/re2scorecard2026`) — run this before any inbox selection query.

### Campaign enrollment tables

| Campaign type | BQ dataset | Tables |
|---------------|-----------|--------|
| PLG | `PLG_OUTBOUND` | `PLG_CONTACTS`, `PLG_CAMPAIGN_ENROLLMENTS` |
| SLG (CRE, BB) | `SLG_OUTBOUND` | `SLG_CONTACTS`, `SLG_CAMPAIGN_ENROLLMENTS` |

Always sync to the correct dataset after loading leads (see Phase 8B in `CAMPAIGN_PLAYBOOK.md`).

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
