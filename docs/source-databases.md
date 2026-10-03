# Private source databases

This workstream creates two local SQLite staging databases from the supplied purchase-order PDF corpus and WernerCo, United Kingdom, and Australia product workbooks. The databases preserve source provenance and are intended for inspection and later migration. They are not connected to the application: this checkout does not yet contain the FastAPI/PostgreSQL catalog and review services or a frozen `ProductDocument v1` adapter.

## Files and source scope

The ignored `output/source-databases/database-files/` directory contains:

- `pdf-evidence.sqlite3`: original PDF bytes, page render bytes, native page text, page-level candidate targets, line observations, hashes, and review state.
- `regional-product-catalog.sqlite3`: three separate catalog namespaces, product identifiers and raw labels, names, descriptions, features, language, other non-price/non-media product fields, all imported attribute rows, and detail-section rows.
- `source-databases-manifest.json`: source and database hashes, counts, review eligibility, and platform integration status.

The source files are copied to the ignored `data/source-snapshot/` directory before import. The PDF archive is checked against the existing private VLM snapshot manifest; all PDF members, source bytes, rendered pages, page text, and candidate observation hashes must agree before the build completes. Catalog workbook SHA-256 hashes and source row numbers are retained. Catalog image/digital-asset sheets and image/digital-asset columns are omitted, as are price columns, per request. The three product catalogs remain separate: overlapping IDs are not merged, and tenant assignments are empty pending platform-specific approval.

## Review and training boundary

The PDF records reuse legacy `PAGE_EXTRACTION_SCHEMA` page observations as candidate annotations. They are evidence-backed drafts, not verified labels. Every page and document begins at `pending_human_review`, every training eligibility flag is false, and the `approved_training_examples` view returns rows only after a named human reviewer approves the document and every page with an append-only review event. A note, correction, or model output alone cannot satisfy this gate. At build time, the view has zero rows; the database is therefore not yet a verified training set.

The local review artifact `output/source-databases/pdf-review.html` presents the source pages and pending annotations for human inspection. It stores progress in that browser's local storage and can export review JSON; it is not connected to either SQLite database, and no review-import workflow is implemented yet. Treat exported decisions as review submissions. The `approved_training_examples` view will remain empty until a separately validated import records the required named, page-level events in the evidence database. Do not overwrite source observations or infer ground truth from product matches. Quantity strings and identifier source labels/roles remain source observations; ambiguous product identity or identifier role needs review.

## Local search

The catalog database includes an SQLite FTS5 index over product names, descriptions, and features when the active SQLite build supports FTS5. Search only within the catalog/tenant scope authorized by the eventual platform policy. For example:

```sql
SELECT catalog_id, product_id_display, product_name_raw,
       product_description_raw, product_features_raw
FROM product_text_search
WHERE product_text_search MATCH ?
LIMIT 20;
```

This is text retrieval, not a product match or approval. The PDF database exposes `unique_visual_line_observations` to hide repeated visual-line occurrences for candidate analysis while retaining all original observations in `line_observations`. Quantity values stay raw strings. No product-to-catalog assignments or aliases are seeded by this import.

## Rebuild

Install the project runtime requirements and `requirements.source-databases.txt`, then run from the repository root:

```powershell
python scripts/build_source_databases.py `
  --source-zip data/source-snapshot/corpus/full-data-set.zip `
  --page-dataset output/source-databases/vlm-dataset `
  --catalog-dir data/source-snapshot/catalogs `
  --output-dir output/source-databases/database-files
```

The importer refuses to replace existing databases or its manifest; build into a fresh ignored output directory for a new source revision. It makes no API calls, performs no model matching, and does not train. Keep source snapshots, database files, page images, raw PDF text, review records, and outputs out of Git.

## Current scope limits

The workbook identified as `WernerCo-B2B-products.xlsx` is the third catalog alongside the United Kingdom and Australia exports. Its file name alone does not establish a country/tenant; that mapping remains unassigned. The current SQLite files are staging exports and cannot be connected directly to an application that uses PostgreSQL. A later integration needs an explicitly approved tenant/catalog mapping, a versioned adapter into the project's shared evidence-preserving contract, and application database migrations/API services. All initial catalog matches require human approval.
