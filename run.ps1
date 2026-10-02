param([string]$InputPath = 'data/originals')
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
& "$PSScriptRoot/.venv/Scripts/python.exe" "$PSScriptRoot/extract.py" $InputPath --render
exit $LASTEXITCODE
