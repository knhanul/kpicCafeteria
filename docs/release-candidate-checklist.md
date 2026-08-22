# Release Candidate Checklist

이 문서는 실제 운영 배포 전에 RC 환경에서 확인할 항목을 정리합니다. 운영 배포 자체는 별도 승인 후 수행합니다.

## 1. Baseline

- [ ] 배포할 branch와 commit을 기록한다.
- [ ] `git status`와 `git diff`를 검토한다.
- [ ] 의도하지 않은 uncommitted 변경이 없는지 확인한다.
- [ ] 실제 Secret 값은 Repository와 문서에 기록하지 않는다.

## 2. Environment

- [ ] `DATABASE_URL`이 대상 DB를 가리키는지 확인한다.
- [ ] `APP_SECRET`이 기본값이 아닌 강한 값인지 확인한다.
- [ ] `ADMIN_PASSWORD`가 기본값이 아닌 강한 값인지 확인한다.
- [ ] `TZ`가 운영 정책과 일치하는지 확인한다.
- [ ] Production 환경에서 Debug/reload 설정이 없는지 확인한다.
- [ ] PostgreSQL이 필요한 범위 밖으로 외부 노출되지 않는지 확인한다.

## 3. Database

- [ ] Model과 실제 DB Schema의 핵심 Table/Column이 일치하는지 확인한다.
- [ ] 배포 직전 `pg_dump`를 실행한다.
- [ ] Backup 파일 크기와 명령 종료 상태를 확인한다.
- [ ] Restore는 원본이 아닌 별도 격리 DB에서 수행한다.
- [ ] Restore 후 핵심 Table Count를 원본과 비교한다.
- [ ] Restore DB의 FK Orphan을 점검한다.
- [ ] Migration 또는 startup schema upgrade의 영향을 확인한다.

## 4. Docker

- [ ] `docker compose build`가 성공한다.
- [ ] `docker compose up --build -d`가 성공한다.
- [ ] app가 `Up` 상태인지 확인한다.
- [ ] db가 `healthy` 상태인지 확인한다.
- [ ] nginx가 `Up` 상태인지 확인한다.
- [ ] `docker compose down` 후 `docker compose up -d`를 수행한다.
- [ ] 재기동 전후 핵심 데이터 Count가 일치하는지 확인한다.
- [ ] `docker compose down -v`는 운영 환경에서 사용하지 않는다.

## 5. Application Smoke Test

- [ ] `GET /health`가 200을 반환한다.
- [ ] `/login`이 200을 반환한다.
- [ ] 실제 로그인 Flow가 동작한다.
- [ ] 식단 작성 화면과 기존 데이터가 열린다.
- [ ] 메뉴/레시피 기준정보가 열린다.
- [ ] 재료 기준정보가 열린다.
- [ ] 발주 화면이 열린다.
- [ ] 통계 화면이 열린다.
- [ ] 예기치 않은 Browser Console Error가 없다.
- [ ] app/nginx 로그에 반복적인 5xx 또는 Traceback이 없다.

## 6. HWPX

- [ ] 식단표 HWPX를 생성한다.
- [ ] 조리지시서 HWPX를 생성한다.
- [ ] 보존식 기록지 HWPX를 생성한다.
- [ ] ZIP Package를 열 수 있는지 확인한다.
- [ ] 내부 XML이 Parse되는지 확인한다.
- [ ] 미치환 Placeholder가 없는지 확인한다.
- [ ] 반복 Page와 마지막 Page를 기술적으로 확인한다.
- [ ] 가능하면 Windows 한글 환경에서 육안 검수한다.
- [ ] 육안 검수를 하지 못했다면 배포 승인 시 별도로 표시한다.

## 7. Rollback

### App Rollback

1. 현재 배포 commit/image를 기록한다.
2. 문제 발생 시 App 트래픽을 중지하거나 이전 App image/commit으로 전환한다.
3. `docker compose up -d`로 이전 App을 기동한다.
4. `/health`, 로그인, 핵심 화면을 확인한다.

### DB Recovery

1. 배포 직전 Backup 파일과 checksum을 보존한다.
2. App 쓰기를 중지한다.
3. 원본 DB에 바로 Restore하지 말고 Backup을 별도 DB에 먼저 검증한다.
4. 복구가 필요하면 승인된 운영 복구 절차에 따라 원본 DB를 복구한다.
5. Restore 후 핵심 Count, FK 무결성, 로그인, 핵심 업무를 재검증한다.

## 8. Final Gate

- [ ] 전체 Test Suite가 0 failed이다.
- [ ] Backup/Restore/Integrity가 PASS이다.
- [ ] Docker Restart와 Data Persistence가 PASS이다.
- [ ] Health/Login이 PASS이다.
- [ ] 핵심 업무 화면이 PASS이다.
- [ ] HWPX Technical Validation이 PASS이다.
- [ ] HWPX Visual Validation 상태를 별도로 기록했다.
- [ ] Release Blocking Issue가 없다.
- [ ] 실제 운영 배포 승인을 별도로 받았다.
