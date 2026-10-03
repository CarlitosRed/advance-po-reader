# T-009: close goal gaps — plan for Claudio

Owner: **Codex · goal gaps:**. Reviewer: Claudio. Date: 2026-10-03.
Status: PR A implemented after Claudio's go with four conditions on PR #7.
PR A includes items 1, 2 and 5 only. PR B is a separate plan-only draft for
items 3, 4 and 6; its implementation waits for A's merge and its own plan go.

PR #5 merged into `codex/worktree-standards` at
`c06b4e9994277997e6ec8b828317cb5942e0daf6`. This branch,
`codex/close-goal-gaps`, starts at that merged base and reuses the assigned
`goal-tests` desk. Baseline evidence: 10 passed, 8 strict xfail, 0 blocked,
0 failed; that is the PR #5 measurement, not a new run.

Sources: T-009, AGENT-WORKFLOW rule 3, the October 3 goal scorecard and
logic audit (F1–F8), the project brief, PROJECT_GOAL.md, AGENTS.md and
the local logic rules. Implementation will preserve immutable observations,
append-only human decisions, tenant/vendor/pool scoping and explicit approval.

## Proposed changes and files

1. **Tiers (goals 4–6; F6, bounded F5).** Expose `certain`, `probable`, or
   `uncertain` for every product/unknown review line independently of retrieval
   outcome and human approval. Certain requires a unique literal, observed,
   role-valid code-column match without conflicting evidence; embedded-code
   and description-only matches are Probable; ambiguity, absent matches and
   unresolved readings are Uncertain. Preselect only Certain and retain the
   approval gate. Inspect contradictory column/embedded codes and alternate
   readings before assigning Certain. Planned files: `backend/catalog.py`,
   `backend/responses.py`, `backend/app.py`, `web/local-reader/app.js` and tests.

2. **Three answers (goal 6; F2).** Add explicit `this_is_product` with a scoped
   catalog id, `new_product` with reviewed catalog fields, and `not_a_product`
   with an exclusion audit event. Support unknown rows and other Uncertain
   lines. Creating a product and binding the source row must be atomic,
   scoped and idempotent; preserve the original row classification. An old
   acknowledgment must not satisfy the three-way decision. Mapping/creation
   must still require an explicit human product approval, never automatic
   acceptance. Planned files: `backend/api_models.py`, `backend/service.py`,
   `backend/review_summary.py`, `backend/responses.py`, `backend/app.py`,
   `web/local-reader/app.js`, `web/local-reader/workflow.js`, tests and the
   affected generated API contracts. Add persistence/migration only if the
   existing review-event storage cannot represent the decisions safely.

3. **Independent completeness (goal 8; F1).** Record a per-page comparison of
   provider product-line count with an independent reviewer-confirmed count
   as the minimum supported path. Use text-layer counts only where a defined
   rule can distinguish product lines; generic text-line counts are not
   product counts. Pages without independent evidence stay partial and
   unresolved; mismatches block processing completion and review resolution.
   Provider declarations and page acknowledgment cannot clear the blocker.
   Correcting a confirmed count requires a reason and append-only evidence;
   omitted rows remain blocked until a source-bound added-row/reconciliation
   event accounts for them. Planned files: `backend/service.py`,
   `backend/api_models.py`, `backend/review_summary.py`, `backend/responses.py`,
   `backend/app.py`, website review controls and tests; `backend/models.py`
   and `alembic/versions/` if durable coverage records require a migration.

4. **Source grounding (goal 7).** Compare each observed product's text with
   independently decoded page text, or crop OCR when an existing local OCR
   path is available. Keep original strings intact and record the comparison
   method/evidence. Flag unsupported text and unavailable independent text
   for human review; do not claim that empty text on a scanned page proves
   fabrication. A source flag requires explicit source-bound review and
   cannot silently approve a product. Planned files: `backend/uploads.py`
   or a small `backend/source_checks.py` helper, `backend/service.py`,
   `backend/responses.py`, `backend/review_summary.py`, website and tests.
   No paid OCR/provider and no new model installation is planned.

5. **Same-row evidence (F3).** Validate quantity/unit references against the
   row's page and declared row region, rejecting a reference on another row
   or page. If shared unit headers need support, use an explicit validated
   association rather than accepting arbitrary regions. Planned files:
   `backend/contracts.py`, review evidence validation in `backend/service.py`,
   affected contract schemas and focused contract/API tests.

6. **Small adjacent repairs (F7, F8).** Add bounded label-aware literal code
   hints for fictional `A123`/`2026` cases while retaining conservative rules
   for unlabeled dates/quantities. Define explicit page/document acknowledgment
   scopes so website requests do not use invalid null region references,
   including partial pages with no regions. These scopes must not clear
   completeness or row-decision blockers. Planned files: `backend/catalog.py`,
   `backend/api_models.py`, `backend/service.py`, `web/local-reader/workflow.js`,
   affected contracts and tests. If F5, F7 or F8 expands beyond a small repair,
   document the precise remaining fault and follow-up in this PR for Claudio.

No legacy `po_reader` CLI edits (F4 is already fixed by PR #3 on main).
No dotenv reads, keys, paid calls, customer data, production database, model
training, deployment or cart/order actions belong to this task.

## Validation after Claudio's plan comment

- Reuse PR #5's fixed-JSON fake provider, generated fictional PDFs/PNG/JPG and
  disposable PostgreSQL cluster. Keep its dotenv and external transport guards.
- Remove each of the eight strict xfail markers only with its behavior fix;
  retain the existing assertions and add meaningful adversarial regression
  coverage for tiers/conflicts, three-way answers, cross-tenant creation/binding,
  idempotency, missing counts/mismatches, invented text, cross-row/page evidence,
  labeled codes and actual website acknowledgment request shapes.
- Run `pytest -m goal` and regenerate `docs/goal-scorecard-2026-10-03.md` from
  actual outcomes. Report skips as blocked, not passed. Run affected backend,
  contract and website tests with their explicit suite configurations, including
  migration checks if persistence changes. Use `git diff --check` before push.
- Exercise changed review controls using fictional sources only, confirming
  that preselection is not approval and unresolved blockers prevent Finish.
- Give each goal item its own implementation commit; keep optional F5/F7/F8
  repairs separately reviewable. Post the measured scorecard as a signed PR
  comment and update `docs/agent-handoff.md` when implementation finishes.

## Review gate

The initial draft contained this plan only. Claudio authorized A's tiers,
three answers and same-row evidence, with separate commits, an explicit
Certain approval test, visible tenant-scoped review-origin catalog entries,
and a migration cycle on a throwaway database. Those conditions are implemented
and tested; measured outcomes are in the goal scorecard. B's completeness,
grounding and F7/F8 remain proposals. All PR comments start with
`**Codex · goal gaps:**`. Later implementation stays on this PR; merge requires
an `Approved at <commit>` comment matching the current head and passing tests.
Carlos's hold stops work.
