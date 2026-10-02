$ErrorActionPreference = 'Stop'
$runtimeFile = Join-Path $PSScriptRoot 'output/worktree-runtime.json'
if (-not (Test-Path -LiteralPath $runtimeFile)) { throw 'Run initialize-worktree.ps1 first.' }
$primary = (Get-Content -LiteralPath $runtimeFile -Raw | ConvertFrom-Json).primary_workspace
$ollama = Join-Path $primary 'data/tools/ollama/ollama.exe'
$reranker = Join-Path $primary 'data/tools/reranker-venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $ollama) -or -not (Test-Path -LiteralPath $reranker)) { throw 'Primary model runtimes missing; follow docs/self-hosted-infrastructure.md to prepare them.' }
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $primary 'run-local-model.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Primary Ollama service failed to start.' }
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $primary 'run-reranker.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Primary reranker service failed to start.' }
Write-Output 'Existing primary model services are available on loopback ports 11435 and 11436. Reranker weights load on first scoring request. No model weights were copied or trained.'
