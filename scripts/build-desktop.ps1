param(
    [string]$Version = "",
    [string]$BuildDate = ""
)

$ErrorActionPreference = "Stop"

while ($true) {
    if (-not $Version) {
        $Version = (Read-Host "실행 파일 버전 (예: 1.2.3, Enter=1.0.0)").Trim()
        if (-not $Version) { $Version = "1.0.0" }
    }
    if ($Version -match '^\d+(\.\d+){0,2}$') { break }
    Write-Host "버전은 숫자와 점(최대 2개)만 입력할 수 있습니다. 예: 1.2.3"
    $Version = ""
}
if (-not $BuildDate) {
    $today = Get-Date -Format "yyyy-MM-dd"
    $BuildDate = (Read-Host "생성일 (Enter=$today)").Trim()
    if (-not $BuildDate) { $BuildDate = $today }
}
$env:KPI_BUILD_VERSION = $Version
$env:KPI_BUILD_DATE = $BuildDate
Write-Host "버전: $Version / 생성일: $BuildDate"

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

$iconIco = Join-Path $repoRoot "desktop-build\KPICCafeteria.ico"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $iconIco) | Out-Null
Add-Type -AssemblyName System.Drawing
$src = [System.Drawing.Image]::FromFile((Join-Path $repoRoot "backend\app\static\assets\ci.png"))
$canvas = New-Object System.Drawing.Bitmap 256, 256
$graphics = [System.Drawing.Graphics]::FromImage($canvas)
$graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$graphics.Clear([System.Drawing.Color]::Transparent)
$scale = [Math]::Min(256.0 / $src.Width, 256.0 / $src.Height)
$iconW = [int][Math]::Round($src.Width * $scale)
$iconH = [int][Math]::Round($src.Height * $scale)
$graphics.DrawImage($src, [int]((256 - $iconW) / 2), [int]((256 - $iconH) / 2), $iconW, $iconH)
$pngStream = New-Object System.IO.MemoryStream
$canvas.Save($pngStream, [System.Drawing.Imaging.ImageFormat]::Png)
$iconPng = $pngStream.ToArray()

$icoStream = New-Object System.IO.MemoryStream
$writer = New-Object System.IO.BinaryWriter $icoStream
$writer.Write([uint16]0)
$writer.Write([uint16]1)
$writer.Write([uint16]1)
$writer.Write([byte]0)
$writer.Write([byte]0)
$writer.Write([byte]0)
$writer.Write([byte]0)
$writer.Write([uint16]1)
$writer.Write([uint16]32)
$writer.Write([uint32]$iconPng.Length)
$writer.Write([uint32]22)
$writer.Write($iconPng)
[System.IO.File]::WriteAllBytes($iconIco, $icoStream.ToArray())
$writer.Dispose()
$icoStream.Dispose()
$pngStream.Dispose()
$graphics.Dispose()
$canvas.Dispose()
$src.Dispose()

Push-Location (Join-Path $repoRoot "backend")
try {
    & $python -m PyInstaller `
        --noconfirm `
        --clean `
        --distpath (Join-Path $repoRoot "desktop-dist") `
        --workpath (Join-Path $repoRoot "desktop-build\pyinstaller") `
        "desktop.spec"
    if ($LASTEXITCODE -ne 0) {
        throw "PC 버전 빌드에 실패했습니다."
    }
} finally {
    Pop-Location
}

$staleDir = Join-Path $repoRoot "desktop-dist\KPICCafeteria"
if (Test-Path $staleDir) {
    Remove-Item -Recurse -Force $staleDir
}

$exe = Join-Path $repoRoot "desktop-dist\KPICCafeteria.exe"
if (-not (Test-Path $exe)) {
    throw "PC 버전 실행 파일을 생성하지 못했습니다."
}
Write-Host "$exe 생성"
