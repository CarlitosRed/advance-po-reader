param([string]$PythonPath = 'python.exe')
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    & $PythonPath -c "import sys; assert sys.version_info[:2] == (3, 12), 'Use Python 3.12'"
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is required.' }
    if (-not (Test-Path -LiteralPath '.venv-backend/Scripts/python.exe')) {
        & $PythonPath -m venv .venv-backend
        if ($LASTEXITCODE -ne 0) { throw 'Backend environment creation failed.' }
    }
    & ./.venv-backend/Scripts/python.exe -m pip install -r requirements.backend.lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
    & ./.venv-backend/Scripts/python.exe -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Backend dependencies are inconsistent.' }
} finally { Pop-Location }
