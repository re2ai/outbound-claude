# PLG Outbound Orchestration

Claude-powered system for running Resquared's PLG outbound campaigns end-to-end -- from building Apollo contact lists to loading leads into SmartLead and tracking everything in BigQuery.

Built to be handed off. Any teammate with credentials and Claude Code can run a correct campaign start to finish.

---

## Two Ways to Run This

When you start a session with Claude Code in this repo, tell it what you want to do. It will suggest one of two paths:

### Path 1: Step-by-Step (Recommended)

Human-in-the-loop approach. Claude proposes, you confirm at every checkpoint. Best for anyone running campaigns -- you don't need to know the system inside out.

```
You: "I want to run a new PLG campaign targeting janitorial companies"
Claude: reads stepbystep.txt, walks you through each step, asks for approval before spending credits
```

**How it works:**
1. Claude proposes a strategy (segment, keywords, search approach, copy angle)
2. You approve or adjust
3. Claude pulls a 20-50 contact sample into BigQuery -- you eyeball it
4. Claude verifies emails, generates copy -- you review in BQ console
5. You approve, Claude scales to 1,000+ contacts
6. Claude sets up SmartLead campaign, you confirm launch

Every intermediate result lands in a BigQuery table so you can inspect it. Nothing happens without your sign-off at each checkpoint.

**Start here:** Read `stepbystep.txt` for the full workflow.

### Path 2: Autopilot

For experienced operators who know the system. Claude runs the full pipeline with minimal checkpoints.

```
You: "Run autopilot for local marketing agencies, 1K list, use the proven copy template"
Claude: executes the full CAMPAIGN_PLAYBOOK.md end-to-end, checks in at major milestones
```

This follows `outbound/CAMPAIGN_PLAYBOOK.md` which has every phase documented. Claude will still pause before spending Apollo credits and before launching a SmartLead campaign, but won't ask for approval on intermediate steps.

**Only use this if** you've run at least one step-by-step campaign and understand the pipeline.

---

## Setup

### 1. Install dependencies

```bash
pip install -r outbound/requirements.txt
```

### 2. Create `.env` file

Create `.env` in the project root with all credentials:

```env
# Apollo -- list building and contact enrichment
APOLLO_API_KEY=your_key_here
# Get from: apollo.io -> Settings -> API Keys

# SmartLead -- campaign management
SMARTLEAD_API_KEY=your_key_here
# Get from: smartlead.ai -> Settings -> API

# OpenAI -- LLM copywriting (gpt-4.1-mini for bulk generation)
OPENAI_API_KEY=your_key_here
# Get from: platform.openai.com -> API Keys

# HubSpot -- signup tracking and dedup
HUBSPOT_ACCESS_TOKEN=your_token_here
# Get from: HubSpot -> Settings -> Integrations -> Private Apps

# BillionVerify -- email verification (REQUIRED before loading any leads)
BILLIONVERIFY_API_KEY=your_key_here
# Get from: eng team -- billionverify.com
# Top up credits at billionverify.com before running

# Slack -- notifications (optional)
slackwebhook=https://hooks.slack.com/services/...
```

### 3. Authenticate Google Cloud (BigQuery)

```bash
gcloud auth application-default login
```

You need read/write access to the `PLG_OUTBOUND` dataset in project `tenant-recruitin-1575995920662`. Ask an admin to grant `roles/bigquery.dataEditor` on that dataset.

---

## Key Files

| File | Purpose |
|------|---------|
| `stepbystep.txt` | **Start here.** Human-in-the-loop workflow with BigQuery checkpoints |
| `outbound/CAMPAIGN_PLAYBOOK.md` | Full autopilot reference -- every phase documented |
| `outbound/CLAUDE.md` | Master context Claude reads every session (ICP, APIs, rules) |
| `outbound/ICP_DEFINITIONS.md` | Who qualifies for each segment -- read before building any list |
| `outbound/working_copy.md` | Per-campaign scratch pad for developing email copy |
| `outbound/verify_emails.py` | BillionVerify verification -- run after enrichment, before SmartLead |
| `outbound/generate_emails.py` | LLM copy generation with segment configs |
| `outbound/bq_sync.py` | Sync contacts and enrollments to BigQuery |
| `outbound/smartlead_pull.py` | Pull campaign stats, positive replies, per-campaign breakdown |
| `outbound/SEARCH_LOG.md` | Running log of every Apollo search: TAM, credits used, pages pulled |
| `outbound/INBOX_AUDIT.md` | How to read inbox health: connection, warmup, reputation, capacity |

---

## BigQuery Source of Truth

Dataset: `PLG_OUTBOUND` in project `tenant-recruitin-1575995920662`

**Permanent tables (shared across all campaigns):**
| Table | Contents |
|-------|---------|
| `PLG_CONTACTS` | Every Apollo contact ever pulled -- one row per person, deduped by apollo_id/email |
| `PLG_CAMPAIGN_ENROLLMENTS` | Every SmartLead enrollment -- append-only log |

**Per-campaign pipeline tables (one per campaign build):**
| Naming | Example |
|--------|---------|
| `{segment}_{date}_{variant}` | `local_marketing_20260317_v2` |

One campaign = one table. The sample pull and the full pull go into the SAME table. Never create a second table for the same campaign.

Also used for dedup (Airbyte-synced HubSpot data):
- `airbyte_prod.hubspot_contacts` -- all HubSpot contacts
- `airbyte_prod.hubspot_form_submissions` -- PLG landing page signups

---

## Rules That Never Change

- **Email 1 is ALWAYS plain text.** No HTML, no links. No exceptions. PLG and non-PLG. This has ruined campaigns before.
- **Emails 2 and 3 CAN be HTML** (they contain signup links).
- **Never touch CRE inbox capacity for PLG** -- CRE campaigns are sales, always take priority
- **Always run inbox health check before assigning** -- check actual sends/day, not theoretical capacity
- **All 3 SmartLead delivery settings must be ON**: plain text mode, ESP matching, no open/click tracking
- **`follow_up_percentage: 50`** -- always 50% new leads / 50% follow-ups
- **One campaign = one BigQuery table** -- sample and full pull in the same table
- **Sync to BigQuery after every lead load** -- don't leave the source of truth stale
- **Never spend Apollo credits without human approval** -- free discovery first, review, then enrich
- **Always verify emails via BillionVerify before SmartLead** -- Apollo "verified" is NOT SMTP-verified

---

## Quickstart

1. Open Claude Code in this repo
2. Tell Claude what campaign you want to run
3. Claude will suggest step-by-step (recommended) or autopilot
4. Follow the prompts -- Claude handles the APIs, you make the decisions
