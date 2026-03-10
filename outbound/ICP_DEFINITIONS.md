# Resquared ICP Definitions

## The One Rule That Overrides Everything

**We only sell to people who are CURRENTLY doing active cold outreach (cold email, cold calls, door-to-door) to LOCAL BUSINESSES.**

A "local business" = any business with a Yelp or Google Maps page. Restaurants, retailers, local medical offices (dentists, chiropractors, urgent care), auto repair shops, salons, gyms, local contractors. Consumer-facing, main street businesses.

**If a company would never cold call a new restaurant, retail store, or local medical office — we do not sell to them.**

This disqualifies:
- Anyone selling to large corporations, enterprises, or government
- Anyone selling to individuals/consumers (even if their product is business-adjacent)
- Anyone whose new business comes entirely from referrals, inbound, or carrier assignment
- Anyone selling to other businesses via channel/wholesale (not direct to the end business)

---

## Segment ICP Definitions

---

### INSURANCE

#### Who qualifies
Independent insurance agents and agencies that actively cold prospect **small local businesses** for commercial accounts — specifically targeting new business openings, restaurants, retail stores, local offices, contractors.

The signal: they are trying to be **first in the door** when a new business opens in their territory. They cold call, cold email, door-knock. They are NOT waiting for referrals.

**Target profile:**
- Independent agency (NOT captive — see exclusions)
- Writes commercial GL, BOP, workers comp, commercial property for **small local businesses**
- 1–20 employees is sweet spot (owner/principal is also doing the prospecting themselves)
- Up to 50 employees acceptable
- US only
- Titles: owner, principal, agent, producer, agency owner, managing partner, founder

**Keywords that indicate correct ICP:**
- "small business insurance"
- "local business insurance"
- "restaurant insurance"
- "retail insurance"
- "new business insurance"
- "main street" (in company description)
- "commercial lines" + small business context
- "general liability" + local business context
- "business owners policy" / "BOP"

#### Who does NOT qualify
- **Captive agents** (State Farm, Allstate, Farmers, Nationwide, Erie, USAA, Travelers, Liberty Mutual, American Family) — they have territory assignment, don't cold prospect the same way
- **Personal lines** agents — home, auto, life, health. Their customers are individuals.
- **Benefits / group health** brokers — sell employee benefits to employers, not to local businesses as local businesses
- **Large commercial brokers** — their clients are mid-market and enterprise companies, not a new pizza place
- **Wholesale / surplus lines brokers** — they sell to other agents, not directly to businesses
- **Professional liability specialists** (D&O, E&O, cyber, malpractice) — their market is professional firms, not local retail/restaurants
- **Workers comp only at scale** — large account WC brokers are not cold calling local restaurants
- **Reinsurance** — not even close

#### Apollo filter logic
- `organization_num_employees_ranges`: ["1,50"]
- `organization_locations`: ["United States"]
- `person_titles`: ["owner", "principal", "agent", "producer", "president", "founder", "partner", "managing partner", "agency owner"]
- `q_keywords`: NEEDS REFINEMENT — "commercial insurance" is too broad. Should target keywords indicating LOCAL/SMALL business focus and active prospecting behavior.
- **Post-filter exclusions**: company name contains State Farm, Allstate, Farmers, Nationwide, Erie, USAA, Travelers, Liberty Mutual, American Family, Progressive, Berkshire, Chubb, AIG, Zurich, etc.

---

### JANITORIAL / COMMERCIAL CLEANING

#### Who qualifies
Commercial cleaning companies that actively cold call and door-knock **local businesses** — restaurants, medical offices, retail stores, office parks — to sell recurring cleaning contracts.

**Target profile:**
- Sells recurring janitorial/cleaning services to LOCAL businesses (not one-time cleans)
- 1–50 employees
- Titles: owner, operations manager, sales manager, business development

**Disqualifiers:**
- Residential cleaning (maid services, home cleaning) — customers are individuals
- Carpet cleaning / restoration / disaster recovery — not recurring local business contracts
- Large national/franchise cleaning (ABM, Aramark, ServiceMaster at scale) — they don't cold prospect small accounts
- Window washing only, pressure washing only — niche, rarely cold prospecting

---

### IT / MSP

#### Who qualifies
Managed service providers and IT companies that actively cold prospect **small local businesses** — local retail, restaurants, medical offices, auto dealerships — for recurring managed IT contracts.

**Target profile:**
- Provides managed IT services (not project-only), structured cabling, low-voltage, physical security hardware to LOCAL businesses
- 1–50 employees
- Titles: owner, MSP director, sales, business development, founder

**Disqualifiers:**
- SaaS / software development companies — they build products, don't cold call restaurants
- Cybersecurity software vendors — enterprise focus
- IT staffing / recruiting firms
- Large national MSPs (not cold calling local pizza shops)
- Residential IT / home theater / home automation (customers are individuals)
- Guard services / patrol (different product entirely)

---

### EVENT / CORPORATE CATERING

#### Who qualifies
Off-premise catering companies that actively cold call and email **local businesses and offices** to sell corporate catering — box lunches, office catering, executive dining, event catering for business events.

**Target profile:**
- Sells to offices, corporate clients, business events (NOT weddings, social events)
- 1–50 employees
- Titles: owner, catering director, sales, business development

**Disqualifiers:**
- Wedding / social event catering only — their customers are individuals, not local businesses
- Restaurant caterers who only do on-site events
- Meal prep / personal chef services
- Food trucks (no active cold prospecting to businesses)
- Party rental / event staffing

---

### MERCHANT SERVICES / PAYMENT PROCESSING

#### Who qualifies
ISOs, agents, and payment processors that actively cold call and door-knock **local retailers, restaurants, and main street businesses** to sell POS systems, credit card processing, and merchant accounts.

**Target profile:**
- Sells POS hardware, credit card terminals, or merchant processing directly to local businesses
- 1–50 employees
- Titles: owner, agent, ISO, sales rep, business development, merchant services rep

**Disqualifiers:**
- Enterprise payment processors (Stripe, Square, Toast at scale) — not door-knocking
- Wealth management / financial planning firms — unrelated
- Mortgage / lending — different customer
- Crypto / blockchain payment companies

---

### SIGNAGE

#### Who qualifies
Signage companies that actively sell storefront signs, vehicle wraps, and exterior branding to **local businesses** — new business openings, rebrands, retail stores, restaurants.

**Target profile:**
- Sells physical exterior signage and vehicle wraps to local businesses
- 1–50 employees
- Titles: owner, sales, account manager

**Disqualifiers:**
- Digital signage / display companies (trade shows, enterprise)
- Print shops that only do business cards, flyers, brochures (not exterior signage)
- Web design / digital marketing agencies (different product)
- Large national sign manufacturers (not cold calling local restaurants)

---

### CRE (Sales segment — not PLG)

#### Who qualifies
Commercial real estate brokers and landlords focused on **retail leasing** — finding tenants for retail spaces, strip malls, mixed-use. They need to find local businesses that are opening or expanding.

**Target profile:**
- Retail-focused leasing (NOT office-only, NOT industrial-only, NOT residential)
- 1–500 employees (this segment goes higher)
- Titles: broker, leasing agent, VP leasing, principal, owner

**Disqualifiers:**
- Residential real estate (Realtors) — different market entirely
- Industrial / warehouse only
- Office only (their tenants are not local consumer businesses)
- Property management only (reactive, not prospecting)

---

## Apollo Filter Principles (Apply to All Segments)

1. **Never use broad industry keywords alone** — "commercial insurance" or "cleaning services" catches too much. Always combine with context that indicates LOCAL BUSINESS focus.
2. **Employee count 1–50** for most PLG segments (owner is doing the prospecting). Go up to 200 only if the segment supports a larger sales team doing cold outreach.
3. **Exclude captive/franchise networks** where reps have assigned territories and don't cold prospect.
4. **Title filter must match who actually does the prospecting** — not just the CEO of a 200-person company.
5. **Post-filter by company name** to exclude known large nationals and franchises.
