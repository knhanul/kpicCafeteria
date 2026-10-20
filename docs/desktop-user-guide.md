# 구내식당 관리 PC 버전

## 지원 범위

현재 PC 버전은 다음 정책으로 구현되어 있다.

```text
운영체제: Windows
화면: 내장 WebView2
DB: 로컬 SQLite
로그인: 없음
초기 데이터: 빈 DB
출력: HWPX만 지원
```

기존 Docker/PostgreSQL 서버 버전은 그대로 유지된다. PC 모드는 별도 launcher가 환경변수를 설정한 뒤 동일 FastAPI/Jinja/Vanilla JavaScript 애플리케이션을 localhost에서 실행한다.

## 개발 실행

### 1. Desktop 환경 설치

```powershell
cd C:\Pjt\kpicCafeteria
python -m venv .desktop-venv
.\.desktop-venv\Scripts\python.exe -m pip install -r .\backend\requirements-desktop.txt
```

### 2. 실행

```powershell
.\scripts\start-desktop.ps1
```

로그인 화면 없이 구내식당 관리 창이 열린다. 동시에 두 개를 실행할 수 없다.

## 실행 파일 빌드

```powershell
cd C:\Pjt\kpicCafeteria
.\scripts\build-desktop.ps1
```

스크립트가 버전과 생성일을 입력받는다. 버전은 `1.2.3`처럼 숫자와 점(최대 3단계)만 입력할 수 있고 Enter는 `1.0.0`이 기본이다. `-Version`, `-BuildDate` 파라미터로 직접 전달할 수도 있다.

```powershell
.\scripts\build-desktop.ps1 -Version 1.0.0 -BuildDate 2026-10-20
```

아이콘은 `backend\app\static\assets\ci.png`에서 생성한다.

결과:

```text
desktop-dist\KPICCafeteria.exe
```

단일 실행 파일 하나가 배포 단위다.

회사/기관 Windows Application Control이나 백신 정책에서는 서명되지 않은 PyInstaller EXE가 차단될 수 있다. 이 경우 코드서명 인증서와 허용 정책이 필요하다.

## 데이터 위치

기본 위치:

```text
%LOCALAPPDATA%\KPICCafeteria\
```

구조:

```text
%LOCALAPPDATA%\KPICCafeteria\
  .desktop-secret
  data\
    cafeteria.db
  storage\
    imports\
    templates\
    generated\
  exports\
    backup\
      auto\
      manual\
    archive\
  logs\
```

실행 파일을 업데이트해도 이 폴더를 삭제하거나 덮어쓰면 안 된다.

## 최초 데이터 구축

PC 버전은 빈 SQLite DB로 시작한다.

1. `설정`을 연다.
2. `기본 데이터 관리`를 선택한다.
3. `기초 데이터 구축`을 선택한다.
4. Canonical Migration XLSX를 업로드한다.
5. Preview 결과를 확인한다.
6. 명시적으로 Apply한다.

기존 PostgreSQL 운영 데이터를 자동으로 가져오지는 않는다.

## HWPX 양식

빈 DB에는 활성 HWPX 양식이 없다.

1. `설정 > 기본 데이터 관리 > HWPX 양식 관리`로 이동한다.
2. 식단표, 조리지시서, 보존식 기록지 양식을 등록한다.
3. 검증한다.
4. 사용할 양식을 활성화한다.

양식 파일은 `%LOCALAPPDATA%\KPICCafeteria\storage\templates`에 저장된다.

## 출력

PC 버전은 HWPX 다운로드만 제공한다.

```text
식단표 HWPX
조리지시서 HWPX
보존식 기록지 HWPX
```

PDF API는 PC 모드에서 HTTP 404와 다음 메시지를 반환한다.

```text
PC 버전에서는 HWPX 출력만 지원합니다.
```

## Backup

`설정 > 시스템 데이터 백업`에서 backup을 생성할 수 있다.

PC 모드에서는 PostgreSQL `pg_dump` 대신 SQLite online backup API를 사용한다. 생성 후 `PRAGMA integrity_check`가 통과해야 완료로 기록된다.

Backup 파일:

```text
cafeteria_db_backup_manual_YYYYMMDD_HHMMSS.db
cafeteria_db_backup_auto_YYYYMMDD_HHMMSS.db
```

DB backup과 HWPX template 파일은 별도다. 완전한 재해 복구를 위해 다음 두 위치를 함께 보관한다.

```text
%LOCALAPPDATA%\KPICCafeteria\exports\backup
%LOCALAPPDATA%\KPICCafeteria\storage\templates
```

## Restore

`설정 > 시스템 데이터 백업`에서 백업 파일을 되돌릴 수 있다.

- 백업 목록의 `복원` 버튼: 보관 중인 백업 파일로 복원한다.
- `백업파일로 복원` 버튼: 다른 PC에서 가져온 `.db` 백업 파일을 업로드해 복원한다.

복원 전에는 현재 상태의 안전 백업(`backup/auto`)이 자동으로 만들어지고, 복원 파일은 SQLite magic과 `PRAGMA integrity_check`로 검증한다. 복원 후에는 스키마 정합 절차가 자동으로 실행되고, 다른 PC에서 가져온 DB의 HWPX 양식 경로는 현재 데이터 폴더 기준으로 다시 찾는다(양식 파일은 `storage\templates`를 함께 복사해야 한다).

DB만 다른 PC로 옮길 때 HWPX 양식 파일이 함께 없으면 양식 관리에서 파일이 없다고 표시되며, `storage\templates` 폴더를 같이 복사하면 경로가 자동으로 재해석된다.

PostgreSQL 서버 버전도 같은 화면에서 `.dump` 복원을 지원한다(`pg_restore --clean --if-exists`).

## SQLite 안전 설정

PC launcher가 사용하는 SQLite engine에는 다음 설정이 적용된다.

```text
PRAGMA foreign_keys=ON
PRAGMA journal_mode=WAL
PRAGMA busy_timeout=30000
PRAGMA synchronous=NORMAL
```

DateTime은 DB 저장 전 UTC로 정규화하고 SQLite에서 읽을 때 UTC timezone을 복원한다.

`schema_migrations` table에 현재 Desktop schema version을 기록한다.

## 로그인 제거 방식

PC 모드에서는 로그인/로그아웃/비밀번호 변경/사용자 관리 router와 UI를 제공하지 않는다.

기존 API와 Audit FK 호환성을 위해 내부적으로 다음 local actor를 유지한다.

```text
username: local-system
role: admin
display name: 로컬 사용자
```

FastAPI는 random local port의 `127.0.0.1`에만 bind된다. LAN에는 노출하지 않는다.

## 검증 결과

```text
Desktop focused tests: 8 passed
Full regression: 141 passed
JavaScript syntax: PASS
Python compile: PASS
PyInstaller onedir build: PASS
Source-mode WebView smoke: PASS
```

PyInstaller EXE 직접 smoke는 현재 개발 PC의 Application Control 정책에 의해 차단되어 `확인 필요`다. Source-mode WebView는 같은 PC에서 정상적으로 10초 이상 실행됨을 확인했다.

## 문제 해결

### WebView2 오류

Microsoft Edge WebView2 Runtime 설치 여부를 확인한다.

### 앱이 이미 실행 중이라는 메시지

작업 관리자에서 기존 `KPICCafeteria` 또는 Desktop Python process가 남아 있는지 확인한다. 강제 종료 후 다시 실행한다.

### DB가 열리지 않음

다음 폴더 쓰기 권한을 확인한다.

```text
%LOCALAPPDATA%\KPICCafeteria
```

### HWPX 출력 실패

활성 HWPX 양식이 등록되어 있는지 확인하고, 양식 검증을 다시 실행한다.
