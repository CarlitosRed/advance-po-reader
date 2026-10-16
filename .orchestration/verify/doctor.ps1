# Read-only doctor for the Advance PO Reader free demo. Prints PASS/FAIL per check; exit 0 only if all pass.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File .orchestration\verify\doctor.ps1 -Desk <worktree> -Port <n> -PostgresBin <bin> [-ExpectSha <sha>]
# Check 5 (driving capability) is a browser no-op done by the agent: open http://127.0.0.1:<port>/poc-demo and read "Upload a purchase order".
param([Parameter(Mandatory)][string]$Desk, [Parameter(Mandatory)][int]$Port, [Parameter(Mandatory)][string]$PostgresBin, [string]$ExpectSha)
$fail = 0
function Report($n, $ok, $what) { if ($ok) { "PASS $n $what" } else { "FAIL $n $what"; $script:fail++ } }
$runtime = Get-Content -Raw (Join-Path $Desk 'output\poc-demo\runtime.json') | ConvertFrom-Json
$owner = Get-Content -Raw (Join-Path $Desk 'data\poc-demo\runtime\owner.json') | ConvertFrom-Json
# 1. processes alive: the uvicorn listener on the port and the postmaster recorded in the desk cluster
$listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
$pmPid = [int](Get-Content (Join-Path $Desk 'data\poc-demo\runtime\cluster\postmaster.pid') -TotalCount 1)
Report 1 ($listener -and (Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue) -and (Get-Process -Id $pmPid -ErrorAction SilentlyContinue)) "app pid $($listener.OwningProcess) on $Port, postmaster pid $pmPid"
# 2. readiness: the start page answers 200
try { $code = (Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/poc-demo" -TimeoutSec 10).StatusCode } catch { $code = 0 }
Report 2 ($code -eq 200) "GET /poc-demo -> $code"
# 3. commit: the app exposes no version; weaker fallback = runtime.json desk is this checkout and its HEAD equals the launch sha
$head = (git -C $Desk rev-parse HEAD).Trim()
Report 3 (($runtime.desk -eq (Resolve-Path $Desk).Path) -and (-not $ExpectSha -or $head -eq $ExpectSha) -and $runtime.port -eq $Port) "desk=$($runtime.desk) head=$head expected=$ExpectSha (fallback: no version endpoint)"
# 4. data marker: fictional namespace, synthetic flag, 153 products, offline flags
$q = "select (select count(*) from catalog_namespaces where source_catalog_id='poc-demo-fictional-v1' and synthetic) || '/' || (select count(*) from catalog_namespaces) || '/' || (select count(*) from catalog_products)"
$marker = (& (Join-Path $PostgresBin 'psql.exe') -h 127.0.0.1 -p $owner.port -U poc_demo -d $owner.database -At -c $q).Trim()
Report 4 ($marker -eq '1/1/153' -and $runtime.live_processing_enabled -eq $false -and $runtime.provider_key_present -eq $false) "namespaces fictional/total/products=$marker live=$($runtime.live_processing_enabled) key=$($runtime.provider_key_present)"
"CHECK 5 is the browser no-op (agent): open the start page and read the heading 'Upload a purchase order'."
if ($fail) { "DOCTOR FAIL ($fail)"; exit 1 } else { "DOCTOR PASS (checks 1-4)"; exit 0 }
