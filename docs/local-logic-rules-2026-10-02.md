# Local logic rules and Gate A boundary

Updated October 2, 2026 from the high-level logic review. This document resolves the first four tightening rules for local development and explicitly defers the Apple privacy promise to Milestone 2. `PROJECT_GOAL.md` remains the project objective; `AGENTS.md` governs implementation behavior. The active next workstream is Gate A only.

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

## Current Gate A scope

Implement only the local FastAPI health/configuration foundation, local PostgreSQL/Alembic baseline, and the first versioned contract boundary. It must start without OpenAI credentials or external services. Add focused tests for configuration, liveness/readiness, database/migration behavior, and contract state validation. Use synthetic test fixtures only. No upload endpoint, supplied PDF processing, extractor, catalog, matcher, review UI, cart, provider request, AWS, Apple, Qwen inference, or training belongs in Gate A.
