$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$distDir = Join-Path $repoRoot "dist"
$zipPath = Join-Path $distDir "kpicCafeteria-update.zip"
$staging = Join-Path $distDir "staging"

if (Test-Path $distDir) { Remove-Item $distDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $distDir | Out-Null
New-Item -ItemType Directory -Force -Path $staging | Out-Null

$excludeNames = @(".env", ".git", ".venv", "__pycache__", ".pytest_cache", "backup", "dist", "postgres_data", "node_modules")

$sourceItems = Get-ChildItem -Path $repoRoot -Force
foreach ($item in $sourceItems) {
    if ($excludeNames -contains $item.Name) { continue }
    Copy-Item -Path $item.FullName -Destination (Join-Path $staging $item.Name) -Recurse -Force
}

Get-ChildItem -Path $staging -Recurse -Force -Directory |
    Where-Object { $_.Name -in @("__pycache__", ".pytest_cache", ".git", ".venv", "node_modules") } |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Get-ChildItem -Path $staging -Recurse -Force -File |
    Where-Object { $_.Extension -eq ".pyc" -or $_.Name -eq "cafeteria.db" } |
    Remove-Item -Force -ErrorAction SilentlyContinue

Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $zipPath -Force
Remove-Item $staging -Recurse -Force

$size = (Get-Item $zipPath).Length
Write-Host "$zipPath 생성 ($([math]::Round($size/1KB, 1)) KB)"
