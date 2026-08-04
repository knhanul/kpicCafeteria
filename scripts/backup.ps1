$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
New-Item -ItemType Directory -Force -Path "backup" | Out-Null
docker compose exec -T db pg_dump -U cafeteria cafeteria | Out-File -Encoding utf8 "backup/cafeteria_$stamp.sql"
Write-Host "backup/cafeteria_$stamp.sql 생성"
