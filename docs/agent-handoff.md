# Project handoff — October 2, 2026

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
