import sys
import time
from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

errors = []

def test_analysis_ux():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto("http://127.0.0.1:8089/")
        page.locator("button[data-view='analysis']").click()
        page.wait_for_selector("#analysis-conditions")

        # 1. Daily Tab
        print("[1] Testing 'daily' tab...")
        page.locator("button[data-analysis-tab='daily']").click()
        time.sleep(0.1)
        # Check quick buttons
        page.locator("button[data-quick='3m']").click()
        time.sleep(0.1)
        start_val = page.locator("#an-start").input_value()
        print(f"  daily: 3m start date = {start_val}")
        # Test dropdown 18m
        page.locator("#an-period-dropdown-btn").click()
        page.locator("button[data-period-opt='18m']").click()
        time.sleep(0.1)
        start_18m = page.locator("#an-start").input_value()
        print(f"  daily: 18m start date = {start_18m}")
        if start_val == start_18m:
            errors.append("daily: 18m did not update start date")
        # Meal type toggle
        page.locator("button[data-meal='DINNER']").click()
        time.sleep(0.1)
        if "active" not in page.locator("button[data-meal='DINNER']").get_attribute("class"):
            errors.append("daily: DINNER button not active")
        # Query button click
        page.locator("#an-query").click()
        time.sleep(0.5)
        # Verify chart or table rendered
        has_chart = page.locator(".an-chart").is_visible() or page.locator(".an-table").is_visible() or page.locator(".an-empty").is_visible()
        print(f"  daily: query executed, content visible = {has_chart}")

        # 2. Popular Tab
        print("[2] Testing 'popular' tab...")
        page.locator("button[data-analysis-tab='popular']").click()
        time.sleep(0.1)
        # Scope toggle
        page.locator("button[data-pop-scope='all']").click()
        time.sleep(0.1)
        # Basis toggle
        page.locator("button[data-pop-basis='group']").click()
        time.sleep(0.1)
        # Detail toggle
        detail_panel = page.locator("#an-detail-panel")
        if detail_panel.is_visible():
            errors.append("popular: detail panel should be hidden initially")
        page.locator("#an-detail-toggle").click()
        time.sleep(0.1)
        if not detail_panel.is_visible():
            errors.append("popular: detail panel should be visible after toggle")
        # Query
        page.locator("#an-query").click()
        time.sleep(0.5)
        print("  popular: query executed")

        # 3. Menu Tab
        print("[3] Testing 'menu' tab...")
        page.locator("button[data-analysis-tab='menu']").click()
        time.sleep(0.1)
        # Search menu
        search_input = page.locator("#an-search-input")
        search_input.fill("불고기")
        page.locator("#an-search-btn").click()
        time.sleep(0.3)
        # Check search list
        search_list = page.locator("#an-search-list")
        if search_list.is_visible():
            first_item = page.locator("#an-search-list button").first
            menu_name = first_item.inner_text().split("\n")[0]
            first_item.click()
            time.sleep(0.2)
            # Check chip
            chips = page.locator(".an-chip")
            print(f"  menu: added chip, count = {chips.count()}")
            if chips.count() == 0:
                errors.append("menu: chip not added after click")
            else:
                # Remove chip
                page.locator(".an-chip button").first.click()
                time.sleep(0.1)
                print(f"  menu: after chip remove, count = {page.locator('.an-chip').count()}")
        page.locator("#an-query").click()
        time.sleep(0.5)

        # 4. Ingredient Tab
        print("[4] Testing 'ingredient' tab...")
        page.locator("button[data-analysis-tab='ingredient']").click()
        time.sleep(0.1)
        ing_search = page.locator("#an-search-input")
        ing_search.fill("돼지고기")
        page.locator("#an-search-btn").click()
        time.sleep(0.3)
        if page.locator("#an-search-list").is_visible():
            page.locator("#an-search-list button").first.click()
            time.sleep(0.2)
            print(f"  ingredient: added chip count = {page.locator('.an-chip').count()}")
        page.locator("#an-query").click()
        time.sleep(0.5)

        # 5. Weather Tab
        print("[5] Testing 'weather' tab...")
        page.locator("button[data-analysis-tab='weather']").click()
        time.sleep(0.1)
        page.locator("#an-query").click()
        time.sleep(0.5)
        print("  weather: query executed")

        # 6. Check responsive behavior & horizontal scrollbar
        print("[6] Checking responsive behavior at 1024px, 768px, 480px...")
        for w in [1024, 768, 480]:
            page.set_viewport_size({"width": w, "height": 800})
            time.sleep(0.1)
            scroll_width = page.evaluate("document.documentElement.scrollWidth")
            client_width = page.evaluate("document.documentElement.clientWidth")
            diff = scroll_width - client_width
            print(f"  viewport {w}px: scrollWidth={scroll_width}, clientWidth={client_width}, diff={diff}")
            if diff > 5:
                errors.append(f"viewport {w}px has horizontal scroll: diff={diff}")

        # Capture screenshots
        page.set_viewport_size({"width": 1440, "height": 900})
        page.locator("button[data-analysis-tab='daily']").click()
        time.sleep(0.3)
        page.screenshot(path="scratch/screenshot_daily.png")
        page.locator("button[data-analysis-tab='popular']").click()
        time.sleep(0.3)
        page.screenshot(path="scratch/screenshot_popular.png")
        page.locator("button[data-analysis-tab='menu']").click()
        time.sleep(0.3)
        page.screenshot(path="scratch/screenshot_menu.png")

        browser.close()

    if errors:
        print("\n=== ERRORS ENCOUNTERED ===")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("\n=== ALL TESTS PASSED SUCCESSFULLY! ===")

if __name__ == '__main__':
    test_analysis_ux()
