# Advance PO Reader

## Run the free demo on Windows

Use **`integration/ui-and-matching` until v1 lands on `main`**. This demo runs
the local review screens with fictional orders, a bundled fictional catalog,
and fixed extraction answers. It does not read new orders with AI or need an
API key. The launcher creates its own local database and temporary local token.

| Prerequisite | How to get it |
| --- | --- |
| Git | Install [Git for Windows](https://git-scm.com/downloads/win) to clone or change branches. |
| Python 3.12, 64-bit | Get the [Python 3.12 Windows installer](https://www.python.org/downloads/release/python-31210/); enable **Add python.exe to PATH**. Check `python --version` reports `3.12.x`. |
| PostgreSQL 17 binaries | Get the Windows installer or binary ZIP from [PostgreSQL's Windows downloads](https://www.postgresql.org/download/windows/). Find the `bin` folder containing `initdb.exe` and `pg_ctl.exe`; add it to PATH or pass `-PostgresBin 'YOUR_POSTGRES_BIN_FOLDER'` to the launcher. An existing database service is not needed. |
| Browser | Open the page in [Microsoft Edge](https://www.microsoft.com/edge) or another browser. |
| PowerShell and ports | Open Windows PowerShell normally, **not as administrator**. Keep local port `8020` free; use `-Port 8021` if it is occupied. The demo selects a separate free local PostgreSQL port. |
| Node.js | Not required to start or use this demo. The optional browser verification script uses [Node.js](https://nodejs.org/en/download) and Playwright. |

From a fresh clone:

```powershell
git clone --branch integration/ui-and-matching --single-branch https://github.com/CarlitosRed/advance-po-reader.git
Set-Location -LiteralPath .\advance-po-reader
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-poc-demo.ps1
```

For an existing clone, run `git fetch origin`, `git switch integration/ui-and-matching`,
and `git pull --ff-only origin integration/ui-and-matching` before the same start command.
If Python is not found, add `-Python 'YOUR_PYTHON_3_12_EXE'`; if PostgreSQL is not
found, add `-PostgresBin 'YOUR_POSTGRES_BIN_FOLDER'`. The first start installs the
pinned Python dependencies and needs access to the package index.

Wait for **Free POC ready**, open [http://127.0.0.1:8020/poc-demo](http://127.0.0.1:8020/poc-demo)
(use your chosen port), and choose **Try a sample order**. Stop with **Ctrl+C**.
No `data\` folder is needed beforehand: private runtime files are created locally.
Files under `data\`, including the old CLI's `catalog-seed.json`, are private and
are never in Git; the demo uses the fictional files under `fixtures/poc-demo/`.
The separate live OpenAI mode needs your own OpenAI key
(see [Run the live demo with your own OpenAI key](#run-the-live-demo-with-your-own-openai-key)).
Never request or share keys in chat, Git, email or any shared file, and never
copy anyone's credentials to another machine. The only place a key belongs is the
private, Git-ignored `.env.backend` file described in the live section. See the [demo runbook](docs/poc-demo-runbook.md)
for the free workflow and its limits.

Local agent integration is implemented: 11 scoped STDIO MCP tools connect to
the website, with human source authorization and product approval in the UI.
The website follows agent-started runs and shares the saved review summary.
Read [the agent/demo activation guide](docs/local-agent-demo.md). The backend
API key was deferred at that checkpoint. Later records ([API activation](docs/api-activation-verification.md),
[live demo](docs/live-demo-continuation.md)) show the server key configured, native `po_reader` calls working,
and one human-authorized PDF processed once with OpenAI; extraction accuracy is not measured.

The local website (built 2026-10-02) is implemented in `web/local-reader/`, served by the FastAPI backend, with saved uploads/runs, source previews and evidence-preserving review/audit. It can work with private catalog namespaces and a private original-PDF library when you supply them on your own PC; those are never in Git, and a fresh clone has none. Read [the website runbook](docs/local-website.md) and [verification record](docs/website-verification.md). It runs locally without an API key. Live extraction runs only when the server key is set and `live_processing_enabled` is on (`backend/config.py:26`), for a source a person has authorized.

Historical desk record, 2026-10-02 (not the state of your clone): the original desk's test workspace had three manually selected catalogs (WernerCo, United Kingdom, Australia) and the original 33-PDF email archive. Product IDs remain separate across catalogs. No country is inferred for WernerCo. That desk used port 8014, database gate_a_backend_website and branch codex/local-website-catalogs; Gate A on 8010 and backend preparation on 8012 were preserved checkpoints. A fresh clone that runs the documented launcher gets the fictional catalog, its own generated demo database and port 8020 (or the port you choose), and no private catalogs or original PDFs.

Read [PROJECT_GOAL.md](PROJECT_GOAL.md), [local logic rules](docs/local-logic-rules-2026-10-02.md), and [agent handoff](docs/agent-handoff.md) before continuing. The extraction payload is version 1.2 (`backend/contracts.py:20`; legacy 1.1 is still accepted, `backend/contracts.py:21`; the OpenAI adapter emits 1.2, `backend/providers.py:187`); source observations, parses, catalog suggestions and human decisions remain separate. Every product approval is explicit. The reviewed-product summary has no cart/order writes. Training, deployment, Apple, AWS and cart or order writes are not part of this phase.

## Run the live demo with your own OpenAI key

Live mode reads a real order with an OpenAI model and costs real money. As a
rough estimate it is a few cents per document; the real cost depends on the model
and the document, and nobody has measured it here. Free mode above stays the
default. Work through these steps in order from the repo root, in a normal (not
administrator) PowerShell, and keep that one PowerShell window open from step 3
to step 6 (the settings you type with `$env:` last only as long as the window).
The key is only ever put into one ignored file on your own PC.

Checked against the code at commit `a28f866` (the version-1 landing branch,
`claude/landing-v1`): its launchers refuse the shared default token and apply the
spend limit below. On an older commit the limits behave differently.

**1. Create the key file.** The file is `.env.backend` in the repo root (next to
`README.md`). Git ignores it (`.gitignore` line 9, `.env.*`); check with
`git check-ignore -v .env.backend`. It holds two lines:

```text
OPENAI_API_KEY=your OpenAI key
PO_BACKEND_LOCAL_API_TOKEN=a private password of 16 or more characters
```

The token is a password for the local server only. It must be at least 16
characters and must not be the shared default; a shorter one makes the launcher
stop with "The server settings could not be loaded".

The safer way is to let PowerShell ask for the key with a hidden prompt: your
screen shows only asterisks, the key never appears in the command, and the
command is not saved in your history. It also makes the token for you. Copy the
key from the OpenAI page, run the lines below, paste it at the prompt (right-click
pastes in a console window) and press Enter:

```powershell
$secure = Read-Host 'Paste your OpenAI key, then press Enter' -AsSecureString
$key = [System.Net.NetworkCredential]::new('', $secure).Password
$token = [guid]::NewGuid().ToString('N')
Set-Content -LiteralPath .env.backend -Encoding ascii -Value "OPENAI_API_KEY=$key", "PO_BACKEND_LOCAL_API_TOKEN=$token"
$key = $null; $secure = $null
Set-Clipboard -Value ' '
```

This replaces any existing `.env.backend`, so if you already keep other settings
there, edit the file instead. The last line empties the clipboard. To check the
file without showing the values: `(Get-Content .env.backend) -replace '=.*','=(hidden)'`.

The other way is `notepad .env.backend` (answer Yes to create the file, paste the
two lines, replace the descriptions with your values, save and close). Notepad
shows the key in plain text. Do this only when nobody can see your screen and
nothing is sharing or recording it, and close the window right after saving.
Either way, check in Explorer that the name is exactly `.env.backend` and not
`.env.backend.txt`, and never use `echo` or any command that contains the key.

**2. Protect the key.** Never share it in chat, email, Git or screenshots, and do
not copy someone else's key. Create a separate OpenAI project with its own key and
set a monthly spend limit on that project. Turn on **Enforce a hard limit** there:
according to OpenAI's [spend-limit guide](https://developers.openai.com/api/docs/guides/spend-limits),
alerts alone do not stop requests, and the limit can be exceeded slightly because
enforcement is not instant. Revoke the key when you are done.

**3. Rehearse for free.** This shows the live screens against a fake OpenAI. It
needs no key and sends nothing to OpenAI (the first start of the launcher does
install packages, so it needs the internet once):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-poc-demo.ps1 -LiveRehearsal -Port 8021
```

Wait for `Live rehearsal (fake transport, no key, no network) ready`, then open
`http://127.0.0.1:8021/poc-demo`. Stop with Ctrl+C. Files you upload during the
rehearsal are counted by the live run limit in step 5, because the demo database
cannot tell them from real runs. If you uploaded any, add `-FreshDatabase` in
step 5.

**4. Probe once (a few cents as a rough estimate; needs the key).** This sends one fictional
one-page PDF, never a real order. It uses the `.venv-backend` folder that step 3
created, so run step 3 first:

```powershell
.\.venv-backend\Scripts\python.exe scripts\poc-probe-live.py --confirm
```

Without `--confirm` it refuses and sends nothing. It prints `model`,
`answered_by`, `input_sent`, `result` (`succeeded` or a failure), `failure` (the
failure code, if any), `latency_ms`, `tokens`, `estimated_cost_usd` and
`model_accepted_this_input`. The command exits with 0 only when `result` is
`succeeded`. Read `failure` first: `model_accepted_this_input` is a hint worked
out from that code, not a diagnosis.

- `yes`: the request ended in `succeeded`, or in a reply that could not be used
  (`invalid_output`, `incomplete`, `refused`). A reply came back; it does not prove
  the reading is good. A broken (non-JSON) reply to a rejected request also shows
  `yes`.
- `probably_no`: the failure was HTTP 400, 404 or 422. The PDF may be the cause,
  but a wrong model name (usually 404) or a bad request setting gives the same
  value. Fix the model (`PO_BACKEND_EXTRACTION_MODEL`, default `gpt-6-luna`) if
  that is the problem. Only if the failure points at the PDF, rerun with
  `--images` (another probe, another few cents) and, if that works, set
  `$env:PO_POC_PDF_AS_IMAGES = '1'` before step 5 (one-page PDFs only).
- `unknown`: any other failure, such as a rejected key (401), a rate or quota
  limit (429), a server error or a timeout. After a timeout or server error the
  result is unknown and OpenAI may already have charged for it: check your OpenAI
  usage before you retry.

`estimated_cost_usd` is filled in only after you set `PO_POC_INPUT_USD_PER_MTOK`
and `PO_POC_OUTPUT_USD_PER_MTOK` (dollars per million tokens, your model's
current prices) in PowerShell before the probe.

**5. Go live.** Optional first: set a limit (see "Spend limits" below).

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-poc-demo.ps1 -Live -Port 8021
```

Add `-CatalogFile C:\path\to\your-catalog.json -FreshDatabase` to use your own
catalog (same shape as `fixtures/poc-demo/catalog.json`; keep it outside the
repo). Live processing is switched on for that launch only; nothing is written to
disk. Wait for `Live POC ready`, then open the page and upload a PDF or photo. The
page asks "This sends this document to OpenAI. Cost is usually a few cents. Send
it?" That is a general note, not a price for this file: the page does not show the
cost of the document before it is sent. Only **Send** submits it. A line on the
page shows the limit status: a count of runs used, and, if you set both prices,
the estimated spend so far (what earlier runs recorded, not this document).

**Sending the same file again.** If this exact file already has a finished
reading (completed or partial) in the same demo database, choosing it again opens
that reading and sends nothing. In every other case it is sent again and can cost
again: when the earlier try failed, was cancelled, was interrupted or timed out
(the result is then unknown and may already have been charged, so check your
OpenAI usage first), and also when you start with `-FreshDatabase`, which uses a
new database that does not know the earlier readings. Only an identical file
counts; a rescanned or re-saved copy is a different file.

**Spend limits.** Two limits can apply, and a new upload is refused when either
one is reached. Set them in the PowerShell window before you start step 5.

- Run limit (always on): `PO_POC_MAX_LIVE_RUNS`, default 5. It counts every live
  attempt that reached the server, including failed ones and rehearsal uploads,
  not free-mode samples. Example for 3 runs: `$env:PO_POC_MAX_LIVE_RUNS = '3'`
- Dollar limit (only when both prices are set): the example numbers below are
  made up, use your model's current prices. `PO_POC_SPEND_CAP_USD` defaults to 3
  and does nothing unless both prices are set. The run limit still applies as well
  (5 unless you raise it with `PO_POC_MAX_LIVE_RUNS`).

```powershell
$env:PO_POC_INPUT_USD_PER_MTOK = '2'
$env:PO_POC_OUTPUT_USD_PER_MTOK = '8'
$env:PO_POC_SPEND_CAP_USD = '2'
```

Limits to know about: the dollar check looks at what earlier attempts recorded
and does not reserve the price of the document you are about to send. At $1.99 of
a $2.00 limit the next document is still allowed and may end above $2.00, so the
dollar limit stops the next send, it is not a maximum for the session. An attempt
whose usage was not recorded (a timeout or server error) is counted at a fixed
high estimate (100,000 input and 16,000 output tokens at your prices), not at
zero; it is still an estimate, so your OpenAI project limit from step 2 is the
real safety net.

At a limit, the page says the live-run limit is reached and nothing is sent, and
the file chooser is switched off. The demo keeps running. To continue, press
Ctrl+C, raise the limit that was reached (the status line shows which: `N of M
live runs used` is the run limit, `Estimated spend $X of $Y` is the dollar limit;
raise both if both are at their limit), set it again in the same window, and
start step 5 again. Raising only the other limit changes nothing. `-FreshDatabase`
starts the count at zero.

**6. Stop.** Press Ctrl+C in the terminal. Live data stays in the ignored `data/`
folder.

**Windows details.** If `python` is not on PATH, add `-Python 'C:\path\to\python.exe'`
(`py -3.12 -c "import sys;print(sys.executable)"` prints it). If PostgreSQL is not
on PATH, add `-PostgresBin 'C:\path\to\postgres\bin'`. Use port 8020, or
`-Port 8021` if 8020 is taken. Choose `-Live` or `-LiveRehearsal`, not both.

**If it refuses.** Where you see it decides what happened.

When you start the launcher (`start-poc-demo.ps1`), it stops before anything
starts and nothing is sent. The launcher then adds the line `POC stopped with an
error; inspect output/poc-demo privately.`; the line before it is the reason.

| The message contains | What to do |
| --- | --- |
| `Live mode needs a private local API token` | Add `PO_BACKEND_LOCAL_API_TOKEN` (16 or more characters, your own) to `.env.backend`. |
| `Live mode needs your OpenAI key` | Add `OPENAI_API_KEY` to `.env.backend` yourself. |
| `The server settings could not be loaded` | Look for a typo in `.env.backend`, or a token shorter than 16 characters; values are never printed. |
| `Choose -Live or -LiveRehearsal, not both.` | Use one of them. |

When you run the probe (`poc-probe-live.py`) it prints its own message and exits
with 2, without the `POC stopped` line; nothing is sent.

| The message contains | What to do |
| --- | --- |
| `Refused: this sends one small fictional page` | Rerun the probe with `--confirm`. |
| `Live mode needs your OpenAI key` or `The server settings could not be loaded` | As in the table above (the probe does not need the token). |

While the demo is running, the limit shows in the browser and the server keeps
running:

| What the page says | What to do |
| --- | --- |
| `The live-run limit for this demo is reached, so nothing was sent` (server error `poc_spend_cap_reached`) | See "Spend limits": raise the limit that was reached and restart. |
| `OpenAI did not accept the key` | Check `OPENAI_API_KEY` in `.env.backend`, then restart. |
| `The connection to OpenAI was interrupted, so the result is unknown` | The attempt may have been charged and counts against the limits. Check your OpenAI usage before sending that file again. |

Details and limits: [demo runbook](docs/poc-demo-runbook.md), "Live mode (T-019)".

## Preserved foundations and comparison components

The original Gate A foundation in gate_a/ established health/configuration, local PostgreSQL/Alembic and the ProductDocument v1 envelope. Its [guide](docs/gate-a.md) records that checkpoint. Backend preparation in backend/ implemented validated uploads, immutable source/run/provider history, bounded candidates and review/audit; [its runbook](docs/local-backend.md) and [historical verification](docs/backend-verification.md) describe the earlier branch. The retained legacy reader is the native-text CLI (`reader.py`); the self-hosted model reader was removed, and its reports are archived under `docs/archive/`. Those measurements do not evaluate the OpenAI provider.

The earlier prototype's local-model implementation and training-data tooling have been removed. The retained CLI extraction path uses the native PDF text engine; it is a prototype, separate from the FastAPI/ProductDocument workflow in `backend/`, and makes no provider call. Historical measurements and operating guides are in [docs/archive](docs/archive/README.md). Original research sources remain in `docs/research/` as evidence and do not authorize provider transfers, API spending, training, or deployment.

## Run local Gate A

The local foundation in `gate_a/` implements health/configuration routes, a tenant-only PostgreSQL/Alembic baseline, and a versioned ProductDocument v1 envelope with observation/state validators. It starts without provider credentials or a running database. The full extraction payload remains outside Gate A.

```powershell
powershell -ExecutionPolicy Bypass -File .\setup-gate-a.ps1 -PythonPath 'PATH_TO_PYTHON_3_12.exe'
& .\.venv-gate-a\Scripts\python.exe -m gate_a
```

Run synthetic checks in a second terminal:

```powershell
& .\.venv-gate-a\Scripts\python.exe -m pytest -c pytest.gate-a.ini
```

The API defaults to `127.0.0.1:8000`. PostgreSQL is optional for startup/liveness and required for readiness. Apply migrations explicitly with `python -m alembic upgrade head` in the Gate A environment. See [Gate A setup and verification](docs/gate-a.md) for configuration, health routes, isolated database tests, and verification limits.

Gate A stops at this foundation. Uploads, extraction, catalog matching and human review were built after Gate A in `backend/`. Gate A itself makes no provider request and implements no cart action.

Local Gate A has been implemented and verified within its bounded scope. Implemented since: shared payload, catalog, upload, OpenAI extraction adapter (off unless enabled), review and audit, the web workflow and the free demo. Intended, not built or not verified: accuracy on real documents, an independent evaluation set, automatic acceptance, Apple, AWS and cart writes (see Current scope in `PROJECT_GOAL.md`). Production use still depends on an authorized authoritative catalog, a defined cart/import contract, independently reviewed evaluation data, and privacy approval for any external processing. The later phone-first product includes a web workflow; the retained CLI is a native-text prototype.

## Saved context and agent work

Read [the agent handoff](docs/agent-handoff.md) for the published baseline, next priorities, worktree setup and private fixture boundaries. The web demo source is retained under `web/po-reader-mockup/` as regular files with synthetic document assets.

## Native CLI prototype

The legacy CLI analyzes PDFs with its native text engine. Vision-model analysis is unavailable in this CLI; image-only PDF pages need OCR and require manual review.

```powershell
& .\.venv\Scripts\python.exe reader.py analyze 'PURCHASE_ORDER.pdf' --summary
```

The sample catalog is provisional. A match remains subject to source validation and human review. The real catalog, tenant boundary, production UI, and cart contract are not implemented by this CLI.

## Local checks

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Customer documents, API keys, catalogs, review records, and generated outputs must stay out of Git. Gate A uses synthetic fixtures only.
