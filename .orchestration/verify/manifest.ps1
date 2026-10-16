# Writes or checks the evidence list in a run folder's manifest.json (size + SHA-256 per file).
# Usage: manifest.ps1 -Run <run folder> -Mode record   (adds "evidence" to manifest.json, keeps other fields)
#        manifest.ps1 -Run <run folder> -Mode verify   (re-hashes; prints SURVIVAL PASS/FAIL; exit 1 on mismatch)
param([Parameter(Mandatory)][string]$Run, [ValidateSet('record','verify')][string]$Mode = 'record')
$path = Join-Path $Run 'manifest.json'
$m = Get-Content -Raw $path | ConvertFrom-Json
if ($Mode -eq 'record') {
    $files = Get-ChildItem $Run -File | Where-Object Name -ne 'manifest.json' | Sort-Object Name | ForEach-Object {
        [ordered]@{ path = $_.Name; size = $_.Length; sha256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower() } }
    $m | Add-Member -Force -NotePropertyName evidence -NotePropertyValue @($files)
    [IO.File]::WriteAllText($path, ($m | ConvertTo-Json -Depth 6), (New-Object Text.UTF8Encoding $false))
    "recorded $(@($files).Count) evidence files"
} else {
    $bad = 0
    foreach ($e in $m.evidence) {
        $f = Join-Path $Run $e.path
        if (-not (Test-Path $f)) { "MISSING $($e.path)"; $bad++; continue }
        $h = (Get-FileHash $f -Algorithm SHA256).Hash.ToLower(); $s = (Get-Item $f).Length
        if ($h -ne $e.sha256 -or $s -ne $e.size) { "CHANGED $($e.path)"; $bad++ } else { "OK $($e.path) $s $h" }
    }
    if ($bad) { "SURVIVAL FAIL ($bad)"; exit 1 } else { "SURVIVAL PASS ($(@($m.evidence).Count) files)" }
}
