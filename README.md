# Advance PO Reader

Updated October 2, 2026. The current direction is the local OpenAI-first web workflow, then an Apple on-device extraction provider after the shared contract and matching path are measured. Qwen/self-hosted inference and training are deferred. Read [PROJECT_GOAL.md](PROJECT_GOAL.md) and the [research adoption note](docs/research/document-ai-research-adoption-2026-10-02.md); all four supplied research documents and searchable copies are preserved under `docs/research/`.

The repository also contains a previously built self-hosted VLM/candidate prototype and measurements. Those results remain available for comparison and do not verify the proposed OpenAI-first or Apple workflows. The local model stack is optional for the current roadmap. No API-first FastAPI service, canonical ProductDocument v1 implementation, authoritative commerce catalog, or production cart connection has been verified. Do not send supplied customer PDFs to an external model without applicable customer privacy authorization. Website integration still needs the real catalog and cart contract.

## Current implementation priority

The API-first implementation begins with local Gate A: FastAPI health/configuration, PostgreSQL and Alembic setup, and the first versioned contract boundary. The next stages establish a tenant-scoped catalog, validated local uploads, a server-side OpenAI extractor, bounded candidate matching, review/audit, and an independent evaluation gate. AWS hosting follows local validation. Apple Vision/Foundation Models is Milestone 2. Qwen/self-hosting and training follow only if measured evidence supports them. The October 2 research review updated documentation only; it did not begin implementation.

## Existing prototype and commands

The existing CLI supports native PDF parsing and the pretrained self-hosted Qwen comparison pipeline. Its 18-product sample catalog is provisional. Current direction and shared contract requirements are in the goal; historic model readiness and measurements are in [self-hosted infrastructure](docs/self-hosted-infrastructure.md) and [first results](docs/framework-first-results.md). The app/API described in the new research is a planned next milestone, not an existing CLI feature.

## Run

To run the existing self-hosted comparison prototype (Python activation is unnecessary):

```powershell
powershell -ExecutionPolicy Bypass -File .\run-local-model.ps1
& .\.venv\Scripts\python.exe reader.py analyze 'YOUR_AUTHORIZED_TEST_PDF.pdf' --summary
& .\.venv\Scripts\python.exe reader.py analyze 'YOUR_AUTHORIZED_TEST_ARCHIVE.zip' --limit 1 --summary
```

This existing CLI uses the configured local cascade on `http://127.0.0.1:11435`: Qwen3-VL extraction followed by optional gpt-oss text adjudication, embeddings and a dedicated reranker. It accepts PDFs, PNG/JPEG/WebP images, directories, and ZIP collections. This is a historical comparison workflow, not the current Milestone 1 architecture. Check live service readiness before relying on it.

Inspect/download the target stack and compare PDFs before making catalog decisions:

```powershell
& .\.venv\Scripts\python.exe model_stack.py
powershell -ExecutionPolicy Bypass -File .\setup-model-stack.ps1
& .\.venv\Scripts\python.exe benchmark_vision.py --mode vision --model qwen3-vl:8b-instruct --pipeline cascade --extraction-only --only-labeled --label-file output/vision-gold-representative.json --timeout 600 --output-dir output/new-8b-run
& .\.venv\Scripts\python.exe collect_review.py collect --result output/new-8b-run/vision-benchmark-vision.json --run-id new-8b-run
```

The 4B instruction model remains an explicit baseline: `reader.py analyze FILE --pipeline single --model qwen3-vl:4b-instruct`. The independent verifier requires a separately supported runtime; see the infrastructure guide.

This local-model comparison is separate from the OpenAI-first Milestone 1 goal. The explicit `-instruct` tag was used for the historical evaluation; the default Qwen thinking checkpoint exhausted the 8,192-token output budget on initial pages. See the saved report before relying on a different model configuration.

The existing CLI has an optional OpenAI provider, but it is not the new FastAPI/ProductDocument v1 path. An OpenAI request sends the supplied document to the API and can incur API charges. Use customer material only under the relevant privacy policy and explicit authorization. The model identifier and request fields from the October 2026 research must be verified at implementation. The CLI example accepts only an already-authorized local test file:

```powershell
& .\.venv\Scripts\python.exe reader.py analyze 'order.pdf' --provider openai --model YOUR_VISION_MODEL --summary
```

Run the earlier native parser and its sample evaluation explicitly:

```powershell
& .\.venv\Scripts\python.exe reader.py analyze data/originals --engine native --summary
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
& .\.venv\Scripts\python.exe evaluate.py
```

Use the returned session ID to stage a matched row or confirm a review row. Examples below use `SESSION_ID` as a placeholder:

```powershell
& .\.venv\Scripts\python.exe reader.py add SESSION_ID VERIFIED_CATALOG_ID 2 --line-id line-1 --unit EA
& .\.venv\Scripts\python.exe reader.py add SESSION_ID VERIFIED_CATALOG_ID 3 --line-id line-2 --unit EA --confirm
& .\.venv\Scripts\python.exe reader.py show SESSION_ID
& .\.venv\Scripts\python.exe reader.py remove SESSION_ID line-1
```

`--confirm` records the user's explicit resolution of an uncertain or edited row; it is not a bypass for nonexistent catalog IDs. `reader.py shipping` accepts a local details JSON with company/address/postcode/country_code/phone strings and requires `--confirm`. See `reader.py --help` and each subcommand's help.

The original evidence-only baseline is still available:

```powershell
& .\.venv\Scripts\python.exe extract.py --render
& .\.venv\Scripts\python.exe verify_samples.py
```

For a single file:

```powershell
& .\.venv\Scripts\python.exe extract.py 'YOUR_AUTHORIZED_TEST_PDF.pdf' --render --output output/single
```

`run.ps1` runs the full extraction with rendering. `setup.ps1` recreates missing dependencies from `requirements.lock.txt`; its optional `-PythonPath` accepts another Python 3.12 interpreter. The current environment uses Codex's bundled Python as its base, so retain that runtime or recreate the environment if it moves. Call scripts with `powershell -ExecutionPolicy Bypass -File .\run.ps1` if script policy prevents direct execution; this changes policy only for that process.

## Files and outputs

The repository retains local tools for preparing private, source-bound VLM image/JSON drafts and a page review editor. See [VLM dataset workflow](docs/vlm-dataset.md) for `build_vlm_dataset.py`, `build_vlm_review.py`, validation and explicit human release. These tools belong to the historical self-hosted comparison workflow. Drafts stay separate from approved labels; preparing a dataset does not train a model or change the current OpenAI-first roadmap.

- `data/originals/`: seven unchanged PDF attachments from the exact forwarded email, with original filenames.
- `data/source_manifest.json`: message provenance, attachment IDs, expected byte sizes and SHA-256 hashes. No expiring download credentials saved.
- `output/extractions/`: JSON evidence, plain and layout text, word coordinates, independent pypdf text, and page PNGs. Eight pages total.
- `docs/sample-findings.md`: visually checked sample findings and limitations.
- `extract.py`: command-line baseline; flags candidates for review and leaves address roles unset.
- `verify_samples.py`: real-file integrity and representative extraction regression checks.
- `data/catalog-seed.json` and `data/catalog.sqlite3`: private 18-product sample knowledge base, with raw observed variants and source references.
- `po_reader/`: parsing, retrieval, grounded matching, confirmations/cart state and bounded region rendering.
- `po_reader/model_provider.py`: OpenAI and local Ollama adapters with validated extraction/comparison schemas.
- `po_reader/vision.py`: page processing, raw observations, evidence checks, and comparison orchestration.
- `po_reader/model_matching.py`: LLM description comparison followed by exact catalog/source/quantity checks.
- `run-local-model.ps1`: starts/reuses the hidden project-local model server; `-Pull` downloads the selected local model if needed.
- `data/tools/ollama/` and `data/models/ollama/`: ignored portable runtime and local model weights. Installation manifest records the official release digest.
- `output/sessions/`: preserved source PDFs/images and full review/audit records, keyed by session ID. Review page images are optional with `reader.py analyze --render`.
- `benchmark_vision.py` and `docs/vision-evaluation.md`: full ZIP inventory, native/vision comparison, duplicate grouping and independent gold-label scoring.
- `output/logic-evaluation.json`: measured sample results; `output/sample-reviews-summary.json` contains the latest saved seven-sample CLI run.
- `docs/logic-architecture.md`, `docs/tiling-review.md` and `docs/UI_UX_HANDOFF.md`: current design reasoning, research and later UI/UX handoff.

Private source data and outputs are ignored by Git; source code and documentation can be versioned independently. This directory is under OneDrive, so local files remain subject to the user's existing OneDrive synchronization settings.

## Interpretation

Postcodes, phones, country evidence, quantities and identifiers remain strings. The model preserves all observed identifiers with their printed labels and roles. Semantic comparison can accept different wording while surfacing material, size, model, and pack differences. Automatic matches require an exact authoritative ID, compatible description, positive each quantity, and corroborated source evidence. Vision-only readings, uncertain roles, customer IDs without a scoped crosswalk, conflicting IDs, missing units, packs and reader disagreements require confirmation. Catalog suggestions do not replace a different printed ID. No identifier repair, implicit unit, or pack conversion is applied.

Dependencies are pinned from the installed environment. pdfplumber handles positioned text, pypdf provides independent text evidence, and PDFium renders pages locally. Official references: https://github.com/jsvine/pdfplumber and https://pypdf.readthedocs.io/en/stable/user/extract-text.html .

## Measurement and next integration

The existing native sample measurement recovered 23/23 source product rows and quantities, matched 19 rows, routed 4 rows to review, and excluded one shipping charge. Those PDFs also seeded the provisional catalog. A larger private ZIP inventory and a two-PDF/14-row reviewed subset support only the historic local-model evaluation; see `docs/sample-findings.md` and `docs/framework-first-results.md` for scope and limitations. The results do not measure the planned OpenAI or Apple providers, and planning targets in the new research are not measured results.

The next project milestone is local Gate A, followed by the shared evidence-preserving contract and catalog/extraction/review/evaluation gates in `PROJECT_GOAL.md`. Production use still depends on an authorized authoritative catalog, a defined cart/import contract, independently reviewed evaluation data, and privacy approval for any external processing. The later phone-first product includes a web workflow; the existing CLI remains a comparison prototype.

## Saved context and agent work

Read [the agent handoff](docs/agent-handoff.md) for the published baseline, next priorities, worktree setup and private fixture boundaries. The web demo source is retained under `web/po-reader-mockup/` as regular files with synthetic document assets.
