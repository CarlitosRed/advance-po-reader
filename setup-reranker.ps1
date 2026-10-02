param(
    [string]$PythonPath = (Join-Path $PSScriptRoot '.venv\Scripts\python.exe')
)
$ErrorActionPreference = 'Stop'
$rerankerVenv = Join-Path $PSScriptRoot 'data\tools\reranker-venv'
$rerankerPython = Join-Path $rerankerVenv 'Scripts\python.exe'
$rerankerRequirements = Join-Path $PSScriptRoot 'requirements.reranker.txt'

if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python executable not found: $PythonPath. Supply -PythonPath with Python 3.10 to 3.13."
}
& $PythonPath -c 'import sys; assert (3, 10) <= sys.version_info[:2] <= (3, 13), "Use Python 3.10 to 3.13"'
if ($LASTEXITCODE -ne 0) { throw 'Unsupported Python version for the pinned reranker runtime' }

if (-not (Test-Path -LiteralPath $rerankerPython -PathType Leaf)) {
    & $PythonPath -m venv $rerankerVenv
    if ($LASTEXITCODE -ne 0) { throw 'Reranker virtual environment creation failed' }
}
& $rerankerPython -m pip install 'torch==2.11.0+cpu' --index-url 'https://download.pytorch.org/whl/cpu'
if ($LASTEXITCODE -ne 0) { throw 'CPU PyTorch installation failed' }
& $rerankerPython -m pip install -r $rerankerRequirements
if ($LASTEXITCODE -ne 0) { throw 'Reranker dependency installation failed' }
& $rerankerPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Reranker dependency compatibility check failed' }
& $rerankerPython -c 'import torch; from sentence_transformers import CrossEncoder; assert torch.version.cuda is None, "Expected CPU-only torch"; print("CPU reranker dependencies import successfully; no model loaded")'
if ($LASTEXITCODE -ne 0) { throw 'CPU reranker import check failed' }

Write-Output 'Dependencies prepared. Model weights load only on the first reranking request.'
Write-Output ('Start: & "{0}" "{1}" --cpu-threads 4' -f $rerankerPython, (Join-Path $PSScriptRoot 'reranker_server.py'))
