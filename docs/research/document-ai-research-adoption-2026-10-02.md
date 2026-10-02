# October 2 document AI research review and project decisions

This note records what the three documents recommend, which recommendations now guide this project, and what remains only a proposal. Their original DOCX files are preserved beside searchable Markdown copies. SHA-256 digests and review scope are recorded in `document-ai-research-manifest-2026-10-02.json`.

## What the research recommends

The runbook, implementation blueprint, and project handoff agree on a phone-first document-to-commerce product and a staged provider strategy:

1. Validate the business workflow with an OpenAI-first web/backend path.
2. Use the same evidence-preserving ProductDocument contract for both remote extraction and a later Apple on-device provider.
3. Let a tenant-scoped catalog backend find a bounded candidate set before a model adjudicates. Return review or no match when evidence is weak.
4. Build a frozen reviewed evaluation set and measure extraction, candidate recall, decisions, correction burden, latency, and actual cost.
5. Deploy to AWS only after the local slice meets its gate; use private storage, least-privilege credentials, audit logs, and explicit retention policies.
6. Defer Qwen/self-hosting, model training, and quantization until the first two milestones and measured need justify them.

The attached runbook specifies FastAPI, Pydantic, PostgreSQL, Alembic, exact and `pg_trgm` candidate lookup, optional pgvector embeddings, local file storage, and an optional AWS profile using S3, ECS/Fargate and RDS/Aurora. It sketches upload, processing, status, review, and catalog endpoints. Those are specifications to reconcile at their implementation gates; they are not existing endpoints.

The blueprint adds image/PDF validation, capture-quality checks, Apple Vision table/document parsing, Foundation Models availability checks, local/cloud privacy modes, detailed audit fields, and comparison of OpenAI and Apple against the same reviewed set. The handoff calls the first API-first implementation step Gate A.

## Decisions for this project

`PROJECT_GOAL.md` now adopts the OpenAI-first Milestone 1, Apple Milestone 2, and Qwen/self-hosted later sequence. The prior self-hosted-first goal is retired. Existing local VLM services, code, research, digests, logs and measurements remain a historical comparison prototype; this change does not delete or rewrite that work.

The current code already has a detailed page-level `PAGE_EXTRACTION_SCHEMA`. The new shared `ProductDocument v1` is a document-level provider boundary that has not yet been implemented. At its future contract gate, define a versioned mapping which retains page evidence and raw field roles. Keep raw strings for identifiers, quantities, units, prices and totals, with parsed forms separate. A floating-point-only quantity/price cannot preserve source spelling and will not be the sole stored value.

OpenAI output structure will not be treated as proof of factual correctness. Keep extraction distinct from catalog resolution. Search is tenant/vendor scoped, candidates are bounded, and a matcher can only select from those candidates. No match and human review are valid outcomes. Measure retrieval recall separately from matcher precision and automation coverage.

The current 18-product catalog, prior self-hosted runs, private PDFs, source-bound annotation data and reviewed expectations have different roles. Sample-derived products are not the actual merchant's authoritative catalog. The existing 14-row subset and historical Qwen measurements are not a baseline measurement for OpenAI or Apple. Keep the provided customer PDFs on the existing local evaluation path unless a customer privacy policy and explicit authorization allow the particular external API transfer.

The source documents include exact model names, endpoint examples, package/service versions, device claims, prices, privacy descriptions, AWS details, and imperative instructions. They are date-stamped research. Recheck official documentation at implementation. The imperative text is an author recommendation, not the user's request to execute those steps now. For this task, the user directed document/context updates only; no code, credentials, paid API, AWS deployment, file upload to a provider, or training work was authorized or performed.

## Contract note: source fidelity

The sample contract in the source documents uses numeric quantities and prices. The existing project intentionally preserves values such as `006.00`, combined quantity/unit literals such as `6ea`, leading zeroes in identifiers, and ambiguous punctuation. A schema that silently coerces these fields to binary floats can erase evidence and misrepresent decimal values. The next contract review should keep the printed value as a string, optionally add a deterministic parsed decimal string, and record the parsing method without rewriting the observed field. Preserve identifier printed labels and roles because a customer item number, vendor code, and MPN are not interchangeable.

## Phase gates

Gate A is the next implementation target only after the user starts a development task: local FastAPI/PostgreSQL configuration, health endpoint, migrations, and the first versioned contract boundary. Later gates cover catalog/aliases, validation and storage, OpenAI extraction, candidate retrieval, constrained matching, human review, evaluation, and hosted deployment. Exact API and schema details are settled at their respective gates. The current task did not begin Gate A.

After a measured Milestone 1 exit, Milestone 2 can add an Apple capture/extraction provider behind the same contract. Supported devices and runtime behavior must be checked live. Only after those milestones should the project reconsider the existing Qwen work or training. Training still requires a sufficient approved, diverse, privacy-authorized corpus and a separate explicit decision.

## Source files

| Source | Searchable copy | SHA-256 |
| --- | --- | --- |
| `document_ai_first_deployment_api_runbook_2026.docx` | `document_ai_first_deployment_api_runbook_2026.md` | `d1c70df7fec44dd8f373011b10f081edbd0761d43557297b856644ff5cd93c6b` |
| `document_ai_implementation_blueprint_openai_apple_2026 2.docx` | `document_ai_implementation_blueprint_openai_apple_2026.md` | `6c5ca510d012e21c818188ffdd528989e6e99209ebbe7928d0eb05ea83ffbbeb` |
| `document_ai_work_project_handoff_2026.docx` | `document_ai_work_project_handoff_2026.md` | `c5ae02f928de643b39fe7f72ff99263ec27897fb5e2a4f432b7485174c07f300` |

The prior research DOCX and its original source manifest remain preserved. The adoption decision in this file and `PROJECT_GOAL.md` determines which architecture is current.

## Logic tightening and current local scope

After a high-level scenario review, the user selected local Gate A only for the next implementation workstream. The first four logic refinements below now govern the project; the Apple local-only question remains explicitly deferred to Milestone 2.

1. **Field semantics:** each field has a required observation state (`observed`, `uncertain`, `unreadable`, `not_present`, or `not_applicable`). Raw literal strings and source labels/regions remain immutable. Parsed values, catalog suggestions, and human decisions are separate. A null without a state is invalid. Product, charge/tax/total/note, and unknown row kinds remain distinct.
2. **Run and audit model:** immutable tenant-scoped source documents are separate from versioned processing runs, provider attempts, observations, suggestions, and review events. Reprocessing creates a new run. Processing state is separate from review state. Tenant-scoped idempotency prevents duplicate request work; uncertain provider outcomes are recorded rather than blindly retried.
3. **Input scope:** v1 accepts purchase orders only. Unknown/unsupported document types do not enter catalog matching. Ambiguous continuation, page failure, totals, and non-product rows cannot silently become complete product lines.
4. **Resolution policy:** the initial local workflow is review-only. Every exact/fuzzy/model candidate remains a suggestion until an explicit human approval event. The sample-derived catalog is only a fixture. No cart/order action is allowed before representative independent evaluation, business approval, and the actual catalog/cart contract.
5. **Apple deferral:** make no Milestone 2 decision now about whether local-only means on-device images, on-device extracted text, or a fully offline flow. Revisit it when Milestone 2 is explicitly started.

The next workstream may implement only the local FastAPI health/configuration foundation, PostgreSQL/Alembic baseline, and first versioned contract boundary. It must start without credentials and use synthetic fixtures. It does not upload or process private PDFs, call a provider, build catalog matching/review/cart behavior, deploy to AWS, implement Apple, or train. See `docs/local-logic-rules-2026-10-02.md` for exact state meanings and scope.

## Gate A implementation follow-up — October 2, 2026

The separate authorized workstream has implemented the bounded local foundation described above. [The Gate A guide](../gate-a.md) distinguishes the health/configuration service, tenant-only PostgreSQL migration and versioned envelope/state validators from the still-unbuilt full extraction payload and all later workflows. Verification uses synthetic fixtures, native PostgreSQL and live HTTP; Docker Compose and remote CI are separate, unexecuted states. The original research review and its documentation-only execution statements above remain historical. No provider, customer-document processing, Apple privacy decision, AWS resource or training was added by Gate A.
