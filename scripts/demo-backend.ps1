param(
    [string]$BaseUrl = "http://127.0.0.1:8012",
    [string]$Output = "output/backend-demo"
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendPython = Join-Path $projectRoot ".venv-backend/Scripts/python.exe"
if (-not (Test-Path -LiteralPath $backendPython)) {
    throw "Run setup-backend.ps1 first to create the local backend environment."
}
Push-Location $projectRoot
try {
    & $backendPython -m backend.demo --base-url $BaseUrl --output $Output
    if ($LASTEXITCODE -ne 0) { throw "Synthetic local backend demo failed." }
}
finally { Pop-Location }
