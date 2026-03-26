#!/usr/bin/env python3
"""Build audio cache JSON files for each museum.

Generates:
  cache/met.json   — from Sanity CMS API (fast, single query)
  cache/moma.json  — from Playwright crawl of MoMA playlists
  cache/frick.json — from Playwright crawl of Frick eMuseum

Run: /Library/Developer/CommandLineTools/usr/bin/python3 build_cache.py
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)


# ==================== THE MET (Sanity API — no Playwright needed) ====================


def build_met_cache():
    """Query Sanity API for ALL Met audio stops in one request."""
    print("\n========== THE MET ==========")
    query = '*[_type == "audioFile" && defined(stopNumber)]{stopNumber, title, "audioUrl": file.asset->url}'
    url = (
        "https://cctd4ker.apicdn.sanity.io/v2023-05-03/data/query/production"
        f"?query={urllib.parse.quote(query)}"
    )
    print(f"Querying Sanity API...")
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())

    stops = {}
    for item in data.get("result", []):
        num = str(item.get("stopNumber", "")).strip()
        audio_url = item.get("audioUrl")
        title = item.get("title", "")
        if num and audio_url:
            stops[num] = {"url": audio_url, "title": title}

    print(f"Found {len(stops)} stops")
    out_path = os.path.join(CACHE_DIR, "met.json")
    with open(out_path, "w") as f:
        json.dump(stops, f, indent=2)
    print(f"Saved to {out_path}")
    return stops


# ==================== MOMA (Playwright — Cloudflare bypass) ====================


def build_moma_cache():
    """Crawl MoMA audio playlists to find all valid stops."""
    from playwright.sync_api import sync_playwright

    print("\n========== MOMA ==========")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome", headless=True, args=["--headless=new"]
        )
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = ctx.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        )

        # First, get all playlist IDs from the audio index
        print("Loading MoMA audio index...")
        page.goto(
            "https://www.moma.org/audio", wait_until="domcontentloaded", timeout=20000
        )
        for _ in range(10):
            if "moment" not in page.title().lower():
                break
            time.sleep(1)

        playlist_ids = page.evaluate(
            """() => {
            var ids = [];
            document.querySelectorAll('a[href*="/audio/playlist/"]').forEach(a => {
                var m = a.href.match(/\\/audio\\/playlist\\/(\\d+)/);
                if (m) ids.push(parseInt(m[1]));
            });
            return [...new Set(ids)];
        }"""
        )
        print(f"Found playlist IDs: {playlist_ids}")

        # For each playlist, load it and get all stop links
        stops = {}
        for pid in playlist_ids:
            print(f"\n  Playlist {pid}...")
            page.goto(
                f"https://www.moma.org/audio/playlist/{pid}",
                wait_until="domcontentloaded",
                timeout=20000,
            )
            for _ in range(10):
                if "moment" not in page.title().lower():
                    break
                time.sleep(1)

            if "not found" in page.title().lower() or "moment" in page.title().lower():
                print(f"    Skipped (not found or Cloudflare)")
                continue

            # Get all stop links from the playlist page
            stop_links = page.evaluate(
                """() => {
                var results = [];
                document.querySelectorAll('a[href*="/audio/playlist/"]').forEach(a => {
                    var m = a.href.match(/\\/audio\\/playlist\\/\\d+\\/(\\d+)/);
                    if (m) {
                        var text = (a.textContent || '').trim().substring(0, 100);
                        results.push({stopId: m[1], text: text, href: a.href});
                    }
                });
                return results;
            }"""
            )
            print(f"    Found {len(stop_links)} stop links")

            # Visit each stop to get the audio URL and find the museum stop number
            for sl in stop_links:
                stop_id = sl["stopId"]
                try:
                    page.goto(sl["href"], wait_until="domcontentloaded", timeout=15000)
                    for _ in range(8):
                        if "moment" not in page.title().lower():
                            break
                        time.sleep(1)

                    if "not found" in page.title().lower():
                        continue

                    title = re.sub(r"\s*\|\s*MoMA\s*$", "", page.title())

                    audio_url = page.evaluate(
                        """() => {
                        var a = document.querySelector('audio');
                        return a ? (a.src || a.currentSrc || '') : '';
                    }"""
                    )

                    if audio_url:
                        # Extract the museum stop number from the title (e.g., "338 Forrest Bess...")
                        # or from the page content
                        stop_num = page.evaluate(
                            """() => {
                            // Look for the stop number in the page
                            var el = document.querySelector('.audio-player__number, [class*="stop-number"], [class*="audio-number"]');
                            if (el) return el.textContent.trim();
                            // Try URL-based: the stop_number query param
                            var url = new URL(window.location.href);
                            return '';
                        }"""
                        )

                        # Use playlist stop ID as key if no museum number found
                        key = (
                            stop_num
                            if stop_num and stop_num.isdigit()
                            else f"p{pid}s{stop_id}"
                        )
                        stops[key] = {"url": audio_url, "title": title}
                        print(f"    ✓ {key}: {title[:50]}")

                except Exception as e:
                    print(f"    ✗ stop {stop_id}: {e}")

        # Also try the stop_number lookup for common ranges
        print("\n  Trying stop number lookup (1-500)...")
        for num in range(1, 501):
            if str(num) in stops:
                continue
            url = f"https://www.moma.org/audio/?stop_number={num}"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=10000)
                for _ in range(6):
                    if "moment" not in page.title().lower():
                        break
                    time.sleep(1)

                title = page.title()
                if (
                    "not found" in title.lower()
                    or "audio guides" in title.lower()
                    or "moment" in title.lower()
                ):
                    continue

                clean_title = re.sub(r"\s*\|\s*MoMA\s*$", "", title)
                audio_url = page.evaluate(
                    """() => {
                    var a = document.querySelector('audio');
                    return a ? (a.src || a.currentSrc || '') : '';
                }"""
                )

                if audio_url:
                    stops[str(num)] = {"url": audio_url, "title": clean_title}
                    print(f"    ✓ {num}: {clean_title[:50]}")

            except Exception:
                pass

        browser.close()

    print(f"\nTotal MoMA stops: {len(stops)}")
    out_path = os.path.join(CACHE_DIR, "moma.json")
    with open(out_path, "w") as f:
        json.dump(stops, f, indent=2)
    print(f"Saved to {out_path}")
    return stops


# ==================== FRICK (Playwright — eMuseum crawl) ====================


def build_frick_cache():
    """Crawl Frick eMuseum audio-available collection for all stops."""
    from playwright.sync_api import sync_playwright

    print("\n========== FRICK ==========")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome", headless=True, args=["--headless=new"]
        )
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = ctx.new_page()

        # Try audio number lookup for range 1-500
        print("Trying audio number lookup (1-500)...")
        stops = {}
        for num in range(1, 501):
            url = f"https://collections.frick.org/search/{num}"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=10000)
                try:
                    page.wait_for_url("**/objects/details/**", timeout=4000)
                except Exception:
                    continue

                title = page.title()
                final_url = page.url
                if (
                    "showAudios" not in final_url
                    and "/objects/details/" not in final_url
                ):
                    continue

                # Click audio tab
                try:
                    audio_tab = page.query_selector(
                        'a[href*="audioVideoBlock"], a[href*="showAudios"]'
                    )
                    if audio_tab:
                        audio_tab.click()
                        page.wait_for_selector("audio[src]", timeout=3000)
                except Exception:
                    continue

                audio_url = page.evaluate(
                    """() => {
                    var a = document.querySelector('audio');
                    return a ? (a.src || a.currentSrc || '') : '';
                }"""
                )

                if audio_url:
                    clean_title = re.sub(
                        r"\s*[–-]\s*Works\s*[–-].*$", "", title
                    ).strip()
                    stops[str(num)] = {"url": audio_url, "title": clean_title}
                    print(f"  ✓ {num}: {clean_title[:50]}")

            except Exception:
                pass

        browser.close()

    print(f"\nTotal Frick stops: {len(stops)}")
    out_path = os.path.join(CACHE_DIR, "frick.json")
    with open(out_path, "w") as f:
        json.dump(stops, f, indent=2)
    print(f"Saved to {out_path}")
    return stops


# ==================== MAIN ====================

if __name__ == "__main__":
    print("Building audio cache for all museums...")
    print(f"Cache directory: {CACHE_DIR}")

    met = build_met_cache()
    moma = build_moma_cache()
    frick = build_frick_cache()

    print("\n========== SUMMARY ==========")
    print(f"The Met:  {len(met)} stops")
    print(f"MoMA:    {len(moma)} stops")
    print(f"Frick:   {len(frick)} stops")
    print(f"\nCache files saved to {CACHE_DIR}/")
