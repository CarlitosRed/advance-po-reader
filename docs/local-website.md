# Local website and real catalogs

> **Superseded checkpoint (banner added 2026-10-08).** This guide describes the website checkpoint before API activation (real extraction deferred, no live call authorized). Later records show the server key configured and one authorized PDF processed once; accuracy is unmeasured. Current scope and the Implemented versus Intended list are in [PROJECT_GOAL.md](../PROJECT_GOAL.md) and [AGENTS.md](../AGENTS.md); later evidence is in [api-activation-verification.md](api-activation-verification.md) and [live-demo-continuation.md](live-demo-continuation.md). The text below is kept unchanged as historical evidence.

For the October 5 T-017 **free synthetic POC**, use
[poc-demo-runbook.md](poc-demo-runbook.md) and `scripts/start-poc-demo.ps1`.
That kit owns a fresh database, bypasses dotenv and injects fixed fictional
observations; it uses a separate vendor-scoped entry because synthetic
namespaces cannot join the all-products pool. The historical real-catalog
setup below does not prepare that fresh demo. No live call is authorized by
the free kit; see [its verification](poc-demo-verification.md).

Implemented October 2, 2026 in the dedicated managed worktree
`C:\Users\carlo\.codex\worktrees\local-website-catalogs\Advance PO Reader`,
branch `codex/local-website-catalogs`, based on backend checkpoint `ce1a025`.
The subsequent agent/demo preparation is implemented; see
[local-agent-demo.md](local-agent-demo.md) for the 11 scoped tools, source
authorization handoff, shared review summary, startup recovery and API activation.
This chat continues the work; a new chat was unnecessary. The user's explicit
choices are one local test workspace with three separately selected catalogs,
and the original 33-PDF email archive. Use the existing **Create PDF reader website
mockup** design as the reference. No country is assigned to WernerCo.

## Implemented behavior

- FastAPI serves the local HTML/CSS/JavaScript website and private APIs from the
  same origin. The website uses plain text branding only; no logo images are shipped.
  The earlier mockup and its private Site are preserved.
- Three real catalog namespaces contain 2,720 products: WernerCo 2,380,
  United Kingdom 160, Australia 180. IDs are never merged across namespaces.
  The search field named `sku` in the earlier backend carries the unchanged
  catalog primary product ID; this import does not infer printed SKU/barcode,
  ordering-unit, variant or customer-ID aliases.
- The versioned `regional-catalog-adapter-v1` checks the staging database against
  its source manifest, then preserves raw source fields, workbook hashes,
  source labels/row numbers, 42,996 attributes, and 2,570 detail sections in
  immutable PostgreSQL records. Generic catalog imports cannot append to a
  real source namespace. A changed catalog revision or mapping requires an
  explicit future versioning workflow or fresh local database.
- The private original archive is copied and hash-checked before use. All
  33 PDFs and 45 pages are decoded/validated locally. The library preserves
  original filenames and source hashes privately; it does not import the
  legacy VLM observations, source text, candidate targets or training labels.
  Documents begin unprocessed, without a catalog assignment.
- The user selects a catalog before upload or choosing a library document.
  Stored source bytes and opaque references remain immutable. Upload and run
  history, page previews, enlarged source inspection, and source-based row
  previews are available. Coordinates follow the visible raster for rotated
  PDFs and EXIF-oriented photos.
- A separately labeled fictional sample exercises the real local upload,
  run, suggestion, correction and audit APIs. Real uploads never receive
  sample extraction rows.
- Every product approval is explicit. Manual catalog search first records a
  named, bounded `propose_candidate` event. The backend and database allow
  approval only from the original candidate snapshot or an immutable proposal
  within that run/row and catalog. Proposals do not modify original suggestions.
- Corrections preserve raw observations and literal string values, retain
  evidence/reviewer/reason, and invalidate the previous row decision until
  approved again. Non-products are acknowledged separately. All rows,
  partial-page uncertainties and document warnings must be addressed before
  completing a review. Failed pages require a new run.
- The final surface is a reviewed-product summary with literal reviewed
  quantities/units. It performs no cart/order operation and establishes no
  catalog ordering-unit conversion, availability, pricing or order readiness.
- Two optional browser tools read local state or search the already selected
  catalog. They cannot approve, train or invoke extraction.
- The local STDIO agent tools can prepare a library document without processing,
  run a fictional workflow, or process an existing source-authorized OpenAI run
  once. The website follows agent-started processing through read-only polling.
  Human corrections, approvals and review resolution remain in the website.

## Local boundary and ownership

Website: `http://127.0.0.1:8014/`. Database:
`gate_a_backend_website` on the existing loopback PostgreSQL service at
`127.0.0.1:55433`. This worktree owns its environment, source snapshots,
uploads, corpus copies, audit records and outputs. The staging databases and
archive in verified-source-databases are read-only inputs. Gate A on 8010 and
backend preparation on 8012 remain untouched.

The browser uses an unpredictable HttpOnly, SameSite=Strict local session and
an in-memory CSRF token. No API/provider key is sent to JavaScript. The
existing explicit local CLI token remains supported. Origins and Host must
match the loopback boundary; private responses disable caching. This local
development session is not production customer authentication or tenant
authorization. Hosted identity, customer access policy, deployment and shared
file storage are later work.

All private catalog/corpus files, source labels, filenames, hashes, API tokens,
reviews, screenshots and runtime receipts live under ignored data/output or
environment paths. Only source code, fictional fixtures, contracts, brand
assets and sanitized documentation are committed.

## Start and stop

The current machine's isolated environment and private source import are
already prepared. From this worktree:

```powershell
& ./scripts/start-local-website.ps1
```

Open `http://127.0.0.1:8014/`. Use Ctrl+C in the owning terminal to stop a
manually launched server. Do not stop another worktree's server or the shared
native PostgreSQL service. The agent's retained local service and verified PID
are recorded privately in `output/agent-ready/runtime.json`; check
the port owner and launcher path before acting on a saved PID.

Restarting the server expires its in-memory browser session. Reload the
website after a restart; source files, runs and review events remain in
private storage and PostgreSQL.

For a fresh authorized local checkout:

```powershell
python -m venv .venv-backend
& ./.venv-backend/Scripts/python.exe -m pip install -r requirements.backend.lock.txt
Copy-Item .env.backend.example .env.backend
& ./.venv-backend/Scripts/python.exe -m backend.database --create --migrate
```

Use a distinct database/port for another writable worktree. The example uses
synthetic local PostgreSQL credentials, not provider credentials. If the
native PostgreSQL service is absent, follow the preserved local setup guide;
do not reuse a production database.

To load user-approved private inputs, supply paths to the staging catalog
database, its manifest, and original archive. The importer snapshots them
into this worktree before connecting them:

```powershell
& ./.venv-backend/Scripts/python.exe -m backend.source_import --catalog-database PATH_TO_CATALOG_SQLITE --manifest PATH_TO_SOURCE_MANIFEST_JSON --pdf-archive PATH_TO_ORIGINAL_ZIP --mapping single-workspace --assigned-by 'NAMED_AUTHORIZED_USER'
```

This command makes no provider request. Identical reimports are idempotent;
different snapshots/mappings are rejected without replacing recorded evidence.
Source filenames are never used as storage paths.

## Verification and continuation

See [local-agent-demo.md](local-agent-demo.md) for the current phase and
[website-verification.md](website-verification.md) for the preceding checks and
their limits. Use `scripts/test-backend.ps1` for the complete backend and
preserved Gate A suites on this worktree's separately named synthetic test
databases. No Node build or hosted Site registration is required for this
local static frontend.

Real document extraction is still deferred. The server-side provider adapter
is prepared and tested through injected mocks, with live processing disabled
by default. Having a key alone does not enable it. Before activation, verify
the current official model/API/data-control details, configure the key
server-side, and obtain the relevant customer/source authorization and policy.
The UI can save affirmative authorization bound to the exact source hash
before processing is enabled, without making a provider attempt. The existing
CLI live-test command has the same authorization boundary. Active or
unknown-outcome attempts are not automatically retried by the website.

The configured default model `gpt-6.1-sol` and the Responses PDF-input path
were checked against the current official [model catalog](https://developers.openai.com/api/docs/models)
and [file-input guide](https://developers.openai.com/api/docs/guides/file-inputs)
on October 2, 2026. This documentation check does not verify account access,
live provider responses, retention policy compliance or extraction quality.
Recheck the relevant data controls when setting up the server credential.

First test one authorized source, inspect the literal extraction, bounded
candidates, and review/audit end to end, then plan the wider 33-PDF evaluation.
No independent reviewed gold set was created here. Frozen gold labels,
accuracy/recall, realized provider cost, hosted deployment, Apple, Qwen,
training, and real cart/order integration remain unverified or deferred.
