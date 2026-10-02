$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
try {
    if (-not (Test-Path -LiteralPath './.venv-backend/Scripts/python.exe')) {
        throw 'Create the isolated backend environment using docs/local-website.md first.'
    }
    # The app binds only to loopback and does not migrate or enable a provider
    # at startup. Settings loads this worktree's ignored .env.backend.
    & './.venv-backend/Scripts/python.exe' -m backend
    if ($LASTEXITCODE -ne 0) { throw 'Local website stopped with an error.' }
} finally { Pop-Location }
