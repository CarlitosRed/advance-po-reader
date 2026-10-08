# Product line assessment and JSON workflow

> **Historical assessment:** This document describes the earlier local native-PDF and self-hosted prototype against a private sample corpus. It is retained as evidence and design history. Read [PROJECT_GOAL.md](../../PROJECT_GOAL.md) for current scope. Historic CLI behavior and measurements do not describe the FastAPI backend, shared ProductDocument contract or web UI, which have since been implemented in `backend/` and `web/local-reader/` (see PROJECT_GOAL.md Current scope).

User clarified the eventual goal after initial setup: upload a customer purchase order PDF and obtain an importable JSON file listing the Werner products requested. Subsequent instructions deferred the accepted JSON format and authorized a provisional catalog containing only products in these PDFs. The current logic extracts fields and rows, retrieves product evidence and stages reviewed choices; no UI is included. See `logic-architecture.md` for current implementation. Do not call the internal evidence/review JSON importable.

The following is based on extracted text and visual review of all eight sample pages. Quantities and identifiers below are representative source evidence, not catalog-validated mappings.

Private per-document row transcriptions are retained locally rather than published. Observed mapping issues include customer-versus-supplier identifiers, identifiers embedded in wrapped descriptions, charge rows, continued tables, conflicting codes and pack units.

There are 23 visually identified product rows plus one shipping-charge row across the sample set. This count describes source rows, not unique catalog products or confirmed valid import records.

## Decisions needed for trustworthy output

1. Later, obtain a real accepted JSON example or importer schema: required keys, nesting, order header requirements, identifier expectations, quantity type, UOM, optional pricing, and error behavior. This is not a prerequisite to the current logic work.
2. The current provisional catalog uses the sample products under the user's instruction. Before production use, obtain an authoritative Werner catalog or lookup method. Distinguish customer SKU, MPN, supplier reference, and text-embedded codes. Preserve codes as strings; never silently fuzzy-match a description to a product.
3. Define quantity/UOM rules, especially packs, suffixes, fractional quantities, and conversions. Source quantity should retain its raw representation; parsed quantities should use exact decimal handling, not binary floats.
4. Decide handling of charges, unsupported products, conflicting codes/descriptions, missing fields, repeated lines, and manual review. Missing catalog/schema means unresolved records, not guessed imports.
5. Build region/row extraction that joins wrapped descriptions, handles multipage continuation, removes repeated headers, and retains source page and bounding-box evidence.
6. Validate each sample against human-verified line expectations, then serialize only accepted records to the agreed import schema. Keep audit/evidence JSON separate from the importer payload.

## Suggested logic discussion

Current pipeline: native PDF text/positions -> validated row extraction or generic review candidates -> sample-catalog retrieval -> grounded deterministic validation -> explicit resolution -> internal cart. Company and shipping evidence are part of the current scope. OCR and importer-schema export are later extensions.

Sample-validated parsing and retrieval-grounded matching are implemented. Production reliability, local OCR and importer-schema export remain unverified or unimplemented.
