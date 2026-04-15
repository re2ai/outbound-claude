# SmartLead API Reference

**Base URL:** `https://server.smartlead.ai/api/v1`  
**Auth:** `?api_key=YOUR_KEY` on every request (env var: `SMARTLEAD_API_KEY`)  
**Docs:** https://helpcenter.smartlead.ai/en/articles/125-full-api-documentation

---

## Quick-copy pattern (Python)

```python
import requests, os
from dotenv import load_dotenv
load_dotenv()
KEY = os.environ['SMARTLEAD_API_KEY']
BASE = 'https://server.smartlead.ai/api/v1'

# GET
r = requests.get(f'{BASE}/campaigns/', params={'api_key': KEY})

# POST with body
r = requests.post(f'{BASE}/campaigns/{campaign_id}/settings',
    params={'api_key': KEY},
    json={'follow_up_percentage': 100})

# PATCH (only works for /campaigns/{id}/status)
r = requests.patch(f'{BASE}/campaigns/{campaign_id}/status',
    params={'api_key': KEY},
    json={'status': 'PAUSED'})  # START | PAUSED | STOPPED
```

---

## Campaign Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/campaigns/` | List all campaigns. Optional: `client_id`, `include_tags` |
| GET | `/campaigns/{id}` | Get single campaign (full config) |
| POST | `/campaigns/create` | Create campaign in DRAFTED status. Body: `name`, `client_id` |
| PATCH | `/campaigns/{id}/status` | Change status. Body: `{"status": "START"\|"PAUSED"\|"STOPPED"}` |
| POST | `/campaigns/{id}/schedule` | Update schedule. Body: `timezone`, `days_of_the_week` (0-6 array), `start_hour`, `end_hour`, `min_time_btw_emails`, `max_leads_per_day` |
| POST | `/campaigns/{id}/settings` | Update settings (confirmed working). Body fields below |
| GET | `/campaigns/{id}/sequences` | Get all sequence steps |
| POST | `/campaigns/{id}/sequences` | Save/update sequences |
| DELETE | `/campaigns/{id}` | Permanently delete campaign |
| GET | `/campaigns/{id}/analytics` | Top-level stats (total_count, sent_count, reply_count, campaign_lead_stats, etc.) |
| GET | `/campaigns/{id}/statistics` | Per-email stats. Optional: `sent_time_start_date`, `sent_time_end_date`, `offset` |
| GET | `/campaigns/{id}/analytics-by-date` | Time-series analytics by date range |
| GET | `/campaigns/{id}/leads-export` | Export leads as CSV |
| GET | `/leads/{lead_id}/campaigns` | All campaigns a lead appears in |

### `/campaigns/{id}/settings` — body fields
```json
{
  "follow_up_percentage": 100,
  "track_settings": ["DONT_EMAIL_OPEN", "DONT_LINK_CLICK"],
  "stop_lead_settings": "REPLY_TO_AN_EMAIL",
  "send_as_plain_text": true,
  "enable_ai_esp_matching": true,
  "unsubscribe_text": "",
  "client_id": null
}
```

### `/campaigns/{id}/schedule` — body fields
```json
{
  "timezone": "America/New_York",
  "days_of_the_week": [1, 2, 3, 4, 5],
  "start_hour": "08:00",
  "end_hour": "19:00",
  "min_time_btw_emails": 20,
  "max_new_leads_per_day": 300
}
```

---

## Email Account Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/email-accounts/` | List all inboxes. Params: `offset`, `limit` (max 100) |
| GET | `/email-accounts/{id}/` | Get single inbox (full config + warmup details) |
| POST | `/email-accounts/save` | Create inbox. Body: `from_name`, `from_email`, `username`, `password`, `smtp_host`, `smtp_port`, `smtp_port_type` (TLS\|SSL), `imap_host`, `imap_port`, `max_email_per_day` |
| POST | `/email-accounts/{id}` | Update inbox (partial updates OK, same fields as create) |
| POST | `/email-accounts/{id}/warmup` | Configure warmup. Body: `warmup_enabled`, `total_warmup_per_day`, `daily_rampup`, `reply_rate_percentage` |
| GET | `/email-accounts/{id}/warmup-stats` | Last 7 days of warmup stats |
| GET | `/campaigns/{id}/email-accounts` | Inboxes assigned to a campaign |
| POST | `/campaigns/{id}/email-accounts` | Add inboxes to campaign. Body: `{"email_account_ids": [123, 456]}` |
| DELETE | `/campaigns/{id}/email-accounts` | Remove inboxes. Body: `{"email_account_ids": [123]}` |

### Key inbox fields returned
```
from_email, from_name, is_smtp_success, is_imap_success,
smtp_failure_error, imap_failure_error,
daily_sent_count, message_per_day,
warmup_details.status, warmup_details.warmup_reputation,
warmup_details.blocked_reason
```

---

## Lead Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/campaigns/{id}/leads` | List leads in campaign. Params: `offset`, `limit` (max 100) |
| GET | `/leads/` | Find lead by email. Param: `email` |
| GET | `/leads/fetch-categories` | All lead categories (Interested, Meeting Request, etc.) |
| POST | `/campaigns/{id}/leads` | Add leads to campaign |
| POST | `/campaigns/{id}/leads/{lead_id}` | Update lead properties |
| POST | `/campaigns/{id}/leads/{lead_id}/pause` | Pause lead |
| POST | `/campaigns/{id}/leads/{lead_id}/resume` | Resume lead |
| DELETE | `/campaigns/{id}/leads/{lead_id}` | Remove lead from campaign |
| POST | `/campaigns/{id}/leads/{lead_id}/unsubscribe` | Unsub from this campaign |
| POST | `/leads/{lead_id}/unsubscribe` | Global unsubscribe (all campaigns) |
| POST | `/leads/add-domain-block-list` | Block domain globally |
| GET | `/campaigns/{id}/leads/{lead_id}/message-history` | Full send/reply history for a lead |
| POST | `/campaigns/{id}/reply-email-thread` | Send reply to a lead thread |

### `campaign_lead_stats` breakdown (from analytics response)
```
total, notStarted, inprogress, completed, paused, blocked, stopped, interested, revenue
```

---

## Global Analytics

| Method | Path | Description |
|--------|------|-------------|
| GET | `/analytics/overview` | Account-wide metrics across all campaigns |

---

## Notes

- **Pagination:** Use `offset` + `limit` (max 100). Loop until response length < limit.
- **Positive reply categories:** `Interested`, `Meeting Request`, `Meeting Booked`, `Information Request`
- **follow_up_percentage:** % of daily capacity allocated to follow-up emails vs new leads. 50 = split evenly, 100 = all capacity to follow-ups (use when notStarted = 0).
- **max_leads_per_day:** Only controls new lead Email 1 starts — does NOT throttle follow-up emails.
- **seq_delay_details.delayInDays:** Calendar days. Weekend sends get pushed to next Monday.
- **Confirmed NOT working:** `PATCH /campaigns/{id}`, `POST /campaigns/{id}`, `PUT /campaigns/{id}` — use the specific sub-routes above instead.
