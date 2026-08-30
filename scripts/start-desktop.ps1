$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$desktopPython = Join-Path $repoRoot ".desktop-venv\Scripts\python.exe"
$python = if (Test-Path $desktopPython) { $desktopPython } else { "python" }

Push-Location (Join-Path $repoRoot "backend")
try {
    & $python "desktop_launcher.py"
    if ($LASTEXITCODE -ne 0) {
        throw "PC 버전 실행에 실패했습니다."
    }
} finally {
    Pop-Location
}
