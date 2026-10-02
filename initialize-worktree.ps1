param([Parameter(Mandatory=$true)][string]$PrimaryWorkspace)
$ErrorActionPreference = 'Stop'
$primary = (Resolve-Path -LiteralPath $PrimaryWorkspace).Path
$destinationRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
if ($primary -eq $destinationRoot) { throw 'Choose the original evidence workspace as the source, and run this from a separate worktree.' }
$python = Join-Path $primary '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Primary Python environment missing; use setup.ps1 in this checkout instead.' }
$inputs = @('data/originals', 'data/catalog.sqlite3', 'data/catalog-seed.json', 'data/source_manifest.json', 'data/private-tests')
foreach ($relative in $inputs) {
    $source = Join-Path $primary $relative
    if (-not (Test-Path -LiteralPath $source)) { continue }
    $files = if ((Get-Item -LiteralPath $source).PSIsContainer) { Get-ChildItem -LiteralPath $source -File -Recurse } else { Get-Item -LiteralPath $source }
    foreach ($file in $files) {
        $suffix = $file.FullName.Substring($primary.Length).TrimStart('\','/')
        $destination = Join-Path $destinationRoot $suffix
        if (Test-Path -LiteralPath $destination) {
            if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash) { throw "Existing local fixture differs: $suffix" }
            continue
        }
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $destination
    }
}
New-Item -ItemType Directory -Force -Path (Join-Path $destinationRoot 'output') | Out-Null
@{python_executable=$python; primary_workspace=$primary; private_inputs_copied=$inputs; model_weights_copied=$false; outputs_shared=$false} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $destinationRoot 'output/worktree-runtime.json') -Encoding UTF8
Write-Output 'Worktree private fixtures initialized. Model weights and outputs are not copied. Run run-worktree-checks.ps1 for verification.'
