# 구내식당 관리 시스템 — 실행 및 배포 가이드

## 1. 사전 요구사항

- **Docker** 24 이상
- **Docker Compose** v2 이상
- 포트 80 사용 가능 (nginx)

Windows 환경에서는 PowerShell을 관리자 권한으로 실행합니다.

## 2. 환경 설정

### 2.1 `.env` 파일 생성

```powershell
Copy-Item .env.example .env
```

### 2.2 `.env` 항목 편집

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `APP_NAME` | 시스템 이름 | `구내식당 관리 시스템` |
| `APP_SECRET` | 세션 암호화 키 | 운영 전 반드시 변경 |
| `ADMIN_USERNAME` | 초기 관리자 ID | `admin` |
| `ADMIN_PASSWORD` | 초기 관리자 비밀번호 | 운영 전 반드시 변경 |
| `ADMIN_DISPLAY_NAME` | 관리자 표시명 | `영양사` |
| `DATABASE_URL` | PostgreSQL 연결 문자열 | `postgresql+psycopg://cafeteria:cafeteria@db:5432/cafeteria` |
| `TZ` | 시간대 | `Asia/Seoul` |
| `STORAGE_ROOT` | 파일 저장 경로 (컨테이너 내부) | `/app/storage` |
| `PUBLIC_BASE_URL` | 외부 접속 URL | `http://localhost` |

> **주의**: 운영 배포 전 `APP_SECRET`과 `ADMIN_PASSWORD`를 반드시 변경하세요.

## 3. 로컬 실행 (개발/테스트)

### 3.1 스크립트 사용 (Windows PowerShell)

```powershell
.\scripts\start.ps1
```

스크립트가 수행하는 작업:
1. `.env` 파일이 없으면 `.env.example`에서 복사
2. `docker compose up --build -d` 실행
3. 컨테이너 상태 출력

### 3.2 수동 실행

```powershell
docker compose up --build -d
docker compose ps
```

### 3.3 접속

```
http://localhost
```

초기 로그인 정보는 `.env`의 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 값입니다.

### 3.4 로그 확인

```powershell
.\scripts\logs.ps1
# 또는
docker compose logs -f app
```

### 3.5 중지

```powershell
.\scripts\stop.ps1
# 또는
docker compose down
```

### 3.6 Linux/macOS에서 실행

```bash
cp .env.example .env
./scripts/start.sh
```

## 4. 서버 배포 (운영)

### 개발 PC

```powershell
# 1) ZIP 생성

cd C:\Pjt\kpicCafeteria

tar.exe -a -c -f ".\dist\cafeteria-update.zip" `
  --exclude=".git" `
  --exclude=".venv" `
  --exclude=".env" `
  --exclude="backend/data" `
  --exclude="backend/storage" `
  .

# 2) 서버 업로드

scp ".\dist\cafeteria-update.zip" root@8.219.243.65:/tmp/cafeteria-update.zip

```

### 서버

set -euo pipefail

cd /opt/cafeteria

# --------------------------------------
# 1. 배포 ID
# --------------------------------------

TS=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR=/opt/cafeteria-backups

mkdir -p "$BACKUP_DIR"


# --------------------------------------
# 2. 환경설정 백업
# --------------------------------------

cp .env "$BACKUP_DIR/env-$TS"
chmod 600 "$BACKUP_DIR/env-$TS"


# --------------------------------------
# 3. DB 백업
# --------------------------------------

docker compose exec -T db \
  pg_dump -U cafeteria cafeteria \
  | gzip > "$BACKUP_DIR/db-$TS.sql.gz"

test -s "$BACKUP_DIR/db-$TS.sql.gz"
gzip -t "$BACKUP_DIR/db-$TS.sql.gz"


# --------------------------------------
# 4. 현재 소스 백업
# --------------------------------------

tar \
  --exclude='.venv' \
  --exclude='.git' \
  --exclude='data' \
  --exclude='storage' \
  -czf "$BACKUP_DIR/source-$TS.tar.gz" \
  -C /opt/cafeteria .


# --------------------------------------
# 5. 새 배포본 압축 해제
# --------------------------------------

rm -rf /tmp/cafeteria-update
mkdir -p /tmp/cafeteria-update

unzip -q /tmp/cafeteria-update.zip \
  -d /tmp/cafeteria-update


# --------------------------------------
# 6. 배포본 검증
# --------------------------------------

test -f /tmp/cafeteria-update/docker-compose.yml
test -d /tmp/cafeteria-update/backend


# --------------------------------------
# 7. 소스 반영
# --------------------------------------

rsync -a --delete \
  --exclude='.env' \
  --exclude='data/' \
  --exclude='storage/' \
  --exclude='.git/' \
  --exclude='.venv/' \
  /tmp/cafeteria-update/ \
  /opt/cafeteria/


# --------------------------------------
# 8. Docker 설정 검증
# --------------------------------------

cd /opt/cafeteria

docker compose config -q


# --------------------------------------
# 9. 이미지 빌드
# --------------------------------------

docker compose build


# --------------------------------------
# 10. 서비스 반영
# --------------------------------------

docker compose up -d --remove-orphans


# --------------------------------------
# 11. 상태 확인
# --------------------------------------

docker compose ps

docker compose logs --tail=100 app


# --------------------------------------
# 12. 내부 Health Check
# --------------------------------------

curl --fail --silent --show-error \
  http://127.0.0.1:8080/health


# --------------------------------------
# 13. 외부 Health Check
# --------------------------------------

curl --fail --silent --show-error \
  https://post.nuni.co.kr/health

echo
echo "Deployment successful: $TS"


# ============================================================
# 부록: Git Push → Pull 배포 방법
# ============================================================
#
# ZIP 파일을 수동으로 업로드하는 기본 방식 대신, Git 저장소를 통해
# 개발 PC에서 push 한 뒤 서버에서 pull 하는 배포 방식입니다.
#
# 전제 조건:
#   - GitHub 저장소: https://github.com/knhanul/kpicCafeteria.git
#   - 서버 프로젝트 디렉터리: /opt/cafeteria
#   - 서버 백업 디렉터리: /opt/cafeteria-backups
#   - .env, data/, storage/, .venv/, dist/ 는 .gitignore로 추적 제외
#     → pull 해도 서버의 환경설정·데이터·볼륨이 유지됩니다.
#
# ------------------------------------------------------------
# A. 개발 PC: 커밋 후 Push
# ------------------------------------------------------------
#
 cd C:\Pjt\kpicCafeteria

# # 변경 사항 확인
 git status

# # 스테이징 (PowerShell에서는 파일 경로를 직접 지정)
# git add DEPLOY.md backend/app/routers/setup.py backend/app/static/app.js backend/app/templates/app.html backend/app/actual_meal_import.py backend/tests/test_actual_meal_import.py

# # 커밋
git commit -m "식수 정보 XLSX 업로드 기능 추가
#
# - 설정 → 기본 데이터 관리에 '식수 정보 업로드' 탭 추가
# - XLSX 파일 검증·미리보기·DB 반영(Merge/Upsert) 흐름 구현
# - 기존 MealActual/MealService 모델과 ImportJob 테이블 재사용
# - 관리자 권한, Preview 만료, SHA-256 검증, 전체 롤백 적용
# - DEPLOY.md에 Git Push → Pull 배포 방법 추가
#
# Generated with [Devin](https://devin.ai)
#
# Co-Authored-By: Devin <158243242+devin-ai-integration[bot]@users.noreply.github.com>"

# # GitHub 로 Push
git push origin main
#
# # 최종 반영 커밋: 8980a78 (main → main)

# ------------------------------------------------------------
# B. 서버: Pull 후 Docker 재빌드
# ------------------------------------------------------------
#
# # 서버 접속
 ssh root@8.219.243.65
#
# # 프로젝트 디렉터리 이동
 cd /opt/cafeteria
#
# # 백업
TS=$(date +%Y%m%d_%H%M%S)
cp .env .env.bak.$TS
docker compose exec -T db pg_dump -U cafeteria cafeteria | gzip > /opt/cafeteria-backups/cafeteria_db_$TS.dump.gz
#
# # 최신 소스 가져오기
git pull origin main
#
# # 설정 검증
docker compose config -q
#
# # 이미지 빌드
docker compose build
#
# # 서비스 반영
docker compose up -d --remove-orphans
#
# # 상태 확인
docker compose ps
docker compose logs --tail=100 app
#
# # Health Check
curl -i http://127.0.0.1:8080/health
curl -i https://post.nuni.co.kr/health
#
# ------------------------------------------------------------
# 주의사항
# ------------------------------------------------------------
#   - .env 는 Git에 추적되지 않으므로 서버에서 직접 유지됩니다.
#   - data/, storage/, .venv/, dist/ 도 .gitignore로 제외되어
#     pull 로 덮어쓰지 않습니다.
#   - DB 데이터는 Pull과 무관하게 Docker 볼륨으로 유지됩니다.
#   - 반영 전 반드시 pg_dump 백업을 먼저 실행하세요.
#   - 운영 DB에 Apply 하려면 식수 정보 업로드 탭에서 별도 승인 후 실행하세요.