# Resquared Outbound — Master Context

**→ `CAMPAIGN_PLAYBOOK.md` is the single source of truth for all campaign operations.**
Read it before starting any campaign. Everything below is startup context only.

---

## HOW TO START A SESSION

When a user opens this repo with Claude Code, offer two paths:

**Path 1: Step-by-Step (Recommended)**
- Human-in-the-loop. Claude proposes, human confirms at every checkpoint.
- Follow `stepbystep.txt` for the full workflow.
- Best for anyone — no prior knowledge of the system needed.
- Every intermediate result goes to BigQuery for human review before proceeding.

**Path 2: Autopilot**
- For experienced operators who know the pipeline.
- Follow `CAMPAIGN_PLAYBOOK.md` end-to-end with minimal checkpoints.
- Still pause before spending Apollo credits and before launching SmartLead campaigns.

Ask the user which path they prefer, or suggest step-by-step if they seem new.
If the user just says "run a campaign" or gives a segment name, default to step-by-step.

**Campaign launch trigger:** Any message that implies launching, building, or starting a new campaign —
e.g. "let's launch", "new campaign", "start a campaign", "build a CRE campaign", "we need to reach out to X" —
should immediately kick off the campaign playbook from Phase 0. Do not wait for the user to ask explicitly.

**Always open with a joke** when starting a new campaign session. One short, genuinely funny joke before
anything else. Keep it work-appropriate. Then proceed with Phase 0.

---

## CAMPAIGN ACCESS RULES

Claude can create and manage **PLG, CRE, and BB** campaigns. Rules:

1. **Before creating a CRE or BB (SLG) campaign**, always confirm with the user:
   - "Just to confirm — you want a SLG campaign (CRE/BB), not a PLG one?" Briefly explain the difference if helpful.
   - Encourage PLG if the ICP fits the self-serve model — only proceed with SLG on explicit confirmation.
2. **Confirm the full campaign name** (following the taxonomy model) before calling `POST /campaigns/create`.
3. **Before stopping, pausing, or deleting any campaign**, always confirm with the user first.
4. You may **READ stats** from any campaign at any time for analysis/reporting.
5. You may **NOTIFY the user** if any campaign has issues (blocked inboxes, high bounce rate, etc.).

---

## WHAT RESQUARED IS

Resquared (re2.ai) is a **local business intelligence and prospecting platform**.

**WE DO NOT SELL TO LOCAL BUSINESSES.**

We sell to companies that **SELL TO local businesses. B2B vendors whose customers are local businesses.**

Examples of buyers:
- Janitorial company → uses Resquared to find restaurants/offices to pitch cleaning contracts
- MSP/IT company → finds new local businesses to offer managed IT services
- Commercial insurance agent → finds local restaurants, retailers, and offices
- Payment processor/ISO → finds new retailers/restaurants to sign up for POS/merchant services
- Signage company → finds businesses opening that need storefront signs
- CRE broker → finds retail tenants for their spaces

**NEVER suggest Google Maps scraping to find Resquared's customers. Resquared IS Google Maps data. Our buyers are B2B companies on LinkedIn and Apollo.**

**Ideal client:** A company actively doing cold outreach (cold email, cold calls, door-to-door) to local businesses.

---

## SEGMENT STRUCTURE

### Sales Segments (SLG)
- **CRE** — Commercial real estate brokers/landlords (retail focus)
- **Business Brokers (BB)** — Buy/sell local businesses

### PLG Segments (self-serve → landing.re2.ai/resquared-trial-redirect)

Active PLG campaigns in SmartLead:
- Janitorial / Cleaning
- IT Solutions (MSP)
- Security
- Event/Corporate Catering
- Commercial Cleaners
- Local Marketing Agencies / Web Design
- Merchant Services
- Signage

**All campaign names must follow the taxonomy model — see CAMPAIGN PLAYBOOK Phase 0.**

---

## CAMPAIGN NAMING TAXONOMY

All campaigns must follow this exact format:

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
| **Version** | `v1` (default), `v2`, `v3`, ... |

**Examples:**
- `PLG - IT Solutions - Email - DataDriven - Access - v1`
- `SLG - CRE - Email - HyperPersonal - Demo - v1`
- `SLG - Business Brokers - Email - ProblemFirst - Connect - v1`

When starting a new campaign, propose an Approach and CTA based on the ICP, explain the reasoning, then get user approval before creating the campaign. See playbook for Approach/CTA guidance tables.

---

## COST COMPARISON: Apollo vs Clay

### 1,000 contacts with 100% email coverage:
| Approach | Plan cost | Credits used | Total | Per contact |
|----------|-----------|-------------|-------|-------------|
| Apollo only | $59/mo Basic (2,500 credits included) | 1,000 of 2,500 | **$59** | $0.059 |
| Clay + Prospeo | $149/mo Starter (24K credits) | ~2,000 of 24K | **$149** | $0.149 |

**Apollo is 2.5x cheaper for building tables with emails.**
- 1 credit = discovery + full contact + verified email in a single API call
- Clay = 2 separate operations each consuming credits, at markup

### Apollo plan costs:
- Basic: $59/mo → 2,500 credits → $0.024/contact
- Professional: $99/mo → 4,000 credits → $0.025/contact
- Credit add-on pricing: **check in Apollo account settings**

---

## SEGMENT TAM (segment_data.json)

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

## APIs & KEYS (all in .env)

| Service | Env var | Notes |
|---------|---------|-------|
| Apollo | `APOLLO_API_KEY` | Use `X-Api-Key` header, NOT query param |
| SmartLead | `SMARTLEAD_API_KEY` | Query param: `?api_key=` — **see `SMARTLEAD_API.md` for all endpoints before making any API call** |
| HubSpot | `HUBSPOT_ACCESS_TOKEN` | |
| Slack | `slackwebhook` | Notifications |
| Clay | `CLAY` | Outbound enrichment FROM Clay only — no inbound API |

**Before writing any SmartLead API call:** check `SMARTLEAD_API.md` first. It has all confirmed working endpoints, correct HTTP methods, and request body shapes. Do not guess — several intuitive routes (e.g. `PATCH /campaigns/{id}`) return 404. If you need an endpoint not in that file, fetch https://helpcenter.smartlead.ai/en/articles/125-full-api-documentation and add it to `SMARTLEAD_API.md` before using it.
