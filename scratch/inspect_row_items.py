import sys
import time
from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto("http://127.0.0.1:8089/")
    page.locator("button[data-view='analysis']").click()
    page.wait_for_selector("#analysis-conditions")
    page.locator("button[data-analysis-tab='popular']").click()
    time.sleep(0.1)

    rows = page.locator("#analysis-conditions .an-row").all()
    for idx, r in enumerate(rows):
        box = r.bounding_box()
        print(f"Row {idx+1}: height={box['height']:.1f}px, width={box['width']:.1f}px")
        # List child elements in this row
        children = r.locator("> *").all()
        for c in children:
            c_box = c.bounding_box()
            tag = c.evaluate("el => el.className || el.tagName")
            print(f"   - {tag}: x={c_box['x']:.1f}, y={c_box['y']:.1f}, w={c_box['width']:.1f}, h={c_box['height']:.1f}")

    browser.close()
