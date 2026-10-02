Document AI Commerce
Implementation Blueprint
OpenAI-first web deployment → Apple on-device extraction

Deep research edition • 2 October 2026

| Scope: build Milestone 1 completely before training or self-hosting anything. Then implement Milestone 2 as a new extraction provider that produces the same contract. Qwen, quantization and fine-tuning are explicitly deferred. |
| --- |

Research basis: 29 targeted deep-search workstreams (232 search-result slots) plus primary-source verification across OpenAI, Apple, AWS, PostgreSQL/pgvector, MDN, OWASP and 2026 academic work.

## 1. Executive decision

The recommended implementation is a provider-agnostic document-to-commerce system. The business backend owns the catalog, candidate retrieval, matching policy, audit trail and review workflow. A document extractor is merely a replaceable provider. Milestone 1 uses OpenAI; Milestone 2 adds Apple on-device extraction. Both emit the same ProductDocument v1 payload.

| Core design rule: preserve what the document actually said. Never replace raw extracted evidence with the corrected catalog value. Store raw_product_id and canonical_product_id separately. |
| --- |

| Layer | Milestone 1 choice | Milestone 2 change |
| --- | --- | --- |
| Capture | Mobile web photo / PDF | Native iPhone/iPad camera + VisionKit/AVFoundation |
| Document understanding | OpenAI Responses API | Apple Vision + Foundation Models when available |
| Canonical contract | ProductDocument v1 JSON Schema | Unchanged |
| Catalog retrieval | PostgreSQL exact + pg_trgm + pgvector | Unchanged |
| Ambiguous matching | OpenAI sees only top candidates | Unchanged initially |
| Human review | Web review UI | Web or native review UI |
| Training/self-hosting | Not in scope | Still not in scope until after Milestone 2 evaluation |

### Why this sequence is the lowest-risk path

- OpenAI lets us validate the hard product question first: can arbitrary photos/PDFs be converted into correct catalog products with acceptable precision?

- The first useful proprietary asset is not a trained model; it is an evaluation corpus containing documents, extracted fields, candidate sets, final product decisions and human corrections.

- Apple local intelligence should be evaluated only after the backend contract and matching behavior are stable; otherwise model differences and business-logic bugs get mixed together.

- The 2026 product-linking literature independently supports a retrieve → match → escalate cascade rather than asking one large model to search an entire catalog [R1].

- ReceiptBench separates document automation into perception, normalization, semantic reasoning and structure parsing; this is exactly why extraction and product resolution should remain separate stages [R2].

## 2. Document map

| Sec. | Purpose | Sec. | Purpose |
| --- | --- | --- | --- |
| 3 | Scope + success criteria | 13 | Milestone 1 build + exit gate |
| 4 | Canonical data contract | 14 | Apple native architecture |
| 5 | Milestone 1 architecture | 15 | Apple Vision implementation |
| 6 | OpenAI implementation | 16 | Apple Foundation Models |
| 7 | Catalog retrieval + matching | 17 | Fallback + privacy modes |
| 8 | Database design | 18 | Apple evaluation + exit gate |
| 9 | Web UX + mobile capture | 19 | Operational economics |
| 10 | Security + auditability | 20 | Explicitly deferred work |
| 11 | Testing + evaluation | 21 | Reference code snippets |
| 12 | Deployment path | 22 | Source register |

## 3. Scope, assumptions and success criteria

### 3.1 Business problem

A user should be able to photograph a purchase order, receipt, packing slip, handwritten/printed requisition, or upload a PDF. The system extracts line items, finds the corresponding products in a business-specific catalog, and returns an order-ready result with explicit review for uncertain lines.

### 3.2 Non-goals for the first two milestones

- No custom model training, fine-tuning, distillation or quantization.

- No self-hosted Qwen inference service.

- No attempt to eliminate human review before empirical calibration.

- No claim that model self-confidence is equivalent to correctness.

- No destructive normalization of source evidence.

### 3.3 Chosen technical stack

| Component | Recommended implementation | Reason |
| --- | --- | --- |
| Backend | Python + FastAPI + Pydantic + SQLAlchemy | Matches existing Python skillset; strong typed contracts; native async HTTP. |
| MVP web UI | FastAPI/Jinja + small vanilla JS or HTMX layer | One deployable service; enough for upload/review; can later be replaced by React without backend changes. |
| Database | PostgreSQL + pg_trgm + pgvector | Exact, fuzzy and semantic retrieval in one transactional store. |
| File store | Local filesystem in dev; private S3 in hosted environment | Cheap object storage; presigned uploads later avoid proxying large files. |
| OpenAI | Responses API + Structured Outputs | Image/PDF understanding plus schema-constrained output [O1–O3]. |
| Apple | SwiftUI + AVFoundation/VisionKit + Vision + Foundation Models | Best access to on-device document parsing and local multimodal generation [A1–A5]. |
| Container | Docker | Same artifact locally and in AWS. |

### 3.4 Milestone 1 exit criteria

| These are engineering targets for our system, not benchmark claims. We calibrate them on our own frozen evaluation set. |
| --- |

| Metric | Target / gate |
| --- | --- |
| Schema validity | 100% parseable ProductDocument payloads for successful model calls. |
| Candidate retrieval | True product appears in top-20 candidates ≥99% on catalog-match test set. |
| Auto-accepted match precision | ≥99% initially; increase threshold for financially consequential workflows. |
| Raw evidence preservation | 100% of resolved lines retain raw extracted SKU/description separately from canonical product. |
| Human-review safety | Every ambiguous/no-match case is reviewable; no silent forced match. |
| Operational success | ≥95% of supported uploads finish without system error on evaluation set. |
| Security | No API key in browser/mobile code; private object storage; upload validation active. |
| Observability | Every job records prompt/schema version, model, request ID, latency, token use and final decision. |

## 4. Canonical ProductDocument v1 contract

The JSON Schema is the system boundary. OpenAI generates it in Milestone 1. The Apple app generates the same semantic object in Milestone 2. Catalog matching consumes it. This is what prevents vendor/model lock-in.

```text
{
  "schema_version": "1.0",
  "document_type": "purchase_order | receipt | invoice | packing_slip | other",
  "supplier": {"raw_name": "...", "raw_id": null},
  "document_number": null,
  "currency": "USD",
  "items": [
    {
      "line_index": 1,
      "raw_product_id": "1113",
      "raw_description": "3/4 INDUSTRIAL HOSE 10M",
      "raw_brand": null,
      "quantity": 2,
      "unit": "EA",
      "unit_price": 18.75,
      "line_total": 37.50,
      "evidence_text": "1113  3/4 INDUSTRIAL HOSE 10M  2 EA 18.75 37.50",
      "quality_flags": []
    }
  ],
  "document_quality_flags": []
}
```

### 4.1 Contract rules

- raw_* fields are literal evidence. Do not “correct” them during extraction.

- Use null when a value is not visible or cannot be inferred safely.

- The extractor should not return canonical catalog product IDs unless the document literally contains them.

- quality_flags should describe observable uncertainty (cropped, blur, glare, ambiguous_columns, handwritten, unreadable_id) rather than a fabricated probability.

- Each schema revision is versioned. Prompt changes do not silently redefine field meaning.

### 4.2 Resolution object is separate

```text
{
  "line_id": "...",
  "raw_product_id": "1113",
  "selected_product_id": "product_8f2a",
  "canonical_sku": "1112",
  "decision": "auto_accept | review | no_match",
  "decision_source": "exact | rules | llm | human",
  "candidate_set_version": "...",
  "reasons": ["vendor SKU differs by one digit", "description and pack size agree"],
  "conflicts": ["raw ID conflicts with canonical SKU"]
}
```

| This separation is the auditability moat: the system can say “the document read 1113; after catalog resolution we selected canonical SKU 1112” instead of rewriting history. |
| --- |

## 5. Milestone 1 — OpenAI-first architecture

### 5.1 Request lifecycle

1. Client requests an upload slot and receives a document ID. In local development the file may post directly to FastAPI; in hosted beta use a short-lived S3 presigned URL [AWS1].

2. Server validates the object: allowlisted type, size, magic bytes/content decode, image dimensions, PDF parser acceptance, generated storage name and tenant ownership [S1].

3. For phone images, create a working JPEG/PNG derivative with metadata stripped; keep the original only if product policy requires it. HEIC from iPhone should be converted before sending because OpenAI vision inputs list PNG/JPEG/WEBP/non-animated GIF [O1].

4. OpenAI extraction returns ProductDocument v1 through Structured Outputs. Image inputs use high/original detail as appropriate; PDFs are sent as input_file so OpenAI can include extracted text and page images [O1–O3].

5. For every line item, backend performs deterministic candidate retrieval. The candidate stage is recall-oriented: exact identifiers first, then fuzzy SKU/name, then semantic retrieval.

6. Only the small candidate set is shown to the OpenAI matcher. The matcher can choose one of those IDs or no_match; backend rejects any ID outside the set.

7. A policy layer decides auto-accept vs review. Human corrections are written as immutable audit events.

### 5.2 State machine

```text
UPLOADED
  → VALIDATING
  → READY_FOR_EXTRACTION
  → EXTRACTING
  → EXTRACTED
  → RETRIEVING_CANDIDATES
  → MATCHING
  → RESOLVED | REVIEW_REQUIRED | NO_MATCH | FAILED
  → APPROVED
```

Representing this explicitly prevents the web UI from guessing what is happening and makes retries/idempotency tractable.

## 6. OpenAI implementation

### 6.1 Model choice for the first working system

As of 2 October 2026, OpenAI’s model catalog describes GPT-6.1 Sol as the balance of intelligence and cost, GPT-6 Astra as the flagship, and GPT-6 Luna as the high-volume efficient tier; all latest models accept image input and support Structured Outputs [O10].

| Role | Initial choice | Later experiment |
| --- | --- | --- |
| Document extraction | gpt-6.1-sol | Benchmark difficult subset against gpt-6-astra; cost-down to gpt-6-luna only if evals pass. |
| Candidate adjudication | gpt-6.1-sol initially | Move common candidate adjudication to gpt-6-luna after correctness is frozen. |
| Hard-tail escalation | gpt-6-astra only if needed | Use only for cases Sol cannot reliably resolve. |

| Do not optimize model cost before we have the first frozen evaluation set. Early API spend buys ground truth about failure modes. |
| --- |

### 6.2 Image and PDF input policy

| Input | OpenAI path | Recommended detail |
| --- | --- | --- |
| Single phone photo | input_image | original for dense/small print when supported; high for routine captures. |
| Several page photos | multiple input_image parts | high/original; process pages in order. |
| PDF | input_file | high for dense purchase orders; OpenAI sends both extracted text and page images [O3]. |
| HEIC/HEIF | convert first | JPEG working derivative; validate decode and orientation. |

### 6.3 Extraction prompt design

```text
SYSTEM — Document extraction
You extract evidence from purchasing documents.

Rules:
1. Preserve visible identifiers exactly. Never repair, normalize, or guess a SKU.
2. Return null when a field is not visible enough to support a value.
3. One source row should become one item unless the layout clearly wraps a single row.
4. Do not map extracted items to our catalog. Catalog resolution happens later.
5. Include a short evidence_text copied from the visible row for each item.
6. Mark observable quality issues in quality_flags.
7. Do not invent a quantity, price, brand, unit, or product ID.
```

### 6.4 Python extraction skeleton

```text
from pydantic import BaseModel
from openai import OpenAI

client = OpenAI()  # reads OPENAI_API_KEY server-side

class ProductLine(BaseModel):
    line_index: int
    raw_product_id: str | None
    raw_description: str | None
    raw_brand: str | None
    quantity: float | None
    unit: str | None
    unit_price: float | None
    line_total: float | None
    evidence_text: str | None
    quality_flags: list[str]

class ProductDocument(BaseModel):
    schema_version: str
    document_type: str
    document_number: str | None
    currency: str | None
    items: list[ProductLine]
    document_quality_flags: list[str]

response = client.responses.parse(
    model="gpt-6.1-sol",
    input=[{
        "role": "user",
        "content": [
            {"type": "input_text", "text": EXTRACTION_PROMPT},
            {"type": "input_image", "file_id": openai_file_id, "detail": "original"},
        ],
    }],
    text_format=ProductDocument,
    store=False,
)
product_document = response.output_parsed
```

Structured Outputs constrain shape, not factual correctness. Validation, candidate retrieval and human review remain necessary [O2].

### 6.5 API key and project setup

- Create a dedicated OpenAI project for this application; do not mix experimentation and production traffic.

- Use a project/service-account key in production, stored in a secret manager or environment variable. OpenAI explicitly warns against exposing keys in browsers or mobile apps [O4–O5].

- Set a low project spend alert/hard limit during prototype work and log billing-limit errors distinctly [O7].

- Log the OpenAI request ID, model ID, prompt version, schema version, usage and latency per extraction.

- Set store=false when application-level response persistence is unnecessary; separately review API data-retention settings because store=false is not the same as Zero Data Retention [O6].

## 7. Catalog retrieval and product matching

The LLM is not the search engine. The database is the search engine. The LLM is an adjudicator over a deliberately small, evidence-rich candidate set.

### 7.1 Candidate generation order

1. Tenant/vendor-scoped exact match: canonical SKU, vendor SKU, UPC/EAN/GTIN, customer-specific aliases.

2. Normalized exact match: Unicode normalization, uppercasing, whitespace/punctuation normalization; never discard the original string.

3. Typo/OCR tolerant retrieval: pg_trgm similarity for IDs and descriptions; include common visual confusions as candidate expansion only (0/O, 1/I/l, 5/S, 8/B).

4. Semantic retrieval: embed a stable product text representation (brand + name + variant + pack + description) and query pgvector.

5. Union and deduplicate the candidate channels. Preserve which channel retrieved each product and each raw score.

6. Compute deterministic feature signals: identifier equality/edit distance, brand agreement, pack/unit agreement, price-range plausibility, vendor compatibility.

7. Send top 5–20 candidates to the matcher. If the true product is not in the candidate set, no LLM can recover it; therefore candidate Recall@K is a first-class metric [R1].

### 7.2 Matcher contract

```text
class MatchDecision(BaseModel):
    selected_product_id: str | None
    verdict: Literal["match", "ambiguous", "no_match"]
    reasons: list[str]
    conflicts: list[str]

# Prompt invariant:
# You may select only an ID that appears in CANDIDATES, or return null.
# Raw document evidence is authoritative about what was visible;
# catalog data is authoritative about canonical product identity.
```

### 7.3 Acceptance policy

| Case | Backend action |
| --- | --- |
| Unique exact trusted identifier + no contradictory attributes | Auto-accept; no LLM needed. |
| Strong multi-signal candidate + matcher agrees + no conflict | Auto-accept only after empirical threshold is calibrated. |
| Top candidates close / contradictory brand, size, pack or ID | Review required. |
| No plausible candidate | No-match; never force nearest product. |
| LLM returns ID outside candidate set | Reject model response and review/log as validation failure. |

| Our north-star metric is precision on auto-accepted lines, not “percentage automated.” It is acceptable to review more documents while learning; it is not acceptable to silently order the wrong product. |
| --- |

## 8. Database design

### 8.1 Core tables

| Table | Key fields / purpose |
| --- | --- |
| tenants | Business/customer boundary. Every query is tenant-scoped. |
| products | canonical_product_id, canonical_sku, brand, name, description, unit, pack_size, active. |
| product_aliases | vendor/customer-specific SKU, UPC/GTIN/EAN, alternate descriptions and source. |
| product_embeddings | product_id, embedding, embedding_model, embedding_version. |
| documents | tenant_id, source type, object key, SHA-256, MIME, status, timestamps. |
| extractions | document_id, provider/model, prompt_version, schema_version, raw JSON, request_id, latency, token usage. |
| extracted_lines | literal line values and evidence; immutable except superseding extraction version. |
| match_candidates | line_id, product_id, retrieval_channel, rank, raw score, normalized features. |
| resolutions | selected product, decision source, policy version, status. |
| review_events | who changed what, old/new value, timestamp, reason. |

### 8.2 Product text used for embeddings

```text
embedding_text = f"""
brand: {brand}
name: {name}
canonical_sku: {canonical_sku}
variant: {variant}
pack: {pack_size} {unit}
description: {description}
""".strip()
```

Use one stable embedding template and version it. OpenAI’s current embeddings documentation lists text-embedding-3-small and text-embedding-3-large, with dimensions configurable; small is sufficient to begin candidate retrieval [O9].

### 8.3 Indexes

```text
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE INDEX products_sku_trgm_idx
  ON products USING gin (normalized_sku gin_trgm_ops);

CREATE INDEX products_name_trgm_idx
  ON products USING gin (normalized_name gin_trgm_ops);

CREATE INDEX product_embedding_hnsw_idx
  ON product_embeddings USING hnsw (embedding vector_cosine_ops);
```

PostgreSQL pg_trgm provides similarity operators/index support for typo-tolerant matching [PG1]. pgvector adds vector similarity and HNSW/IVFFlat indexing [PG2]. RDS/Aurora PostgreSQL support the vector extension, so the same database design can move to AWS without replacing the search layer [AWS3].

## 9. Web MVP and mobile photo UX

### 9.1 First screen

- Primary CTA: “Take photo / Scan order”. Secondary CTA: “Choose PDF or image”.

- Use a file input accepting image/* plus PDF. The capture="environment" hint can request the rear camera on supporting mobile browsers, but browser support is not universal, so the UI must also support ordinary photo/file selection [WEB1].

- Immediately preview the image and allow retake before upload.

- If possible, client-side downscale only extremely large images while retaining enough resolution for small product codes. Keep the original upload available to retry at higher detail if extraction fails.

```text
<input
  type="file"
  name="document"
  accept="image/*,application/pdf"
  capture="environment"
/>
```

### 9.2 Review screen

The reviewer sees the source image/PDF on the left and extracted rows on the right. Every row shows raw values, selected catalog product, why it matched, and a one-click change action. Do not hide auto-accepted rows; they should remain auditable.

| Column | Show |
| --- | --- |
| Source | Thumbnail/page and evidence text. |
| Raw | raw_product_id, description, quantity, unit, price. |
| Resolved | canonical SKU + product name. |
| Signals | exact/fuzzy/vector channels; conflicts. |
| Action | Approve, change candidate, no-match, edit extraction. |

## 10. Security, privacy and auditability

### 10.1 Upload security

- Allowlist business-required types only. Do not trust Content-Type alone; validate decoded content/magic bytes [S1].

- Generate storage keys server-side; never reuse user filenames as object keys or filesystem paths.

- Set upload size and image-dimension/page-count limits to prevent resource exhaustion.

- For images, decode and re-encode a working copy. For PDFs, reject malformed/encrypted documents unless explicitly supported; scan/sandbox before downstream processing when threat model requires it.

- Keep objects private. In AWS, use short-lived presigned upload URLs so the client can upload without AWS credentials [AWS1].

### 10.2 OpenAI data boundary

OpenAI API data is not used to train models by default; standard retention/abuse-monitoring controls and eligible Zero Data Retention options are documented separately [O6]. The app should have its own configurable original-document retention policy instead of assuming the model provider is the system of record.

### 10.3 Tenant isolation

- Every document, product, alias, candidate and resolution row carries tenant_id.

- All service-layer database methods require tenant context; do not rely only on front-end filtering.

- Presigned S3 object keys include opaque tenant/document IDs but do not expose customer names.

- If Postgres Row Level Security is added later, retain service-layer checks as defense in depth.

### 10.4 Audit log

| Record | Minimum evidence |
| --- | --- |
| Extraction | model, request ID, prompt version, schema version, source file hash, output JSON. |
| Candidate set | candidate IDs, retrieval channels/ranks/scores, retrieval version. |
| Model match | candidate payload hash, model, matcher prompt version, decision, conflicts. |
| Human correction | reviewer, before/after, timestamp, explicit reason where required. |
| Final action | approved product/order action and user/system identity. |

## 11. Evaluation system — build this before optimizing

ReceiptBench’s 10k+ real-world receipt benchmark emphasizes four distinct abilities: perception, format normalization, semantic reasoning and structure parsing [R2]. Our evaluation should mirror those layers and add catalog resolution.

### 11.1 Frozen gold set

| Slice | Suggested initial count | Purpose |
| --- | --- | --- |
| Clean digital PDFs | 30 | Baseline layout and PDF behavior. |
| Clear phone photos | 40 | Main user workflow. |
| Skew / perspective | 20 | Capture robustness. |
| Glare / low contrast | 20 | Hard visual text. |
| Blur / smudge | 15 | Reject/retake and fallback behavior. |
| Dense / long line-item docs | 25 | Structure parsing. |
| Multilingual / abbreviations | 15 | Language and catalog semantics. |
| Near-duplicate products | 25 | Product-resolution hard tail. |

These are planning counts, not statistical guarantees. Expand the set as real documents arrive, but never mutate the frozen comparison subset without versioning it.

### 11.2 Metrics by stage

| Stage | Metrics |
| --- | --- |
| Capture/validation | rejection rate by reason; retake rate; image dimensions; page count. |
| Extraction | line-item recall, raw SKU exact match, quantity exact match, price exact/tolerance match, false-positive/hallucinated field rate, document-level complete accuracy. |
| Candidate retrieval | Recall@5/10/20; retrieval channel contribution; true-product rank. |
| Matching | auto-accept precision, review precision, no-match precision/recall, wrong-product substitution rate. |
| Human review | review rate, correction rate by field, median review time, top correction reasons. |
| Operations | p50/p95 latency, OpenAI tokens/cost, retries, 4xx/5xx, queue depth when async. |

### 11.3 Confidence policy

Do not trust an LLM-generated “0.97 confidence” as a calibrated probability. Confidence should be a backend routing score derived from observable signals and calibrated against historical outcomes. A good initial policy can combine exact-ID evidence, candidate separation, attribute conflicts, image quality flags and whether the matcher returns ambiguous.

| Measure precision at a given automation coverage. “98% automation” is meaningless if the 2% wrong product substitutions are expensive. |
| --- |

## 12. Deployment path

### 12.1 Stage A — local end-to-end

- Docker Compose: api + PostgreSQL. Store sample uploads on a local volume.

- OpenAI API is the only external dependency needed for the first extraction.

- Use Alembic migrations from day one.

- Seed a realistic product catalog CSV into Postgres and create normalized aliases/embeddings.

- Run the frozen gold set locally before any public deployment.

### 12.2 Stage B — first hosted AWS deployment

| AWS component | Role |
| --- | --- |
| ECS Fargate | Run the Dockerized FastAPI service without managing EC2 hosts [AWS2]. |
| Application Load Balancer | HTTPS routing to the API/service. |
| RDS/Aurora PostgreSQL | Managed catalog + transactional state; enable pg_trgm and vector. |
| S3 private bucket | Original/working document objects; short-lived presigned uploads [AWS1]. |
| Secrets Manager / task secrets | OpenAI key and DB credentials. |
| CloudWatch | Logs and alarms; add OpenTelemetry later if needed. |

### 12.3 When to add a queue

Do not overbuild the first demo. A synchronous processing endpoint is acceptable for controlled testing. Before multi-user external beta, switch to POST upload → 202 Accepted → SQS/job worker so request timeouts and worker restarts do not lose document jobs. The state machine already prepares the data model for that transition.

## 13. Milestone 1 build sequence

| Gate | Deliverable | Definition of done |
| --- | --- | --- |
| A | Repository + environment | Docker, FastAPI, Postgres, Alembic, pytest, settings, OpenAI project key; health endpoint. |
| B | Product catalog | Create product/alias schema; CSV importer; normalization; pg_trgm; embedding job; catalog browser. |
| C | Document contract | Freeze ProductDocument v1 JSON/Pydantic models; contract tests; prompt/schema version constants. |
| D | Upload | Image/PDF validation, HEIC conversion path, storage abstraction, SHA-256, document state machine. |
| E | OpenAI extractor | Responses API, structured output, store=false where appropriate, request logging and retry handling. |
| F | Candidate retrieval | Exact → trigram → vector union; Recall@K test harness. |
| G | Matcher | Candidate-only LLM adjudication; backend validation; no-match and ambiguous outcomes. |
| H | Review UI | Side-by-side source + raw line + canonical match; correction audit events. |
| I | Evaluator | Gold labels, per-stage metrics, cost/latency dashboard/export. |
| J | Hosted beta | Container deploy, S3, RDS, HTTPS, spend limits, backups, monitoring. |

| Only when Gate J passes the Milestone 1 exit criteria do we begin the Apple implementation. No Qwen work is required to reach this point. |
| --- |

## 14. Milestone 2 — native Apple extraction provider

The native app is not a new matching system. It is a better capture client and an alternative extractor. The backend keeps the same product database, candidate retrieval, matcher, review and audit logic.

### 14.1 Target platform strategy

- Target the current iOS/iPadOS toolchain that exposes Apple’s latest multimodal Foundation Models APIs; runtime-check model availability rather than assuming hardware support.

- Apple Intelligence currently requires eligible hardware (including iPhone 15 Pro/Pro Max, iPhone 16 or later, and supported iPads such as M1+ / A17 Pro classes; exact current list should be rechecked before release) [A6].

- Keep Vision document parsing usable independently from the generative model so devices can still perform local structure/OCR work even when Foundation Models are unavailable.

- The app never contains the OpenAI API key. Cloud fallback uploads through our authenticated backend [O5].

### 14.2 iOS project modules

```text
ios/
  App/
  Capture/
    DocumentCamera.swift
    CaptureQuality.swift
  Extraction/
    VisionDocumentParser.swift
    AppleFoundationExtractor.swift
    ExtractionRouter.swift
  Contracts/
    ProductDocument.swift
    APIModels.swift
  Networking/
    BackendClient.swift
  Review/
    ReviewView.swift
  Diagnostics/
    EvaluationLogger.swift
```

## 15. Apple Vision implementation

RecognizeDocumentsRequest scans a document image and returns a hierarchical DocumentObservation containing text, tables, lists and barcodes; Apple states Vision APIs run entirely on-device [A1–A3]. This makes it ideal as the deterministic perception layer.

### 15.1 Capture path

1. Use AVFoundation or a VisionKit document-scanning UI to capture a high-resolution rear-camera image.

2. Correct orientation. If using a document scanner, retain its perspective-corrected output; otherwise detect/crop the document before analysis.

3. Run capture-quality checks. At minimum detect obviously bad focus/blur/crop; Apple also exposes lens-smudge detection in modern Vision [A2].

4. If quality fails, ask for a retake before any model inference. This is cheaper and safer than trying to reason over missing pixels.

5. Run RecognizeDocumentsRequest and preserve tables/rows/cells, text transcripts, barcodes and bounding regions for optional evidence display.

### 15.2 Vision skeleton

```text
import Vision

func parseDocument(_ image: CGImage) async throws -> DocumentObservation {
    let request = RecognizeDocumentsRequest()
    let observations = try await request.perform(on: image)
    guard let document = observations.first?.document else {
        throw ExtractionError.noDocument
    }
    return document
}

// document.tables
// document.lists
// document.text.transcript
// document.barcodes
```

Apple’s sample code demonstrates row-by-row table access and normalized bounding regions, which can later highlight the source cell during review [A3].

## 16. Apple Foundation Models implementation

Current Apple documentation supports image attachments in Foundation Models and recommends Generable for constrained structured output. Apple also exposes Vision OCR/barcode tools that the model can call, allowing a local perception + reasoning composition [A4–A5].

### 16.1 Swift contract

```text
import FoundationModels

@Generable
struct ProductLine: Codable {
    var lineIndex: Int
    var rawProductID: String?
    var rawDescription: String?
    var rawBrand: String?
    var quantity: Double?
    var unit: String?
    var unitPrice: Double?
    var lineTotal: Double?
    var evidenceText: String?
    var qualityFlags: [String]
}

@Generable
struct ProductDocument: Codable {
    var schemaVersion: String
    var documentType: String
    var documentNumber: String?
    var currency: String?
    var items: [ProductLine]
    var documentQualityFlags: [String]
}
```

### 16.2 Local multimodal extraction

```text
let session = LanguageModelSession(
    instructions: """
    Extract purchasing-document evidence. Preserve visible IDs literally.
    Never map to our catalog. Use nil for unsupported values.
    """
)

let response = try await session.respond(
    generating: ProductDocument.self,
    options: GenerationOptions(samplingMode: .greedy)
) {
    "Extract this document into ProductDocument v1."
    Attachment(cgImage)
}

let document = response.content
```

Greedy sampling is appropriate where deterministic extraction is preferred. Guided generation guarantees structural correctness of the Swift type, but factual correctness still requires evaluation and fallback [A4–A5].

### 16.3 Combine Vision evidence with Foundation Models

Do not force the Apple foundation model to rediscover everything from pixels. Give it the image plus structured Vision evidence when that improves consistency. Apple documents built-in OCRTool and BarcodeReaderTool as Foundation Models tools; our own custom tool can also expose table text or barcode results [A4].

## 17. Extraction router and privacy modes

| Mode | What leaves device | Use case |
| --- | --- | --- |
| Cloud standard | Photo/PDF → our backend → OpenAI | Maximum compatibility and simplest support. |
| Private mobile | Only ProductDocument JSON and optional Vision metadata | Supported Apple devices; original photo stays local. |
| Hybrid fallback | JSON first; image only if user/policy allows and local extraction is uncertain | Best balance of privacy and accuracy. |
| Strict local visual | No image upload permitted; unresolved cases require user correction | High-privacy customers willing to accept more manual review. |

### 17.1 Router logic

```text
if localFoundationModel.isAvailable:
    local = appleExtractor.extract(image)
    if local.passesQualityAndPolicy:
        return backend.match(local.productDocument)   # JSON only

vision = visionParser.parse(image)
if policy.allowsServerReasoningWithoutImage:
    return backend.extractFromVisionMetadataAndMatch(vision)

if policy.allowsCloudVision:
    return backend.uploadAndOpenAIFallback(image)

return requireHumanCorrection()
```

| Privacy and training-data collection must be separate user/customer policies. If “image never leaves device” is promised, do not quietly upload images for analytics or model improvement. |
| --- |

## 18. Milestone 2 evaluation and exit gate

Run Apple and OpenAI over the same frozen gold set. Do not judge Apple by subjective demos. The evaluation unit is the final business outcome: does the correct product reach the cart with the required review burden?

| Dimension | Compare |
| --- | --- |
| Extraction | Raw SKU exact match, item recall, quantity/price accuracy, hallucinated fields. |
| Catalog outcome | Candidate Recall@K, final match precision, no-match behavior. |
| Fallback | Percent of documents requiring OpenAI image fallback. |
| Privacy | Average bytes sent off-device and percent of sessions with no image upload. |
| Latency | capture→local JSON p50/p95; end-to-end resolution p50/p95. |
| Device behavior | model availability, memory pressure, thermal/battery observations by supported device class. |
| UX | retake rate, user corrections, review time. |

### 18.1 Go/no-go policy

- Ship local extraction only on device/OS combinations that pass the frozen evaluation set.

- Use measured fallback thresholds; do not hide poor local accuracy behind forced automation.

- If Apple local extraction is excellent on clean phone captures but weaker on dense PDFs or unusual layouts, keep a hybrid route rather than requiring one provider for every document type.

- Once this milestone is stable, the resulting corpus tells us exactly what Qwen or another private model would need to beat.

## 19. API economics and instrumentation

Current OpenAI standard short-context prices reviewed on 2 October 2026 list GPT-6.1 Sol at approximately $2/M input and $10/M output tokens, GPT-6 Luna at $0.10/M input and $0.50/M output, and GPT-6 Astra at $10/M input and $50/M output [O8,O10]. Image input is tokenized based on model/image detail, so actual request usage must be measured rather than assumed [O1].

| Illustrative request | Input tokens | Output tokens | Approx. model cost* |
| --- | --- | --- | --- |
| GPT-6.1 Sol extraction | 3,500 | 600 | $0.013 |
| GPT-6 Luna same workload | 3,500 | 600 | $0.00065 |
| GPT-6 Astra hard case | 3,500 | 600 | $0.065 |

*Illustrative arithmetic using the token assumptions shown; image/PDF tokenization and real outputs can differ. Record usage from every API response and compute realized cost per document.

### 19.1 Cost dashboard fields

- document_id, model, service tier, input tokens, cached input tokens, output tokens, estimated USD cost.

- Extraction cost and matching cost separately.

- Cost by tenant, document type and quality tier.

- Cost per approved line item and cost per fully automated document.

- Fallback cost: how often a cheaper path escalates to Sol/Astra.

## 20. Explicitly deferred: Qwen, training and quantization

The codebase should keep a provider interface that can eventually host Qwen or another VLM, but no engineering time should be spent training it before the first two milestones are measured. The future trigger is evidence: enough labeled documents and a clear failure/cost/privacy problem that a private model can solve.

| Deferred item | Why not now | What we need first |
| --- | --- | --- |
| Qwen server | Adds GPU serving complexity before product logic is proven. | Frozen evaluation corpus + OpenAI baseline. |
| Fine-tuning | No domain-specific labels yet. | Corrected extractions and final catalog resolutions. |
| Quantization | Optimization without a proven model/latency target. | Chosen model + real device/server benchmarks. |
| Qwen on iPhone | Feasible research path, but product UX/memory/thermal risk. | Apple native baseline and device metrics. |

## 21. Reference implementation snippets

### 21.1 Provider interface

```text
from typing import Protocol

class DocumentExtractor(Protocol):
    async def extract(self, source: DocumentSource) -> ProductDocument: ...

class OpenAIExtractor(DocumentExtractor): ...
# Future server-side:
class QwenExtractor(DocumentExtractor): ...

# iOS implements the same semantic contract locally and sends ProductDocument JSON.
```

### 21.2 FastAPI endpoints

```text
POST /v1/documents                 -> create document + upload instructions
POST /v1/documents/{id}/process    -> extract + retrieve + match
GET  /v1/documents/{id}            -> state/result
GET  /v1/documents/{id}/review     -> review payload
POST /v1/lines/{id}/resolve        -> human decision
POST /v1/match                     -> accept ProductDocument from iOS local extractor
GET  /v1/products/search           -> manual candidate search
```

### 21.3 Candidate retrieval pseudocode

```text
def retrieve_candidates(line, tenant_id, k=20):
    candidates = []
    candidates += exact_identifiers(line, tenant_id)
    candidates += trigram_sku_and_name(line, tenant_id, limit=30)
    candidates += vector_search(line, tenant_id, limit=30)
    candidates = merge_and_feature_score(candidates, line)
    return sort_for_recall(candidates)[:k]
```

### 21.4 Decision invariant tests

```text
def test_raw_evidence_is_never_overwritten(): ...
def test_matcher_cannot_select_outside_candidate_set(): ...
def test_no_candidate_returns_no_match_not_nearest_neighbor(): ...
def test_tenant_isolation_on_every_catalog_query(): ...
def test_openai_key_never_serialized_to_frontend(): ...
def test_same_product_document_contract_web_and_ios(): ...
```

## 22. Source register

Primary sources were preferred. URLs are current as of the research date; APIs and pricing should be rechecked immediately before implementation or release.

[O1] OpenAI — Images and vision: https://developers.openai.com/api/docs/guides/images-vision

[O2] OpenAI — Structured model outputs: https://developers.openai.com/api/docs/guides/structured-outputs

[O3] OpenAI — File inputs / PDF: https://developers.openai.com/api/docs/guides/pdf-files/

[O4] OpenAI — Production best practices: https://developers.openai.com/api/docs/guides/production-best-practices

[O5] OpenAI — API reference overview / credential safety: https://developers.openai.com/api/reference/overview

[O6] OpenAI — Your data: https://developers.openai.com/api/docs/guides/your-data

[O7] OpenAI — Spend limits: https://developers.openai.com/api/docs/guides/spend-limits

[O8] OpenAI — API pricing: https://developers.openai.com/api/docs/pricing

[O9] OpenAI — Vector embeddings: https://developers.openai.com/api/docs/guides/embeddings

[O10] OpenAI — Model catalog: https://developers.openai.com/api/docs/models

[A1] Apple — RecognizeDocumentsRequest: https://developer.apple.com/documentation/vision/recognizedocumentsrequest

[A2] Apple WWDC25 — Read documents using Vision: https://developer.apple.com/videos/play/wwdc2025/272/

[A3] Apple — Recognizing tables within a document: https://developer.apple.com/documentation/vision/recognize-tables-within-a-document

[A4] Apple — Analyzing images with multimodal prompting: https://developer.apple.com/documentation/FoundationModels/analyzing-images-with-multimodal-prompting

[A5] Apple — Foundation Models framework: https://developer.apple.com/documentation/foundationmodels

[A6] Apple Support — Apple Intelligence device requirements: https://support.apple.com/en-us/121115

[A7] Apple — Manage app privacy: https://developer.apple.com/help/app-store-connect/manage-app-information/manage-app-privacy/

[R1] Wang et al. (2026) — Retrieve, Match, Escalate: https://arxiv.org/abs/2608.25037

[R2] Wang et al. (ACL 2026) — ReceiptBench: https://aclanthology.org/2026.acl-long.2135/

[S1] OWASP — File Upload Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html

[PG1] PostgreSQL — pg_trgm: https://www.postgresql.org/docs/current/pgtrgm.html

[PG2] pgvector — official repository: https://github.com/pgvector/pgvector

[AWS1] AWS — S3 presigned upload/download URLs: https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html

[AWS2] AWS — ECS Fargate getting started: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/getting-started-fargate.html

[AWS3] AWS — Aurora PostgreSQL vector extension example: https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/AuroraPostgreSQL.VectorDB.html

[WEB1] MDN — file input / capture attribute: https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/input/file

## 23. Immediate build checklist

| Order | Action | Output |
| --- | --- | --- |
| 1 | Create dedicated OpenAI API project + small spend limit + server-side key. | Credential boundary ready. |
| 2 | Create repo, Docker Compose, FastAPI and Postgres. | Local stack boots. |
| 3 | Define ProductDocument v1 and migrations. | Contract frozen. |
| 4 | Import one realistic product catalog. | Searchable catalog. |
| 5 | Implement one photo → OpenAI → ProductDocument request. | First extraction. |
| 6 | Implement exact + fuzzy candidates; add embeddings after exact/fuzzy works. | Top-K candidates. |
| 7 | Implement candidate-only matcher. | Resolved or review state. |
| 8 | Build simple review screen and audit log. | Safe end-to-end flow. |
| 9 | Create/label initial gold set and evaluator. | Measured baseline. |
| 10 | Deploy hosted beta. | Milestone 1 candidate. |
| 11 | After Milestone 1 passes, create SwiftUI app with Vision parser. | Milestone 2 begins. |
| 12 | Add Foundation Models local ProductDocument generation and compare against gold set. | Measured local provider. |

| The first coding objective is intentionally small: one real phone photo should travel from capture → OpenAI → ProductDocument → candidate set → resolved product or review. Everything else grows around that verified spine. |
| --- |
# Source document

Searchable text extracted in document order from the user-provided DOCX. The original file (including its three architecture figures) sits beside this companion. Treat its imperative implementation sequence as research recommendations; the user's current request for this turn authorized documentation updates only. Adopted project direction and schema-safety notes are in [the review/adoption note](document-ai-research-adoption-2026-10-02.md).
