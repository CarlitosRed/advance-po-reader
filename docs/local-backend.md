> The current website branch extends this backend on port 8014 and database gate_a_backend_website. Use [local-website.md](local-website.md) for current startup and real catalog/corpus integration. The backend-only checkpoint and commands below are preserved context; its original service on 8012 remains independent.

# Local backend preparation

Updated October 2, 2026. The user's direct request expanded the completed Gate A into a local backend slice, with the website and OpenAI key later. This branch implements and tests that slice using fictional synthetic documents. No live provider call, credential creation/import, customer-file transfer, API spend, training, Apple/Qwen inference, AWS resource, website, cart or order action was performed.

The source branch is `codex/local-backend-preparation`, in the dedicated `ffd4` managed worktree. Gate A checkpoint `d67616c2f5e4210b06391ee32537df290a6d89d7` remains on `codex/local-gate-a`; it was cherry-picked here as `6d82d1c`. Its original HTTP service on `8010` and database `gate_a_service` were preserved. This backend uses loopback port `8012` and its own `gate_a_backend_dev` database. The source checkpoint is local; no push was performed.

## Implemented behavior

- `backend/` is an independent FastAPI application. It does not import the legacy reader/inference pipeline. Construction and startup require neither a database connection nor a provider key; readiness reports unavailable/unmigrated databases separately from liveness. Migrations are explicit commands.
- `ProductDocument` extraction payload **1.2** is the current OpenAI boundary in `backend/contracts.py`, `contracts/product-document-extraction-1.2.json` and `contracts/product-document-extraction-1.2-provider.json`. Frozen 1.1 payloads and `/v1.1` provider schema remain readable for legacy runs. Gate A's **1.0 envelope remains unchanged**. Version 1.2 adds explicit `row_role`, `item_group_id` and `continuation_of`; raw page observations remain separate rows. A continuation must be an unknown-kind observation linked to one earlier product root, on the same page, with horizontally aligned, vertically adjacent source regions and no independent identifiers, quantity, unit, unit price or line total. An adjacency, vendor/description match, sequence number, or blank quantity alone is insufficient. Truly unknown rows remain review blockers. Product roots with blank quantity remain separate product items.
- Tenant/vendor catalogs and supplied aliases use compound scope constraints. Imports are atomic and idempotent for identical products; changed descriptions or conflicting aliases return conflict. Exact role-sensitive identifiers come first, then cautious ASCII search variants, then bounded indexed `pg_trgm` candidates when available. Unknown roles never silently become vendor SKUs. No embeddings or model adjudicator was justified for this initial local slice. Every candidate requires human approval, including an exact hit. Charge/tax/subtotal/total/note/unknown rows never enter matching.
- Actual PDF/PNG/JPEG decode validation runs in a short-lived worker. Defaults: 10 MiB upload, 20 PDF pages, 8,000-pixel image side and 25 million image pixels; decoding times out at 15 seconds. Every PDF page is decoded with bounded render output. Encrypted/repaired/malformed PDFs, animated or unsupported images and excessive dimensions are rejected. Files are stored under this worktree's ignored `data/` using opaque references; filenames are ignored. SHA-256 is checked before processing. Storage references cannot be arbitrary paths.
- Immutable sources are distinct from processing runs. Upload and run keys are scoped to a tenant, and the same key with a different payload returns HTTP 409. A new key deliberately creates a new processing run while retaining previous observations, attempts, suggestions and review events. Run creation itself does not process a file.
- A provider attempt is committed as `unknown_outcome` **before** the provider boundary, so interruption does not invite a hidden retry. There is one explicit attempt per run. The receipt retains requested model, returned model when provided, prompt/schema versions, request/response IDs, actual usage, latency, state and sanitized error code. Refusal, invalid/missing output, incomplete output, timeout/disconnect, cancellation, unsupported/unknown type and source-integrity failure have explicit outcomes. Cancellation during a provider callback retains its attempt metadata and discards the uncommitted observation.
- The server-side OpenAI adapter constructs a single Responses request against the fixed official endpoint. It has no automatic connection/status retries, redirects, provider URL supplied by a client, file-URL ingestion or Files API upload. PDF bytes use `input_file`; image bytes use `input_image`. Strict `text.format` shape is followed by application semantic validation. The new default is `gpt-6-luna`; the project chat verified its official model metadata and documented image/structured-output support on October 2, 2026. No generation request or customer content was sent in this verification. `store=false` is the configurable default; it is **not a promise of zero provider retention**.
- Live processing is disabled by default. Disabled processing or a missing key returns `provider_not_configured`, with no attempted request and no substitute extraction. Even when enabled/key-configured, an OpenAI run requires affirmative, named, policy-referenced authorization bound to that exact source SHA-256. The synthetic provider works only for exact hashes of the built-in deterministic fictional fixtures; it rejects an ordinary upload or changed fixture.
- Review projection policy **`review-summary-v2`** is shared by `/runs/{id}/summary`, the browser and `reader_get_review_summary`. Product roots and true unknown rows are actionable; typed charge/tax/subtotal/total/note rows remain in immutable extraction evidence and `document_details`, with no fabricated row acknowledgement. A validated continuation remains linked evidence on the root product card and does not require a separate review event. Continuations cannot be separately approved, excluded, acknowledged or proposed. A correction after approval makes that product unresolved. Candidate approval remains explicit and candidate-bound. Partial pages and document warnings require explicit acknowledgement; failed pages require a new run. A resolved review remains immutable. Existing review events are preserved as legacy audit history; the policy version is returned explicitly. This projection-only change requires no database migration.
- Local browser mutations require `X-Local-Token`, a loopback Host and a same-origin request when an Origin is supplied. Cross-site browser requests are denied. Whole request bodies are bounded before multipart parsing, including streaming requests. All private reads also require the local token. `X-Tenant-ID` is a **local scope convention**, not production identity/authentication. Do not expose this server publicly as tenant authentication. Access logging is disabled; error responses omit raw input/provider exception text and unknown JSON property names.

## Setup and current machine

Python 3.12 is required. The verified environment is `.venv-backend`; dependencies are pinned in `requirements.backend.lock.txt`. The legacy unittest suite uses the bundled base runtime because its existing PDF dependencies are deliberately absent from the independent backend environment.

On this machine, the Gate A worktree owns native PostgreSQL 17.11 at `127.0.0.1:55433`. This task reused that server only through separate databases; it did not stop it, alter its cluster/runtime or migrate/write `gate_a_service`. `backend.config.Settings` rejects that database and unrelated database names. PostgreSQL configuration requires loopback `postgresql+psycopg` and a `gate_a_backend_` or `gate_a_test_backend_` database. If the original cluster is unavailable, its owner should manage its lifecycle using `docs/gate-a.md`; this backend does not start or stop it.

From this worktree:

```powershell
.\setup-backend.ps1
# Optional local settings; the example has no provider key.
Copy-Item -LiteralPath .env.backend.example -Destination .env.backend
.\.venv-backend\Scripts\python.exe -m backend.database --create --migrate
.\scripts\start-backend.ps1
```

Skip the copy if `.env.backend` already contains intentional local configuration. Default settings already work here. `Ctrl+C` stops a foreground backend. The live verification instance was started separately; inspect `output/backend-verification/runtime.json` and confirm the recorded worker still owns `8012` before stopping it. Python's Windows virtual-environment launcher can have a distinct worker PID. Do not stop the `8010` Gate A service or shared PostgreSQL server.

Open [API documentation](http://127.0.0.1:8012/docs), [OpenAPI JSON](http://127.0.0.1:8012/openapi.json), [liveness](http://127.0.0.1:8012/health/live), [readiness](http://127.0.0.1:8012/health/ready), or [configuration](http://127.0.0.1:8012/configuration). Health/config/schema metadata are public on loopback. The business routes require the development token `local-backend-dev-only` unless overridden; it is a local development value, not a provider credential.

## Endpoint contract

`X-Local-Token` protects all private routes. Tenant-scoped routes additionally require `X-Tenant-ID`. Upload/run creation require `Idempotency-Key` (1–120 ASCII characters). The OpenAPI document includes typed request/response models and the full extraction graph for later website clients.

| Method and route | Request / result |
| --- | --- |
| `GET /health/live`, `/health/ready`, `/configuration` | Independent liveness/readiness and safe configuration; no secret values. |
| `GET /contracts/product-document/v1/schema` | Preserved Gate A 1.0 envelope. |
| `GET /contracts/product-document/v1.1/schema`, `/provider-schema` | Application schema and Responses strict schema. |
| `POST /tenants` | `{ "name": "Synthetic tenant" }` → local tenant UUID. |
| `POST /vendors` | Tenant header plus `{ "name": "Synthetic vendor" }` → vendor UUID. |
| `POST /catalog/import` | `{ "vendor_id": "UUID", "products": [{ "sku": "SYN-001", "description": "Synthetic blue widget", "aliases": [{ "value": "CUSTOM-01", "source_role": "customer_item" }] }] }`. |
| `GET /catalog?vendor_id=UUID&limit=100&offset=0` | Scoped product/alias records, limit/offset and `next_offset`. |
| `POST /documents` | Multipart `file` and `vendor_id`; returns immutable source metadata/hash/reference. |
| `GET /documents/{source_id}` | Scoped source metadata; does not serve raw file bytes. |
| `POST /documents/{source_id}/runs` | `{ "provider": "synthetic", "fixture_name": "purchase_order", "external_authorization": null }`; state starts `created`. Normal provider default is `openai`. |
| `GET /documents/{source_id}/runs` | Prior and current runs remain distinct. |
| `POST /runs/{run_id}/process` | One explicit synchronous attempt. Replayed terminal processing returns its saved status; active/uncertain work cannot be retried. |
| `POST /runs/{run_id}/cancel` | Cancels a nonterminal run. A remote callback may still finish, with metadata retained. |
| `GET /runs/{run_id}`, `/result`, `/suggestions`, `/reviews` | Processing/review status, immutable extraction+separate parses+attempts, bounded candidate snapshots and audit events. |
| `POST /runs/{run_id}/reviews` | Named `approve`, `no_match`, `acknowledge`, `correct`, `acknowledge_page`, `acknowledge_document` or `resolve` event. |

A review example uses the row's actual evidence references and an actual candidate ID from `/suggestions`:

```json
{
  "action": "approve",
  "row_id": "line-1",
  "reviewer": "Named reviewer",
  "reason": "Compared the literal source with the supplied candidate",
  "evidence_reference": [{"page_number": 1, "region_reference": "line-1"}],
  "selected_candidate_id": "UUID-FROM-THIS-ROW-SNAPSHOT"
}
```

`correct` requires `field_name` and nullable `new_value`. Supported fields are `description`, `quantity`, `unit`, `unit_price`, `line_total`, `identifier.raw_value`, `identifier.source_label` and `identifier.source_role`. Identifier fields also require `identifier_index`. Corrected values are audit data, not replacements in extraction or global catalog rules. Page/document acknowledgements have no row ID and use declared page/region evidence. `resolve` has no row, candidate or evidence list; it checks saved decisions and uncertainty acknowledgements.

## Reproducible synthetic demo and reports

Keep the server running in one terminal; run this in another:

```powershell
.\scripts\demo-backend.ps1
# Equivalent command with explicit report location:
.\.venv-backend\Scripts\python.exe -m backend.demo `
  --base-url http://127.0.0.1:8012 --output output/backend-demo
```

The command creates a unique synthetic tenant/vendor, imports two fictional products/one explicit alias, generates a real PDF and PNG, uploads, checks replay/conflict behavior, processes through the explicit fixture provider, retrieves results/candidates, records a named synthetic review of every row and resolves both PO runs. It also exercises default OpenAI `provider_not_configured` and an unsupported document. The generated sources remain under ignored `data/demo-agent/`; `output/backend-demo/workflow-evidence.json` and `evaluation.json` hold private inspectable reports. Re-running creates a new tenant/history and replaces only those report filenames.

Evaluation expectations are declared independently of the extraction output. Failures/partial runs remain in applicable denominators. Reports separate literal field/role/quantity/unit/price fidelity, product-line recall/extra rows, candidate Recall@K, suggestion precision, no-match behavior, review events, latency, usage and known cost. Reviewer time and real cost remain unknown without actual evidence; token usage is not an invoiced charge. Auto-accept is disabled. Synthetic fixture scores test workflow mechanics and **do not measure real model performance or held-out accuracy**. There is no frozen reviewed customer gold set in this branch.

## Later source-authorized live activation

No key was imported or created for this work. When the user later provides a credential through an appropriate secure local workflow, configure `OPENAI_API_KEY` server-side in the ignored environment and explicitly set `PO_BACKEND_LIVE_PROCESSING_ENABLED=true`. Restart only this backend. A key by itself does not enable requests, and startup never sends one. `.env.backend.example` deliberately contains no provider key. Do not place keys in a document committed to Git, browser code, API bodies or normal tool output.

Each live run needs an authorization object:

```json
{
  "authorized": true,
  "source_sha256": "EXACT-LOWERCASE-SOURCE-SHA256",
  "authorized_by": "Named authorizer",
  "policy_reference": "Applicable customer/privacy permission reference",
  "reason": "Purpose approved for this particular source"
}
```

The later command validates affirmative flags and exact source hash, checks configured/explicitly enabled server state, then uploads locally and requests processing once:

```powershell
# LATER ONLY: use an authorized source and its real tenant/vendor UUIDs.
$env:PO_BACKEND_LOCAL_API_TOKEN = 'YOUR-LOCAL-SERVER-TOKEN'
$taskAuthorizedSource = 'C:\path\to\authorized-source.pdf'
$taskAuthorizedHash = (Get-FileHash -LiteralPath $taskAuthorizedSource -Algorithm SHA256).Hash.ToLowerInvariant()
.\.venv-backend\Scripts\python.exe -m backend.live_test `
  --source-path $taskAuthorizedSource --source-sha256 $taskAuthorizedHash `
  --tenant-id 'TENANT-UUID' --vendor-id 'VENDOR-UUID' `
  --authorized-by 'Named authorizer' --policy-reference 'Applicable policy reference' `
  --reason 'Approved test of this particular material' --authorize-external-processing
```

This command's enabled behavior was tested only with injected offline transports. Do not execute it merely because a key exists. Its saved result is unreviewed provider evidence, not a training label or accuracy report. A timeout/database outage after an attempt begins leaves explicit uncertainty; inspect `/result` and original run before any separately deliberate new run. No hidden retry or model fallback occurs. In this synchronous local phase, a crash or database outage can leave a run `processing` with a persisted unknown attempt; a duplicate request returns conflict instead of spending again. Local orphan blobs can remain if a database transaction fails after file storage; they are ignored private files, never source overwrites.

## Tests and verification state

```powershell
.\scripts\test-backend.ps1
.\.venv-backend\Scripts\python.exe -m pip check
.\.venv-backend\Scripts\python.exe -m alembic -c backend.alembic.ini current
.\.venv-backend\Scripts\python.exe -m alembic -c backend.alembic.ini check
```

The script creates separate synthetic test databases and sets opt-in URLs for the API, catalog and contract/failure suites. Never point tests at a service/private catalog database. Without those explicit URLs, PostgreSQL tests skip rather than mutate a database. The preserved Gate A suite uses a separate `gate_a_test_backend_gate_a` database and its original migration configuration. Existing legacy tests remain independent:

```powershell
& 'C:\Users\carlo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests -q
```

Local validation covers actual PostgreSQL migrations/constraints/trigram retrieval, tenant/vendor isolation, all five observation states, full page/region graph, deterministic decimal preservation, actual decode failures/limits, idempotency/concurrent retries, independent reprocess history, cancellation during success/exception callbacks, active uncertain attempts, refusals/missing/invalid/incomplete outputs, unknown remote outcomes, candidate bounds, audit integrity, corrections and resolution gates, secret/source redaction, and later live-command authorization. All provider responses in tests use mocks. Exact final counts and live smoke results are recorded in `docs/backend-verification.md` and ignored `output/backend-verification/`; remote CI, hosted deployment, real OpenAI requests and model performance are unverified.

## Dataset workstream inspected

At the user's request, this task read **Create VLM training dataset** and `docs/source-databases.md` in the separate `verified-source-databases` worktree. It also opened the two SQLite staging files read-only to inspect their table names and approval/mapping counts. `approved_training_examples` returned **0**, and `tenant_catalog_assignments` returned **0**. No PDF blobs, private observations or catalog rows were copied into this branch or its synthetic fixtures.

Those databases preserve original PDF/page evidence and legacy candidate annotations separately from regional catalog namespaces. They can inform a later integration, but are not already PostgreSQL API data or a ProductDocument 1.1 adapter. Before that integration, approve each source catalog's tenant/vendor mapping, preserve workbook/product provenance and attributes in a versioned import, and review evidence independently. The WernerCo workbook name alone does not establish a country/tenant. Do not convert pending annotations or retrieval hits into gold labels. Dataset creation remains distinct from training authorization.

## Official provider references checked October 2, 2026

The adapter follows the fetched [file-input guide](https://developers.openai.com/api/docs/guides/file-inputs) for base64 PDF inputs, the [image-input guide](https://developers.openai.com/api/docs/guides/images-vision) for image data URLs, and the [structured-output guide](https://developers.openai.com/api/docs/guides/structured-outputs) for Responses `text.format`, required nullable properties and closed objects. The strict schema is application-validated as well; shape does not prove factual transcription.

The [GPT-6 Luna model page](https://developers.openai.com/api/docs/models/gpt-6-luna) lists image input and structured outputs; the project chat also completed a metadata-only GET returning the requested model ID. This is not a generation or PDF-compatibility test. The implementation uses a single direct HTTP request, not an SDK retry loop, and has no automatic model fallback. [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data) describe application-state and other retention behavior; `store=false` does not establish zero retention. Recheck these date-sensitive sources before activation. This branch records actual token usage and does not calculate an invoice from research pricing.

## Continuation-fix integration handoff

The development branch `codex/orderlens-product-rows` contains this extraction/review change and no catalog retrieval implementation. It is based on `1051805aa502f65b6d188c1a7b1958325701cc69`. Combine it with catalog change `e646570a7ebc1faa91d0b364adb5e4ab627d9fcb` (`0006_catalog_description_hint`); the catalog branch adds `catalog-retrieval-v2` provenance and immutable suggestion snapshots. My changes create no migration, so `0007` remains the next available revision if the combined pool work requires one. Shared touch points are `backend/service.py` and the local reader UI under `web/local-reader/`; preserve both branch changes when merging. The original live run/schema 1.1 observations, suggestions and events remain unchanged. Start a new extraction run to use `ProductDocument 1.2` and `review-summary-v2`; do not reinterpret or rewrite the old run. `output/pdf/synthetic-continuation-review.pdf` is the fictional browser-verification fixture; generated PDF/PNG are ignored, not committed.

PostgreSQL [pg_trgm documentation](https://www.postgresql.org/docs/17/pgtrgm.html) supports the optional GIN similarity operators used here. The fallback stays exact/normalized when the trusted extension cannot be installed. No vector service, merchant scraping or private provisional sample catalog was used.
