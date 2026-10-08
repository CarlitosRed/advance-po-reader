# Local Gate A foundation

> **Superseded checkpoint (banner added 2026-10-08).** This guide records the Gate A checkpoint, whose boundary excluded upload, extraction, matching, review and any provider request. Those were built afterwards; Gate A itself still makes no provider request. Current scope and the Implemented versus Intended list are in [PROJECT_GOAL.md](../PROJECT_GOAL.md) and [AGENTS.md](../AGENTS.md); later evidence is in [api-activation-verification.md](api-activation-verification.md) and [live-demo-continuation.md](live-demo-continuation.md). The text below is kept unchanged as historical evidence.

Implemented October 2, 2026 on `codex/local-gate-a`, starting from published commit `a41bf23c23bce63d38db8d04ccef1fb1137c279d`. The `gate_a` package is independent of the legacy `po_reader` package. It has no provider configuration, requires no API key, and starts with PostgreSQL stopped. Readiness stays unavailable until the local database is reachable and explicitly migrated.

Gate A implements health/configuration, a PostgreSQL tenant foundation, Alembic migrations, and an initial `ProductDocument v1` envelope with reusable observation/state validation. It does not implement document ingestion or extraction. The full extraction payload and any mapping from `PAGE_EXTRACTION_SCHEMA` remain to be specified at their later gate. The [project goal](../PROJECT_GOAL.md) and [local logic rules](local-logic-rules-2026-10-02.md) continue to govern scope.

## Set up and run

Use Python 3.12. From this worktree, create a separate environment and install the pinned Gate A dependencies:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup-gate-a.ps1 -PythonPath 'PATH_TO_PYTHON_3_12.exe'
& .\.venv-gate-a\Scripts\python.exe -m gate_a
```

The second command runs in the foreground. Defaults bind the API to `127.0.0.1:8000` and configure PostgreSQL at `127.0.0.1:55432/gate_a`. No database connection or migration occurs at application construction/startup. `/health/live`, `/configuration`, and the contract-schema endpoint work without PostgreSQL.

Optional settings are in `.env.gate-a`, a Git-ignored file anchored to the project root. Copy `.env.example` there for the Compose defaults. Environment variables with the `PO_READER_` prefix override that file; explicit `Settings` constructor arguments override environment variables. Only the `local` environment, a loopback bind address, and a `postgresql+psycopg` URL with a loopback host, database name, and no query overrides are accepted. Provider environment variables are not read. `/configuration` returns only public gate/contract metadata; it never returns the database URL or credentials.

The dependency lock includes the test tools. It does not import or install the legacy PDF/model stack. Settings reject unknown entries in the dedicated dotenv file, making configuration mistakes visible.

## Local PostgreSQL and migrations

For a machine with Docker Compose available:

```powershell
docker compose -p po-reader-gate-a-d9fa -f compose.gate-a.yml up -d --wait postgres
& .\.venv-gate-a\Scripts\python.exe -m alembic upgrade head
& .\.venv-gate-a\Scripts\python.exe -m alembic current
& .\.venv-gate-a\Scripts\python.exe -m alembic check
```

Use a unique Compose project name for every worktree. The PostgreSQL 17 service publishes only `127.0.0.1:55432` and binds persistence to this worktree's ignored `data/gate-a/postgres` directory. Its `gate_a` / `gate_a_local` credentials and seeded tenant are synthetic local development values. They are not a hosted configuration. Stop it with `docker compose -p po-reader-gate-a-d9fa -f compose.gate-a.yml down`; the bind data remains for the next start.

Revision `0001_gate_a` creates only `tenants` and Alembic's revision table. The tenant has a UUID primary key, nonblank name, and server timestamp, with one seed named `Gate A synthetic development tenant` and UUID `00000000-0000-0000-0000-000000000001`. This establishes a future scope anchor; it does not implement authentication, access control, catalogs, sources, processing runs, or review persistence.

Migrations are explicit CLI operations. The API never calls `create_all`, applies migrations, writes a seed, or repairs a revision. Readiness requires exactly the expected single Alembic head. An empty, older, newer, or multi-head database returns `migration_required`. Connection, pool, and statement timeouts bound database waits; database exceptions become a generic `unavailable` status, without error text in the response.

An explicit `alembic downgrade base` removes the Gate A tenant table. Use it only against an owned disposable local database; the verification tests use isolated synthetic databases and do not touch the legacy catalog.

## HTTP surface

| GET route | Behavior |
| --- | --- |
| `/health/live` | `200`, process is alive; no database use. |
| `/health/ready` | `200` with database `ready`, or `503` with `unavailable` / `migration_required`. |
| `/configuration` | Safe local gate and contract metadata, including `extraction_payload_finalized: false`. |
| `/contracts/product-document/v1/schema` | JSON Schema for the envelope only. Accepts no document or observation data. |
| `/openapi.json` | Local API metadata. |

There are no POST or mutation routes. Browser documentation that would load external CDN assets is disabled. This is a backend foundation without a review UI.

## Contract boundary and states

`ProductDocumentV1` requires explicit `schema_version: "1.0"`, `document_type: "purchase_order"`, and tenant/source/run UUID references. Missing versions/classification, unsupported types, and extra payload fields are rejected. UUIDs are references, not evidence that a source exists or has been uploaded. Persistence referential validation belongs to its later gate.

```json
{
  "contract_name": "ProductDocument",
  "schema_version": "1.0",
  "tenant_id": "00000000-0000-0000-0000-000000000001",
  "source_document_id": "00000000-0000-0000-0000-000000000002",
  "run_id": "00000000-0000-0000-0000-000000000003",
  "document_type": "purchase_order",
  "run_state": "created",
  "review_state": "not_started"
}
```

The module also supplies reusable frozen observation primitives. These are independently validated building blocks; the envelope contains no extraction payload:

- `FieldObservation` requires a state and explicit string-or-null `raw_value`. `observed` requires literal text and page/region evidence; `uncertain` retains a best reading and/or alternatives tied to the same evidence; `unreadable` retains evidence with null raw text; `not_present` and `not_applicable` cannot invent values. Numeric raw inputs are rejected, and strings retain spacing, punctuation, and leading zeroes.
- `IdentifierObservation` additionally requires explicit source label and possible role (each string or null). These never become canonical catalog identifiers.
- `ParsedDecimal` records a separate finite decimal string, parse status, and method. It validates a supplied deterministic result and does not perform parsing. Unsupported or ambiguous parses retain a null value with `unresolved` status and their method.
- `RowKind` distinguishes product, charge, tax, subtotal, total, note, and unknown vocabulary. It does not define rows or classify documents.

Processing and human-review state remain independent. Pure validators allow `created → validating → processing`, then `completed`, `partial`, `failed`, or `cancelled`; active stages can also fail or cancel. Terminal states have no outgoing edge. Reprocessing must use a new run reference. Review allows `not_started → in_progress → resolved`. The validators do not start work, persist state, approve a match, or enforce a future workflow's cross-state rules.

## Tests and verification

```powershell
& .\.venv-gate-a\Scripts\python.exe -m pytest -c pytest.gate-a.ini
```

The default suite uses synthetic observations and SQLite surrogate/offline migration checks. SQLite and generated PostgreSQL SQL are separately identified; they do not establish live PostgreSQL behavior. Live integration tests are opt-in:

```powershell
$env:GATE_A_TEST_DATABASE_URL = 'postgresql+psycopg://gate_a:gate_a_local@127.0.0.1:55433/gate_a_test_baseline'
& .\.venv-gate-a\Scripts\python.exe -m pytest -c pytest.gate-a.ini
Remove-Item Env:GATE_A_TEST_DATABASE_URL
```

Use only an empty, owned loopback PostgreSQL database named `gate_a_test_*` with no URL query overrides. Tests reject a populated database and preserve isolation. Keep the service database separate. The Gate A pytest directory has no package initializer, so the existing legacy unittest job does not import these separate dependencies. A new GitHub workflow defines Gate A checks with an ephemeral PostgreSQL service; remote execution is a separate verification state.

The October 2 machine verification used Python 3.12.14 and a native PostgreSQL 17.11 portable runtime obtained through the [official PostgreSQL Windows page](https://www.postgresql.org/download/windows/) and its linked [EDB binary archive](https://www.enterprisedb.com/download-postgresql-binaries). No Windows service was installed. The runtime/cluster are confined to ignored `data/gate-a-verification`, with logs and evidence under ignored `output/gate-a-verification`. Docker was unavailable, so Docker Compose execution is unverified; live native PostgreSQL migrations were tested separately.

The verified native service uses `.env.gate-a` with PostgreSQL at `127.0.0.1:55433/gate_a_service` and HTTP at `127.0.0.1:8010`. The live smoke checks covered startup with PostgreSQL absent, pre-migration readiness, explicit upgrade and repeat upgrade, post-migration readiness, migration current/head, and Alembic schema-drift checks. The JSON evidence records the local process ID, statuses and commands. Recheck live health before relying on a saved process ID or prior result.

The final Gate A suite passed **135 tests with no skips or warnings** against that isolated PostgreSQL runtime, including upgrade/downgrade/seed validation and a real exclusive-lock test proving a timed-out readiness read returns `unavailable` and recovers after the lock is released. The test database was empty after cleanup. `pip check` passed; Alembic reported revision `0001_gate_a (head)` and no new upgrade operations. These are Gate A infrastructure/contract results, not extraction, matching or provider measurements.

The database-free suite passed **133 tests with 2 explicit live-PostgreSQL skips**. The preserved legacy unittest discovery also completed successfully: **101 tests reported, 9 skips for unavailable private PDF/catalog fixtures**. Legacy tests used synthetic inputs and mocked provider requests; no real model/provider was exercised. This confirms discovery remains separate without copying private fixtures into this worktree.

The private VLM dataset from **Update Goal and Build VLM Test** was considered as context. Its guide describes source-bound draft visual transcriptions pending human review, useful for a later extraction evaluation or adapter gate. It was not copied, consumed, or used as ground truth for Gate A; all fixtures here are synthetic. The active dataset-building chat and legacy private directories retain their ownership.

## Local verified runtime lifecycle

The portable runtime is an optional machine-local verification setup, not a dependency downloaded by source startup. If retained, restart its existing cluster from this worktree using:

```powershell
$taskPgCtl = (Resolve-Path 'data/gate-a-verification/runtime/pgsql/bin/pg_ctl.exe').Path
$taskPgCluster = (Resolve-Path 'data/gate-a-verification/cluster').Path
$taskPgLog = [IO.Path]::GetFullPath('output/gate-a-verification/postgres.log')
$taskPgProcess = Start-Process -FilePath $taskPgCtl -ArgumentList @('-D', ('"' + $taskPgCluster + '"'), '-l', ('"' + $taskPgLog + '"'), '-w', '-t', '30', 'start') -WindowStyle Hidden -PassThru
if (-not $taskPgProcess.WaitForExit(30000)) { throw 'PostgreSQL start timed out; inspect its log.' }
if ($taskPgProcess.ExitCode -ne 0) { throw 'PostgreSQL failed to start; inspect its log.' }
& .\.venv-gate-a\Scripts\python.exe -m gate_a
```

Use Ctrl+C for a foreground API. Windows' virtual-environment launcher can have a separate Python worker: for the background verification instance, read `worker_pid` in ignored `service-smoke.json` and confirm that it owns loopback port `8010` and runs `-m gate_a` before stopping that PID. Its `service_pid` records the launcher. Stop PostgreSQL with:

```powershell
& 'data/gate-a-verification/runtime/pgsql/bin/pg_ctl.exe' -D (Resolve-Path 'data/gate-a-verification/cluster').Path -m fast -w stop
```

No upload, supplied PDF processing, extraction, catalog/matching, review workflow/UI, cart/order action, OpenAI/Apple/Qwen request, AWS resource, or training has been implemented or exercised by this gate. Apple privacy architecture remains deferred to Milestone 2.
