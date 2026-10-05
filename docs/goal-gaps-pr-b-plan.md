# T-009 PR B: completeness, source grounding and F7/F8

Owner: **Codex · goal gaps:**. Reviewer: Claudio · PR review. Updated: 2026-10-05.
Status: plan confirmed at `7438183`; item 3 approved at `53a092d`.
Carlos merged PR A #7 into `codex/worktree-standards` as
`fe5c1f421c4293d0b993a5e2e4abecc69fba500c` on 2026-10-05 at 07:03 UTC.
B includes that merged base through a merge, preserving published history
without a rebase or force-push. Claudio · PR review confirmed the revised
plan at `7438183646873bdef52f5211357e85e0626b389a` on October 5 at 17:55:42 UTC;
Carlos gave GO to code B. Item 3 now implements the attributed reviewer-count
path using the existing append-only review-event storage, so no new migration
is needed. The first contract-changing commit regenerates OpenAPI and adds its
application comparison test. Items 4 and 6 still follow the scoped plan below.

PR A's approved head `54c979e457e9fa83e0ac22ada12cb2b3385e0a21` is a parent
of the merge. A's CI measured backend 268 passed and goal 53 passed,
1 documented browser skip and 2 strict xfails; its local goal run measured
54 passed, 2 strict xfails and no skips. These are A's measurements, not new
local runs on this plan branch. The remaining xfails are goals 7 (source
grounding) and 8
(independent product-line completeness). A supplies tiers, explicit line
answers, scoped/marked review-created products and same-row quantity/unit
evidence. B also inherits A's full backend and goal CI job; new B tests must
run in those suites before implementation can be considered verified.

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
- Persist each reviewer count per source page and exact source hash, scoped
  to the tenant and run, with count, method, page/source evidence,
  reviewer/reason, timestamp and matched/mismatch/unavailable status separately
  from the provider payload. Counts are nonnegative integers. A count of zero
  on a page with extracted product rows is a mismatch, never missing evidence
  or a successful empty-page check. A genuinely empty page still needs its own
  independent zero count; another page's count cannot stand in for it.
  Continuation and document-detail rows must not inflate product counts.
- **Reconciliation choice: rerun-only in B.** A missing or extra product line
  requires a new source-bound run against the same immutable source hash; B
  adds no action that inserts/removes extracted rows or overrides a count
  mismatch in the existing run. Keep the old run, observations and decisions
  intact. The new run must receive its own independent per-page checks and
  explicit product decisions before it can finish; starting it is subject to
  the existing source/provider authorization rules and is not an automatic retry.
- Missing independent evidence or a mismatch keeps processing partial and
  blocks Finish. Provider declarations, row exclusions, generic page/document
  acknowledgments and unavailable-text confirmations cannot clear coverage
  blockers. Surface the mismatching page, compared counts and the new-run
  remedy in the review controls, so the reviewer has an actionable next step.
  `partial` therefore also means awaiting independent counts, even when the
  provider returned a complete payload. A zero-product whole document may
  finish after every page has an independent matching zero count and all
  page/document warnings and other review blockers have been addressed;
  no product approval is required when there are no product rows.
- A reviewer may correct a genuinely mistaken independent count only by a
  new attributed, reasoned, append-only count record bound to the same page,
  source hash and run; preserve the prior record. The latest source-supported
  count is compared again. This is a count-evidence correction, not row
  reconciliation: it cannot represent an omitted line, remove an extra line
  or silently lower the count to match the provider. A discrepancy that still
  exists in the source requires the new-run remedy above.
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
  and supported/unsupported/unavailable status. A valid region declaration by
  itself does not prove text support.
- **Comparison normalization:** apply Unicode case-folding, collapse each run
  of Unicode whitespace to one ASCII space, and trim leading/trailing space
  on both observed text and decoded region text. Compare complete observed
  text as a contiguous phrase with alphanumeric token boundaries in the
  normalized region text. Do not erase punctuation or numbers, rewrite codes,
  apply fuzzy matching, or search other regions/pages to rescue a failed
  comparison. Preserve literal observations and decoded source text; retain
  the normalized comparison evidence and named method separately.
- Grounding status remains separate from candidate tier and product approval.
  Unsupported product text is a visible row-level source flag and blocker;
  it requires an attributed source review/correction through the existing
  audited review flow. Generic acknowledgment cannot clear it. A source-flag
  decision cannot approve a product or clear independent count discrepancies.
- **Unavailable-text policy:** a scanned page, photo or empty text layer is
  unavailable evidence, not proof of fabrication. It retains each line's
  existing Certain/Probable/Uncertain tier and its normal selection policy;
  no tier is demoted because independent text is unavailable. Use an existing
  local OCR path only if already available; install no model and call no paid
  provider. Preserve the unavailable status when no independent text exists.
- Provide one distinct, attributed page-level `confirm_unavailable_page_text`
  review action bound to the tenant, run, exact source hash and page, with
  reviewer, reason and timestamp in append-only evidence. It satisfies the
  unavailable-text review requirement for every affected row on that page;
  no additional per-row grounding confirmation is required. It does not turn
  unavailable text into a claimed text match, resolve unsupported text,
  approve products, clear normal row decisions, or clear the item 3 count
  blocker. A generic page/document acknowledgment is not this confirmation.
  Each affected page needs its own confirmation; a new run requires its own
  source-bound evidence.

Expected files: a small `backend/source_checks.py` helper or
`backend/uploads.py`, `backend/service.py`, `backend/api_models.py`,
`backend/models.py`, `backend/review_summary.py`, `backend/responses.py`,
review controls, focused tests and any required migration/contracts.

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
   real processing routes, then remove only those markers. Cover missing
   counts, per-page/source-hash binding, zero count with product rows as a
   mismatch, genuinely empty pages, continuation counting, and append-only
   reviewer-count corrections. Prove a mismatch stays blocked in the old run
   and a new source-bound run requires fresh checks rather than copying approval.
   For grounding, test an invented product string inside an otherwise valid
   real source region and a correct product string in that same region; the
   invented text must be unsupported and the correct text supported. Test
   case/whitespace equivalence, token boundaries and wrong-region/page text
   without rewriting literal observations. On scanned/empty-text/photo pages,
   preserve all three tiers, including Certain, and show that one attributed
   page confirmation satisfies unavailable-text review for multiple rows while
   product approvals, unsupported flags and a mismatched count remain blocked.
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
   review. Run the full backend (`pytest -c pytest.backend.ini
   --isolated-backend`) and `pytest -m goal`, affected suites with explicit
   configurations, changed browser controls and `git diff --check`. Verify
   the inherited `backend-goal` CI job runs both full suites including B's new
   cases at B's head; local output alone does not satisfy the CI prerequisite.
   Name CI and local coverage separately, including the documented CI browser
   skip and the actual local browser result. Regenerate the scorecard from
   actual results, treating skips as blocked, and update the handoff. In the
   first B contract-changing commit, regenerate `contracts/local-backend-openapi.json`
   and add a comparison with `app.openapi()` to close A's non-blocking snapshot nit.
6. Reply to review comments as **Codex · goal gaps:** and post the measured
   scorecard when B is ready. Merge requires `Approved at <commit>` matching
   B's current head with passing tests; Carlos's hold stops work.

The plan gate is satisfied. Each implementation item is committed separately
and requires re-review at its exact head; final code approval must say
`Approved at <commit>`. Count corrections explicitly reference the latest
record and attest `independent_count_error`; a reviewer-confirmed source
discrepancy permanently keeps that old run blocked. The website can prepare
a new run of the same source without copying source authorization, counts or
product approvals, and without automatically starting provider processing.
No model accuracy or production result is claimed.
