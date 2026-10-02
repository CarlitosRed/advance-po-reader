# Evaluating the vision reader

The current framework-aligned cascade, explicit quantity parsing and first 4B/8B results are documented in [self-hosted infrastructure](self-hosted-infrastructure.md) and [first results](framework-first-results.md). [PROJECT_GOAL.md](../PROJECT_GOAL.md) is authoritative; training is deferred. The original failed thinking-model run below remains historical evidence.

`benchmark_vision.py` measures extraction against independently reviewed source labels. It reads PDF members directly from a ZIP in memory, inventories every document, groups duplicates, and optionally runs the existing native reader or the vision reader. Its reports are shadow results: it never calls the cart service.

The supplied `Full Data Set.zip` contains 33 PDFs and 45 pages. `output/vision-gold-representative.json` has manually transcribed expectations for **two PDFs and 14 product rows**, after reviewing all three rendered source pages. These cover a digital truck-equipment order and Kurent's two-page safety-products order, including customer versus vendor identifier labels. They do not establish accuracy on the other 31 PDFs or on handwriting. Catalog product IDs remain null because the website catalog is unavailable.

## Run an inventory and native comparison

From this project directory in PowerShell:

```powershell
.\.venv\Scripts\python.exe benchmark_vision.py --mode inventory --zip 'C:\Users\carlo\Downloads\Full Data Set.zip'
.\.venv\Scripts\python.exe benchmark_vision.py --mode native --zip 'C:\Users\carlo\Downloads\Full Data Set.zip' --label-file output/vision-gold-representative.json
```

Inventory and native modes import no model providers and send no API requests. The inventory uses both PDF text readers and word positions, because a weak `pdfplumber.extract_text()` result can coexist with usable words or `pypdf` text. Full-page RGB renders at PDFium scale 0.75 supply duplicate fingerprints. Page fingerprints describe exact pixels at that resolution, not general semantic similarity.

Reports are saved under the ignored `output/` directory as `vision-benchmark-inventory.json`, `vision-benchmark-native.json`, or `vision-benchmark-vision.json`. Rerunning a mode replaces its report; use `--output-dir output/run-name` to keep different runs. The unverified `vision-gold-template.json` is created only if absent, so an annotation in progress is preserved.

## Run a model comparison

After the chosen Ollama model is available locally:

```powershell
.\.venv\Scripts\python.exe benchmark_vision.py --mode vision --provider ollama --model qwen3-vl:4b-instruct --base-url http://127.0.0.1:11435 --label-file output/vision-gold-representative.json --only-labeled --timeout 600
```

For OpenAI, configure `OPENAI_API_KEY` in the process environment and select a supported vision model:

```powershell
.\.venv\Scripts\python.exe benchmark_vision.py --mode vision --provider openai --model MODEL_NAME --label-file output/vision-gold-representative.json --only-labeled
```

The OpenAI mode exits before provider initialization if a key is absent. Vision mode calls `po_reader.vision.analyze_vision(raw, filename, catalog, provider)` and records source output, match states, model name, usage if supplied, and elapsed time. Page progress and failures are printed as they occur. `--limit N` limits predictions after `--only-labeled` filtering; inventory still includes the full ZIP. Document exceptions, inventory failures, and model page failures produce exit status 1 while preserving completed results from the rest of the run.

## Measured local run on October 1, 2026

The installed `qwen3-vl:4b` model was run against `http://127.0.0.1:11435` with a 300-second request timeout and the two representative labels. All three page responses reached the provider's 8,192-token output limit and were rejected as incomplete. This was an output-length failure, not a request timeout. No page produced a validated extraction, so no identifiers, quantities, units, or PO numbers were available for scoring. No product reached a catalog comparison or automatic match.

| Source | Pages attempted | Document time | Exact source IDs | Exact ID/quantity/UOM rows | Exact PO |
| --- | ---: | ---: | ---: | ---: | ---: |
| Kurent PO 015446 | 2 | 416.234 s | 0/8 | 0/8 | 0/1 |
| Truck Equipment PO 101016 | 1 | 216.219 s | 0/6 | 0/6 | 0/1 |
| Total | 3 | 632.453 s | 0/14 | 0/14 | 0/2 |

The measured document processing time was about 10 minutes 32 seconds, excluding ZIP inventory. Page generation durations reported by Ollama were 213.870, 201.564, and 216.100 seconds. Prompt token counts were 3,979, 3,648, and 4,344, and each output consumed 8,192 tokens. The report records these failed calls and zero recovered rows rather than treating them as missing evaluation cases.

The raw original report is preserved as `output/vision-benchmark-vision-qwen3-vl4b-incomplete-original.json`; `output/vision-benchmark-vision.json` has the same predictions with explicit partial-document and failed-page summary counts. The original loaded harness returned exit status 0 even though the pipeline had recorded page failures; the harness now returns 1 for those internal failures and prints page failures immediately. These results establish that this model and extraction configuration need correction before an extraction accuracy comparison is meaningful. They do not establish how well a completed vision response would read these PDFs.

The current catalog has only 18 sample-derived products. Measuring whether new printed codes were extracted correctly is possible with source labels, while measuring whether they were assigned to the right website product requires separate website catalog labels.

## Label format and evidence

Document labels are keyed by exact lowercase PDF SHA-256, so a filename change cannot silently change the test case. Verified source annotations must set `review_status` to `visually_verified` and record the complete reviewed page set. Unverified templates have null expectations, are not scored, and are never populated from model responses.

```json
{
  "schema_version": 1,
  "documents": [{
    "filename": "sample.pdf",
    "archive_entry": "Full Data Set/sample.pdf",
    "sha256": "EXACT_64_CHARACTER_LOWERCASE_SHA256",
    "review_status": "visually_verified",
    "evidence": {
      "method": "Independent visual transcription from all rendered source pages",
      "pages_reviewed": [1],
      "notes": "Explain any ambiguous text or identifier role."
    },
    "expected": {
      "po_number": "00042",
      "lines": [{
        "line_number": 1,
        "page": 1,
        "identifiers": [{
          "raw_value": "00123-A",
          "printed_label": "VEND-PART#",
          "role": "vendor_product_code"
        }],
        "quantity": "2",
        "uom": "EA",
        "expected_catalog_product_id": null
      }]
    }
  }]
}
```

Supported source identifier roles are `vendor_product_code`, `manufacturer_part_number`, `customer_item_number`, and `unknown`. Keep all visible identifiers on each product row, including distinct fields containing the same string. Use `unknown` when a printed label and context do not establish its role. Do not infer a unit from a quantity or convert packs to eaches. A null `lines` means unverified; an empty list means all pages were independently reviewed and contain zero product rows.

For Kurent, the quantity column prints amounts joined to `ea`; the gold separates the readable numeric amount from the printed unit and uses `EA` for case-insensitive UOM comparison. Page 2 contains totals for eight lines and a quantity due of 158, with no additional product rows. `OUR NUMBER` establishes the customer item role; `VEND-PART#` is populated only for H232005 and R410020LE. The truck-equipment form labels its code column `Part Number`; the gold uses `unknown` for the identifier role because it does not explicitly distinguish vendor code from manufacturer part number.

## Interpreting a report

The report lists labeled coverage before reporting accuracy. It counts exact raw identifier agreement separately from exact identifier-and-role agreement, and exposes quantity and UOM agreements separately. Its main line measure requires exact raw IDs, the numerical quantity, and the UOM. Null field expectations do not receive credit and field-specific label counts show their coverage. Leading zeros, hyphens, and ID suffixes remain significant. Quantities compare as decimal values, so `2` and `2.00` agree; UOM comparison ignores case and outer spacing but does not treat `PK` as `EA`.

Line signatures are compared as multisets rather than by row position. Reordered correct rows get credit, missing rows reduce recall, and extra or repeated product rows reduce precision. Extra identifiers on a row make its ID signature differ from the gold. Exact PO-number agreement is measured separately and preserves leading zeros. An empty extraction has zero recovered rows; it cannot be described as 100% accurate. Failed predictions on labeled documents count as missing fields and rows instead of being removed from the accuracy denominator. Catalog decision correctness is unavailable wherever `expected_catalog_product_id` is null.

Whole PDF byte hashes identify identical documents. Identical rendered page pixels connect documents into a conservative `leakage_group`, including different POs with an identical terms page. Assign an entire group to one development/evaluation split. For a broader accuracy claim, complete independent labels and hold out supplier/layout families, including scans and handwriting; two labeled PDFs are a development sample.
