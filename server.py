#!/usr/bin/env python3
"""Local dev server with proxy endpoints to bypass CORS/Cyberhaven.

Endpoints:
  GET /             — serves static files
  GET /sanity?stop= — queries Met's Sanity CMS API
  GET /proxy?url=   — fetches any URL server-side
  GET /moma?stop=   — uses Playwright to bypass Cloudflare + extract MoMA audio
  GET /frick?stop=  — uses Playwright to search Frick eMuseum + extract audio
"""
import http.server
import json
import os
import re
import urllib.parse
import urllib.request

PORT = 8000

# MoMA audio extraction via Playwright (lazy-loaded)
_playwright = None
_browser = None

MOMA_AUDIO_EXTRACT_JS = """() => {
    var sources = [];
    document.querySelectorAll('audio').forEach(a => {
        if (a.src) sources.push(a.src);
        if (a.currentSrc) sources.push(a.currentSrc);
        a.querySelectorAll('source').forEach(s => { if (s.src) sources.push(s.src); });
    });
    document.querySelectorAll('[data-audio-src],[data-src]').forEach(el => {
        var src = el.getAttribute('data-audio-src') || el.getAttribute('data-src');
        if (src && /\\.(mp3|m4a|wav|aac)/i.test(src)) sources.push(src);
    });
    document.querySelectorAll('script').forEach(s => {
        var m = (s.textContent || '').match(/https?:\\/\\/[^"'\\s]+\\.(mp3|m4a|wav|aac)/gi);
        if (m) m.forEach(u => sources.push(u));
    });
    return [...new Set(sources)];
}"""


def get_browser():
    """Lazy-init Playwright browser (reused across requests)."""
    global _playwright, _browser
    if _browser is None:
        from playwright.sync_api import sync_playwright

        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch(
            channel="chrome", headless=True, args=["--headless=new"]
        )
        print("[Playwright] Browser launched")
    return _browser


def fetch_moma_audio(stop_number):
    """Use Playwright to look up a MoMA stop number via their audio guide search.

    MoMA's audio page has a lookup form: /audio/?stop_number=XXX
    which redirects to the correct playlist/stop URL (e.g., /audio/playlist/297/4587).
    The stop_number is the museum label number (e.g., 338), NOT the playlist index.
    """
    import time

    browser = get_browser()
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        viewport={"width": 1280, "height": 720},
    )
    page = context.new_page()
    page.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
    )

    # Use MoMA's own stop number lookup
    url = f"https://www.moma.org/audio/?stop_number={stop_number}"
    print(f"[MoMA] Looking up stop {stop_number} via {url}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except Exception:
        pass

    # Wait for Cloudflare challenge to resolve
    for _ in range(10):
        if "moment" not in page.title().lower():
            break
        time.sleep(1)

    title = page.title()
    final_url = page.url
    print(f"[MoMA] Title: {title}")
    print(f"[MoMA] Final URL: {final_url}")

    result = None
    if (
        "not found" not in title.lower()
        and "moment" not in title.lower()
        and "audio guides" not in title.lower()
    ):
        # Page loaded a specific stop — extract audio
        try:
            audio_urls = page.evaluate(MOMA_AUDIO_EXTRACT_JS)
        except Exception:
            audio_urls = []

        if audio_urls:
            clean_title = re.sub(r"\s*\|\s*MoMA\s*$", "", title)
            result = {
                "audioUrl": audio_urls[0],
                "title": clean_title,
                "allUrls": audio_urls,
                "resolvedUrl": final_url,
            }

    context.close()
    return result


def fetch_frick_audio(stop_number):
    """Use Playwright to search Frick's eMuseum by audio number and extract audio URL.

    Frick's eMuseum at collections.frick.org/search/{number} JS-redirects to
    the object detail page with #showAudios-{number}. The audio tab must be
    clicked to reveal the <audio> element with a dispatcher URL (audio/mpeg).
    """
    browser = get_browser()
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        viewport={"width": 1280, "height": 720},
    )
    page = context.new_page()

    url = f"https://collections.frick.org/search/{stop_number}"
    print(f"[Frick] Looking up audio number {stop_number} via {url}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=12000)
    except Exception:
        pass

    # Wait for JS redirect to object detail page (up to 5s)
    try:
        page.wait_for_url("**/objects/details/**", timeout=5000)
    except Exception:
        pass

    title = page.title()
    final_url = page.url
    print(f"[Frick] Title: {title}")
    print(f"[Frick] Final URL: {final_url}")

    result = None
    if "showAudios" in final_url or "/objects/details/" in final_url:
        # Click the audio tab to reveal the <audio> element
        try:
            audio_tab = page.query_selector(
                'a[href*="audioVideoBlock"], a[href*="showAudios"]'
            )
            if audio_tab:
                audio_tab.click()
                # Wait for audio element to appear (up to 3s)
                page.wait_for_selector("audio[src]", timeout=3000)
        except Exception:
            pass

        # Extract audio URL from <audio> elements
        audio_urls = page.evaluate(
            """() => {
            var sources = [];
            document.querySelectorAll('audio').forEach(a => {
                if (a.src) sources.push(a.src);
                if (a.currentSrc) sources.push(a.currentSrc);
                a.querySelectorAll('source').forEach(s => { if (s.src) sources.push(s.src); });
            });
            return [...new Set(sources)];
        }"""
        )

        if audio_urls:
            clean_title = re.sub(r"\s*[–-]\s*Works\s*[–-].*$", "", title).strip()
            result = {
                "audioUrl": audio_urls[0],
                "title": clean_title,
                "allUrls": audio_urls,
                "resolvedUrl": final_url,
            }

    context.close()
    return result


class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/proxy":
            self.handle_proxy(parsed)
        elif parsed.path == "/sanity":
            self.handle_sanity(parsed)
        elif parsed.path == "/moma":
            self.handle_moma(parsed)
        elif parsed.path == "/frick":
            self.handle_frick(parsed)
        else:
            super().do_GET()

    def handle_proxy(self, parsed):
        params = urllib.parse.parse_qs(parsed.query)
        url = params.get("url", [None])[0]
        if not url:
            self.send_error(400, "Missing url parameter")
            return
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
                self.send_response(200)
                self.send_header(
                    "Content-Type", resp.headers.get("Content-Type", "text/html")
                )
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)
        except Exception as e:
            self.send_response(502)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(str(e).encode())

    def handle_sanity(self, parsed):
        params = urllib.parse.parse_qs(parsed.query)
        stop = params.get("stop", [None])[0]
        if not stop:
            self.send_error(400, "Missing stop parameter")
            return
        query = f'*[stopNumber=="{stop}"][0]{{title,"audioUrl":file.asset->url}}'
        sanity_url = (
            "https://cctd4ker.apicdn.sanity.io/v2023-05-03/data/query/production"
            f"?query={urllib.parse.quote(query)}"
        )
        try:
            req = urllib.request.Request(sanity_url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)
        except Exception as e:
            self.send_response(502)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(str(e).encode())

    def handle_moma(self, parsed):
        """Use Playwright headless Chrome to fetch MoMA audio (bypasses Cloudflare)."""
        params = urllib.parse.parse_qs(parsed.query)
        stop = params.get("stop", [None])[0]
        if not stop:
            self.send_error(400, "Missing stop parameter")
            return

        print(f"[MoMA] Fetching audio for stop {stop} via Playwright...")
        try:
            result = fetch_moma_audio(stop)
            if result:
                print(f"[MoMA] Found: {result['audioUrl'][:80]}")
                payload = json.dumps({"result": result}).encode()
                self.send_response(200)
            else:
                print(f"[MoMA] No audio found for stop {stop}")
                payload = json.dumps(
                    {"result": None, "error": "Stop not found"}
                ).encode()
                self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(payload)
        except Exception as e:
            print(f"[MoMA] Error: {e}")
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def handle_frick(self, parsed):
        """Use Playwright to search Frick eMuseum and extract audio."""
        params = urllib.parse.parse_qs(parsed.query)
        stop = params.get("stop", [None])[0]
        if not stop:
            self.send_error(400, "Missing stop parameter")
            return

        print(f"[Frick] Fetching audio for stop {stop} via Playwright...")
        try:
            result = fetch_frick_audio(stop)
            if result:
                print(f"[Frick] Found: {result['audioUrl'][:80]}")
                payload = json.dumps({"result": result}).encode()
                self.send_response(200)
            else:
                print(f"[Frick] No audio found for stop {stop}")
                payload = json.dumps(
                    {"result": None, "error": "Stop not found"}
                ).encode()
                self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(payload)
        except Exception as e:
            print(f"[Frick] Error: {e}")
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def log_message(self, format, *args):
        if not args or not isinstance(args[0], str):
            return
        path = args[0].split()[1] if " " in args[0] else ""
        if (
            path.startswith("/proxy")
            or path.startswith("/sanity")
            or path.startswith("/moma")
            or path.startswith("/frick")
        ):
            super().log_message(format, *args)


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    with http.server.HTTPServer(("", PORT), ProxyHandler) as httpd:
        print(f"Museum Audio Tour server: http://localhost:{PORT}")
        httpd.serve_forever()
