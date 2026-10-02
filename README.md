# Advance PO Reader

Self-hosted document extraction and catalog reconciliation, updated October 1, 2026. The authoritative working goal is [PROJECT_GOAL.md](PROJECT_GOAL.md), based on the retained [research framework](docs/research/self_hosted_document_ai_recommendation_2026.docx). This phase uses pretrained models and provided PDFs for inference, evaluation and review collection. **Training and fine-tuning are deferred.** Runs use a project-specific Python `.venv` and a project-local Ollama server. Website integration awaits its authoritative catalog and cart API schema.

## Product goal

The workflow reads a customer's PO PDF or image, preserves raw business fields and requested identifiers/quantities, retrieves and ranks bounded catalog candidates, and uses a separate text LLM on ambiguous cases. Deterministic rules validate any proposed match. The framework targets Qwen3-VL-8B-Instruct, Qwen3 embeddings/reranker, gpt-oss-20b and independent PaddleOCR-VL verification. Current readiness and measurements are documented in [Self-hosted infrastructure](docs/self-hosted-infrastructure.md); configured, downloaded and tested states are distinguished. The current catalog contains only 18 provisional product IDs from the earlier seven PDFs. Actual website resolution needs its catalog. See `docs/vision-catalog-design.md` for schema/validation contracts and `docs/logic-architecture.md` for the earlier native engine.

## Run

Start or reuse this project's local model server, then read a document (Python activation is unnecessary):

```powershell
powershell -ExecutionPolicy Bypass -File .\run-local-model.ps1
& .\.venv\Scripts\python.exe reader.py analyze 'data/originals/PO1298947.pdf' --summary
& .\.venv\Scripts\python.exe reader.py analyze 'C:\Users\carlo\Downloads\Full Data Set.zip' --limit 1 --summary
```

Vision is the default engine, using the configured cascade on `http://127.0.0.1:11435`: `qwen3-vl:8b-instruct` extraction followed by selective `gpt-oss:20b` text adjudication, with optional embedding and dedicated reranker services. It accepts PDFs, PNG/JPEG/WebP images, directories, and ZIP collections. Extraction reads each page without catalog context; comparison preserves the immutable source strings. Raw observations and decisions are saved in a review session. A failed page makes the document `partial`. Unavailable optional services are recorded; they are never claimed tested. Progress prints to stderr while JSON results print to stdout.

Inspect/download the target stack and compare PDFs before making catalog decisions:

```powershell
& .\.venv\Scripts\python.exe model_stack.py
powershell -ExecutionPolicy Bypass -File .\setup-model-stack.ps1
& .\.venv\Scripts\python.exe benchmark_vision.py --mode vision --model qwen3-vl:8b-instruct --pipeline cascade --extraction-only --only-labeled --label-file output/vision-gold-representative.json --timeout 600 --output-dir output/new-8b-run
& .\.venv\Scripts\python.exe collect_review.py collect --result output/new-8b-run/vision-benchmark-vision.json --run-id new-8b-run
```

The 4B instruction model remains an explicit baseline: `reader.py analyze FILE --pipeline single --model qwen3-vl:4b-instruct`. The independent verifier requires a separately supported runtime; see the infrastructure guide.

Use the explicit `-instruct` tag. The default `qwen3-vl:4b` thinking checkpoint exhausted the 8,192-token output budget on all three initial real PDF pages, with no completed JSON. An actual diagnostic confirmed its output remained in hidden thinking despite `think=false`; its failed report is retained for comparison.

Use OpenAI after configuring `OPENAI_API_KEY` in the process environment and selecting a supported vision model:

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
& .\.venv\Scripts\python.exe reader.py add SESSION_ID 7050418L 2 --line-id line-1 --unit EA
& .\.venv\Scripts\python.exe reader.py add SESSION_ID 7050718L 3 --line-id line-2 --unit EA --confirm
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
& .\.venv\Scripts\python.exe extract.py 'data/originals/PO-93337.pdf' --render --output output/single
```

`run.ps1` runs the full extraction with rendering. `setup.ps1` recreates missing dependencies from `requirements.lock.txt`; its optional `-PythonPath` accepts another Python 3.12 interpreter. The current environment uses Codex's bundled Python as its base, so retain that runtime or recreate the environment if it moves. Call scripts with `powershell -ExecutionPolicy Bypass -File .\run.ps1` if script policy prevents direct execution; this changes policy only for that process.

## Files and outputs

The PDF ZIP can now be prepared as a private, source-bound VLM dataset with assistant-draft image/JSON labels and a local page review editor. See [VLM dataset workflow](docs/vlm-dataset.md) for `build_vlm_dataset.py`, `build_vlm_review.py`, validation and explicit human release. Drafts stay separate from approved labels; preparing the dataset does not train a model.

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

The native sample measurement is 23/23 source product rows and quantities recovered, 19 matched rows, 4 review rows, and one excluded shipping charge. These seven PDFs also seeded the catalog. The larger ZIP contains 33 PDFs / 45 pages, with eight repeated rendered pages. Two PDFs / 14 product rows have independent visual gold labels in `output/vision-gold-representative.json`; the gold template for the rest contains null unverified expectations. Read measured local vision results in `output/vision-benchmark-vision.json` after running the companion. These are development measurements; the remaining supplier layouts and handwriting need independent labels.

Next integration requires the actual website catalog key/attributes/ordering-unit definitions and cart API/import schema. Complete the corpus labels, evaluate held-out supplier/layout groups, and establish approved customer/supplier identifier crosswalks from authoritative business data. UI/UX belongs in a separate chat.

## Saved context and agent work

Read [the agent handoff](docs/agent-handoff.md) for the published baseline, next priorities, worktree setup and private fixture boundaries. The web demo source is retained under `web/po-reader-mockup/` as regular files with synthetic document assets.
