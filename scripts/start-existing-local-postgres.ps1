param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$readerRoot = Split-Path -Parent $PSScriptRoot
$readerConfiguration = Join-Path $readerRoot 'data/agent-runtime/local-postgres.json'
if (-not (Test-Path -LiteralPath $readerConfiguration -PathType Leaf)) {
    throw 'Provide the approved existing runtime paths in data/agent-runtime/local-postgres.json. This script does not install or initialize PostgreSQL.'
}
$readerRuntime = Get-Content -LiteralPath $readerConfiguration -Raw | ConvertFrom-Json
$readerCtl = (Resolve-Path -LiteralPath $readerRuntime.pg_ctl).Path
$readerCluster = (Resolve-Path -LiteralPath $readerRuntime.cluster).Path
if ((Split-Path -Leaf $readerCtl) -ne 'pg_ctl.exe' -or
    -not (Test-Path -LiteralPath (Join-Path $readerCluster 'PG_VERSION') -PathType Leaf) -or
    $readerRuntime.port -ne 55433) {
    throw 'Expected an existing PostgreSQL cluster and the approved loopback port 55433.'
}
& $readerCtl status -D $readerCluster
if ($LASTEXITCODE -eq 0) { Write-Output 'Existing PostgreSQL is already running.'; return }
if ($CheckOnly) { throw 'Existing PostgreSQL is stopped.' }
$readerLogDirectory = Join-Path $readerRoot 'output/agent-ready'
New-Item -ItemType Directory -Path $readerLogDirectory -Force | Out-Null
$readerLog = Join-Path $readerLogDirectory 'postgresql-recovery.log'
$readerArguments = @('-D', ('"' + $readerCluster + '"'), '-l', ('"' + $readerLog + '"'),
    '-o', '"-h 127.0.0.1 -p 55433"', '-w', '-t', '30', 'start')
$readerStart = Start-Process -FilePath $readerCtl -ArgumentList $readerArguments -WindowStyle Hidden -PassThru
if (-not $readerStart.WaitForExit(30000) -or $readerStart.ExitCode -ne 0) {
    throw 'Existing PostgreSQL did not start. Inspect output/agent-ready/postgresql-recovery.log privately.'
}
Write-Output 'Existing PostgreSQL started on 127.0.0.1:55433; preserved databases are retained.'
