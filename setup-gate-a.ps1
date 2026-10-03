param([Parameter(Mandatory=$true)][string]$PythonPath)
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    & $PythonPath -c "import sys; assert sys.version_info[:2] == (3, 12), 'Gate A requires Python 3.12'"
    if ($LASTEXITCODE -ne 0) { throw 'Use a Python 3.12 interpreter.' }
    if (-not (Test-Path -LiteralPath '.venv-gate-a/Scripts/python.exe')) {
        & $PythonPath -m venv .venv-gate-a
        if ($LASTEXITCODE -ne 0) { throw 'Gate A environment creation failed.' }
    }
    & ./.venv-gate-a/Scripts/python.exe -m pip install -r requirements.gate-a.lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Gate A dependency installation failed.' }
    & ./.venv-gate-a/Scripts/python.exe -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Gate A dependency check failed.' }
} finally { Pop-Location }
