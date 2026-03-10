# Apollo Search Log

Track every search: filters used, TAM discovered, how many enriched, how many remain.

---

## Insurance — 2026-02-27

### Search v1 (BROAD — do not reuse)
**Keyword**: `commercial insurance`
**Filters**:
- person_titles: owner, principal, agent, producer, president, founder, partner, managing partner, agency owner
- organization_num_employees_ranges: 1,50
- organization_locations: United States
- has_email: true (free api_search flag)

**TAM**: ~2,900 contacts
**Enriched**: 100 contacts (using people/match, ~1 credit each)
**Credits used**: ~100
**Saved to**: `/tmp/insurance_enriched.json`
**Status**: DEPRECATED — keyword too broad, catches large commercial brokers, benefits consultants, wholesale/surplus lines. Do NOT load these into campaigns.

---

### Search v2 (CURRENT — tight ICP)
**Keyword**: `independent insurance agent`
**Filters**:
- person_titles: owner, principal, agent, producer, president, founder, partner, managing partner, agency owner
- organization_num_employees_ranges: 1,50
- organization_locations: United States
- has_email: true (free api_search flag)

**Post-filters applied**:
- has_email=True on api_search result
- Exclude captive brands: State Farm, Allstate, Farmers, Nationwide, Erie, USAA, Travelers, Liberty Mutual, American Family, Progressive, Berkshire, Chubb, AIG, Zurich
- Exclude personal-lines-only titles: life insurance, health insurance, personal lines, homeowners

**TAM**: ~2,290 contacts (estimated via binary search on free api_search pages — no credits)
**Candidates pulled (api_search, free)**: 182 contacts → saved to `/tmp/ins_v2_candidates.json`
**Enriched via people/match**: 148 contacts attempted
**Verified emails returned**: 100 contacts
**Yield**: ~68% (148 attempted → 100 with verified email)
**Credits used**: ~148
**Saved to**: `/tmp/ins_v2_final.json`
**Status**: READY — 100 contacts ready to load into campaign 2979670

**Remaining TAM**: exhausted this search — all 23 pages pulled

---

### Search v3 (2026-03-02 — extended v2 pull, same filters)
**Same filters as v2** — continued from page 3 through page 23
**Candidates pulled (api_search, free)**: 1,047 new candidates → `/tmp/ins_v3_candidates.json`
**Enriched**: 721 contacts (Apollo Basic plan, ~600 credits used)
**Verified emails**: 721 (yield higher on Basic plan vs free)
**Saved to**: `/tmp/ins_v3_enriched.json`
**Deduplicated against v2**: 759 fresh contacts remaining after dedup

**Split across campaigns (2026-03-02):**
- 253 → PLG - Commercial Insurance - Claude (top-up, campaign 2980072) — total now 352 leads
- 319 → PLG - Commercial Insurance - Blunt - Claude (new, campaign 2986711) — Subject1/Email1 custom fields (plain body, company name in subject)
- 253 → PLG - Commercial Insurance - More Capacity - Claude (new, campaign 2986627) — LLM opening line

**Apollo plan**: upgraded to Basic ($59/mo, 2,500 credits/month) on 2026-03-02
**Credits used to date (estimate)**: ~850 of 2,500 monthly
**Remaining TAM**: search v2 keyword "independent insurance agent" is likely exhausted (~2,290 contacts total across all pages). Need new keyword variation to find more contacts.
**Next step**: Try different keywords (e.g. "commercial lines agent", "business insurance broker", "P&C insurance agent") to find additional ICP contacts beyond current TAM.

---

## IT/MSP — 2026-03-05

### Search v1 (CURRENT)
**Keyword**: `IT services`
**Filters**:
- person_titles: owner, founder, president, CEO, managing director
- organization_num_employees_ranges: 1,50
- organization_locations: United States
- has_email: true (free api_search flag)

**TAM**: ~672 contacts (7 pages × ~96/page)
**Candidates pulled (api_search, free)**: 478 contacts → `/tmp/it_msp_candidates.json`
**Enriched via people/match**: 476 contacts attempted
**Verified emails (Zerobounce)**: 395 valid → `/tmp/it_msp_verified.json`
**Yield**: ~83% (476 attempted → 395 with valid email)
**Credits used**: ~476

**Web enrichment (gpt-5 + web_search)**:
- Tool: `web_enrich.py`, model: gpt-5, 5 workers
- Input: `/tmp/it_msp_verified.json`
- Output: `/tmp/it_msp_enriched.json`
- Hit rate: 59% (235/395 got specific service + smb_type)
- Fallback: "managed IT support" / "local businesses" for the rest

**Email generation**:
- Tool: `generate_emails.py --segment it_msp`
- Mode: web_enrich (no GPT per contact)
- Output: `/tmp/it_msp_emails.json`
- Template: "Do you do [service] for [smb_type] mainly, or more general SMB?"

**Campaign**: PLG - IT Solutions - Web Enrich - Claude (ID: 3001311)
- 393 leads loaded (2 blocked by global block list)
- 20 inboxes: tyler/jalen/leonardo at aire2sales, airesquaredsales, byre2tech, getre2sales, etc.
- max_new_leads_per_day: 20 | Schedule: Mon-Fri 8am-6pm ET
- **Launched: 2026-03-05**

**Status**: ACTIVE — 0 contacts remaining in enriched pool (395 all loaded)
**Next**: Pull more pages / try keyword variants if campaign performs well
**Next keywords to try**: "managed service provider", "managed IT", "network support"

---

## Janitorial / Commercial Cleaning — 2026-03-09

### Search v1 (CURRENT — Apollo multi-keyword pull)
**Keywords searched**: `commercial cleaning` (431), `janitorial services` (268 new), `janitorial company` (27 new), `cleaning services` (1,826 new)
**Filters**:
- person_titles: owner, founder, president, CEO, managing director
- organization_num_employees_ranges: 1,50
- organization_locations: United States
- has_email: true (free api_search flag)

**Total unique candidates pulled**: 2,553 → `/tmp/janitorial_candidates_all.json`
**Prioritized for enrichment**: 1,100 → `/tmp/janitorial_to_enrich.json`
**Enriched via people/match**: 1,100 attempted
**With email returned**: 478 (43% yield — lower than IT/MSP due to "cleaning services" broad keyword)
**ZB verified (valid only)**: 338 → `/tmp/janitorial_verified.json`
**ZB verified (valid + catch-all)**: 417 → `/tmp/janitorial_verified_ca.json`
**Emails generated**: 417 → `/tmp/janitorial_emails.json`
**Deduplicated against existing Janitorial leads**: 57 dupes removed
**Loaded into campaign**: 360 fresh leads → PLG - Janitorial (campaign 2947140)
**Credits used**: ~1,100
**Remaining pool**: ~1,453 candidates in `/tmp/janitorial_candidates_all.json` not yet enriched (need next month credits)

**Campaign**: PLG - Janitorial (ID: 2947140)
- 69 inboxes (mix of griffin/leonardo/jalen)
- Total leads after this load: 1,576 + 360 = ~1,936
- **Status**: ACTIVE — 360 new leads added 2026-03-09

**Email format used**:
- Subject: `cleaning x local restaurants`
- Email1: `Hi {first_name}, Do you do commercial cleaning for restaurants mainly, or more general SMB? We have about 1,000 restaurants in {city}... Free account for {company}?`
- Mode: web_enrich defaults (no web search run — all contacts use default smb_type=restaurants)

**Next keywords to try**: "office cleaning", "commercial janitorial", "cleaning contractor"
**Remaining TAM**: Exhausted — new keywords (commercial cleaning company, janitorial contractor, office cleaning service, building cleaning service) yielded 0-1 new candidates

### Batch 2 (2026-03-09 — remaining 1,453 candidates)
**Candidates enriched**: 1,453 → 348 with email (24% yield — "cleaning services" keyword broad)
**ZB verified**: 284 (219 valid + 65 catchall)
**Loaded into campaign**: 271 fresh → PLG - Janitorial (2947140)
**Total Janitorial new leads today**: 360 + 271 = **631 fresh leads**

---

## Catering — 2026-03-09

**Keywords**: corporate catering (15), catering company (57), event catering (30), catering service (12)
**Total candidates**: 114 → 114 enriched (100% yield) → 90 ZB verified (valid+catchall)
**Loaded into**: PLG - Event Catering (ID 2911388) — 88 fresh leads
**Remaining TAM**: Small (~114 candidates total, exhausted for these keywords)
**Next keywords**: "food service company", "meal delivery service" — may find different ICP

---

## Signage — 2026-03-09

**Keywords**: sign company (228), signage company (4), commercial signage (1), sign shop (24), sign manufacturer (3)
**Total candidates**: 260 → 259 enriched → 91 ZB verified (valid+catchall)
**Loaded into**: PLG - Local Signage Businesses - copy (ID 2698429) — 89 fresh leads, campaign RESTARTED
**Remaining TAM**: Likely exhausted for these keywords

---

## Merchant Services — 2026-03-09

**Keywords**: merchant services (231), payment processing (47), credit card processing (9)
**Total candidates**: 287 → 287 enriched → 77 ZB verified
**Status**: Emails generated (/tmp/merchant_emails.json) — NO CAMPAIGN YET (needs setup)

---

## IT/MSP — Round 2 — 2026-03-09

**Keywords**: managed service provider (11), managed IT (118), network support (34), IT support company (1)
**Total new candidates**: 164 → 163 enriched → 160 ZB verified
**Loaded into**: PLG - IT Solutions - Web Enrich - Claude (ID 3012037) — 107 fresh leads

---

## Insurance — Round 2 — 2026-03-09

**Keywords**: commercial lines agent (272), P&C insurance (136), property casualty insurance (294), business insurance broker (11)
**Total candidates**: 700 → 695 enriched (99% yield!) → 609 ZB verified (432 valid + 177 catchall)
**Emails generated**: 609 (decision tree mode, GPT per contact)
**Loaded into**: 204/203/198 across PLG - Commercial Insurance - Claude (2980072), Blunt-Claude (2986711), MoreCapacity-Claude (2986627)

---

## Other Segments

| Segment | Status |
|---------|--------|
| Merchant Services | Emails ready (/tmp/merchant_emails.json) — needs new campaign setup |
| CRE | Sales segment — handled separately |
