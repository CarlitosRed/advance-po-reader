# T-009 PR B: completeness, source grounding and F7/F8

Owner: **Codex · goal gaps:**. Reviewer: Claudio. Date: 2026-10-03.
Status: plan-only draft. Carlos requested this draft after PR A was marked ready.
Implementation waits for **PR A #7 to merge** and **Claudio's go on this plan**.
No application code, tests or migrations change in this draft.

PR A's tested head is `21e9fc47442d61a95817411e432eb5ab910c401f`, with
49 passed and 2 strict xfail. That is A's measurement, not a new run on this
plan branch. The remaining xfails are goals 7 (source grounding) and 8
(independent product-line completeness). A supplies tiers, explicit line
answers, scoped/marked review-created products and same-row quantity/unit
evidence. B will refresh from the merged A base before implementation.

Follow AGENT-WORKFLOW rule 3, AGENTS.md, PROJECT_GOAL.md and the local logic
rules. Preserve source hashes, literal observations, immutable candidate sets,
append-only human decisions, tenant/vendor/pool scope and explicit approval.
No dotenv reads, keys, OpenAI calls, real PDFs, customer catalogs, production
database, model installation, training, deployment or cart/order actions.

## Item 3: independently check every page's product-line coverage

- Record a comparison between the provider's product-item count and an
  independent count on each source page. The minimum supported independent
  path is an attributed reviewer-confirmed product count bound to that page
  and source hash. A generic text-line count is not a product count; use a
  text-layer signal only if an explicit, tested rule identifies product lines.
- Persist count, method, page/source evidence, reviewer/reason where relevant,
  and matched/mismatch/unavailable status separately from the provider payload.
  Continuation and document-detail rows must not inflate product counts.
- Missing independent evidence or a mismatch keeps processing partial and
  blocks Finish. Provider declarations and page/document acknowledgments
  cannot clear coverage blockers. A revised count requires append-only
  evidence; an omitted line remains blocked until a new source-bound run or
  explicit reconciliation accounts for it. Never silently lower the count.
- Reuse A's explicit product binding/approval gate. A count confirmation must
  neither create a catalog entry nor approve an observed product.

Expected files: `backend/service.py`, `backend/api_models.py`,
`backend/models.py`, `backend/review_summary.py`, `backend/responses.py`,
`backend/app.py`, `web/local-reader/workflow.js`, focused tests, generated
contracts and `backend_migrations/versions/` if durable coverage storage needs
a migration. Define permitted processing/review transitions explicitly.

## Item 4: ground product observations in independent source text

- Decode text from the actual hash-checked source page with the existing local
  PDF library. Compare each product's observed text with independently decoded
  text in its declared source region, recording method, comparison evidence
  and supported/unsupported/unavailable status. Keep printed strings intact;
  any comparison normalization must be named and retained separately.
- Flag unsupported product text and make the flag visible in review. A region
  declaration alone is insufficient. Include the flag in the review blockers
  and tier policy without mutating the original extraction.
- A scanned page, photo or empty text layer is unavailable evidence, not proof
  of fabrication. Use an existing local OCR path only if available; install no
  model and call no paid provider. Otherwise require an attributed source-bound
  review of the unavailable/unsupported evidence. Clearing a source flag cannot
  approve a product or clear an independent completeness discrepancy.

Expected files: a small `backend/source_checks.py` helper or
`backend/uploads.py`, `backend/service.py`, `backend/tiers.py`,
`backend/review_summary.py`, `backend/responses.py`, review controls, focused
tests and any required migration/contracts.

## Item 6: bounded F7/F8 repairs

- **F7:** discover explicitly labeled literal catalog codes such as `A123` and
  `2026`, including safe short/alphabetic/date-shaped cases. Query only the
  authorized catalog scope. Preserve the description as a description; a
  retrieval hint does not become a provider-observed identifier. Unlabeled
  dates, quantities and currency remain conservative. A's labeled-conflict
  veto stays in force and no match is automatically approved.
- **F8:** define explicit region/page/document acknowledgment evidence scopes.
  Row actions retain A's same-row region validation. A page acknowledgment
  names a valid source page, including a partial page with no regions; a
  document acknowledgment names the source/run. Make the real website buttons
  send these request shapes instead of null region references. Acknowledgments
  cannot clear row decisions, source grounding or independent coverage blockers.

Expected files: `backend/catalog.py`, `backend/api_models.py`,
`backend/service.py`, `backend/review_summary.py`,
`web/local-reader/workflow.js`, affected contracts and focused tests.

## Validation and delivery after the prerequisites

Use A's fixed-JSON fake provider, generated fictional PDF/PNG/JPG bytes, owned
throwaway PostgreSQL cluster, dotenv/external-transport guards and headless
browser bridge. Do not reuse an existing application's database or service.

1. Keep goals 7/8 strict xfail until their original assertions pass through the
   real processing routes, then remove only those markers. Add missing-count,
   per-page mismatch, invented-region text, empty-text/photo and continuation
   counting cases. Check count corrections/reconciliation cannot hide omissions.
2. Test labeled codes with and without pg_trgm, conflicting evidence and
   unlabeled dates/quantities. Exercise actual acknowledgment buttons against
   partial pages, document warnings and pages with no regions. Verify they never
   bypass source/coverage/row blockers.
3. Preserve A's all-Certain explicit approval, atomic/idempotent creation,
   visible `origin=review`, cross-tenant/vendor/pool isolation and same-row/page
   evidence tests. New source/count records require matching isolation tests.
4. Any migration includes a downgrade and an upgrade/downgrade/upgrade test on
   a separate throwaway database. Refuse any downgrade that would discard
   source-check or human-decision evidence.
5. Give each item its own implementation commit; keep F7/F8 changes easy to
   review. Run `pytest -m goal`, affected suites with explicit configurations,
   changed browser controls and `git diff --check`. Regenerate the scorecard
   from actual results, treating skips as blocked, and update the handoff.
6. Reply to review comments as **Codex · goal gaps:** and post the measured
   scorecard when B is ready. Merge requires `Approved at <commit>` matching
   B's current head with passing tests; Carlos's hold stops work.

This publication requests plan review only. No B behavior is implemented,
no runtime is changed, and no new accuracy or production result is claimed.
