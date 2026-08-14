# HWPX 출력 기능 분석 문서

작성 목적: 현재 구내식당 시스템과 제공된 HWPX 템플릿의 실제 구조를 확인하고, 이후 HWPX 기반 출력 기능 구현을 위한 기초 분석을 정리한다.

---

## 1. 현재 시스템 구조

### 1-1. 기술 스택

- **Frontend**: Vanilla JavaScript, Jinja2 템플릿, 정적 CSS/JS
- **Backend**: FastAPI
- **ORM**: SQLAlchemy 2
- **Database**: PostgreSQL 16
- **PDF 관련 라이브러리**: Playwright 1.54.0 Chromium
- **문서 템플릿**: Jinja2 + HWPX ZIP 패키지 처리
- **배포/실행**: Docker Compose, Nginx

### 1-2. 실행/배포 환경

- `docker-compose.yml` 기준으로 다음 서비스가 존재한다.
  - `db`: `postgres:16-alpine`
  - `app`: FastAPI 애플리케이션
  - `nginx`: 리버스 프록시
- `storage/` 볼륨이 업로드 파일, 템플릿, 생성 문서 저장용으로 사용된다.

### 1-3. 문서/PDF 관련 기존 구현

현재 문서 출력은 **HTML 미리보기 + PDF 변환 + HWPX 생성** 흐름을 가진다.

- `backend/app/document_service.py`
  - `create_preview()`로 미리보기 데이터 생성
  - `render_preview_html()`로 Jinja2 HTML 렌더링
  - `render_pdf()`로 Playwright 기반 PDF 생성
- `backend/app/routers/documents.py`
  - `/api/documents/preview`
  - `/preview/{token}`
  - `/api/documents/{token}/pdf`
  - `/api/documents/{token}/hwpx`
- `backend/app/hwpx_service.py`
  - HWPX 템플릿 검증
  - HWPX XML 치환 및 재패키징

### 1-4. 파일 다운로드 관련 기존 구현

- PDF/HWPX 다운로드는 `Response` + `Content-Disposition` 헤더 방식으로 제공된다.
- 템플릿 파일 자체 다운로드/조회는 `FileResponse`가 일부 라우트에서 사용된다.
- 업로드는 `UploadFile` + `shutil.copyfileobj()` 방식이다.

---

## 2. 현재 기능 구조와 DB 매핑

아래는 실제 코드 기준의 기능별 테이블/모델 매핑이다.

### 2-1. 식단표 작성

관련 모델:

- `MealService`
- `MealServiceMenu`
- `MealServiceMenuIngredient`
- `Menu`
- `Recipe`
- `RecipeIngredient`
- `MealTypeSetting`

주요 필드:

- `MealService.service_date`
- `MealService.meal_type`
- `MealService.planned_count`
- `MealService.service_time`
- `MealService.concept_title`
- `MealServiceMenu.menu_name_snapshot`
- `MealServiceMenu.recipe_name_snapshot`
- `MealServiceMenu.recipe_version_snapshot`
- `MealServiceMenu.ingredients`
- `MealServiceMenuIngredient.ingredient_name_snapshot`
- `MealServiceMenuIngredient.quantity_total`
- `MealServiceMenuIngredient.quantity_per_100`
- `MealServiceMenuIngredient.unit`

관련 코드:

- 식단 편집 UI: `backend/app/static/app.js`
- 저장 처리: `backend/app/document_service.py`, `backend/app/routers/documents.py`
- 출력 데이터 생성: `backend/app/document_service.py::_meal_plan_payload()`

### 2-2. 메뉴 관리

관련 모델:

- `Menu`
- `Recipe`
- `RecipeIngredient`
- `Ingredient`
- `IngredientAlias`

주요 필드:

- `Menu.name`, `Menu.canonical_name`, `Menu.role`, `Menu.active`
- `Recipe.name`, `Recipe.version`, `Recipe.composition_key`, `Recipe.is_default`
- `RecipeIngredient.quantity_per_100`, `RecipeIngredient.unit`, `RecipeIngredient.is_primary`
- `Ingredient.name`, `Ingredient.default_unit`, `Ingredient.stat_group`

관련 코드:

- 기준정보 관리: `backend/app/static/app.js`
- HWPX 출력에 직접 반영되는 레시피/재료 스냅샷: `MealServiceMenu`, `MealServiceMenuIngredient`

### 2-3. 메뉴별 식재료

관련 모델:

- `RecipeIngredient`
- `Ingredient`
- `MealServiceMenuIngredient`(식단에 스냅샷 저장된 재료)

데이터 흐름:

- 메뉴 기준 레시피: `Recipe -> RecipeIngredient -> Ingredient`
- 실제 식단 출력용 스냅샷: `MealServiceMenu -> MealServiceMenuIngredient`

### 2-4. 중식/석식

관련 모델:

- `MealService.meal_type`
- `MealTypeSetting.code`, `MealTypeSetting.name`

흐름:

- 시스템은 식사 구분을 `meal_type` 코드로 관리한다.
- 출력/표시명은 `MEAL_NAMES` 또는 `MealTypeSetting` 정보를 사용한다.
- 현재 로직상 주로 `LUNCH`, `DINNER`를 기준으로 그룹핑한다.

### 2-5. 식수 인원

관련 모델:

- `MealService.planned_count`
- `MealActual.actual_count`

흐름:

- 계획 식수는 식단 작성 시 `MealService.planned_count`
- 실제 식수는 `MealActual.actual_count`
- 현재 출력 데이터는 계획 식수를 주요 값으로 사용한다.

### 2-6. 조리지시서

관련 모델:

- `MealService`
- `MealServiceMenu`
- `MealServiceMenuIngredient`
- `Recipe`
- `RecipeIngredient`
- `Ingredient`

출력용 데이터는 `backend/app/document_service.py::_cooking_payload()`에서 생성한다.

핵심 구조:

- 날짜별 서비스 목록
- 각 서비스별 중식/석식 구분
- 메뉴별 재료 목록
- 메뉴별 조리지시 문구

### 2-7. 보존식 기록

관련 모델:

- `PreservationRecord`
- `MealService`
- `MealServiceMenu`

출력용 데이터는 `backend/app/document_service.py::_preservation_payload()`에서 생성한다.

핵심 구조:

- 배식일
- 채취 시각
- 담당자
- 메뉴 목록
- 냉동고 온도
- 폐기 예정일
- 수거자
- 수거 시간

### 2-8. 기존 출력/인쇄 기능

관련 파일:

- `backend/app/document_service.py`
- `backend/app/routers/documents.py`
- `backend/app/templates/documents/*.html`

현재 구조:

- HTML 미리보기 페이지 생성
- Playwright로 HTML을 PDF로 렌더링
- HWPX는 템플릿 기반 치환으로 생성
- `/preview/{token}` 는 HTML 미리보기
- `/api/documents/{token}/pdf` 는 PDF 다운로드
- `/api/documents/{token}/hwpx` 는 HWPX 다운로드

---

## 3. 데이터 흐름 분석

### 3-1. 식단표 흐름

실제 코드 기준 구조:

```text
MealService
 └─ service_date
 ├─ meal_type (LUNCH / DINNER)
 ├─ planned_count
 ├─ service_time
 ├─ concept_title
 └─ menus[]
     ├─ menu_name_snapshot
     ├─ recipe_name_snapshot
     ├─ recipe_version_snapshot
     └─ ingredients[]
         ├─ ingredient_name_snapshot
         ├─ quantity_total
         ├─ quantity_per_100
         └─ unit
```

`backend/app/document_service.py::_meal_plan_payload()`는 다음 형태로 출력 데이터를 만든다.

- 날짜별(`service_date`)로 묶음
- 한 날짜 안에서 `meal_type`별로 중식/석식 분리
- 각 서비스에 대해 메뉴명 배열을 생성
- 템플릿에서 `W1_D1_DATE`, `W1_D1_LUNCH_MENU` 같은 토큰에 매핑

### 3-2. 메뉴 → 식재료 흐름

실제 코드 기준 구조:

```text
Menu
 └─ Recipe[]
     └─ RecipeIngredient[]
         ├─ ingredient_id
         ├─ quantity_per_100
         ├─ unit
         └─ is_primary
             └─ Ingredient
                 ├─ name
                 ├─ default_unit
                 └─ stat_group
```

출력용으로는 다음 두 경로가 존재한다.

- 기준정보 관리용: `Recipe -> RecipeIngredient -> Ingredient`
- 실제 배식 출력용: `MealServiceMenu -> MealServiceMenuIngredient`

즉, 출력 문서에서는 기준 레시피가 아니라 **식단에 저장된 스냅샷**을 우선 사용한다.

---

## 4. HWPX 템플릿 구조 분석

실제 템플릿 파일:

- `docs/template/식단표_원본템플릿.hwpx`
- `docs/template/조리지시서_원본템플릿.hwpx`
- `docs/template/보존식기록지_원본템플릿.hwpx`

### 4-1. 공통 ZIP 구조

세 파일 모두 공통적으로 다음 구조를 가진다.

- `mimetype`
- `Contents/content.hpf`
- `Contents/header.xml`
- `Contents/section0.xml`
- `META-INF/container.xml`
- `META-INF/manifest.xml`
- `META-INF/container.rdf`
- `settings.xml`
- `version.xml`
- `Preview/PrvImage.png`
- `Preview/PrvText.txt`
- `BinData/image1.bmp`

특징:

- **section 파일은 모두 1개**(`section0.xml`)이다.
- `content.hpf`의 manifest/spine는 header + section0 중심이다.
- 각 파일에 이미지 리소스가 1개 포함되어 있다.

### 4-2. 실제 XML 구조 요약

모든 템플릿은 `Contents/section0.xml` 내부에 다음 요소들을 포함한다.

- 문단(`p`)
- 표(`tbl`)
- 표 행(`tr`)
- 표 셀(`tc`)
- 텍스트 런(`run`)
- 텍스트 노드(`t`)

실측 결과:

- **식단표**: `p 44`, `tr 7`, `tc 37`
- **조리지시서**: `p 35`, `tr 8`, `tc 30`
- **보존식 기록지**: `p 51`, `tr 8`, `tc 48`

### 4-3. 플레이스홀더 분리 여부

실제 검사 결과:

- 세 템플릿 모두 **플레이스홀더가 여러 `<hp:run>` 또는 텍스트 노드로 분리된 사례는 발견되지 않았다.**
- 검사 기준 `SPLIT 0`

즉, 현재 템플릿 기준으로는 각 `{{FIELD}}`가 단일 텍스트 노드 안에 존재한다.

다만 이 결과는 **현재 템플릿에 한정**된다. 템플릿 편집으로 글자 스타일이 끊기면 placeholder가 run 단위로 분리될 수 있다.

### 4-4. 템플릿별 필드 목록

#### 식단표

실제 플레이스홀더 수: **36개**

- `{{PERIOD_TITLE}}`
- `{{W1_D1_DATE}}` ~ `{{W2_D5_DATE}}`
- `{{W1_D1_LUNCH_MENU}}` ~ `{{W2_D5_LUNCH_MENU}}`
- `{{W1_D1_DINNER_MENU}}` ~ `{{W2_D5_DINNER_MENU}}`
- `{{W1_LUNCH_TIME_INFO}}`
- `{{W2_LUNCH_TIME_INFO}}`
- `{{DINNER_TIME_INFO}}`
- `{{ORIGIN_INFO}}`
- `{{NOTICE}}`

#### 조리지시서

실제 플레이스홀더 수: **29개**

- `{{DATE_LABEL}}`
- `{{LUNCH_MENU_1}}` ~ `{{LUNCH_MENU_7}}`
- `{{LUNCH_INGREDIENTS_1}}` ~ `{{LUNCH_INGREDIENTS_7}}`
- `{{DINNER_MENU_1}}` ~ `{{DINNER_MENU_7}}`
- `{{DINNER_INGREDIENTS_1}}` ~ `{{DINNER_INGREDIENTS_7}}`

#### 보존식 기록지

실제 플레이스홀더 수: **27개**

- `{{B1_DATE_LABEL}}`
- `{{B1_SAMPLE_HOUR}}`, `{{B1_SAMPLE_MINUTE}}`, `{{B1_MANAGER}}`
- `{{B1_MENU_LIST}}`
- `{{B1_FREEZER_TEMP}}`, `{{B1_DISCARD_DATETIME}}`
- `{{B1_COLLECTOR}}`, `{{B1_COLLECTION_TIME}}`
- B2, B3도 동일한 규칙

### 4-5. `TEMPLATE_FIELDS.md` 일치 여부

파일: `docs/template/TEMPLATE_FIELDS.md`

분석 결과:

- 문서에 정의된 필드와 실제 템플릿의 필드 목록은 **대체로 일치**한다.
- 식단표의 경우 `W1_LUNCH_TIME_INFO`, `W2_LUNCH_TIME_INFO`, `DINNER_TIME_INFO`가 문서와 실제 템플릿에서 모두 확인된다.
- 조리지시서와 보존식 기록지도 문서의 반복 필드 구조와 실제 필드 구조가 일치한다.

### 4-6. 반복 영역 추정

실제 템플릿 구조상 반복 영역은 다음처럼 해석된다.

#### 식단표

- 2주 단위 반복
- 각 주당 5일 반복
- 각 날짜마다 중식/석식 메뉴 셀 반복

즉:

```text
W1 / W2
 └─ D1 ~ D5
     ├─ DATE
     ├─ LUNCH_MENU
     └─ DINNER_MENU
```

#### 조리지시서

- 1일 단위 문서
- 중식 7개 메뉴 슬롯
- 석식 7개 메뉴 슬롯
- 각 메뉴마다 재료 슬롯 7개

즉:

```text
DATE_LABEL
 ├─ LUNCH_MENU_1..7
 ├─ LUNCH_INGREDIENTS_1..7
 ├─ DINNER_MENU_1..7
 └─ DINNER_INGREDIENTS_1..7
```

#### 보존식 기록지

- 1페이지 3블록 구조
- B1~B3 반복
- 각 블록에 날짜/채취시각/담당자/메뉴/온도/폐기일/수거자/수거시간 배치

---

## 5. 단순 문자열 치환 안전성 검토

### 결론

- **현재 제공된 템플릿 파일에서는 `{{...}}` 플레이스홀더가 단일 텍스트 노드에 존재한다.**
- 따라서 현재 상태만 보면 `xml.replace("{{FIELD}}", value)` 계열의 단순 문자열 치환이 우연히 동작할 가능성은 높다.

### 그러나 권장하지 않는 이유

- HWPX는 ZIP 내부 XML 패키지이다.
- 텍스트 스타일이 바뀌면 placeholder가 여러 run으로 쪼개질 수 있다.
- 단순 문자열 replace는
  - XML 구조 보존이 불안정하고
  - 네임스페이스/인코딩 처리에 취약하며
  - 후속 템플릿 편집 시 쉽게 깨질 수 있다.

### 권장 방식

- ZIP을 해제한 뒤 `section*.xml`을 XML 파서로 읽는다.
- `<hp:t>` 또는 동등 텍스트 노드를 순회하며 치환한다.
- 치환 후 다시 HWPX로 재패키징한다.
- 생성된 HWPX를 다시 열어 구조 검증을 수행한다.

---

## 6. 예상 기술적 문제

1. **HWPX 내부 런 분리 문제**
   - 현재는 분리되지 않았지만 템플릿 수정 시 발생 가능

2. **표 반복 구조 유지 문제**
   - 식단표는 2주 × 5일, 조리지시서는 7개 슬롯, 보존식은 3블록 구조를 유지해야 함

3. **출력 데이터와 템플릿 필드의 정합성 문제**
   - 현재 DTO/플레이스홀더 매핑을 문서별로 정확히 맞춰야 함

4. **HWPX 생성 후 재검증 필요**
   - 생성된 패키지가 다시 열리고 section XML이 유효한지 확인 필요

5. **PDF 변환 방식 선택 문제**
   - 현재 시스템은 HTML → PDF 방식이 있으나, 요구사항은 HWPX를 마스터 문서로 사용해야 함
   - 따라서 PDF 파이프라인은 재설계 필요 가능성이 큼

---

## 7. 구현 권장 구조

### 권장 아키텍처

```text
DB
 └─ 문서별 DTO 변환
     └─ HWPX 템플릿 엔진
         └─ HWPX 생성
             ├─ HWPX 다운로드
             └─ PDF 변환
                 └─ 미리보기/인쇄/다운로드
```

### 권장 분리

- **데이터 수집 레이어**: `document_service.py`
- **HWPX 렌더링 레이어**: `hwpx_service.py`
- **라우팅/API 레이어**: `routers/documents.py`, `routers/master_data.py`
- **템플릿 관리**: `docs/template/` 및 업로드 저장소

### 권장 원칙

- DB 모델을 그대로 템플릿에 넘기지 말고 DTO 사용
- 템플릿별 매핑 함수를 분리
- HWPX는 생성 후 다시 검증
- PDF는 HWPX 파생 산출물로 취급

---

## 8. 변경해야 할 파일 예상 목록

이 단계에서는 수정하지 않았고, 향후 구현 시 예상되는 파일만 정리한다.

- `backend/app/document_service.py`
- `backend/app/hwpx_service.py`
- `backend/app/routers/documents.py`
- `backend/app/routers/master_data.py`
- `backend/app/routers/templates.py`
- `backend/app/templates/documents/*.html` (미리보기 UI 유지 여부에 따라)
- `backend/app/static/app.js` (출력 버튼/다운로드 연결 필요 시)
- `docs/template/TEMPLATE_FIELDS.md` (실제 필드와의 정합성 보완 필요 시)
- `docs/hwpx-output-analysis.md` (현재 문서)

---

## 9. 요약 결론

- 현재 시스템은 이미 **FastAPI + SQLAlchemy + PostgreSQL + Playwright** 기반의 문서 출력 구조를 갖고 있다.
- HWPX 템플릿은 각 파일당 **단일 section 구조**이며, 플레이스홀더는 현재 모두 **단일 텍스트 노드**에 존재한다.
- `TEMPLATE_FIELDS.md`와 실제 템플릿 필드는 큰 틀에서 일치한다.
- 따라서 다음 단계에서는 **HWPX 기반 DTO/렌더링 파이프라인을 안전하게 정리**하는 것이 핵심이다.
