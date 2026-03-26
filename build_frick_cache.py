#!/usr/bin/env python3
"""Quick Frick cache builder - crawl Bloomberg Connects rooms, save incrementally."""
import json
import os
import re
import time

from playwright.sync_api import sync_playwright

CACHE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "cache", "frick.json"
)

# All Frick exhibition/room URLs from Bloomberg Connects (pre-scraped)
ROOMS = [
    ("0c1801c8-63ef-44f1-bf93-2cdc3b6e9dfa", "Entrance Hall"),
    ("e903e427-f3a2-4ea6-91db-e8b6dbbd38ff", "Reception Hall"),
    ("4f86e3e2-2502-4317-9a05-fcfc0945de1f", "East Vestibule"),
    ("3e9d5254-23dc-479e-adcf-7931670ba988", "Octagon Room"),
    ("a06fcf09-9e92-4deb-9468-86382f840998", "Anteroom"),
    ("23bd213b-a135-4050-9f79-43c4e41bc230", "Cabinet"),
    ("6c94a9cb-91c9-42b1-afef-801b15434962", "Dining Room"),
    ("4527a658-c561-491d-954a-ae36e87a68c8", "West Vestibule"),
    ("1e32f30a-14b2-4458-8e51-73dfb473d6dd", "Fragonard Room"),
    ("2a3eb431-7519-48df-843f-cc087487b986", "Living Hall"),
    ("47eae090-6a77-4f2e-90e9-21613121aee9", "Library"),
    ("ac125885-6a3e-40f1-b308-5442cc6c13a0", "Portico Gallery"),
    ("a6c69240-a695-4f43-96ae-20b38078d40b", "West Gallery"),
    ("9a771a87-e918-4213-b2ca-d6337ba15d2b", "Enamels Room"),
    ("5bb3cb81-13ae-4878-9033-8ea7d10eb7a1", "Oval Room"),
    ("609256c3-5ede-48a9-b819-f56366e6458f", "East Gallery"),
    ("35cf3eea-bcbb-4d4b-9eb1-cd27316ec5ce", "Garden Court"),
    ("cbe985cd-a2f3-43c6-8b62-16939b89c4b4", "North Hall"),
    ("cd430ff1-57db-40a5-a71d-6565ed6ff9ec", "South Hall"),
    ("9b3f1721-5e3e-4e81-a3fb-3178c71817a6", "Foot of Stairs"),
    ("0757c0d8-1a02-45fa-9d9f-eb74eb2d840e", "Grand Stair Hall"),
    ("568f5a30-43da-4191-a3dc-0ad70e6ce882", "Breakfast Room"),
    ("eb64c84d-16e0-4acb-b893-53c4af3f07b9", "Medals Room"),
    ("f463c944-9faf-4a04-a2ec-002c7522fa93", "Impressionist Room"),
    ("0fe9d7a2-4c71-42b2-a32e-19f1bff98138", "Small Hallway"),
    ("be55fe00-bf8f-4c25-8edd-0c93a910c459", "Du Paquier Passage"),
    ("6522deef-94ab-4413-a883-cdf157591ffa", "Ceramics Room"),
]

BASE = "https://guides.bloombergconnects.org/en-US/guide/frick"


def save(stops):
    with open(CACHE_FILE, "w") as f:
        json.dump(stops, f, indent=2)


def extract_stops(page):
    """Extract stop number and audio URL from current page."""
    return page.evaluate(
        """() => {
        var body = document.body.innerText;
        var numMatch = body.match(/#(\\d+)/);
        var num = numMatch ? numMatch[1] : null;
        var audio = [];
        document.querySelectorAll('audio').forEach(a => {
            if (a.src) audio.push(a.src);
        });
        var title = document.title.split('|')[0].trim();
        return {num: num, audio: audio, title: title};
    }"""
    )


with sync_playwright() as p:
    browser = p.chromium.launch(
        channel="chrome", headless=True, args=["--headless=new"]
    )
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    )
    page = ctx.new_page()
    stops = {}

    for room_id, room_name in ROOMS:
        url = f"{BASE}/exhibition/{room_id}"
        print(f"\n  Room: {room_name}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=10000)
            time.sleep(2)
        except:
            print("    timeout")
            continue

        # Get room-level audio
        data = extract_stops(page)
        if data["num"] and data["audio"]:
            stops[data["num"]] = {"url": data["audio"][0], "title": data["title"]}
            print(f"    ✓ #{data['num']}: {data['title'][:50]}")

        # Get item links
        items = page.evaluate(
            """() => {
            var results = [];
            document.querySelectorAll('a[href*="/item/"]').forEach(a => {
                var text = (a.textContent || '').trim().substring(0, 80);
                if (text.length > 2) results.push({href: a.href, text: text});
            });
            return results;
        }"""
        )

        for item in items:
            try:
                page.goto(item["href"], wait_until="domcontentloaded", timeout=8000)
                time.sleep(1)
                data = extract_stops(page)
                if data["num"] and data["audio"]:
                    stops[data["num"]] = {
                        "url": data["audio"][0],
                        "title": data["title"],
                    }
                    print(f"    ✓ #{data['num']}: {data['title'][:50]}")
            except:
                pass

        # Save after each room
        save(stops)

    # Also check the intro/guide items
    print("\n  Guide items...")
    for item_path in [
        "item/2d508e43-43b1-415e-9fd9-2c72bf1de10b",
    ]:
        try:
            page.goto(
                f"{BASE}/{item_path}", wait_until="domcontentloaded", timeout=8000
            )
            time.sleep(1)
            data = extract_stops(page)
            if data["num"] and data["audio"]:
                stops[data["num"]] = {"url": data["audio"][0], "title": data["title"]}
                print(f"    ✓ #{data['num']}: {data['title'][:50]}")
        except:
            pass

    save(stops)
    browser.close()

print(f"\nTotal: {len(stops)} stops")
print(f"Saved to {CACHE_FILE}")
