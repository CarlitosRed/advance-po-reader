# Goal acceptance scorecard — v1.1 backend integration, October 8, 2026

Execution: local isolated run. Suite: `python -m pytest -m goal`. Skips count as blocked; strict xfails are separate.

T-007 acceptance suite; T-009 PR A plus PR B items 3/4/6 (independent counts, source grounding and F7/F8). Base `codex/worktree-standards` at `fe5c1f421c4293d0b993a5e2e4abecc69fba500c` (merged PR A). The original PR #5 baseline was 10 passed and 8 strict xfail.

Measured with generated fictional PDFs/PNG/JPG, fixed JSON from an injected fake provider, actual upload/processing/catalog/review HTTP routes, and a disposable PostgreSQL cluster. No model accuracy or real-document performance is measured.

| Goal | Passed | Xfail | Blocked | Failed |
| --- | ---: | ---: | ---: | ---: |
| 1 | 1 | 0 | 0 | 0 |
| 2 | 25 | 0 | 0 | 0 |
| 3 | 1 | 0 | 0 | 0 |
| 4 | 3 | 0 | 0 | 0 |
| 5 | 15 | 0 | 0 | 0 |
| 6 | 14 | 0 | 0 | 0 |
| 7 | 41 | 1 | 0 | 0 |
| 8 | 21 | 1 | 0 | 0 |
| 9 | 21 | 0 | 0 | 0 |
| 10 | 27 | 0 | 0 | 0 |

Total: 169 passed, 2 xfail, 0 blocked, 0 failed. Pytest exit status: 0.

## Remaining work

F7/F8 backend rules are available in the enabled mode. PR #20 requires independent exact-head review; CI execution and browser availability must be reported separately.

## PR A behavior verified

Goals 4–6 now pass: only Certain is initially preselected, every product still needs explicit approval, and Uncertain rows require an existing-product binding, a marked new-product binding, or explicit not-a-product exclusion. Catalog creation and binding are atomic and retry-safe; review-created products stay tenant/vendor/pool scoped and expose origin=review. Corrections keep the original strings and require fresh approval. Quantity/unit evidence must reference that row or a fully contained cell on the same page; unlinked shared headers are rejected. A clean throwaway database passes upgrade/downgrade/upgrade.

## v1.1 Safety Net modes

The server setting PO_BACKEND_SAFETY_NET_FINISH_BLOCKING defaults OFF. The default mode preserves v1 processing, existing description-code retrieval and Finish behavior; its two strict expected failures retain the historical grounding/completeness gaps. The added PR #9 modules explicitly enable the setting and verify independent counts, source confirmations and typed source-bound acknowledgments without approving products. Mode regressions include PDF/PNG/JPG, legacy acknowledgments, mode transition, malformed typed evidence and source integrity at Finish. This is fixed-provider evidence only.

New Safety Net UI controls and their browser proof are deferred to the new UI track. No web file is changed by this integration. Current-tab browser checks below exercise OFF.

Current v1 browser checks: passed locally against the isolated API.

## Expected failures

- `test_goal_7_invented_line_in_declared_region_is_rejected_or_flagged[False]`: v1 default OFF preserves the pre-Safety-Net gap
- `test_goal_8_missing_product_line_triggers_completeness_check[False]`: v1 default OFF preserves the pre-Safety-Net gap

## Interpretation and isolation

Each goal has one or more separately scored clauses. A passed clause does not mean its entire goal passed. Strict xfail marks fail on unexpected success; they only catch AssertionError so harness/infrastructure errors stay visible.

Goals 1–3 test the backend's handling of hand-authored extraction observations; the fake provider does not prove that a vision model finds or classifies rows. Goal 2 tests the backend's actual description-code retrieval. Goals 7–8 deliberately give the fake provider incorrect but schema-valid observations.

All OPENAI_API_KEY and PO_BACKEND_* variables are removed inside the test process; Settings uses `_env_file=None`. Dotenv file opens, built-in provider extraction and external HTTP transports are guarded. No `.env` file or customer document is opened. Application configuration and storage path roots are redirected only in the test harness, so repository `data/` and `output/` stay untouched. Existing services and databases are not migrated or restarted. This scorecard measures the changed PR B source with isolated fixtures; it is not production validation.

Locally PostgreSQL is initialized on an available loopback port from GOAL_POSTGRES_BIN (or PATH), with an owned cluster and fresh `gate_a_test_backend_*` database. CI creates fresh databases on its ephemeral loopback PostgreSQL service, never a preexisting application database. Migrations and pg_trgm run there. Each created database is dropped at teardown; only the locally owned server is stopped. Missing binaries are reported as blocked skips; initialization or migration errors fail setup rather than becoming xfail.
