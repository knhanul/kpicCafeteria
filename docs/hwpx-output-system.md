# HWPX Output System

## 1. 목적

이 시스템의 목표는 **DB의 급식 데이터를 기준으로 출력용 DTO를 만들고, 생성된 HWPX를 원본으로 PDF 미리보기를 제공하는 것**이다.

핵심 원칙은 다음과 같다.

- DB → DTO → HWPX 생성 → PDF 변환 순서를 유지한다.
- HWPX를 건너뛰는 직접 HTML/PDF 출력은 사용하지 않는다.
- PDF 미리보기와 HWPX 다운로드는 같은 데이터 소스에서 생성된다.
- 출력 기능은 기존 식단 작성 UX를 크게 바꾸지 않고 자연스럽게 추가한다.

---

## 2. 전체 아키텍처

```text
DB / ORM
  └─ document_builders.py
       └─ document_dtos.py
            └─ document_hwpx.py
                 ├─ hwpx_engine.py
                 │    └─ HWPX 생성
                 └─ hwpx_pdf_renderer.py
                      └─ HWPX → PDF 변환
                           ├─ 다운로드 API
                           └─ 미리보기 API
```

### 주요 레이어

- **데이터 수집 레이어**
  - `backend/app/document_service.py`
  - `backend/app/document_builders.py`
- **문서 DTO 레이어**
  - `backend/app/document_dtos.py`
- **HWPX 렌더링 레이어**
  - `backend/app/hwpx_engine.py`
  - `backend/app/hwpx_service.py`
  - `backend/app/document_hwpx.py`
- **PDF 렌더링 레이어**
  - `backend/app/hwpx_pdf_renderer.py`
- **API 레이어**
  - `backend/app/routers/documents.py`
- **프론트엔드 UI 레이어**
  - `backend/app/static/app.js`
  - `backend/app/static/app.css`
  - `backend/app/templates/app.html`

---

## 3. 템플릿 위치

실제 출력 템플릿은 다음 위치에 있다.

- `docs/template/식단표_원본템플릿.hwpx`
- `docs/template/조리지시서_원본템플릿.hwpx`
- `docs/template/보존식기록지_원본템플릿.hwpx`

추가로 템플릿 필드 맵과 관리 기준은 다음 문서를 함께 본다.

- `docs/template/TEMPLATE_FIELDS.md`

### 템플릿 저장 방식

- 업로드된 템플릿은 `DocumentTemplate.storage_path`에 저장된다.
- 활성 템플릿은 `active_template()`로 조회한다.
- 실제 PDF/HWPX 출력은 **활성 템플릿 경로**를 기준으로 수행한다.

---

## 4. DTO 구조

문서 출력은 ORM 객체를 바로 사용하지 않고 **출력 전용 DTO**로 변환한다.

### 4-1. 식단표

- `MealPlanDocumentDTO`
- `period`
- `weeks[]`
- `days[]`
- 각 일자별 `lunch`, `dinner`
- 각 식사 블록에 `menus[]`

### 4-2. 조리지시서

- `CookingInstructionDocumentDTO`
- `days[]`
- 각 일자별 `lunch`, `dinner`
- 각 메뉴에 `ingredients[]`
- 재료는 `quantity`, `quantity_per_100`, `unit`, `remark`를 포함

### 4-3. 보존식 기록지

- `PreservationRecordDocumentDTO`
- `records[]`
- 각 record는 날짜, 식사명, 수거 시각, 담당자, 메뉴 목록, 폐기 시각 등을 포함

### DTO 생성 규칙

- DTO는 `document_builders.py`에서 생성한다.
- 정렬 순서는 서비스 날짜와 식사 유형 순서를 따른다.
- 누락값은 예외 대신 빈 값/None으로 보존한다.
- 출력용 순서는 메뉴/재료 입력 순서를 유지한다.

---

## 5. HWPX 생성 과정

### 5-1. 입력

- 날짜 범위 또는 서비스 ID 목록
- 활성 HWPX 템플릿 경로
- 문서 유형

### 5-2. 처리 단계

1. `document_service.resolve_services()`로 대상 배식을 조회한다.
2. `document_hwpx.build_document_dto()`로 문서별 DTO를 만든다.
3. `document_hwpx.build_hwpx_render_request()`로 HWPX 렌더 요청 payload를 만든다.
4. `hwpx_engine.render_document()`가 템플릿을 로드하고 플레이스홀더를 치환한다.
5. 결과 HWPX는 ZIP/XML 무결성 검증을 거쳐 bytes로 반환된다.

### 5-3. 검증

`hwpx_engine`는 다음을 검증한다.

- ZIP 구조 무결성
- 필수 파일 존재 여부
- XML 파싱 가능 여부
- manifest/spine 참조 일치 여부
- 문서 유형별 필수 플레이스홀더 존재 여부
- 저장 후 재검증(reopen)

---

## 6. PDF 변환 과정

### 6-1. 변환 흐름

- `document_hwpx.generate_pdf_bytes()`
- 먼저 `generate_hwpx_bytes()`로 HWPX bytes를 만든다.
- 그 HWPX bytes를 `hwpx_pdf_renderer.default_pdf_renderer()`에 넘긴다.
- 현재 구현은 Windows + Hancom Office COM 기반이다.

### 6-2. 현재 구현

`hwpx_pdf_renderer.py`의 기본 렌더러는 다음 방식으로 동작한다.

- 임시 디렉터리 생성
- HWPX bytes를 임시 `.hwpx` 파일로 저장
- Hancom COM `HWPFrame.HwpObject` 생성
- HWPX 열기
- PDF로 SaveAs
- PDF bytes 확인
- 임시 디렉터리 정리

### 6-3. 왜 이렇게 했는가

- HWPX를 마스터 출력물로 유지할 수 있다.
- HTML 기반 미리보기를 우회하지 않는다.
- UI/API 변경 없이 렌더러만 교체 가능한 구조다.

---

## 7. API 목록

### 7-1. 기존 미리보기/다운로드

- `POST /api/documents/preview`
  - 기존 토큰 기반 미리보기 생성
- `GET /preview/{token}`
  - HTML 미리보기 페이지
- `GET /api/documents/{token}/pdf`
  - 토큰 기반 PDF 다운로드
- `GET /api/documents/{token}/hwpx`
  - 토큰 기반 HWPX 다운로드

### 7-2. HWPX 출력 다운로드

- `POST /api/documents/meal-plan/hwpx`
- `POST /api/documents/cooking-instruction/hwpx`
- `POST /api/documents/preserved-food/hwpx`
- `POST /api/documents/preservation-record/hwpx`

### 7-3. 출력 미리보기

- `POST /api/documents/meal-plan/preview`
- `POST /api/documents/cooking-instruction/preview`
- `POST /api/documents/preserved-food/preview`
- `POST /api/documents/preservation-record/preview`

### 출력 미리보기 요청 형식

요청 바디는 다음처럼 날짜 범위만 전달한다.

```json
{
  "start_date": "2026-08-17",
  "end_date": "2026-08-21"
}
```

### 응답

- 성공 시 PDF bytes를 inline response로 반환
- `Content-Type: application/pdf`
- `Content-Disposition: inline; filename*=UTF-8''...`

---

## 8. frontend 흐름

### 진입점

`app.html`의 기존 문서 출력 버튼을 사용한다.

- 버튼 라벨: `출력 미리보기`
- 기존 식단 작성/조리지시서 작성 UX는 유지한다.

### 동작 흐름

1. 사용자가 출력 미리보기를 누른다.
2. 현재 화면의 조회 기간(`state.workspace.start`, `state.workspace.end`)을 사용한다.
3. 문서 유형 선택 모달이 열린다.
4. 서버의 preview API를 호출한다.
5. 생성 중에는 loading 상태를 보여준다.
6. 성공하면 PDF를 modal 안의 iframe에서 보여준다.
7. 사용자는 다음을 수행할 수 있다.
   - HWPX 다운로드
   - PDF 다운로드
   - 인쇄
   - 페이지 이동은 브라우저 PDF 뷰어 기능 사용

### UI 파일

- `backend/app/static/app.js`
- `backend/app/static/app.css`

### UX 원칙

- 새 라이브러리를 추가하지 않는다.
- 기존 디자인 시스템(`primary-button`, `secondary-button`, `modal`, `toast`)을 그대로 사용한다.
- PDF 미리보기 실패 시에도 HWPX 다운로드는 가능해야 한다.

---

## 9. 새 템플릿 추가 방법

1. 새 HWPX 템플릿 파일을 준비한다.
2. `docs/template/`에 저장하거나 업로드 기능으로 `DocumentTemplate`를 등록한다.
3. `DocumentTemplate.document_type`를 올바르게 지정한다.
4. 템플릿을 활성화한다.
5. `hwpx_service.validate_hwpx()`로 템플릿 검증을 통과시킨다.
6. 필요하면 `docs/template/TEMPLATE_FIELDS.md`를 갱신한다.
7. 필요한 경우 `hwpx_engine.REQUIRED_PLACEHOLDERS`도 같이 갱신한다.

---

## 10. 플레이스홀더 추가 방법

플레이스홀더를 새로 늘릴 때는 다음을 함께 수정한다.

- 템플릿 내부 XML
- `docs/template/TEMPLATE_FIELDS.md`
- `hwpx_engine.py`의 문서별 필수 플레이스홀더 목록
- 해당 renderer의 필드 매핑
- 관련 테스트

권장 순서:

1. 템플릿에 토큰을 추가한다.
2. DTO에 필요한 값이 있는지 확인한다.
3. `hwpx_engine`의 필수 토큰 검증을 맞춘다.
4. 테스트를 추가한다.

---

## 11. 반복 영역 추가 방법

반복 영역은 단순 문자열 치환이 아니라 **섹션/행/블록 단위의 복제**로 처리한다.

### 식단표

- 주차와 일자 수에 따라 문서 섹션/페이지 매핑을 유지한다.
- 빈 일자도 레이아웃이 깨지지 않도록 placeholder를 남기지 않고 빈 값으로 채운다.

### 조리지시서

- 날짜별 섹션을 복제한다.
- 메뉴 수와 재료 수가 늘어도 동일한 구조를 유지하도록 복제 후 채운다.

### 보존식 기록지

- 기록 개수에 따라 페이지/섹션을 반복한다.
- 3건 단위 페이지 구조가 깨지지 않도록 빈 슬롯도 생성한다.

### 구현 시 주의점

- 반복 영역은 템플릿 XML 구조와 강하게 연결된다.
- 템플릿을 수정할 때는 현재 `hwpx_engine`의 clone/remove 로직과 함께 변경해야 한다.
- 테스트에서 섹션 수와 플레이스홀더 제거 여부를 같이 확인해야 한다.

---

## 12. 장애 발생 시 확인 방법

### 12-1. HWPX 생성 실패

확인할 것:

- 활성 템플릿이 있는가
- `DocumentTemplate.storage_path`가 올바른가
- `validate_hwpx()`가 통과하는가
- 필수 플레이스홀더가 모두 있는가
- DTO에 필요한 데이터가 비어 있지 않은가

### 12-2. PDF 변환 실패

확인할 것:

- Windows 환경인가
- Hancom Office가 설치되어 있는가
- COM `HWPFrame.HwpObject`가 동작하는가
- 임시 파일이 정상 생성되는가
- `Hancom PDF` 관련 환경이 준비되어 있는가

### 12-3. 미리보기 UI 실패

확인할 것:

- 브라우저 팝업 차단 여부
- 네트워크 오류
- preview API 응답 상태
- pdf blob URL 생성 여부

### 12-4. XML/package 무결성 검사

자동 검사에서 우선 확인하는 것:

- ZIP 손상 여부
- `archive.testzip()` 결과
- `section*.xml` 존재 여부
- `{{...}}` 토큰이 남아 있는지
- 생성된 HWPX를 다시 열 수 있는지

---

## 13. 자동 테스트와 수동 확인 분리

### 자동 테스트에서 검증한 것

- HWPX ZIP/package 무결성
- XML 파싱 가능 여부
- 플레이스홀더 제거 여부
- 문서별 DTO 생성
- HWPX 다운로드 응답 형식
- PDF가 HWPX-first 파이프라인을 따른다는 점
- preview/download가 같은 HWPX 소스에서 파생되는 점

### 자동 테스트로는 한계가 있는 것

다음은 **Hancom Office의 실제 실행 환경**이 필요하므로 수동 확인을 권장한다.

- 한글에서 정상 열림
- 문서 복구 메시지 없음
- 글자 깨짐 없음
- 표 깨짐 없음
- 편집 가능 여부
- 메뉴 수정 가능 여부
- 식재료 수정 가능 여부
- 저장 가능 여부
- 다시 열기 가능 여부

### 수동 확인 절차

1. 세 파일을 다운로드한다.
   - `식단표.hwpx`
   - `조리지시서.hwpx`
   - `보존식기록지.hwpx`
2. 한글에서 연다.
3. 복구 경고나 깨짐이 없는지 확인한다.
4. 표/줄바꿈/페이지 나눔을 확인한다.
5. 텍스트를 일부 수정한다.
6. 저장 후 다시 연다.
7. PDF와 나란히 비교해 레이아웃 차이를 확인한다.

---

## 14. 알려진 제약사항

- PDF 미리보기는 현재 Windows + Hancom Office COM 환경에 의존한다.
- Linux/Docker-only 환경에서는 동일 품질을 보장하지 않는다.
- 브라우저 PDF 뷰어는 한글 편집기와 페이지 처리 결과가 완전히 같지 않을 수 있다.
- 자동 테스트는 편집 가능성 자체를 완전 대체할 수 없다.
- COM 기반 PDF 변환은 데스크톱 세션/스타트업 타이밍에 민감할 수 있다.

---

## 15. 참고 파일

- `backend/app/document_builders.py`
- `backend/app/document_dtos.py`
- `backend/app/document_hwpx.py`
- `backend/app/hwpx_engine.py`
- `backend/app/hwpx_pdf_renderer.py`
- `backend/app/routers/documents.py`
- `backend/app/static/app.js`
- `backend/app/static/app.css`
- `backend/tests/test_document_hwpx.py`
- `backend/tests/test_hwpx_engine.py`
- `backend/tests/test_hwpx_output_system.py`
- `docs/template/TEMPLATE_FIELDS.md`

## 16. 요약

이 시스템은 **HWPX를 정본으로 생성하고, 그 결과를 PDF 미리보기/다운로드에 재사용하는 구조**다.

자동화된 테스트는 패키지 무결성과 HWPX-first 흐름을 검증하고, 한글 편집 가능성 및 실제 출력 품질은 수동 절차로 별도 확인한다.
