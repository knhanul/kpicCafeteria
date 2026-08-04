# 구내식당 관리 시스템 — 영양사 1인용 Full Source

`식재료_마이그레이션_기준정보.xlsx`를 업로드하여 기초데이터와 과거 식단을 생성하고, 한 화면에서 식단·조리지시·보존식·실제 식수를 관리하는 구내식당 시스템입니다.

## 주요 기능

### 기초데이터 및 과거 식단 이관

- 배식 설정: 중식 400명, 석식 100명
- 메뉴 기준정보 및 메뉴 역할
- 재료 기준정보 및 통계분석군
- 재료 별칭
- 메뉴별 100인 기준 레시피
- 같은 메뉴에 재료 구성이 다른 여러 레시피 등록 및 선택
- 과거 식단과 당시 재료 스냅샷
- 교체/병합 방식 지원
- 이관된 과거 데이터도 수정 가능

### 공통 주간 작업공간

좌측에는 월~금 주간 식단표, 오른쪽에는 선택한 배식의 업무 패널을 표시합니다.

- 식단 작성
- 조리지시서 작성
- 보존식 기록
- 실제 식수 결과 입력

기본 모드:

- 2주 표시
- 주말 열과 빈 공간 없음
- 평일 5열 전체 너비 사용

집중 작성 모드:

- 좌측 시스템 메뉴 및 상단 헤더 숨김
- 선택한 한 주만 표시
- 이전 주/다음 주 이동
- 글꼴, 카드, 입력창 확대
- 현재 선택과 입력 상태 유지


### 메뉴·재료 기준정보

- 팝업이 아닌 목록 + 우측 편집 패널
- 메뉴 등록·수정·삭제(미사용 처리)
- 재료 등록·수정·삭제(미사용 처리)
- 같은 메뉴에 여러 레시피 등록
- 재료 구성이 같고 수량만 다른 경우 기존 레시피 수정
- 레시피 재료를 엑셀처럼 그리드에 입력
- 엑셀에서 `재료명 / 100인 수량 / 단위 / 주재료` 열을 복사해 붙여넣기

### 출력

- 식단표 HTML 미리보기/PDF
- 조리지시서 HTML 미리보기/PDF
- 보존식 기록지 HTML 미리보기/PDF
- 보존식 기록지는 한 페이지 3건, 부족한 칸은 빈 양식 유지
- HWPX 문서 메뉴에서 등록한 정상 HWPX 템플릿으로 HWPX 생성

PDF는 즉시 사용할 수 있습니다. HWPX는 기관 양식의 정확한 레이아웃을 유지하기 위해 문서 유형별 템플릿을 먼저 등록합니다.

### 별도 식단 구성 대시보드

식단 입력 패널은 깔끔하게 유지하고, 통계는 독립된 대시보드에서 기간을 선택해 조회합니다.

- 주간 단백질원 구성
- 최근 4주 반복 메뉴와 마지막 제공일
- 재료 통계분석군별 사용 빈도 및 환산 가능한 중량
- 채소계와 가공식품·소스 구성 참고

## 기술 스택

- FastAPI
- SQLAlchemy 2
- PostgreSQL 16
- Jinja2 + Vanilla JavaScript
- Playwright Chromium
- Docker Compose
- Nginx

Node 빌드 과정이 없어 내부망 배포와 유지보수가 단순합니다.

## 빠른 실행 — Windows PowerShell

```powershell
cd cafeteria-nutritionist-full
Copy-Item .env.example .env
notepad .env
.\scripts\start.ps1
```

접속:

```text
http://localhost
```

초기 로그인 정보는 `.env`의 다음 값입니다.

```text
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change-me
```

운영 전 반드시 비밀번호와 `APP_SECRET`을 변경하세요.

## Docker 명령

```powershell
docker compose up --build -d
docker compose ps
docker compose logs -f app
docker compose down
```

## 최초 데이터 생성

1. 로그인합니다.
2. 좌측 `기초 데이터 구축` 메뉴를 엽니다.
3. `data/source/식재료_마이그레이션_기준정보.xlsx`를 선택합니다.
4. `파일 검증`을 실행합니다.
5. 최초 구축은 `기존 업무데이터 교체`를 선택합니다.
6. `기초데이터 생성`을 실행합니다.

기준 파일 예상 규모:

- 배식유형 2건
- 메뉴 939건
- 재료 562건
- 재료 별칭 172건
- 메뉴별 재료 약 4,200행
- 과거 식단 3,162행
- 과거 식단 재료 약 10,400행

일부 행은 원본의 수량·단위·분류 부족으로 검토 상태가 유지됩니다. 이 값들은 임의로 채우지 않습니다.

## HWPX 템플릿

`HWPX 문서` 메뉴에서 문서 유형별 템플릿을 등록합니다.

- 식단표
- 조리지시서
- 보존식 기록지

플레이스홀더 규칙은 [`templates/hwpx/README.md`](templates/hwpx/README.md)를 참고하세요.

구조:

```text
동일 preview 데이터
├─ HTML 미리보기
├─ HTML → PDF
└─ 등록 HWPX 템플릿 → 데이터 치환 → HWPX
```

HWPX 패키지를 처음부터 새로 생성하지 않으며, 템플릿의 표·행 높이·셀 병합·글꼴을 보존합니다.

## 데이터 백업

```powershell
.\scripts\backup.ps1
```

`backup/cafeteria_YYYYMMDD_HHMMSS.sql`이 생성됩니다.

## 폴더 구조

```text
backend/
  app/
    routers/          API
    templates/        화면 및 출력 HTML
    static/           UI CSS/JavaScript
    importer.py       XLSX 이관
    stats_service.py  식단 참고 통계
    document_service.py
    hwpx_service.py
  tests/
data/source/          마이그레이션 기준 XLSX
storage/              업로드, 템플릿, 생성파일
nginx/
templates/hwpx/       HWPX 플레이스홀더 규칙
scripts/
docs/
```

## 검증

```powershell
docker compose exec app pytest -q
```

직접 확인 권장 항목:

- XLSX 교체 이관과 병합 이관
- 기본 화면 월~금 5열
- 집중 작성 모드와 주 이동
- 식단 메뉴/재료 수정
- 선택적 조리지시 저장
- 보존식 기록 완료 상태
- 실제 식수 별도 저장
- HTML/PDF 문서
- HWPX 템플릿 등록 및 실제 아래아한글 열기

## 설계 원칙

- 영양사 1인이 제약 없이 사용
- 승인·확정·과거 데이터 잠금 제거
- 수정 제한보다 백업·삭제 확인·스냅샷 제공
- 조리지시는 메뉴별 필수 입력이 아님
- 주간 카드에는 조리지시서 출력과 보존식 기록 여부만 간단히 표시
- 실제 식수는 보존식 기록과 별도 저장
- 통계는 별도 대시보드에서 선택을 차단하지 않고 참고 정보만 제공
- 메뉴와 재료 삭제는 과거 스냅샷 보존을 위해 미사용 처리
