param([switch]$LiveDemo)
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
try {
    if (-not (Test-Path -LiteralPath './.venv-backend/Scripts/python.exe')) {
        throw 'Create the isolated backend environment using docs/local-website.md first.'
    }
    # Explicit live activation is separate from merely storing a key. Neither
    # launch mode sends a document; source authorization is still required.
    if ($LiveDemo) {
        $readerPreviousLiveSwitch = $env:PO_BACKEND_LIVE_PROCESSING_ENABLED
        & './.venv-backend/Scripts/python.exe' -c 'from backend.config import Settings; s=Settings(); raise SystemExit(0 if s.openai_api_key and s.openai_api_key.get_secret_value().strip() else 1)'
        if ($LASTEXITCODE -ne 0) { throw 'Configure the server OPENAI_API_KEY privately before using -LiveDemo.' }
        $env:PO_BACKEND_LIVE_PROCESSING_ENABLED = 'true'
    }
    # Settings loads this worktree's ignored .env.backend. No migration at startup.
    # serve_backend.py = the plain backend server plus, when live is on, the private-token check and the spend cap.
    & './.venv-backend/Scripts/python.exe' 'scripts/serve_backend.py'
    if ($LASTEXITCODE -ne 0) { throw 'Local website stopped with an error.' }
} finally {
    if ($LiveDemo) {
        if ($null -eq $readerPreviousLiveSwitch) { Remove-Item Env:PO_BACKEND_LIVE_PROCESSING_ENABLED -ErrorAction SilentlyContinue }
        else { $env:PO_BACKEND_LIVE_PROCESSING_ENABLED = $readerPreviousLiveSwitch }
    }
    Pop-Location
}
