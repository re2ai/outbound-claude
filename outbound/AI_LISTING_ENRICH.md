# AI Web Search Enrichment — Optional Pre-Campaign Tool

## What This Is

An optional enrichment step that uses OpenAI's native web search capability to find real, currently live external data for each contact — without writing a scraper.

The model is given a structured prompt with everything we know about the contact (name, company, domain, title, location) and told to try multiple search strategies across multiple sites until it finds what we need. It returns structured fields we can pipe directly into email copy or append to a campaign table.

This sits **between** your contact list and `generate_emails.py`. It's not required for every campaign — use it when your email copy needs a specific real-world data point that varies per contact and can't be templated generically.

---

## When To Use It

Use this tool when:
- Your Email 1 copy references something **specific to that contact** that you can look up online
- The data is **publicly available** but not in Apollo or HubSpot (listing details, recent news, a specific product, a recent hire)
- You want **higher personalization without Clay** (Clay charges per enrichment; this costs only OpenAI tokens)
- You're testing a new segment and want to validate signal before investing in Clay workflows

Do NOT use it when:
- The data isn't publicly findable (private pricing, internal contacts)
- Generic segment-level copy is good enough — don't over-engineer
- You already have the data from Apollo/HubSpot enrichment

---

## How It Works

### Architecture

```
Input CSV (contacts) → listing_enrich.py → Output JSON + CSV
                              ↓
                    OpenAI Responses API
                    (gpt-5.4 + web_search_preview tool)
                              ↓
                    Structured fields per contact
                              ↓
                    generate_emails.py (copy generation)
```

### Two-Pass Search Strategy

Every contact gets up to two attempts:

**Pass 1 — Rep-level search (preferred)**
Searches by the individual's name + company across LoopNet, Crexi, company site, and broad web. Uses all context available: full name (from CSV or parsed from email), title, location, and any specialty hint. Prefers the most relevant property type for your use case.

**Pass 2 — Company-level fallback**
If Pass 1 finds nothing, falls back to a pure company-level search with no type restrictions. Accepts any result — the goal is coverage over perfection.

### What Makes the Hit Rate High

1. **Use real names when available.** Individual broker/agent profiles on listing sites are highly searchable by full name. Email-parsed names ("B Broadbent") work but real names ("Bruce Broadbent") work much better.

2. **Give the model multiple search strategies explicitly.** Don't just say "find their listing." Tell it: try LoopNet by name, try LoopNet by company, try Crexi, try their own domain, try broad search. The model will try them in order.

3. **Use every signal in your data.** Title, city/state, and property type specialty all help the model narrow searches faster.

4. **Two passes with different scopes.** Pass 1 is targeted and type-filtered. Pass 2 is broad and accepts anything. Together they consistently hit 95-98% on lists where the contacts are genuinely findable online.

5. **Resume-safe checkpointing.** Writes output every 10 completions so you never lose progress if something interrupts.

---

## Running It

```bash
python outbound/listing_enrich.py \
  --file your_contacts.csv \
  --out /path/to/output.json \
  --stages "Emailed" "Mapped (Clay)"   # optional funnel_stage filter
  --limit 50                            # optional cap for testing
```

**Required CSV columns:** `email`, `domain`

**Beneficial CSV columns (use when available):**
- `contact_name` — full name dramatically improves hit rate
- `company_name` — company to search
- `contact_title` — helps model understand their role
- `city`, `state` — narrows searches geographically
- `property_type` — specialty hint (e.g. "Retail", "Office") from source data
- `funnel_stage` — for `--stages` filtering

**Output columns added:**
| Column | Description |
|--------|-------------|
| `listing_found` | true/false |
| `listing_type` | retail, office, industrial, mixed-use, etc. |
| `listing_type_score` | 1=retail (best) → 5=industrial (worst for our ICP) |
| `listing_address` | full street address + city/state |
| `listing_size` | sq ft or acreage if found |
| `listing_price` | asking price or $/SF/yr if found |
| `listing_details` | 1-2 key specs (anchor tenants, traffic count, etc.) |
| `listing_date` | date posted or last updated if shown |
| `listing_url` | direct link to the live listing |
| `search_pass` | 1 = found on rep search, 2 = found on company fallback |

---

## Adapting For Other Use Cases

`listing_enrich.py` is written for CRE broker listings but the pattern works for any publicly findable data point. To adapt it:

### 1. Rewrite the two prompt templates

`PROMPT_PASS1` — targeted, individual-level search with preferred result type
`PROMPT_PASS2` — broader company-level fallback, any result acceptable

Keep the structured output format (`field: value` lines) — the parser handles it generically.

### 2. Update the output fields

Change what fields you ask for in the prompts and update `call_openai()` to parse them. The parser loops over `("address", "type", "details", "url")` — swap in whatever fields you need.

### 3. Update the CSV output columns

Add/remove from `csv_cols` in `main()`.

### Examples of other use cases this pattern fits:

| Use Case | What to search for | Good for segment |
|---|---|---|
| CRE brokers | Active property listings | CRE campaign ✓ |
| IT/MSP | Specific service pages + client verticals | IT MSP campaign |
| Insurance agents | Coverage specialties + business types | Insurance campaign |
| Staffing agencies | Open job postings they're filling | Staffing |
| Caterers | Recent corporate clients or event menus | Catering |
| Signage companies | Recent installs / portfolio projects | Signage |
| Franchise owners | Which franchise locations they own | Multi-unit operators |

The existing `web_enrich.py` already does a simpler version of this (one pass, two fields) for IT MSP, insurance, catering, cleaning, and signage segments. `listing_enrich.py` is the more robust two-pass version with richer output — use it as the template for new segments.

---

## Model

Always use the latest OpenAI model with web search support. **Do not hardcode an old model.** Check the OpenAI API docs for the current flagship before running. As of March 2026 this is `gpt-5.4`.

The web search tool in the Responses API is `{"type": "web_search_preview"}`.

---

## Cost

Roughly $0.05–0.15 per contact depending on how many searches the model runs and whether Pass 2 is needed. For 3,000 contacts expect $150–400 total. Much cheaper than Clay for one-off enrichment runs.

---

## Performance Benchmarks (CRE Brokers, March 2026)

- **3,260 contacts processed**
- **98% hit rate** (3,188 listings found)
- **~2.5 hours** at 5 workers
- Type breakdown: ~55% retail, ~30% office, ~10% industrial, ~5% other
- Source: `relaunch_campaign_20260325.csv` — CRE brokers scraped from LoopNet
