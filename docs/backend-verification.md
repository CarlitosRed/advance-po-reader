# Local backend verification, October 2, 2026

This records local implemented behavior separately from provider performance. The full workflow and activation boundaries are in [local-backend.md](local-backend.md). Source changes live in the dedicated `codex/local-backend-preparation` worktree; Gate A remains a separate checkpoint/service. No source push, external provider request, credential creation/import, private corpus copy, training, website or deployment was performed.

## Executed tests

| Check | Actual result | Interpretation |
| --- | --- | --- |
| `scripts/test-backend.ps1` backend suite | **221 passed**, no skips or warnings, 9.36 seconds | Contract, provider mocks, actual decode/security, evaluation, later live-command mocks, real PostgreSQL/API/catalog/concurrency/review behavior. |
| Same script, preserved Gate A suite | **135 passed**, no skips or warnings, 2.33 seconds | Independent original health/configuration, tenant migration and envelope/state checks on a separate test DB. |
| Bundled base Python `-m unittest discover -s tests -q` | **101 reported, 9 skipped**, no failures, 2.426 seconds | Legacy comparison regression discovery; skips identify unavailable private fixtures. No real inference/provider ran. |
| Backend `pip check` | No broken requirements | Isolated Python 3.12 environment. |
| Backend Alembic `current` | `0003_provider_receipt (head)` | Actual native PostgreSQL database `gate_a_backend_dev`. |
| Backend Alembic `check` | No new upgrade operations | Schema and metadata agree, including optional trigram indexes. |
| Catalog test migration round trip | `0002 → 0001 → 0002`, then additive `0003` | Executed only on its isolated test database; did not downgrade service history. |
| `git diff --check` | Passed | Source whitespace check. |

The legacy suite was initially invoked in `.venv-backend` and correctly failed imports for its absent `pdfplumber`, `pypdf` and `pypdfium2` dependencies. It passed using the existing bundled base runtime. Those legacy dependencies were not added to the independent backend lock file; application startup does not depend on the legacy pipeline.

Tests use synthetic documents and separate local databases: `gate_a_test_backend_api`, `gate_a_test_backend_catalog`, `gate_a_test_backend_contract` and `gate_a_test_backend_gate_a`. Agent fixture/storage paths are separate ignored directories inside this worktree. Unit tests exercise the fixed Responses endpoint only through injected mock transports. Real PostgreSQL tests exercise compound scope foreign keys, immutable source/history guards, bounded exact/alias/normalized/trigram lookup, concurrent retry/cancellation, committed uncertain attempt states and append-only reviewer events.

## Live local smoke

The final backend serves loopback `http://127.0.0.1:8012`, using `gate_a_backend_dev` at PostgreSQL `127.0.0.1:55433`. Actual requests verified liveness, migrated readiness, safe configuration, schema routes, interactive API documentation and typed OpenAPI. OpenAPI has **19 paths and 35 component schemas**; the live specification was compared with `create_app().openapi()`. A tracked static specification is in `contracts/local-backend-openapi.json`. It describes the local-token security scheme, explicit tenant/idempotency headers and typed extraction/result/review models.

Both original Gate A endpoints at `http://127.0.0.1:8010/health/live` and `/health/ready` still returned HTTP 200. Its running service, PostgreSQL cluster/runtime and `gate_a_service` database were left intact.

The final synthetic demo ID is `a5d41a2353f647ef9813e42f50564359`. Actual HTTP and database paths completed:

1. Create a unique synthetic tenant/vendor and import two fictional products plus an explicitly supplied alias.
2. Generate valid deterministic one-page PDF and PNG documents, decode/validate and store private opaque sources.
3. Retry upload/run keys without creating extra work; reject changed payloads with HTTP 409.
4. Process each PO through the explicit hash-gated fixture provider; retrieve unchanged raw observations, separate decimal parses and bounded review-only candidate snapshots.
5. Record named synthetic approval of every product, acknowledgement of shipping/total rows, and explicit review resolution. Original extraction remained identical after review.
6. Create a separate default OpenAI run returning `provider_not_configured` with no extraction/attempt and no model substitution.
7. Process an unsupported invoice fixture, retain classification evidence and stop before matching.

Private reports are `output/backend-demo/workflow-evidence.json` and `evaluation.json`. They retain all four cases, including two intentional failure cases, in applicable denominators. Their stated interpretation is synthetic workflow verification; their rates are not real extraction/matching accuracy, held-out evaluation or production thresholds. External provider attempts and spend were zero.

Ignored `output/backend-verification/runtime.json` contains the verified worker PID, UTC verification timestamp, database/revision and smoke responses. Confirm the current process/port before using a saved PID; it is not a persistent service registration.

## Inspected adjacent work and remaining verification

Read **Create VLM training dataset**, its separate source-database guide and the two staging SQLite table lists through read-only access. The evidence database's `approved_training_examples` view returned **0**; the catalog database's tenant-assignment table returned **0**. No annotations/catalog rows/PDF bytes were imported into this branch. Existing staging integrity claims were not rerun here and remain evidence from that workstream.

The backend is ready for later local website integration and source-authorized real testing. The OpenAI adapter is implemented and mock-tested; actual key/account/model access, live strict-schema acceptance, provider retention choices, real PDF transcription/match quality, realized cost and a frozen reviewed evaluation set remain unverified. The optional later command requires affirmative source-specific authorization plus configured and explicitly enabled server state. The local header/token convention is not production authentication. No hosted/AWS, Apple, Qwen, training, automated acceptance or cart/order behavior is implemented.
