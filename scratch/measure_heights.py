import sys
import time
from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    page.goto("http://127.0.0.1:8089/")
    page.locator("button[data-view='analysis']").click()
    page.wait_for_selector("#analysis-conditions")

    tabs = ['daily', 'popular', 'menu', 'ingredient', 'weather']
    print("=== Current Heights (Before Redesign) ===")
    for tab in tabs:
        page.locator(f"button[data-analysis-tab='{tab}']").click()
        time.sleep(0.1)
        box = page.locator("#analysis-conditions").bounding_box()
        h = box['height'] if box else 0
        print(f"Tab '{tab}': height = {h:.1f}px")

    browser.close()
