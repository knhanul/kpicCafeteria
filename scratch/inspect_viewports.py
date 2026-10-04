import sys
import time
from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    for width in [1280, 1440, 1920]:
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.goto("http://127.0.0.1:8089/")
        page.locator("button[data-view='analysis']").click()
        page.wait_for_selector("#analysis-conditions")
        print(f"=== Viewport {width}px ===")
        for tab in ['daily', 'popular', 'menu', 'ingredient', 'weather']:
            page.locator(f"button[data-analysis-tab='{tab}']").click()
            time.sleep(0.05)
            box = page.locator("#analysis-conditions").bounding_box()
            rows = page.locator("#analysis-conditions .an-row").count()
            detail_open = page.locator("#analysis-conditions .an-detail-panel").is_visible()
            print(f"  Tab '{tab}': height={box['height']:.1f}px, rows={rows}, detail_open={detail_open}")
    browser.close()
