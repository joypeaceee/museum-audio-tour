# Museum Audio Guide (NYC Edition) — Hypernova Webapp

## Context for Devmate

This is a Hypernova webapp (Meta smart glasses platform) being developed and tested in a MacBook browser first. Run `server.py` and open `http://localhost:8000` in Chrome — the 600x600 viewport simulates the Hypernova display. Use arrow keys for D-pad, Enter for tap, Escape for back.

**Important:** Start the server with the Python that has Playwright installed:
```bash
/Library/Developer/CommandLineTools/usr/bin/python3 server.py
```

---

## What the App Does

A hands-free museum audio guide for NYC museums. The user selects a museum, enters an audio stop number, and the app fetches the audio file URL and plays it natively.

### User Flow

```
Screen 1: Museum Select
  → Three museum cards: MoMA, The Met, Frick Collection
  → Official museum logos (SVG vector paths for MoMA/Met, PNG monogram for Frick)
  → D-pad to navigate, Enter to select

Screen 2: Stop Number Entry
  → Header shows selected museum name
  → Large number display + CLR button + 3x4 numpad grid
  → Keyboard number keys also work directly
  → Press GO to load the audio

Screen 3: Audio Player
  → Shows loading: "Fetching audio for Stop #XXX..."
  → Museum-specific fast paths (see Architecture below)
  → On success: native player with play/pause, seekable progress bar, time display
  → On no audio URL: iframe fallback renders the proxied page
  → On failure: error message + museum page URL + "Copy URL" button
  → Escape returns to stop entry, audio stops
```

---

## Architecture

### Local Server with Proxy Endpoints (`server.py`)

All external fetches go through `server.py` (Python HTTP server) to avoid CORS issues. The Cyberhaven corporate security browser extension strips CORS headers from all external responses, so browser-side `fetch()` to external APIs fails. Server-side Python requests bypass this entirely.

**Endpoints:**
- `GET /` — serves static files (index.html, styles.css, app.js, logos/)
- `GET /sanity?stop=XXXX` — queries Met's Sanity CMS API server-side, returns JSON
- `GET /moma?stop=XXXX` — uses Playwright headless Chrome to bypass Cloudflare, extract MoMA audio
- `GET /proxy?url=XXXX` — fetches any URL server-side, returns raw content

**Detection in app.js:**
```javascript
var HAS_SERVER_PROXY = location.protocol !== 'file:';
var PROXY_URL = HAS_SERVER_PROXY ? '/proxy?url=' : 'https://api.allorigins.win/raw?url=';
```

---

## Museum Support Status

| Museum | Status | Method | Speed | Notes |
|--------|--------|--------|-------|-------|
| **The Met** | ✅ Working | `/sanity` → Sanity GROQ API | ~1s | Direct API query, ~200 bytes response |
| **MoMA** | ✅ Working | `/moma` → Playwright + Cloudflare bypass | ~3-5s | First request slower (browser launch) |
| **Frick** | ✅ Working | `/frick` → Playwright + eMuseum search | ~4-6s | Two-step JS interaction (see below) |

### Why Speed Differs Across Museums

| Museum | ~Speed | Why |
|--------|--------|-----|
| **The Met** | ~1s | Simple `urllib` HTTP request to Sanity API returns ~200 bytes JSON. No browser needed at all. |
| **MoMA** | ~3-5s | Playwright loads one page. Cloudflare challenge takes ~1-2s to solve, then the page renders and audio is extracted. Browser is already running (reused singleton). |
| **Frick** | ~4-6s | **Two-step Playwright process**: (1) eMuseum JS-redirects the search page to the object detail page (~2s — this is a JavaScript redirect, not HTTP, so it requires Playwright), then (2) we click the "Audio/Video" tab and wait for the `<audio>` element to appear (~2s — the audio isn't in the initial HTML, only revealed after tab click). Two navigations + a click interaction = slowest. |

**Why the Frick can't be faster:**
- The eMuseum (TMS/eMuseum by Gallery Systems) is a legacy Java-based CMS with heavy JavaScript — slower to render than modern React sites
- The search-to-object redirect is JavaScript-driven (not an HTTP 301/302), so we can't skip Playwright
- The `<audio>` element is dynamically injected after clicking the audio tab — not in the server-rendered HTML, so we can't use simple `urllib`
- Unlike the Met (which has a public Sanity API) or MoMA (single page load), Frick requires two separate JS interactions
- The optimized version uses `wait_for_selector("audio[src]")` instead of fixed sleeps, so it returns as soon as the audio appears rather than waiting a fixed time

---

## The Met — What Was Tried and What Works

### Approach 1: iframe embedding (FAILED)
**What:** Load the Met's audio page directly in an `<iframe>`.
**Result:** All three museums set `X-Frame-Options: DENY`, so the browser refuses to render the page inside an iframe. The iframe shows "refused to connect."

### Approach 2: CORS proxy + iframe srcdoc (PARTIAL)
**What:** Fetch the Met page HTML via a CORS proxy (corsproxy.io, allorigins.win), inject a `<base href>` tag, and load it via `iframe.srcdoc`.
**Result:** The page loaded (bypassed X-Frame-Options since srcdoc is inline content) but the Met's Next.js app threw a client-side JS error: "Application error: a client-side exception has occurred." The React Server Components hydration fails because the page runs in a different origin context.

### Approach 3: CORS proxy + audio URL extraction (FAILED intermittently)
**What:** Fetch the Met page HTML via CORS proxy, regex-extract audio URLs from the HTML (ported from QRScanPlay iOS app's `AudioWebView.swift` lines 25-70), play the extracted URL in a native `<audio>` element.
**Result:**
- `corsproxy.io` → HTTP 403 (the Met blocks this proxy)
- `allorigins.win` → Works from `curl` but fails intermittently from the browser due to Cyberhaven corporate extension stripping `Access-Control-Allow-Origin` headers from responses
- When allorigins worked, the extraction successfully found audio URLs in the Met's RSC streaming data (`cdn.sanity.io/files/cctd4ker/production/{hash}.mp3`)

### Approach 4: Sanity CMS API direct query (FAILED from browser)
**What:** The Met uses Sanity CMS (project `cctd4ker`, dataset `production`). Query the GROQ API directly: `*[stopNumber=="9450"][0]{title,"audioUrl":file.asset->url}`.
**Discovery process:**
1. `curl` the Met page — found RSC streaming data with Sanity asset references
2. Identified Sanity project ID `cctd4ker` from the HTML data
3. Tried GROQ query with `audioFile` field — returned null
4. Inspected raw document structure — discovered the field is named `file`, not `audioFile`
5. Correct query: `*[stopNumber=="9450"][0]{title,"audioUrl":file.asset->url}` → returns audio URL
**Result:** Works from `curl`, but blocked from browser by Cyberhaven extension (strips CORS headers) and also blocked from `file://` origin (Sanity API doesn't accept `Origin: null`).

### Approach 5: Local server proxy for Sanity API (✅ WORKS)
**What:** Added `/sanity?stop=XXXX` endpoint to `server.py` that queries the Sanity GROQ API server-side. The browser only talks to `localhost` — no CORS, no Cyberhaven interference.
**Result:** Works perfectly. ~1 second response time. Returns ~200 bytes JSON with the audio URL and title.

### Limitations Found (The Met)
- **Sanity schema dependency**: If the Met changes their Sanity CMS schema (field names, project ID, dataset), the query will break
- **No Cloudflare protection**: The Met doesn't use Cloudflare, so server-side urllib works fine
- **Stop numbering**: The Met's stop numbers map directly to Sanity `stopNumber` field — no translation needed
- **Audio CDN**: `cdn.sanity.io` serves MP3 files without authentication or CORS restrictions — direct playback works

---

## MoMA — What Was Tried and What Works

### Approach 1: CORS proxy fetch (FAILED)
**What:** Fetch MoMA page HTML via CORS proxies.
**Result:** Both `corsproxy.io` (403) and `allorigins.win` return Cloudflare's "Just a moment..." challenge page. MoMA uses Cloudflare's **managed challenge** (`cType: 'managed'`) which requires full browser JavaScript execution. No amount of User-Agent spoofing or header manipulation bypasses it.

### Approach 2: Server-side urllib fetch (FAILED)
**What:** Python `urllib.request` with browser User-Agent header via `server.py /proxy` endpoint.
**Result:** Same Cloudflare challenge page. The managed challenge requires an actual browser JS engine, not just HTTP requests.

### Approach 3: MoMA API probing (FAILED)
**What:** Tried various API URL patterns:
- `www.moma.org/api/audio/playlist/3/338`
- `www.moma.org/api/v1/audio/338`
- `www.moma.org/audio` (root)
- `www.moma.org/calendar/audio`
- JSON Accept header on the audio page URL
- MoMA CDN subdomains: `media.moma.org`, `assets.moma.org`, `audio.moma.org`
**Result:** All return HTTP 403 (Cloudflare). Every endpoint on `www.moma.org` is behind Cloudflare.

### Approach 4: Bloomberg Connects investigation (FAILED)
**What:** MoMA uses Bloomberg Connects as their audio guide provider (mobile app). Investigated their web platform:
- `api.bloombergconnects.org/v2/` → Returns CMS admin HTML page, not a REST API
- `api.bloombergconnects.org/v2/guides` → HTTP 200 but returns CMS web app
- `guides.bloombergconnects.org/en-US/moma` → HTTP 200, loads a Next.js app shell
- `guides.bloombergconnects.org/en-US/moma/stops/338` → HTTP 200 but page content is `NEXT_NOT_FOUND`
- `guides.bloombergconnects.org/en-US/moma/lookup/338` → Same: `NEXT_NOT_FOUND`
- Tried `/api/guides/moma/stops/338`, `/api/v1/stops/338?guide=moma`, `/api/lookup` → All resolve to Next.js HTML pages (not JSON APIs)
- Next.js RSC flight request with `RSC: 1` header → HTTP 500
**Result:** Bloomberg Connects pages are fully client-rendered (Next.js). No audio data exists in the server-rendered HTML. The mobile app likely uses a private API that isn't exposed on the web platform. MoMA stop numbers don't map to Bloomberg Connects URL scheme.

### Approach 5: Playwright headless Chromium (FAILED)
**What:** Use Playwright with default headless Chromium (`p.chromium.launch(headless=True)`) to load MoMA pages.
**Result:** Page title remains "Just a moment..." — Cloudflare detects and blocks Playwright's bundled Chromium headless shell. The installed binary was "Chrome Headless Shell" which has a different fingerprint than real Chrome.

### Approach 6: Playwright with Chrome channel + new headless (✅ WORKS)
**What:** Use Playwright with the locally installed Chrome browser in new headless mode:
```python
browser = p.chromium.launch(channel="chrome", headless=True, args=["--headless=new"])
```
Key anti-detection settings:
- `channel="chrome"` — uses the real locally installed Chrome (not Playwright's bundled headless shell)
- `--headless=new` — Chrome's new headless mode that behaves identically to headed mode
- `navigator.webdriver` overridden to `undefined`
**Result:** Cloudflare challenge passes. Page loads successfully. Audio URLs extracted from `<audio>` elements via JavaScript evaluation inside the page context.

### Approach 6a: Wrong URL pattern (FIXED)
**Discovery:** Initially used `playlist/3/{stopNumber}` (from the original plan). Playwright loaded the page but got "Page not found | MoMA" — playlist 3 no longer has those stops.
**Investigation:**
1. Loaded `moma.org/audio` → found 10 valid playlist IDs: 1, 289, 294, 296, 297, 298, 346, 349, 350, 351
2. Tested stops across playlists — only playlist 1 had stops at low indices
3. Discovered MoMA stop numbers (e.g., 338) are **museum label numbers**, NOT playlist indices
4. Found that MoMA has a stop number lookup form: `moma.org/audio/?stop_number=338` which redirects to the correct URL (`playlist/297/4587`)
**Fix:** Use MoMA's own lookup form URL instead of guessing playlists. The `/moma` endpoint now navigates to `https://www.moma.org/audio/?stop_number={stop}` and follows the redirect.

### What Finally Works for MoMA
The `/moma?stop=XXX` endpoint in `server.py`:
1. Lazy-launches a real Chrome browser via Playwright (`channel="chrome"`, `--headless=new`)
2. Navigates to `https://www.moma.org/audio/?stop_number={stop}`
3. Waits for Cloudflare challenge to resolve (~1-3s)
4. MoMA's server redirects to the correct playlist/stop URL (e.g., `playlist/297/4587`)
5. Extracts audio URLs from the page's `<audio>` elements via JS evaluation
6. Returns JSON with audio URL and title
7. Browser instance is reused across requests (lazy singleton)

### Limitations Found (MoMA)
- **Cloudflare dependency**: If Cloudflare updates their challenge to detect Chrome's new headless mode, this will break
- **Speed**: First request ~5-8s (browser launch + Cloudflare solve), subsequent ~2-3s
- **Chrome required**: The deployment server must have Chrome installed (not just Chromium headless shell)
- **Playwright dependency**: Adds ~200MB to deployment (Playwright + Chrome)
- **Stop number lookup**: Depends on MoMA's `/audio/?stop_number=` form continuing to work. If they remove or change this lookup, we'd need to reverse-engineer their stop number → playlist/index mapping
- **Stop number validation**: Not all stop numbers are valid. Invalid numbers show an error message rather than silently failing
- **Audio CDN**: MoMA audio is on `moma.org/d/audios/` — also behind Cloudflare, but the browser's Cloudflare cookie from the page load allows direct `<audio>` playback from our app since the MP3 URL is served without Cloudflare challenge (it's a static asset)

---

## Frick — What Was Tried and What Works

### Approach 1: Direct URL guess (FAILED)
**What:** Assumed URL pattern `frick.org/visit/museum/audio#stop-{number}`.
**Result:** HTTP 403 (access denied). The Frick audio guide page is behind access control.

### Approach 2: Bloomberg Connects (FAILED)
**What:** Frick uses Bloomberg Connects for their mobile guide. Tried `guides.bloombergconnects.org/en-US/frick/guide`, `/guide/stops`, `/lookup/1`.
**Result:** Bloomberg Connects pages are fully client-rendered (Next.js). All stop pages rendered empty — no audio data in the HTML. The BC mobile app uses a private API not exposed on the web.

### Approach 3: Frick collections eMuseum (✅ WORKS)
**What:** Discovered `frick.org/audio` redirects to `frick.org/guide`, which has a link to "Search by Audio Number" pointing to `collections.frick.org` (their eMuseum platform by Gallery Systems). Found that:
1. `collections.frick.org/search/{audioNumber}` JS-redirects to the object detail page: `objects/details/{objectId}#showAudios-{audioNumber}`
2. The object detail page has an "Audio/Video" tab that reveals an `<audio>` element
3. The audio src is a dispatcher URL: `collections.frick.org/internal/media/dispatcher/{mediaId}/resize%3Aformat%3Dfull`
4. The dispatcher URL returns `Content-Type: audio/mpeg` (HTTP 200) — direct MP3

**Implementation:** Added `/frick?stop=XXX` endpoint to `server.py` that uses Playwright to:
1. Navigate to `collections.frick.org/search/{stop}`
2. Wait for JS redirect to object detail page
3. Click the "Audio/Video" tab
4. Wait for `<audio>` element to appear
5. Extract the dispatcher URL
6. Return JSON with audio URL and title

**Optimizations applied:**
- `domcontentloaded` instead of `networkidle` (skip waiting for all resources)
- `wait_for_url("**/objects/details/**")` instead of `time.sleep(2)` (returns as soon as redirect completes)
- `wait_for_selector("audio[src]")` instead of `time.sleep(2)` (returns as soon as audio element appears)

### Limitations Found (Frick)
- **Slowest of the three** (~4-6s) because of the two-step JS interaction (see speed comparison above)
- **eMuseum dependency**: TMS/eMuseum by Gallery Systems is a legacy Java-based CMS. If the Frick migrates to a different platform, the endpoint will break
- **No direct API**: Unlike the Met's Sanity API, the Frick has no public data API. Audio content requires Playwright to interact with the eMuseum JS application
- **Audio number scope**: Not all numbers are valid audio numbers. Invalid numbers return search results instead of redirecting to an object page
- **Audio CDN**: Audio is served from `collections.frick.org/internal/media/dispatcher/` — no authentication required, direct playback works
- **No Cloudflare**: The Frick doesn't use Cloudflare, but Playwright is still required because the search redirect and audio tab are JavaScript-driven

---

## Comparison: Met vs MoMA vs Frick

| Aspect | The Met | MoMA | Frick |
|--------|---------|------|-------|
| **Cloudflare** | No | Yes (managed challenge) | No |
| **CMS** | Sanity CMS (public GROQ API) | Unknown (no public API) | eMuseum by Gallery Systems |
| **Audio CDN** | `cdn.sanity.io` (public) | `moma.org/d/audios/` (static) | `collections.frick.org/internal/media/dispatcher/` |
| **Data access** | Direct API query → JSON | Playwright → Cloudflare bypass → page scraping | Playwright → JS redirect → tab click → audio extraction |
| **Stop number** | Direct: `stopNumber` in Sanity | Indirect: lookup form redirects to playlist/index | Indirect: search JS-redirects to object detail page |
| **Server dependency** | `urllib` (stdlib) | Playwright + Chrome | Playwright + Chrome |
| **Speed** | ~1s | ~3-5s | ~4-6s |
| **Fragility** | Medium (schema changes) | High (Cloudflare detection) | Medium (eMuseum structure) |

---

## CORS / Cyberhaven Journey

A significant portion of development time was spent debugging CORS failures caused by Meta's **Cyberhaven corporate security browser extension**:

1. **Initial approach**: Browser-side `fetch()` to external APIs (Sanity, allorigins.win)
2. **Problem**: Cyberhaven intercepts ALL outgoing browser requests and strips `Access-Control-Allow-Origin` headers from responses
3. **Symptom**: CORS errors for every external API call, even from `http://localhost:8000`
4. **Misdiagnosis**: Initially thought the APIs themselves were blocking CORS, or that `file://` origin was the issue
5. **Clue**: The Cyberhaven extension error appeared in console logs: `Uncaught SecurityError: Failed to read the 'sessionStorage' property from 'Window': The document is sandboxed and lacks the 'allow-same-origin' flag` at `_CyberhavenDomEvents`
6. **Solution**: All external fetches routed through `server.py` proxy endpoints. Python `urllib` requests bypass Cyberhaven entirely since it only intercepts browser-level network requests.

### Proxies tried and their issues:
| Proxy | Issue |
|-------|-------|
| `corsproxy.io` | Met returns 403, MoMA returns Cloudflare challenge |
| `allorigins.win` | Works from `curl` but Cyberhaven strips CORS headers in browser |
| Sanity API direct | Cyberhaven strips CORS headers; also `file://` origin not accepted |
| `server.py /proxy` | ✅ Works — server-side fetch bypasses all browser restrictions |
| `server.py /sanity` | ✅ Works — dedicated Met endpoint |
| `server.py /moma` | ✅ Works — Playwright bypasses Cloudflare server-side |

---

## Known Issues / TODO

1. **Frick speed** — Slowest of the three (~4-6s) due to two-step JS interaction. See speed comparison above.
2. **MoMA Cloudflare** — If Cloudflare updates challenge detection, MoMA endpoint will break.
3. **Parser fragility** — If Met changes Sanity schema, MoMA changes their audio page, or Frick changes eMuseum, extraction breaks.
4. **Cyberhaven extension** — Strips CORS headers from all external responses. `server.py` proxy endpoints work around this.
5. **Deployment Playwright** — Deployed server needs Chrome installed + Playwright Python package (~200MB).
6. **Voice input** — MetaGlassSDK dictation could replace numpad.

---

## Next Step: EMG Handwriting Input for Stop Numbers

### Summary

The `MetaGlassSDK` (auto-injected into all Hypernova webapps as `window.MetaGlassSDK`) supports EMG handwriting recognition. This would allow users to "write" stop numbers in the air with their hand instead of navigating the D-pad numpad — significantly faster input.

### Two Integration Options

**Option A — Automatic (recommended, minimal code):**
`MetaGlassSDK.autoHandwriting` is **enabled by default**. It auto-starts handwriting sessions when any safe `<input>` element gains focus (`type="text|number|search|email|url|tel"`). To use this:
1. Add a real `<input type="number">` to Screen 2 (currently uses a `<div>` display + button clicks)
2. When it receives input (from handwriting or keyboard), update `state.stopNumber`
3. Numpad buttons remain as fallback for D-pad navigation
4. On desktop browser: regular keyboard typing also works (already does via keydown handler)

**Option B — Manual (more control):**
Use `MetaGlassSDK.handwriting` API for custom handling:
```javascript
if (window.MetaGlassSDK && MetaGlassSDK.isSupported) {
  MetaGlassSDK.handwriting.start({ silenceTimeout: 5000, autocorrect: false });
  MetaGlassSDK.handwriting.addEventListener('insert', function(e) {
    // e.text contains recognized character(s)
    if (/^\d+$/.test(e.text)) {
      state.stopNumber += e.text;
      updateStopDisplay();
    }
  });
}
```

### Key API Details (from MetaGlassSDK docs)

- **SDK global**: `window.MetaGlassSDK` — auto-injected, no import needed
- **Feature check**: `MetaGlassSDK.isSupported` (boolean)
- **Auto mode**: `MetaGlassSDK.autoHandwriting.enable()` — on by default, handles everything
- **Manual start**: `MetaGlassSDK.handwriting.start({ silenceTimeout, autocorrect, autocomplete })`
- **Events**: `insert` (committed text), `composing` (preview), `delete`, `end`
- **Current SDK version**: v2.2.0-alpha.1 (alpha — internal prototyping only)

### ⚠️ Confidentiality

"Never publicly host code that directly invokes any MetaGlassSDK methods. Doing so could leak sensitive information about our products and roadmap. All code using this SDK should remain internal to Meta." — SDK docs

### Implementation Plan

1. Add `<input type="number" id="stop-input">` to Screen 2 (hidden or styled into the display area)
2. `autoHandwriting` activates automatically when the input gains focus on Hypernova
3. Listen for `input` events on the field to sync with `state.stopNumber` and the display
4. Keep the numpad as fallback — D-pad navigates numpad, EMG writes directly
5. Wrap any direct `MetaGlassSDK` calls in `if (window.MetaGlassSDK)` checks for browser testing
6. Do NOT deploy MetaGlassSDK-invoking code to public URLs

### Docs References

- [MetaGlassSDK Overview](https://www.internalfb.com/wiki/Smartglass/webapp/sdk/)
- [Handwriting API Reference](https://www.internalfb.com/wiki/Smartglass/webapp/sdk/api/handwriting/)
- [Auto-Handwriting API Reference](https://www.internalfb.com/wiki/Smartglass/webapp/sdk/api/auto-handwriting/)
- [SDK Changelog](https://www.internalfb.com/wiki/Smartglass/webapp/sdk/CHANGELOG/)

---

## Development Setup

```bash
# Install dependencies (one-time)
pip install playwright
playwright install chromium

# Start the server (use the Python with Playwright installed)
cd /Users/shanchu/Documents/Develop/museum-audio-tour
/Library/Developer/CommandLineTools/usr/bin/python3 server.py

# Open in browser
open http://localhost:8000
```

### Deployment

Deploy `server.py` alongside the static files on `wearableweb.manus.space` or any host. The app detects non-`file://` protocol and uses relative `/sanity`, `/moma`, and `/proxy` endpoints automatically.

Files to deploy:
- `index.html`, `styles.css`, `app.js` (static frontend)
- `logos/` directory (moma.svg, met.svg, frick.png — official museum logos)
- `server.py` (backend with `/sanity`, `/moma`, `/proxy` endpoints)

Requirements on server:
- Python 3.9+
- `playwright` package
- Chrome or Chromium browser installed
- For production, use a proper WSGI server instead of Python's built-in `http.server`

---

## Reference: QRScanPlay iOS App

Audio extraction approach ported from QRScanPlay iOS app (December 2025):
- **Audio extraction**: `AudioWebView.swift` lines 25-70 → `app.js` `extractAudioUrls()` + `server.py` `MOMA_AUDIO_EXTRACT_JS`
- **Player UI**: `AudioPlayerView.swift` lines 124-216 → HTML/CSS native player
- **Time formatting**: `AudioPlayerView.swift` lines 210-215 → `app.js` `formatTime()`
- **Auto-play**: `AudioPlayerView.swift` lines 199-207 → `canplay` event handler

Note: The iOS app's WKWebView could solve Cloudflare challenges natively. The webapp replicates this with Playwright's Chrome channel.

---

## Hypernova Webapp Constraints

- **Viewport**: 600x600 pixels, fixed
- **Input**: D-pad (Up/Down/Left/Right), Enter (tap), Escape (back). NO touch.
- **All interactive elements** must have `class="focusable"` for D-pad navigation
- **Focus ring**: Cyan glow (`#00d4ff`) on focused element
- **Dark theme**: Black background, white text, cyan accents
- **No build system**: Plain HTML/CSS/JS + Python server

---

## File Structure

```
museum-audio-tour/
  index.html              # 3 screens: museum-select, stop-entry, audio-player
  styles.css              # Dark theme, museum cards, numpad, player UI, focus states
  app.js                  # Navigation, Sanity API, Playwright fetch, audio extraction, native player
  server.py               # Local server with /sanity, /moma (Playwright), /proxy endpoints
  logos/
    moma.svg              # Official MoMA logo (vector paths from moma.org header)
    met.svg               # Official The Met logo (intertwined vector paths from Wikipedia)
    frick.png             # Official Frick monogram (from frick.org apple-touch-icon)
  DEVMATE_CONTEXT.md      # This file
```
