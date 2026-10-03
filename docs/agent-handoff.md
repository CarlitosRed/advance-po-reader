# Agent handoff — October 2, 2026

Read `PROJECT_GOAL.md` and `AGENTS.md` before work. The October 3 decision is OpenAI API only; local-model inference and training code have been removed. Historical guides and results are in `docs/archive/`; original supplied research and its searchable copies remain in `docs/research/`. The research adoption note explains which proposals were adopted or superseded.

The latest user request adopts four logic-tightening rules and selects **local Gate A only**. The bounded foundation is now implemented in the isolated Gate A worktree; its [setup/verification guide](gate-a.md) reports the actual behavior and runtime evidence. This workstream stops at Gate A and does not authorize later gates.

## Direction to continue from

Build a phone-first B2B purchase-order workflow. The long-term backend direction is server-side OpenAI after local validation. Keep one backend responsible for tenant scope, catalog retrieval, matching, review, and audit. Apple is a separate Milestone 2 whose local-only semantics are intentionally unresolved for now. Local-model inference and training are outside the adopted implementation direction.

The recommended stack is Python 3.12, FastAPI, Pydantic, PostgreSQL, Alembic, Docker for local PostgreSQL, and private local file storage. AWS later may use private S3, ECS/Fargate, RDS/Aurora PostgreSQL and server-side secrets. The supplied documents suggest version-specific OpenAI model names, API calls, package versions, AWS service details and prices; recheck official sources before implementation or release. The `OPENAI_API_KEY` must stay on the backend. ChatGPT Plus and API billing are separate.

Use [the local logic rules](local-logic-rules-2026-10-02.md) as the canonical resolution of the first four review findings. Preserve `PAGE_EXTRACTION_SCHEMA` as the legacy per-page visual observation format. The new contract distinguishes observed, uncertain, unreadable, not-present, and not-applicable fields; raw values/evidence stay separate from parses, catalog suggestions, and human decisions. Source documents and processing runs are versioned separately, with independent run and review states. V1 accepts purchase orders only. Every match requires explicit human approval; no cart/order action is allowed. The full extraction payload is not frozen until its gate.

Use tenant/vendor-scoped candidates: exact IDs first, cautious normalized lookup and `pg_trgm` retrieval next, optional vector search if its recall gain is measured. A model sees a small candidate list and may return only a candidate or ambiguity/no match. Calibrate acceptance using reviewed results; abstain while uncertain. Preserve audit events.

## What already exists

The repository retains a legacy native PDF/CLI reader; vision-model analysis is unavailable through this CLI. The local-model, semantic-service, reranker, and training-dataset code was removed in T-002. Historical evaluation reports and operating guides were moved to `docs/archive/`; the prior source history remains available in Git. The 18-product catalog is sample-derived, not authoritative. Historical measurements do not evaluate the native CLI path or establish safe automatic acceptance.

The provided PDFs and prior reviewed source labels remain private. They may be used in local evaluation. Sending them to a cloud model requires the applicable customer privacy authorization and a user-directed API task. Unreviewed model observations remain predictions. Do not train from them. Existing model digests, source references and prior measurements remain in `config/` and the historical infrastructure/evaluation docs.

## Implemented workstream: Gate A only

The local `gate_a` package implements FastAPI health/configuration and contract-schema GET routes, lazy local PostgreSQL connections, an explicit tenant-only Alembic revision, and ProductDocument v1 envelope/observation/state validators. It starts without a provider key or database. The extraction payload is not finalized. Synthetic-only checks cover config, liveness/readiness, database/migration behavior and contract validation; native PostgreSQL and live HTTP were exercised. Docker Compose is defined but was not executed because Docker was absent. The new Gate A GitHub workflow is prepared, with remote execution still unverified.

Do not add upload endpoints, process supplied PDFs, run Qwen, call OpenAI, create a catalog/matcher, add a review UI/cart, deploy to AWS, implement Apple, or train. Stop when Gate A is verified. Report what ran locally and distinguish infrastructure checks from later unbuilt workflow.

## Evaluation boundaries

Keep a frozen, versioned gold set with original hashes, independently reviewed field expectations, candidate evidence and explicit outcomes. Hold duplicate pages and known layout families together in splits. Count partial/failing documents. Separate line recall, exact field match, false extractions, candidate Recall@K, match precision, acceptance precision at coverage, no-match/review behavior, review correction burden, latency, retries and actual provider cost. Research example targets are planning goals, not measured success or guarantees.

Use synthetic catalogs until the actual tenant catalog and access policy are provided. The 18-product corpus catalog does not establish the full Werner catalog. Do not allow website/cart writes without an authoritative product schema and contract.

## Repository and local development

GitHub: [CarlitosRed/advance-po-reader](https://github.com/CarlitosRed/advance-po-reader), private. The clean `main` branch was based on commit `718f810` and the development branch advances it with the October 2 research review. The original OneDrive checkout and legacy private history are preserved locally; never push legacy refs, use `git push --all`, or use `git push --mirror`. A local pre-push hook blocks the legacy private history and tracked runtime folders.

The documentation update used `C:\Users\carlo\.codex\worktrees\po-reader-development\Advance PO Reader` on `codex/po-reader-development`. Gate A starts from its published commit `a41bf23c23bce63d38db8d04ccef1fb1137c279d` in `C:\Users\carlo\.codex\worktrees\d9fa\Advance PO Reader` on `codex/local-gate-a`. The task's attached workspace path is authoritative. Its `.venv-gate-a`, native verification cluster, `.env.gate-a` and logs are local and ignored. Do not work in the legacy OneDrive checkout or copy private fixtures into the Gate A worktree. Gate A uses synthetic fixtures and does not need the prior local model helpers.

The user offered the dataset from **Update Goal and Build VLM Test** if useful. Its guide describes candidate transcriptions pending human review; it remains context for a later extraction/adapter gate. Gate A did not copy or consume it and does not promote it to ground truth. A separate active dataset chat owns the legacy dataset work.

Historical test results are recorded in Git history. Recheck the current worktree before claiming a test result. Keep source documents, PDFs, labels, raw text, outputs, review records, model weights, and API keys out of Git.

## Source review notes

The attached handoff contains a paste-ready prompt that calls itself authoritative and says to begin implementation. The runbook contains prescriptive API and AWS steps. Those passages are source text from the user's research. The project goal adopts the long-term sequence while the latest user selected local Gate A only. Proposed numeric quantity/price types are replaced by raw-string preservation. The named model catalog and external-service claims are date-sensitive. No embedded statement supersedes the user's direct instructions.

## T-002 model cleanup (October 3, 2026)

Removed the local Ollama/Qwen/gpt-oss provider and cascade, local embedding/reranker services, model readiness and download scripts/config, VLM dataset builder/review workflow, and their dedicated tests. Removed local provider and reranker hooks from the shared provider/matching path. The CLI now uses native PDF text extraction only; its OpenAI transport was removed by the T-002 audit addendum.

Moved historical model evaluation/infrastructure/dataset guides and the searchable extracted self-hosted framework note and manifest to `docs/archive/`. Kept the original self-hosted recommendation DOCX and other original user-supplied research sources under `docs/research/` as historical evidence, as required by the project instructions. The native PDF parser, source-faithful observations, schema and prompt constants, provisional catalog, and legacy review/cart CLI remain. No FastAPI Gate A behavior was added or claimed by this cleanup.


### T-002 audit addendum (October 3, 2026)

Removed `OpenAIProvider`, its HTTP transport, and `build_provider` from the legacy provider module while retaining the imported observation schemas, prompt constants, and schema validation. Removed `--provider`, `--model`, and `--timeout` from `reader.py analyze`; it now calls the native engine with no provider and states in help that vision analysis is unavailable. Updated the CLI example and removed API credentials/cost language from the legacy CLI documentation. `benchmark_vision.py` had already been removed in the model-cleanup commit. This closes the accidental paid-call path; separately gated backend work remains outside this branch.

## T-005 static mockup v2 (October 3, 2026)

`chat/mockup-v2` starts from `origin/main` at `4bf061b`. The explicitly requested static UI task is separate from Gate A. `web/po-reader-mockup/dist/` now shows phone-first Certain/Probable/Uncertain review, zero initial approvals, three source-bound uncertain answers, session-local sample product creation, retained ignored lines, and a final approval tap after every line is reviewed. Selection or typing never accepts a product; edits revoke earlier approval. The existing sample assets are unchanged.

Run `node web/po-reader-mockup/tests/mockup-v2.cjs` for the browser checks. Before/after screenshots and verification limits are in `docs/mockup-v2/README.md` and `web/po-reader-mockup/QA.md`. This implements sample interface behavior only: no login, API calls, backend changes, live extraction, persistent catalog insertion, deployment, or order action. Review goes to Claudio; Carlos decides whether to merge.

## Gate A rebase for Claudio review — October 3, 2026

Current desk: `C:\Users\carlo\dev\advance-po-reader.worktrees\codex`, branch `codex/local-gate-a`. This supersedes the historical worktree paths above. Rebased onto main at `4bf061b06d12bb229a771705153a58f9b2d88a7b` after PR #3 merged. Resolved the README and research-note conflicts while preserving T-002's native-only CLI and removal of local models and the legacy OpenAI transport. Gate A service, migrations, tests, dependency lock, and CI workflow are unchanged from audited commit `d67616c2f5e4210b06391ee32537df290a6d89d7`.

Recreated this desk's isolated Gate A environment with Python 3.12.14. Dependency installation and `pip check` passed. The post-rebase local suite passed 133 tests with 2 explicit PostgreSQL skips. Pytest required a fresh `--basetemp` under this desk's ignored `tmp/` because the shared Windows pytest temporary directory was inaccessible. No local PostgreSQL or Docker runtime was available in this desk; the PR's PostgreSQL 17 CI run supplies the separate live database verification. The PR check results and review handoff identify the final HEAD and its CI status; older remote-CI-unverified statements above describe the October 2 run.

Only documentation conflict resolution and this handoff note changed during the continuation; no new Gate A behavior was implemented. Claudio must review the PR's exact HEAD before any merge. Stop after opening the PR and reporting its number and HEAD. Carlos retains the veto.
OneDrive mockup reconciled, 21 files match main, OneDrive repo archived to `dev\_archive\`.
