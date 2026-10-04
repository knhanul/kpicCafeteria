import sys
from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.goto("http://127.0.0.1:8089/")
    page.locator("button[data-view='analysis']").click()
    page.wait_for_selector("#analysis-conditions")
    page.locator("button[data-analysis-tab='popular']").click()

    card_box = page.locator("#analysis-conditions").bounding_box()
    print(f"Card Height: {card_box['height']:.1f}px")

    groups = page.locator("#analysis-conditions .an-group").all()
    for idx, g in enumerate(groups):
        box = g.bounding_box()
        title = g.locator(".an-group-title").inner_text()
        print(f"Group {idx+1} ({title}): height={box['height']:.1f}px")
        items = g.locator(".an-item").all()
        for it in items:
            it_box = it.bounding_box()
            txt = it.inner_text().replace('\n', ' ')
            print(f"   - item: h={it_box['height']:.1f}px, txt='{txt[:40]}'")

    foot = page.locator("#analysis-conditions .an-foot-bar").bounding_box()
    print(f"Foot bar height: {foot['height']:.1f}px")

    browser.close()
