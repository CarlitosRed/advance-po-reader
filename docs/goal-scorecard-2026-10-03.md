# Goal acceptance scorecard — 2026-10-03

T-007; base `origin/codex/worktree-standards` at `183412f4b1daaf8fc49b2a60f91ed8e34b749afb`.

Measured with generated fictional PDFs/PNG/JPG, fixed JSON from an injected fake provider, actual upload/processing/catalog/review HTTP routes, and a disposable PostgreSQL cluster. No model accuracy or real-document performance is measured.

| Goal | Passed | Xfail | Blocked | Failed |
| --- | ---: | ---: | ---: | ---: |
| 1 | 1 | 0 | 0 | 0 |
| 2 | 1 | 0 | 0 | 0 |
| 3 | 1 | 0 | 0 | 0 |
| 4 | 1 | 1 | 0 | 0 |
| 5 | 1 | 1 | 0 | 0 |
| 6 | 2 | 4 | 0 | 0 |
| 7 | 0 | 1 | 0 | 0 |
| 8 | 0 | 1 | 0 | 0 |
| 9 | 2 | 0 | 0 | 0 |
| 10 | 1 | 0 | 0 | 0 |

Total: 10 passed, 8 xfail, 0 blocked, 0 failed. Pytest exit status: 0.

## Top 3 gaps

1. Source grounding and completeness: valid JSON can invent a product in a real region or omit a printed product while processing still reports complete (goals 7 and 8; `backend/service.py`, `backend/contracts.py`).
2. Unknown-line decisions: an unknown row cannot be mapped to product X or a new catalog product. Acknowledgement can exclude it but does not explicitly classify it as not a product (goal 6; `backend/api_models.py`, `backend/service.py`).
3. Confidence tiers: exact and description matches remain generic suggestions; Certain, Probable and Uncertain are absent even though preselection and human approval safety work (goals 4, 5 and 6; `backend/responses.py`).

## Expected failures

- `test_goal_4_exact_code_is_in_certain_tier`: backend/responses.py:SuggestionResponse and catalog.py:_result expose suggested/ambiguous/no_match; no Certain tier
- `test_goal_5_description_only_match_is_in_probable_tier`: backend/responses.py:SuggestionResponse has no Probable tier; description-only trigram matches remain generic suggested outcomes
- `test_goal_6_unknown_line_is_in_uncertain_tier`: backend/service.py skips unknown rows during retrieval; the public review projection has no Uncertain tier for them
- `test_goal_6_unknown_line_accepts_answer_product_x`: backend/service.py:review_run rejects propose_candidate for row_kind unknown with non_product_row_cannot_match
- `test_goal_6_unknown_line_accepts_new_product_added_to_catalog`: catalog/import can add products, but backend/service.py cannot bind that new product to an unknown source row
- `test_goal_6_unknown_line_accepts_explicit_not_a_product_answer`: backend/api_models.py:ReviewRequest has no explicit not_product decision; acknowledge only records generic classification review
- `test_goal_7_invented_line_in_declared_region_is_rejected_or_flagged`: backend/contracts.py only validates page/region references; service.process_run never grounds observed products against source pixels/text
- `test_goal_8_missing_product_line_triggers_completeness_check`: backend/service.py considers a provider-declared complete page complete if any product remains; no independent source product-line count check

## Interpretation and isolation

Each goal has one or more separately scored clauses. A passed clause does not mean its entire goal passed. Strict xfail marks fail on unexpected success; they only catch AssertionError so harness/infrastructure errors stay visible.

Goals 1–3 test the backend's handling of hand-authored extraction observations; the fake provider does not prove that a vision model finds or classifies rows. Goal 2 tests the backend's actual description-code retrieval. Goals 7–8 deliberately give the fake provider incorrect but schema-valid observations.

All OPENAI_API_KEY and PO_BACKEND_* variables are removed inside the test process; Settings uses `_env_file=None`. Dotenv file opens, built-in provider extraction and external HTTP transports are guarded. No `.env` file or customer document is opened. Application configuration and storage path roots are redirected only in the test harness, so repository `data/` and `output/` stay untouched. Production logic is unchanged.

PostgreSQL is initialized on an available loopback port from GOAL_POSTGRES_BIN (or PATH), with an owned cluster and `gate_a_test_backend_goal_*` database. Migrations and pg_trgm run there. The database is dropped and the owned server stopped during fixture teardown. Missing binaries are reported as blocked skips; initialization or migration errors fail setup rather than becoming xfail.
