# Working Copy File — Local Marketing Campaign (March 2026)

This file gets overwritten every campaign. It's the scratch pad for developing copy.

**UNIVERSAL RULE: Email 1 is ALWAYS plain text. No HTML, no links. Emails 2/3 can be HTML (signup links).**

---

## Best Historical Copy (actual emails from top campaigns)

### Web Design — 0.69% positive rate (BEST PLG performer, 6,642 sent)
```
Subject: website design x local businesses

Hi Shane, do you sell website design to retail businesses in Austin?

We built a platform that automates identifying and sending AI-personalized emails to
local businesses likely to need your services. It helps you reach the right prospects
faster with relevant messaging.

We're offering free accounts this month — want me to set one up for you?
```

### IT Solutions Web Enrich — 1.21% reply rate (578 sent, small sample but highest reply)
```
Subject: managed IT x local dental offices

Hi Alexa,

Do you do structured cabling for dental offices mainly, or more general SMB?

We have about 1,000 dental offices in Orlando that could be a match. We built an app
that uses AI to find managed IT companies leads and use AI to email them.

Do you want me to set up a free account for Nerd Te[am] and send you the login to test?
```

### Local Marketing Agencies — 0.35% positive (3,760 sent)
```
Subject: copywriting x local businesses

Hi Drew, do you sell copywriting to retail businesses in Ypsilanti?

We built a platform that automates identifying and sending AI-personalized emails to
local businesses likely to need your services. It helps you reach the right prospects
faster with relevant messaging.

We're offering free accounts this month — want me to set one up for you?
```

### Signage — 0.25% positive (1,602 sent)
```
Subject: signage x local businesses

Hi Ryan,

Do you sell signage and vehicle wraps to local businesses in Cincinnati?

[same body as above]
```

---

## What Worked vs What Didn't

WINNER pattern (Web Design 0.69%, IT Web Enrich 1.21%):
- Opening question that names a SPECIFIC service + SPECIFIC business type
- IT Web Enrich went further: named a specific vertical from their actual website
- Short, reads like a human typed it fast
- CTA: "want me to set one up for you?" / "Do you want me to set up a free account?"

WEAKER pattern (Local Marketing 0.35%, Signage 0.25%):
- "do you sell [generic service] to retail businesses in [city]?"
- "retail businesses" is vague — these agencies serve specific verticals
- Same middle paragraph on every campaign (starts feeling templated)
- "automates identifying and sending AI-personalized emails" is wordy

WORST performer across all PLG: "are you the best person to reach out to about this?" as Email 3 (0.254% positive)

---

## What We Know About This Audience (Local SEO / Marketing Agencies)

From Apollo company_keywords on our sample:
- google business profile optimization, local citation services, reputation management
- local lead generation, organic growth, google ads management
- website design, content marketing, social media, SEO
- Some specialize: dental, home services, restaurants, contractors

These are agency OWNERS (1-50 emp) who sell local marketing services to brick-and-mortar
businesses. Many of them are already doing cold outreach to win clients. Resquared gives
them the local business data + AI email tool to do that outreach way faster.

The pitch is dead simple: "you sell local SEO to dentists — we have a database of every
dentist in your city with contact info, and we'll let you email them for free."

---

## Proposed Copy — Option A (Apollo data only, no web enrichment)

Uses company_keywords to pick the most specific service and smb_type.
LLM writes the opening question, rest is template.

```
Subject: {service} x local {smb_type}
Example: "local SEO x local dental offices"

Hi {first_name},

{LLM opening question — one sentence, based on company_keywords}

We have a database of thousands of {smb_type} in {city} with emails and phone numbers.
We're giving away free accounts to agencies that want to try it for prospecting.

Should I set one up for {company_name}?
```

Example rendered:
```
Subject: local SEO x local dental offices

Hi Mark,

Do you do most of your local SEO work for dental practices, or spread across verticals?

We have a database of thousands of dental offices in Chicago with emails and phone
numbers. We're giving away free accounts to agencies that want to try it for prospecting.

Should I set one up for SearchLab?
```

---

## Proposed Copy — Option B (tighter, more casual)

Drops the "database" framing, leads with the value prop more directly.

```
Subject: {service} x {smb_type} in {city}
Example: "local SEO x restaurants in Austin"

Hi {first_name},

{LLM opening question}

We just built a tool that finds {smb_type} in {city} that likely need {service} and
cold emails them for you. Takes about 15 minutes to set up.

Free account if you want to try it — want me to send the login?
```

Example rendered:
```
Subject: local SEO x restaurants in Austin

Hi Brian,

Are most of your clients restaurants and retail, or do you work across local niches?

We just built a tool that finds restaurants in Austin that likely need local SEO and
cold emails them for you. Takes about 15 minutes to set up.

Free account if you want to try it — want me to send the login?
```

---

## Proposed Copy — Option C (blend of A + B, closest to top performer structure)

Keeps the proven "do you do X for Y" opener from the 0.69% winner, but swaps in
specific data from company_keywords instead of generic "retail businesses."

```
Subject: {service} x local {smb_type}

Hi {first_name},

Do you do {service} for {smb_type} in {city}, or more general local business?

We have about 1,000 {smb_type} in {city} with verified contact info. We built an app
that lets you email all of them on autopilot.

Free account this month — want me to set one up for {company_name}?
```

Example rendered:
```
Subject: google business profile x local contractors

Hi Justin,

Do you do Google Business Profile work for contractors in Santa Monica, or more general
local business?

We have about 1,000 contractors in Santa Monica with verified contact info. We built an
app that lets you email all of them on autopilot.

Free account this month — want me to set one up for Merchynt?
```

---

## Email 2 — Day +3 (mail-merge, no LLM)

```
I ran a quick search in {city} myself this morning.
I made a target list of 200 businesses and their contact email that I think would be
interested in your services before the end of Q1.

You can access all the local business data for {city}.

<a href="https://landing.re2.ai/resquared-trial-redirect?utm_source=email&utm_medium=link&utm_campaign=claude-v1&email={url_encoded_email}">Access {city} Lead Data</a>

This is for a free account to try it yourself. Would love your feedback.
```

## Email 3 — Day +7 (mail-merge, no LLM)

```
Since I'm guessing you're busy, I'll just leave this here so you can check the data
whenever you have a moment.

You can access all the local business data for {city}.

<a href="https://landing.re2.ai/resquared-trial-redirect?utm_source=email&utm_medium=link&utm_campaign=claude-v1&email={url_encoded_email}">Access {city} Lead Data</a>
```

---

## Decision: Which option?

Waiting on human review. Key tradeoffs:
- Option A: Most professional, "database" framing, clear value prop
- Option B: Most casual, "tool" framing, shortest, "takes 15 minutes" is concrete
- Option C: Closest to proven 0.69% winner structure, "1,000 {smb_type}" is specific and compelling

All three use company_keywords from Apollo to personalize — NO web enrichment needed.
The LLM only writes the opening question (one sentence). Everything else is template.
