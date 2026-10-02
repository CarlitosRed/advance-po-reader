[CmdletBinding()]
param([int]$Port = 11435)

$ErrorActionPreference = 'Stop'
$taskSetupScript = Join-Path $PSScriptRoot 'run-local-model.ps1'
foreach ($taskModel in @('qwen3-vl:8b-instruct', 'qwen3-embedding:0.6b', 'gpt-oss:20b')) {
    Write-Output "Preparing local pretrained model: $taskModel"
    & $taskSetupScript -Port $Port -Model $taskModel -Pull
}
Write-Output 'Model downloads completed. PDF inference and adjudication must be evaluated separately.'
Write-Output 'For the dedicated CPU reranker, run setup-reranker.ps1 and follow docs/self-hosted-infrastructure.md.'
