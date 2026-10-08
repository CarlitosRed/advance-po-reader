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
The separate live OpenAI mode on Carlos's machine needs Carlos's private key and
authorization. Never request or share keys in chat or files, and never copy his
credentials to a teammate's machine. See the [demo runbook](docs/poc-demo-runbook.md)
for the free workflow and its limits.

Local agent integration is implemented: 11 scoped STDIO MCP tools connect to
the website, with human source authorization and product approval in the UI.
The website follows agent-started runs and shares the saved review summary.
Read [the agent/demo activation guide](docs/local-agent-demo.md). The backend
API key is still deferred; no live OpenAI request or customer-file transfer has
been made. Actual STDIO and fictional/mocked workflows are verified.

The active local website is implemented in `web/local-reader/`, served by the FastAPI backend. It connects the three supplied catalog namespaces, private original PDF library, saved uploads/runs, source previews, and evidence-preserving review/audit. Read [the website runbook](docs/local-website.md) and [verification record](docs/website-verification.md). It runs locally without an API key; real extraction is deferred until the server key, current model verification and source-specific customer authorization are supplied.

The user selected one local test workspace with three manually selected catalogs (WernerCo, United Kingdom, Australia), and the original 33-PDF email archive. Product IDs remain separate across catalogs. No country is inferred for WernerCo. This worktree owns port 8014, database gate_a_backend_website, and its private data/output directories. Source changes are on codex/local-website-catalogs. Gate A on 8010 and backend preparation on 8012 remain preserved checkpoints.

Read [PROJECT_GOAL.md](PROJECT_GOAL.md), [local logic rules](docs/local-logic-rules-2026-10-02.md), and [agent handoff](docs/agent-handoff.md) before continuing. The extraction payload is version 1.1; source observations, parses, catalog suggestions and human decisions remain separate. Every product approval is explicit. The reviewed-product summary has no cart/order writes. There is no live provider request, training or deployment in this phase.

## Preserved foundations and comparison components

The original Gate A foundation in gate_a/ established health/configuration, local PostgreSQL/Alembic and the ProductDocument v1 envelope. Its [guide](docs/gate-a.md) records that checkpoint. Backend preparation in backend/ implemented validated uploads, immutable source/run/provider history, bounded candidates and review/audit; [its runbook](docs/local-backend.md) and [historical verification](docs/backend-verification.md) describe the earlier branch. The existing self-hosted reader and all research remain preserved under their existing paths. Their measurements do not evaluate the new OpenAI provider.

The earlier prototype's local-model implementation and training-data tooling have been removed. The retained CLI extraction path uses the native PDF text engine; it is a prototype and is not the new FastAPI/ProductDocument v1 workflow. Historical measurements and operating guides are in [docs/archive](docs/archive/README.md). Original research sources remain in `docs/research/` as evidence and do not authorize provider transfers, API spending, training, or deployment.

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

Gate A stops at this foundation. Later gates cover uploads, extraction, catalog matching, and human review. Gate A makes no provider request and implements no cart action.

Local Gate A has been implemented and verified within its bounded scope. Later shared-payload, catalog, extraction, review and evaluation gates remain governed by `PROJECT_GOAL.md`. Production use still depends on an authorized authoritative catalog, a defined cart/import contract, independently reviewed evaluation data, and privacy approval for any external processing. The later phone-first product includes a web workflow; the retained CLI is a native-text prototype.

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
