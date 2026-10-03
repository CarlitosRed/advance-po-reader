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
