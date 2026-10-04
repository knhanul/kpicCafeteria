import sys
import time
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright

def run_tests():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        print("[1] Opening main page...")
        page.goto("http://127.0.0.1:8088/")
        page.wait_for_load_state("networkidle")

        # 식수 분석 메뉴 클릭
        print("[2] Navigating to 식수 분석...")
        page.locator("button[data-view='analysis']").click()
        page.wait_for_selector("#analysis-conditions", timeout=5000)

        # ----------------------------------------------------
        # 1. 날짜별 식수 탭
        # ----------------------------------------------------
        print("\n--- Testing 탭: 날짜별 식수 ---")
        summary_text = page.locator(".an-summary-text").inner_text()
        print(f"Initial summary: {summary_text}")
        assert "중식" in summary_text, f"Expected '중식' in summary, got: {summary_text}"
        
        # 상세 조건 버튼이 없어야 함
        detail_toggle = page.locator("#an-detail-toggle")
        assert detail_toggle.count() == 0, "Daily tab should not have detail toggle"

        # 빠른 선택 6개월 클릭
        print("Clicking 6개월 quick button...")
        page.locator("button[data-quick='6m']").click()
        summary_after_6m = page.locator(".an-summary-text").inner_text()
        print(f"Summary after 6m: {summary_after_6m}")
        assert "6개월" in summary_after_6m, f"Expected '6개월' in summary, got: {summary_after_6m}"

        # 기간 선택 드롭다운 테스트 (18개월)
        print("Testing period dropdown (18개월)...")
        page.locator("#an-period-dropdown-btn").click()
        dropdown_menu = page.locator("#an-period-dropdown-menu")
        assert "hidden" not in (dropdown_menu.get_attribute("class") or ""), "Dropdown menu should be visible"
        page.locator("button[data-period-opt='18m']").click()
        time.sleep(0.2)
        drop_btn_text = page.locator("#an-period-dropdown-btn span").inner_text()
        print(f"Dropdown button text: {drop_btn_text}")
        assert "18개월" in drop_btn_text, f"Expected '18개월 ▾', got {drop_btn_text}"
        summary_after_18m = page.locator(".an-summary-text").inner_text()
        print(f"Summary after 18m: {summary_after_18m}")
        assert "18개월" in summary_after_18m, f"Expected '18개월' in summary, got: {summary_after_18m}"

        # 직접 날짜 변경 테스트
        print("Testing manual date input...")
        start_input = page.locator("#an-start")
        start_input.fill("2026-05-01")
        time.sleep(0.1)
        # 빠른 선택 active 해제 확인
        assert page.locator("button[data-quick='6m'].active").count() == 0
        assert page.locator("#an-period-dropdown-btn.active").count() == 0
        summary_manual = page.locator(".an-summary-text").inner_text()
        print(f"Summary after manual date: {summary_manual}")
        assert "2026-05-01" in summary_manual, f"Expected '2026-05-01' in summary, got: {summary_manual}"

        # 배식 석식 토글
        print("Testing meal type toggle...")
        page.locator("button[data-meal='DINNER']").click()
        summary_dinner = page.locator(".an-summary-text").inner_text()
        print(f"Summary after dinner: {summary_dinner}")
        assert "석식" in summary_dinner, f"Expected '석식' in summary, got: {summary_dinner}"

        # ----------------------------------------------------
        # 2. 인기 메뉴 탭
        # ----------------------------------------------------
        print("\n--- Testing 탭: 인기 메뉴 ---")
        page.locator("button[data-analysis-tab='popular']").click()
        time.sleep(0.3)
        pop_summary = page.locator(".an-summary-text").inner_text()
        print(f"Popular summary: {pop_summary}")

        # 상세 조건 토글 확인
        detail_toggle = page.locator("#an-detail-toggle")
        assert detail_toggle.count() == 1, "Popular tab must have detail toggle"
        detail_panel = page.locator("#an-detail-panel")
        assert "hidden" in (detail_panel.get_attribute("class") or ""), "Detail panel must be hidden by default"

        print("Clicking detail toggle in popular tab...")
        detail_toggle.click()
        assert "hidden" not in (detail_panel.get_attribute("class") or ""), "Detail panel should now be visible"
        toggle_text = detail_toggle.inner_text()
        print(f"Toggle button text after open: {toggle_text}")
        assert "−" in toggle_text or "-" in toggle_text

        # 50개 선택
        print("Selecting 50개 limit...")
        page.locator("button[data-pop-limit='50']").click()
        pop_summary_50 = page.locator(".an-summary-text").inner_text()
        print(f"Popular summary after 50 limit: {pop_summary_50}")
        assert "50개" in pop_summary_50

        # 다시 토글 닫기
        detail_toggle.click()
        assert "hidden" in (detail_panel.get_attribute("class") or ""), "Detail panel should be hidden after second click"

        # ----------------------------------------------------
        # 3. 메뉴별 식수 탭
        # ----------------------------------------------------
        print("\n--- Testing 탭: 메뉴별 식수 ---")
        page.locator("button[data-analysis-tab='menu']").click()
        time.sleep(0.3)
        menu_summary = page.locator(".an-summary-text").inner_text()
        print(f"Menu summary: {menu_summary}")

        # 라벨 확인
        labels = page.locator(".an-label").all_inner_texts()
        print(f"Menu tab labels: {labels}")
        assert "메뉴 검색" in labels, "Expected '메뉴 검색' label"
        assert "메뉴 이름 (최대" not in " ".join(labels), "Long label should be replaced with concise '메뉴 검색'"

        # 상세 조건 확인 (날씨 조건, 날씨 함께 보기)
        page.locator("#an-detail-toggle").click()
        assert page.locator("#an-weather-filter").is_visible()
        assert page.locator("#an-show-weather").is_visible()

        # ----------------------------------------------------
        # 4. 재료별 식수 탭
        # ----------------------------------------------------
        print("\n--- Testing 탭: 재료별 식수 ---")
        page.locator("button[data-analysis-tab='ingredient']").click()
        time.sleep(0.3)
        ing_labels = page.locator(".an-label").all_inner_texts()
        print(f"Ingredient tab labels: {ing_labels}")
        assert "재료 검색" in ing_labels, "Expected '재료 검색' label"
        assert "조회 기준" in ing_labels, "Expected '조회 기준' label"

        # ----------------------------------------------------
        # 5. 날씨별 식수 탭
        # ----------------------------------------------------
        print("\n--- Testing 탭: 날씨별 식수 ---")
        page.locator("button[data-analysis-tab='weather']").click()
        time.sleep(0.3)
        weather_labels = page.locator(".an-label").all_inner_texts()
        print(f"Weather tab labels: {weather_labels}")
        assert "날씨 조건" in weather_labels, "Expected '날씨 조건' label"
        # 상세 토글 없어야 함
        assert page.locator("#an-detail-toggle").count() == 0

        # ----------------------------------------------------
        # 6. 반응형 (뷰포트 조절) 검증
        # ----------------------------------------------------
        print("\n--- Testing Responsive Viewports ---")
        for width in [1280, 900, 768, 480]:
            page.set_viewport_size({"width": width, "height": 800})
            time.sleep(0.2)
            scroll_width = page.evaluate("document.documentElement.scrollWidth")
            client_width = page.evaluate("document.documentElement.clientWidth")
            print(f"Viewport width {width}px: scrollWidth={scroll_width}, clientWidth={client_width}")
            assert scroll_width <= client_width + 1, f"Horizontal scrollbar detected at {width}px!"

        # 스크린샷 캡처 1: 인기 메뉴 상세 조건 열림 상태
        page.set_viewport_size({"width": 1280, "height": 800})
        page.locator("button[data-analysis-tab='popular']").click()
        time.sleep(0.2)
        page.locator("#an-detail-toggle").click()
        time.sleep(0.2)
        page.locator("#analysis-conditions").screenshot(path="scratch/analysis_popular_detail_open.png")

        # 스크린샷 캡처 2: 메뉴별 식수 탭
        page.locator("button[data-analysis-tab='menu']").click()
        time.sleep(0.2)
        page.locator("#analysis-conditions").screenshot(path="scratch/analysis_menu_preview.png")
        print("\nCaptured additional screenshots!")

        print("\nALL VERIFICATIONS PASSED SUCCESSFULLY!")
        browser.close()

if __name__ == "__main__":
    run_tests()
