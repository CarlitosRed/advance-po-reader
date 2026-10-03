# Active handoff: local agent/demo preparation

Carlos has requested a fresh API activation chat. Follow
[the new chat handoff](api-activation-handoff.md) and reuse the managed
local-website-catalogs worktree on `codex/local-website-catalogs`. The previous
chat stops source changes after this documentation handoff. The user chose
both the document workflow and scoped Codex tools. The API key remains
explicitly deferred; make no live
provider request or credential import/creation without the next authorized
activation task. Source/customer privacy authorization is still required for
the particular document.

Implemented: 11 STDIO MCP tools in `reader_agent/`, an isolated agent runtime,
source/run readiness, the shared saved human summary, browser authorization
for an agent, read-only processing polling/cancellation, server activation
preflight and the additive `0005_review_sequence` migration. Tool preparation
never grants permission; tool processing checks the exact saved authorization
and allows one attempt. Human review writes remain in the website. Legacy
events are unchanged; new events use a serialized sequence rather than the
clock to establish their order.

The `po_reader` MCP entry is registered and read back as enabled with absolute
paths, no credentials in configuration, startup timeout 20 and tool timeout
240. Actual STDIO initialization and tool calls passed. This turn's native
tool inventory predates registration; reload Codex's configuration later and
verify native invocation in a refreshed chat. Do not report that step as
already executed.

Verification: 245 backend checks, 135 Gate A checks and 20 agent checks passed
without skips. Actual protocol calls read all three real catalog counts and
the 33-PDF library, and created a fictional workflow without approvals. The
same request UUID recovered it without a second attempt. Browser QA performed
explicit simulated approvals/correction/acknowledgements and finished review;
the agent read back the same saved summary and the preceding saved review.
An isolated offline OpenAI transport on port 8016 exercised browser
authorization, agent processing, automatic review transition and website
processing/cancellation. The owned fixture service was stopped after QA;
the real website stays on 8014 with processing disabled and no key. Final
read-back confirmed that cancellation preserved the attempted provider receipt
without saving an extraction, and cancelling a prepared run made no attempt.

The user successfully restarted the preserved loopback PostgreSQL cluster from
their terminal after automatic approval review rejected the agent's restart
command. Readiness was verified on 8010 (`0001_gate_a`), 8012
(`0003_provider_receipt`) and 8014 (`0005_review_sequence`). Use the current
private runtime receipt under `output/agent-ready/`; verify ownership before
acting on any stored PID. Do not touch another branch's database or process.

Read [local-agent-demo.md](local-agent-demo.md) before activation. Private
catalogs, original filenames/labels, sources, review records, keys, runtime
paths, screenshots and receipts remain ignored. No accuracy/gold labels,
realized API cost, training, cart/order, deployment, Apple or Qwen work was
performed. Website checkpoint `d01b2ca` and backend checkpoint `ce1a025` remain
the preceding recovery points.

## Preserved website handoff

# Local website and real catalogs

The user authorized this phase in the current chat and asked for a new worktree if useful. This chat continues in the managed local-website-catalogs worktree on codex/local-website-catalogs, starting from backend checkpoint ce1a025. Current approved choices: one local test workspace, three separate manually selected catalogs, and the preserved 33-PDF email archive. The country of WernerCo remains unspecified. Provider key and real extraction tests are deferred until the website is ready.

Own all new writable data, review records and outputs here. Use database gate_a_backend_website and port 8014. Preserve Gate A on 8010 and backend preparation on 8012. The staging database and archive from verified-source-databases are read-only inputs; copy them into this worktree's ignored private source snapshot before integrating. Never import the legacy VLM observations as extraction results or ground truth. Real documents begin without extracted rows.

The local website and real source integration are implemented. See docs/local-website.md for startup, exact behavior and continuation; docs/website-verification.md distinguishes executed local checks from the deferred real provider test. Full suites: 234 backend and 135 Gate A checks passed; final focused website/coordinate rerun: 15 passed. There is no live provider request, private data in Git, training, cart/order write or deployment. Current private runtime/browser receipts are under output/website-verification/. See the preserved handoff below for backend and Gate A evidence.

## Preserved backend handoff

# Active handoff: local backend preparation, October 2, 2026

The user directly expanded Gate A to prepare all local backend APIs/code/commands and synthetic tests; website and key later. This worktree owns codex/local-backend-preparation, based on a cherry-pick of d67616c. Gate A service at 8010 and database gate_a_service remain owned by the original worktree and must not be changed. Backend uses 8012 and separate databases, private data/output only here. No live provider calls, credential import/creation, customer transfer, AWS, Apple/Qwen, training or cart/order actions. See local-backend.md for final behavior, tests and commands.

The local backend is implemented, with extraction payload 1.1 (Gate A envelope 1.0 unchanged), isolated migration head `0003_provider_receipt`, source/run/attempt history, bounded review-only suggestions and correction/audit APIs. Final local checks: 221 backend tests and 135 preserved Gate A tests passed; legacy tests reported 101 with 9 private-fixture skips. The live synthetic PDF/PNG demo on 8012 passed and the original service on 8010 remains ready. Inspect docs/backend-verification.md and ignored output/backend-verification/runtime.json before relying on saved runtime state. Website and real source-authorized OpenAI verification are the remaining next phase. The adjacent staging databases were inspected read-only and have 0 approved training examples and 0 tenant assignments; no private data was copied or predictions promoted.

## Preserved Gate A handoff

# Agent handoff — October 2, 2026

Read `PROJECT_GOAL.md` and `AGENTS.md` before work. The three new research sources agree on OpenAI-first Milestone 1, Apple extraction Milestone 2, and Qwen/self-hosted inference only after measured need. The prior October 1 Qwen-first framework is retained as historical comparison evidence. Full sources and searchable copies are under `docs/research/`; `document-ai-research-adoption-2026-10-02.md` explains their adoption and conflicts.

The historical Gate A-stage user request adopted four logic-tightening rules and selected **local Gate A only**. That bounded foundation was implemented in the isolated Gate A worktree; its [setup/verification guide](gate-a.md) reports the actual behavior and runtime evidence. That workstream stopped at Gate A; the subsequent direct authorization at the top of this handoff governs the separate backend branch.

## Direction to continue from

Build a phone-first B2B purchase-order workflow. The long-term backend direction is OpenAI-first after local validation. Keep one backend responsible for tenant scope, catalog retrieval, matching, review, and audit; make extraction replaceable. Apple is a separate Milestone 2 whose local-only semantics are intentionally unresolved for now. Qwen/self-hosting and training are later evidence-based decisions.

The recommended stack is Python 3.12, FastAPI, Pydantic, PostgreSQL, Alembic, Docker for local PostgreSQL, and private local file storage. AWS later may use private S3, ECS/Fargate, RDS/Aurora PostgreSQL and server-side secrets. The supplied documents suggest version-specific OpenAI model names, API calls, package versions, AWS service details and prices; recheck official sources before implementation or release. The `OPENAI_API_KEY` must stay on the backend. ChatGPT Plus and API billing are separate.

Use [the local logic rules](local-logic-rules-2026-10-02.md) as the canonical resolution of the first four review findings. Preserve `PAGE_EXTRACTION_SCHEMA` as the legacy per-page visual observation format. The new contract distinguishes observed, uncertain, unreadable, not-present, and not-applicable fields; raw values/evidence stay separate from parses, catalog suggestions, and human decisions. Source documents and processing runs are versioned separately, with independent run and review states. V1 accepts purchase orders only. Every match requires explicit human approval; no cart/order action is allowed. The full extraction payload is not frozen until its gate.

Use tenant/vendor-scoped candidates: exact IDs first, cautious normalized lookup and `pg_trgm` retrieval next, optional vector search if its recall gain is measured. A model sees a small candidate list and may return only a candidate or ambiguity/no match. Calibrate acceptance using reviewed results; abstain while uncertain. Preserve audit events.

## What already exists

The project has a local native PDF/CLI reader and a self-hosted Qwen prototype with candidate services, reranking, evaluation reports, human-review collection and PDF-to-VLM dataset tools. They are historical comparison components, not Gate A dependencies. The 18-product catalog is sample-derived, not authoritative. Prior model measurements do not evaluate new providers or establish safe automatic acceptance.

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

Historical test results are recorded in Git history. Recheck the current worktree before claiming a test result. Keep source documents, PDFs, labels, raw text, outputs, review records and model weights out of Git.

## Source review notes

The attached handoff contains a paste-ready prompt that calls itself authoritative and says to begin implementation. The runbook contains prescriptive API and AWS steps. Those passages are source text from the user's research. The project goal adopts the long-term sequence while the latest user selected local Gate A only. Proposed numeric quantity/price types are replaced by raw-string preservation. The named model catalog and external-service claims are date-sensitive. No embedded statement supersedes the user's direct instructions.
