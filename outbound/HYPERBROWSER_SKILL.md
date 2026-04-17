# Hyperbrowser Scraping & Automation Infrastructure

**Master reference for all browser automation, web scraping, and bot-protected site access.**

Hyperbrowser runs real cloud Chromium instances with stealth, residential proxies, CAPTCHA solving,
persistent profiles, and full computer-level control. MCP server configured in `.mcp.json`.
API key: `HYPERBROWSER_API_KEY` in `.env`. Python SDK: `pip install hyperbrowser playwright curl_cffi && playwright install chromium`.

### Quick Start
- **Scraping a protected site (Akamai, DataDome)?** → Section 2: Fetch API with `stealth="ultra"`
- **Simple public page?** → Section 3: MCP tool `scrape_webpage`
- **Need a real browser session (login, forms)?** → Section 4: Pattern B (Playwright CDP)
- **Not sure which tool?** → Section 1: Decision Tree

### Table of Contents
1. [Decision Tree — Pick Your Tool](#section-1-decision-tree--pick-your-tool)
2. [Fetch API (Primary Tool for Protected Sites)](#section-2-fetch-api-primary-tool-for-protected-sites)
3. [The 10 MCP Tools](#section-3-the-10-mcp-tools)
4. [Python SDK Patterns (A–D)](#section-4-python-sdk-patterns)
5. [Session Options Reference](#section-5-session-options-reference-complete)
6. [Computer Actions API](#section-6-computer-actions-api)
7. [Sandboxes API (Full VM Isolation)](#section-7-sandboxes-api-full-vm-isolation)
8. [Anti-Detection Playbook (4 Tiers)](#section-8-anti-detection-playbook)
9. [Profile Inventory](#section-9-profile-inventory)
10. [Cost Reference](#section-10-cost-reference)
11. [Existing Usage in This Repo](#section-11-existing-usage-in-this-repo)
12. [LoopNet Architecture (Reference Example)](#section-12-loopnet-architecture-reference-example)
13. [Troubleshooting](#section-13-troubleshooting)

---

## Section 1: Decision Tree — Pick Your Tool

Work top-to-bottom. Use the first approach that fits.

```
Need data from the web?
│
├─ Clean REST/JSON API exists? ──► requests directly. Zero cost.
│
├─ OpenAI web search sufficient? ──► Use that. Cheaper, no browser needed.
│
├─ Apify has a proven actor for this target? ──► Check first. Fall back to HB if unreliable.
│
└─ Need a real browser? Continue:
   │
   ├─ Static/lightly dynamic page, no login, site isn't aggressively blocking?
   │   └──► scrape_webpage MCP ($0.001/page)
   │
   ├─ Need to follow links across multiple pages?
   │   └──► crawl_webpages MCP ($0.001/page)
   │
   ├─ Need structured JSON from page(s) and site isn't heavily protected?
   │   └──► extract_structured_data MCP ($0.001/page + AI tokens)
   │
   ├─ Site has moderate bot protection (Cloudflare Turnstile, reCAPTCHA)?
   │   └──► Any of the above + sessionOptions: useStealth+useProxy+solveCaptchas
   │
   ├─ Site has HEAVY bot protection (Akamai, DataDome, PerimeterX)?
   │   └──► **Fetch API with stealth="ultra"** (PROVEN on LoopNet/Akamai)
   │       • `client.web.fetch(FetchParams(url=..., stealth="ultra", ...))`
   │       • Handles TLS fingerprinting that MCP tools and browser agents can't
   │       • Add location for geo-targeted proxy: country="US", state="FL"
   │       • Returns markdown/html/json — parse with regex or AI extraction
   │       • Cost: ~1 credit/page (vs 20/step for browser_use_agent)
   │       • If Fetch API still blocked → curl_cffi with impersonate="chrome136"
   │       • browser_use_agent is LAST RESORT for Akamai (20 credits/step, often fails)
   │
   ├─ Authenticated session / need to stay logged in across many runs?
   │   └──► Python SDK + Playwright CDP + persistent profile (Pattern B below)
   │       One-time login → saved profile → reuse forever
   │
   ├─ Complex multi-step workflow, accuracy critical?
   │   ├─ claude_computer_use_agent (best reasoning, full-screen vision)
   │   └─ openai_computer_use_agent (enterprise-grade, slower but reliable)
   │
   ├─ Need pixel-precise human-like mouse movements / keyboard control?
   │   └──► Python SDK + Computer Actions API (Section 6)
   │       Explicit move_mouse → click → type_text at coordinates
   │
   └─ Need full isolated VM environment (run code, expose ports, multi-process)?
       └──► Sandboxes API (Section 7) — full Linux container
```

**When NOT to use Hyperbrowser:**
- Site serves data via public API → just call the API
- Data is already in BigQuery / Apollo / Clay → query those first
- OpenAI web search resolves it → faster and cheaper

**Cost ladder (100 pages):**
| Approach | ~Cost | When |
|----------|-------|------|
| `web.fetch` (no stealth) | ~$0.10 | Public pages, fastest |
| `web.fetch` stealth="ultra" | ~$0.50 | **Akamai/DataDome protected. USE THIS FIRST.** |
| scrape_webpage MCP | ~$0.10 | Public, no bot protection |
| extract_structured_data MCP | ~$0.40 | Need structured fields, no bot protection |
| browser_use_agent (5 steps each) | ~$10 | Interactive workflows, form fills, multi-step nav |
| claude_computer_use_agent | ~$15–30 | Complex visual tasks, last resort |

**CRITICAL COST RULE:** Always start with `web.fetch` before reaching for agents.
A `browser_use_agent` run costs 20–100x more per page than `web.fetch`.

---

## Section 2: Fetch API (Primary Tool for Protected Sites)

**This is the #1 tool for scraping bot-protected sites.** The Fetch API has its own `stealth="ultra"`
mode that handles TLS fingerprint spoofing — the layer that MCP tools and browser agents fail at.

**Proven on:** LoopNet (Akamai Enterprise), tested 2026-04-16.

### Basic Usage

```python
from hyperbrowser import Hyperbrowser
from hyperbrowser.models.web.fetch import FetchParams
from hyperbrowser.models.web.common import (
    FetchBrowserOptions,
    FetchNavigationOptions,
    FetchBrowserLocationOptions,
    FetchOutputOptions,
)

client = Hyperbrowser(api_key=os.getenv("HYPERBROWSER_API_KEY"))

result = client.web.fetch(FetchParams(
    url="https://www.loopnet.com/search/retail-space/miami-fl/for-lease/",
    stealth="ultra",                          # THE KEY — TLS-level stealth
    browser=FetchBrowserOptions(
        solve_captchas=True,
        location=FetchBrowserLocationOptions(country="US", state="FL"),
    ),
    navigation=FetchNavigationOptions(
        wait_until="networkidle",             # Wait for SPA hydration
        timeout_ms=30000,
    ),
    outputs=FetchOutputOptions(
        html=True,
        markdown=True,
    ),
))

# Response is a FetchResponse (Pydantic model)
print(result.status)           # "completed" or "failed"
print(result.error)            # None on success
print(result.data.markdown)    # Full page as markdown
print(result.data.html)        # Raw HTML
print(result.data.links)       # Extracted links
print(result.data.screenshot)  # Base64 screenshot
print(result.data.json_)       # Structured JSON (if json_ output requested)
```

### FetchParams Reference

| Field | Type | Notes |
|-------|------|-------|
| `url` | str | Target URL (required) |
| `stealth` | `"none"` / `"auto"` / `"ultra"` | **Use `"ultra"` for Akamai/DataDome/PerimeterX** |
| `browser` | FetchBrowserOptions | Proxy location, CAPTCHA solving, profile, screen size |
| `navigation` | FetchNavigationOptions | `wait_until`, `timeout_ms`, `wait_for` |
| `outputs` | FetchOutputOptions | `html`, `markdown`, `links`, `screenshot`, `json_` |
| `cache` | FetchCacheOptions | `max_age_seconds` for response caching |

### FetchBrowserOptions

| Field | Type | Notes |
|-------|------|-------|
| `solve_captchas` | bool | Auto-solve CAPTCHAs |
| `location` | FetchBrowserLocationOptions | `country`, `state`, `city` — routes through geo-proxy |
| `profile_id` | str | Reuse a persistent profile (cookies, localStorage) |
| `screen` | ScreenConfig | `width`, `height` |

### Stealth Levels

| Level | What it does | When to use |
|-------|-------------|-------------|
| `"none"` | No stealth | Public sites, testing |
| `"auto"` | Standard anti-detection | Cloudflare basic, light WAFs |
| `"ultra"` | Full TLS fingerprint spoofing | **Akamai, DataDome, PerimeterX, any site that blocks browser agents** |

### Batch Fetching

```python
# Fetch multiple URLs in one call
results = client.web.batch_fetch(urls=[url1, url2, ...], stealth="ultra", ...)
```

### Also Available: `client.web.crawl()` and `client.web.search()`

Same API surface, same stealth options, for multi-page crawls and web search.

### Why Fetch API Beats Browser Agents for Protected Sites

| Factor | `web.fetch` stealth="ultra" | `browser_use_agent` |
|--------|----------------------------|---------------------|
| TLS fingerprint | Spoofed at handshake level | Not spoofed — standard Playwright Chromium |
| Cost per page | ~$0.005 | ~$0.40+ (20 credits/step × multiple steps) |
| Speed | 5-15 seconds | 30-120 seconds |
| Akamai success | **Yes (confirmed)** | **No (confirmed fail after 27 steps)** |
| When to use | Data extraction, scraping | Interactive workflows, form fills, logins |

---

## Section 3: The 10 MCP Tools

Available in Claude Code as `mcp__hyperbrowser__*`.

---

### 1. `scrape_webpage`
Single URL → markdown, html, links, or screenshot.

| Param | Required | Notes |
|-------|----------|-------|
| `url` | yes | Target URL |
| `outputFormat` | yes | Array: `["markdown"]`, `["html"]`, `["links"]`, `["screenshot"]`, or combo |
| `sessionOptions` | no | See Section 5 |

**Cost:** $0.001/page (+$0.009 with proxy)

---

### 2. `crawl_webpages`
Follow links from a start URL across multiple pages.

| Param | Required | Notes |
|-------|----------|-------|
| `url` | yes | Start URL |
| `outputFormat` | yes | Same as scrape_webpage |
| `followLinks` | yes | Usually true |
| `maxPages` | no | Default 10, max 100 |
| `ignoreSitemap` | no | Skip sitemap traversal |
| `sessionOptions` | no | |

**Cost:** $0.001/page crawled

---

### 3. `extract_structured_data`
AI-powered HTML → typed JSON matching a schema you define.

| Param | Required | Notes |
|-------|----------|-------|
| `urls` | yes | Array of URLs |
| `prompt` | yes | Extraction instruction |
| `schema` | no | JSON Schema for output type |
| `sessionOptions` | no | |

**Cost:** $0.001/page + $0.030/1M output tokens

---

### 4. `search_with_bing`
Web search returning title, URL, snippet per result.

| Param | Required | Notes |
|-------|----------|-------|
| `query` | yes | Up to 500 chars |
| `numResults` | no | Default 10, max 50 |

**Advanced filters:** `exactPhrase`, `excludeTerms`, `boostTerms`, `site`, `fileType`, `titleMatches`, `urlMatches`

**Cost:** $0.005–$0.01/search

---

### 5. `browser_use_agent`
Fast lightweight browser automation. Best cost/performance for most tasks.

| Param | Default | Notes |
|-------|---------|-------|
| `task` | — | Natural language. Be very explicit and step-by-step. |
| `llm` | `gemini-2.0-flash` | Also: `gpt-5.4`, `gpt-5.4-mini`, `claude-sonnet-4-6`, `gemini-2.5-flash` |
| `maxSteps` | 25 | Budget cap. 1 step ≈ $0.02 |
| `useVision` | true | Screenshot analysis. Keep enabled for complex layouts. |
| `validateOutput` | false | Validate result against schema |
| `maxActionsPerStep` | 10 | Actions per LLM step |
| `plannerLlm` | — | Separate model for planning (use cheaper model here) |
| `pageExtractionLlm` | — | Separate model for extraction |
| `initialActions` | — | Pre-task setup actions array |
| `sensitiveData` | — | `{"PASSWORD": "actual-val"}` — masked from LLM, injected at runtime |
| `keepBrowserOpen` | false | Reuse session: pass `sessionId` in next call |
| `sessionId` | — | Attach to existing open session |
| `returnStepInfo` | false | Return step-by-step debug info (verbose, use only when debugging) |
| `sessionOptions` | — | See Section 5 |

**Cost:** ~$0.02/step

---

### 6. `openai_computer_use_agent`
Full-screen computer vision automation via OpenAI CUA. Slower but very capable.

| Param | Default | Notes |
|-------|---------|-------|
| `task` | — | Natural language |
| `llm` | `gpt-5.4` | Also: `gpt-5.4-mini` |
| `maxSteps` | 20 | |
| `maxFailures` | 3 | Consecutive failures before abort |
| `useComputerAction` | false | Enable full-screen interaction (not just DOM elements) |
| `keepBrowserOpen` | false | |
| `sessionId` | — | |
| `useCustomApiKeys` | false | Use your own OpenAI key to reduce credit cost |
| `sessionOptions` | — | |

---

### 7. `claude_computer_use_agent`
Best reasoning, full-screen vision. Use when accuracy matters most.

| Param | Default | Notes |
|-------|---------|-------|
| `task` | — | Natural language |
| `llm` | `claude-sonnet-4-5` | Also: `claude-opus-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5-20251001` |
| `maxSteps` | 20 | |
| `maxFailures` | 3 | |
| `useComputerAction` | false | Full-screen (not just page) — enable for elements outside Playwright reach |
| `keepBrowserOpen` | false | |
| `sessionId` | — | |
| `useCustomApiKeys` | false | Use your own Anthropic key |
| `sessionOptions` | — | |

**Cost:** Token-based. Haiku is ~3x cheaper than Sonnet; use Haiku for simple vision tasks.

---

### 8–10. Profile Management
`create_profile`, `list_profiles`, `delete_profile` — see Section 9.

---

## Section 4: Python SDK Patterns

```bash
pip install hyperbrowser playwright && playwright install chromium
```

---

### Pattern A: Simple REST Scrape

```python
import os
from hyperbrowser import Hyperbrowser
from dotenv import load_dotenv

load_dotenv()
client = Hyperbrowser(api_key=os.getenv("HYPERBROWSER_API_KEY"))

# Scrape a page
result = client.scrape.start_and_wait(
    url="https://example.com/page",
    scrape_options={"formats": ["markdown"]},
    session_options={"use_stealth": True, "accept_cookies": True}
)
print(result.data.markdown)

# Extract structured data
result = client.extract.start_and_wait(
    urls=["https://example.com/listing/123"],
    prompt="Extract: address, broker name, broker email, square footage",
    schema={
        "type": "object",
        "properties": {
            "address":      {"type": "string"},
            "broker_name":  {"type": "string"},
            "broker_email": {"type": "string"},
            "sqft":         {"type": "number"},
        }
    }
)
print(result.data)
```

**Async client:**
```python
from hyperbrowser import AsyncHyperbrowser
async_client = AsyncHyperbrowser(api_key=os.getenv("HYPERBROWSER_API_KEY"))
result = await async_client.scrape.start_and_wait(...)
```

**Batch scrape (Scale plan — up to 1,000 URLs):**
```python
result = client.scrape.start_and_wait(urls=[url1, url2, ...url1000])
```

---

### Pattern B: Playwright CDP + Persistent Profile (Authenticated Sessions)

Use when you need full browser control and repeat authenticated access. Already used in `x_hb_login.py` / `x_dm.py`.

```python
import asyncio, aiohttp, ssl, os
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv()
HB_API_KEY = os.getenv("HYPERBROWSER_API_KEY")
PROFILE_ID = "your-profile-uuid"


def make_ssl():
    ctx = ssl.create_default_context()
    ctx.load_verify_locations("/etc/ssl/cert.pem")
    return ctx


async def create_session(profile_id: str, stealth=True, proxy=False,
                          os_spoof="windows", device="desktop") -> tuple[str, str, str]:
    connector = aiohttp.TCPConnector(ssl=make_ssl())
    async with aiohttp.ClientSession(
        headers={"x-api-key": HB_API_KEY}, connector=connector
    ) as s:
        body = {
            "profile": {"id": profile_id, "persistChanges": True, "persistSessionCookies": True},
            "useStealth": stealth,
            "solveCaptchas": True,
            "acceptCookies": True,
            "adblock": True,
            "annoyances": True,
            "operatingSystems": [os_spoof],   # "windows" | "macos" | "linux" | "android" | "ios"
            "device": [device],               # "desktop" | "mobile"
            "platform": ["chrome"],           # "chrome" | "firefox" | "safari" | "edge"
            "locales": ["en-US"],
        }
        if proxy:
            body["useProxy"] = True
            body["proxyCountry"] = "US"
        async with s.post("https://app.hyperbrowser.ai/api/session", json=body) as r:
            if r.status != 200:
                raise RuntimeError(f"Session create failed: {r.status} {await r.text()}")
            data = await r.json()
            return data["id"], data["wsEndpoint"], data.get("liveUrl", "")


async def stop_session(session_id: str) -> bool:
    connector = aiohttp.TCPConnector(ssl=make_ssl())
    async with aiohttp.ClientSession(
        headers={"x-api-key": HB_API_KEY}, connector=connector
    ) as s:
        async with s.put(
            f"https://app.hyperbrowser.ai/api/session/{session_id}/stop"
        ) as r:
            return r.status == 200


async def run(profile_id: str):
    session_id, ws_url, live_url = await create_session(profile_id, proxy=True)
    print(f"Watch live: {live_url}")  # paste in browser to observe in real time
    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(ws_url)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await context.new_page()

            # Session warm-up: visit a neutral page before the target
            await page.goto("https://www.google.com", wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(2000)

            # Navigate to target
            await page.goto("https://target-site.com", wait_until="networkidle", timeout=45000)
            content = await page.content()
            await browser.close()
            return content
    finally:
        await stop_session(session_id)  # ALWAYS stop — sessions cost $0.10/hr

asyncio.run(run(PROFILE_ID))
```

**Key rules:**
- Always `stop_session` in `finally` block
- `wait_until="networkidle"` for JS SPAs — waits for XHR to settle
- `liveUrl` lets you watch the session in any browser tab (invaluable for debugging)
- `persistChanges: True` auto-saves login state back to the profile on stop
- `react_fill()` pattern for React inputs — use `press_sequentially()` not `fill()` (see `x_hb_login.py`)

---

### Pattern C: Organic Navigation (Fallback for Interactive Workflows)

> **Try `web.fetch(stealth="ultra")` first (Section 2).** It handles Akamai/DataDome
> at the TLS level for ~$0.005/page. Pattern C is for cases where you need interactive
> browser control (form fills, multi-step navigation, authenticated actions) and the
> target site also has heavy bot protection. It costs 100x more per page.

Heavy bot detectors (Akamai, DataDome) check referrer headers. Traffic that arrives
directly to a target URL from a datacenter looks suspicious. Traffic that arrives
via a Google search click looks human. Use this pattern when you need a real browser
session AND the site has bot protection.

```python
from hyperbrowser import Hyperbrowser
from hyperbrowser.models import StartBrowserUseTaskParams, CreateSessionParams

client = Hyperbrowser(api_key=os.getenv("HYPERBROWSER_API_KEY"))

task = """
1. Go to https://www.bing.com
2. Search for: "miami retail space for lease loopnet"
3. Wait for search results to load
4. Click the LoopNet result — do NOT extract href and navigate, click the actual element
5. If a new tab opens, switch to it and wait for full load
6. Extract all property listings: address, size, asking rent, broker name
7. Return as JSON array
"""

result = client.agents.browser_use.start_and_wait(
    StartBrowserUseTaskParams(
        task=task,
        max_steps=30,
        use_vision=True,
        session_options=CreateSessionParams(
            use_stealth=True,
            use_proxy=True,
            proxy_country="US",
            proxy_state="FL",
            solve_captchas=True,
            accept_cookies=True,
            adblock=True,
            annoyances=True,
            operating_systems=["windows"],
            platform=["chrome"],
            device=["desktop"],
        ),
    )
)

# IMPORTANT: result.data is a BrowserUseTaskData Pydantic object — NOT a dict.
# Use attribute access, never .get():
steps = result.data.steps if result.data else []          # list of step objects
final = result.data.final_result if result.data else ""   # the agent's summary string

print(f"Status: {result.status}  Steps: {len(steps)}")
print(f"Result: {final}")
```

This sets the Referer header to Bing and gives the session a realistic browsing history.

**SDK response structure:** `result` is a `BrowserUseTaskResponse` with:
- `result.status` — `"completed"` or `"failed"`
- `result.error` — error message or `None`
- `result.data` — `BrowserUseTaskData` Pydantic object (NOT a dict — `.get()` fails)
  - `result.data.steps` — list of step objects, each with `.action`, `.result`
  - `result.data.final_result` — string summary produced by the agent
- `result.metadata` — `{"input_tokens": N, "output_tokens": N, "num_task_steps_completed": N}`

---

### Pattern D: Human-Like Computer Actions

For sites that use behavioral analysis (mouse path entropy, click velocity, etc.).
Uses the Computer Actions API for pixel-level control with realistic movements.

```python
import asyncio, aiohttp, ssl, os, random, math
from playwright.async_api import async_playwright

async def human_move(page, from_x, from_y, to_x, to_y, steps=20):
    """Simulate a curved human-like mouse movement between two points."""
    for i in range(steps + 1):
        t = i / steps
        # Ease in-out curve (not linear)
        eased = t * t * (3 - 2 * t)
        # Small random jitter
        jitter_x = random.uniform(-2, 2) if 0 < i < steps else 0
        jitter_y = random.uniform(-2, 2) if 0 < i < steps else 0
        x = int(from_x + (to_x - from_x) * eased + jitter_x)
        y = int(from_y + (to_y - from_y) * eased + jitter_y)
        await page.mouse.move(x, y)
        await page.wait_for_timeout(random.randint(8, 25))

async def human_click(page, x, y):
    await human_move(page, x - random.randint(50, 200), y - random.randint(20, 80), x, y)
    await page.wait_for_timeout(random.randint(80, 200))
    await page.mouse.click(x, y)

async def human_scroll(page, amount=500):
    """Scroll in small increments like a human reading."""
    steps = random.randint(3, 7)
    for _ in range(steps):
        await page.mouse.wheel(0, amount // steps)
        await page.wait_for_timeout(random.randint(100, 400))
```

**When to use:** Sites that measure mouse entropy, dwell time, or scroll patterns
(some DataDome configurations, behavioral-analysis WAFs). Note: Akamai blocks at
the TLS fingerprint level *before* behavioral analysis matters — use
`web.fetch(stealth="ultra")` for Akamai, not mouse simulation.

---

## Section 5: Session Options Reference (Complete)

All fields for `sessionOptions` in MCP tools, or the session body in Pattern B.
**Python SDK uses snake_case; REST API / MCP use camelCase.**

### Stealth & Anti-Detection
| Field | Type | Notes |
|-------|------|-------|
| `useStealth` | bool | Standard anti-detection. Use for any site with login or rate limits. |
| `useUltraStealth` | bool | Enterprise-only (returns 402 on non-enterprise plans). **For Akamai-class sites, use `web.fetch(stealth="ultra")` instead — it works on all plans.** |

### Browser Identity Spoofing
| Field | Type | Notes |
|-------|------|-------|
| `operatingSystems` | string[] | `"windows"`, `"macos"`, `"linux"`, `"android"`, `"ios"` — match your target audience |
| `device` | string[] | `"desktop"`, `"mobile"` |
| `platform` | string[] | `"chrome"`, `"firefox"`, `"safari"`, `"edge"` |
| `locales` | string[] | ISO locale codes. Default: `["en-US"]`. Match proxy location. |
| `screen` | object | `{"width": 1280, "height": 720}` — keep at 1280×720, larger causes model degradation |

### Proxy
| Field | Type | Notes |
|-------|------|-------|
| `useProxy` | bool | Enable managed residential proxy pool |
| `proxyCountry` | string | ISO code or `"RANDOM_COUNTRY"` for max randomization |
| `proxyState` | string | US two-letter code (mutually exclusive with `proxyCity`) |
| `proxyCity` | string | City name (mutually exclusive with `proxyState`) |
| `region` | string | Server region: `us-central`, `us-west`, `us-east`, `asia-south`, `europe-west` |
| `staticIpId` | string | UUID from dashboard — sticky IP. Requires `useProxy: true`. |
| `proxyServer` | string | Bring your own: `"socks5://proxy.example.com:1080"` |
| `proxyServerUsername` | string | Custom proxy auth |
| `proxyServerPassword` | string | Custom proxy auth |

**Rotating vs static:** Use rotating (`useProxy`) for bulk scraping. Use `staticIpId` for
authenticated sessions where IP changes mid-session trigger "new device" flags.

### CAPTCHA & Blocking
| Field | Type | Notes |
|-------|------|-------|
| `solveCaptchas` | bool | Auto-solve: reCAPTCHA v2/v3, hCaptcha, Cloudflare Turnstile, image CAPTCHAs |
| `imageCaptchaParams` | object[] | Custom image CAPTCHA: `[{"imageSelector": ".img", "inputSelector": "#input"}]` |
| `acceptCookies` | bool | Auto-dismiss GDPR/cookie banners |
| `adblock` | bool | Block ads — speeds page loads, less fingerprinting surface |
| `trackers` | bool | Block tracking pixels |
| `annoyances` | bool | Block popups, modals, newsletter overlays |
| `urlBlocklist` | string[] | Block specific URLs during session |

### Profile & State
| Field | Type | Notes |
|-------|------|-------|
| `profile.id` | string | Profile UUID — session starts already logged in |
| `profile.persistChanges` | bool | Save session state back to profile on stop (default: true) |
| `profile.persistNetworkCache` | bool | Also persist HTTP cache (request access from HB) |

### Recording & Debug
| Field | Type | Notes |
|-------|------|-------|
| `enableWebRecording` | bool | rrweb DOM recording — replay in browser with rrweb-player |
| `enableVideoWebRecording` | bool | MP4 video. Requires `enableWebRecording: true`. |
| `viewOnlyLiveView` | bool | Read-only live view — share URL without giving control |

### Advanced
| Field | Type | Notes |
|-------|------|-------|
| `extensionIds` | string[] | Load custom Chrome extensions (upload via Extensions API first) |
| `browserArgs` | string[] | Raw Chromium flags e.g. `["--disable-web-security"]` |
| `disablePostQuantumKeyAgreement` | bool | TLS fingerprint adjustment |
| `timeoutMinutes` | number | 1–720. Default varies by plan. |
| `saveDownloads` | bool | Keep files downloaded during session |
| `disablePasswordManager` | bool | Suppress password manager popup |
| `enableAlwaysOpenPdfExternally` | bool | Force PDF download instead of in-browser view |

---

## Section 6: Computer Actions API

**This is Hyperbrowser's human behavior simulation layer.** Direct pixel-level
control: click at exact coordinates, type text, press key combos, move mouse,
drag, scroll. Combine with Pattern D (human-like movements) to pass behavioral
analysis.

```python
# Get a session first (Pattern B), then use the REST endpoints directly
# OR use the Python SDK after creating a session

# SDK methods on client object:
client.computer_action.click(session_id, x=500, y=300,
    button="left",   # "left" | "right" | "middle" | "back" | "forward" | "wheel"
    click_count=1,
    return_screenshot=False)

client.computer_action.move_mouse(session_id, x=500, y=300)

client.computer_action.drag(session_id,
    coordinates=[{"x": 100, "y": 100}, {"x": 200, "y": 200}])

client.computer_action.scroll(session_id, x=500, y=300, scroll_x=0, scroll_y=100)

client.computer_action.type_text(session_id, text="search query", return_screenshot=False)

client.computer_action.press_keys(session_id,
    keys=["Control_L", "a"])   # xdotool format

screenshot_b64 = client.computer_action.screenshot(session_id)
```

**Session response also includes `computerActionEndpoint`** — the raw REST endpoint
for these actions if you prefer not to use the SDK.

**Use case:** Akamai v3 measures mouse entropy (path randomness), dwell time,
and scroll behavior. If stealth + proxy isn't enough, implement human-like
patterns with the Computer Actions API (see `human_move()` in Pattern D).

---

## Section 7: Sandboxes API (Full VM Isolation)

Sandboxes are full Linux containers — not just browsers. They run arbitrary code,
expose ports, have filesystems, process management, and snapshots. Use when you
need to run a complete scraping workflow in an isolated environment, execute
downloaded files, or build multi-step data pipelines that combine scraping + processing.

```python
# Create a sandbox VM
sandbox = client.sandboxes.create(CreateSandboxParams(
    image_name="node",       # or "python", "ubuntu", etc.
    cpu=4,
    memory_mib=4096,
    disk_mib=8192,
    region="us-west",
    timeout_minutes=30,
    enable_recording=True,
    exposed_ports=[SandboxExposeParams(port=3000, auth=True)]
))

# Execute a command
result = sandbox.exec(
    "python scraper.py --city Miami --limit 100",
    cwd="/app", env={"HYPERBROWSER_API_KEY": "..."}, timeout_ms=300000
)

# File operations
sandbox.files.write_text("/app/scraper.py", script_content)
output = sandbox.files.read_text("/app/results.json")

# Expose a port (e.g., run a headless scraper with API)
exposure = sandbox.expose(SandboxExposeParams(port=8080, auth=True))
url = sandbox.get_exposed_url(8080)

# Snapshots — resume from a checkpoint
snapshot = sandbox.create_memory_snapshot(SandboxMemorySnapshotParams(
    snapshot_name="after-login"
))

# Connect to existing sandbox
sandbox = client.sandboxes.connect(sandbox_id)

# Stop
sandbox.stop()
```

**When to use sandboxes:**
- Multi-stage pipeline: scrape → process → store in a single isolated run
- Run untrusted downloaded content safely
- Long-running jobs that need to survive disconnects (with snapshots)
- Parallel scraping workers (one sandbox per worker)

---

## Section 8: Anti-Detection Playbook

### Tier 1: Basic (works for most sites)
```python
sessionOptions = {
    "useStealth": True,
    "acceptCookies": True,
    "adblock": True,
    "annoyances": True,
}
```

### Tier 2: Standard (Cloudflare, reCAPTCHA, moderate blocking)
```python
sessionOptions = {
    "useStealth": True,
    "useProxy": True,
    "proxyCountry": "US",
    "solveCaptchas": True,
    "acceptCookies": True,
    "adblock": True,
    "annoyances": True,
    "operatingSystems": ["windows"],
    "platform": ["chrome"],
    "device": ["desktop"],
    "locales": ["en-US"],
}
```

### Tier 3: Heavy (Akamai, DataDome, PerimeterX)
**Start here:** `web.fetch(stealth="ultra")` — handles TLS fingerprint spoofing that
browser agents and MCP tools cannot do. Confirmed working on Akamai Enterprise (LoopNet).

```python
result = client.web.fetch(FetchParams(
    url="https://protected-site.com/data",
    stealth="ultra",
    browser=FetchBrowserOptions(
        solve_captchas=True,
        location=FetchBrowserLocationOptions(country="US", state="FL"),
    ),
    navigation=FetchNavigationOptions(wait_until="networkidle", timeout_ms=30000),
    outputs=FetchOutputOptions(markdown=True),
))
```

**If you also need interactive browser control** (form fills, login, multi-step nav)
on a Tier 3 site, THEN use browser agents with organic navigation (Pattern C) as a fallback.

### Tier 4: Maximum (curl_cffi fallback — no Hyperbrowser credits needed)
If `web.fetch(stealth="ultra")` doesn't work, `curl_cffi` with TLS impersonation
bypasses at the same level with zero Hyperbrowser credits:

```python
from curl_cffi import requests
session = requests.Session()
resp = session.get(url, impersonate="chrome136", headers={...})
```

See github.com/johnstenner/LoopnetMCP for a production example.

### What Hyperbrowser DOES vs DOESN'T do automatically

| Capability | Status | Notes |
|-----------|--------|-------|
| Browser fingerprint consistency | ✅ Built-in stealth | User-Agent, WebGL, Canvas, timezone aligned |
| Residential proxy pool | ✅ `useProxy: true` | Residential IPs, 100+ countries |
| CAPTCHA solving | ✅ `solveCaptchas: true` | reCAPTCHA, hCaptcha, Turnstile, image |
| OS/browser spoofing | ✅ `operatingSystems`/`platform` | Explicit opt-in |
| Auto-accept cookie banners | ✅ `acceptCookies: true` | |
| **Human mouse movements** | ❌ NOT automatic | Must implement via Computer Actions + Pattern D |
| **Organic referrer (from Google)** | ❌ NOT automatic | Must write it into agent task |
| **Session warm-up** | ❌ NOT automatic | Must navigate neutral pages manually |
| **TLS fingerprint spoofing** | ✅ Fetch API `stealth="ultra"` | Handles JA3/JA4 — the key to Akamai/DataDome bypass |
| **Akamai/DataDome/PerimeterX** | ✅ Via Fetch API | `web.fetch(stealth="ultra")` confirmed working on LoopNet (Akamai Enterprise) |
| **Self-recovery from detection** | ❌ Not built-in | Implement retry logic with different session config |

---

## Section 9: Profile Inventory

Profiles persist indefinitely. All team profiles documented here.

| Profile ID | Site | Purpose | Script |
|-----------|------|---------|--------|
| `1840e338-62d6-4e56-9d86-8324488282e8` | X / Twitter | DM sending | `x_hb_login.py` (login), `x_dm.py` (use) |
| *(not needed)* | LoopNet | Public data via Fetch API — no profile needed | `scrape_loopnet.py` |

**Create a new profile (run in Claude Code):**
```
Use mcp__hyperbrowser__create_profile with name="loopnet-prod"
→ Returns profile UUID — add to table above and to scraping script
```

**Naming convention:** `{site}-{env}` e.g. `loopnet-prod`, `crexi-dev`

**Refresh expired session:** Re-run login script with same `profile_id` and `persistChanges: True`.
New cookies overwrite old ones.

---

## Section 10: Cost Reference

**1 credit = $0.001**

| Operation | Credits | Cost |
|-----------|---------|------|
| **web.fetch (stealth="ultra")** | **~5/page** | **~$0.005** |
| web.fetch (no stealth) | ~1/page | ~$0.001 |
| scrape_webpage (no proxy) | 1/page | $0.001 |
| scrape_webpage (with proxy) | 10/page | $0.010 |
| extract_structured_data | 1/page + 30/1M tokens | $0.001 + AI tokens |
| crawl_webpages | 1/page | $0.001 |
| browser_use_agent | 20/step | $0.020/step |
| claude_computer_use haiku | token-based | ~$0.005/step |
| claude_computer_use sonnet | token-based | ~$0.015/step |
| openai CUA (gpt-5.4) | token-based | ~$0.020/step |
| Browser session (Playwright) | 100/hour | $0.10/hr |
| Proxy data | 10,000/GB | $10.00/GB |
| search_with_bing | 5–10/search | $0.005–0.010 |

**Concurrency limits:**
| Plan | Concurrent browsers |
|------|-------------------|
| Free | 1 |
| Startup | 25 |
| Scale | 100 (+ batch scrape up to 1,000 URLs) |
| Enterprise | 1,000+ (sub-ms latency, 99.9% uptime) |

---

## Section 11: Existing Usage in This Repo

| Script | Pattern | Purpose |
|--------|---------|---------|
| `x_hb_login.py` | B (Playwright CDP + profile) | One-time X login, save to profile. Run when session expires. |
| `x_dm.py` | B (Playwright CDP + profile) | Send DMs to X commenters via saved profile |
| `scrape_loopnet.py` | Fetch API (`stealth="ultra"`) | LoopNet listing data — working, tested 2026-04-16 |

**Patterns to steal from existing scripts:**
- `react_fill()` in `x_hb_login.py` — how to type into React inputs without DOM manipulation
- Session health check on entry (`x_dm.py` line 131) — verify still logged in before doing work
- Resume-safe checkpoint loop (`x_dm.py` line 196) — checkpoint every N items

**MCP tools in Claude Code:**
All 10 tools available as `mcp__hyperbrowser__*`. Use them directly in conversation — e.g.:
`"Use mcp__hyperbrowser__extract_structured_data on these URLs with this schema..."`

---

## Section 12: LoopNet Architecture (Reference Example)

LoopNet is protected by **Akamai Enterprise** (deployed by CoStar group-wide).
**Verified 2026-04-16:** `web.fetch(stealth="ultra")` bypasses Akamai. 579 listings returned, 66K markdown.

### What works
| Approach | Result |
|----------|--------|
| **`web.fetch(stealth="ultra")`** | **579 listings, 66K markdown, full page content** |
| `web.fetch(stealth="ultra")` + FL proxy | Same — confirmed working with geo-location |

### What was tested and failed (for reference — avoid these for Akamai)
| Approach | Result | Why it failed |
|----------|--------|---------------|
| `scrape_webpage` MCP with `useStealth` | Access Denied | No TLS fingerprint spoofing |
| `browser_use_agent` with all sessionOptions | Blocked after 27 steps | Playwright Chromium has known TLS fingerprint |
| Python SDK + Playwright CDP + organic Bing nav | Access Denied | Same TLS issue at handshake level |
| `useUltraStealth` on session | 402 Payment Required | Enterprise plan only |

**Root cause:** Akamai detects at the TLS handshake level (JA3/JA4 fingerprint) before any
HTTP request completes. Standard Playwright Chromium has a distinctive TLS fingerprint that
Akamai blocklists. The Fetch API's `stealth="ultra"` spoofs TLS fingerprints at a lower level
than sessions/agents can, which is why it succeeds where everything else fails.

### Working LoopNet scraper pattern
```python
from hyperbrowser import Hyperbrowser
from hyperbrowser.models.web.fetch import FetchParams
from hyperbrowser.models.web.common import (
    FetchBrowserOptions, FetchNavigationOptions,
    FetchBrowserLocationOptions, FetchOutputOptions,
)

client = Hyperbrowser(api_key=os.getenv("HYPERBROWSER_API_KEY"))

result = client.web.fetch(FetchParams(
    url="https://www.loopnet.com/search/retail-space/miami-fl/for-lease/",
    stealth="ultra",
    browser=FetchBrowserOptions(
        solve_captchas=True,
        location=FetchBrowserLocationOptions(country="US", state="FL"),
    ),
    navigation=FetchNavigationOptions(wait_until="networkidle", timeout_ms=30000),
    outputs=FetchOutputOptions(markdown=True),
))

# result.data.markdown contains full page as markdown — parse with regex
# For pagination: append /{page}/ to URL (e.g. .../for-lease/2/)
```

### Important implementation lessons

**Fetch API > Agents for protected sites.** The Fetch API handles TLS-level stealth
that browser agents and MCP tools cannot. For any Akamai/DataDome/PerimeterX site,
always try `web.fetch(stealth="ultra")` first. It's ~100x cheaper than browser agents.

**MCP sessionOptions ≠ full API:** MCP tools only expose 5 sessionOptions fields
(`useStealth`, `useProxy`, `solveCaptchas`, `acceptCookies`, `profile`). Everything
else requires the Python SDK or REST API directly.

**Fallback: curl_cffi.** If `web.fetch` is unavailable, `curl_cffi` with
`impersonate="chrome136"` handles TLS fingerprint spoofing locally (see
github.com/johnstenner/LoopnetMCP for a working implementation).

**BQ output schema:** `SLG_OUTBOUND.LOOPNET_LISTINGS` — full schema in `scrape_loopnet.py`.

---

## Section 13: Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Access Denied` / Akamai reference # | TLS fingerprint detected | **Use `web.fetch(stealth="ultra")` — not agents or MCP tools.** This handles TLS-level spoofing. |
| Still blocked with `web.fetch` stealth="auto" | Stealth level too low | Upgrade to `stealth="ultra"` — this adds full TLS fingerprint spoofing |
| `browser_use_agent` blocked on Akamai site | Playwright Chromium TLS fingerprint | Switch to `web.fetch(stealth="ultra")`. Agents can't fix TLS-level detection. |
| Akamai challenge page ("checking browser") | Bot detection triggered | `web.fetch(stealth="ultra")` with `solve_captchas=True` |
| Session returns empty / skeleton HTML | SPA not hydrated | `wait_until="networkidle"` instead of `domcontentloaded` |
| Login redirects back to login page | Profile session expired | Re-run login script with same `profile_id`, `persistChanges: True` |
| React input not registering | React-controlled input | Use `press_sequentially()` not `fill()` (see `react_fill()` in x_hb_login.py) |
| Rate limited after N pages | IP flagged for volume | Reduce parallelism to 2–3 concurrent sessions, add delays |
| CAPTCHA loop (solves then re-triggers) | Missing proxy for CAPTCHA | Enable `useProxy: true` alongside `solveCaptchas: true` |
| `wsEndpoint` refused | Session didn't start cleanly | Check API key, retry — check `liveUrl` first to verify session is alive |
| Session cost accumulating | Forgot to stop | Always `stop_session` in `finally` block |
| PDF downloaded instead of viewed | Wanted in-browser PDF view | Set `enableAlwaysOpenPdfExternally: false` |
| Agent fails on complex page | Task instruction too vague | Be explicit: list every step, every element to find, every action to take |
| MCP tool rejects sessionOptions field | MCP schema only supports 5 fields | Use Python SDK / REST API for `operatingSystems`, `adblock`, etc. Or use `web.fetch` API which has its own stealth. |
| Bing click doesn't navigate to target | Link opened new tab | Use `context.wait_for_event("page")` to catch new tab; switch `page` reference to it |
| Screenshot times out on blocked page | Akamai/Cloudflare page loads external fonts | Wrap in `try/except`, pass `timeout=5000`, use `clip={"x":0,"y":0,"width":800,"height":400}` |
| LoopNet always Access Denied | Using wrong tool (agents/MCP) | Use `web.fetch(stealth="ultra")` — confirmed working 2026-04-16 |
| `AttributeError: 'BrowserUseTaskData' object has no attribute 'get'` | `result.data` is Pydantic, not dict | Use `result.data.steps` and `result.data.final_result` — attribute access only |
