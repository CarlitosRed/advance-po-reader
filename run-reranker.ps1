[CmdletBinding()]
param([ValidateRange(1024,65535)][int]$Port = 11436)

$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$taskPython = Join-Path $taskRoot 'data\tools\reranker-venv\Scripts\python.exe'
$taskScript = Join-Path $taskRoot 'reranker_server.py'
$taskLogs = Join-Path $taskRoot 'data\tools\reranker-venv'
$taskPidPath = Join-Path $taskLogs "server-$Port.pid"
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run setup-reranker.ps1 first.' }
$taskProcess = $null
if (Test-Path -LiteralPath $taskPidPath) {
    $taskSavedId = 0
    if ([int]::TryParse((Get-Content -LiteralPath $taskPidPath -Raw).Trim(),[ref]$taskSavedId)) {
        $taskCandidate = Get-Process -Id $taskSavedId -ErrorAction SilentlyContinue
        if ($taskCandidate -and $taskCandidate.Path -eq $taskPython) { $taskProcess = $taskCandidate }
    }
}
if (-not $taskProcess) {
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { throw "Port $Port is already in use." }
    $taskArguments = '"{0}" --port {1} --cpu-threads 4' -f $taskScript,$Port
    $taskProcess = Start-Process -FilePath $taskPython -ArgumentList $taskArguments -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskLogs "server-$Port.stdout.log") -RedirectStandardError (Join-Path $taskLogs "server-$Port.stderr.log") -PassThru
    [IO.File]::WriteAllText($taskPidPath,[string]$taskProcess.Id)
}
for ($taskAttempt=0; $taskAttempt -lt 30; $taskAttempt++) {
    try {
        $taskHealth = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
        [pscustomobject]@{Endpoint="http://127.0.0.1:$Port";ProcessId=$taskProcess.Id;Model=$taskHealth.model;State=$taskHealth.status;Ready=$taskHealth.ready}
        exit 0
    } catch {
        $taskProcess.Refresh()
        if ($taskProcess.HasExited) { throw 'Reranker exited; inspect data/tools/reranker-venv server logs.' }
        Start-Sleep -Milliseconds 500
    }
}
throw 'Reranker health endpoint did not become reachable.'
