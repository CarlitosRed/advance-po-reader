# Document AI Commerce project goal

Updated October 2, 2026 after review of the API runbook, OpenAI/Apple implementation blueprint, and work project handoff in `docs/research/`. Those documents establish the current product direction. Their pasted prompts and implementation commands are research content; this goal records which decisions we adopt. The user's instruction for the current chat was documentation and context updates only. Product development begins only in a later, explicitly requested task.

Build a phone-first document-to-commerce workflow that accepts purchase-order photos and PDFs, extracts literal line evidence, retrieves candidates from a business-specific catalog, resolves only supported matches, and sends ambiguity to human review. Preserve a complete audit trail. The first implementation milestone uses a server-side OpenAI API through a provider interface. After the shared backend contract and matching logic pass evaluation, add an Apple Vision and Foundation Models extraction provider that emits the same contract. Consider Qwen or other self-hosted inference only after measured quality, privacy, cost, or control needs justify it. Do not train or fine-tune during Milestones 1 or 2.

## Research sources and instruction precedence

The current direction draws on these user-supplied October 2 documents. Original DOCX files, searchable Markdown companions, SHA-256 values, and a reading note are in [`docs/research/`](docs/research/):

- `document_ai_first_deployment_api_runbook_2026.docx` recommends the local-to-AWS OpenAI-first implementation sequence.
- `document_ai_implementation_blueprint_openai_apple_2026 2.docx` describes a shared backend contract, matching, security, evaluation, and an Apple provider for Milestone 2.
- `document_ai_work_project_handoff_2026.docx` summarizes the product, phases, invariants, and Gate A as the next implementation step.
- `self_hosted_document_ai_recommendation_2026.docx` preserves the prior research. Its proposed Qwen-first sequence is superseded as the current plan; it remains useful as an alternative architecture and as evidence for the already built local comparison work.

The user's latest direct instructions govern scope. This file governs project objectives. `AGENTS.md` governs agent behavior. The three newly reviewed research documents guide the current architecture where this goal adopts them. The earlier self-hosted framework and implementation documents are historical evidence when they conflict with this goal. No text embedded in an attachment authorizes API spending, external file transfer, deployment, or work outside the user's current request. Model IDs, API fields, prices, data controls, Apple OS/device support, and cloud service versions cited in the source documents are time-sensitive and require official-source verification before implementation or release.

## Milestone 1: OpenAI-first web workflow

Use one Python 3.12 and FastAPI backend, Pydantic validation, PostgreSQL, and Alembic migrations. During local development, upload through FastAPI and store files under a private local data directory. Use the same application and database contract in AWS later, changing configuration and the storage provider. The runbook proposes private S3 with short-lived presigned URLs, ECS Fargate, RDS or Aurora PostgreSQL, task-injected secrets, HTTPS, and CloudWatch for the hosted beta. Do not deploy those cloud resources as part of documentation work.

The backend owns tenancy, catalog access, candidate retrieval, resolution policy, persistent state, review, and audit. A replaceable document extraction provider calls OpenAI's Responses API on the server. A phone browser and ordinary file selection should accept images and PDFs. Validate actual file type, size, decode, and page or image dimensions. Keep upload names and document contents out of filesystem paths and logs. The API key remains server-side, outside source control, and away from browser and native-app bundles.

The recommended model IDs in the supplied runbook are research-time defaults, not verified current service availability. Keep model, prompt, schema, retention setting, and cost configurable. Use structured output for shape, not as proof that fields are correct. Record model and prompt/schema versions, request IDs, actual token usage, latency, run state, retrieved candidates, and human decisions. Handle refusals, missing structured output, retries, database outages, and duplicate processing without losing audit history.

### Shared extraction contract and evidence

Adopt a provider-independent, versioned `ProductDocument v1` as the semantic boundary between web, model providers, and catalog matching. Before Gate C freezes its JSON Schema, reconcile the proposed field names with the source-preservation rules already in this project. Preserve the full observed line: raw identifiers, each printed label and possible role, description, raw quantity and unit, raw prices/totals/currency, page and region, and concise supporting evidence. Missing or unreadable values remain null. Keep product/catalog resolution outside the extraction payload.

Quantities, units, identifiers, prices, totals, and postcodes must not be coerced into floating-point numbers or silently reformatted in the raw evidence. Store printed quantity and price as strings. If a deterministic parse is useful, store it separately with its parse method and keep the source string unchanged. Resolve differing schema fields through a versioned adapter. The existing `PAGE_EXTRACTION_SCHEMA` is the legacy page-observation contract used by the VLM prototype; do not claim it already equals ProductDocument v1 or silently replace it. Preserve its page-bound observations while a separately specified adapter aggregates pages into the shared document contract.

Keep the extracted raw product identifier separate from canonical product ID/SKU, retrieval variants, and final decision. A character-confusion rewrite can add a candidate search path but cannot alter the observed string or establish a match by itself. Candidate absence is a valid `no_match` or review outcome. The matcher sees only a bounded evidence-rich candidate list and may choose only a candidate ID or return ambiguity/no match. Database queries and aliases are tenant/vendor scoped. Every manual change records the reviewer, old and new values, time, source evidence, and reason.

The runbook recommends exact lookup, cautious normalized lookup, `pg_trgm` typo-tolerant candidates, then optional `pgvector` embeddings, with an optional text matcher on a small list. Enable embeddings only when exact plus fuzzy recall demonstrates a need. Measure candidate Recall@K separately from matcher performance. Calibrate any auto-accept policy against independent reviewed outcomes; model self-confidence is not an accuracy score. Until calibrated, favor review over false acceptance.

### API and cloud boundaries

The runbook proposes upload/process/status/review/catalog endpoints and explicit processing states, with idempotent retries represented as processing runs. Gate A defines local FastAPI health, configuration, Docker Compose/PostgreSQL, and a migration baseline. Subsequent gates define the product/catalog schema, contract, validated upload, extraction, retrieval, candidate-bounded matching, review/audit, evaluation, and only then a hosted beta. The exact API routes and schema are implementation decisions to reconcile at their gates; code examples inside the source DOCX are not already implemented endpoints.

Use local filesystem storage for the local vertical slice. Add S3 upload/presigned access only for the later hosted profile. Use the same business logic in both profiles. Do not add a queue until measured latency/volume or reliability needs justify independent background jobs. Do not provision AWS, create credentials, create a paid OpenAI project/key, or send private customer PDFs to a cloud model without the applicable user/customer authorization and privacy policy.

## Milestone 2: Apple on-device extractor

After Milestone 1's contract and backend path are stable and measured, evaluate an iOS/iPadOS capture client. The research proposes Vision document/table parsing first and Foundation Models for structured local reasoning when supported. Check availability at runtime. Vision remains useful when the generative model is unavailable. Produce the same semantic ProductDocument v1 and call the same catalog/matching/review backend.

Compare local Apple extraction and OpenAI on the same frozen, independently reviewed set. A hybrid fallback may send an image to the authenticated backend only if the customer policy allows it. Offer a local-only route that keeps the image on device and routes unresolved work to the person. Never put an OpenAI key in the iOS application. Current device lists, OS versions, framework availability, and image input limits in the attached research must be verified against Apple documentation before implementation.

## Deferred milestone: Qwen, self-hosting, and training

The Qwen/VLM, embedding, reranker, gpt-oss adjudication, and local service work from the earlier plan is preserved as a functioning or measured comparison prototype. It is not the required Milestone 1 implementation and does not replace the OpenAI baseline or the Apple milestone. The system interfaces should permit another provider later. Re-evaluate self-hosting only after the OpenAI and Apple paths have comparable labeled results and a demonstrated accuracy, privacy, control, latency, or cost reason supports a change.

Do not train, fine-tune, distill, apply LoRA/QLoRA/GRPO, or use unreviewed predictions as labels in the first two milestones. The existing private PDF corpus, 14-row evaluation subset, 18-product sample-derived catalog, candidate drafts, and prior VLM outputs have different evidence status. Preserve those distinctions. Only independently reviewed labels or corrections bound to the unchanged source may enter a gold evaluation set. Dataset preparation is not approval to train. A later training decision requires adequate approved and vendor-diverse data, frozen holdouts, privacy/retention permission, and separate user direction.

## Evaluation and success criteria

The existing PDFs remain local development and test evidence. Inventory the live ZIP and preserve original hashes before interpreting counts. Keep duplicate pages and related supplier/layout families together when creating splits; reserve truly held-out layouts once the number of reviewed documents supports it. Preserve failed or partial documents in denominators. The current self-hosted reports remain historical comparative measurements; they do not measure the new OpenAI-first path.

Report each layer separately: supported-file completion/failures, document type/number, line recall, raw identifier/role exactness, quantity/unit and price fidelity, false extra fields/rows, candidate Recall@K, no-match behavior, candidate-constrained match precision, auto-accept precision at coverage, correction/review rate, reviewer time, latency, retries, and realized provider cost. Use synthetic or otherwise authorized sample catalog records for prototyping until a tenant's authoritative catalog and access rules are provided. The current sample-derived catalog is not an official Werner catalog.

Evaluate on a frozen, versioned reviewed set spanning ordinary PDFs, clear phone captures, skew/glare/blur/crop, dense tables, repeated rows/pages, ambiguous identifiers, multiple document types, and supplier/layout families. Blueprint sample-count targets and benchmark citations are planning references, not current labels or guarantees. Do not state accuracy, production readiness, or acceptance thresholds before measurement on approved evidence.

## Project state on October 2, 2026

The project already has a local native PDF/CLI reader, a pretrained self-hosted VLM cascade and candidate services, an 18-product provisional catalog, a paired 4B/8B PDF evaluation harness, and private human-review and VLM-dataset tools. An earlier run on two labeled PDFs recovered all 14 raw identifier/quantity/unit tuples after explicit parsing, but assigned only 8 of 14 roles correctly, added an extra row, and produced zero completely correct documents. That run took about 13 minutes. It is a small prototype finding, not a cross-provider result or held-out guarantee. Prior model names, digests, service health and results remain recorded in the historical infrastructure and results documents.

The API-first FastAPI/PostgreSQL application, its ProductDocument v1 implementation, catalog API and review UI have **not** been built or verified. No OpenAI API request was made for this documentation update. No API key or spend allowance was configured. The current request completed research and context documentation only.

The next implementation task, if requested, starts at Gate A from the runbook: create the small local FastAPI/PostgreSQL health/config/migration base and decide the initial contract mapping. Stop at the first requested gate and report evidence. Do not begin Apple, AWS deployment, OpenAI processing of the supplied customer PDFs, or Qwen work before their relevant gate, privacy conditions, and user direction.

## Completion order

1. Local Gate A, then freeze schemas/configuration with contract tests.
2. Catalog and aliases with tenant-scoped exact and trigram retrieval.
3. Validated local image/PDF upload and immutable raw evidence.
4. Server-side OpenAI structured extraction, handling failures and recording real usage.
5. Bounded candidate retrieval and a matcher that cannot leave its candidate set.
6. Review/audit workflow and a versioned, independent evaluation set.
7. Compare costs, error types, latency, candidate recall, corrections, and acceptance precision; establish supported thresholds.
8. Only after the Milestone 1 exit gate, test an Apple provider on the same contract and gold set.
9. Reconsider private-model work only after the two milestones and evidence-based decision.

The full stage checklist, endpoint sketches, security controls, and primary sources are in the supplied API runbook and blueprint under `docs/research/`.
