# PLG Outbound Orchestration

Claude-powered system for running Resquared's PLG outbound campaigns end-to-end — from building Apollo contact lists to loading leads into SmartLead and tracking everything in BigQuery.

Built to be handed off. Any marketer with credentials and Claude Code can run a correct campaign start to finish.

---

## What This Does

- **List building** — queries Apollo API to find exact-ICP contacts (free discovery + paid enrichment)
- **Deduplication** — checks HubSpot, SmartLead, and BigQuery before enriching to avoid re-contacting
- **LLM copywriting** — generates personalized cold emails via GPT (per-contact opening lines + locked templates)
- **SmartLead automation** — creates campaigns, sets all settings correctly, loads leads, manages inboxes
- **BigQuery source of truth** — every contact and every campaign enrollment written to `PLG_OUTBOUND` so nothing lives only on a local machine
- **Monitoring** — daily health checks (inbox status, send volume, positive replies, HubSpot signups)

---

## Credentials Required

Create `outbound/.env` with all of the following before running anything:

```env
# Apollo — list building and contact enrichment
APOLLO_API_KEY=your_key_here
# Get from: apollo.io → Settings → API Keys

# SmartLead — campaign management
SMARTLEAD_API_KEY=your_key_here
# Get from: smartlead.ai → Settings → API

# OpenAI — LLM copywriting
OPENAI_API_KEY=your_key_here
# Get from: platform.openai.com → API Keys

# HubSpot — signup tracking and dedup
HUBSPOT_ACCESS_TOKEN=your_token_here
# Get from: HubSpot → Settings → Integrations → Private Apps

# Zerobounce — email verification (REQUIRED before loading any leads)
ZEROBOUNCE_API_KEY=your_key_here
# Get from: eng team (we have an account) or zerobounce.net
# Top up credits at zerobounce.net before running — ~$0.008/email, pay as you go

# Slack — notifications (optional)
slackwebhook=https://hooks.slack.com/services/...
# Get from: Slack → Apps → Incoming Webhooks
```

**Google Cloud / BigQuery:**
This repo uses the project `tenant-recruitin-1575995920662`. Authenticate with:
```bash
gcloud auth application-default login
```
You need read/write access to the `PLG_OUTBOUND` dataset. Ask an admin to grant `roles/bigquery.dataEditor` on that dataset.

---

## Key Files

| File | Purpose |
|------|---------|
| `outbound/CAMPAIGN_PLAYBOOK.md` | **Start here.** Full step-by-step workflow for running a campaign |
| `outbound/ICP_DEFINITIONS.md` | Who qualifies for each segment — read before building any list |
| `outbound/INBOX_AUDIT.md` | How to read inbox health: connection, warmup, reputation, capacity |
| `outbound/SEARCH_LOG.md` | Running log of every Apollo search: TAM, credits used, pages pulled |
| `outbound/verify_emails.py` | Zerobounce verification — run after enrichment, before SmartLead load |
| `outbound/bq_sync.py` | Sync contacts and enrollments to BigQuery after every run |
| `outbound/smartlead_pull.py` | Pull campaign stats, positive replies, per-campaign breakdown |
| `outbound/.env` | Local credentials (never commit this) |

---

## BigQuery Source of Truth

Dataset: `PLG_OUTBOUND` in project `tenant-recruitin-1575995920662`

| Table | Contents |
|-------|---------|
| `PLG_CONTACTS` | Every Apollo contact ever pulled — one row per person, deduped by apollo_id/email |
| `PLG_CAMPAIGN_ENROLLMENTS` | Every SmartLead enrollment — which contact went into which campaign and when |

Use this to:
- Check if a domain/company has already been contacted before pulling credits
- Cross-reference with HubSpot deals to avoid hitting active customers
- Track how much of a segment's TAM has been used across all campaigns

After every lead load, run:
```bash
python outbound/bq_sync.py contacts --file /tmp/enriched.json --segment insurance --keyword "independent insurance agent"
python outbound/bq_sync.py enroll   --campaign-id 12345 --campaign-name "PLG - Insurance - Claude" --segment insurance --variant claude
```

To backfill from all current SmartLead campaigns:
```bash
python outbound/bq_sync.py backfill
```

---

## Quickstart (new campaign)

1. Read `outbound/ICP_DEFINITIONS.md` — confirm the segment is a real Resquared buyer
2. Read `outbound/SEARCH_LOG.md` — check if this keyword/segment has remaining TAM
3. Follow `outbound/CAMPAIGN_PLAYBOOK.md` phase by phase — do not skip steps
4. Get copy approved before generating for the full list
5. Run pre-launch QA checklist (Phase 7 of the playbook) before hitting START

---

## Rules That Never Change

- **Never touch CRE inbox capacity for PLG** — CRE campaigns are sales, always take priority
- **Always run inbox health check before assigning** — check actual sends/day, not theoretical capacity
- **All 3 SmartLead delivery settings must be ON**: plain text mode, ESP matching, no open/click tracking
- **`follow_up_percentage: 50`** — always 50% new leads / 50% follow-ups
- **Sync to BigQuery after every lead load** — don't leave the source of truth stale
- **Step-by-step approval** — copy must be approved before full generation; QA before launch
