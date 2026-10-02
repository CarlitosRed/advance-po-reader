DOCUMENT AI COMMERCE

First Deployment API Runbook

Local workstation → AWS cloud server → OpenAI-first MVP

| PURPOSE  This is the engineering source of truth for Milestone 1. It is intentionally prescriptive so Work/Codex can implement the system without repeatedly researching which APIs, endpoints, SDK calls, schemas, environment variables, or cloud services to use. |
| --- |

| Status | Implementation-ready / API-first |
| --- | --- |
| Date | 2 October 2026 |
| Primary backend | Python 3.12 + FastAPI |
| Cloud target | AWS ECS Fargate + PostgreSQL + S3 |

Engineering rule: follow this runbook first; browse documentation only when a pinned call fails, a vendor deprecates a parameter, or a security requirement changes.

## 1. Pinned decisions — do not re-decide during the first deployment

| Area | Pinned choice | Why |
| --- | --- | --- |
| Backend | Python 3.12 + FastAPI | Fast iteration, strong typing with Pydantic, straightforward OpenAI/AWS/Postgres SDK support. |
| AI extraction | OpenAI Responses API + gpt-6.1-sol | Image input + Structured Outputs; strong quality/cost balance. Keep model ID configurable. |
| AI matcher | OpenAI Responses API + gpt-6-luna | Cheap text-only adjudication after deterministic candidate retrieval. |
| Semantic retrieval | text-embedding-3-small (optional at first) | 1536 dimensions; only add when exact + trigram retrieval does not reach candidate-recall target. |
| Database | PostgreSQL 18 + pg_trgm + pgvector 0.8.6 | Exact, typo-tolerant, and vector retrieval in one database. |
| Local storage | Local private upload directory | No AWS dependency for first vertical slice. |
| Cloud storage | Private Amazon S3 + short-lived presigned URLs | Browser uploads without AWS credentials; objects remain private. |
| Cloud compute | Amazon ECS Fargate | Runs the same Docker image without managing a VM. |
| Cloud DB | RDS/Aurora PostgreSQL | Managed Postgres; supports pgvector. |
| Secrets | Local .env; AWS Secrets Manager in cloud | No OpenAI API key in browser/mobile code or Git. |
| Queue | None initially | Add only when document latency/volume makes synchronous processing operationally painful. |

| NON-NEGOTIABLE DATA RULE  Never replace visual evidence. Persist raw_product_id/raw_description exactly as extracted, and store canonical_product_id separately after catalog resolution. |
| --- |

## 2. API inventory — exactly what Milestone 1 uses

### 2.1 Required on day one

| API / protocol | Purpose | Called by | Auth | Required? |
| --- | --- | --- | --- | --- |
| OpenAI Responses API  POST /v1/responses | Image/PDF → ProductDocument; candidate set → match decision | FastAPI backend | OPENAI_API_KEY | YES |
| PostgreSQL wire protocol | Catalog, jobs, raw extraction, candidates, resolutions, audit trail | FastAPI backend | DATABASE_URL | YES |
| Internal REST API /api/v1/* | Browser <-> backend contract | Web client | App auth later; dev session initially | YES |
| Local filesystem | Private document storage during local development | FastAPI backend | OS permissions | YES — local only |
| S3 presigned PUT/GET | Direct upload and temporary model-access URL in AWS | Browser + backend | ECS IAM role; signed URL for browser | YES — cloud only |

### 2.2 Planned but not mandatory for the first vertical slice

| API | Use it when… | Default decision |
| --- | --- | --- |
| OpenAI Embeddings  POST /v1/embeddings | Exact SKU + pg_trgm fails to place the true product in top-K reliably. | Implement behind feature flag; do not block first photo → match demo. |
| OpenAI Files  POST /v1/files | A document must be reused across multiple OpenAI calls or external URL/base64 is inconvenient. | Do not use by default; prefer base64 locally and short-lived S3 URL in cloud. |
| AWS Secrets Manager API | Runtime code needs to retrieve/rotate secrets itself. | Prefer ECS secret injection; application code should not call Secrets Manager unless necessary. |
| SQS / worker queue | Processing becomes slow, bursty, or needs retries independent of HTTP lifecycle. | Defer until measurements justify it. |

## 3. One codebase, two execution profiles

### 3.1 Local development profile

```text
Browser / phone browser
        |
        v
FastAPI (localhost:8000)
        |--- local file volume: ./data/uploads
        |--- PostgreSQL 18 + pg_trgm + pgvector (Docker)
        |
        +--- OpenAI Responses API
                 |--- gpt-6.1-sol: extraction
                 +--- gpt-6-luna: candidate adjudication
```

- Use multipart upload to FastAPI locally. No S3, IAM, ECS, or Secrets Manager is required.

- The OpenAI key is read server-side from OPENAI_API_KEY. The browser never sees it.

- The database schema and application endpoints are the same ones used in cloud.

### 3.2 AWS profile

```text
Browser / phone browser
        |
        | 1. POST /api/v1/uploads/presign
        v
FastAPI on ECS Fargate -------------------------+
        |                                       |
        | 2. returns presigned PUT URL          | IAM task role
        v                                       |
Private S3 <----- browser PUT ------------------+
        |
        | 3. backend creates short-lived signed GET
        v
OpenAI Responses API
        |
        v
RDS/Aurora PostgreSQL <--- FastAPI
```

| SAME APPLICATION LOGIC  Only StorageProvider changes: LocalStorageProvider locally, S3StorageProvider in AWS. DocumentAIProvider and CatalogResolver are unchanged. |
| --- |

## 4. Environment variables — exact configuration surface

| Variable | Local example | Cloud source | Secret? |
| --- | --- | --- | --- |
| APP_ENV | local | ECS task env: production | No |
| DATABASE_URL | postgresql+psycopg://app:app@db:5432/docai | Secrets Manager injected into task | YES |
| OPENAI_API_KEY | sk-proj-… in .env only | Secrets Manager injected into task | YES |
| OPENAI_EXTRACTION_MODEL | gpt-6.1-sol | same | No |
| OPENAI_MATCHER_MODEL | gpt-6-luna | same | No |
| OPENAI_EMBEDDING_MODEL | text-embedding-3-small | same | No |
| ENABLE_EMBEDDINGS | false | false until needed | No |
| STORAGE_BACKEND | local | s3 | No |
| LOCAL_UPLOAD_DIR | ./data/uploads | unused | No |
| AWS_REGION | unused | us-east-1 (or chosen region) | No |
| S3_BUCKET | unused | private bucket name | No |
| S3_URL_TTL_SECONDS | unused | 300 | No |
| MAX_UPLOAD_MB | 25 | 25 | No |
| FILE_RETENTION_DAYS | 30 | 30 or customer policy | No |
| ALLOWED_ORIGINS | http://localhost:3000 | production UI origin | No |
| LOG_LEVEL | INFO | INFO | No |

```text
# .env.example — commit this file, never the real .env
APP_ENV=local
DATABASE_URL=postgresql+psycopg://app:app@db:5432/docai
OPENAI_API_KEY=
OPENAI_EXTRACTION_MODEL=gpt-6.1-sol
OPENAI_MATCHER_MODEL=gpt-6-luna
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
ENABLE_EMBEDDINGS=false
STORAGE_BACKEND=local
LOCAL_UPLOAD_DIR=./data/uploads
MAX_UPLOAD_MB=25
FILE_RETENTION_DAYS=30
ALLOWED_ORIGINS=http://localhost:3000
LOG_LEVEL=INFO
```

## 5. Local bootstrap — packages and Docker

### 5.1 Python dependencies

```text
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate

pip install   fastapi "uvicorn[standard]" openai pydantic pydantic-settings   sqlalchemy alembic "psycopg[binary,pool]" pgvector   python-multipart pillow pillow-heif boto3 httpx pytest

pip freeze > requirements.lock.txt
```

| PIN AFTER FIRST GREEN BUILD  Do not hand-author speculative package versions. Install the current compatible set once, run tests, then commit requirements.lock.txt so Work uses the same versions thereafter. |
| --- |

### 5.2 Docker Compose database

```text
services:
  db:
    image: pgvector/pgvector:0.8.6-pg18
    environment:
      POSTGRES_DB: docai
      POSTGRES_USER: app
      POSTGRES_PASSWORD: app
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

- The current pgvector image supports PostgreSQL 18 and pgvector 0.8.6.

- For the first development pass, run FastAPI on the host; containerize it after the vertical slice works.

## 6. Canonical contracts — freeze these before API coding

### 6.1 ProductDocument v1

```text
from typing import Literal
from pydantic import BaseModel, Field

class ProductLine(BaseModel):
    line_id: str
    raw_product_id: str | None = None
    raw_description: str | None = None
    quantity: float | None = None
    unit: str | None = None
    unit_price: float | None = None
    currency: str | None = None
    source_page: int | None = None
    evidence_text: str | None = None
    ambiguity_notes: list[str] = Field(default_factory=list)

class ProductDocument(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    document_type: Literal[
        "purchase_order", "invoice", "receipt", "packing_slip", "unknown"
    ]
    supplier_name_raw: str | None = None
    document_number_raw: str | None = None
    line_items: list[ProductLine]
    document_warnings: list[str] = Field(default_factory=list)
```

Extraction rule: missing or unreadable values are null. The extractor does not invent catalog IDs, normalize to a known product, or silently “fix” characters.

### 6.2 CatalogResolution v1

```text
class MatchDecision(BaseModel):
    decision: Literal["match", "no_match", "review"]
    selected_product_id: str | None = None
    reason_code: Literal[
        "EXACT_ID",
        "NEAR_ID_DESCRIPTION_SUPPORTS",
        "DESCRIPTION_AND_ATTRIBUTES_SUPPORT",
        "CONTRADICTORY_EVIDENCE",
        "INSUFFICIENT_EVIDENCE"
    ]
    supporting_evidence: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
```

| MATCHER CONSTRAINT  The matcher may select only one of the product IDs included in the candidate list supplied by the backend, or return no_match/review. It may never invent a new catalog product. |
| --- |

## 7. Internal REST API — the browser/backend contract

| Method + path | Purpose | Local | Cloud |
| --- | --- | --- | --- |
| GET /api/v1/health | Liveness/readiness and dependency summary | YES | YES |
| POST /api/v1/documents/upload | Multipart file upload; creates document row | YES | NO (dev fallback only) |
| POST /api/v1/uploads/presign | Create document ID + S3 presigned PUT | NO | YES |
| POST /api/v1/documents/{id}/uploaded | Confirm S3 upload and persist metadata | NO | YES |
| POST /api/v1/documents/{id}/process | Run extraction → retrieval → match | YES | YES |
| GET /api/v1/documents/{id} | Return state, raw extraction and resolutions | YES | YES |
| POST /api/v1/documents/{id}/review | Human confirms/corrects selected product(s) | YES | YES |
| POST /api/v1/catalog/import | Load/update product catalog for dev/admin | YES | YES |

### 7.1 State machine

```text
CREATED
  -> UPLOADED
  -> EXTRACTING
  -> EXTRACTED
  -> MATCHING
  -> RESOLVED | NEEDS_REVIEW | FAILED
  -> HUMAN_APPROVED  (when review occurs)
```

- Persist state transitions in the database. The UI polls GET /documents/{id} in v1; no WebSocket is required.

- A retry must be idempotent: re-processing a document creates a new processing_run record, not duplicate product/order rows.

## 8. OpenAI Responses API — document extraction

### 8.1 Image path

```text
import os
from openai import OpenAI
from .schemas import ProductDocument

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

EXTRACTION_INSTRUCTIONS = """
Extract only what is visibly supported by the document.
Return null for unreadable/missing values.
Preserve product IDs exactly as seen; do not correct them using world knowledge.
Treat each physical line item as a separate line_items entry.
Put uncertain interpretations in ambiguity_notes/document_warnings.
"""

def extract_image(image_url_or_data_url: str) -> ProductDocument:
    rsp = client.responses.parse(
        model=os.getenv("OPENAI_EXTRACTION_MODEL", "gpt-6.1-sol"),
        instructions=EXTRACTION_INSTRUCTIONS,
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Extract this purchasing document."},
                {
                    "type": "input_image",
                    "image_url": image_url_or_data_url,
                    "detail": "original",
                },
            ],
        }],
        text_format=ProductDocument,
        reasoning={"effort": "low"},
        store=False,
    )
    if rsp.output_parsed is None:
        raise RuntimeError("OpenAI did not return a parsed ProductDocument")
    return rsp.output_parsed
```

- Local: convert JPEG/PNG/WEBP to a base64 data URL and pass it as image_url.

- Cloud: pass a short-lived S3 presigned GET URL. The bucket itself remains private.

- Use detail="original" for small/dense SKU text. Benchmark "high" later if it preserves accuracy at lower token cost.

### 8.2 PDF path

```text
def extract_pdf(file_url_or_data: dict) -> ProductDocument:
    # cloud content example: {"type":"input_file", "file_url": signed_url, "detail":"high"}
    # local content example: {"type":"input_file", "filename":"doc.pdf",
    #                         "file_data":"data:application/pdf;base64,...", "detail":"high"}
    rsp = client.responses.parse(
        model=os.getenv("OPENAI_EXTRACTION_MODEL", "gpt-6.1-sol"),
        instructions=EXTRACTION_INSTRUCTIONS,
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Extract this purchasing document."},
                file_url_or_data,
            ],
        }],
        text_format=ProductDocument,
        reasoning={"effort": "low"},
        store=False,
    )
    return rsp.output_parsed
```

- Responses API PDF input supplies extracted text plus page images to vision-capable models.

- Each file must be under 50 MB and combined file input per request is capped at 50 MB; our application limit is deliberately lower at 25 MB for the MVP.

- PDF page-image detail supports auto/low/high; pin high for the initial benchmark.

### 8.3 What we are NOT using

- No Assistants API.

- No File Search.

- No web search tool.

- No Agents SDK for the first vertical slice.

- No OpenAI API call directly from browser/iPhone code.

## 9. Catalog candidate retrieval — database first, LLM second

### 9.1 Database extensions and indexes

```text
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE products (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL,
    sku text NOT NULL,
    normalized_sku text NOT NULL,
    upc text,
    vendor_sku text,
    name text NOT NULL,
    description text,
    searchable_text text NOT NULL,
    embedding vector(1536),
    active boolean NOT NULL DEFAULT true
);

CREATE UNIQUE INDEX ux_products_tenant_sku
  ON products (tenant_id, normalized_sku);
CREATE INDEX ix_products_search_trgm
  ON products USING gin (searchable_text gin_trgm_ops);
CREATE INDEX ix_products_embedding_hnsw
  ON products USING hnsw (embedding vector_cosine_ops);
```

| EMBEDDINGS FEATURE FLAG  Create the vector column/index now so the schema is future-ready, but do not populate/query embeddings until ENABLE_EMBEDDINGS=true. Exact + trigram retrieval comes first. |
| --- |

### 9.2 Candidate generation order

1. Normalize the raw identifier without changing ambiguous characters: trim whitespace, uppercase, standardize separators only.

1. Exact lookup on normalized SKU, UPC/EAN/GTIN, and vendor SKU within the tenant.

1. Generate controlled visual-confusion variants only for retrieval (for example O<->0, I/L<->1). Never overwrite raw_product_id.

1. Run pg_trgm similarity over SKU/name/searchable_text and retain the strongest candidates.

1. If embeddings are enabled, add vector neighbors using the raw description + vendor context.

1. Merge/dedupe channels and send at most 10 candidates to the LLM matcher.

```text
-- illustrative trigram retrieval
SELECT id, sku, name, description,
       similarity(searchable_text, :query) AS trigram_score
FROM products
WHERE tenant_id = :tenant_id
  AND active = true
ORDER BY trigram_score DESC
LIMIT 10;
```

## 10. OpenAI Embeddings API — optional semantic channel

```text
def embed_text(text: str) -> list[float]:
    response = client.embeddings.create(
        model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
        input=text.replace("\n", " "),
        encoding_format="float",
    )
    return response.data[0].embedding
```

- text-embedding-3-small returns 1536 dimensions by default, matching vector(1536).

- Embed catalog records offline/on import, not on every document processing request.

- At runtime, embed one query string per line item, then search only inside the current tenant.

```text
SELECT id, sku, name, description,
       1 - (embedding <=> :query_embedding) AS cosine_similarity
FROM products
WHERE tenant_id = :tenant_id
  AND active = true
  AND embedding IS NOT NULL
ORDER BY embedding <=> :query_embedding
LIMIT 10;
```

## 11. OpenAI Responses API — candidate adjudication

```text
MATCHER_INSTRUCTIONS = """
You resolve one extracted line item against a supplied candidate list.
You may select only a candidate ID that appears in candidates.
Prefer exact identifiers, but reject them if other attributes clearly contradict.
If evidence is insufficient or contradictory, return review or no_match.
Never invent a product, SKU, pack size, brand, or unit.
"""

def adjudicate(line_item: dict, candidates: list[dict]) -> MatchDecision:
    payload = {"line_item": line_item, "candidates": candidates}
    rsp = client.responses.parse(
        model=os.getenv("OPENAI_MATCHER_MODEL", "gpt-6-luna"),
        instructions=MATCHER_INSTRUCTIONS,
        input=[{"role":"user", "content": str(payload)}],
        text_format=MatchDecision,
        reasoning={"effort": "low"},
        store=False,
    )
    decision = rsp.output_parsed
    allowed = {str(c["id"]) for c in candidates}
    if decision.selected_product_id and decision.selected_product_id not in allowed:
        raise RuntimeError("Matcher selected an out-of-candidate product")
    return decision
```

| DO NOT TRUST MODEL SELF-CONFIDENCE  Automation thresholds must be calibrated from empirical correctness, deterministic agreements, candidate score margins, contradictions, and second checks—not from the model claiming “95% confidence.” |
| --- |

## 12. Amazon S3 API — cloud upload and temporary model access

### 12.1 Presigned PUT

```text
import boto3
from botocore.config import Config

s3 = boto3.client(
    "s3",
    region_name=os.environ["AWS_REGION"],
    config=Config(signature_version="s3v4"),
)

def create_upload_url(bucket: str, key: str, content_type: str) -> str:
    return s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=300,
        HttpMethod="PUT",
    )
```

- Browser sends PUT directly to the returned URL with the same Content-Type used when signing.

- Object keys use opaque tenant/document UUIDs, not customer names or original filenames.

- Bucket blocks public access. The URL is capability-based and short-lived.

### 12.2 Presigned GET for OpenAI input

```text
def create_read_url(bucket: str, key: str) -> str:
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=300,
        HttpMethod="GET",
    )
```

- Use this URL as input_image.image_url for images or input_file.file_url for PDFs.

- Generate it immediately before the OpenAI request; do not persist it in the database.

## 13. Security and privacy implementation checklist

| Control | Implementation |
| --- | --- |
| OpenAI key | Server-side only. Environment variable locally; ECS secret injection in cloud. Never browser/mobile. |
| AWS credentials | No static keys in the container. ECS task role grants only required S3 object permissions. |
| Uploads | Allowlist JPEG/PNG/WEBP/HEIC/PDF at app layer; sniff actual file type; reject oversized files; re-encode images before processing. |
| Object access | S3 Block Public Access ON; short-lived presigned URLs; no public ACLs. |
| OpenAI storage | Set store=False for extraction/matcher calls. Keep our own audit records separately. |
| Tenant isolation | Every product/document/query is scoped by tenant_id before retrieval. |
| Logs | Never log full API keys, raw signed URLs, or whole documents. Log document_id, request ID, model, latency, usage and result state. |
| Database | Private network in cloud; migrations through Alembic; separate app role with least privileges. |
| Human review | Show raw evidence and canonical selection separately; record actor, timestamp, old value, new value. |

## 14. Error handling and retry policy

| Condition | Action | HTTP to client |
| --- | --- | --- |
| Unsupported extension/MIME | Reject before storage/model call | 415 |
| File over MAX_UPLOAD_MB | Reject | 413 |
| Malformed request/schema | Reject with field error | 422 |
| OpenAI 429 / transient 5xx / timeout | Retry with bounded exponential backoff; respect Retry-After | 202/503 depending execution mode |
| OpenAI refusal / no parsed structured result | Mark processing run failed or needs review; preserve raw file | 502 or document state NEEDS_REVIEW |
| Catalog returns zero candidates | Do not ask matcher to invent; set NEEDS_REVIEW/NO_MATCH | 200 document result |
| S3 URL expired | Generate a new URL and retry once | transparent |
| Database unavailable | Fail request; do not continue AI call if audit state cannot be persisted | 503 |

| RETRY BOUNDARY  Retry transport/throttling failures. Do not automatically retry deterministic 4xx validation errors. Every model retry creates or updates a processing_run entry so duplicate work is visible. |
| --- |

## 15. Observability — fields every processing run records

| Field group | Fields |
| --- | --- |
| Identity | processing_run_id, document_id, tenant_id, source_type |
| OpenAI extraction | model, OpenAI request ID, input tokens, output tokens, duration_ms, success/refusal/error |
| Retrieval | exact_hits, trigram_hits, vector_hits, merged_candidate_count, top_score_margin |
| Matcher | model, OpenAI request ID, input/output tokens, decision, reason_code, duration_ms |
| Review | was_reviewed, final_product_id, correction_type, reviewer_id, review_duration_ms |
| Cost | estimated_extraction_cost_usd, estimated_matcher_cost_usd, total_cost_usd |

- Use OpenAI response usage fields rather than estimating tokens from prompt length.

- Capture x-request-id / SDK request ID for production troubleshooting.

- Never treat a model-generated confidence value as the KPI. Track empirical correction rate and false-match rate.

## 16. Tests that must pass before cloud deployment

### 16.1 Unit / invariant tests

- Normalization never changes raw_product_id.

- Matcher cannot select a product outside candidate_ids.

- No candidates → no matcher call.

- Exact SKU match still preserves original visual extraction.

- Each database query includes tenant_id.

- S3 provider never returns a public object URL—only expiring presigned URLs.

- OPENAI_API_KEY is absent from frontend build output and logs.

### 16.2 Integration fixtures

| Fixture | Expected assertion |
| --- | --- |
| Clean one-page PO photo | All visible line items extracted; exact products resolve. |
| SKU one character misread | Raw SKU preserved; true catalog product appears in candidates; resolution separate. |
| Duplicate descriptions / different pack sizes | System reviews or uses pack evidence; no silent first-hit selection. |
| Blurred image | Warnings/low evidence cause review rather than fabricated data. |
| Multi-page PDF | Lines preserve source_page and no duplicate rows. |
| No catalog match | no_match/review; no invented catalog ID. |
| Cross-tenant same SKU | Only active tenant product can appear in candidates. |

## 17. Engineering sequence — follow in this order

1. Create repository layout: app/api, app/core, app/models, app/schemas, app/providers, app/services, migrations, tests.

2. Create .env.example, Settings class, GET /api/v1/health, and local Postgres Docker Compose.

3. Run Alembic migration enabling pg_trgm/vector and creating products/documents/processing_runs/extractions/resolutions/reviews.

4. Implement LocalStorageProvider and local multipart upload.

5. Freeze ProductDocument v1 and make a single gpt-6.1-sol image produce parsed ProductDocument from one real photo.

6. Persist the raw extraction exactly as returned.

7. Import a small product catalog; implement exact + pg_trgm retrieval.

8. Implement gpt-6-luna candidate adjudication with the hard candidate-ID guard.

9. Build result/review screen and persist human corrections.

10. Create 20–50 representative fixtures and run the first accuracy/error taxonomy pass.

11. Containerize FastAPI. Create S3StorageProvider and presigned upload/read flow.

12. Create AWS infrastructure: S3 private bucket, RDS/Aurora PostgreSQL, Secrets Manager, ECR, ECS Fargate service, HTTPS ingress.

13. Run migrations in cloud, smoke-test one image and one PDF end to end, then compare local/cloud outputs.

14. Only after candidate recall is measured, decide whether to turn ENABLE_EMBEDDINGS=true.

## 18. AWS deployment checklist — no architecture redesign

| AWS component | What to configure | Application impact |
| --- | --- | --- |
| ECR | Repository for the API Docker image | CI/build pushes image |
| ECS Fargate | One API service; task health check /api/v1/health | Runs identical FastAPI image |
| Application Load Balancer + ACM | HTTPS public endpoint | API_BASE_URL / CORS only |
| RDS/Aurora PostgreSQL | Private DB, backups, pg_trgm + vector extensions | DATABASE_URL changes |
| S3 | Private document bucket, encryption, lifecycle rule | STORAGE_BACKEND=s3 |
| Secrets Manager | OPENAI_API_KEY and DB secret | Injected into task |
| IAM task role | Minimum S3 read/write on object prefix | No static AWS key |
| CloudWatch Logs | Container stdout/stderr | Structured logs automatically collected |

| DEPLOYMENT PRINCIPLE  Do not create a second cloud-specific code path. Configuration selects storage/database endpoints; business logic stays identical. |
| --- |

## 19. Explicitly out of scope for this deployment

- Apple Vision / Foundation Models implementation — Milestone 2.

- Qwen, MLX, model quantization, fine-tuning, LoRA/QLoRA, or custom GPU servers.

- Kafka, Kubernetes, service mesh, microservices, or event-driven complexity.

- Agents SDK, autonomous web search, or model tool orchestration.

- Custom confidence neural model or learning-to-rank system.

- Full ERP/e-commerce integrations beyond the catalog and review loop.

| WHY  The first deployment proves the invariant workflow: document → raw structured extraction → candidate retrieval → constrained canonical match → human review. Everything else is optimization or expansion. |
| --- |

## 20. Ready-to-paste Work / engineering bootstrap instruction

```text
Use the attached “First Deployment API Runbook” as the authoritative implementation specification for Milestone 1.

Rules:
1. Do not redesign the architecture or research alternative APIs unless a pinned API call is rejected/deprecated, a test proves the chosen method inadequate, or a security blocker requires a change.
2. Implement in the exact sequence in Section 17.
3. Keep the OpenAI key server-side only.
4. Preserve raw extraction separately from canonical product resolution.
5. Retrieval narrows the catalog first; the LLM may adjudicate only the supplied candidates.
6. Keep local and AWS deployments on the same codebase; use providers/configuration for storage differences.
7. Do not start Apple, Qwen, training, or quantization work in this milestone.
8. After each gate, run tests and commit before moving to the next gate.
9. If the live SDK differs from a code sample, make the smallest compatibility change, document it in CHANGELOG.md, and preserve the API contract.

Start by creating the repository structure, local PostgreSQL/pgvector Docker environment, Settings/.env.example, health endpoint, database migration, and ProductDocument v1 Pydantic schemas. Then stop and report the files created and test results before continuing.
```

## 21. Definition of “first deployment complete”

- A phone browser can capture/select a photo and process it locally through the full pipeline.

- A PDF follows the same ProductDocument contract.

- At least one intentionally misread SKU resolves correctly while preserving the raw extraction.

- No-match and ambiguous cases route to review instead of fabricating a product.

- The exact same Docker image runs in AWS with S3/RDS configuration changes only.

- OpenAI keys and AWS permissions never reach client-side code.

- Processing runs store usage, request IDs, timing, candidate sets, decisions, and human corrections.

- The initial gold set has measurable extraction accuracy, candidate recall@K, auto-match precision, review rate, and cost/document.

- Only then begin Milestone 2 (Apple on-device extraction).

## 22. Primary source register

> [OA1] OpenAI — GPT-6.1 Sol model — https://developers.openai.com/api/docs/models/gpt-6.1-sol

> [OA2] OpenAI — GPT-6 Luna model — https://developers.openai.com/api/docs/models/gpt-6-luna

> [OA3] OpenAI — Images and vision — https://developers.openai.com/api/docs/guides/images-vision

> [OA4] OpenAI — File inputs — https://developers.openai.com/api/docs/guides/file-inputs

> [OA5] OpenAI — Structured Outputs — https://developers.openai.com/api/docs/guides/structured-outputs

> [OA6] OpenAI — Embeddings — https://developers.openai.com/api/docs/guides/embeddings

> [OA7] OpenAI — API overview / key safety — https://developers.openai.com/api/reference/overview

> [OA8] OpenAI — Production best practices — https://developers.openai.com/api/docs/guides/production-best-practices

> [OA9] OpenAI — Your data — https://developers.openai.com/api/docs/guides/your-data

> [OA10] OpenAI — Spend limits — https://developers.openai.com/api/docs/guides/spend-limits

> [PG1] PostgreSQL — pg_trgm — https://www.postgresql.org/docs/current/pgtrgm.html

> [PG2] pgvector — official README — https://github.com/pgvector/pgvector

> [PG3] pgvector-python — https://github.com/pgvector/pgvector-python

> [AWS1] AWS S3 — presigned URLs — https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html

> [AWS2] Boto3 — generate_presigned_url — https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/generate_presigned_url.html

> [AWS3] AWS ECS — Fargate getting started — https://docs.aws.amazon.com/AmazonECS/latest/developerguide/getting-started-fargate.html

> [AWS4] Aurora PostgreSQL — pgvector — https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/AuroraPostgreSQL.VectorDB.html

> [SEC1] OWASP — File Upload Cheat Sheet — https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html

> [R1] Retrieve, Match, Escalate (2026) — https://arxiv.org/abs/2608.25037

> [R2] ReceiptBench (ACL 2026) — https://aclanthology.org/2026.acl-long.2135/
# Source document

Searchable text extracted in document order from the user-provided DOCX. The original file sits beside this companion. Treat its imperative implementation sequence as research recommendations; the user's current request for this turn authorized documentation updates only. Adopted project direction and schema-safety notes are in [the review/adoption note](document-ai-research-adoption-2026-10-02.md).
