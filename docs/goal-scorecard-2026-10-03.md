# Goal acceptance scorecard — 2026-10-03

T-007 acceptance suite; T-009 PR A (tiers, three answers, same-row evidence). Base `codex/worktree-standards` at `c06b4e9994277997e6ec8b828317cb5942e0daf6`. The original PR #5 baseline was 10 passed and 8 strict xfail.

Measured with generated fictional PDFs/PNG/JPG, fixed JSON from an injected fake provider, actual upload/processing/catalog/review HTTP routes, and a disposable PostgreSQL cluster. No model accuracy or real-document performance is measured.

| Goal | Passed | Xfail | Blocked | Failed |
| --- | ---: | ---: | ---: | ---: |
| 1 | 1 | 0 | 0 | 0 |
| 2 | 1 | 0 | 0 | 0 |
| 3 | 1 | 0 | 0 | 0 |
| 4 | 3 | 0 | 0 | 0 |
| 5 | 11 | 0 | 0 | 0 |
| 6 | 13 | 0 | 0 | 0 |
| 7 | 14 | 1 | 0 | 0 |
| 8 | 0 | 1 | 0 | 0 |
| 9 | 3 | 0 | 0 | 0 |
| 10 | 2 | 0 | 0 | 0 |

Total: 49 passed, 2 xfail, 0 blocked, 0 failed. Pytest exit status: 0.

## Top 3 gaps

1. Source grounding: a fabricated product can still use a declared region without its text being checked against the source (goal 7; `backend/service.py`).
2. Independent completeness: an omitted printed product is not detected by an independent per-page product count (goal 8; `backend/service.py`).
3. Adjacent F7/F8 repairs remain planned for PR B: label-aware embedded codes such as A123/2026, and valid page/document acknowledgment scopes. These are follow-ups, not additional goal xfails.

## PR A behavior verified

Goals 4–6 now pass: only Certain is preselected, every product still needs explicit approval, and Uncertain rows require an existing-product binding, a marked new-product binding, or explicit not-a-product exclusion. Catalog creation and binding are atomic and retry-safe; review-created products stay tenant/vendor/pool scoped and expose origin=review. Corrections keep the original strings and require fresh approval. Quantity/unit evidence must reference that row's declared page/region; unlinked shared headers are rejected. A clean throwaway database passes upgrade/downgrade/upgrade.

The headless browser check drives the real review controls and test-owned API: Certain preselection creates no decision, Probable/Uncertain are not preselected, all three answers save separate events, and Finish stays disabled until explicit product approvals/exclusions resolve every row.

## Expected failures

- `test_goal_7_invented_line_in_declared_region_is_rejected_or_flagged`: backend/contracts.py only validates page/region references; service.process_run never grounds observed products against source pixels/text
- `test_goal_8_missing_product_line_triggers_completeness_check`: backend/service.py considers a provider-declared complete page complete if any product remains; no independent source product-line count check

## Interpretation and isolation

Each goal has one or more separately scored clauses. A passed clause does not mean its entire goal passed. Strict xfail marks fail on unexpected success; they only catch AssertionError so harness/infrastructure errors stay visible.

Goals 1–3 test the backend's handling of hand-authored extraction observations; the fake provider does not prove that a vision model finds or classifies rows. Goal 2 tests the backend's actual description-code retrieval. Goals 7–8 deliberately give the fake provider incorrect but schema-valid observations.

All OPENAI_API_KEY and PO_BACKEND_* variables are removed inside the test process; Settings uses `_env_file=None`. Dotenv file opens, built-in provider extraction and external HTTP transports are guarded. No `.env` file or customer document is opened. Application configuration and storage path roots are redirected only in the test harness, so repository `data/` and `output/` stay untouched. Existing services and databases are not migrated or restarted. This scorecard measures the changed PR A source with isolated fixtures; it is not production validation.

PostgreSQL is initialized on an available loopback port from GOAL_POSTGRES_BIN (or PATH), with an owned cluster and `gate_a_test_backend_goal_*` database. Migrations and pg_trgm run there. The database is dropped and the owned server stopped during fixture teardown. Missing binaries are reported as blocked skips; initialization or migration errors fail setup rather than becoming xfail.
