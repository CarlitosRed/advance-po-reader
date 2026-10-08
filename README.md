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
Never request or share keys in chat or files, and never copy anyone's
credentials to another machine. See the [demo runbook](docs/poc-demo-runbook.md)
for the free workflow and its limits.

Local agent integration is implemented: 11 scoped STDIO MCP tools connect to
the website, with human source authorization and product approval in the UI.
The website follows agent-started runs and shares the saved review summary.
Read [the agent/demo activation guide](docs/local-agent-demo.md). The backend
API key was deferred at that checkpoint. Later records ([API activation](docs/api-activation-verification.md),
[live demo](docs/live-demo-continuation.md)) show the server key configured, native `po_reader` calls working,
and one human-authorized PDF processed once with OpenAI; extraction accuracy is not measured.

The active local website is implemented in `web/local-reader/`, served by the FastAPI backend. It connects the three supplied catalog namespaces, private original PDF library, saved uploads/runs, source previews, and evidence-preserving review/audit. Read [the website runbook](docs/local-website.md) and [verification record](docs/website-verification.md). It runs locally without an API key. Live extraction runs only when the server key is set and `live_processing_enabled` is on (`backend/config.py:26`), for a source a person has authorized.

The user selected one local test workspace with three manually selected catalogs (WernerCo, United Kingdom, Australia), and the original 33-PDF email archive. Product IDs remain separate across catalogs. No country is inferred for WernerCo. This worktree owns port 8014, database gate_a_backend_website, and its private data/output directories. Source changes are on codex/local-website-catalogs. Gate A on 8010 and backend preparation on 8012 remain preserved checkpoints.

Read [PROJECT_GOAL.md](PROJECT_GOAL.md), [local logic rules](docs/local-logic-rules-2026-10-02.md), and [agent handoff](docs/agent-handoff.md) before continuing. The extraction payload is version 1.2 (`backend/contracts.py:20`; legacy 1.1 is still accepted, `backend/contracts.py:21`; the OpenAI adapter emits 1.2, `backend/providers.py:187`); source observations, parses, catalog suggestions and human decisions remain separate. Every product approval is explicit. The reviewed-product summary has no cart/order writes. Training, deployment, Apple, AWS and cart or order writes are not part of this phase.

## Run the live demo with your own OpenAI key

Live mode reads a real order with an OpenAI model and costs real money (a few
cents per document). Free mode above stays the default. Work through these steps
in order from the repo root, in a normal (not administrator) PowerShell. The key
is only ever typed into one ignored file on your own PC.

**1. Create the key file.** The file is `.env.backend` in the repo root (next to
`README.md`). Git ignores it (`.gitignore` line 9, `.env.*`); check with
`git check-ignore -v .env.backend`. It holds two lines:

```text
OPENAI_API_KEY=PASTE_YOUR_KEY_HERE
PO_BACKEND_LOCAL_API_TOKEN=PASTE_A_PRIVATE_TOKEN_OF_16_OR_MORE_CHARACTERS
```

The token is a private password you invent for the local server. It must be at
least 16 characters and must not be the shared default. Create the file without
the key showing in shell history or on screen: run `notepad .env.backend`, answer
Yes to create the file, paste the two lines, replace the placeholders, save, and
close. Check in Explorer that the name is exactly `.env.backend` and not
`.env.backend.txt`. Never use `echo`, `Set-Content` or any command that contains
the key.

**2. Protect the key.** Never share it in chat, email, Git or screenshots, and do
not copy someone else's key. Create a separate OpenAI project key with a monthly
budget limit on that project, and revoke the key when you are done.

**3. Rehearse for free.** This shows the live screens against a fake OpenAI. It
needs no key and makes no network calls:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-poc-demo.ps1 -LiveRehearsal -Port 8021
```

Wait for `Live rehearsal (fake transport, no key, no network) ready`, then open
`http://127.0.0.1:8021/poc-demo`. Stop with Ctrl+C.

**4. Probe once (a few cents, needs the key).** This sends one fictional one-page
PDF, never a real order:

```powershell
.\.venv-backend\Scripts\python.exe scripts\poc-probe-live.py --confirm
```

Without `--confirm` it refuses and sends nothing. The output lists the model,
`result` (`succeeded` or a failure), latency, tokens, estimated cost and
`model_accepted_this_input`: `yes` means the model took the PDF; `probably_no`
means it rejected the PDF, so rerun with `--images` and, if that works, set
`$env:PO_POC_PDF_AS_IMAGES = '1'` before step 5 (one-page PDFs only);
`unknown` means the failure was something else, so check the key and budget.
Cost shows only after you set `PO_POC_INPUT_USD_PER_MTOK` and
`PO_POC_OUTPUT_USD_PER_MTOK` to your current prices.

**5. Go live.**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-poc-demo.ps1 -Live -Port 8021
```

Add `-CatalogFile C:\private\catalog.json -FreshDatabase` to use your own catalog
(keep it outside the repo). Live processing is switched on for that process only.
Upload a PDF or photo: the page asks whether to send this document to OpenAI and
shows the cost; only **Send** submits it, and the same file is never sent twice.
The page shows a running count. By default the spend cap counts runs:
`PO_POC_MAX_LIVE_RUNS` (default 5). To cap by estimated dollars set
`PO_POC_INPUT_USD_PER_MTOK`, `PO_POC_OUTPUT_USD_PER_MTOK` and
`PO_POC_SPEND_CAP_USD` (default 3) in PowerShell before starting, for example
`$env:PO_POC_MAX_LIVE_RUNS = '3'`. At the cap, new uploads are refused with a
plain message; raise the limit and restart. `-FreshDatabase` resets the count.

**6. Stop.** Press Ctrl+C in the terminal. Live data stays in the ignored `data/`
folder.

**Windows details.** If `python` is not on PATH, add `-Python 'C:\path\to\python.exe'`
(`py -3.12 -c "import sys;print(sys.executable)"` prints it). If PostgreSQL is not
on PATH, add `-PostgresBin 'C:\path\to\postgres\bin'`. Use port 8020, or
`-Port 8021` if 8020 is taken. Choose `-Live` or `-LiveRehearsal`, not both.

**If it refuses** (nothing is started and nothing is sent):

| Message starts with | What to do |
| --- | --- |
| `Live mode needs a private local API token` | Add `PO_BACKEND_LOCAL_API_TOKEN` (16 or more characters, your own) to `.env.backend`. |
| `Live mode needs your OpenAI key` | Add `OPENAI_API_KEY` to `.env.backend` yourself. |
| `The server settings could not be loaded` | Look for a typo in `.env.backend`; values are never printed. |
| `Refused: this sends one small fictional page` | Rerun the probe with `--confirm`. |
| `The limit for this demo is reached` / `poc_spend_cap_reached` | Raise `PO_POC_MAX_LIVE_RUNS` or `PO_POC_SPEND_CAP_USD`, then restart. |
| `POC stopped with an error` | Printed after any refusal above; read the line before it. |

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
