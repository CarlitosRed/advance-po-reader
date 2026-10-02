# Extracted research framework

Text and links extracted from the attached DOCX. The original DOCX is the research authority; this companion is searchable text. Benchmark claims below are source claims, not measurements on this project corpus.

Self-Hosted Document Understanding& Product Matching Architecture

Deep-research recommendation for receipts, purchase orders, PDFs and images

Goal: maximum extraction reliability while keeping the full stack on infrastructure you control.

Recommended stackQwen3-VL-8B (fine-tuned) for semantic document extraction → deterministic candidate retrieval + Qwen3 Reranker for catalog matching → gpt-oss-20b only for ambiguous cases. Use PaddleOCR-VL-1.6 as an independent high-fidelity visual verifier on risky pages/fields.

Research scope: 18 targeted Exa search queries (132 returned result slots before deduplication), then primary-source validation against model cards, repositories, and academic papers.

Executive recommendation

The short versionFor your use case, the best answer is not “pick one OCR model.” It is a controlled cascade. The vision model should extract what the document actually shows; the matching system should separately decide which canonical database product it corresponds to. Never let the second stage overwrite the first.

If I had to choose one visual model to build around today, I would choose Qwen3-VL-8B and fine-tune it on your own schema and documents. ReceiptBench (ACL 2026) is unusually relevant because it measures real receipt/invoice extraction rather than generic OCR. The base Qwen3-VL-8B scored 0.6545 overall F1; supervised fine-tuning raised it to 0.7736, and the paper’s SFT+GRPO recipe reached 0.7950. The key lesson is not the exact number: domain alignment mattered more than raw parameter scale. [1][2]

For pure page parsing fidelity, however, PaddleOCR-VL-1.6 is too strong to ignore. It is a compact 0.9B vision-language document model and its current 2026 release reports 96.33% on OmniDocBench v1.6, including strong text, table, formula and real-world distortion performance. It is not “Tesseract plus an LLM”; the recognition component is a VLM, although the complete Paddle pipeline also uses a separate layout-analysis stage. [3][4]

For database reconciliation, the main engine should not be a general LLM. Use deterministic candidate generation and a specialized reranker first. Then use a reasoning LLM only on the hard tail. My default local adjudicator is OpenAI gpt-oss-20b: Apache 2.0, structured outputs, fine-tunable, 21B total / 3.6B active parameters, and officially designed to run in about 16 GB of memory. [5]

Why Donut is no longer my first choice

Donut was an important architectural breakthrough: ECCV 2022 showed that document understanding could map pixels directly to structured text without an external OCR engine. That is exactly the direction you were asking for. But it is now a four-year-old baseline, its official environment is tied to older dependency versions, and 2025–2026 document VLMs have substantially improved high-resolution perception, long-document handling and reasoning. I would keep Donut as a historical baseline, not as the foundation of a new B2B system. [6]

How I evaluated the options

Evidence first: priority to first-party model cards/repositories and peer-reviewed or primary research papers.

Task fit over generic leaderboards: receipts and purchase orders require exact character perception, schema adherence, nested line items, normalization and semantic reasoning.

Self-hosting: open weights, commercial usability, practical single-server deployment and fine-tuning mattered.

Reliability architecture: I favored systems that can preserve evidence, abstain, and be independently verified rather than systems that simply generate plausible JSON.

Benchmark caution: OmniDocBench, ReceiptBench and entity-matching benchmarks measure different things; their scores should not be compared as if they were one leaderboard.

1. Best visual/document model

Model | What it is | Evidence relevant to your use case | Main weakness | Role I would give it
Qwen3-VL-8B | General open-weight VLM; image + text → text/JSON | ReceiptBench: 0.6545 base; 0.7736 after SFT; 0.7950 with SFT+GRPO. Strong OCR, long-document parsing, reasoning. Apache 2.0. [1][2] | Heavier than a dedicated parser; dense tiny text can still cause digit confusions. | PRIMARY semantic extractor; fine-tune to your JSON schema.
PaddleOCR-VL-1.6 | 0.9B document VLM plus layout-analysis pipeline | 96.33% on OmniDocBench v1.6; strong tables/text/formulas and real-world distortions. [3][4] | Full system is two-stage; strongest evidence is page parsing, not catalog-level semantic reasoning. | SECONDARY parser/verifier; excellent for difficult pages and audit evidence.
olmOCR-7B | Open document/PDF parsing system | ReceiptBench specialized-model score 0.6228 in the ACL study. [1] | Less compelling than fine-tuned Qwen for structured business reasoning. | Benchmark candidate, not first choice.
DeepSeek-OCR-small | Specialized visual document model | ReceiptBench score 0.3959 in that specific structured-receipt evaluation. [1] | Strong perception ideas do not automatically translate into structured business extraction. | Research candidate only.
Donut | OCR-free image-to-sequence document transformer | Pioneered external-OCR-free document understanding in 2022. [6] | Older architecture/tooling; surpassed by newer document VLMs. | Historical baseline.

Figure 1. ReceiptBench comparison. These numbers come from one benchmark and do not imply universal superiority; they do show the large value of domain-specific fine-tuning. Source: [1].

“OCR-free” versus computer vision: an important terminology point

A vision-language model still has to recognize characters from pixels. In that literal sense, it is performing optical character recognition internally. “OCR-free” in papers such as Donut means there is no separate, off-the-shelf OCR engine producing tokens and bounding boxes before the neural model. Your requirement is better described as a vision-first or end-to-end document model. Qwen3-VL satisfies that architecture; PaddleOCR-VL uses a VLM for recognition but its full document pipeline also performs explicit layout analysis.

2. The architecture I would actually deploy

Figure 2. Recommended self-hosted cascade. The critical separation is between “what the document showed” and “which catalog entity it matches.”

1.  Rasterize every PDF page to a high-quality image. Use roughly 200–300 DPI as a starting point. This is not OCR; it is simply turning the page into pixels so the VLM sees the same visual evidence a person would.

2.  Run Qwen3-VL-8B with a strict extraction schema. Extract raw product ID, product text, quantity, unit, price, vendor, page number and—where supported—visual location/evidence. Missing fields must remain missing rather than being guessed.

3.  Preserve the raw extraction immutably. Never replace raw_product_id with a guessed canonical ID. The raw value is your audit trail.

4.  Generate database candidates deterministically: exact normalized ID first; then weighted edit distance for likely visual confusions; then semantic retrieval over product name/description/vendor if the identifier is damaged or absent.

5.  Rerank only the top candidates using Qwen3-Reranker (0.6B or 4B). This is cheaper and more stable than asking a general LLM to reason over the full database. [7]

6.  Send only ambiguous top-K candidates to gpt-oss-20b. Force a structured output such as match / no_match / abstain, selected candidate ID, evidence fields, contradiction list and a machine-readable reason code. [5]

7.  For high-value or low-confidence cases, run PaddleOCR-VL-1.6 independently on the relevant page/crop. Agreement between independent models is a stronger reliability signal than an LLM saying it is “95% confident.”

8.  Auto-accept only when deterministic rules and model evidence agree; otherwise abstain or route to a human reviewer. Log the review decision so it becomes future training data.

3. Best local model for matching the JSON to your product database

Recommended division of laborUse Qwen3 Embedding / Reranker for the normal case. Use gpt-oss-20b for ambiguous adjudication. If you use gpt-oss-20b for every row, it will work, but you will spend far more compute than the task requires and make the system harder to calibrate.

Component | Recommended model/algorithm | Why
Exact / near-exact ID lookup | SQL + normalization + weighted Levenshtein/Hamming | A product code such as 1112 vs 1113 is fundamentally a constrained string-matching problem. Deterministic logic is faster, auditable and safer than generative correction.
Semantic candidate retrieval | Qwen3-Embedding-0.6B or 4B | Apache 2.0; designed for retrieval; multilingual; converts names/descriptions into vectors so a damaged ID can still retrieve plausible catalog products. [7]
Candidate ranking | Qwen3-Reranker-0.6B or 4B | Dedicated cross-encoder reranker. It compares the extracted record with each candidate directly and is purpose-built for ranking. [7]
Ambiguous decision | gpt-oss-20b | Apache 2.0, structured outputs, fine-tunable, strong reasoning, ~16 GB official memory target; ideal for the small fraction of cases where rules/reranking disagree. [5]
Later high-volume optimization | Distilled cross-encoder / small classifier | Recent 2026 product-linking work supports retrieve → lightweight match → escalate. Once you have approved labels, distill the expensive decisions into a cheaper matcher. [8]

Why gpt-oss-20b is my default adjudicator

It is actually self-hostable: OpenAI publishes the weights and says the 20B model can run with about 16 GB of memory. [5]

Its Apache 2.0 license is straightforward for a commercial B2B application, subject to the model’s usage policy. [5]

It supports structured outputs and fine-tuning, which matters more here than conversational style. [5]

It is text-only—which is a benefit at this stage. The visual interpretation has already happened; the matcher should reason over extracted facts and a small candidate set, not reinterpret the page.

It is large enough to handle contradictions such as “ID is one digit off but brand, package size and vendor SKU all agree,” while still being practical on one server.

I would not choose Jellyfish-7B as the production default even though it is explicitly trained for entity matching and data preprocessing. It is academically relevant and demonstrates that 7–13B local models can do entity matching, but the published Jellyfish-7B checkpoint is CC BY-NC 4.0, which is a poor fit for a commercial B2B deployment. Its base model is also older. [9][10]

The strongest architectural evidence: retrieval, matching, escalation

A 2026 paper on product linking describes almost exactly the architecture that makes sense here: retrieve plausible catalog candidates, use a lightweight cross-encoder for the high-confidence majority, and escalate only ambiguous cases to a more capable model. The reported system calibrated auto-acceptance at a 98% precision bar; escalating the difficult tail improved end-to-end coverage while avoiding expensive model calls on easy pairs. This is much closer to your real problem than a generic “best LLM” benchmark. [8]

Likewise, entity-matching research in EDBT 2025 found that open LLMs can approach hosted LLM performance with small amounts of task-specific data or explicit matching rules, and that LLMs generalize better to unseen entities than traditional fine-tuned PLMs in many settings. But the same body of work reinforces that prompt/model behavior varies by dataset—another reason to benchmark on your product catalog rather than trust a generic ranking. [11]

4. How to “bulletproof” the PDF reading layer

Failure mode | Protection
Tiny or blurred characters | Render at sufficient DPI; retain original crop; retry only the affected region at higher resolution; cross-check with PaddleOCR-VL.
1/7, 0/O, 5/S, 8/B and similar ID confusions | Use a catalog-aware confusion-cost matrix in candidate generation. Do not alter the raw extraction.
Different receipt/PO layouts | Fine-tune Qwen3-VL on vendor-diverse examples; stratify training by vendor/layout; hold out entire vendors during evaluation.
Model hallucinates a missing field | Schema rule: missing means empty/absent. Reward/validate abstention. ReceiptBench specifically shows hallucination as a major failure mode. [1]
Long multi-page PO | Process pages individually for visual fidelity, then aggregate line items with stable page/row identifiers. Avoid one giant prompt when page-level evidence can be preserved.
Duplicate/near-duplicate catalog products | Return top-K candidate evidence; require discriminating fields (pack size, brand, vendor SKU, UPC/EAN, unit). Abstain when no field uniquely resolves the candidate.
LLM invents a plausible canonical ID | The LLM may select only from candidate IDs supplied by the database. It cannot author a new canonical ID.
False confidence | Do not trust self-reported confidence. Use measurable signals: candidate score margin, exact field agreement, independent parser agreement, rule checks and calibrated historical error rates.
Silent model drift after an upgrade | Pin model/version hashes; maintain a gold evaluation set; run regression tests before every model or prompt update.

5. Keep raw extraction and canonical matching as two different records

A robust data contract should look conceptually like this:

{  "raw_extraction": {    "line_items": [{"raw_product_id": "1113", "raw_description": "Widget 10 mm blue", "page": 2}]  },  "catalog_resolution": {    "selected_product_id": "1112",    "candidate_ids": ["1112", "1118"],    "decision": "match",    "reason_code": "VISUAL_ID_1_CHAR_OFF_DESCRIPTION_EXACT",    "second_vision_model_agrees": true  },  "audit": {"vision_model": "qwen3-vl-8b@pinned", "matcher_model": "gpt-oss-20b@pinned"}}

Notice that raw_product_id remains “1113.” The system can conclude that the canonical catalog product is 1112, but it never pretends the document visually contained 1112. That separation is what makes the workflow auditable and safe to improve later.

6. Training strategy: do not train from scratch

1.  MVP: use the pretrained models with strict prompts and your database. Build the end-to-end evaluation harness before fine-tuning anything.

2.  Create a gold set of representative documents. Start with several hundred; include many vendors, layout families, poor scans, photos, rotated pages and genuinely ambiguous products. Keep a vendor-disjoint test set.

3.  Fine-tune Qwen3-VL-8B with supervised examples mapping page images to your exact JSON schema. LoRA/QLoRA is the pragmatic first step; full pretraining is unnecessary.

4.  Measure field-level exact match separately for product ID, description, quantity and price. A single averaged “document accuracy” can hide catastrophic ID errors.

5.  Only consider reinforcement/alignment training after supervised fine-tuning is stable. ReceiptBench shows GRPO can improve Qwen3-VL, but it also documents instability on smaller models. [1]

6.  Use human-approved catalog matches to train or distill the reranker. Over time, the general LLM should handle fewer cases, not more.

7.  Never continuously self-train on the system’s own unreviewed predictions. That turns extraction mistakes into labels and can amplify error patterns.

7. Acceptance test before production

Metric | Why it matters | Suggested target for pilot
Raw product-ID exact match | Measures visual fidelity before database help | Track by vendor/layout; maximize, but do not hide errors with fuzzy matching.
Candidate recall@5 | Did retrieval include the true catalog item? | ≥99.5% on the gold set before tuning auto-accept thresholds.
Auto-match precision | Wrong canonical products are often worse than abstentions | Target 99%+ for auto-accepted cases; adjust threshold to business risk.
Auto-match coverage | How much work is handled without humans | Optimize only after precision is safe.
Abstention quality | Does the system refuse genuinely ambiguous cases? | False certainty should be rarer than human review.
Per-vendor worst-case | Averages can hide one broken supplier format | Set a minimum floor per important vendor.
Latency / GPU-seconds per page | Determines hosting economics | Measure each stage separately; keep gpt-oss off the easy path.

8. Practical self-hosting footprint

A sensible first production target is one NVIDIA GPU server in the 24–48 GB VRAM class, plus ordinary CPU/RAM for PDF rendering, the database and orchestration. Qwen3-VL-8B is comfortable with more headroom at native precision; quantization can reduce the footprint substantially. PaddleOCR-VL-1.6 is only 0.9B parameters and is comparatively light. OpenAI explicitly states that gpt-oss-20b can run in about 16 GB of memory. [3][5]

You do not need all models resident at full precision simultaneously. In production, you can run the parser and reranker continuously, keep the larger adjudicator in a separate inference service, or load it only for the ambiguous queue. At higher volume, separate GPU services let you scale each stage independently.

Final decision

If I were building your first version nowI would start with Qwen3-VL-8B + Qwen3-Embedding/Reranker + gpt-oss-20b, all self-hosted. I would add PaddleOCR-VL-1.6 as the independent verifier, not as the sole source of truth. I would not start with Donut, and I would not train a document model from scratch.

The deepest reason is system design: your database is an enormous source of prior information. The visual model does not need to be infallible by itself; it needs to be faithful enough to produce evidence. The catalog matcher can then use ID similarity, descriptions, vendor constraints and package attributes to recover from perceptual noise—but only in a constrained, auditable way. That turns a brittle “AI reads a receipt” demo into an enterprise data pipeline.

Recommended 4-week proof of concept

Week | Build | Exit criterion
1 | Upload API, PDF rasterization, product DB candidate service, evaluation dataset format. | 100–200 documents can run end-to-end with raw outputs logged.
2 | Qwen3-VL-8B extraction prompt/schema; exact + fuzzy + semantic candidate retrieval; Qwen3 reranker. | Measure raw ID accuracy, recall@5 and match precision.
3 | gpt-oss-20b adjudicator; PaddleOCR-VL verifier; abstention and audit logging. | Auto-accept threshold reaches target precision on held-out data.
4 | LoRA fine-tune Qwen3-VL on approved examples; regression test; package services in containers. | Fine-tuned model beats prompt-only baseline without worsening worst-vendor error rate.

Sources

[1] Wang et al. (ACL 2026), “From Recognition to Reasoning: Benchmarking and Enhancing MLLMs on Real-World Receipt Document Understanding” (ReceiptBench). Source

[2] Qwen3-VL official repository / model card. Source

[3] PaddleOCR-VL-1.6 official PaddleOCR documentation. Source

[4] PaddleOCR official repository and 2026 release notes. Source

[5] OpenAI gpt-oss-20b official model card / documentation. Source

[6] Kim et al. (ECCV 2022), “OCR-free Document Understanding Transformer” (Donut). Source

[7] Qwen3 Embedding & Reranking official release (0.6B/4B/8B; Apache 2.0). Source

[8] Wang et al. (Aug. 2026), “Retrieve, Match, Escalate: Accurate and Scalable Product Linking with VLM-Distilled Cross-Encoders and Agentic VLMs.” Source

[9] Zhang et al., “Jellyfish: A Large Language Model for Data Preprocessing.” Source

[10] Jellyfish-7B model card (license and checkpoint details). Source

[11] Peeters, Steiner & Bizer (EDBT 2025), “Entity Matching using Large Language Models.” Source

[12] Qwen3-Reranker-0.6B model card. Source

[13] OpenAI gpt-oss-20b developer model page. Source

Research note: Dated 1 October 2026. Benchmark your exact documents and catalog before production; this recommendation prioritizes task-specific evidence and controllable failure modes over generic leaderboards.

## Original source hyperlinks

- https://aclanthology.org/2026.acl-long.2135/
- https://github.com/QwenLM/Qwen3-VL
- https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/algorithm/PaddleOCR-VL/PaddleOCR-VL-1.6.md
- https://github.com/PaddlePaddle/PaddleOCR
- https://openai.com/index/gpt-oss-model-card/
- https://www.ecva.net/papers/eccv_2022/papers_ECCV/html/8042_ECCV_2022_paper.php
- https://qwenlm.github.io/blog/qwen3-embedding/
- https://arxiv.org/abs/2608.25037
- https://arxiv.org/html/2312.01678v4
- https://huggingface.co/NECOUDBFM/Jellyfish-7B
- https://openproceedings.org/2025/conf/edbt/paper-81.pdf
- https://huggingface.co/Qwen/Qwen3-Reranker-0.6B
- https://developers.openai.com/api/docs/models/gpt-oss-20b
