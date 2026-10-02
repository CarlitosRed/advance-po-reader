# Agent handoff — October 2, 2026

Read PROJECT_GOAL.md first. It governs the current pretrained inference/evaluation phase and overrides older native-parser design notes. The retained research DOCX, its searchable text and original-byte manifest are under docs/research/. Training and fine-tuning remain deferred. Dataset drafting is authorized; assistant transcriptions require named human review before release.

## Saved baseline

The publication includes the native reader, pretrained VLM/LLM cascade, semantic candidate retrieval, genuine cross-encoder reranking service, PDF benchmarking, human review collection, PDF-to-VLM dataset builders, tests, scripts, configuration, research and synthetic web demo. The demo files are regular repository files under web/po-reader-mockup; its original nested repository remains untouched in the original workspace. Saving source does not deploy the Site.

The original local backend commit and web history contain private sample/provenance details. A clean root snapshot is used for GitHub publication. The original checkout and its local legacy branch remain intact, with current source and Git bundles preserved under ignored output/github-publication-2026-10-02/. Never push legacy refs or use push --all or --mirror. Future changes belong on branches descended from published main. Contact fields and private source-specific regressions are retained only locally. Publication copies of historical findings remove those fields while retaining the conclusions.

## Measured state and limits

- Publication verification on October 2: all 138 tests passed in both the original workspace and the clean worktree with private fixtures. The source-only checkout ran 101 tests with 9 explicit skips; private-PDF class skips represent additional unavailable cases. GitHub's Windows CI passed on the published baseline. Read the latest test output before carrying these results forward.
- Runtime previously verified on Ryzen 7 5800X, 32 GB RAM and Radeon RX 6700 XT 12 GB. Project-local Ollama uses loopback port 11435 and Vulkan; the CPU cross-encoder service uses port 11436. Service availability must be checked live, especially after restart.
- Qwen3-VL-8B-Instruct, 4B comparison baseline, Qwen3-Embedding-0.6B, Qwen3-Reranker-0.6B and gpt-oss-20b have prior actual stage measurements. See docs/framework-first-results.md and config/model-digests.json. PaddleOCR-VL-1.6 is awaiting a supported runtime and independent PDF test.
- The private corpus inventory contains seven initial PDFs / eight pages and a retained ZIP with 33 PDFs / 45 pages. Inventory live contents before reporting counts. Keep duplicated pages and layout families together when proposing splits.
- The latest 8B run recovered all 14 labeled identifier/quantity/unit tuples after explicit observed-unit parsing, but only 8/14 identifier roles and one additional charge row; neither of the two labeled documents was completely correct. It took about 13 minutes. These are development cases, not held-out generalization.
- The newer dataset workflow prepares source-bound images, candidate targets, duplicate-aware proposed splits and offline human review. A saved dataset manifest exists locally; assistant labels remain pending human review. Validation and release must be checked before any training claim. Dataset binaries, raw native text and targets are outside Git.

## Agent collaboration

Use one branch and worktree per concurrent writer. The original OneDrive checkout remains the local evidence/runtime workspace. Use the attached clean worktree for new source changes. Assign concrete file ownership before simultaneous work. Merge through reviewed commits; resolve conflicts against PROJECT_GOAL.md. Do not write the same review queue, dataset directory, SQLite catalog or session directory from multiple agents.

Keep context compact: PROJECT_GOAL.md is the objective, this file is the continuation map, model-stack-sources.md records research verification, framework-first-results.md records measured evidence, and vlm-dataset.md defines review/release operations. Update the applicable document when behavior or verified state changes. Record actual tests, skips, model identities and next unresolved step in the commit or PR.

Worktrees improve edit isolation and preserve committed context; they do not increase GPU throughput or share chat history automatically. Reuse existing inference services on their loopback ports. Serialize heavy model runs so agents do not compete for the GPU. Do not copy weights, runtimes, environment directories or writable outputs into every worktree.

## Local checks and private fixtures

A fresh clone can install Python dependencies with setup.ps1 and run `python -m unittest discover -s tests -v`. Private-PDF integration checks explicitly skip without local fixtures; a skipped suite does not establish real-PDF correctness. Mock provider tests do not call live models.

On this machine, use `initialize-worktree.ps1 -PrimaryWorkspace <original-workspace>` from the worktree. It copies only the small original PDFs, provisional catalog and private regression fixtures into ignored data/. It records the existing primary Python executable under ignored output/worktree-runtime.json. Each worktree has independent writable outputs. Then use `run-worktree-checks.ps1` to run tests through that interpreter with the worktree as the current directory. This reuses packages while importing the worktree source. It does not start inference or train.

Use `run-worktree-models.ps1` to start/reuse the existing primary Ollama and reranker services without duplicating their weights. The reranker is lazy and loads on the first scoring request. Check `model_stack.py` through the recorded interpreter for current service availability; starting a service is not a fresh model-quality evaluation.

Repository: https://github.com/CarlitosRed/advance-po-reader (private). Main stores the clean baseline; the attached worktree uses codex/po-reader-development with its own upstream. A local pre-push hook rejects the preserved private legacy history and tracked runtime/data folders. Fresh clones should enable the versioned hook with `git config core.hooksPath .githooks`.

For corpus work, explicitly supply the original retained ZIP path to the dataset builder or copy it into that worktree's ignored data/corpora/. Copy only reviewed labels needed for the task and use a new output directory. Do not share output/ wholesale or propagate draft labels into approved releases.

## Next engineering priorities

1. Validate the newly prepared private dataset and review UI, retain pending status, and collect human corrections. Do not train.
2. Improve identifier-role and product-versus-charge extraction on the independently labeled PDFs; compare the same cases and prompt/schema versions across 4B and 8B. Preserve failed/partial documents in denominators.
3. Bring up the independent PaddleOCR verifier on a supported runtime and measure risky pages separately.
4. Obtain the authoritative catalog and website/cart contract before production matching or external writes. Keep the current 18-product catalog provisional.

The source backup cannot restore private evidence or model weights by itself. Preserve the original local evidence workspace and private checkpoint archives separately.
