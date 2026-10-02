# First framework-aligned inference results

Completed October 1, 2026. The updated [project goal](../PROJECT_GOAL.md) adopts the attached research framework while deferring all training and fine-tuning. This is a working pretrained prototype with measured extraction failures, not an approved automatic ordering system.

## Implemented and verified

The local stack now has Qwen3-VL-8B-Instruct, the existing 4B instruction baseline, Qwen3-Embedding-0.6B, a dedicated CPU Qwen3-Reranker-0.6B and a separate gpt-oss-20b adjudicator. Ollama v0.35.0 uses loopback port 11435 and the working Radeon Vulkan backend. The pinned reranker runs on loopback port 11436 in its own CPU environment. `config/model-digests.json` retains the resolved local weight digests and reranker revision; each run also records the models actually used.

The 8B model was loaded with approximately 7.78 GB reported in VRAM at 16,384-token context. The gpt-oss model reported approximately 14.07 GB total loaded size and 10.46 GB in VRAM, using offload. These are actual local runtime observations, not a guarantee that all models fit concurrently. The server limits loading and requests to one at a time.

PaddleOCR-VL-1.6 is **pending** its full supported parser runtime and an independent PDF test. No repeated Qwen call is labeled independent verification. The target verifier and primary deployment sources are documented in [model-stack-sources.md](model-stack-sources.md).

## Corpus and independent evidence

The supplied ZIP contains **33 PDFs and 45 pages**, with eight repeated rendered-page occurrences grouped for future split assignment. An unchanged private copy is retained in `data/corpora/full-data-set.zip`, SHA-256 `b45ca9c36171c7d8d410f2d6ff428b5006100f27a8fa894671ee637367d55e21`. The seven earlier PDFs remain unchanged in `data/originals/`; all seven hashes/sizes passed verification.

Independent development labels cover **two PDFs, three pages and 14 product rows**. Original document identities and source-specific labels are retained in the private evaluation files. All three rendered source pages were checked again against those labels. The other 31 ZIP documents remain unverified. There are no independent authoritative website-catalog labels, so website match accuracy and candidate recall cannot be claimed.

## Visual extraction measurements

The paired v2 runs use the same source labels, page rendering and prompt/schema. The earlier v1 4B run is retained as a development comparison, with its different prompt version explicitly recorded. Requested rendering is 216 DPI under the existing pixel cap. Native text is supplied as separate observations.

| Run | PO numbers | Exact raw identifier sets | Identifier sets and roles | Identifier/quantity/unit after explicit parsing | All those fields including roles | Extracted product rows | Document time |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 4B instruction, prompt v1 | 2/2 | 14/14 | 2/14 | 14/14 | 2/14 | 14 | 383.157 s |
| 4B instruction, prompt v2 | 2/2 | 6/14 | 0/14 | 6/14 | 0/14 | 14 | 458.657 s |
| 8B instruction, prompt v2 | 2/2 | 14/14 | 8/14 | 14/14 | 8/14 | 15 | 791.593 s |

All VLM page requests completed with validated JSON; no model page failed. **Neither labeled 8B document was completely correct.** The 8B reader assigned six real-row identifier roles incorrectly and generated an extra product row on the totals page, combining an account identifier with the total quantity. Its 14/14 raw identifier recovery does not erase these errors. Extra rows remain in precision denominators and review data.

The v2 prompt improved explicit instructions about blank identifier columns and joined quantity/unit cells, but the 4B result regressed on this layout. Both versions are preserved rather than selecting only a favorable measurement. This small development comparison does not establish supplier-disjoint generalization or prove the 8B model superior on all documents.

## Quantity parsing correction and preserved observations

The models returned joined literal values such as `quantity_raw="6ea"` with separately observed `uom_raw="EA"`. The original strict application parser left those quantities unparsed, so the original 8B report recovered only 6/14 identifier/quantity/unit tuples. The application now parses only a positive numeric literal with the exact explicitly observed unit, preserving case/spacing distinctions in the raw source fields. `6ea` with `EA` yields `6`; `006.00ea` preserves `006.00`; missing or mismatched units, exponents, negative values and price prose fail.

This is deterministic parsing of visible characters, not a guessed unit or pack conversion. It does not alter identifiers, roles, page observations or model weights. Provenance is saved in `quantity_parsing`, and source checks corroborate the number/unit pair once. The original reports remain unchanged. Separate `vision-benchmark-vision-quantity-parsed.json` reports record the parent report hash and revised application-level scores; no model call was rerun to produce them. The measurement table above uses those explicitly parsed reports. Raw-model reports remain available for inspection.

## Candidate and adjudication service checks

- Real Qwen embedding calls returned **1,024-dimensional vectors** and completed catalog/query retrieval in **7.984 s** including the initial local model load. Candidate IDs and exact bindings remained intact.
- The pinned CPU reranker returned genuine logit scores, ranking `31334000` first for the Easiway ladder query. Initial download/load/scoring took **148.422 s**; a warm six-candidate call took **3.156 s**. These are service checks against the provisional catalog, not production match accuracy.
- gpt-oss-20b returned validated structured JSON for a real line from the original Selco PDF and selected supplied catalog ID `31334000` with a compatible description. Its first measured call included queueing/loading behind the visual run, so its 192.234 s elapsed duration is not steady-state inference latency.
- A warm reranker → gpt-oss → deterministic-validation check completed in **9.453 s**. The application returned `review_needed` because the directly supplied native line lacked the vision path's required source-validation evidence. No cart service or external order operation was called.

Exact matches can skip adjudication only under narrow source/identifier/full-description/unit checks. Embeddings and reranker scores are suggestions until calibrated. Unavailable stages are explicit. The current catalog has 18 sample-derived products and remains provisional.

## Review collection and validation

New model reports and the explicit-quantity derivative were collected into private pending records under `output/review-data/queue/`. Predictions, canonical suggestions and human corrections are separate. Approval requires a named human reviewer, original PDF bytes, matching document/page fingerprints and complete reviewed expectations. Recollection cannot overwrite corrections; only approved records export into the benchmark gold schema. No new corpus predictions were approved or trained on.

The final code suite passed **124 tests**. Tests cover separate image/text providers, selective adjudication, source disagreement, outside-candidate choices, candidate preservation, real score protocol, embedding dimension mismatch, identifier-role scoring, joined quantity/unit parsing, observation immutability and review approval/export boundaries. PowerShell setup/launch/evaluation scripts parsed successfully, and original PDF integrity checks passed.

Raw results, source-page evidence, service checks, dependency locks, readiness snapshots and comparison summaries are retained under `output/framework-poc-20261001/`. The current source/research checkpoint is `output/checkpoint-self-hosted-inference-v1/`. Model weights stay in their existing ignored directories rather than inside the checkpoint archive.

## Continue from this prototype

Use `run-framework-evaluation.ps1` to repeat the paired visual test with current code and approved labels in a fresh output directory. Use `collect_review.py` to collect and explicitly approve source-backed corrections. The next reliability work is the independent Paddle parser, reviewing additional supplier/layout families and resolving the totals-page/role failures. Keep automatic acceptance disabled for unresolved observations. Training remains a later decision after enough approved, diverse labels and held-out evaluation exist.
