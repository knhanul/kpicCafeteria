# 집중작성모드 레이아웃 문제 분석 보고

> 작성일: 2026-08-13  
> 상태: 원인 분석 완료, 수정 대기 (사용자 승인 전)

---

## 1. 관련 파일

| 파일 | 역할 |
|------|------|
| `backend/app/templates/app.html` | DOM 구조 정의 (focus-toolbar, workspace-grid 등) |
| `backend/app/static/app.css` | 집중작성모드 스타일 (line 19, line 161) |
| `backend/app/static/app.js` | `toggleFocus()` 함수 (line 477) |

---

## 2. 현재 Component 구조

집중작성모드 진입 시 실제 DOM 계층:

```
body
└─ #app-shell.app-shell.focus-mode
   │  display: block (base: grid → focus에서 override)
   │  min-height: 100vh
   │
   ├─ aside.sidebar
   │  display: none !important  (focus mode에서 숨김)
   │
   └─ section.main-area
      │  min-width: 0
      │  (별도 position/height 지정 없음)
      │
      ├─ header.top-header
      │  display: none !important  (focus mode에서 숨김)
      │
      └─ main#view-workspace.view.active
         │  padding: 10px 16px 28px  ← ★ 실제 적용값 (ID 선택자)
         │  padding: 80px 10px 10px  ← 의도값 (class 선택자, 적용 안 됨)
         │  display: block
         │
         ├─ div.workspace-toolbar
         │  display: none !important  (focus mode에서 숨김)
         │
         ├─ div#focus-toolbar.focus-toolbar
         │  position: fixed
         │  top: 0; left: 0; right: 0
         │  height: 58px
         │  z-index: 100
         │  (normal flow에서 제외됨)
         │
         └─ div.workspace-grid
            │  display: grid
            │  grid-template-columns: minmax(0,3fr) minmax(500px,2fr)
            │  height: calc(100vh - 90px)
            │  align-items: start  ← base CSS에서 상속, focus에서 override 안 됨
            │  gap: 14px
            │
            ├─ section.week-board-wrap
            │  │  height: 100%
            │  │  max-height: none
            │  │  overflow-y: auto
            │  │  padding: 12px
            │  │
            │  └─ div#week-board.week-board
            │     │  height: auto
            │     │  display: flex; flex-direction: column; gap: 14px
            │     │
            │     └─ section.week-section (×2)
            │        │  height: auto
            │        │  overflow: visible (density CSS override)
            │        │
            │        └─ div.weekday-grid
            │           │  height: auto
            │           │  display: grid
            │           │  grid-template-columns: repeat(5, minmax(0,1fr))
            │           │
            │           └─ article.day-column (×5)
            │              ├─ header.day-head (날짜 헤더)
            │              └─ div.day-body
            │
            └─ aside#editor-panel.editor-panel
               │  position: static
               │  height: 100%
               │  max-height: none
               │  overflow: auto
               │  padding: 20px
```

---

## 3. 현재 높이 계산

### 3.1 각 주요 컨테이너의 height 관련 속성

| 요소 | 선택자 | height | min-height | max-height | overflow | position | top | z-index |
|------|--------|--------|------------|------------|----------|----------|-----|---------|
| `#app-shell` | `.app-shell` | auto | 100vh | — | visible | static | — | — |
| `.main-area` | `.main-area` | auto | — | — | visible | static | — | — |
| `#view-workspace` | `#view-workspace` | auto | — | — | visible | static | — | — |
| `#focus-toolbar` | `.focus-toolbar` | 58px | — | — | visible | **fixed** | 0 | 100 |
| `.workspace-grid` | `.focus-mode .workspace-grid` | calc(100vh - 90px) | — | — | visible | static | — | — |
| `.week-board-wrap` | `.focus-mode .week-board-wrap` | 100% | — | none | **y: auto** | static | — | — |
| `.editor-panel` | `.focus-mode .editor-panel` | 100% | — | none | auto | static | — | — |

### 3.2 의도한 높이 계산 (설계 의도)

```
viewport (100vh)
├─ #focus-toolbar (position: fixed, 58px, 별도)
└─ #view-workspace
   ├─ padding-top: 80px   ← focus-toolbar 58px + 22px gap
   ├─ .workspace-grid
   │  height: calc(100vh - 90px)
   ├─ padding-bottom: 10px
   └─ total: 80 + (100vh - 90) + 10 = 100vh  ✓
```

### 3.3 실제 높이 계산 (현재 적용값)

```
viewport (100vh)
├─ #focus-toolbar (position: fixed, 58px, 별도)
└─ #view-workspace
   ├─ padding-top: 10px    ← ★ ID 선택자가 이김 (10px만 적용)
   ├─ .workspace-grid
   │  height: calc(100vh - 90px)
   ├─ padding-bottom: 28px ← ★ ID 선택자가 이김 (28px 적용)
   └─ total: 10 + (100vh - 90) + 28 = 100vh - 52px  ✗
```

**52px의 빈 공간이 하단에 발생한다.**

---

## 4. Scroll 구조

### 4.1 스크롤 담당 요소

```
viewport
└─ #app-shell (scroll: 없음)
   └─ .main-area (scroll: 없음)
      └─ #view-workspace (scroll: 없음)
         └─ .workspace-grid (scroll: 없음)
            ├─ .week-board-wrap ← scroll-y: auto (식단 패널 스크롤)
            │  └─ #week-board (scroll: 없음)
            │     └─ .week-section (overflow: visible)
            │        └─ .weekday-grid (scroll: 없음)
            └─ .editor-panel ← overflow: auto (편집 패널 스크롤)
```

### 4.2 스크롤 동작

- **좌측 식단 패널**: `.week-board-wrap`이 `overflow-y: auto`로 내부 스크롤 담당
- **우측 편집 패널**: `.editor-panel`이 `overflow: auto`로 내부 스크롤 담당
- **전체 페이지**: body 레벨 스크롤은 발생하지 않음 (내용이 viewport 내에 수용되도록 설계)

---

## 5. 상단 날짜 헤더가 가려지는 원인

### 핵심 원인: CSS Specificity 충돌

| 선택자 | CSS 선언 | Specificity |
|--------|----------|-------------|
| `#view-workspace` | `padding: 10px 16px 28px` | **(1, 0, 0)** |
| `.focus-mode .view` | `padding: 80px 10px 10px` | (0, 2, 0) |

CSS 명시도 우선순위: **(1, 0, 0) > (0, 2, 0)**

ID 선택자가 class 선택자보다 항상 우선하므로,  
`.focus-mode .view`의 `padding: 80px 10px 10px`는 **적용되지 않는다.**

### 결과

- **의도한 padding-top**: 80px (focus-toolbar 58px + 22px 여백)
- **실제 padding-top**: 10px (ID 선택자 값)
- **차액**: 70px

`#focus-toolbar`는 `position: fixed; top: 0; height: 58px`로 viewport 상단에 고정된다.  
본문 콘텐츠는 padding-top 10px부터 시작하므로, **상단 48px 영역이 toolbar에 가려진다.**

첫 번째 주 날짜 헤더(`.day-head`)는 `.week-board-wrap` padding(12px)을 포함해  
약 y=22px 위치에 렌더링되며, 58px 높이의 toolbar에 완전히 가려진다.

### 코드 위치

- **원인 라인**: `app.css` line 161 — `#view-workspace{padding:10px 16px 28px}`
- **무효화된 라인**: `app.css` line 19 — `.focus-mode .view{padding:80px 10px 10px}`

### 부가 원인: Scroll Position 유지

`toggleFocus()` 진입 시 `.week-board-wrap`의 `scrollTop`을 초기화하지 않는다.

```js
// app.js line 477
function toggleFocus(enabled){
  state.focus=enabled; state.weeks=2;
  $('#app-shell').classList.toggle('focus-mode',enabled);
  $('#focus-toolbar').classList.toggle('hidden',!enabled);
  $('#focus-toggle').classList.toggle('hidden',enabled);
  loadWorkspace(true);
  // ← scrollTop = 0 초기화 없음
}
```

일반모드에서 2주차를 보기 위해 스크롤한 경우,  
`.week-board-wrap`의 `scrollTop`이 집중모드로 전환 후에도 유지되어  
첫 번째 주가 더 위로 스크롤된 상태로 나타난다.

### 각 가능성 검증 결과

| 가능성 | 확인 결과 |
|--------|-----------|
| A. Toolbar overlay | **확인됨** — fixed toolbar + 부족한 padding-top |
| B. 잘못된 top 값 | 해당 없음 — 본문에 position:sticky/top 없음 |
| C. Overflow clipping | 해당 없음 — `.week-section`은 `overflow: visible` |
| D. Scroll Position 유지 | **부가 원인 확인** — scrollTop 초기화 없음 |
| E. Sticky 날짜 헤더 | 해당 없음 — 내부에 추가 sticky 요소 없음 |

---

## 6. 화면 하단에 빈 공간이 남는 원인

### 핵심 원인: 동일한 CSS Specificity 충돌

위와 동일한 원인으로, `padding-bottom`도 의도값(10px)이 아닌 ID 선택자 값(28px)이 적용된다.

### 높이 계산 비교

| 항목 | 의도값 | 실제값 | 차액 |
|------|--------|--------|------|
| padding-top | 80px | 10px | -70px |
| .workspace-grid height | calc(100vh - 90px) | calc(100vh - 90px) | 0 |
| padding-bottom | 10px | 28px | +18px |
| **전체 높이** | **100vh** | **100vh - 52px** | **-52px** |

Grid height는 `calc(100vh - 90px)`로 의도대로 적용되지만,  
실제 padding 합계가 38px(10+28)이 아닌 의도한 90px(80+10)이어야 한다.

**결과: 52px의 빈 공간이 하단에 발생한다.**

### 코드 위치

- **원인 라인**: `app.css` line 161 — `#view-workspace{padding:10px 16px 28px}`
- **Grid 높이 라인**: `app.css` line 19 — `.focus-mode .workspace-grid{height:calc(100vh - 90px)}`

### 기타 확인 항목

| 확인 항목 | 결과 |
|-----------|------|
| 부모 height 제한 (70vh, 700px 등) | 없음 |
| calc() 계산 오류 (존재하지 않는 Header 높이 차감) | **확인됨** — 90px는 80px padding + 10px padding을 가정했으나 실제 padding은 38px |
| Flex 구조 문제 (flex:1, min-height:0 부재) | 해당 없음 — Grid 구조 사용 |
| Grid 구조 문제 (고정 row 높이) | `align-items: start`가 base CSS에서 상속되지만, `height:100%`로 items가 채우므로 직접 원인 아님 |
| viewport 단위 혼용 | `100vh`만 사용 중, 혼용 없음 |

---

## 7. 두 문제가 같은 원인인지 별도 원인인지

### 판단: **동일한 원인 + 부가 원인 1개**

| 문제 | 주요 원인 | 부가 원인 |
|------|-----------|-----------|
| 상단 날짜 가려짐 | CSS Specificity 충돌 (padding-top 80px → 10px) | scrollTop 미초기화 |
| 하단 빈 공간 | CSS Specificity 충돌 (padding 계산 90px → 38px) | — |

**두 문제 모두 `#view-workspace` ID 선택자가 `.focus-mode .view` class 선택자를 무효화하는 동일한 원인에서 발생한다.**

부가적으로 `scrollTop` 초기화 누락이 상단 가려짐을 악화시킨다.

---

## 8. 추천 수정안

### 최소 변경안 (권장)

#### 수정 1: CSS 선택자 Specificity 해결 (핵심)

`app.css` line 19의 `.focus-mode .view`를 `.focus-mode #view-workspace`로 변경:

```css
/* 수정 전 */
.focus-mode .view{padding:80px 10px 10px}

/* 수정 후 */
.focus-mode #view-workspace{padding:80px 10px 10px}
```

Specificity: (1, 1, 0) > (1, 0, 0) → `#view-workspace`의 padding을 올바르게 override.

이 수정 하나로:
- **상단 가려짐 해결**: padding-top 80px 적용 → toolbar(58px) 아래 22px 여백 확보
- **하단 빈 공간 해결**: padding-bottom 10px 적용 → 전체 높이 = 80 + (100vh - 90) + 10 = 100vh

#### 수정 2: Scroll Position 초기화 (부가)

`app.js` `toggleFocus()` 함수에 scroll 초기화 추가:

```js
/* 수정 전 */
function toggleFocus(enabled){
  state.focus=enabled; state.weeks=2;
  $('#app-shell').classList.toggle('focus-mode',enabled);
  $('#focus-toolbar').classList.toggle('hidden',!enabled);
  $('#focus-toggle').classList.toggle('hidden',enabled);
  loadWorkspace(true);
}

/* 수정 후 */
function toggleFocus(enabled){
  state.focus=enabled; state.weeks=2;
  $('#app-shell').classList.toggle('focus-mode',enabled);
  $('#focus-toolbar').classList.toggle('hidden',!enabled);
  $('#focus-toggle').classList.toggle('hidden',enabled);
  loadWorkspace(true);
  const wrap=$('.week-board-wrap'); if(wrap) wrap.scrollTop=0;
}
```

### 대안 검토: Flex 구조 재설계

요청에서 제시된 구조:

```
FocusMode (height: 100dvh, display: flex, flex-direction: column)
├─ FocusToolbar (fixed height)
└─ WorkArea (flex: 1, min-height: 0, overflow: hidden)
    ├─ SchedulePanel (height: 100%, overflow-y: auto)
    └─ EditorPanel (height: 100%, overflow-y: auto)
```

**판단**: 현재 구조에서는 불필요.  
핵심 원인이 CSS 선택자 명시도 충돌이므로, 선택자 1개 수정으로 해결 가능.  
전체 구조를 Flex로 재설계하면 변경 범위가 커지고 Regression 위험이 증가함.

---

## 9. 수정 예상 파일

| 파일 | 수정 내용 | 변경 규모 |
|------|-----------|-----------|
| `backend/app/static/app.css` | line 19: `.focus-mode .view` → `.focus-mode #view-workspace` | 1개 선택자 |
| `backend/app/static/app.js` | line 477: `toggleFocus()`에 `scrollTop=0` 추가 | 1줄 추가 |

---

## 10. Regression 위험

### 일반모드 영향

- **없음.** `.focus-mode #view-workspace` 선택자는 `.focus-mode` class가 부여된 상태에서만 활성화되므로 일반모드에 영향을 주지 않음.

### 우측 편집 패널 영향

- **없음.** `.focus-mode .editor-panel`은 이미 올바른 specificity (0,2,0) > base `.editor-panel` (0,1,0)으로 작동 중.  
  수정 후 grid height가 정상적으로 100vh를 채우면 editor-panel의 `height:100%`도 정상 작동.

### Sticky Toolbar 영향

- **없음.** 일반모드의 `.workspace-toolbar` sticky 동작은 `.focus-mode` class와 무관.

### 집중모드 종료 시 영향

- **수정 2(scrollTop=0) 적용 시**: 종료 시에도 scrollTop을 0으로 설정하면, 일반모드에서 이전 스크롤 위치가 복원되지 않음.  
  **권장**: 종료 시에는 scrollTop을 0으로 하지 않거나, 별도 복원 로직 추가.  
  다만 현재는 종료 시 `loadWorkspace(true)`가 호출되어 `renderWeekBoard()`가 innerHTML을 재생성하므로, 대부분의 브라우저에서 scrollTop이 자연스럽게 0으로 초기화됨.  
  **실제 Regression 위험: 낮음.**

### 모바일/반응형 영향

- `@media(max-width:1180px)` 규칙에서 `.focus-mode .workspace-grid{height:auto}`가 적용됨.  
  이는 `.focus-mode #view-workspace` padding 수정과 무관하게 작동하므로 영향 없음.

---

## 11. 100vh vs 100dvh 검토

### 현재 상태

- 코드 내 viewport 단위: `100vh`만 사용 중 (`100dvh` 사용 없음)
- 사용 환경: Desktop Browser 중심

### 검토 의견

| 단위 | 장점 | 단점 |
|------|------|------|
| `100vh` | Desktop에서 안정적, 브라우저 지원 범용 | Mobile에서 주소창 토글 시 높이 변동 |
| `100dvh` | Mobile에서 주소창 토글 대응 | 구형 브라우저 미지원 (caniuse: 2023년 이후 지원) |

**판단**: Desktop 전용 시스템이므로 `100vh` 유지가 적절.  
추후 Mobile 지원이 필요해지면 `100dvh`로 전환 검토.

---

## 12. 핵심 원인 분류

### 판단: **유형 A + 유형 B (동일 원인)**

| 유형 | 해당 여부 | 근거 |
|------|-----------|------|
| A. Header Overlay | **해당** | fixed toolbar + padding-top 부족 (10px < 58px) |
| B. 잘못된 viewport height 계산 | **해당** | grid height calc(100vh-90px)가 padding 38px 기준이 아닌 90px 기준으로 계산 |
| C. 부모 Flex/Grid 구조 | 해당 없음 | Grid 구조 자체는 정상, height:100%로 items 채움 |
| D. Scroll container/scrollTop | **부가 해당** | scrollTop 미초기화가 증상 악화 |
| E. 복합 | **최종 판단** | A+B가 동일 원인(CSS Specificity)에서 발생, D가 부가 |

---

## 13. 높이 관련 CSS 중복 정리

### `#view-workspace`에 적용되는 padding 선언 (2개 충돌)

| 선택자 | 선언 | Specificity | 적용 여부 |
|--------|------|-------------|-----------|
| `#view-workspace` (line 161) | `padding: 10px 16px 28px` | (1, 0, 0) | **적용됨** |
| `.focus-mode .view` (line 19) | `padding: 80px 10px 10px` | (0, 2, 0) | 무시됨 |

### `.workspace-grid`에 적용되는 height 선언

| 선택자 | 선언 | Specificity | 적용 여부 |
|--------|------|-------------|-----------|
| `.workspace-grid` (line 10) | (height 명시 없음) | (0, 1, 0) | — |
| `.focus-mode .workspace-grid` (line 19) | `height: calc(100vh - 90px)` | (0, 2, 0) | 적용됨 |

### `.week-board-wrap`에 적용되는 height/overflow 선언

| 선택자 | 선언 | Specificity | 적용 여부 |
|--------|------|-------------|-----------|
| `.week-board-wrap` (line 10) | `max-height:calc(100vh-132px); overflow:auto` | (0, 1, 0) | — |
| `.week-board-wrap` (line 175) | `max-height:calc(100vh-120px)` | (0, 1, 0) | 동일 선택자, 뒤에 선언되어 적용 |
| `.focus-mode .week-board-wrap` (line 19) | `height:100%; max-height:none; overflow-y:auto` | (0, 2, 0) | **적용됨** |

### `.editor-panel`에 적용되는 height/overflow 선언

| 선택자 | 선언 | Specificity | 적용 여부 |
|--------|------|-------------|-----------|
| `.editor-panel` (line 10) | `position:sticky; top:164px; max-height:calc(100vh-184px); overflow:auto` | (0, 1, 0) | — |
| `.editor-panel` (line 176) | `top:110px` | (0, 1, 0) | 동일 선택자, 뒤에 선언되어 top만 override |
| `.focus-mode .editor-panel` (line 19) | `position:static; max-height:none; height:100%` | (0, 2, 0) | **적용됨** |

### 충돌 요약

**유일한 충돌**: `#view-workspace` (ID) vs `.focus-mode .view` (class)의 padding 선언.  
나머지 focus mode CSS는 모두 정상적으로 base CSS를 override하고 있음.
