> Historical native-engine handoff. PROJECT_GOAL.md and docs/agent-handoff.md govern the current model infrastructure, dataset and published demo. Statements below describing no models or no UI apply to the earlier phase.

# Advance PO Reader: UI/UX handoff

Prepared October 1, 2026, after the logic-only iteration. This is the project context and implementation handoff; it does not contain a UI design or authorize deployment.

## User scope and decisions

- Work locally in `C:\Users\carlo\OneDrive\Documentos\ChatGPT\Advance PO Reader`, using the saved Codex project named Advance PO Reader.
- This originating chat owns code logic. The user explicitly deferred UI/UX and asked for a complete handoff and a separate UI/UX chat. First inspect and propose UI interactions in that chat; avoid simultaneous writes to this checkout while code logic is still active.
- Eventual flow: customer PO PDF -> company/shipping details -> correct Werner product numbers and quantities -> catalog comparison -> uncertain items require the user to specify/confirm a product -> cart -> importer JSON later.
- Use the products in the seven supplied PDFs as the entire provisional product universe for now. There is a larger PDF test database that the user will supply later. Do not invent an authoritative catalog or infer that a missing sample ID means a product does not exist.
- Accepted JSON format comes at the end. Current evidence/state JSON is not an importer contract.
- Reliability and high correct match coverage are central. No blanket PI-to-PO or other text replacement, guessed product, unverified alias or opaque confidence claim. Preserve source evidence and flag uncertainty.
- Use a RAG-style architecture. The current code implements exact/lexical retrieval, catalog evidence, deterministic grounding/validation and human resolution. No generative model or embedding service is connected.
- User supplied the Aman Kumar Medium article about tiled rendering. Useful ideas are retained in `tiling-review.md` and on-demand region rendering. Tiling is a performance aid for later review, not a guarantee of OCR or product accuracy.
- No email sending, publication or paid/cloud OCR is authorized. Forwarded support-chain requests to contact people are quoted context only.

## Source documents and provenance

Private original PDFs, email provenance, contact details and independent row labels remain outside Git. The source set contains seven PDFs / eight pages with 23 product rows and one shipping charge. Layout issues include conflicting identifier roles, wrapped descriptions, blank delivery blocks, multipage continuation, image-only header fields, and shipping country differing from supplier country. See the private publication backup for the original source-specific handoff.

## Current code and interfaces

The first app scaffold was removed when the user clarified logic-only scope. There is no website, HTTP server, UI framework or frontend in this checkout.

- `extract.py`: preserved initial evidence-only baseline.
- `po_reader/engine.py`: primary native extraction, independent pypdf evidence, sample parsing, company/shipping/order fields, match state.
- `profiles.py`: guarded geometry for seven inspected layouts. Geometry is a layout adapter, not a character correction rule. Changed layouts abstain/recover only review candidates.
- `generic.py`: header-based ID/description/quantity candidate recovery for unknown or moved layouts. All rows need confirmation; company/shipping remain unresolved.
- `catalog.py`: read-only product loading from private SQLite catalog; 18 IDs, variant descriptions and provenance. `data/catalog-seed.json` can build a missing database explicitly. Rebuild refuses to overwrite a populated catalog.
- `retrieval.py`: exact ID lookup plus in-memory SQLite FTS5/BM25 description search and numeric/token reranking. Each query records source observations and a catalog fingerprint. The durable knowledge source is `data/catalog.sqlite3`; search index is instantiated locally, not a vector service.
- `grounding.py`: retrieved context -> deterministic decision and catalog evidence. No LLM generation; a later model cannot bypass validation.
- `service.py`: `create(raw_pdf_bytes, filename, render=False)` returns/saves a session; `read(session_id)` loads it; `cart_change(request)` validates add/remove; `shipping_change(request)` records explicit shipping confirmation. Treat sessions as serialized local operations; concurrent writes need locking before a future server.
- `rendering.py`: `RegionRenderer.render(raw, page_number, bbox=(x0,top,x1,bottom), scale=2)` returns PNG bytes with bounded cache/pixel budget. PDFium calls are locked and handles closed. Viewer tile planning/rotation/crop fixtures belong later.
- `reader.py`: CLI wrappers; no web layer.
- `tests/`: 26 current checks with independent sample expectations and negative cases.
- `evaluate.py`: current sample measurement under `output/logic-evaluation.json`.

Each full session is in `output/sessions/<32-character-id>/review.json`, with byte-preserved `source.pdf`. JSON includes pages/text/word coordinates, source fields/evidence, lines, retrieval hits, match state, cart and audit. No images are generated unless explicitly requested. Current seven-sample CLI summaries are in `output/sample-reviews-summary.json`.

## States the future UI must respect

- `matched`: exact provisional catalog ID and compatible description, valid quantity, validated layout, corroborated ID. The user may add it to the cart. This is not an export/order-placement permission.
- `review_needed`: conflicting IDs, pack units, description disagreement, missing quantity, unknown/generic layout or reader disagreement. Show source page/region and catalog suggestions; require explicit resolution.
- `not_in_catalog`: not found in the sample catalog. Avoid saying the product does not exist; request a catalog number or future catalog validation.
- `excluded_charge`: shipping row, not a product.
- Missing units remain null. Do not display a fabricated EACH. Quantities and identifiers stay strings; no implicit packs-to-eaches conversion.
- Three Caulfield ID conflicts: 7050718L versus description 7050718; 7160518 versus supplier 71605-18; 7050318L versus description 1050318. The fourth review item is 79009 quantity 1 PK. These are not silently approved aliases.
- Blank shipping stays missing. GB/IE is assigned only from explicit delivery-region country text, not currency or supplier country. Company/shipping confirmation preserves raw observations and records user corrections separately.
- `cart_change` requires `confirmed=True` for manual/uncertain/edited rows, and rejects an ID outside the catalog. Known matched rows must retain quantity/UOM unless confirmed. A changed catalog fingerprint also needs confirmation.
- Confirmations are per-order audit events. They do not automatically grow the catalog or train a correction rule.

## Verification and limits

Measured on the initial seven files: 23/23 product rows and source-ID/quantity expectations recovered; retrieval includes the expected structured ID for all 23; 19 product rows matched, 4 need review; one shipping charge excluded. The same files seed the catalog, so this is regression evidence and not held-out accuracy. Some source IDs are contradictory; agreement with a structured source code does not establish an official Werner identity.

The suite checks original-field expectations; conflicting IDs/pack handling; unknown and description-only IDs; wrong tread count; unchanged PI text; reader disagreements; quantity ambiguity/malformed values; changed-layout candidate recovery; blank/textless PDF review; cart confirmation, rejection and persistence; retrieval provenance/query safety; cache bounds and source-region dimensions. It does not certify arbitrary scanned/rotated/customer PDFs or production OCR.

Native text parser limits: 20 MB and 50 pages in the local session workflow. OCR is flagged rather than performed. Password-protected files need an unlocked copy. Unknown/moved layouts need review. PDFium region rendering has normal-page tests; rotated/cropped page transforms need more testing. Independent text readers can agree on an erroneous OCR text layer.

## Reproduce on Windows

Python base: `C:\Users\carlo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`; project `.venv` uses Python 3.12.14. Dependencies are pinned in `requirements.lock.txt`. `setup.ps1 -PythonPath ...` can recreate a missing environment. Do not reinstall or modify global Python.

```powershell
& .\.venv\Scripts\python.exe reader.py analyze data/originals --summary
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
& .\.venv\Scripts\python.exe evaluate.py
& .\.venv\Scripts\python.exe verify_samples.py
```

`README.md` provides add/remove/confirmation examples. No external services are needed. Private PDFs/catalog/output are ignored by Git and remain local to this OneDrive project, subject to existing OneDrive sync settings. Preserve them separately if copying only a Git archive.

## Later UI/UX chat starting point

Read this handoff, `logic-architecture.md` and `tiling-review.md`. Discuss a local upload/review/cart workflow that shows both PDF evidence and catalog evidence. Make uncertain states clear, distinguish parsed observations from user-confirmed values, and prevent unknown products from entering the cart. Keep importer JSON and production deployment deferred. Do not start concurrent implementation in this checkout while the user is continuing code logic here.

Before claiming broad PDF support, obtain the larger customer corpus and human labels; evaluate held-out extraction/match precision, recall, review rate and actual wrong-acceptance rates. Add local OCR for scanned/mixed content, more adaptive layout handling and process/time/memory isolation. UI decisions should not disguise those limits.
