# v1.1 Safety Net backend integration plan and claim ledger

Author: **Codex · integration**. PR #20, Tier 3, base `integration/ui-and-matching`.
Carlos approved the revised backend-only scope in [signed go](https://github.com/CarlitosRed/advance-po-reader/pull/20#issuecomment-6064563292).
The [original five conditions](https://github.com/CarlitosRed/advance-po-reader/pull/20#issuecomment-6023893815)
apply to the backend, with current-screen controls deferred under that go.

## Plan

Bring #9's approved backend items 3, 4 and 6 onto landing prep while preserving
the current v1 screen and default behavior. Normal landing merge: `0d432b10d4de39845e162a724ef54e404c7de1a0`,
from `398210a1ac7188e8c1e8aa2abdabe3c3fe14c760`. Safety input:
`100f1d83bb385aeeb55527b7beb2fb675cdf916b`.

The selective two-parent safety merge `cbe4eb6` retains both histories. An `ours`
merge established the parents without writing any UI file; `git apply --3way`
applied the exact #9 diff for backend, contracts, tests, pytest configuration
and documentation. Both documentation conflict sides were retained. #9's
browser-control script and four-mode UI test changes were intentionally excluded:
they require controls assigned to the separate new UI track. Existing v1 browser
checks remain. This is a selective textual backend merge, not a claim of a full-tree #9 merge.

Add one setting, `Settings.safety_net_finish_blocking`, environment name
`PO_BACKEND_SAFETY_NET_FINISH_BLOCKING`, default **false**. OFF preserves v1
processing states, retrieval order (including the old description-code route),
region acknowledgments and Finish. ON enables #9's source checks, independent
counts, typed acknowledgments and labeled literal SKU hints; clean runs wait
for independent coverage before becoming completed. Source confirmations and
counts remain separate from product decisions in both modes. Count routes are
available in both modes; OFF does not let them alter processing state.

No implementation changes under `web/`, no script/demo-page changes, no prompt,
tier-policy, gate configuration, live provider, migration or production changes.
Contract changes are additive except that ON requires typed acknowledgments.
Historical OFF runs without grounding require a new processing run under ON;
legacy region acknowledgments cannot silently acquire source-bound meaning.
The new UI will drive the enabled APIs and build the controls once.

## Risk and state ledger

| State | Configuration / evidence | Meaning and limit |
| --- | --- | --- |
| S1 | OFF (default) | Current v1 Finish policy and known grounding/completeness gaps remain. |
| S2 | ON, missing counts or source confirmation | API blocks Finish; product approval alone is insufficient. |
| S3 | ON, partial page or document warning | Typed source/page/run acknowledgment required, separately from counts and decisions. |
| S4 | OFF history reopened with ON | Missing grounding needs new processing; legacy acknowledgment is insufficient. |
| S5 | ON, all checks and decisions satisfied | Finish may resolve; the endpoint rechecks stored source bytes. |
| S6 | Resolved review | Existing immutability remains; events and source observations are retained. |

## Claims ledger

Line references below are repository-relative implementation pins; the PR evidence
comment supplies the immutable final head. Exceptions are deliberate mode boundaries.

| Claim | Exact condition | Exception | Implementation pin | State |
| --- | --- | --- | --- | --- |
| Safety Net defaults OFF | Settings created without explicit override | Environment may explicitly enable it; dotenv is not needed | `backend/config.py:27` | S1 |
| Default demo Finish remains available after decisions | OFF, all original v1 blockers cleared | Partial pages/warnings still need the original region acknowledgments | `backend/service.py:235`, `backend/review_summary.py:18` | S1 |
| Counts and grounding block Finish | ON, missing/mismatched independent counts or missing source confirmation | OFF retains original gaps | `backend/review_summary.py:18` | S2 |
| Each product contributes to one page count | Schema 1.1/1.2 product row, attributed to its earliest source evidence page | Continuation/detail rows and repeated evidence add no products | `backend/coverage.py:8` | S2, S5 |
| Confirmation never approves a product | Source/page/count event only | A separate explicit product decision may already exist | `backend/review_summary.py:80` excludes source confirmation from latest decision | S2 |
| Typed acknowledgment is bound to source and run | ON page/document acknowledgment | OFF accepts the original region evidence; ON ignores that legacy history | `backend/service.py:459`, `backend/review_summary.py:55` | S3, S4 |
| A zero-product document remains blocked | Either mode, no product/unknown rows; matching zero counts do not clear `unresolved_rows_remain` | Detail rows do not satisfy the product-review requirement | `backend/review_summary.py:27` | S1, S2 |
| Changed stored bytes prevent enabled Finish | ON resolve, exact stored hash checked | Summary is a projection, not a fresh file-integrity check | `backend/service.py:235` resolve branch | S5 |
| Labeled hints use bounded exact SKU lookup | ON only | OFF uses the unchanged existing retrieval route; no tier policy changed | `backend/catalog.py:244` | S1, S2 |
| Resolved review remains immutable | Any mode, resolved review | Existing idempotent replay rule is retained | `backend/service.py:235`, `backend/service.py:479` | S6 |

## Expected defect classes and sweeps

- Mode boundaries: default/env setting, processing states, retrieval methods,
  direct resolve vs summary, count-state synchronization, legacy history after
  enabling. Exercise OFF and ON through actual API calls; retain original OFF
  strict expected failures and ON positive cases.
- Count request fields: strict nonnegative integer page/count, 64 lowercase hex
  source hash, explicit boolean discrepancy, nonblank reviewer/reason, latest
  correction UUID and count-error attestation. Sweep missing, malformed, stale,
  cross-page/run/tenant and source-discrepancy cases in inherited #9 tests.
- Review scope fields: action, row vs page vs document scope, region membership,
  integer page, source hash, document/run UUID, extra fields and one-reference
  cardinality. Sweep missing/renamed/case-changed scopes, newline/Unicode hashes,
  boolean/float/outside pages, wrong document/run and persisted legacy events.
- Source evidence: unsupported vs unavailable text, all flagged regions, exact
  source bytes and separate product approval. Sweep PDF and generated PNG/JPG,
  partial pages without regions, zero-product document and legacy missing checks.
- Matching: inherited tenant/vendor/pool, bounded exact labeled hints and
  pg_trgm-present/absent cases; OFF preserves the original method and tiers.
- Preservation/platform: Windows PowerShell, owned native PostgreSQL, both
  backend+goal and separate-goal JUnit inventories, current-tab browser flow,
  byte-identical `web/`, scripts and gate.json against landing prep.
- Documentation: claim/mode/pin/state ledger, historical #9 banners, checked
  local links and Mermaid fences; distinguish local browser evidence from CI skips.

## Evidence protocol

Baseline at landing prep: backend **373 passed**; goals **61 passed, 2 skipped,
2 strict expected failures**. Final measured counts and JUnit preservation
results are in `goal-scorecard-integration-2026-10-08.md`, the PR evidence
comment and the external audit note. All new #9 goal modules explicitly enable
Safety Net; current-screen browser tests exercise OFF. New Safety Net UI controls
and condition 1's real-browser separation proof are deferred to the new UI.
Backend separation, blocker API visibility and independent-count semantics are tested.

Run both full suites with desk-local runtime/basetemp, injected fixed providers,
actual disposable PostgreSQL and generated fictional source bytes. Run the free
demo and checked-in current-tab verifier on a checked unused port, then stop
only the owned server/cluster. Compare inherited goal test functions against
both JUnit sets; compare inherited backend functions against backend+goal JUnit.
Report browser exclusions as exclusions, not as executed proof.

Run `pip check`, `git diff --check`, gate content scan over outgoing history,
and gate merge dry-run. The dry-run cannot pass state while the explicitly
requested base is non-main and the PR is draft; PM retargets after landing.
Independent review and Carlos's exact-head approval remain pending.

The supplied batch scorer has no stored-only mode: it reads originals and can
fall back to a paid OpenAI call. Only its pure summary functions were used on
saved counts-only JSON. Successful historical snapshots retain **150 product
rows, count matches 33/33**, out of 351 total rows including non-products.
This is aggregate snapshot verification, not a new-backend re-score of live
stored runs. That requested proof remains limited by the no-real-PO/no-paid-call
boundary and needs a strictly read-only counts-only harness before readiness.

## Plain-English summary

The backend can now require a person to check page counts and source evidence
before Finish. The feature starts switched off, so the current demo still
finishes through its existing tabs. The new UI will supply the added controls.
No product is approved by confirming source text or entering a count. Local
synthetic tests establish behavior; they do not measure model accuracy.

## Cost

$0 API spend. No paid calls, dotenv opens, original PO reads, private catalog
access, deployment, order write, self-approval or PR merge.

## Broader history diagnostic and required scan evidence

A broader ancestry-range diagnostic from the former remote PR #20 head reports
inherited #9 fake key-shaped test strings in `950ca7e`, `53a092d`, `100f1d8`,
and old branding images introduced by landing history `6daa449`. The final
worktree contains no branding image changes relative to landing prep, and
the current fixture already uses landing prep's neutral fictional test value.
The requested normal merges retain those pre-existing remote ancestors. The
staged scan of the 26 implementation paths and the pre-push `--outgoing HEAD`
scan of unpublished commits both pass. Normal `git push` succeeded; no rebase,
force push, gate/hook bypass or gate.json change was performed. Exact-head CI
`scan --rev HEAD` also passed. The broader diagnostic is recorded separately
and does not negate those narrower results. No repair of ancestral history is
claimed. Fresh stored-batch re-scoring remains the independent evidence limitation.

## Measured local checkpoint

- Backend+goal: **542 passed, 2 strict expected failures, 0 skips, 0 failures/errors**.
- Separate goals: **169 passed, 2 strict expected failures, 0 skips, 0 failures/errors**.
- Original 65 goal cases map to **63 passed and the same 2 OFF expected failures**;
  the baseline's two browser skips now pass locally.
- Both JUnit suites contain all **73 inherited goal test function names** from
  landing prep and #9; backend+goal also contains all **206 inherited backend
  function names**. No missing function. #9's four UI mode variants are explicitly
  excluded because those controls are deferred; function-name preservation is
  not a claim that their UI parameter matrix executed.
- Current demo start and browser verifier: **153 fictional products, 5 cases**;
  PDF/PNG/JPG uploads, tabs, quantities, decisions, Finish and resolved reload pass;
  **0 external browser requests, 0 page errors**. Owned port 8031 and demo
  PostgreSQL stopped. No existing service was touched.
- Local Markdown links: **0 broken** in changed docs; **0 Mermaid blocks**.
- `pip check` and `git diff --check` pass. Gate.json, scripts and the complete
  `web/` tree match landing prep. Final-tree scan and history scan are separate
  evidence; the broader inherited-history diagnostic is recorded separately.
