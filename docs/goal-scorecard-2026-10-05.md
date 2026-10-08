> Historical PR #9 artifact at `100f1d83bb385aeeb55527b7beb2fb675cdf916b`. In v1.1 integration these Safety Net rules apply only when `PO_BACKEND_SAFETY_NET_FINISH_BLOCKING` is ON; it defaults OFF. New controls are deferred to the separate UI track. See [current integration plan](integrate-safety-net-plan.md).

# Goal acceptance scorecard — rerun October 5, 2026

Execution: local isolated run. Suite: `python -m pytest -m goal`. Skips count as blocked; strict xfails are separate.

T-007 acceptance suite; T-009 PR A plus PR B items 3/4/6 (independent counts, source grounding and F7/F8). Base `codex/worktree-standards` at `fe5c1f421c4293d0b993a5e2e4abecc69fba500c` (merged PR A). The original PR #5 baseline was 10 passed and 8 strict xfail.

Measured with generated fictional PDFs/PNG/JPG, fixed JSON from an injected fake provider, actual upload/processing/catalog/review HTTP routes, and a disposable PostgreSQL cluster. No model accuracy or real-document performance is measured.

| Goal | Passed | Xfail | Blocked | Failed |
| --- | ---: | ---: | ---: | ---: |
| 1 | 1 | 0 | 0 | 0 |
| 2 | 24 | 0 | 0 | 0 |
| 3 | 1 | 0 | 0 | 0 |
| 4 | 3 | 0 | 0 | 0 |
| 5 | 15 | 0 | 0 | 0 |
| 6 | 13 | 0 | 0 | 0 |
| 7 | 41 | 0 | 0 | 0 |
| 8 | 21 | 0 | 0 | 0 |
| 9 | 8 | 0 | 0 | 0 |
| 10 | 18 | 0 | 0 | 0 |

Total: 145 passed, 0 xfail, 0 blocked, 0 failed. Pytest exit status: 0.

## Remaining work

F7/F8 are implemented in item 6. PR #9 still requires exact-head review; CI execution and browser availability must be reported separately.

## PR A behavior verified

Goals 4–6 now pass: only Certain is initially preselected, every product still needs explicit approval, and Uncertain rows require an existing-product binding, a marked new-product binding, or explicit not-a-product exclusion. Catalog creation and binding are atomic and retry-safe; review-created products stay tenant/vendor/pool scoped and expose origin=review. Corrections keep the original strings and require fresh approval. Quantity/unit evidence must reference that row or a fully contained cell on the same page; unlinked shared headers are rejected. A clean throwaway database passes upgrade/downgrade/upgrade.

## PR B item 3 behavior verified

Each source page requires an independent, attributed reviewer product count bound to its exact hash and run. Missing evidence and count mismatches block Finish; zero with product rows is a mismatch, and empty pages need their own zero count. Original product items are counted without continuations/details or row exclusions. Count corrections append evidence and require a latest-event reference, reason and independent-count-error attestation. A reported source discrepancy stays blocked in the old run; a new run receives no copied count or product approvals. Matching counts do not approve products. The local backend OpenAPI snapshot is compared with app.openapi().

## PR B item 4 behavior verified

Literal product descriptions and identifiers are compared only inside their declared source regions on the hash-checked PDF. Unicode case-folding and whitespace normalization preserve punctuation/numbers and require contiguous phrase token boundaries. Original observations, literal decoded text and normalized evidence stay separately recorded. Unsupported text needs attributed row source review; unavailable text retains all tiers and needs one source-bound page confirmation for all affected rows. Neither action approves products or clears count/row blockers. Legacy runs lacking grounding need new processing. Goal 7's original assertion passes without an xfail. Browser cases exercise text, photo and unsupported-row controls against the isolated API.

## PR B item 6 behavior verified

Explicitly labeled short, alphabetic and date-shaped codes (including A123/2026) are bounded literal SKU retrieval hints within the authorized tenant/vendor/pool. Tests execute with and without the actual pg_trgm extension in a disposable transaction. Descriptions/identifiers remain literal, unlabeled dates/quantities/currency stay conservative, conflicts veto Certain, and every product requires explicit approval. Region evidence remains bound to the row; page acknowledgments name the exact hash/page including partial pages without regions; document acknowledgments name source/hash/run. The real website buttons send these scopes and cannot bypass row, grounding or count blockers. Historical region audit evidence remains readable. OpenAPI is regenerated.

Browser check: passed against the real review controls and test-owned API, including source-text confirmation and page/document acknowledgment controls.

## Expected failures


## Interpretation and isolation

Each goal has one or more separately scored clauses. A passed clause does not mean its entire goal passed. Strict xfail marks fail on unexpected success; they only catch AssertionError so harness/infrastructure errors stay visible.

Goals 1–3 test the backend's handling of hand-authored extraction observations; the fake provider does not prove that a vision model finds or classifies rows. Goal 2 tests the backend's actual description-code retrieval. Goals 7–8 deliberately give the fake provider incorrect but schema-valid observations.

All OPENAI_API_KEY and PO_BACKEND_* variables are removed inside the test process; Settings uses `_env_file=None`. Dotenv file opens, built-in provider extraction and external HTTP transports are guarded. No `.env` file or customer document is opened. Application configuration and storage path roots are redirected only in the test harness, so repository `data/` and `output/` stay untouched. Existing services and databases are not migrated or restarted. This scorecard measures the changed PR B source with isolated fixtures; it is not production validation.

Locally PostgreSQL is initialized on an available loopback port from GOAL_POSTGRES_BIN (or PATH), with an owned cluster and fresh `gate_a_test_backend_*` database. CI creates fresh databases on its ephemeral loopback PostgreSQL service, never a preexisting application database. Migrations and pg_trgm run there. Each created database is dropped at teardown; only the locally owned server is stopped. Missing binaries are reported as blocked skips; initialization or migration errors fail setup rather than becoming xfail.
