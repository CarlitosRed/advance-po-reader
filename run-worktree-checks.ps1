$ErrorActionPreference = 'Stop'
$localPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
$runtimeFile = Join-Path $PSScriptRoot 'output/worktree-runtime.json'
if (Test-Path -LiteralPath $localPython) { $python = $localPython }
elseif (Test-Path -LiteralPath $runtimeFile) { $python = (Get-Content -LiteralPath $runtimeFile -Raw | ConvertFrom-Json).python_executable }
else { throw 'Use setup.ps1 or initialize-worktree.ps1 before running checks.' }
Push-Location -LiteralPath $PSScriptRoot
try {
    & $python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Unit tests failed.' }
} finally { Pop-Location }
