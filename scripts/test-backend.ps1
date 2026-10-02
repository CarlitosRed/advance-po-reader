$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
try {
    & ./.venv-backend/Scripts/python.exe -m backend.database --create-test-databases
    if ($LASTEXITCODE -ne 0) { throw 'Test database setup failed.' }
    # Local synthetic credentials; each suite owns a different mutable database.
    $taskTestPrefix = 'postgresql+psycopg://gate_a:gate_a_local@127.0.0.1:55433/'
    $env:PO_BACKEND_API_TEST_DATABASE_URL = $taskTestPrefix + 'gate_a_test_backend_website_api'
    $env:PO_BACKEND_TEST_DATABASE_URL = $taskTestPrefix + 'gate_a_test_backend_website_catalog'
    $env:PO_BACKEND_CONTRACT_TEST_DATABASE_URL = $taskTestPrefix + 'gate_a_test_backend_website_contract'
    & ./.venv-backend/Scripts/python.exe -m pytest -c pytest.backend.ini -q
    if ($LASTEXITCODE -ne 0) { throw 'Backend verification failed.' }
    $env:GATE_A_TEST_DATABASE_URL = $taskTestPrefix + 'gate_a_test_backend_website_gate_a'
    & ./.venv-backend/Scripts/python.exe -m pytest -c pytest.gate-a.ini -q
    if ($LASTEXITCODE -ne 0) { throw 'Preserved Gate A verification failed.' }
} finally { Pop-Location }
