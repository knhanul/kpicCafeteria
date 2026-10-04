import sys
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

    items = page.evaluate("""() => {
        const row2 = document.querySelectorAll('#analysis-conditions .an-row')[1];
        return Array.from(row2.children).map(el => ({
            cls: el.className,
            text: el.innerText.replace(/\\n/g, ' ').trim(),
            w: el.offsetWidth,
            mw: window.getComputedStyle(el).minWidth,
            pad: window.getComputedStyle(el).padding,
            mar: window.getComputedStyle(el).margin
        }));
    }""")
    for it in items:
        print(f"[{it['cls']}] '{it['text']}' -> width: {it['w']}px, pad: {it['pad']}, mar: {it['mar']}")

    browser.close()
