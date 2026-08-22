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

### 4.1 서버 준비

- Docker 및 Docker Compose v2 설치
- 방화벽에서 80번 포트 개방 (또는 리버스 프록시 사용)

### 4.2 소스 코드 전달

```bash
# Git에서 클론
git clone <repository-url> /opt/kpicCafeteria
cd /opt/kpicCafeteria

# 또는 기존 zip 파일을 서버로 전송 후 압축 해제
unzip cafeteria_latest.zip -d /opt/kpicCafeteria
cd /opt/kpicCafeteria
```

### 4.3 환경 설정

```bash
cp .env.example .env
vi .env
```

운영 환경에 맞게 다음 항목을 변경합니다:

```ini
APP_SECRET=<랜덤 문자열 32자 이상>
ADMIN_PASSWORD=<강력한 비밀번호>
PUBLIC_BASE_URL=http://<서버-IP-또는-도메인>
```

### 4.4 빌드 및 시작

```bash
docker compose up --build -d
docker compose ps
```

### 4.5 접속 확인

```
http://<서버-IP-또는-도메인>
```

### 4.6 HTTPS 적성 (선택)

nginx 컨테이너 앞에 리버스 프록시(예: Caddy, Traefik)를 두거나, `nginx/default.conf`에 SSL 인증서를 추가합니다.

**Caddy 예시:**

```caddyfile
cafeteria.example.com {
    reverse_proxy localhost:80
}
```

**nginx 직접 SSL 적용 시:**

1. `nginx/` 폴더에 인증서 파일 추가
2. `nginx/default.conf`에 443 리스너 및 SSL 설정 추가
3. `docker-compose.yml`의 nginx 포트에 `443:443` 추가
4. `docker compose up -d`로 재시작

## 5. 최초 데이터 구축

1. 로그인 (`.env`의 `ADMIN_USERNAME` / `ADMIN_PASSWORD`)
2. 좌측 **기본 데이터 관리** 메뉴 → **기초 데이터 구축** 탭
3. 로컬 XLSX 파일 선택
4. **파일 검증** 실행
5. 최초 구축은 **기존 업무데이터 교체** 선택
6. **기초데이터 생성** 실행

## 6. 데이터 백업 및 복원

### 6.1 백업

```powershell
.\scripts\backup.ps1
```

`backup/cafeteria_YYYYMMDD_HHMMSS.sql` 파일이 생성됩니다.

수동 백업:

```bash
docker compose exec -T db pg_dump -U cafeteria cafeteria > backup.sql
```

### 6.2 복원

```bash
docker compose exec -T db psql -U cafeteria cafeteria < backup.sql
```

### 6.3 데이터 볼륨

PostgreSQL 데이터는 `postgres_data` Docker 볼륨에 저장됩니다. 컨테이너를 삭제해도 데이터는 유지됩니다.

```bash
# 볼륨 확인
docker volume ls | grep postgres_data

# 볼륨까지 완전 삭제 (주의: 모든 데이터 손실)
docker compose down -v
```

## 7. 업데이트 (버전 갱신)

```bash
# 1. 백업
.\scripts\backup.ps1    # Windows
./scripts/backup.ps1   # 또는 수동 pg_dump

# 2. 소스 코드 갱신
git pull origin main
# 또는 새 zip 파일로 덮어쓰기

# 3. 재빌드 및 재시작
docker compose up --build -d

# 4. 확인
docker compose ps
docker compose logs -f app
```

## 8. 테스트 실행

```bash
docker compose exec app pytest -q
```

## 9. 문제 해결

### 컨테이너가 시작되지 않는 경우

```bash
# 로그 확인
docker compose logs app
docker compose logs db
docker compose logs nginx

# 컨테이너 상태 확인
docker compose ps -a
```

### DB 연결 오류

```bash
# DB 헬스체크 확인
docker compose ps db

# DB에 직접 접속
docker compose exec db psql -U cafeteria -d cafeteria
```

### 포트 충돌

80번 포트가 사용 중인 경우 `docker-compose.yml`의 nginx 포트를 변경합니다:

```yaml
nginx:
  ports:
    - "8080:80"   # 8080으로 변경
```

### 앱 재시작 (이미지 재빌드 없이)

```bash
docker compose restart app
```

### 캐시 초기화 후 재빌드

```bash
docker compose build --no-cache app
docker compose up -d
```

## 10. 아키텍처 개요

```
Client (Browser)
    │
    ▼
Nginx (port 80) ── reverse proxy ──▶ FastAPI App (port 8000)
                                        │
                                        ▼
                                    PostgreSQL 16
                                        │
                                        ▼
                                    postgres_data (volume)

App Container:
  - uvicorn (FastAPI)
  - Playwright Chromium (PDF 생성)
  - Noto CJK 폰트 (한글 렌더링)
```

## 11. 주요 파일 구조

```
kpicCafeteria/
├── .env.example          환경 변수 템플릿
├── docker-compose.yml    컨테이너 오케스트레이션
├── nginx/
│   └── default.conf      nginx 리버스 프록시 설정
├── backend/
│   ├── Dockerfile        앱 컨테이너 이미지 정의
│   ├── entrypoint.sh     컨테이너 시작 스크립트
│   ├── requirements.txt  Python 의존성
│   └── app/
│       ├── main.py       FastAPI 앱 진입점
│       ├── routers/      API 라우터
│       ├── models.py     SQLAlchemy 모델
│       ├── templates/    Jinja2 HTML 템플릿
│       └── static/       CSS, JavaScript
├── scripts/
│   ├── start.ps1         Windows 시작 스크립트
│   ├── start.sh          Linux/macOS 시작 스크립트
│   ├── stop.ps1          중지 스크립트
│   ├── logs.ps1          로그 확인 스크립트
│   └── backup.ps1        백업 스크립트
├── storage/              업로드, 템플릿, 생성 파일 (볼륨 마운트)
└── data/                 데이터 내보내기 (볼륨 마운트)
```
