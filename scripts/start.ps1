$ErrorActionPreference = "Stop"
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
docker compose up --build -d
docker compose ps
Write-Host "접속: http://localhost"
