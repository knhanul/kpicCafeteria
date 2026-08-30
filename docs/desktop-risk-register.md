# Desktop Conversion Risk Register

## 구현 후 상태 갱신

2026-08-30 후속 구현에서 다음 위험을 코드와 자동 테스트로 완화했다.

```text
DSK-001 foreign_keys=ON
DSK-002 WAL + busy_timeout
DSK-003 UTC DateTime adapter
DSK-004 schema_migrations version 기록 기반
DSK-009 LOCALAPPDATA writable 경로
DSK-011 local-system principal
DSK-014 127.0.0.1-only bind
DSK-015 PDF 제외, HWPX-only
DSK-021 SQLite online backup + integrity_check
DSK-023 WebView2/pywebview 선택
DSK-026 binary/data directory 분리
DSK-036 Windows mutex single-instance
```

남은 주요 위험은 실제 운영 데이터 이전, active HWPX template 확보, SQLite restore UI, installer/code signing, 서명된 EXE와 실제 사용자 acceptance다. 현재 개발 PC에서는 source-mode WebView smoke가 성공했지만 unsigned PyInstaller EXE는 Application Control 정책에 의해 실행이 차단되었다.

## 1. 평가 기준

| 등급 | 의미 |
|---|---|
| Critical | 데이터 손실, 핵심 기능 불능 또는 구조 선택을 막는 장애요인 |
| High | 배포 전 반드시 해결/검증해야 하는 위험 |
| Medium | 기능 또는 운영 품질 저하 가능성 |
| Low | 제한적 영향 또는 문서/UX 보완 사항 |

가능성은 `높음/중간/낮음`, 상태는 `확인됨/미검증/확인 필요`로 기록한다.

## 2. Risk Register

| ID | 영역 | 위험 | 근거 | 가능성 | 영향 | 등급 | 완화/검증 | 상태 |
|---|---|---|---|---|---|---|---|---|
| DSK-001 | SQLite | SQLite FK가 기본 비활성이라 CASCADE, SET NULL, orphan 방지가 보장되지 않음 | `db.py`는 `check_same_thread=False`만 설정, model은 `ondelete` 다수 사용 | 높음 | 데이터 관계 훼손 | Critical | 모든 connection에 `PRAGMA foreign_keys=ON`; destructive FK test 및 `foreign_key_check` | 확인됨 |
| DSK-002 | SQLite | WAL/busy timeout/single-writer 정책 부재로 write lock 발생 가능 | engine 초기화에 concurrency PRAGMA 없음 | 중간 | 저장/Import/출력 상태 갱신 실패 | High | file-backed concurrent test, WAL/busy timeout 결정, 긴 작업을 transaction 밖으로 이동 | 확인됨 |
| DSK-003 | SQLite | timezone-aware DateTime이 SQLite에서 naive로 복원될 가능성 | model `DateTime(timezone=True)`, code는 `datetime.now(timezone.utc)`와 비교 | 높음 | Preview 만료/통계/기록 오류 | Critical | UTC serialization type 확정, round-trip 및 DST test | 확인됨 |
| DSK-004 | Migration | schema migration history/version/rollback 부재 | startup `schema_upgrade.py` + `create_all`, Alembic 없음 | 높음 | upgrade 실패/복구 불가 | Critical | version table/Alembic 검토, backup-before-upgrade, migration rehearsal | 확인됨 |
| DSK-005 | Migration | 기존 SQLite constraint migration이 불완전 | source 주석에 legacy unique constraint in-place 제거 불가 명시 | 중간 | 기존 DB upgrade 실패 | High | clean SQLite import를 기본으로 하고 table rebuild migration test | 확인됨 |
| DSK-006 | Data migration | 운영 PostgreSQL 실제 데이터와 runtime asset을 보지 못함 | 운영 접근 금지, dump/active template 미제공 | 높음 | 전환 누락/데이터 손실 | Critical | 익명화 dump + storage manifest 확보 후 격리 rehearsal | 확인 필요 |
| DSK-007 | Data migration | PostgreSQL과 SQLite의 JSON/date/time/index/constraint 의미 차이 | SQLAlchemy generic types이나 dialect 차이 존재 | 중간 | 값 또는 제약 불일치 | High | entity별 canonical export/import, row/FK/hash/sample 비교 | 미검증 |
| DSK-008 | Storage | Docker absolute `storage_path`가 Windows에서 무효 | `DocumentTemplate.storage_path`, `ImportJob.storage_path` 문자열 저장 | 높음 | template/Import file 접근 불가 | Critical | relative storage key로 migration, data-root resolver 도입 | 확인됨 |
| DSK-009 | Storage | CWD 상대경로가 설치 폴더에 생성될 수 있음 | config 기본 `./storage`, `./data`, `./cafeteria.db`; import 시 mkdir | 높음 | UAC/access denied 또는 데이터 위치 혼란 | Critical | `%LOCALAPPDATA%`/정책 경로를 app 시작 전에 주입 | 확인됨 |
| DSK-010 | Storage | DB backup만으로 HWPX template file이 복원되지 않음 | template metadata는 DB, 실제 파일은 storage | 높음 | 출력 기능 불능 | High | DB+storage manifest를 하나의 backup set으로 구성 | 확인됨 |
| DSK-011 | Auth | 로그인 UI만 제거하면 업무 API는 계속 401 반환 | 대부분 router가 `Depends(current_user)` 사용 | 높음 | 전체 업무 기능 불능 | Critical | local principal compatibility layer를 먼저 설계 | 확인됨 |
| DSK-012 | Auth | `admin_user` 제거/우회 시 backup/archive/user 권한 의미가 사라짐 | users/admin router와 Jinja role 조건 | 높음 | 관리자 기능 노출/차단 오류 | High | 단일 사용자 정책 확정, local admin semantics 정의 | 확인 필요 |
| DSK-013 | User data | User 삭제 시 FK와 actor 기록 손상 | `DocumentPreview.user_id`, `AuditLog.user_id`; 여러 `created_by` 문자열 | 높음 | migration/FK/audit 손상 | Critical | 초기에는 local-system User 유지, 완전 삭제는 별도 migration | 확인됨 |
| DSK-014 | Local security | 로그인 제거 후 local API가 LAN에 노출되면 무인증 변경 가능 | 현재 entrypoint는 `0.0.0.0` bind | 중간 | 업무 데이터 무단 변경 | Critical | desktop에서는 `127.0.0.1` 강제, startup secret/port 검토 | 확인됨 |
| DSK-015 | PDF | PDF 변환이 Windows Hancom COM에 의존 | `HWPFrame.HwpObject`, `SaveAs(..., "PDF")` | 높음 | PDF 기능 불능 | Critical | 지원 한컴 version/license matrix, capability check, fallback | 확인됨 |
| DSK-016 | PDF packaging | pywin32가 requirements에 없음 | local import 가능하지만 `requirements.txt` 미선언 | 높음 | 새 PC에서 `win32com` import 실패 | Critical | Windows dependency lock에 pywin32 고정, clean-PC test | 확인됨 |
| DSK-017 | PDF | COM bitness, desktop session, 보안 module, timing에 민감 | subprocess COM, retry, FilePathCheckerModule | 중간 | intermittent failure/hang | High | 32/64-bit matrix, timeout, process cleanup, target PC test | 미검증 |
| DSK-018 | PDF tests | 자동 테스트가 실제 COM 변환을 검증하지 않음 | `test_hwpx_pdf_renderer.py`가 fake renderer monkeypatch | 높음 | CI PASS인데 실제 PDF 실패 | High | Windows 전용 smoke test를 별도 운영 | 확인됨 |
| DSK-019 | HWPX | 운영 활성 template가 저장소 template와 동일한지 알 수 없음 | runtime storage 제외, DB row 미확인 | 높음 | 출력 layout/placeholder 오류 | Critical | 운영 template bundle과 checksum manifest 확보 | 확인 필요 |
| DSK-020 | HWPX | HWPX engine 변경 없이도 한컴 버전별 rendering 차이 가능 | ZIP/XML render 후 한컴이 실제 표시 | 중간 | 문서 layout 깨짐 | High | 세 문서 유형 golden-file 및 실제 한컴 열기 검증 | 미검증 |
| DSK-021 | Backup | 현재 in-app backup은 SQLite를 명시적으로 거부 | `admin.py`: SQLite URL이면 HTTP 400 | 높음 | PC backup 기능 없음 | Critical | SQLite online backup/restore 구현 및 integrity check | 확인됨 |
| DSK-022 | Backup | WAL 상태에서 단순 DB file copy는 일관되지 않을 수 있음 | SQLite 전환 시 예상 | 중간 | 복원 불가능 backup | Critical | SQLite backup API 사용, restore rehearsal | 미검증 |
| DSK-023 | Desktop shell | shell 기술 미확정 | pywebview/PyInstaller 미설치, package 설정 없음 | 높음 | 구현/배포 계획 미확정 | High | WebView2 wrapper와 기본 browser prototype 비교 | 확인 필요 |
| DSK-024 | WebView | Blob CSV, file upload/download, `window.open`, inline PDF가 shell별로 다름 | `app.js`에서 Blob/anchor/window.open/location 사용 | 중간 | 출력·Import UX 실패 | High | target WebView acceptance matrix | 확인됨 |
| DSK-025 | Packaging | Jinja/static/HWPX reference/hidden import 누락 가능 | 현재 Docker COPY만 존재, desktop spec 없음 | 높음 | 실행 또는 화면/출력 실패 | High | package manifest, clean VM install test | 확인됨 |
| DSK-026 | Packaging | Program Files 아래 쓰기 시 startup directory 생성 실패 | config import 시 directory 생성 | 높음 | 앱 시작 실패 | Critical | binary/data directory 분리, UAC standard user test | 확인됨 |
| DSK-027 | Packaging | installer update가 DB/storage를 덮어쓸 위험 | update 구조 없음 | 중간 | 데이터 손실 | Critical | immutable install + persistent data root, upgrade/rollback test | 확인 필요 |
| DSK-028 | Windows | Defender/백신이 unsigned executable/local server/COM을 차단할 수 있음 | desktop package 미구현 | 중간 | 설치/실행 실패 | High | 코드서명, clean managed-PC pilot | 확인 필요 |
| DSK-029 | Windows | WebView2 runtime이 target PC에 없을 수 있음 | shell 미확정 | 중간 | UI 실행 실패 | High | evergreen bootstrapper 또는 preflight | 확인 필요 |
| DSK-030 | Font/layout | Docker Noto CJK font와 Windows font 결과가 다를 수 있음 | Dockerfile에서 font 설치 | 중간 | HTML/HWPX/PDF 표시 차이 | Medium | font policy 및 golden screenshot/document test | 확인됨 |
| DSK-031 | Performance | 실제 운영 데이터 크기와 SQLite 장기 성능 미확인 | 운영 DB 미접근 | 중간 | 통계/검색 지연 | High | 익명화 full-volume fixture, query timing/index review | 확인 필요 |
| DSK-032 | Import | 대형 XLSX Apply와 UI write가 겹치면 lock/원자성 문제가 발생할 수 있음 | importer는 여러 row 후 commit, SQLite single writer | 중간 | Import 실패/부분 상태 우려 | High | isolated file DB import, rollback/count/FK test | 미검증 |
| DSK-033 | Legacy API | template/stats/document preview 경로가 중복되어 PC 대상 범위가 불명확 | `/api/templates` vs master-data, `/api/stats` vs statistics | 중간 | 불필요 package/회귀 누락 | Medium | frontend/API call graph와 test coverage로 활성 경로 확정 | 확인됨 |
| DSK-034 | Dependency | Playwright/Chromium이 설치되지만 app/test 사용처 없음 | requirements/Dockerfile에는 존재, source grep은 0 | 높음 | PC package 비대화 | Medium | 실제 사용 여부 재확인 후 desktop dependency 제외 | 확인됨 |
| DSK-035 | Diagnostics | local log/crash/support export 정책 없음 | 현재 Uvicorn console log 중심 | 높음 | 현장 장애 원인 파악 어려움 | High | rotating logs, diagnostic bundle, 민감정보 제거 | 확인 필요 |
| DSK-036 | Single instance | 같은 SQLite file을 여러 app process가 열 수 있음 | desktop lifecycle 구현 없음 | 중간 | lock/중복 작업 | High | Windows mutex/file lock 및 stale recovery | 확인 필요 |
| DSK-037 | Date UI | browser Date/ISO conversion과 local timezone 차이 가능 | `new Date(...).toISOString()` 사용 | 중간 | 보존식 시간 날짜 이동 | High | Asia/Seoul/UTC round-trip 및 DST-independent test | 확인됨 |
| DSK-038 | Test coverage | 현재 132 tests는 desktop launcher/installer/file DB를 검증하지 않음 | test suite는 주로 in-memory SQLite | 높음 | desktop-specific defect 미검출 | High | 별도 desktop integration/Windows acceptance suite | 확인됨 |
| DSK-039 | Docker baseline | 현 환경에서 app image build를 완료하지 못함 | Docker Desktop Linux daemon pipe 없음 | 중간 | 현재 server image 기준선 미확인 | Medium | daemon 실행 가능한 개발 환경에서 `docker compose build app` 재실행 | 미검증 |

## 3. 기능별 우선 Risk

### 식단/메뉴/Recipe/재료

- DSK-001 FK
- DSK-003 timezone
- DSK-004 migration
- DSK-031 performance

### 조리지시서/보존식/출력

- DSK-008 storage path
- DSK-015~020 Hancom/HWPX/PDF
- DSK-030 font/layout
- DSK-037 date/time UI

### 발주/통계

- DSK-002 lock
- DSK-007 dialect behavior
- DSK-031 performance

### Backup/Archive/Import

- DSK-010 asset-complete backup
- DSK-021~022 SQLite backup
- DSK-032 Import atomicity

### 로그인/사용자

- DSK-011~014 auth/FK/local exposure

## 4. Windows 전용 검증 Checklist

### 설치 및 실행

- [ ] 지원 Windows version에서 standard user 설치
- [ ] WebView2 설치됨/미설치 상태
- [ ] 한글 Windows username과 한글/공백 app data path
- [ ] 긴 path와 OneDrive redirect 환경
- [ ] UAC elevation 없이 DB/storage/log 생성
- [ ] 두 번 실행 시 single-instance 동작
- [ ] port 충돌 시 복구
- [ ] Defender/백신 활성 상태
- [ ] signed/unsigned installer 정책

### UI shell

- [ ] 로그인 제거 후 첫 화면 진입
- [ ] 모든 상대 `/api` 요청
- [ ] XLSX/HWPX file picker upload
- [ ] HWPX/PDF/Excel/CSV download
- [ ] Blob URL download
- [ ] `window.open` template download
- [ ] inline PDF preview
- [ ] browser back/refresh/close
- [ ] DPI 100/125/150/200%
- [ ] multi-monitor

### Hancom

- [ ] 지원 한컴 버전별 `HWPFrame.HwpObject`
- [ ] 32/64-bit compatibility
- [ ] FilePathCheckerModule
- [ ] 식단표 HWPX open/PDF
- [ ] 조리지시서 HWPX open/PDF
- [ ] 보존식 HWPX open/PDF
- [ ] 한컴 미설치 시 안내 및 HWPX fallback
- [ ] conversion timeout 및 앱 강제 종료 후 orphan process
- [ ] 임시 HWPX/PDF cleanup

### SQLite

- [ ] `foreign_keys=ON`
- [ ] `foreign_key_check`
- [ ] WAL/checkpoint
- [ ] simultaneous save/import/backup
- [ ] power-loss/crash simulation 후 integrity check
- [ ] DateTime UTC round-trip
- [ ] 대용량 migration 성능
- [ ] backup restore 및 installer upgrade 후 보존

## 5. 전환 전 필수 승인 Gate

다음 Critical 위험이 해소되기 전 실제 PC 구현/배포를 진행하지 않는다.

```text
DSK-001 SQLite FK
DSK-003 timezone
DSK-004 migration
DSK-006 실제 데이터 migration fixture
DSK-008 storage path
DSK-009 writable data directory
DSK-011 로그인/API principal
DSK-013 User FK/audit
DSK-014 localhost security
DSK-015~016 Hancom/pywin32
DSK-019 실제 template
DSK-021~022 backup/restore
DSK-026~027 install/update data safety
```

## 6. 현재 결론

현재 business 기능과 UI는 상당 부분 재사용할 수 있지만, 단순히 PostgreSQL URL을 SQLite로 바꾸고 로그인 화면을 제거하는 방식은 안전하지 않다. 먼저 SQLite foundation, storage path, local actor, Windows Hancom capability, backup/restore를 검증해야 한다.

운영 DB와 서버에는 접근하지 않았으며, 미확인 항목은 위 표에서 `확인 필요` 또는 `미검증`으로 남겼다.
