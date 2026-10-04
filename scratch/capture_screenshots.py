from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 900})
    page.goto('http://127.0.0.1:8089/')
    page.locator("button[data-view='analysis']").click()
    page.wait_for_selector('#analysis-conditions')
    for tab in ['daily', 'popular', 'menu', 'ingredient']:
        page.locator(f"button[data-analysis-tab='{tab}']").click()
        page.wait_for_timeout(200)
        page.screenshot(path=f'scratch/group_box_{tab}.png')
    browser.close()
