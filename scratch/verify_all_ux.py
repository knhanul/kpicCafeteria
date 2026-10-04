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
        if "로그인" in page.title():
            page.fill("#username", "admin")
            page.fill("#password", "change-me")
            page.click("button[type='submit']")
            page.wait_for_load_state("networkidle")
        page.locator("button[data-view='analysis']").click()
        page.wait_for_selector("#analysis-conditions")

        # 0. Global Check: Detail toggle button should be completely removed
        toggle_count = page.locator("#an-detail-toggle, .an-detail-toggle").count()
        print(f"[0] Detail toggle button count: {toggle_count}")
        if toggle_count > 0:
            errors.append("Detail toggle button (#an-detail-toggle) still exists!")

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
        # Query button click (inside basic conditions box)
        query_btn = page.locator("#an-query")
        if not query_btn.is_visible():
            errors.append("daily: #an-query not visible")
        query_btn.click()
        time.sleep(0.5)
        has_content = page.locator(".an-chart").is_visible() or page.locator(".an-table").is_visible() or page.locator(".an-empty").is_visible()
        print(f"  daily: query executed, content visible = {has_content}")

        # 2. Popular Tab
        print("[2] Testing 'popular' tab...")
        page.locator("button[data-analysis-tab='popular']").click()
        time.sleep(0.1)
        # Check that detail items (popLimit, minDays) are inside "순위 조건" box and ALWAYS visible
        pop_box = page.locator(".an-group").nth(2)
        pop_box_title = pop_box.locator(".an-group-title").inner_text()
        print(f"  popular 3rd box title: {pop_box_title}")
        if "순위 조건" not in pop_box_title:
            errors.append(f"popular: 3rd box is not '순위 조건', got: {pop_box_title}")
        
        limit_btns = pop_box.locator("[data-pop-limit]")
        min_days_input = pop_box.locator("#an-min-days")
        if limit_btns.count() == 0 or not limit_btns.first.is_visible():
            errors.append("popular: popLimit buttons not visible in ranking box")
        if not min_days_input.is_visible():
            errors.append("popular: #an-min-days not visible in ranking box")

        # Test changing pop-limit
        pop_box.locator("button[data-pop-limit='20']").click()
        time.sleep(0.1)
        if "active" not in pop_box.locator("button[data-pop-limit='20']").get_attribute("class"):
            errors.append("popular: pop-limit 20 button not active")

        # Test changing min-days
        min_days_input.fill("2")
        min_days_input.dispatch_event("change")
        time.sleep(0.1)

        # Query button click (inside ranking box)
        pop_query = pop_box.locator("#an-query")
        if not pop_query.is_visible():
            errors.append("popular: #an-query not visible in ranking box")
        pop_query.click()
        time.sleep(0.5)
        print("  popular: query executed with limit=20, min_days=2")

        # 3. Menu Tab
        print("[3] Testing 'menu' tab...")
        page.locator("button[data-analysis-tab='menu']").click()
        time.sleep(0.1)
        # Check that weather detail items are inside "기간 및 옵션" box and ALWAYS visible
        period_box = page.locator(".an-group").first
        period_box_title = period_box.locator(".an-group-title").inner_text()
        print(f"  menu 1st box title: {period_box_title}")
        if "기간" not in period_box_title:
            errors.append(f"menu: 1st box title doesn't contain '기간', got: {period_box_title}")
        
        weather_select = period_box.locator("#an-weather-filter")
        show_weather_check = period_box.locator("#an-show-weather")
        if not weather_select.is_visible():
            errors.append("menu: #an-weather-filter not visible in period box")
        if not show_weather_check.is_visible():
            errors.append("menu: #an-show-weather not visible in period box")

        # Search menu & add chip
        search_box = page.locator(".an-group").nth(2)
        search_input = search_box.locator("#an-search-input")
        search_input.fill("불고기")
        search_box.locator("#an-search-btn").click()
        time.sleep(0.3)
        search_list = page.locator("#an-search-list")
        if search_list.is_visible():
            first_item = page.locator("#an-search-list button").first
            first_item.click()
            time.sleep(0.2)
            chips = page.locator(".an-chip")
            print(f"  menu: added chip, count = {chips.count()}")
            if chips.count() == 0:
                errors.append("menu: chip not added after click")
        
        # Query button click (inside search box)
        menu_query = search_box.locator("#an-query")
        if not menu_query.is_visible():
            errors.append("menu: #an-query not visible in search box")
        menu_query.click()
        time.sleep(0.5)
        print("  menu: query executed")

        # 4. Ingredient Tab
        print("[4] Testing 'ingredient' tab...")
        page.locator("button[data-analysis-tab='ingredient']").click()
        time.sleep(0.1)
        # Check weather detail in period box
        ing_period_box = page.locator(".an-group").first
        if not ing_period_box.locator("#an-weather-filter").is_visible():
            errors.append("ingredient: #an-weather-filter not visible in period box")
        if not ing_period_box.locator("#an-show-weather").is_visible():
            errors.append("ingredient: #an-show-weather not visible in period box")

        ing_search_box = page.locator(".an-group").nth(2)
        ing_search = ing_search_box.locator("#an-search-input")
        ing_search.fill("돼지고기")
        ing_search_box.locator("#an-search-btn").click()
        time.sleep(0.3)
        if page.locator("#an-search-list").is_visible():
            page.locator("#an-search-list button").first.click()
            time.sleep(0.2)
            print(f"  ingredient: added chip count = {page.locator('.an-chip').count()}")
        
        ing_query = ing_search_box.locator("#an-query")
        if not ing_query.is_visible():
            errors.append("ingredient: #an-query not visible in search box")
        ing_query.click()
        time.sleep(0.5)
        print("  ingredient: query executed")

        # 5. Weather Tab
        print("[5] Testing 'weather' tab...")
        page.locator("button[data-analysis-tab='weather']").click()
        time.sleep(0.1)
        page.locator("#an-query").click()
        time.sleep(0.5)
        print("  weather: query executed")

        # 6. Check responsive behavior & horizontal scrollbar
        print("[6] Checking responsive behavior at 1440px, 1024px, 768px, 480px...")
        for w in [1440, 1024, 768, 480]:
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
        page.locator("button[data-analysis-tab='ingredient']").click()
        time.sleep(0.3)
        page.screenshot(path="scratch/screenshot_ingredient.png")

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
