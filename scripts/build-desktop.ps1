$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$venvRoot = Join-Path $repoRoot ".desktop-venv"
$python = Join-Path $venvRoot "Scripts\python.exe"

if (-not (Test-Path $python)) {
    python -m venv $venvRoot
    if ($LASTEXITCODE -ne 0) {
        throw "PC 버전 가상환경 생성에 실패했습니다."
    }
}

& $python -m pip install -r (Join-Path $repoRoot "backend\requirements-desktop.txt")
if ($LASTEXITCODE -ne 0) {
    throw "PC 버전 의존성 설치에 실패했습니다."
}

Push-Location (Join-Path $repoRoot "backend")
try {
    & $python -m PyInstaller `
        --noconfirm `
        --clean `
        --distpath (Join-Path $repoRoot "desktop-dist") `
        --workpath (Join-Path $repoRoot "desktop-build") `
        "desktop.spec"
    if ($LASTEXITCODE -ne 0) {
        throw "PC 버전 빌드에 실패했습니다."
    }
} finally {
    Pop-Location
}

$exe = Join-Path $repoRoot "desktop-dist\KPICCafeteria\KPICCafeteria.exe"
if (-not (Test-Path $exe)) {
    throw "PC 버전 실행 파일을 생성하지 못했습니다."
}
Write-Host "$exe 생성"
