# Three-tab review and safety-net integration plan

Author: **Codex · integration**. Status: plan only; implementation awaits the
independent reviewer's `go`. Intended tier: **tier-3**, because the free-demo
fixture generator and checked-in browser verifier under `scripts/` may need
compatibility changes. This is a new draft PR, so the current project workflow
applies even though PR #9 predates the gate.

## Problem and exact inputs

The approved tabs and matching stack has no controls for the independent page
counts and source checks that PR #9 requires before Finish. Importing #9 alone
would leave a review that cannot finish through the three-tab screen.

- Base: `integration/ui-and-matching`,
  `7d971391155e2ad367319d5b2ff19edcf50f9bbc`.
- Safety net: `origin/codex/close-goal-gaps-b`,
  `100f1d83bb385aeeb55527b7beb2fb675cdf916b`, PR #9 items 3, 4 and 6.
- New branch: `codex/integrate-safety-net`.
- New desk: `C:\Users\carlo\dev\advance-po-reader.worktrees\integration-safety-net`.

The requested base is appropriate: it contains the combined tabs and matching
stack, so this PR isolates the safety-net integration. It is not a PR to main.
A read-only merge-tree simulation at these heads reproduces exactly six
conflicting files. No working-tree merge has been started.

## Plan

1. After reviewer `go`, merge the pinned safety-net head into this branch.
   Preserve both sides in `docs/agent-handoff.md`,
   `docs/goal-acceptance-tests.md`, `tests/goal/review-controls.cjs`,
   `tests/goal/test_goal_review_controls.py`, `web/local-reader/app.js` and
   `web/local-reader/workflow.js`. Retain #9's backend, contract and regressions
   alongside the existing matching changes. Check the combined backend diff
   explicitly; do not change count, grounding, retrieval, tier or approval rules.
2. Add page-count entry and attributed mistaken-count correction to the tabs
   and summary. POST to the existing `/runs/{run_id}/page-counts` endpoint with
   reviewer, reason, page number, exact source hash, product count and explicit
   source-discrepancy flag. Corrections identify the prior count event and use
   `correction_kind: "independent_count_error"`. An actual source discrepancy
   stays blocked and offers a new source-bound run; never lower a count to hide
   an omitted line. Independent counts remain separate from provider counts.
3. Show source-grounding flags and literal comparisons on the affected row.
   Provide source inspection and `confirm_source_text` with evidence covering
   every flagged field region on that same row/page. Preserve the unsupported
   result and keep source confirmation separate from product approval.
4. Offer one `confirm_unavailable_page_text` control for each affected page.
   Its evidence is `{scope: "page", page_number, source_sha256}`. It preserves
   unavailable text and cannot clear product decisions or count mismatches.
5. Send typed page/document acknowledgments: page evidence names scope, valid
   source page and exact hash; document evidence names scope, source document,
   run and exact hash. Include partial pages without regions. Generic
   acknowledgments cannot clear the count, source or row-decision blockers.
6. Keep Finish controlled by the current backend `can_finish_review` response.
   Make all remaining blockers reachable even while rows still await answers;
   an apparently completed tab must not imply the order can finish. Preserve
   tabs, empty-tab handling, snapshots, explicit three-way decisions, separate
   product approval, quantity standardization, CSV export and resolved review
   immutability.
7. Preserve the free demo with fictional fixture compatibility updates as
   required by #9's page-count declarations. The fixture's provider declaration
   must never become an independent reviewer count. Update the checked-in demo
   verifier to exercise the added controls before Finish. Keep paid providers,
   the provider prompt and existing running applications untouched.

## Files and commit boundaries

- First implementation commit: merge #9 and resolve the six conflicts while
  preserving the two existing test sets and documentation histories.
- Second: combined controls and meaningful integration regressions in
  `web/local-reader/{app.js,workflow.js,styles.css}` and `tests/goal/`, plus
  test-fixture/import compatibility where needed in `tests/backend/`.
- Third, if needed: fictional demo declarations and verifier compatibility in
  `scripts/poc_demo_support.py`, `scripts/verify-poc-demo.{py,cjs}`,
  `fixtures/poc-demo/`, and related demo tests/runbook.
- Update the acceptance guide, measured integration scorecard and handoff with
  actual results; retain historical scorecards as historical measurements.

Push small commits to this same draft PR with signed exact-head evidence.
Re-check remote input heads before merging. If an input moves, report it rather
than silently incorporating unreviewed changes. No rebase, force-push,
self-approval, self-review or merge of this PR is planned.

## Validation

Create this desk's own `.venv-goal`; do not copy another desk's environment.
Use fresh ignored worktree-local basetemp directories, generated fictional
PDF/PNG/JPG bytes, fixed JSON and harness-owned disposable PostgreSQL.
Keep dotenv and external-transport guards active.

Run both named suites with Node/Playwright and installed Edge enabled:

```text
python -m pytest -c pytest.backend.ini --isolated-backend -q --basetemp=.backend-review-integration-1 -p no:cacheprovider --tb=short --junitxml=.backend-review-integration-1/results.xml
python -m pytest -m goal -q --basetemp=.goal-review-integration-1 -p no:cacheprovider --tb=short --goal-scorecard=docs/goal-scorecard-integration-2026-10-06.md --junitxml=.goal-review-integration-1/results.xml
python -m pip check
git diff --check
```

Compare JUnit case sets: every #9 goal regression and the tabs regressions must
execute in both suites. Run all four inherited browser modes (text, photo,
unsupported text, page/document acknowledgments) and the empty-tab browser test.
Add real-button combined-flow coverage: a clean generated order reaches Finish
through the tabs only after explicit decisions and independent counts; a
mismatch stays blocked until a valid attributed count-error correction;
source confirmation does not approve a row; unavailable-page confirmation and
typed acknowledgments leave other blockers in place. Verify source observations
and tiers remain unchanged, then reload the resolved review and verify CSV.

Run the checked-in free-demo API and browser verifiers using only a newly owned
runtime on a checked unused port. Leave all existing servers and desks intact.
Verify fictional PDF/PNG/JPG cases, snapshots, quantities and CSV. Report local
browser results separately from CI's deliberately absent browser tools.

Inspect exact-head CI for the backend-plus-goal and separate-goal steps and
their JUnit case sets, then report pass/skip/xfail/failure counts explicitly.
Gate A and legacy Python checks are separate evidence. A queued or cancelled
job is not a passing test suite. No model-accuracy or production claim follows
from these fixed-provider checks.

## Evidence

At plan publication: the new desk is clean, both input heads match the brief,
PR #9 remains draft and unmerged, and merge-tree confirms the six conflicts.
No integration implementation, test execution, demo launch or backend change
has been performed. Results from prior PRs are reference evidence only.

Checkpoint and stop at approximately 60% context in
`C:\Users\carlo\dev\project-notes\audits\handoff-codex-integration-2026-10-06.md`.
Any earlier reviewer gate and unfinished work must be explicit in the handoff.

## Cost

$0 API spend. No paid calls, `.env*` access, customer PO/catalog data in Git or
comments, deployment, order write, or existing application service/database
change is authorized.
