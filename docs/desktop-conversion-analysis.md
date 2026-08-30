# Desktop 전환 영향도 분석

> 2026-08-30 후속 구현에서 Windows WebView, 빈 SQLite DB, 로그인 없는 local actor, HWPX-only 정책이 적용되었다. 구현 및 검증 결과는 `desktop-user-guide.md`를 참고한다. 이 문서의 미검증 항목은 분석 당시 기준이며 실제 EXE 코드서명/운영 데이터 이전/SQLite restore는 여전히 확인 필요다.

## 1. 범위와 조사 조건

이 문서는 현재 Git 저장소의 소스와 로컬 개발 환경만 조사한 결과다. PC 버전 구현, 운영 DB 조회, 운영 서버 접속, 운영 데이터 변경은 수행하지 않았다.

조사 시작 상태:

```text
branch: main
tracking: origin/main
working tree: clean
```

확인하지 않은 운영 자료는 추측하지 않고 `확인 필요`로 표시한다.

## 2. 기준 빌드 및 테스트

로컬 도구:

```text
Python 3.12.10
Node.js v24.18.0
Docker 29.6.1
Docker Compose v5.3.0
```

| 구분 | 명령 | 결과 | 비고 |
|---|---|---|---|
| 프런트엔드 문법 | `node --check backend/app/static/app.js` | PASS | 별도 프런트엔드 build가 없어 JS 구문만 검증 |
| Python 컴파일 | `python -m compileall -q backend/app` | PASS | 소스 import/build 기초 검증 |
| 백엔드 테스트 | `pytest -q -p no:cacheprovider` | PASS, `132 passed in 34.10s` | `backend`에서 실행, 테스트 DB는 주로 in-memory SQLite |
| 현재 Docker app image | `docker compose build app` | 실행 환경 실패 | Docker Desktop Linux daemon이 실행되지 않아 API pipe에 연결하지 못함. 소스 build 오류는 확인되지 않음 |

Docker build 오류:

```text
failed to connect to the docker API at
npipe:////./pipe/dockerDesktopLinuxEngine
```

Docker daemon을 시작해 다시 검증해야 한다. 이번 단계에서는 Docker Desktop을 시작하거나 서비스를 기동하지 않았다.

### 테스트 범위의 한계

- 테스트는 대부분 각 테스트가 만든 `sqlite:///:memory:` DB를 사용한다.
- 실제 장기 보존 SQLite 파일, WAL, lock, crash recovery는 검증하지 않는다.
- PDF 테스트는 Hancom COM을 실제 실행하지 않고 fake renderer/monkeypatch로 배선만 검증한다.
- 테스트 통과는 실제 한컴 설치 PC에서 HWPX → PDF 변환이 성공한다는 의미가 아니다.
- 운영 PostgreSQL 및 운영 HWPX 템플릿은 검증하지 않았다.

## 3. 실제 기술 구성

### 프런트엔드

| 항목 | 확인 결과 |
|---|---|
| 프레임워크 | 없음. Vanilla JavaScript + DOM API |
| UI template | Jinja2 HTML |
| 스타일 | 단일 `backend/app/static/app.css` 중심 |
| JavaScript | 단일 `backend/app/static/app.js` 중심 |
| package manager | `package.json`, lock file 없음 |
| 번들러/build | 없음 |
| 외부 JS/CSS CDN | 확인되지 않음 |
| API 호출 | 브라우저 `fetch()` 기반 상대경로 `/api/...` |

`app.html`이 화면 shell과 view container를 제공하고 `app.js`가 상태, API 호출, DOM rendering, event binding을 담당한다. 로그인 화면은 `login.html` 내부 script를 사용한다.

### 백엔드

| 항목 | 버전/구성 |
|---|---|
| Python | 로컬 3.12.10, Docker base `python:3.12-slim` |
| FastAPI | 0.116.1 |
| Uvicorn | 0.35.0 |
| SQLAlchemy | 2.0.41 |
| Pydantic Settings | 2.10.1 |
| Jinja2 | 3.1.6 |
| PostgreSQL driver | psycopg 3.2.9 |
| XLSX | openpyxl 3.1.5 및 자체 `SimpleXlsxReader` |
| HWPX | ZIP/XML을 직접 다루는 자체 engine |
| PDF | Windows Hancom COM adapter |

실행 진입점:

```text
backend/entrypoint.sh
→ uvicorn app.main:app --host 0.0.0.0 --port 8000
→ backend/app/main.py
```

Startup에서 수행하는 작업:

```text
upgrade_existing_schema(engine)
Base.metadata.create_all(engine)
기본 admin 생성/권한 보정
중식·석식 기본 설정 생성
```

Alembic은 없다. Schema 변경 이력은 `schema_upgrade.py`의 조건부 직접 SQL과 `create_all()`에 의존한다.

### API 구조

| Prefix | 구현 | 역할 |
|---|---|---|
| `/api/auth` | `routers/auth.py` | 로그인, 로그아웃, 현재 사용자, 비밀번호 변경 |
| `/api/users` | `routers/users.py` | 관리자용 사용자 관리 |
| `/api/workspace` | `routers/workspace.py` | 주간 식단, 메뉴/재료 편집, 조리 비고, 보존식, 실제 식수 |
| `/api/master` | `routers/master.py` | 메뉴, Recipe, 재료, 이력/Snapshot |
| `/api/orders` | `routers/orders.py` | 필요량 집계, 발주 item/group |
| `/api/statistics` | `routers/statistics.py` | 운영·식수·메뉴·재료 통계 |
| `/api/stats` | `routers/stats.py` | 구형/별도 대시보드 통계 경로 |
| `/api/documents` | `routers/documents.py` | Preview, HWPX, PDF 출력 |
| `/api/master-data` | `routers/master_data.py` | HWPX 양식 및 배식 기본값 |
| `/api/templates` | `routers/templates.py` | 별도 HWPX template API |
| `/api/setup` | `routers/setup.py` | XLSX migration Preview/Apply |
| `/api/admin` | `routers/admin.py` | PostgreSQL backup, Excel archive |

`/api/templates`와 `/api/master-data/document-templates`, `/api/stats`와 `/api/statistics`는 역할이 겹친다. 현재 프런트엔드는 HWPX 관리에 `/api/master-data/document-templates`, 주요 분석 화면에 `/api/statistics`를 사용하지만 `/api/stats/dashboard` 참조도 일부 남아 있다. 제거 가능 여부는 이번 범위에서 확정하지 않고 `확인 필요`로 둔다.

## 4. DB 연결과 환경 의존성

`config.py` 기본값은 SQLite다.

```text
DATABASE_URL=sqlite:///./cafeteria.db
```

Docker Compose는 이를 PostgreSQL로 덮어쓴다.

```text
postgresql+psycopg://cafeteria:cafeteria@db:5432/cafeteria
```

`db.py`는 URL이 `sqlite`로 시작할 때 `check_same_thread=False`만 추가하고 나머지는 동일 SQLAlchemy Session을 사용한다.

환경변수:

| 변수 | 영향 |
|---|---|
| `APP_NAME` | UI title |
| `APP_SECRET` | SessionMiddleware cookie signing |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_DISPLAY_NAME` | startup 기본 관리자 |
| `DATABASE_URL` | DB dialect 및 위치 |
| `STORAGE_ROOT` | imports/templates/generated 파일 위치 |
| `DATA_EXPORT_ROOT` | backup/archive 파일 위치 |
| `PUBLIC_BASE_URL` | 외부 URL 설정, 현재 주요 runtime 사용처는 추가 확인 필요 |
| `TZ` | 시간대 |

설정 module import 시 저장소 directory를 즉시 생성한다. PC package 설치 폴더가 Program Files처럼 read-only이면 startup부터 실패할 수 있다.

## 5. Docker, Nginx, PostgreSQL 의존성

현재 서버 배포 topology:

```text
Host nginx
→ Docker nginx (127.0.0.1:8080 → 80)
→ FastAPI app:8000
→ PostgreSQL 16
```

Docker app image에 포함되는 외부 구성:

- PostgreSQL client (`pg_dump`)
- Noto CJK/Unifont font
- Playwright Chromium
- Linux shared libraries

PC 버전에서는 Docker, container nginx, PostgreSQL server를 제외할 수 있지만 다음 대체가 필요하다.

- Uvicorn을 localhost 전용으로 실행하고 lifecycle 관리
- PostgreSQL 대신 SQLite file lifecycle/migration/backup
- font 및 WebView runtime 검증
- 현재 Docker volume 경로를 Windows user data 경로로 전환

Playwright 1.54.0과 Chromium은 requirements/Dockerfile에 있지만 현재 `backend/app`과 tests에서 호출되지 않는다. PC package 포함 여부는 `추가 확인 필요`다.

## 6. 로그인·사용자·권한 영향

### 현재 인증 흐름

```text
/login
→ POST /api/auth/login
→ User.password_hash PBKDF2 검증
→ session["user_id"]
→ current_user dependency
→ 업무 API
```

- `SessionMiddleware`는 `APP_SECRET`, `same_site=lax`, `https_only=False`를 사용한다.
- `/`는 session user를 조회하고 비로그인 사용자를 `/login`으로 보낸다.
- 프런트 API helper는 HTTP 401에서 `/login`으로 이동한다.
- Sidebar의 사용자 관리/backup/archive는 Jinja에 전달된 `role`로 표시를 제어한다.
- 관리자 API는 `admin_user`, 나머지 대부분은 `current_user`에 의존한다.

### 사용자 외래키와 attribution

실제 `users.id` FK:

| 위치 | 용도 |
|---|---|
| `DocumentPreview.user_id` | Preview 소유권/접근 제어 |
| `AuditLog.user_id` | 작업 actor 기록 |

문자열 사용자 기록:

| 위치 | 값 |
|---|---|
| `BackupRecord.created_by` | username |
| `DocumentTemplate.created_by` | display name |
| `OrderGroup.created_by` | username |

Import audit와 backup/archive/user management도 현재 user ID에 의존한다.

### 로그인 제거 영향

로그인 UI만 숨기는 것으로 끝나지 않는다. 다음을 함께 결정해야 한다.

1. `current_user`/`admin_user`를 무엇으로 대체할지
2. 모든 local 사용자를 admin으로 간주할지
3. DocumentPreview 소유권을 제거할지 local actor로 유지할지
4. AuditLog의 actor를 보존할지
5. 기존 User table/history를 이관할지
6. 401 redirect, logout, change-password, 사용자 관리 UI를 제거할지
7. local HTTP port가 LAN에 노출되지 않도록 강제할지

권장 초기 전환은 User table/FK를 즉시 삭제하지 않고, 하나의 `local-system` actor를 내부적으로 사용하면서 로그인 화면만 거치지 않는 호환 layer다. 완전 삭제는 데이터 migration과 audit 요구가 확정된 뒤 판단한다.

분류: **수정 후 재사용 / 정책 추가 확인 필요**.

## 7. PostgreSQL → SQLite 전환 위험

### 확인된 PostgreSQL 전용 요소

`schema_upgrade.py` PostgreSQL branch:

- `TIMESTAMPTZ`
- `ALTER TABLE ... DROP CONSTRAINT IF EXISTS`
- `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
- PostgreSQL cast `id::text`
- `NOW()`
- `DO $$ ... pg_constraint ... $$`
- `ALTER COLUMN ... SET NOT NULL`
- PostgreSQL index/constraint upgrade

Backup:

- `pg_dump -F c`
- PostgreSQL URL parsing
- SQLite이면 backup API가 명시적으로 HTTP 400을 반환

일반 업무 query는 대부분 SQLAlchemy `select`, `func`, relationship loader로 작성되어 dialect 이식성이 비교적 높다. `ilike`는 SQLAlchemy가 SQLite에 맞게 변환하지만 성능/한글 검색 동작은 별도 검증이 필요하다.

### SQLite 전환 시 중대한 위험

1. **FK 강제 미설정**
   - 현재 engine에 `PRAGMA foreign_keys=ON` 설정이 없다.
   - SQLite 기본값에서는 DB-level CASCADE/SET NULL과 orphan 방지가 동작하지 않을 수 있다.

2. **동시 쓰기와 lock**
   - 하나의 `check_same_thread=False`만 설정한다.
   - WAL, busy timeout, single-writer 정책이 없다.
   - 문서/Import/backup과 UI 저장이 겹칠 때 `database is locked` 위험이 있다.

3. **Timezone**
   - Model은 `DateTime(timezone=True)`와 UTC aware datetime을 사용한다.
   - SQLite는 timezone 정보를 native type으로 보존하지 않는다.
   - DB에서 읽은 naive datetime과 `datetime.now(timezone.utc)` 비교가 충돌할 수 있다.

4. **기존 SQLite Schema upgrade**
   - custom branch가 일부 column 추가/삭제만 지원한다.
   - 소스 주석도 legacy unique constraint를 in-place 제거할 수 없다고 명시한다.
   - version table, downgrade, transaction별 migration history가 없다.

5. **JSON/Index/Constraint**
   - JSON은 SQLite에서 text affinity로 처리된다.
   - unique/index 동작은 대체로 호환되지만 실제 migration data와 query plan 검증이 필요하다.

6. **백업**
   - 실행 중 단순 file copy는 transaction/WAL 상태에 따라 일관되지 않을 수 있다.
   - SQLite backup API 또는 checkpoint 후 snapshot 정책이 필요하다.

7. **규모/성능**
   - 현재 source workbook 기준 수천 메뉴/Recipe와 1만여 Snapshot row를 처리한다.
   - 단일 PC에는 가능한 규모로 보이나 실제 운영 DB 크기와 장기 증가량은 확인하지 않았다.

## 8. 파일·출력 처리

### 저장소 구조

```text
STORAGE_ROOT/
  imports/       migration XLSX upload
  templates/     등록 HWPX templates
  generated/     생성 파일용 경로

DATA_EXPORT_ROOT/
  backup/auto
  backup/manual
  archive
```

업로드 방식:

- XLSX: random token 파일명으로 `imports/`에 복사, `ImportJob.storage_path` 저장
- HWPX: 문서 유형별 directory에 random/version filename으로 복사, `DocumentTemplate.storage_path` 저장
- generic 첨부파일 기능은 확인되지 않음

### 경로 이전 위험

`DocumentTemplate.storage_path`와 `ImportJob.storage_path`는 문자열 path를 DB에 저장한다. Docker의 `/app/storage/...` path는 Windows에서 유효하지 않다. PC 전환 시 DB의 path를 그대로 복사하면 template/import file을 찾지 못한다.

권장 방향은 absolute path 대신 `stored_filename` 또는 storage-relative key를 canonical 값으로 사용하고 runtime data root에서 path를 재구성하는 것이다.

### HWPX

- HWPX는 ZIP package와 XML을 직접 읽고 validation/rendering한다.
- 자체 engine은 Python 표준 library 중심이라 그대로 재사용 가능성이 높다.
- 기관 양식은 DB metadata와 실제 `.hwpx` 파일이 함께 있어야 한다.
- 저장소에는 reference/template 파일이 있지만 운영에서 활성화된 template와 동일한지는 `확인 필요`다.

### PDF

현재 pipeline:

```text
DB → DTO/Builder → HWPX bytes → Hancom COM → PDF bytes
```

외부 의존성:

- Windows
- Hancom Office 설치 및 라이선스
- COM ProgID `HWPFrame.HwpObject`
- `win32com.client`, `pythoncom` (pywin32)
- HWP 보안 module `FilePathCheckerModule`
- 현재 사용자 desktop session/COM 권한
- Python/한컴 32/64-bit 호환

로컬 조사 결과 `win32com`과 `pythoncom`은 현재 PC에 설치되어 있지만, `backend/requirements.txt`에는 pywin32가 없다. 새 PC package에서 재현되지 않는 중대한 dependency 누락이다.

### Excel/CSV

- Migration XLSX read: 자체 `SimpleXlsxReader`
- Archive XLSX write: openpyxl
- 통계 CSV: 브라우저 Blob download
- WebView shell을 사용하면 download, Blob URL, `window.open`, inline PDF 동작을 검증해야 한다.

## 9. 기능별 구현 위치와 분류

| 기능 | 프런트엔드 | 백엔드/데이터 | 분류 | 전환 메모 |
|---|---|---|---|---|
| 주간 식단표/식단 편집 | `app.html`, `app.js` workspace/meal editor | `routers/workspace.py`, `MealService*` | 수정 후 재사용 | API auth 제거, SQLite transaction/시간대 검증 필요 |
| 메뉴 | `app.js` master/menu picker | `routers/master.py`, `Menu` | 수정 후 재사용 | query는 대체로 portable, auth dependency 조정 |
| Recipe | `app.js` Recipe editor/Snapshot apply | `routers/master.py`, `Recipe*` | 수정 후 재사용 | unique/composition/migration 검증 |
| 재료/별칭 | `app.js` ingredient workspace | `routers/master.py`, `Ingredient*` | 수정 후 재사용 | 한글 검색/alias/FK 검증 |
| 조리지시서 | workspace cooking view | `workspace.py`, document builders | 수정 후 재사용 | 업무 로직 재사용, 출력 path/COM 검증 |
| 보존식 | preservation editor | `workspace.py`, `PreservationRecord`, document builders | 수정 후 재사용 | DateTime timezone 및 출력 검증 |
| 실제 식수 | actual editor | `workspace.py`, `MealActual` | 수정 후 재사용 | 단순 CRUD는 높은 재사용 가능성 |
| 발주 | orders view | `routers/orders.py`, `OrderItem/Group` | 수정 후 재사용 | SQLite FK/unique/transaction 검증 |
| 통계 | dashboard/stat views, CSV | `statistics.py`, 통계 service modules | 수정 후 재사용 | dialect/한글 검색/성능 검증 |
| HWPX engine/DTO | 출력 dialog | `document_builders.py`, `document_dtos.py`, `hwpx_engine.py` | 그대로 재사용 | pure-Python 부분. 실제 template regression 필요 |
| HWPX template 관리 | master-data view | `master_data.py`, `DocumentTemplate` | 수정 후 재사용 | writable data path와 relative storage key 필요 |
| PDF | inline/download UI | `document_hwpx.py`, `hwpx_pdf_renderer.py` | 수정 후 재사용 | Windows Hancom COM 및 pywin32 package 필요 |
| XLSX Import | setup UI | `setup.py`, `importer.py`, `xlsx_reader.py` | 수정 후 재사용 | storage path와 SQLite atomic import/backup 필요 |
| Excel archive | archive UI | `admin.py`, openpyxl | 수정 후 재사용 | user/admin 제거와 desktop save dialog 검토 |
| PostgreSQL backup | backup UI | `admin.py`의 `pg_dump` | PC 버전에서 제외 | SQLite online backup/restore로 대체 필요 |
| 로그인/비밀번호 | login page/sidebar | `auth.py`, `security.py`, session | 추가 확인 필요 | 단일 사용자 PC 정책이면 UI 제외, local actor/FK 전략 필요 |
| 사용자 관리/권한 | users view | `users.py`, `admin_user` | 추가 확인 필요 | 단일 사용자 여부와 감사 요구 확정 필요 |
| Docker/Nginx/PostgreSQL | 없음 | Compose/Dockerfile/Nginx | PC 버전에서 제외 | 배포/서버용 문서는 유지 가능 |
| Playwright Chromium | 직접 UI 사용 없음 | Docker dependency만 확인 | 추가 확인 필요 | 현재 app/test 사용처 없음. PC package 제외 후보 |
| 정적 UI/Jinja/CSS | 전체 | FastAPI static/template mount | 그대로 재사용 | desktop shell에서 동일 origin 제공 시 변경 최소화 |

업무 기능은 대부분 도메인 로직 자체보다 인증, SQLite, 경로, desktop shell 경계 때문에 `수정 후 재사용`으로 분류했다.

## 10. Windows에서만 검증할 수 있는 항목

- 지원 Windows 버전과 WebView2 Runtime 존재 여부
- Hancom Office 설치/라이선스/업데이트 버전
- `HWPFrame.HwpObject` COM 생성
- HWPX open 및 PDF SaveAs 결과
- FilePathCheckerModule 등록
- Python/한컴 bitness 호환
- UAC 아래 Program Files와 `%LOCALAPPDATA%` 쓰기 권한
- 한글/공백/긴 Windows path
- Defender/백신의 executable 및 local HTTP 차단
- WebView의 file upload/download, Blob CSV, `window.open`, inline PDF
- multi-monitor/DPI/scaling/프린터 환경
- installer upgrade 후 DB와 templates 보존
- app crash 후 COM process 및 temp directory 정리

## 11. 누락 또는 확인 필요 자료

| 항목 | 상태 |
|---|---|
| 실제 운영 PostgreSQL dump | 접근 금지/미확인 |
| 운영 `.env` | Git 제외, 미확인 |
| 실제 활성 HWPX template DB row와 파일 | runtime storage 제외, 미확인 |
| PC 대상 Windows version | 확인 필요 |
| 단일 사용자/복수 Windows 사용자 정책 | 확인 필요 |
| 로그인 완전 제거 여부 | 확인 필요 |
| 설치 범위(per-user/per-machine/portable) | 확인 필요 |
| Hancom Office 최소 지원 version/license | 확인 필요 |
| desktop shell(WebView2/기본 브라우저 등) | 확인 필요 |
| 자동 업데이트/코드서명 정책 | 확인 필요 |
| SQLite 암호화 필요 여부 | 확인 필요 |
| 실제 운영 데이터 크기와 증가량 | 확인 필요 |
| backup 보존 위치/외장 저장 정책 | 확인 필요 |

## 12. 중대한 장애요인

1. SQLite를 선택할 수 있다는 것과 운영 안전한 SQLite 전환이 완료되었다는 것은 다르다. FK, timezone, lock, migration, backup 보강이 선행되어야 한다.
2. 로그인 제거는 전 API, 관리자 UI, preview ownership, audit FK를 함께 변경하는 구조적 작업이다.
3. DB에 저장된 Docker absolute path는 Windows에서 유효하지 않다.
4. PDF는 Windows/한컴 COM에 의존하며 pywin32 dependency가 선언되지 않았다.
5. 운영 DB와 활성 template를 확인하지 못해 실제 migration 완전성은 현재 보증할 수 없다.
6. Docker image build 기준선은 Docker daemon 미실행으로 미확인이다.

## 13. 권장 구현 순서

1. PC 요구 확정: Windows version, 단일 사용자, 로그인, 설치 방식, Hancom 지원 범위
2. operating data export/import rehearsal용 익명화된 test fixture 확보
3. SQLite engine policy와 versioned migration 체계 구축
4. PostgreSQL → SQLite migration 검증 및 FK/count/checksum 확인
5. 모든 runtime path를 Windows writable data root + relative key로 전환
6. local trusted actor/auth compatibility layer 결정
7. localhost-only FastAPI process와 desktop shell prototype
8. 메뉴/Recipe/재료/식단/발주/통계 회귀 검증
9. HWPX 및 Hancom COM PDF를 실제 Windows 환경에서 검증
10. SQLite backup/restore와 installer upgrade/rollback 검증
11. 운영 전환 승인 후 별도 구현 단계 진행

이번 단계에서는 위 작업을 구현하지 않는다.
