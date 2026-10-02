[CmdletBinding()]
param(
    [string]$SourceZip = (Join-Path $PSScriptRoot 'data\corpora\full-data-set.zip'),
    [string]$LabelFile = (Join-Path $PSScriptRoot 'output\vision-gold-representative.json')
)

$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $SourceZip -PathType Leaf)) { throw 'Provide the source PDF ZIP using -SourceZip.' }
if (-not (Test-Path -LiteralPath $LabelFile -PathType Leaf)) { throw 'Provide independently reviewed labels using -LabelFile.' }
$taskRunName = 'framework-evaluation-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$taskOutput = Join-Path $PSScriptRoot ('output\' + $taskRunName)
Push-Location $PSScriptRoot
try {
    & $taskPython model_stack.py --output (Join-Path $taskOutput 'readiness.json')
    if ($LASTEXITCODE -ne 0) { throw 'Readiness report failed.' }
    foreach ($taskModel in @('qwen3-vl:4b-instruct', 'qwen3-vl:8b-instruct')) {
        $taskModelName = $taskModel.Replace(':','-')
        $taskModelOutput = Join-Path $taskOutput $taskModelName
        & $taskPython benchmark_vision.py --zip $SourceZip --mode vision --model $taskModel --pipeline cascade --extraction-only --only-labeled --label-file $LabelFile --timeout 600 --output-dir $taskModelOutput
        $taskEvaluationExit = $LASTEXITCODE
        $taskReport = Join-Path $taskModelOutput 'vision-benchmark-vision.json'
        if (Test-Path -LiteralPath $taskReport) {
            & $taskPython collect_review.py collect --result $taskReport --run-id ($taskRunName + '-' + $taskModelName)
            if ($LASTEXITCODE -ne 0) { throw 'Review collection failed; completed report remains saved.' }
        }
        if ($taskEvaluationExit -ne 0) { Write-Warning "Some $taskModel pages failed; inspect the saved report. Failed cases remain in scores." }
    }
    Write-Output "Pretrained inference/evaluation finished: $taskOutput"
    Write-Output 'Review records remain pending. No model training or catalog/cart writes were performed.'
} finally {
    Pop-Location
}
