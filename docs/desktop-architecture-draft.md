# Desktop Architecture Draft

## 1. 문서 성격

이 문서는 현재 웹 시스템을 Windows PC에서 단독 실행하는 경우의 **아키텍처 초안**이다. 확인되지 않은 요구사항은 `확인 필요`로 표시한다.

2026-08-30 후속 구현에서 다음 범위가 적용되었다.

```text
내장 WebView2
localhost-only FastAPI
빈 SQLite DB
로그인 없는 local-system actor
HWPX-only 출력
SQLite online backup
PyInstaller onedir build
```

운영 PostgreSQL 이전, SQLite restore UI, installer/code signing은 아직 구현하지 않았다.

## 2. 목표와 비목표

### 목표

- 현재 식단/메뉴/Recipe/재료/발주/통계 로직을 최대한 재사용
- Docker, Nginx, 별도 PostgreSQL 설치 없이 Windows PC에서 실행
- 사용자 데이터와 HWPX template를 app upgrade와 분리하여 보존
- local DB backup/restore 가능
- HWPX 출력 유지
- Hancom이 설치된 PC에서는 PDF 변환 지원 가능
- 외부 network에 API를 노출하지 않음

### 비목표

- 이번 단계에서 desktop executable 제작
- 운영 PostgreSQL data 실제 변환
- 로그인/사용자 DB 즉시 삭제
- Hancom COM 실동작 보증
- cloud sync 또는 multi-PC 동기화
- multi-user concurrent access

## 3. 권장 논리 구조

```text
┌──────────────── Windows Desktop App ────────────────┐
│                                                     │
│  Desktop shell                                      │
│  - WebView2/pywebview 또는 기본 browser             │
│  - single-instance                                  │
│  - app start/stop 및 download/open 제어              │
│                │                                    │
│                ▼ http://127.0.0.1:<local-port>      │
│  FastAPI + Uvicorn                                  │
│  - 기존 Jinja2/Vanilla JS                           │
│  - 기존 routers/services/builders                   │
│  - localhost-only                                   │
│                │                                    │
│      ┌─────────┼───────────────┐                    │
│      ▼         ▼               ▼                    │
│  SQLite DB  App data files   Hancom COM adapter     │
│             - imports        - HWPX open             │
│             - templates      - PDF SaveAs            │
│             - generated      - optional/fallback     │
│             - backups                                │
└─────────────────────────────────────────────────────┘
```

## 4. 재사용 경계

### 그대로 유지 가능한 중심부

- Jinja2 page template와 Vanilla JS/CSS
- 상대경로 `/api/...` 기반 fetch
- FastAPI routers의 request/response contract
- SQLAlchemy ORM model의 대부분
- 메뉴/Recipe/재료/Snapshot business rule
- 식단, 보존식, 실제 식수, 발주, 통계 service
- document DTO와 builder
- HWPX ZIP/XML validation/render engine
- XLSX reader와 openpyxl archive builder

### Adapter로 분리해야 할 경계

| 경계 | 현재 | Desktop 방향 |
|---|---|---|
| DB | PostgreSQL URL 또는 단순 SQLite | 정책이 적용된 SQLite engine/service |
| Auth | cookie session + User | local principal compatibility adapter |
| Storage | CWD/Docker volume path | Windows app-data path provider |
| Backup | `pg_dump` | SQLite online backup/checkpoint adapter |
| PDF | Hancom COM subprocess | 명시적 optional Windows adapter |
| Browser | 외부 browser/nginx | desktop shell/WebView lifecycle |
| Config | `.env` 중심 | 설치 기본값 + user writable config |

## 5. Desktop shell 후보

### 후보 A: Python + WebView2 wrapper

예: pywebview 계열. 현재 설치/requirements에는 포함되어 있지 않다.

장점:

- 기존 Python backend와 같은 packaging pipeline 사용 가능
- 기존 UI를 거의 그대로 표시 가능
- Windows WebView2를 활용할 수 있음

위험:

- file download, new window, inline PDF 처리 검증 필요
- WebView2 runtime 배포 정책 필요
- pywebview packaging/hidden import 검증 필요

### 후보 B: 기본 browser + local tray/launcher

장점:

- 추가 WebView framework가 최소
- 현재 browser UI와 가장 유사

위험:

- native app처럼 보이지 않음
- port/tab/process lifecycle 제어가 약함
- browser download 위치 제어가 제한됨

### 후보 C: Electron/Tauri shell

장점:

- desktop lifecycle, update, filesystem integration이 풍부

위험:

- 현재 없는 Node/Rust build stack 도입
- Python backend process bundling 복잡도 증가
- 전환 범위가 가장 큼

### 초안 권고

먼저 **후보 A와 B를 작은 prototype으로 비교**한다. 현재 구조에서는 Python process와 기존 웹 UI를 보존할 수 있는 A/B가 유리하다. 최종 shell은 target Windows version, installer, download/PDF UX 확인 후 결정해야 한다.

## 6. 프로세스 lifecycle

권장 lifecycle:

1. single-instance lock 획득
2. writable data directory 생성/검증
3. config 및 schema version 확인
4. SQLite migration 및 integrity check
5. 사용 가능한 loopback port 선택
6. Uvicorn을 `127.0.0.1`에만 시작
7. `/health` ready 확인
8. WebView/browser open
9. shell 종료 시 API process와 COM child process 종료
10. 미완료 temp file 정리

필수 안전 조건:

- `0.0.0.0` binding 금지
- startup token 또는 random local secret 사용 여부 `확인 필요`
- 다른 local process가 API를 호출할 수 있다는 위험 고려
- port collision과 stale process 복구
- 하나의 DB를 여러 app process가 동시에 열지 않도록 single-instance 강제

## 7. Windows data directory

설치 binary와 업무 data를 분리한다.

권장 예시:

```text
%LOCALAPPDATA%\KPICCafeteria\
  config\
  data\
    cafeteria.db
  storage\
    imports\
    templates\
    generated\
  backup\
  archive\
  logs\
  temp\
```

공용 PC의 모든 Windows 사용자가 같은 DB를 써야 한다면 `%PROGRAMDATA%`와 ACL 설계가 필요하다. per-user인지 per-machine인지는 `확인 필요`다.

### 경로 정책

DB에는 가능한 한 absolute path 대신 다음을 저장한다.

```text
storage kind + relative path/stored filename
```

예:

```text
templates/meal_plan/abc.hwpx
imports/token.xlsx
```

현재 `DocumentTemplate.storage_path`, `ImportJob.storage_path`를 이 정책으로 변환할 migration이 필요하다. Docker `/app/storage/...` 값을 Windows path로 문자열 치환하는 방식은 권장하지 않는다.

## 8. SQLite 설계 초안

권장 connection 초기화:

```text
PRAGMA foreign_keys = ON
PRAGMA journal_mode = WAL
PRAGMA busy_timeout = <정책값>
PRAGMA synchronous = NORMAL 또는 FULL 정책 결정
```

실제 값은 crash safety와 성능 test 후 확정한다.

### Transaction 정책

- 하나의 user action은 하나의 DB transaction
- 긴 HWPX/PDF/Excel 처리는 DB transaction 밖에서 수행
- Import Preview는 read/file validation만 수행
- Import Apply는 명확한 transaction boundary와 실패 rollback 보장
- backup 중 write 조정은 SQLite online backup API 사용
- app process 외부에서 DB file 직접 편집 금지

### Time 정책

현재 application은 UTC aware datetime을 생성한다. SQLite에는 다음 중 하나를 명시적으로 선택해야 한다.

1. UTC ISO-8601 text with offset
2. UTC epoch integer
3. SQLAlchemy custom type으로 UTC normalization

기존 `DateTime(timezone=True)`에만 의존하지 않는다. UI 변환은 Asia/Seoul 기준으로 단일화한다.

### Migration 정책

현재 `schema_upgrade.py + create_all()` 대신 최소한 다음이 필요하다.

```text
schema_migrations(version, applied_at, checksum)
```

- fresh DB create
- ordered upgrade
- backup-before-upgrade
- migration transaction
- 실패 복구
- app version과 schema version compatibility
- legacy SQLite rebuild가 필요한 constraint migration

Alembic 도입 여부는 추가 확인 사항이지만, 수동 startup SQL을 계속 확대하는 것은 권장하지 않는다.

## 9. PostgreSQL data 전환

직접 DB file 변환이 아니라 entity 기반 export/import를 사용한다.

권장 순서:

```text
PostgreSQL read-only export
→ canonical migration data
→ validation/count/hash report
→ empty SQLite schema
→ transaction import
→ FK check
→ row count/relationship/sample output 검증
```

필수 검증:

- 현재 기준정보와 과거 Snapshot 구분 유지
- primary/foreign key 관계
- nullable historical reference
- Recipe composition/default/version
- DateTime/Time/JSON 변환
- active HWPX template metadata와 실제 file
- ImportJob 같은 transient data 이관 여부
- Audit/User history 보존 여부

운영 DB에 접근하지 않았으므로 실제 mapping은 `확인 필요`다.

## 10. 로그인 제거 초안

### 권장 1단계: 호환 local actor

```text
local desktop startup
→ 내부 local-system User 확보
→ request context에 local principal 제공
→ current_user/admin_user API contract 유지
→ login UI와 password UX만 비활성화
```

장점:

- 다수의 auth dependency 사용처를 개별 제거하지 않아도 됨
- `AuditLog.user_id`, `DocumentPreview.user_id` FK 유지
- `created_by` 값 유지 가능
- business router 변경 최소화

주의:

- local principal을 cookie session으로 유지할지 request dependency에서 직접 주입할지 결정 필요
- API가 반드시 loopback에만 노출되어야 함
- 로그인 UI를 숨겼다고 network security가 생기는 것은 아님

### 권장 2단계: 정책 확정 후 정리

다음을 확인한 뒤 User table/권한의 완전 제거 여부를 결정한다.

- PC가 영양사 1인 전용인가
- 관리자 기능을 항상 허용할 것인가
- 감사 기록 actor가 필요한가
- Windows account 이름을 attribution에 사용할 것인가
- 여러 Windows 사용자가 같은 DB를 공유하는가

완전 제거 시에는 User FK migration, preview ownership, AuditLog 의미, archive/backup UI, tests를 함께 수정해야 한다.

## 11. 기능 구조

### 식단·메뉴·Recipe·재료

기존 router/service/ORM을 보존하고 DB/session adapter만 교체하는 방향이다. 메뉴/Recipe/Ingredient master와 MealService Snapshot 분리는 그대로 유지한다.

### 조리지시서·보존식

DTO/Builder와 HWPX engine을 재사용한다. template path만 desktop storage provider로 해결한다.

### 발주·통계

SQLAlchemy query는 대부분 portable하다. 실제 SQLite query plan, 한글 `LIKE`, large date range 성능을 측정하고 필요한 index만 추가한다.

### Import/Archive

기존 XLSX import/Excel archive를 재사용한다. browser download를 native save dialog로 연결할지 browser download semantics를 유지할지는 shell별 검증 후 결정한다.

## 12. HWPX/PDF 구조

### HWPX

```text
ORM data
→ DocumentBuilder
→ DTO
→ HWPX template engine
→ HWPX bytes
→ save/download
```

이 경로는 Python 기반이므로 우선 재사용한다.

### PDF

```text
HWPX bytes
→ temp .hwpx
→ isolated Hancom COM child process
→ PDF SaveAs
→ PDF validation
→ temp cleanup
```

필수 보강 후보:

- pywin32를 명시적 Windows dependency로 선언
- Hancom/COM capability startup diagnostic
- conversion timeout
- orphan HWP process cleanup 정책
- HWPX download fallback
- PDF 실패가 업무 data 저장을 rollback하지 않도록 분리

Hancom이 없는 PC에서는 PDF를 제외하고 HWPX만 제공할지 `확인 필요`다.

## 13. Backup/Restore 초안

PostgreSQL `pg_dump` 기능은 desktop runtime에서 제외한다.

SQLite 권장 backup:

1. application SQLite connection을 통한 online backup
2. backup metadata와 checksum 기록
3. 별도 backup directory에 timestamped file 저장
4. backup DB에 `PRAGMA integrity_check`
5. restore는 app 종료 또는 exclusive maintenance mode에서 수행
6. restore 전 현재 DB 자동 backup
7. installer update와 DB restore를 분리

WAL 사용 중 DB 본체만 단순 복사하는 방식은 피한다.

HWPX template와 기타 file asset도 DB backup과 함께 manifest로 묶을 필요가 있다. DB만 복원하면 template `storage_path`/file이 누락될 수 있다.

## 14. Packaging 초안

현재 저장소에는 desktop package 설정과 dependency가 없다.

검토 후보:

- PyInstaller/Nuitka: Python/FastAPI/app assets package
- WebView2 runtime bootstrap 또는 precondition check
- static/Jinja/doc templates/HWPX references 포함
- pywin32 COM hidden imports
- version metadata
- code signing certificate
- installer(MSIX/Inno Setup/WiX 등) — `확인 필요`
- per-user upgrade에서 data directory 보존

현재 로컬에는 `pywin32`가 있으나 `PyInstaller`와 `pywebview`는 설치되어 있지 않다.

## 15. 관측성과 장애 복구

권장:

- rotating local log
- startup 단계별 diagnostic
- schema version과 app version 기록
- SQLite integrity check 결과
- Hancom COM capability 결과
- last backup 시간 표시
- crash report에서 password/업무 data 제외
- UI에서 log folder 열기/diagnostic export

## 16. 권장 구현 단계와 Gate

### Phase 0: 요구 확정

- Windows version
- per-user/per-machine
- 로그인/사용자 정책
- Hancom 필수 여부
- desktop shell
- data migration/backup 요구

**Gate:** 위 항목 승인 전 package 구현 금지.

### Phase 1: SQLite foundation

- engine PRAGMA/time/migration
- file-backed isolated test DB
- backup/restore
- PostgreSQL fixture migration test

**Gate:** FK/integrity/restore 결과 승인.

### Phase 2: path/auth adapter

- Windows data root
- relative storage key migration
- local principal
- localhost-only API

**Gate:** 기존 business tests와 security boundary 통과.

### Phase 3: desktop shell prototype

- single instance
- startup/health/shutdown
- upload/download/window handling

**Gate:** target Windows에서 수동 acceptance.

### Phase 4: business regression

- 식단/기준정보/발주/통계/Import/Archive
- HWPX output

**Gate:** 기존 기준 기능 동일성 확인.

### Phase 5: Hancom PDF

- pywin32 package
- 실제 한컴 version matrix
- error/fallback/cleanup

**Gate:** 실제 Windows PC PDF acceptance.

### Phase 6: installer/update

- signing
- data-preserving upgrade
- rollback
- recovery documentation

현재 구현은 Phase 1~3의 foundation과 HWPX-only 경로까지 반영했다. 실제 운영 데이터 이전, Windows 배포 서명, SQLite restore와 전체 사용자 acceptance는 후속 Gate로 남아 있다.
