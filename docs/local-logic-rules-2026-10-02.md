> Active scope, October 2, 2026: Carlos authorized secure server API configuration and the first local live PDF demo. OrderLens has a seven-day key in the ignored backend environment. After a computer crash, the existing PostgreSQL cluster and website on port 8014 were recovered. One saved, human-authorized library PDF was processed once with OpenAI against the user-selected WernerCo namespace. The provider attempt succeeded; the run remains partial and requires human review. Automatic retrieval returned no candidate; a separate scoped catalog search found one record for comparison. No product is approved and extraction accuracy has not been measured. Exact source/run references and raw evidence remain private. Human corrections, candidate approvals and review resolution remain in the website. Carlos requested this chat remain focused on the live demo and separate chats handle fixes; see docs/live-demo-continuation.md. Keep the workflow local; no AWS, publication, training, Apple/Qwen, or cart/order action is authorized. Earlier preparation-only limits and deferred-key statements below describe preserved checkpoints. See docs/api-activation-verification.md for current evidence.

# Local logic rules and Gate A boundary

Updated October 2, 2026 from the high-level logic review and subsequent website authorization. This document resolves the first four tightening rules for local development and explicitly defers the Apple privacy promise to Milestone 2. `PROJECT_GOAL.md` remains the project objective; `AGENTS.md` governs implementation behavior. The latest direct user instruction authorizes the local website and real catalog integration after backend preparation, with the key and real extraction later. The user selected one local test workspace with three separately selected catalogs and confirmed the original 33-PDF archive. Historical Gate A limits below describe that checkpoint; they do not override this new authorization. The observation, tenancy, run and review rules remain mandatory.

## 1. Preserve field observations and contract states

Every observed field carries its exact source text, printed label when present, page/region reference, and an observation state. Do not normalize or replace the source string in place.

| State | Meaning | Raw value |
| --- | --- | --- |
| `observed` | A literal reading is supported by the visible source. | Required; preserve its spelling, punctuation, spacing, and leading zeroes. |
| `uncertain` | One or more plausible readings exist, but none is confirmed. | Preserve the best literal reading if available and retain alternatives separately with the same source evidence. |
| `unreadable` | The field/region is present, but no dependable text can be transcribed. | Null; retain the page/region evidence. |
| `not_present` | The document does not contain this field. | Null. |
| `not_applicable` | This field does not apply to this document or row kind. | Null. |

A null without an explicit state is invalid. Raw quantity, unit, price, total, currency, identifier, and postcode remain strings. A parse is a separate value with parse status and method; ambiguous locale separators, unsupported units, and invalid values remain unresolved. Keep extraction observations separate from canonical product IDs, catalog suggestions, reviewer corrections, and final resolution. Preserve every printed identifier and its printed label/possible role. Product-versus-charge/tax/total/note classification is explicit; unknown row kinds go to review.

Gate A may establish the versioned envelope and these semantics. It must not pretend that a document extractor or finalized upload schema exists. Freeze the full extraction payload before implementing a provider or ingestion pipeline.

## 2. Keep source documents, runs, and review history separate

An uploaded source is immutable and tenant-scoped. Store its content hash, byte size, media type, and private storage reference; never use an upload filename as a path or log document contents. A second processing attempt creates a new run linked to that source. A new run must not overwrite earlier observations, suggestions, errors, or review decisions.

Keep document storage state separate from processing-run state and review state:

- Processing run: `created` → `validating` → `processing` → `completed`, `partial`, `failed`, or `cancelled`.
- Human review: `not_started`, `in_progress`, or `resolved`.
- Each provider attempt, where one exists, has its own start/end state, request ID, model and prompt/schema version, usage/cost, latency, and failure/unknown outcome.

Use an idempotency key scoped to the tenant so a retried upload request does not accidentally create duplicate work. A deliberate reprocess is a new run. Preserve the result of each attempt; if a remote attempt times out with an unknown outcome, record that state and avoid blind retries that may duplicate cost. A human correction is an append-only audit event with reviewer, timestamp, old and new values, reason, and source evidence. It never changes the original observation or silently becomes a global catalog rule.

## 3. Support purchase orders only in v1

Version 1 accepts purchase orders as PDFs or photos. An unknown or unsupported document type stops before product/catalog matching and receives an explicit unsupported or needs-classification outcome. Do not reinterpret an invoice, quote, packing slip, or other form as a purchase order by guessing.

Extract line candidates with page and region evidence. Keep product rows distinct from shipping/charge rows, taxes, subtotals, totals, notes, and unknown rows. Do not turn totals or repeated headers into product lines. Do not join a continuation row to a product unless the source evidence supports the relationship. A failed page, unresolved continuation, or ambiguous row makes the run partial/review-required rather than silently complete.

## 4. Keep catalog outcomes review-only in the initial local workflow

Every match from exact, normalized, fuzzy, vector, or model-based retrieval is a **suggestion**. For the initial local workflow, a human must approve every product resolution, including exact identifier hits. Store the suggestion and the final human decision separately. A matcher may select only from the tenant/vendor-scoped candidate set or return `no_match`/`ambiguous`; it cannot create aliases or repair source values.

The sample-derived 18-product catalog is a test fixture, not an authoritative merchant catalog. Tenant identity must scope all future document and catalog reads, aliases, candidates, and writes, even when local Gate A uses one seeded development tenant. Do not expose whether an identifier exists in a different tenant. Do not write to a cart or place an order in this local phase. Revisit automated acceptance only after a frozen, independently reviewed and representative evaluation set supports approved precision/coverage thresholds.

## 5. Defer Apple privacy architecture to Milestone 2

Apple Vision/Foundation Models is explicitly out of Gate A and the current local implementation scope. Do not resolve the earlier “local-only” promise now. At Milestone 2, decide whether it means the source image remains on-device, extracted text also remains on-device, or the entire matching/review path works offline. Reassess any data sent to a backend under the applicable privacy policy and verify current Apple platform capabilities then.

## Historical Gate A scope (completed checkpoint)

Implement only the local FastAPI health/configuration foundation, local PostgreSQL/Alembic baseline, and the first versioned contract boundary. It must start without OpenAI credentials or external services. Add focused tests for configuration, liveness/readiness, database/migration behavior, and contract state validation. Use synthetic test fixtures only. No upload endpoint, supplied PDF processing, extractor, catalog, matcher, review UI, cart, provider request, AWS, Apple, Qwen inference, or training belongs in Gate A.

## Preserved local backend preparation checkpoint

Authorized October 2, 2026: extraction schema freeze, catalog/aliases, private validated upload, immutable sources and reprocessing runs, disabled live provider adapter, bounded review-only suggestions, correction/audit APIs, reproducible synthetic demo and tests. No key work or provider request now. Each later external attempt requires affirmative source-specific privacy authorization; key presence alone is insufficient. Website/UI, AWS, Apple, Qwen, training and cart/order actions remain excluded.

## Current local website and agent preparation

The later direct user request authorizes the local website, three manually
selected real catalogs, original 33-PDF batch and both the document workflow
and scoped Codex tools. Keep originals local and unprocessed until applicable
source-specific authorization and later server key activation. Agents may
prepare a run without authorizing it, process the exact authorized source once,
and read saved outcomes. They cannot approve/correct/resolve human decisions.
The website and agent share the saved review summary and resolution blockers.
New review events use a per-run sequence under the existing lock so clock
changes cannot reorder approvals and corrections; legacy rows remain unchanged.
See [local-agent-demo.md](local-agent-demo.md). All external calls/key work,
training, AWS, Apple/Qwen and cart/order work remain deferred in this phase.
