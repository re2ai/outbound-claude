# PLG (Product-Led Growth) Metrics Documentation

## What PLG Is

PLG is Resquared's **self-service acquisition funnel**. It is completely separate from the sales-assisted funnel.

## The PLG Funnel

```
Outbound Emails → Positive Replies → Signups (form subs) → Trial → Paid
      ↓                  ↓                 ↓               ↓       ↓
  SmartLead          SmartLead          HubSpot        HubSpot  HubSpot
  PLG campaigns      lead_category      form subs      stage    stage
```

## Source of Truth: PLG Signups = Form Submissions

**PLG Signups** are tracked via HubSpot form submissions on PLG landing pages:
- `/resquared-trial-redirect`
- Pages containing "PLG" in URL
- `/trial-re2` pages

```sql
SELECT COUNT(*) as plg_signups
FROM airbyte_prod.hubspot_form_submissions
WHERE TIMESTAMP_MILLIS(submittedAt) >= TIMESTAMP('{start_date}')
  AND TIMESTAMP_MILLIS(submittedAt) < TIMESTAMP(DATE_ADD('{end_date}', INTERVAL 1 DAY))
  AND (
    LOWER(pageUrl) LIKE '%/resquared-trial-redirect%'
    OR LOWER(pageUrl) LIKE '%plg%'
    OR LOWER(pageUrl) LIKE '%trial-re2%'
  )
```

## Campaign Variants

Extract utm_campaign from pageUrl to see which campaigns/variants are working:

```sql
SELECT
  COALESCE(REGEXP_EXTRACT(pageUrl, r'utm_campaign=([^&]+)'), 'direct') as campaign_variant,
  COUNT(*) as submissions
FROM airbyte_prod.hubspot_form_submissions
WHERE TIMESTAMP_MILLIS(submittedAt) >= TIMESTAMP('{start_date}')
  AND TIMESTAMP_MILLIS(submittedAt) < TIMESTAMP(DATE_ADD('{end_date}', INTERVAL 1 DAY))
  AND (LOWER(pageUrl) LIKE '%/resquared-trial-redirect%' OR LOWER(pageUrl) LIKE '%plg%' OR LOWER(pageUrl) LIKE '%trial-re2%')
GROUP BY 1
ORDER BY 2 DESC
```

## HubSpot Lifecycle Stages (Downstream Metrics)

Source: index.html scorecard (authoritative). PLG Stages are set by the product team in HubSpot.

| Stage ID | HubSpot PLG Stage Label | Metric | BQ property |
|----------|------------------------|--------|-------------|
| `1062906763` | "Sent 1st email" | **Trial / 1st Email** | `properties_hs_lifecyclestage_1062906763_date` |
| `1062925493` | "Self Serve Customer" | **Paid** | `properties_hs_lifecyclestage_1062925493_date` |
| `953423363` | "Lost/Cancelled" | **Lost** | `properties_hs_lifecyclestage_953423363_date` |

---

### Pre-Trials / Signups (weekly, deduplicated)
Count unique email submissions — filter duplicates like the same person submitting twice in a week.
```sql
SELECT COUNT(DISTINCT JSON_VALUE(values, '$[0].value')) as pre_trials
FROM airbyte_prod.hubspot_form_submissions
WHERE TIMESTAMP_MILLIS(submittedAt) >= TIMESTAMP('{start_date}')
  AND TIMESTAMP_MILLIS(submittedAt) < TIMESTAMP(DATE_ADD('{end_date}', INTERVAL 1 DAY))
  AND (
    LOWER(pageUrl) LIKE '%/resquared-trial-redirect%'
    OR LOWER(pageUrl) LIKE '%plg%'
    OR LOWER(pageUrl) LIKE '%trial-re2%'
  )
  AND LOWER(COALESCE(JSON_VALUE(values, '$[0].value'), '')) NOT LIKE '%test%'
  AND LOWER(COALESCE(JSON_VALUE(values, '$[0].value'), '')) NOT LIKE '%re2.ai%'
```
### Trial / 1st Email (weekly)
Entered PLG Stage "Sent 1st email" (stage 1062906763).
```sql
SELECT COUNT(*) as trials
FROM airbyte_prod.hubspot_contacts
WHERE TIMESTAMP(properties_hs_lifecyclestage_1062906763_date) >= TIMESTAMP('{start_date}')
  AND TIMESTAMP(properties_hs_lifecyclestage_1062906763_date) < TIMESTAMP(DATE_ADD('{end_date}', INTERVAL 1 DAY))
  AND properties_email NOT LIKE '%test%'
  AND properties_email NOT LIKE '%re2.ai%'
```

### Paid / Self-Serve Customer (weekly)
Entered PLG Stage "Self Serve Customer" (stage 1062925493).
```sql
SELECT COUNT(*) as paid
FROM airbyte_prod.hubspot_contacts
WHERE TIMESTAMP(properties_hs_lifecyclestage_1062925493_date) >= TIMESTAMP('{start_date}')
  AND TIMESTAMP(properties_hs_lifecyclestage_1062925493_date) < TIMESTAMP(DATE_ADD('{end_date}', INTERVAL 1 DAY))
  AND properties_email NOT LIKE '%test%'
  AND properties_email NOT LIKE '%re2.ai%'
```

### Lost / Cancelled (weekly)
Entered PLG Stage "Lost/Cancelled" (stage 953423363).
```sql
SELECT COUNT(*) as lost
FROM airbyte_prod.hubspot_contacts
WHERE TIMESTAMP(properties_hs_lifecyclestage_953423363_date) >= TIMESTAMP('{start_date}')
  AND TIMESTAMP(properties_hs_lifecyclestage_953423363_date) < TIMESTAMP(DATE_ADD('{end_date}', INTERVAL 1 DAY))
  AND properties_email NOT LIKE '%test%'
  AND properties_email NOT LIKE '%re2.ai%'
```

## SmartLead PLG Campaigns

PLG campaigns in SmartLead have "PLG" in their name. Use `smartlead_pull.get_plg_campaign_breakdown()` to get per-campaign stats:

- Campaign name
- Emails sent (this week)
- Positive replies (Interested, Meeting Request, Meeting Booked, Information Request)
- Positive reply rate

## PLG UTM Campaigns

Contacts with these utm_campaign values are PLG:
- `re2g`
- `resquaredcs`
- `clay-v2`
- `re2cater`
- `PLG%` (any campaign starting with PLG)

## NOT PLG

- Deals in HubSpot (those are sales-assisted)
- Contacts with EMAIL_MARKETING source (could be sales outbound)
- General new user signups in MongoDB (need to cross-reference with form submissions)

## Goal

**20+ weekly signups** without increasing outbound volume.

## Weekly Benchmarks (as of Jan 2026)

| Week Ending | Signups | Trial | Paid | +Reply Rate |
|-------------|---------|-------|------|-------------|
| 2026-01-24  | 6       | 7     | 0    | 0.18%       |
| 2026-01-17  | ?       | ?     | ?    | ?           |
