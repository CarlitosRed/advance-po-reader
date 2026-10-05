param(
    [string]$Python,
    [string]$PostgresBin,
    [string]$CatalogFile,
    [int]$Port = 8020,
    [switch]$FreshDatabase,
    [switch]$PrepareOnly,
    [switch]$Live,
    [switch]$LiveRehearsal
)
$ErrorActionPreference = 'Stop'
$taskIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$taskPrincipal = [Security.Principal.WindowsPrincipal]::new($taskIdentity)
if ($taskPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'PostgreSQL cannot run as administrator. Open a NORMAL PowerShell from the Start menu (PowerShell, NOT Run as administrator), then rerun the documented command.'
}
$taskRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $taskRoot
try {
    $taskPython = Join-Path $taskRoot '.venv-backend/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $taskPython)) {
        if (-not $Python) {
            $taskBundled = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
            if (Test-Path -LiteralPath $taskBundled) { $Python = $taskBundled }
            else { $Python = (Get-Command python -ErrorAction Stop).Source }
        }
        & $Python -m venv .venv-backend
        if ($LASTEXITCODE -ne 0) { throw 'Isolated Python environment creation failed.' }
        & $taskPython -m pip install --disable-pip-version-check -r requirements.backend.lock.txt
        if ($LASTEXITCODE -ne 0) { throw 'Pinned dependency installation failed.' }
    }
    & $taskPython -c 'import fastapi, psycopg, pymupdf, uvicorn'
    if ($LASTEXITCODE -ne 0) { throw 'Install requirements.backend.lock.txt into .venv-backend first.' }
    $taskArguments = @('scripts/poc-demo.py', '--port', "$Port")
    if ($PostgresBin) { $taskArguments += @('--postgres-bin', $PostgresBin) }
    if ($CatalogFile) { $taskArguments += @('--catalog-file', $CatalogFile) }
    if ($FreshDatabase) { $taskArguments += '--fresh-database' }
    if ($PrepareOnly) { $taskArguments += '--prepare-only' }
    if ($Live -and $LiveRehearsal) { throw 'Choose -Live or -LiveRehearsal, not both.' }
    if ($Live) {
        # Explicit, per-process: nothing is written to disk and free mode stays the default.
        $taskArguments += '--live'
        $env:PO_BACKEND_LIVE_PROCESSING_ENABLED = 'true'
        if (-not $env:PO_BACKEND_PROVIDER_TIMEOUT_SECONDS) { $env:PO_BACKEND_PROVIDER_TIMEOUT_SECONDS = '180' }
    }
    if ($LiveRehearsal) { $taskArguments += '--live-rehearsal' }
    & $taskPython @taskArguments
    if ($LASTEXITCODE -ne 0) { throw 'POC stopped with an error; inspect output/poc-demo privately.' }
} finally {
    if ($Live) {
        Remove-Item Env:PO_BACKEND_LIVE_PROCESSING_ENABLED -ErrorAction SilentlyContinue
    }
    Pop-Location
}
