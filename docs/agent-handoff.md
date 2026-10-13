# Project handoff — October 2, 2026

> **Superseded checkpoint (banner added 2026-10-08).** This handoff describes the October 2 workspace-organization task, the source and backup checkpoints of that day, and a Gate A-only boundary. Since then the upload, extraction, catalog, review and web workflow were built on this branch, a server key was configured and one human-authorized PDF was processed once with OpenAI; entries added by later tasks follow below. Current scope and the Implemented versus Intended list are in [PROJECT_GOAL.md](../PROJECT_GOAL.md) and [AGENTS.md](../AGENTS.md); later evidence is in [api-activation-verification.md](api-activation-verification.md) and [live-demo-continuation.md](live-demo-continuation.md). The text below is kept unchanged as historical evidence.

This document is the sanitized project handoff. The latest user request for this chat is workspace organization: map the workstations, assign ownership only where verified, improve the operating standard, and verify source/runtime backup coverage. Do not continue extraction debugging during this task.

## Current source checkpoints

- The primary saved checkout is `codex/po-reader-logic` at `097f71ea87af97bd36f703ceb0b34b3916e16b3c`; it has an untracked `web/` directory that must be preserved.
- The current integrated website/catalog code is `codex/local-website-catalogs` at `a80be44e1d206295b1076882c410851344476221`. Its active owner chat is not confirmed by app inventory; treat ownership as `Unknown` until reconciled.
- The backend-preparation checkpoint is `codex/local-backend-preparation` at `ce1a025d98ff87ef9cccbdb81849f1a327c16d93`, associated with “Advance PO Reader — Local Backend Preparation.”
- The source-database checkpoint is `codex/source-databases` at `1403527d2ca19e0069939ecb2f0442eb43a59406`; the current owner is `Unknown`.
- The catalog-exploration checkout is detached at `52c46e25d6475d81800b3501e71f317b608396a3`; owner and lifecycle are `Unknown` pending inspection.
- A separate unregistered directory holds the live PostgreSQL cluster used by the integrated local service. Preserve it as a runtime dependency. The complete private workstation map and recovery notes are in the ignored local registry, not this tracked document.

## Backup state at handoff

The configured remote is `https://github.com/CarlitosRed/advance-po-reader.git`. A live `git ls-remote --heads origin` check advertised `main` and `codex/po-reader-development` at `a41bf23c23bce63d38db8d04ccef1fb1137c279d`, `codex/local-gate-a` at `d67616c2f5e4210b06391ee32537df290a6d89d7`, and `codex/source-databases` at `1403527d2ca19e0069939ecb2f0442eb43a59406`.

The integrated source tip `a80be44e1d206295b1076882c410851344476221` is twelve commits beyond the remote `main` baseline and has no advertised remote branch. The GitHub account can read the refs, but no backup of the integrated tip is established. The local source history contains live operational handoff material, so do not push that history as-is. Build a sanitized source/documentation snapshot only after a complete relevant-history and final-tree review; retain private runtime and customer evidence locally under a separate recovery plan.

## Scope and evidence limits

The project documents describe local Gate A as the authorized implementation boundary. Later local integration exists in a separate source checkpoint; do not infer that the wider workflow was validated by Gate A. Prior synthetic suites (141 backend checks and 21 scoped agent checks) are not extraction-accuracy evidence. The required evaluation plan covers all 33 supplied PDFs and varied incoming handwritten, scanned, photographed, structured, and one-to-100-line orders.

A terminal failed provider attempt is preserved as private evidence. Do not retry it or create another provider attempt during workspace organization. Do not approve review items, train, deploy, or write to carts/orders. Refer to the ignored private handoff for exact recovery details when a later authorized task needs them.

## Next actions

1. Use the workstation registry and tracked worktree standard to assign one writer per checkout and one integration owner.
2. Audit and create a safe source-only GitHub backup, then read back its exact remote ref and SHA.
3. Keep ignored runtime/evidence backups separate and verify their recovery path before any cleanup.
4. Report documentation updates separately from implemented behavior, and leave unresolved ownership or backup details marked `Unknown`.

## Goal acceptance tests — October 3, 2026

The dedicated `Codex · goal tests` desk starts at remote
`codex/worktree-standards` commit `183412f4b1daaf8fc49b2a60f91ed8e34b749afb`.
T-007 adds all ten product-goal groups under `tests/goal`, default goal-only
pytest configuration, an injected fixed-JSON provider, generated fictional
PDF/PNG/JPG sources and a disposable PostgreSQL cluster/database. The measured
suite reports 10 passed, 8 strict xfail and 0 blocked; each xfail names the
application fault. See [test guide](goal-acceptance-tests.md) and
[scorecard](goal-scorecard-2026-10-03.md).

Implemented changes are tests and their isolated harness only. Backend logic,
provider settings and customer evidence are unchanged. The scorecard documents
missing confidence tiers, unknown-row decisions, source grounding and product
line completeness; none of those features is fixed or approved by this task.
The PR targets `codex/worktree-standards`, not `main`.

## T-009 PR A — October 3, 2026

`Codex · goal gaps` reused the assigned `goal-tests` desk and PR #7 after
Claudio's four-condition go. Implemented items 1, 2 and 5 in one commit per
item: deterministic Certain/Probable/Uncertain review tiers; existing-product,
new-product and not-a-product answers; and same-row/page quantity/unit
evidence validation. Certain remains pending until an explicit approval.
New products are created and bound atomically with retry protection,
`origin=review`, and tenant/vendor/pool scoping. Staff-facing catalog and
review controls show that origin. Original observations remain immutable;
corrections require fresh approval. Generic acknowledgment cannot finish an
Uncertain row. Bounded conflict checks also veto Certain for alternate,
unreadable or contradictory labeled readings without changing F7 retrieval.

The final goal suite measures **49 passed, 2 strict xfail, 0 blocked, 0 failed**.
Additional affected checks: 68 extraction contract, 27 catalog/database and
7 review-summary checks pass under `pytest.backend.ini` with offline guards.
The goal suite includes a clean upgrade/downgrade/upgrade of migration 0009
on a separate throwaway database and a headless browser driving the real
controls against the fixed-provider test API. The database and uploads are
test-owned; no existing runtime is migrated or restarted. See the updated
[scorecard](goal-scorecard-2026-10-03.md) and [test guide](goal-acceptance-tests.md).

PR B's independent completeness, source grounding and F7/F8 repairs are only
planned. Goals 7 and 8 retain their reasoned xfails. No real-document accuracy,
production validation, provider activation, customer-file use, or deployment
is claimed. A remains review-gated: merge requires `Approved at <commit>`
matching its current head and passing tests. B implementation waits for A's
merge and its own plan go.

## PR #7 review S1 — October 4, 2026

Quantity/unit references may use a declared cell rectangle contained fully in
one of the same row's rectangles on the same page. Region names alone do not
establish containment. Shared headers, other rows/pages, and partially
overlapping rectangles remain invalid. The existing provider prompt and schema
allow declared field rectangles; this change supports that contract without a
live provider call.

Reads remain strict. A previously stored payload with borrowed quantity/unit
evidence can fail validation on review, suggestions or summary reads. This is
acceptable for the isolated test data on this branch; no stored payload is
rewritten and no existing application database has been migrated. Before using
this change on an existing runtime, inventory invalid legacy payloads and
create new source-bound runs under the applicable human authorization. This
handoff documents that compatibility limit rather than claiming a data repair.

## PR #7 review fixes and B2 CI — October 4, 2026

Implemented B1 across retrieval, explicit binding/proposal/approval, catalog
listing/detail/counts and migration 0009's trigger: a run without a pool requires
`review_pool_id IS NULL`. The regression creates a review product in a pool,
then verifies a later same-vendor run without a pool retrieves no candidate,
rejects binding/proposal/approval with 422, omits the product from catalog
listings, and rejects direct database events outside that scope.

S2 keeps legacy unknown/Uncertain `no_match` rows pending in the shared summary
and UI. N1 selects an explicitly bound candidate for the separate approval and
provides the friendly binding-error message; selecting it records no approval.
N2 keeps `not_a_product` canonical and marks `not_product` deprecated in the API
schema while preserving legacy clients and stored events.

B2 adds the Tier 3 `.github/workflows/backend-goal-checks.yml` change and shared
test-owned PostgreSQL provisioning. The full backend suite now runs against
five fresh databases, including the empty historical-migration database; goal
tests use a separate fresh database. Older test fixtures were aligned with the
three-answer contract, and historical migrations seed historical columns.
See [suite commands and CI limits](goal-acceptance-tests.md).

Local verification on the changed source:

- `pytest -c pytest.backend.ini --isolated-backend`: **268 passed in 45.70s**,
  no skips, xfails or failures.
- `pytest -m goal`: **54 passed, 2 strict xfailed in 31.49s**, no skips or
  failures; includes the real review-control browser check on the test-owned API.
- `pip check` and `git diff --check` pass.

The tracked [scorecard](goal-scorecard-2026-10-03.md) is the local measurement.
CI runs backend and goal separately and uploads JUnit results plus its own
scorecard. Its browser tooling is deliberately absent, so that one goal 9
browser check is a documented skip. A successful CI job does not prove browser
coverage; report its named suite summaries and skip count separately from the
local browser pass.

No `.env*`, credentials, customer PDF or live provider is used. No existing
application database is migrated or service restarted. PR #9 remains plan-only;
source grounding, independent completeness and F7/F8 are not implemented here.
Claudio's B-plan conditions 3/4 still require clarification and confirmation
before B coding, which also waits for #7 to merge from an approved exact head.

# T-017 free synthetic POC — October 5, 2026

Implemented on `codex/poc-demo-kit` in the new `poc-demo` desk: script-owned
one-command startup, isolated PostgreSQL/environment, 150 fictional catalog
fixtures, hash-bound fixed observations, PDF/photo upload entry and unchanged
human review controls. All 33 original PDFs/45 pages were validated only
locally under Carlos's explicit authorization; 33 fictional structural
surrogates were processed without any original-source provider attempt.
Phone QA at 390×844 and the existing goal suite (54 passed, 2 strict xfailed)
passed. Reset selects a new owned database and preserves previous evidence.
Source grounding/completeness remain known gaps; live OpenAI, accuracy,
real-catalog integration and ordering are not verified. No backend logic,
migration, CI or existing runtime was changed. Cost is $0. Step 4 still needs
Carlos's separate go and source-transfer authorization. See
[runbook](poc-demo-runbook.md), [evidence](poc-demo-verification.md) and
`audits/handoff-codex-poc-demo-2026-10-05.md`.

Continuation: step 5 runbook finished; source enlargement and all three case
walkthroughs passed at phone width. The launcher now rejects administrator
sessions before setup. Use normal PowerShell and the documented process-only
execution-policy bypass; no Windows policy setting changed. Bypass setup/seed
verification passed. A later full start safely refused already occupied port
8020; the other running demo was left intact. Step 4 and merge remain gated.

<!-- Entries below were merged from main (T-002, T-005, Gate A rebase, T-010). -->

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

## T-010 operating model and merge gate (October 4, 2026)

Desk `advance-po-reader.worktrees\t-010`, branch `claude/t-010-operating-model`, PR #10 (Tier 3). Added `ROLES.md`, the gate tool in `tools/gate/` (standard library only), the `gate-tests` and `scan` CI jobs, the `Gate audit` workflow, a content-scan block in `.githooks/pre-push`, the pull request template, and one appended section in `AGENTS.md`. The `tests` job and every earlier hook line are unchanged. Labels `tier-1` to `tier-4` and `hold` were created on GitHub. No product code changed. Implemented: the files above. Only documented, not built: the attack-team pilot (T-011) and the parked ideas. The gate is a procedure with a record, not a lock: every chat posts as one GitHub account, so it cannot prove who wrote a comment and cannot stop a manual merge. PRs #7, #8 and #9 finish under the old rule 3. `check 7` output after merge: to be added.

## T-009 PR B plan refresh — October 5, 2026

`Codex · goal gaps` refreshed the separate [PR B plan](goal-gaps-pr-b-plan.md)
in the assigned `goal-tests` desk by merging `codex/worktree-standards` at
`fe5c1f421c4293d0b993a5e2e4abecc69fba500c`, Carlos's manual PR #7 merge of
approved head `54c979e457e9fa83e0ac22ada12cb2b3385e0a21`. The refresh preserves
published history and inherits A's full backend/goal CI job. Both A and B
handoff sections are retained after resolving their append-at-end conflict.

The revised plan selects rerun-only for source-line count discrepancies, binds
reviewer counts to each page/source hash, and treats zero with product rows as
a mismatch. Unavailable text retains tiers and uses one attributed page-level
confirmation that cannot clear count/row blockers. Case-folding and whitespace
normalization, invented/correct text cases, and the deferred OpenAPI snapshot
nit are explicit. Only this plan and handoff change relative to the merged
base; no B code, tests or migrations are built and no new local runtime result
is claimed. `git diff --check` is the documentation validation. Implementation
waits for Claudio · PR review's confirmation of the revised plan at its new
head; retain A's approval/scoping regressions and synthetic/disposable test
boundaries afterward. No #9 merge without Carlos's instruction.

## T-009 PR B item 3 — October 5, 2026

`Codex · goal gaps 3` rebuilt the clean desk from the checkpoint, task card,
branch plan and signed PR comments. Claudio confirmed the plan at `7438183`
at 17:55:42 UTC and Carlos gave GO to code B. No prior uncommitted or unpushed
implementation existed. This commit implements only item 3; items 4 and 6
remain separately scoped work.

Every PO run initially remains partial until each source page has an
independent reviewer count. `/runs/{run_id}/page-counts` verifies the actual
source hash and appends a named, reasoned page count in existing immutable
`review_events`; no new table or migration is needed. Comparisons expose
provider/independent counts and matched/mismatch/unavailable status. Product
items are counted from original observations, without description
continuations, document details or human exclusions. Zero with products is
a mismatch; an empty source page requires its own zero check. Matching counts
do not approve products or clear other blockers.

A correction names the latest count event and attests `independent_count_error`,
preserving its old value and sequence. A reviewer-confirmed source discrepancy
keeps that old run blocked; the website can prepare a fresh run of the same
source without starting processing or copying authorization/counts/approvals.
Only a coverage-held outcome transitions partial -> completed after matching
checks. A later mismatch can return completed -> partial before resolution;
other extraction/retrieval partial outcomes remain partial. Resolved reviews
reject further count changes.

The first B contract-changing commit regenerates the local backend OpenAPI
snapshot and adds comparison with `app.openapi()`. `pytest.backend.ini`
collects backend and goal cases, so each new B case runs in both backend-goal
commands. Goal 8's original assertion now passes and its marker is removed.
Goal 7 remains strict xfail with a grounding-specific assertion, so a
coverage-induced partial state cannot masquerade as a grounding fix.

Verification uses fixed JSON and generated fictional source bytes on owned
throwaway PostgreSQL clusters. The separate local goal run reports **76
passed, 1 strict xfail in 34.01s**, no skips or failures; the actual browser
check includes mismatch blocking, attributed count correction and explicit
product approval. The final combined backend/goal command reports **344
passed, 1 strict xfail in 121.13s**, no skips or failures; its 345 collected
cases include every new B case and the actual local browser check. `pip check`
and `git diff --check` pass. CI measurements are recorded separately in the
delivery comment and external checkpoint after publication.
CI deliberately lacks browser tooling and reports its browser skips separately.
No `.env*`, real PO, paid/live provider, application DB migration or main push
is involved. Code approval still requires `Approved at <current head>`; no
merge is authorized in this chat.

## T-009 PR B item 4 — Codex · goal gaps 4, 2026-10-05

The separate plan-only commit `042f9d2` resolves item 3's two non-blocking
notes: zero-product whole documents may Finish after matching per-page zero
counts and other review requirements; `partial` also means awaiting counts.

Item 4 independently decodes actual hash-checked PDF source text inside each
description/identifier's declared region. Unicode case-folding, whitespace
collapse and complete-phrase alphanumeric boundaries preserve punctuation,
numbers and literal observations. Supported/unsupported/unavailable evidence,
literal decoded text and separate normalized comparisons are saved once in
the run's immutable deterministic parses. No new migration is required.

Unsupported text blocks Finish until attributed `confirm_source_text` review
of every flagged region. Corrections retain original observations and still
invalidate product approval. Source review preserves the unsupported status
and cannot approve products. Scanned/empty PDF text and photos retain all tiers
and normal preselection. One attributed, exact-hash page action
`confirm_unavailable_page_text` covers every unavailable row on that page;
the unavailable status, row decisions and independent count blockers remain.
Generic acknowledgments do not substitute. Every page/new run needs its own
evidence; preserved legacy runs missing grounding require new processing.
The website shows row flags and source evidence, with both confirmation
controls tested through the real isolated API. OpenAPI is regenerated and
compared with `app.openapi()`. Goal 7's original assertion now passes with its
strict xfail removed. A zero-product whole-document test is also included.

Final local tests: backend plus goal **367 passed in 100.36s**; separate goal
**99 passed in 52.69s**. Neither command has skips, xfails or failures. Each
runs the same 20 new grounding/empty-document cases and three browser modes
(text PDF, photo/unavailable text and unsupported source text). Tests preserve
the item 3 count and A's approval/scoping/evidence regressions. `pip check`
and `git diff --check` pass. The measured scorecard is regenerated from the
separate goal run. CI for the published item 4 head must be checked separately;
the reported runner-acquisition outage is not a passing-suite result.

Item 6 (F7/F8) is unstarted. Carlos requested a checkpoint and stop at about
60% context; the continuation checkpoint is
`C:\Users\carlo\dev\project-notes\audits\handoff-codex-goal-gaps-4-2026-10-05.md`.
PR #9 stays draft; item 4 needs exact-head re-review, and no merge is authorized.
No dotenv file, paid/live provider, real PO data, existing application database,
deployment, cart/order write or main push is involved.


## Codex · goal gaps 5 — T-009 PR B item 6, October 5, 2026

Item 6 only follows parent `1ca8c035caa1fc974df4abeb43859ae9c6d5fea4`
(item 4). F7 discovers explicitly labeled short/alphabetic/date-shaped literal
codes, including A123/2026, with at most ten distinct forty-character tokens
and a single tenant/vendor/pool-scoped exact SKU query bounded to limit + 1.
Labels and codes are retrieval evidence, never new identifier observations or
rewritten descriptions. Labeled hints take priority over existing conservative
unlabeled hints. Unlabeled dates/quantities/currency remain conservative;
A's labeled-conflict veto and explicit approval remain intact.

F8 defines region/page/document review evidence. Row requests retain same-row
validation and accept both explicit region scope and the existing unscoped
region form. Page acknowledgments name a valid partial source page and exact
hash, including partial pages without any regions. Document acknowledgments
name source/hash/run. New generic acknowledgments reject the old region-only
or null-region shapes; saved historical audit events remain readable. The
response union retains unavailable-page confirmations/count evidence. The
actual website buttons send these source-bound shapes. Generic acknowledgments
cannot approve rows or clear independent grounding/count blockers. Count and
grounding policies are unchanged; no migration is added. OpenAPI is regenerated.

Measured local source validation: full backend plus goal **413 passed in
104.53s**; separate goal **145 passed in 58.84s**, with zero xfails/skips/failures.
JUnit case sets agree: **45 new F7/F8 cases** and **four real browser modes**
passed in both commands. The new browser mode clicks page acknowledgment for
a partial second page without regions and document-warning acknowledgment,
checks their persisted request scopes, and proves row/grounding/count blockers
survive before the separate decisions. Tests use the actual pg_trgm extension
and transactional absence in the disposable harness database; rollback restores
its indexes. Tenant/vendor/pool provenance, hint/candidate bounds, source/hash/
page/run rejection, literal preservation, conflicts and unlabeled tokens pass.
`pip check` passes. The scorecard is regenerated from the separate goal run.

Parent item 4 CI has now been verified: backend **364 passed / 3 browser skips**;
separate goal **96 passed / 3 browser skips**. Its JUnit artifact has identical
sets of twenty passing grounding/empty-document cases in both suites. Claudio
approved item 4 at the full parent SHA; his three non-blocking source-grounding
notes (split-region phrases, raster regions on text-bearing pages, damaged-PDF
PyMuPDF exceptions) remain deferred because this task is item 6 only.

Item 6 still requires CI execution and exact-head review after publication.
The signed PR delivery comment and external checkpoint record the published
head and actual CI state; this local measurement is not a claim of CI execution.
PR #9 remains draft and unmerged; no self-approval or merge is authorized.
Only generated fictional bytes, fixed JSON and test-owned PostgreSQL are used.
No dotenv file, paid/live provider, real PO data, existing application service/
database change, deployment, cart/order write or main push is involved.
The sole external checkpoint is
`C:\Users\carlo\dev\project-notes\audits\handoff-codex-goal-gaps-5-2026-10-05.md`.


## PR #20 v1.1 backend Safety Net — October 8, 2026

Codex · integration merged landing prep `398210a` normally, then selectively
merged #9 `100f1d8` backend/tests/contracts with both parents (`cbe4eb6`). UI
files were never edited for the safety merge; current scripts are unchanged.
Implemented `PO_BACKEND_SAFETY_NET_FINISH_BLOCKING`, default OFF, including the
OFF/ON transition rules, typed ON acknowledgments, source integrity at enabled
Finish, and inherited count/source-check APIs. OFF preserves v1 processing,
retrieval and Finish; ON exposes independent-count and source blockers.

Only documented/deferred: new Safety Net UI controls and their browser proof.
Stored counts-only snapshots confirm the historical 150 products and 33/33
count matches; the supplied batch scorer cannot safely perform the requested
fresh re-score under this task's limits. It reads PDFs and can make paid calls.
The current plan, class/claim/state ledgers and local scorecard distinguish that
limitation. Full evidence and checkpoint: external audit
`project-notes/audits/codex-v11-safety-net-2026-10-08.md`. Independent review and
Carlos's exact-head Tier 3 approval remain required. No PR approval or merge.

## PR #20 P2 corrections — Codex · integration, October 8, 2026

Addressed only P2-1 and P2-2 from Claudio's review of
`eaa442e5b7aa96deac05d3513922041bcbe07c37`. Empty and detail-only orders retain
`unresolved_rows_remain` in both modes, even after a matching independent zero
count. This supersedes the historical PR #9 note above allowing zero-product
documents to Finish; the current claim ledger and inherited goal test are corrected.
Each product row contributes once to coverage, on its earliest evidence page,
regardless of evidence array order or repeated references. No other policy changed.

Class sweep across `backend/`: only `review_run` sets review state to resolved;
it and `reviewed_summary` share `resolution_blockers`. Count-event responses,
summary coverage, enabled processing-state synchronization and resolve share
`page_coverage`. Evaluation counts use row-ID sets; source grounding inspects
evidence without counting products. No additional instance of either defect found.

Before production edits, the zero-order unit cases gave **4 failed / 4 passed**
(ON fails, OFF passes); the zero-order and spanning-row HTTP regressions gave
**5 failed**. On the fixes the targeted slice gave **13 passed**. Full offline
backend+goal, including current browser checks: **554 passed, 2 expected OFF
xfails, 0 skipped, 0 failures/errors**, 165.03s. Both schemas, empty/detail-only
orders, reversed/repeated spanning evidence, count responses, summary and actual
Finish are covered. JUnit evidence is in ignored `tmp/p2-*-results.xml` and
`tmp/p2-red-unit.xml`, `tmp/p2-red-routes.xml`, `tmp/p2-green.xml`.

PR #27 was still OPEN at the publication precheck. Carlos requires its merge
before re-merging `origin/claude/landing-prep`; that dependency remains pending.
P3 findings and deferred UI/batch evidence remain outside this correction.
Cost $0; no paid calls, dotenv opens, private data, existing-service changes,
approval or PR merge. Only disposable test-owned PostgreSQL clusters were used.

## PR #20 refreshed onto main — Codex · integration, October 9, 2026

Normally merged main `7338ad1c26efa461cda2d55ac4cf889db52e61be` into the
approved PR #20 head `e3354ec0d5ed6a02102c7e3cce7e73ff7223ae3b`.
Main's squash landing required resolving ancestry-only conflicts using the shared
pre-landing source `9d1195a`; the four content conflicts retain typed Safety Net
evidence, main's NUL rejection and fail-closed catalog handling, and the measured
goal scorecard. Regenerated the OpenAPI snapshot from the merged application.
Nested typed evidence is included in request NUL validation, and the fictional
goal provider reports its fixture's schema version so main's receipt guard holds.

The Safety Net setting still defaults OFF. Main's web, scripts, gate and shared
test-database guard are preserved exactly; new Safety Net UI remains deferred.
Local suite counts, unchanged-main-test OFF compatibility proof and owned-runtime
cleanup are recorded in `project-notes/audits/codex-v11-main-merge-2026-10-09.md`.
PR #20 remains Tier 3 and draft for independent review of the new head.

## PR #20 documentation restoration - Codex · integration, October 12, 2026

Normally merged main `f07820a` and restored its documentation verbatim,
retaining the PR's additions below main's original text. Swept every
changed file for main lines removed; remaining code/test replacements
are the existing v1.1 work. This repair changes documentation only.
Backend/goal and original-main default-OFF evidence, the per-file
deletion inventory and exact new head are recorded in the signed PR
comment and `project-notes/audits/codex-v11-main-merge-2026-10-09.md`.
New Safety Net UI remains deferred. PR #20 stays draft for independent
re-review; no paid call or real PO data was used.
