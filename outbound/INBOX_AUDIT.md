# Inbox Audit Guide

How to read inbox health in SmartLead, what each signal means, and what to do about problems.

---

## Running the Audit

Pull all inboxes via the API (max 100 per page):

```python
import requests, os
from dotenv import load_dotenv
load_dotenv()

KEY = os.getenv("SMARTLEAD_API_KEY")
BASE = "https://server.smartlead.ai/api/v1"

accounts = []
offset = 0
while True:
    r = requests.get(f"{BASE}/email-accounts/", params={"api_key": KEY, "limit": 100, "offset": offset}, timeout=15)
    batch = r.json()
    if not isinstance(batch, list) or not batch:
        break
    accounts.extend(batch)
    if len(batch) < 100:
        break
    offset += 100

print(f"{len(accounts)} inboxes total")
```

Or use the existing health check in `smartlead_pull.py`.

---

## Key Fields

Each inbox object has these fields that matter for auditing:

| Field | Type | What it means |
|-------|------|---------------|
| `from_email` | string | The sending address |
| `from_name` | string | Display name |
| `is_smtp_success` | bool | SMTP connection working |
| `is_imap_success` | bool | IMAP connection working |
| `smtp_failure_error` | string\|null | Error message if SMTP broken |
| `imap_failure_error` | string\|null | Error message if IMAP broken |
| `daily_sent_count` | int | Emails sent today |
| `message_per_day` | int | Configured send limit (15 or 20) |
| `campaign_count` | int | Number of campaigns this inbox is in |
| `warmup_details.status` | string | `ACTIVE` or `INACTIVE` |
| `warmup_details.warmup_reputation` | string | e.g. `"100%"` |
| `warmup_details.blocked_reason` | string\|null | Why warmup is blocked (if it is) |
| `warmup_details.warmup_created_at` | ISO timestamp | When warmup started |
| `warmup_details.total_sent_count` | int | Total warmup emails sent |
| `warmup_details.total_spam_count` | int | Total warmup emails that landed in spam |

---

## Connection Status

**Healthy:** `is_smtp_success: true`, `is_imap_success: true`

**Disconnected:** either field is `false`. Check `smtp_failure_error` / `imap_failure_error` for the reason.

Common disconnection causes:
- Google OAuth token expired (most common for Gmail inboxes)
- Password changed on the Google account
- "Less secure app access" or OAuth scope revoked
- Domain/DNS change broke SMTP auth

**How to fix:**
1. Go to SmartLead UI → Email Accounts
2. Find the disconnected inbox
3. Click Reconnect → reauthenticate via Google OAuth
4. The `is_smtp_success` and `is_imap_success` fields update within a few minutes of reconnecting

**Script to find disconnected inboxes:**
```python
disconnected = [a for a in accounts if not a.get('is_smtp_success') or not a.get('is_imap_success')]
for a in disconnected:
    print(f"{a['from_email']}: smtp={a['is_smtp_success']} imap={a['is_imap_success']}")
    print(f"  smtp_err: {a.get('smtp_failure_error')}")
    print(f"  imap_err: {a.get('imap_failure_error')}")
```

---

## Warmup Status

Warmup sends low-volume emails between inboxes in a network to build sender reputation. It must always be active on every inbox.

### `warmup_details.status` values

| Value | Meaning |
|-------|---------|
| `ACTIVE` | Warmup is running |
| `INACTIVE` | Warmup is stopped — reactivate immediately |

**Note:** `ACTIVE` does not mean healthy. An inbox can show `ACTIVE` while also having a `blocked_reason`. Always check both fields.

### Reactivating warmup (API)

```python
r = requests.post(
    f"{BASE}/email-accounts/{inbox_id}/warmup",
    params={"api_key": KEY},
    json={"warmup_enabled": True},
    timeout=10
)
```

---

## Blocked Warmup

`warmup_details.blocked_reason` is non-null when the warmup network flagged a problem with the inbox. This happens even when `status` shows `ACTIVE`.

### Blocked reason types we've seen

**1. Bounce detected / reputation blocked**
```
Bounce detected: customer_reputation_blocked (6 bounces)
```
- The warmup network sent emails to this inbox and got 6+ bounces back
- Usually means the mailbox address doesn't fully exist or the domain has routing issues
- `status` goes `INACTIVE` when this happens
- **What to do:** Check that the mailbox is set up correctly in Google Workspace. If the address is real and receives mail, reactivate warmup. If it keeps getting blocked, the domain may have DNS/MX issues.

**2. Address not found**
```
Address not found — Your message wasn't delivered to griffin@airesquaredonline.com because the address couldn't be found
```
- The warmup network tried to send to this inbox and got a hard bounce
- The mailbox itself may not exist or Google Workspace hasn't provisioned it yet
- `status` can still show `ACTIVE` (misleading — the inbox isn't actually warming)
- **What to do:** Verify the mailbox exists in Google Workspace admin. If it's new, wait 10-15 minutes for provisioning. Then reactivate warmup.

**3. Already failed validation**
```
This mailbox already failed the validation test previously.
```
- SmartLead's warmup network gave up retrying after repeated failures
- `status` stays `ACTIVE` but warmup has stopped working
- **What to do:** Investigate the underlying cause (usually same as "Address not found"). Fix it, then reactivate warmup to reset.

**Script to find all blocked inboxes:**
```python
blocked = [a for a in accounts if (a.get('warmup_details') or {}).get('blocked_reason')]
for a in blocked:
    wd = a['warmup_details']
    reason_short = (wd.get('blocked_reason') or '').split('\n')[0][:100]
    print(f"[{wd.get('status')}] {a['from_email']}")
    print(f"  rep={wd.get('warmup_reputation')} | {reason_short}")
```

---

## Warmup Reputation

`warmup_details.warmup_reputation` is a percentage score from the warmup network.

| Score | Meaning | Action |
|-------|---------|--------|
| `100%` | Perfect — emails landing in inbox | None needed |
| `95-99%` | Good — minor spam landings | Monitor |
| `80-94%` | Degraded — notable spam rate | Reduce campaign volume, investigate |
| `<80%` | Bad — significant deliverability damage | Pause campaigns on this inbox |

A low reputation usually means the inbox has been sending to bad lists (high bounce/spam rate) or hasn't been warming long enough before being assigned to campaigns.

---

## Warmup Age

`warmup_details.warmup_created_at` tells you when warmup started. Age matters because new inboxes have no sender history — sending campaigns too early causes bounces and reputation damage.

| Age | Status | Use for campaigns? |
|-----|--------|--------------------|
| < 7 days | Too new | No — do not assign |
| 7-13 days | Borderline | No — wait |
| 14-30 days | Good | Yes — with conservative limits (≤15/day) |
| > 30 days | Fully warmed | Yes — up to configured `message_per_day` |

**Script to check warmup age:**
```python
from datetime import datetime, timezone

def warmup_age_days(account):
    wd = account.get('warmup_details') or {}
    created = wd.get('warmup_created_at')
    if not created:
        return None
    return (datetime.now(timezone.utc) - datetime.fromisoformat(created.replace('Z', '+00:00'))).days

for a in accounts:
    age = warmup_age_days(a)
    if age is not None and age < 14:
        print(f"{a['from_email']}: {age} days old — do not use")
```

---

## Capacity Check

Before assigning an inbox to a new campaign, verify it has actual send capacity.

| Field | Meaning |
|-------|---------|
| `message_per_day` | Configured daily limit (15 or 20) |
| `daily_sent_count` | Already sent today |
| `campaign_count` | Campaigns the inbox is currently in |

**Available capacity** = `message_per_day` - `daily_sent_count`

But `daily_sent_count` resets at midnight and is a snapshot — a better signal is actual 7-day send rate across all campaigns, which you can compute from SmartLead analytics:

```python
# Rough capacity check
for a in accounts:
    cap = a.get('message_per_day', 0)
    sent_today = a.get('daily_sent_count', 0)
    remaining = cap - sent_today
    if remaining > 0 and a.get('is_smtp_success') and warmup_age_days(a) >= 14:
        print(f"{a['from_email']}: {remaining}/{cap} remaining today | campaigns={a.get('campaign_count', 0)}")
```

**Rules before assigning an inbox:**
1. `is_smtp_success: true` and `is_imap_success: true`
2. `warmup_details.status: ACTIVE`
3. No `blocked_reason` (or blocked_reason is resolved)
4. `warmup_reputation` ≥ 95%
5. Warmup age ≥ 14 days (prefer > 30 days)
6. Not already maxed on `daily_sent_count`
7. **Never take from a CRE campaign** — sales inboxes are off limits for PLG

---

## Daily Audit Checklist

Run this before any campaign work:

```python
from datetime import datetime, timezone

issues = []
for a in accounts:
    email = a['from_email']
    wd = a.get('warmup_details') or {}

    if not a.get('is_smtp_success') or not a.get('is_imap_success'):
        issues.append(f"DISCONNECTED: {email}")
    elif wd.get('status') == 'INACTIVE':
        issues.append(f"WARMUP INACTIVE: {email}")
    elif wd.get('blocked_reason'):
        reason = wd['blocked_reason'].split('\n')[0][:80]
        issues.append(f"WARMUP BLOCKED [{wd.get('status')}]: {email} — {reason}")

    rep = wd.get('warmup_reputation', '100%')
    rep_pct = int(rep.replace('%', '')) if rep else 100
    if rep_pct < 95:
        issues.append(f"LOW REPUTATION ({rep}): {email}")

if issues:
    print(f"{len(issues)} issues found:")
    for i in issues:
        print(f"  {i}")
else:
    print("All inboxes healthy.")
```

---

## API Reference

```
GET  /email-accounts/                    ?limit=100&offset=N
POST /email-accounts/{id}/warmup         {"warmup_enabled": true}
POST /email-accounts/{id}                {"message_per_day": 20, "signature": "..."}
```

All requests: `?api_key=SMARTLEAD_API_KEY`
Base URL: `https://server.smartlead.ai/api/v1`
