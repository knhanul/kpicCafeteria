$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
New-Item -ItemType Directory -Force -Path "backup" | Out-Null
$backupPath = "backup/cafeteria_$stamp.sql"
cmd /c "docker compose exec -T db pg_dump -U cafeteria cafeteria > $backupPath"
if ($LASTEXITCODE -ne 0) {
    throw "pg_dump 실패: exit code $LASTEXITCODE"
}
if ((Get-Item $backupPath).Length -le 0) {
    throw "빈 백업 파일이 생성되었습니다: $backupPath"
}
Write-Host "$backupPath 생성"
