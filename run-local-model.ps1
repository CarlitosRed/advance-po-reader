[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 11435,
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._:/-]*$')]
    [string]$Model = 'qwen3-vl:8b-instruct',
    [switch]$Pull
)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$runtimeRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot 'data\tools\ollama'))
$modelRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot 'data\models\ollama'))
foreach ($targetPath in @($runtimeRoot, $modelRoot)) {
    if (-not $targetPath.StartsWith($projectRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'The local model paths must stay inside this project.'
    }
}
$executable = Join-Path $runtimeRoot 'ollama.exe'
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "Portable Ollama is missing: $executable. Extract the official ollama-windows-amd64.zip into data\tools\ollama first."
}
if ($Model -match '(^|[-:])cloud($|[-:])') {
    throw 'Choose a locally downloaded model tag. Cloud features are disabled for this server.'
}
New-Item -ItemType Directory -Path $modelRoot -Force | Out-Null
$endpoint = "http://127.0.0.1:$Port"
$pidPath = Join-Path $runtimeRoot "server-$Port.pid"
$stdoutPath = Join-Path $runtimeRoot "server-$Port.stdout.log"
$stderrPath = Join-Path $runtimeRoot "server-$Port.stderr.log"
$serverProcess = $null
if (Test-Path -LiteralPath $pidPath) {
    $savedProcessId = 0
    if ([int]::TryParse((Get-Content -LiteralPath $pidPath -Raw).Trim(), [ref]$savedProcessId)) {
        $candidateProcess = Get-Process -Id $savedProcessId -ErrorAction SilentlyContinue
        if ($candidateProcess -and $candidateProcess.Path -eq $executable) {
            $serverProcess = $candidateProcess
        }
    }
}

# Variables apply to this invocation and the child server, never to the user or system.
$environmentSettings = @{
    OLLAMA_HOST = "127.0.0.1:$Port"
    OLLAMA_MODELS = $modelRoot
    OLLAMA_NO_CLOUD = '1'
    OLLAMA_CONTEXT_LENGTH = '8192'
    OLLAMA_NUM_PARALLEL = '1'
    OLLAMA_MAX_LOADED_MODELS = '1'
}
$originalEnvironment = @{}
try {
    foreach ($name in $environmentSettings.Keys) {
        $originalEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, $environmentSettings[$name], 'Process')
    }
    if (-not $serverProcess) {
        $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($listener) {
            throw "Port $Port is already in use. Choose another -Port or stop the application that owns it."
        }
        $serverProcess = Start-Process -FilePath $executable -ArgumentList 'serve' -WorkingDirectory $runtimeRoot -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru
        [IO.File]::WriteAllText($pidPath, [string]$serverProcess.Id)
    }
    $version = $null
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try {
            $version = Invoke-RestMethod -Uri "$endpoint/api/version" -TimeoutSec 2
            break
        }
        catch {
            $serverProcess.Refresh()
            if ($serverProcess.HasExited) {
                throw "Ollama exited. Inspect $stderrPath"
            }
            Start-Sleep -Seconds 1
        }
    }
    if (-not $version) {
        throw "Ollama did not start within 60 seconds. Inspect $stderrPath"
    }
    if ($Pull) {
        & $executable pull $Model
        if ($LASTEXITCODE -ne 0) {
            throw "Could not download $Model. The loopback server is still running."
        }
    }
    $installedModels = Invoke-RestMethod -Uri "$endpoint/api/tags" -TimeoutSec 10
    $selectedModel = @($installedModels.models | Where-Object { $_.name -eq $Model -or $_.model -eq $Model })
    if ($selectedModel.Count -eq 0) {
        Write-Warning "Model $Model is not downloaded. Run .\run-local-model.ps1 -Pull to download it."
    }
    [pscustomobject]@{
        Endpoint = $endpoint
        Version = $version.version
        ProcessId = $serverProcess.Id
        Model = $Model
        ModelDownloaded = ($selectedModel.Count -gt 0)
        ModelDirectory = $modelRoot
        Log = $stderrPath
    }
}
finally {
    foreach ($name in $originalEnvironment.Keys) {
        if ($null -eq $originalEnvironment[$name]) {
            Remove-Item -LiteralPath "Env:\$name" -ErrorAction SilentlyContinue
        }
        else {
            [Environment]::SetEnvironmentVariable($name, $originalEnvironment[$name], 'Process')
        }
    }
}
