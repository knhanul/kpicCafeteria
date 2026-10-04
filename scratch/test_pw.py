import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from playwright.sync_api import sync_playwright

print("Starting playwright with msedge channel...")
try:
    with sync_playwright() as p:
        print("Launching msedge...")
        browser = p.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 900})
        page = context.new_page()
        print("Navigating to http://127.0.0.1:8089/...")
        page.goto('http://127.0.0.1:8089/', timeout=10000)
        print("Page title:", page.title())
        
        # If on login page, perform login
        if "로그인" in page.title():
            print("Logging in as admin...")
            page.fill("#username", "admin")
            page.fill("#password", "change-me")
            page.click("button[type='submit']")
            page.wait_for_load_state("networkidle")
            print("After login title:", page.title())
            
        print("Navigating to analysis view...")
        page.locator("button[data-view='analysis']").click()
        page.wait_for_selector("#analysis-conditions", timeout=5000)
        print("Analysis conditions loaded!")
        
        # Check tabs
        for tab in ['daily', 'popular', 'menu', 'ingredient']:
            page.locator(f"button[data-analysis-tab='{tab}']").click()
            page.wait_for_timeout(300)
            page.screenshot(path=f'scratch/screen_{tab}.png')
            print(f"Captured screen_{tab}.png")
            
        browser.close()
        print("Done!")
except Exception as e:
    import traceback
    traceback.print_exc()
