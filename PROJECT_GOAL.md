# Advance PO Reader working goal

Updated October 1, 2026 from Carlos's attached research framework and current instructions.

Build a self-hosted document-understanding and product-matching system that reads customer purchase orders, invoices and images faithfully, preserves their source evidence, and resolves requested products against an authoritative catalog through a controlled cascade. Measure extraction and matching separately, abstain on unresolved evidence, and retain human corrections for possible future training.

## Framework and instruction precedence

The retained research authority is [Self Hosted Document AI Recommendation 2026](docs/research/self_hosted_document_ai_recommendation_2026.docx). Its searchable companion is [framework-extracted.md](docs/research/framework-extracted.md), and its SHA-256 is recorded in `docs/research/framework-manifest.json`. Research benchmark figures are external source claims, never measured accuracy on our PDFs. Model availability and deployment details must be checked against official sources.

Carlos's current instruction overrides the framework's proposed week-four fine-tuning: **do not train, fine-tune, run LoRA/QLoRA/GRPO, or treat model predictions as ground truth yet**. The corpus is too small. In this phase, creating the visual model means configuring an existing pretrained VLM and its inference/evaluation pipeline. Use the provided PDFs as development and test evidence, collect observations, compare them with independently reviewed PDF labels, and record corrections. Model weights remain unchanged.

## Target architecture

1. Render PDFs locally at approximately 200–300 DPI, preserving document hashes, page numbers and images. Native PDF text is separate corroborating evidence where available.
2. Use pretrained **Qwen3-VL-8B-Instruct** as the primary semantic extractor with a strict JSON schema. Preserve exact printed identifiers, labels/roles, descriptions, quantities, units, prices and page evidence. Missing fields stay missing.
3. Preserve raw extraction independently of catalog resolution. Generate bounded catalog candidates using exact identifiers, conservative visual-confusion similarity and, when available, **Qwen3-Embedding-0.6B** semantic retrieval. Fuzzy candidates never silently repair a printed identifier.
4. Rank retrieved candidates using **Qwen3-Reranker-0.6B**, through a real reranking/scoring interface. A generative chat call is not a substitute for cross-encoder scores. Scores are ranking signals until calibrated against approved labels.
5. Use pretrained, text-only **gpt-oss-20b** only to adjudicate ambiguous candidate sets, with structured decisions and contradictions. Exact cases should not require this model.
6. Add **PaddleOCR-VL-1.6** as an independent visual verifier for risky pages/fields once its supported inference runtime is available. Agreement of repeated calls to Qwen alone is not independent verification.
7. Apply deterministic validation and route uncertainty to review. Initial runs produce shadow decisions and local review records. Production catalog integration and external cart writes require the actual catalog and API contract.

The existing `qwen3-vl:4b-instruct` remains a resource-conscious comparison baseline. Using it does not establish that the recommended 8B extractor was evaluated. Target components that are unavailable must be reported as unavailable, not silently substituted or claimed active. Model names, digests, prompt/schema versions, corpus hashes, execution settings and stage durations belong in run records.

## First phase deliverables

Carlos's subsequent October 1, 2026 instruction requests a trainable dataset from the supplied ZIP PDFs. Prepare source-bound page images and strict-schema candidate JSON targets in portable training formats, with duplicate-safe proposed splits and a concrete human-review path. Dataset preparation is authorized; training remains deferred, and assistant transcriptions must stay pending until explicit human review and release.

- A saved project goal and research source that future work can read.
- Configurable, separate VLM extraction and LLM adjudication infrastructure with local inference as the default.
- A repeatable PDF corpus inventory and visual-inference run, preserving raw observations, page failures and comparison artifacts.
- An annotation/review collection format tied to source hashes and page evidence. Unreviewed observations remain predictions and cannot become approved labels automatically.
- Stage-level measurements for exact identifiers, PO numbers, line recall, quantity/unit agreement, review/failure rates and latency where independent labels exist. Unlabeled PDFs receive no invented accuracy score.
- Honest machine/runtime readiness for the target stack, with installation and execution instructions for components awaiting hardware or a supported runtime.

## Data and evaluation boundaries

The seven PDFs in `data/originals/` and the provided `Full Data Set.zip` retained privately as `data/corpora/full-data-set.zip` are the current source corpus. Its original-byte hash is recorded in `data/corpora/manifest.json`. Inventory live contents before reporting counts. Keep exact and visually duplicated pages together in future splits; hold out supplier/layout families once sufficient labels exist. Current development labels and sample-derived catalog records do not establish generalization or authoritative website matches.

Only human-reviewed corrections tied to the original PDF can become approved reference data. Never overwrite stronger reviewed labels with model output. Compare the native reader, 4B baseline and 8B target on the same labeled cases and configuration where feasible. Keep failed/partial documents in the denominator.

## Completion and later milestones

The first phase is complete when goal/context files are updated, local pretrained visual inference runs on supplied PDFs, results and independent-label comparisons are persisted, review data can be collected without training, and unavailable target services are documented with explicit readiness evidence. Installing/configuring a service alone does not verify its end-to-end behavior.

Later work requires an authoritative website catalog and cart schema, more vendor-diverse reviewed documents, held-out evaluation and approved operational thresholds. Training is a separate future decision after enough approved data exists; production deployment requires separate validation. The framework's suggested accuracy targets are aspirations pending measurement, not current guarantees.
