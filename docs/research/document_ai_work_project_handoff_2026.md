DOCUMENT AI COMMERCE

# Work Project Handoff

OpenAI-first document understanding → product catalog matching → Apple on-device path

Handoff state • 2 October 2026

| Purpose. This document is the continuity packet for a new ChatGPT Work project/chat. It records the project goal, decisions already made, technical architecture, research conclusions, implementation sequence, invariants, and immediate next actions. The new chat should continue from this state rather than redesigning the project from zero. |
| --- |

## 1. Ready-to-paste continuation brief

Paste the following as the first message in the Work chat, then attach this handoff and the implementation blueprint.

| You are continuing an existing Document AI Commerce project. Treat the attached handoff and implementation blueprint as authoritative project context unless new evidence requires a change. <br>  <br> Goal: build a phone-first B2B commerce workflow where a user photographs or uploads a purchase order, receipt, invoice, packing slip, requisition, or similar document; the system extracts literal line-item evidence, maps each line to the correct product in a tenant-specific catalog, and returns an order-ready result with human review for uncertainty. <br>  <br> Implementation sequence is fixed for now: <br> 1) Milestone 1 — build the complete business logic with the OpenAI API first. Do not train custom models yet. <br> 2) Milestone 2 — build a native Apple app that performs as much document extraction as possible on-device with Apple Vision + Foundation Models while emitting the exact same ProductDocument v1 contract. <br> 3) Later only — evaluate Qwen/self-hosted/private inference, quantization and training after we have real data and a measured reason to do so. <br>  <br> Non-negotiable architecture principles: <br> - ProductDocument v1 is the canonical extraction contract. <br> - Preserve raw document evidence; never silently replace a visually read SKU with a catalog SKU. <br> - Catalog resolution is separate from extraction. <br> - The database retrieves candidates; the LLM adjudicates only a small candidate set. <br> - A matcher cannot select a product outside the supplied candidate set. <br> - No candidate is a valid answer; do not force nearest-neighbor matches. <br> - Human corrections and model decisions must be auditable. <br> - OpenAI keys stay server-side; the browser/mobile app never receives the key. <br> - Build the backend so extraction providers are swappable: OpenAI now, Apple local next, Qwen later. <br>  <br> Current next step: begin Milestone 1 Gate A. Create the repo, local FastAPI/PostgreSQL environment, OpenAI project/key handling, ProductDocument v1 Pydantic models, and one endpoint that takes a real phone photo and returns schema-valid extraction. Do not jump ahead to Qwen or training. <br>  <br> When making implementation decisions, preserve this architecture and explain any proposed deviation with evidence. |
| --- |

## 2. Project snapshot

| Working product concept | Document-to-commerce intake for B2B/e-commerce workflows. |
| --- | --- |
| Primary user interaction | Phone-first: take a photo or upload a PDF/image; no requirement to scan a PDF first. |
| Milestone 1 | OpenAI API handles visual/document extraction; backend handles candidate retrieval, matching policy, review and audit. |
| Milestone 2 | Native iPhone/iPad app uses Apple Vision and Apple Foundation Models on-device, then sends ProductDocument JSON to the same backend. |
| Deferred milestone | Qwen/self-hosted/private model, quantization, fine-tuning/training only after real data and measured need. |
| Main engineering language | Python/FastAPI backend; PostgreSQL catalog; Swift/SwiftUI for Apple client later. |
| Core research insight | Retrieve → match → escalate is safer and cheaper than letting one LLM search the entire catalog. |
| Current state | Research and design are complete enough to start coding Milestone 1. |

## 3. Product thesis and why this is compelling

The product is not “AI OCR.” The useful commercial workflow is:

| PHOTO / PDF → literal document evidence → ProductDocument → candidate retrieval → verified product match → review if needed → cart / order / ERP action |
| --- |

The customer should be able to give the system the purchasing artifact they already have instead of manually recreating the order in an e-commerce catalog. In B2B this can remove repeated SKU search and data-entry work from multi-line orders. The phone becomes an input method for commerce, not merely a scanner.

> Product positioning to preserve: “Point your phone at the order you already have; we turn it into a verified catalog order.” Avoid positioning the company as simply an invoice/receipt OCR vendor, because raw document reading is becoming commoditized. The differentiating system is document evidence → merchant-specific catalog understanding → canonical product → business rules → transaction.

## 4. Implementation sequence — do not reorder without evidence

### Milestone 1 — OpenAI-first web MVP

- Build the full end-to-end workflow before any custom-model training.

- Accept phone images and PDFs.

- Use OpenAI vision + Structured Outputs to emit ProductDocument v1.

- Perform deterministic/high-recall candidate retrieval from the catalog.

- Use an OpenAI text/vision model only to adjudicate ambiguous candidates.

- Route uncertainty to human review and record corrections.

- Measure accuracy, candidate recall, review rate, latency and realized API cost.

### Milestone 2 — Apple on-device extraction

- Build a native Swift/SwiftUI iPhone/iPad app after Milestone 1 logic is stable.

- Use Apple Vision RecognizeDocumentsRequest for on-device text/document structure, tables, lists and barcodes.

- On Apple Intelligence-capable devices, test Foundation Models multimodal image reasoning + @Generable typed output.

- Emit the exact same ProductDocument v1 JSON and reuse the existing backend/catalog matcher unchanged.

- Keep a hybrid fallback: local extraction when it passes policy; OpenAI cloud vision when the device/model or document is not good enough.

### Milestone 3 — explicitly deferred

- Evaluate Qwen/open VLMs against the frozen real-world gold set.

- Self-host when privacy, accuracy, control or measured economics justify it.

- Only then consider fine-tuning, distillation, quantization, mobile Qwen/MLX, or customer-VPC deployment.

## 5. Canonical architecture

| CLIENT (browser today / iOS later) <br>         │ <br>         ▼ <br> UPLOAD / CAPTURE <br>         │ <br>         ▼ <br> EXTRACTION PROVIDER <br>    ┌───────────────┬──────────────────────┬───────────────┐ <br>    │ OpenAI API    │ Apple on-device      │ Qwen later    │ <br>    └───────┬───────┴───────────┬──────────┴───────┬───────┘ <br>            └───────────────────┴──────────────────┘ <br>                             │ <br>                             ▼ <br>                   ProductDocument v1 <br>                             │ <br>                             ▼ <br>              deterministic candidate retrieval <br>         exact IDs → fuzzy/trigram → semantic/vector <br>                             │ <br>                             ▼ <br>                      top candidate set <br>                             │ <br>                             ▼ <br>                 matcher / adjudication model <br>                             │ <br>                  ┌──────────┴─────────┐ <br>                  ▼                    ▼ <br>              auto-accept          human review <br>                  │                    │ <br>                  └──────────┬─────────┘ <br>                             ▼ <br>                     approved product line <br>                             │ <br>                             ▼ <br>                      cart/order/ERP |
| --- |

> Provider abstraction is foundational. The commerce application should call an internal extractor interface such as DocumentAI.extract(document). OpenAI-specific code stays inside one provider module. The iOS app later emits the same semantic object. This prevents a model/provider migration from forcing a rewrite of business logic.

## 6. ProductDocument v1 — canonical handoff contract

| { <br>   "schema_version": "1.0", <br>   "document_type": "purchase_order \| receipt \| invoice \| packing_slip \| other", <br>   "supplier": {"raw_name": "...", "raw_id": null}, <br>   "document_number": null, <br>   "currency": "USD", <br>   "items": [ <br>     { <br>       "line_index": 1, <br>       "raw_product_id": "1113", <br>       "raw_description": "3/4 INDUSTRIAL HOSE 10M", <br>       "raw_brand": null, <br>       "quantity": 2, <br>       "unit": "EA", <br>       "unit_price": 18.75, <br>       "line_total": 37.50, <br>       "evidence_text": "1113  3/4 INDUSTRIAL HOSE 10M  2 EA 18.75 37.50", <br>       "quality_flags": [] <br>     } <br>   ], <br>   "document_quality_flags": [] <br> } |
| --- |

### Contract invariants

- raw_* fields represent literal evidence from the source document and are immutable.

- Use null when a value is not visibly supportable; guessing is worse than missing data.

- Extraction does not map a line to the catalog.

- The selected canonical product is stored separately from the raw evidence.

- quality_flags describe observable issues such as cropped, glare, blur, unreadable_id, handwritten or ambiguous_columns.

- Every schema change is versioned.

| Resolution example: <br> { <br>   "raw_product_id": "1113", <br>   "selected_product_id": "product_8f2a", <br>   "canonical_sku": "1112", <br>   "decision": "review", <br>   "decision_source": "llm", <br>   "reasons": ["description and pack size agree"], <br>   "conflicts": ["raw ID differs from canonical SKU by one digit"] <br> } |
| --- |

## 7. Product matching logic

Do not allow an LLM to query the entire catalog and invent the nearest plausible product. The database should generate a high-recall candidate set first.

1. Tenant/vendor-scoped exact match: canonical SKU, vendor SKU, UPC/EAN/GTIN, customer aliases.

1. Normalized exact match: Unicode normalization, case, whitespace and punctuation normalization while preserving original evidence.

1. Typo/OCR-tolerant retrieval: PostgreSQL pg_trgm and cautious candidate expansion for confusions such as 0/O, 1/I/l, 5/S, 8/B. These are candidate-generation hints only, never silent corrections.

1. Semantic retrieval: embeddings over stable product text such as brand + name + variant + pack + description, stored/queryable via pgvector.

1. Union/deduplicate channels and compute deterministic evidence features such as identifier edit distance, brand agreement, pack/unit agreement, vendor compatibility and price plausibility.

1. Send only the top ~5–20 candidates to the LLM matcher. The matcher returns one candidate ID or no_match.

1. Backend validates that the returned ID belongs to the supplied candidate set.

1. Use empirical thresholds to auto-accept only sufficiently reliable matches; otherwise review.

> First-class metric: candidate Recall@K. If the true product never reaches the candidate set, no downstream LLM can recover it. This must be measured separately from matching accuracy.

## 8. Recommended Milestone 1 stack

| Layer | Recommended starting point | Reason |
| --- | --- | --- |
| Frontend | Simple responsive web app; phone camera/file input | Fastest path to validate product behavior before native app work. |
| Backend | Python + FastAPI | Natural fit for OpenAI SDK, validation, async API endpoints and future ML work. |
| Schema validation | Pydantic | Directly maps to OpenAI Structured Outputs and clear typed contracts. |
| Database | PostgreSQL | Transactions, tenant isolation, audit history and catalog data. |
| Fuzzy search | pg_trgm | Cheap typo/identifier/name candidate generation. |
| Semantic search | pgvector + OpenAI embedding initially | Keeps vector retrieval close to catalog data; provider can change later. |
| Object storage | S3 or equivalent | Originals/derivatives with explicit retention policy. |
| Deployment | Local first; small AWS container + RDS/S3 later | No GPU required for API-first MVP. |
| Apple client | Swift/SwiftUI + Vision + FoundationModels | Required to access native on-device Apple capabilities. |

## 9. OpenAI API/deployment context

- ChatGPT Plus and OpenAI API billing are separate. The Plus subscription does not include generic API credits.

- The project can begin with a small prepaid API balance; prior research recommended $5–$10 for prototyping rather than GPU infrastructure.

- Use a dedicated OpenAI project for this app and separate development/staging/production as the system matures.

- API keys must remain server-side. Never embed them in browser JavaScript or a native iOS app.

- Use project/service-account credentials in production, environment variables or a secret manager, key rotation, spend alerts/hard limits, and request-ID/usage logging.

- Use store=false when response persistence is unnecessary, but do not confuse store=false with stronger retention programs such as Zero Data Retention.

- Recheck model names, prices and data controls immediately before production because this area changes quickly.

Model strategy at the time of research: start extraction with a stronger current vision-capable model (the research recommendation was GPT-6.1 Sol), establish the quality baseline, then benchmark cheaper tiers such as Luna on the same frozen dataset. Use a stronger model only for the hard tail if a cheaper model is sufficient for the majority.

## 10. Extraction behavior to preserve

| SYSTEM — Purchasing document extraction <br> You extract evidence from purchasing documents. <br>  <br> 1. Preserve visible identifiers exactly. Never repair, normalize or guess a SKU. <br> 2. Return null when a field is not visible enough to support a value. <br> 3. One source row should become one item unless the layout clearly wraps one row. <br> 4. Do not map extracted items to our product catalog; resolution happens later. <br> 5. Include short evidence_text from the visible row for each item. <br> 6. Mark observable document-quality issues in quality_flags. <br> 7. Do not invent quantity, price, brand, unit or product ID. |
| --- |

## 11. File security, tenancy and audit requirements

- Allowlist file types needed for the product. Validate actual file content, not only extension or Content-Type header.

- Enforce upload size/dimension/page limits; generate storage filenames rather than trusting user-supplied names.

- Treat PDFs/images as untrusted input. Store outside the web root and isolate tenant access.

- For hosted beta, use short-lived presigned uploads rather than proxying large files through the app server where practical.

- Strip unnecessary image metadata from the processing derivative; define whether the original is retained, deleted, or retained only with customer consent.

- Every catalog query is tenant-scoped.

- Persist prompt/model/schema version, extraction result, candidate set, match decision, user correction, timestamps and actor/source for auditability.

- Do not expose raw provider confidence as a claim of accuracy. Use empirical review/correction metrics.

## 12. Evaluation plan and success metrics

Build a frozen gold set early. It should deliberately contain clean scans and difficult phone captures: skew, glare, blur, crop, shadows, tiny print, dense tables, multilingual content, unusual vendor layouts and ambiguous IDs.

| Metric | Why it matters |
| --- | --- |
| Line-item recall | Did the extractor find every source line that should be an item? |
| Field exact match | SKU, quantity, unit, price and document number correctness. |
| Candidate Recall@K | Did retrieval put the true catalog product into the candidate set? |
| Match precision | When the system auto-accepts a product, how often is it right? |
| Automation coverage | What share of lines/documents can auto-resolve at the required precision? |
| Human review rate | Operational burden of the system. |
| Review-to-correction rate | Whether the review queue is catching useful uncertainty instead of wasting time. |
| False-match rate | Especially important: plausible wrong products are more dangerous than no_match. |
| Latency | Capture-to-result and extraction/matching components separately. |
| Realized cost | Per document, line item, approved order and tenant. |

> Operational philosophy: Optimize for high precision and graceful abstention. A no_match/review result is acceptable; a confident wrong product entering an order is not.

## 13. Milestone 2 Apple implementation context

- Apple Vision RecognizeDocumentsRequest provides on-device structured document analysis including text hierarchy, tables, lists and barcodes.

- Foundation Models can accept images and generate constrained Swift structures through @Generable on supported Apple Intelligence devices/software.

- Treat Apple Vision and Apple Foundation Models as distinct availability tiers: Vision document parsing can remain useful even when the generative on-device model is unavailable.

- The app should check model availability and fall back gracefully rather than making Apple Intelligence mandatory.

- Use local capture-quality checks and request a retake before inference when the image is clearly unusable.

- The local extractor must emit the same ProductDocument semantics as the OpenAI extractor.

- Possible privacy mode: send JSON only after local extraction. Cloud-vision fallback requires explicit product policy/consent because the source image leaves the device.

- Evaluate Apple vs OpenAI on the same frozen gold set and ship local extraction only where measured performance is acceptable.

## 14. Data strategy — useful later, not a reason to delay the MVP

Every processed and reviewed document can become structured evaluation/training evidence later. For each example, preserve enough metadata to reconstruct what happened: source document policy reference, extraction output, candidates shown, model decision, human decision, final canonical product and document/quality category.

- Do not promise that every uploaded customer image becomes training data. Retention and model-improvement use must be an explicit product/legal policy.

- If private/on-device mode never uploads images, the system may retain only structured corrections unless the customer opts into an improvement program.

- The future Qwen decision should be based on measured shortcomings or enterprise privacy requirements, not on an assumption that self-hosting is automatically cheaper.

## 15. Backend state machine and initial API surface

| UPLOADED → VALIDATING → READY_FOR_EXTRACTION → EXTRACTING → EXTRACTED <br>          → RETRIEVING_CANDIDATES → MATCHING <br>          → RESOLVED \| REVIEW_REQUIRED \| NO_MATCH \| FAILED <br>          → APPROVED |
| --- |

| POST /v1/documents                 create document + upload instructions <br> POST /v1/documents/{id}/process    extract + retrieve + match <br> GET  /v1/documents/{id}            state/result <br> GET  /v1/documents/{id}/review     review payload <br> POST /v1/lines/{id}/resolve        human decision <br> POST /v1/match                     accept ProductDocument from iOS local extractor <br> GET  /v1/products/search           manual candidate search |
| --- |

## 16. Immediate next actions — resume here

1.  Create a repository with backend/, frontend/, tests/, docs/ and migrations/ directories.

2.  Create a local Python environment and FastAPI app with health endpoint.

3.  Start PostgreSQL locally (Docker is fine) and enable pg_trgm; pgvector can be added in the same initial setup or immediately after exact/fuzzy matching works.

4.  Create Pydantic ProductDocument v1 and ProductLine models plus JSON serialization tests.

5.  Create a dedicated OpenAI API project/key and load the key from the server environment only. Set a very low prototype spend limit/alert.

6.  Implement the OpenAIExtractor provider with one photo input and Structured Outputs.

7.  Test one real phone photograph end-to-end and persist the raw extraction result.

8.  Load a small synthetic/sample catalog and implement exact + trigram candidate retrieval.

9.  Implement candidate-constrained matcher and enforce “candidate ID or no_match” in backend validation.

10.  Build a minimal review screen showing the original image, raw line, selected product, reasons/conflicts and correction action.

11.  Only after this vertical slice works should we add PDFs, presigned S3 uploads, embeddings, deployment and broader test documents.

> Definition of the first real success: Take a phone photo of a purchasing document, submit it through our own interface, receive schema-valid literal line-item evidence, retrieve a candidate set from our own catalog, resolve one line to the correct product or deliberately return review/no_match, and persist the complete audit trail.

## 17. Decisions already made — do not repeatedly reopen

- Do not start by training Donut, LayoutLM, Qwen or any other model.

- Do not build a GPU server for the MVP.

- Do not use classical OCR as the only document-understanding strategy.

- Do not make the LLM search the full product database.

- Do not silently “correct” raw document identifiers.

- Do not optimize API cost before measuring accuracy on real documents.

- Do not build iOS first; prove the backend and commerce logic with the web/OpenAI implementation.

- Do not make the Apple app a separate backend architecture; it must reuse the same schema and matching API.

- Do not assume local/self-hosted is cheaper; evaluate based on real throughput, privacy and accuracy.

## 18. Open questions the Work project is allowed to resolve

- Exact frontend framework for the web MVP (plain HTML/JS, React/Next.js, etc.). Optimize for speed of implementation, not ideology.

- Exact AWS hosting choice for first public beta (ECS/Fargate, App Runner, Lambda-compatible pattern, etc.) after the local vertical slice works.

- Exact OpenAI model selected at each routing stage, based on current model availability and measured quality/cost.

- Exact candidate score fusion and review thresholds; these must be calibrated on real labeled examples.

- Whether to retain source images and for how long; this depends on privacy/customer requirements and future improvement consent.

- Which commerce/ERP connector becomes the first transaction target after matching works.

- Whether the Apple app sends only JSON by default or offers configurable cloud fallback, depending on the target customer/privacy tier.

## 19. Existing artifacts to bring into the Work project

- document_ai_implementation_blueprint_openai_apple_2026.docx — detailed 19-page implementation blueprint; attach this alongside the handoff.

- document_ai_two_milestone_implementation_research_2026.docx — earlier two-milestone technical research document, if available.

- document_ai_commerce_master_research_reference_2026.docx — API-first economics/research reference, if available.

- This handoff file — authoritative continuation state and immediate next action list.

## 20. Research anchors

- OpenAI — Images and vision

- OpenAI — Structured Outputs

- OpenAI — File/PDF inputs

- OpenAI — Production best practices

- OpenAI — Your data

- OpenAI — Pricing

- OpenAI — Embeddings

- Apple — RecognizeDocumentsRequest

- Apple WWDC25 — Read documents using Vision

- Apple — Multimodal Foundation Models

- Apple — App privacy

- ReceiptBench — ACL 2026

- Retrieve, Match, Escalate — 2026

- PostgreSQL pg_trgm

- pgvector

- OWASP File Upload Cheat Sheet

## 21. Final instruction to the receiving Work chat

> Continue, do not restart. The research phase has already established the product architecture. The receiving Work chat should now behave like the implementation lead: preserve the contract and invariants, challenge details only when new evidence warrants it, and move the project through Milestone 1 one executable gate at a time. The first deliverable is not another research report; it is a working local vertical slice.
# Source document

Searchable text extracted in document order from the user-provided DOCX. The original file sits beside this companion. Its pasted continuation prompt is an author-authored project instruction, not a separate user message; the user's current request for this turn authorized documentation updates only. Adopted project direction and schema-safety notes are in [the review/adoption note](document-ai-research-adoption-2026-10-02.md).
