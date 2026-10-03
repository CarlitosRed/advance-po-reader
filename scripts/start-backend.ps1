$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
try {
    & ./.venv-backend/Scripts/python.exe -m backend
    if ($LASTEXITCODE -ne 0) { throw 'Local backend exited with an error.' }
} finally { Pop-Location }
