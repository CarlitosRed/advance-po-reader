# T-017 free demo evidence — October 5, 2026

Owner: Codex · poc demo. Branch: `codex/poc-demo-kit`, based on the PR #7 merge `fe5c1f421c4293d0b993a5e2e4abecc69fba500c`. PR #12 targets `codex/worktree-standards`. Carlos authorized steps 1–3 and 5 and skipped separate plan review; Claudio · PR review reviews the finished PR once. Carlos also explicitly authorized local-only corpus inspection after the customer-details stop condition. No original filenames, source text or customer details belong in this report.

## Reproduction gaps and fixes

| Actual failure or missing step | Resulting kit behavior |
| --- | --- |
| Fresh desk had no backend environment or private PostgreSQL runtime record. Existing docs assume a prepared checkout. | Own `.venv-backend` created with Python 3.12.14 and pinned lock; owned cluster/database created by the POC launcher. No existing service/database used. |
| Initial sandbox environment setup stalled; sandbox PostgreSQL startup failed with restricted-token error 87. | Dependencies installed and native startup verified outside the sandbox. Runbook directs Carlos to an ordinary terminal. |
| Carlos's PowerShell rejected the direct script invocation with `PSSecurityException`; an administrator session also prevents PostgreSQL startup. | Runbook uses `powershell -NoProfile -ExecutionPolicy Bypass` for one process only and explicitly requires normal PowerShell. Launcher rejects an elevated role before environment/database setup. No Windows policy setting changed. |
| Seed script initially rejected the migration's built-in synthetic tenant. | Script accepts only that known baseline when creating the fictional namespace, then rejects foreign catalogs. No migration change. |
| Existing all-products setup excludes synthetic namespaces; the ordinary upload landing page requires a default pool. | Script-owned `/poc-demo` entry calls existing vendor-scoped upload/run APIs and opens the unchanged review screen. No fake real-catalog pool. |
| Existing manual mock handles one generated fixture; the built-in demo does not prove a 33-document structural run. | Hash-bound fixed provider, three hand-authored cases, nine generated PDF/photo fixtures and private structural-surrogate registry. Unknown bytes fail instead of receiving canned output. |
| Historical all-products guide names migration `0008`; current backend expects `0009_review_answers`. | Fresh owned database upgraded to the actual head using existing migrations and explicit connection injection, without reading dotenv. |
| First phone test observed `state.run` before its asynchronous summary finished reloading. | Fixed the verification script's wait and isolated QA in fresh fictional runs; no app change. |

## Executed checks

- Fresh desk: isolated environment created, pinned dependencies installed, `pip check` passed.
- Continuation check: `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-poc-demo.ps1 -PrepareOnly` passed in normal PowerShell outside the sandbox: 150 fictional products and three pending cases. The documented seed command with the same process-only bypass passed with stable catalog IDs. Launcher syntax passed; the administrator-refusal branch was checked with a simulated elevated role, not an actual elevated PostgreSQL launch.
- The full bypass start invocation subsequently refused occupied port 8020 with `WinError 10048`. Readback found another running POC process and HTTP 200 from its fictional `/poc-demo` entry. That process was left running. This is an occupied-port refusal, not a fresh full-launch pass; the earlier full launcher startup and current bypass setup verification passed separately.
- `scripts/start-poc-demo.ps1 -PrepareOnly`: passed; current migration head, 150 fixture products, three pending runs, all three tiers. Startup and subsequent seeding were verified repeatedly.
- `scripts/seed-poc-demo.py`: idempotency checked through the seed function twice; same IDs and product data, 150 imported fixtures. Human-created review products remain separate and are preserved.
- `scripts/poc-demo-corpus.py --archive PRIVATE_PATH --profiles PRIVATE_PATH --authorized-local-only`: 33 original uploads validated, 45 original pages decoded; 33 fictional structural runs, 45 surrogate pages and 156 fictional rows; zero failures. Original provider-attempt count independently queried as zero. Fixed cases reproduce representative page/row shapes, including terms pages, dense tables and handwriting ambiguity; they are not source-bound extraction labels or independent completeness checks.
- `scripts/verify-poc-demo.py --fresh-proof`: seed IDs stable; dotenv reads, built-in OpenAI, external HTTP and live run creation refused; modified fictional PDF receives no fixed output; fresh database starts empty and previous source/run/review counts remain preserved.
- Checkpoint detail: the successful reset proof preceded the latest non-reset verification. That later run checked unknown-upload rejection through the real API and overwrote `isolation-qa.json` with its reset field `false` because `--fresh-proof` was not requested; it did not report a reset failure. Preserve this distinction on resume.
- `scripts/verify-poc-demo.cjs http://127.0.0.1:8020 PATH_TO_BROWSER`: rerun on the real server using installed Edge at 390×844. Passed all three fictional cases, all tiers/answers, source enlargement, embedded description-code preservation without adding an observed identifier, explicit approval, literal correction/reapproval, persistence, Finish blockers/resolution and PDF/PNG/JPG uploads. Zero page errors and external browser requests. All decisions attributed **Synthetic QA (Codex simulation)**. Screenshot capture waits for the saved-decision toast to clear and scroll to settle; final summary visually checked unobstructed.
- Existing suite: `python -m pytest -m goal --basetemp=tmp/poc-goal-checks -q --tb=short --goal-scorecard=output/poc-demo/goal-scorecard.md`: **54 passed, 2 strict xfailed in 28.48s; no skips or failures**, including the existing real-review-controls browser check on a separate test-owned API/cluster.
- Private receipts/screenshots live only under ignored `output/poc-demo/`; original snapshots and structural profiles under ignored `data/poc-demo/`. Original content is not logged. Desk checkpoint is `audits/handoff-codex-poc-demo-2026-10-05.md`.

Continuation status: steps 1–3 retain their earlier measured evidence; the goal suite and original corpus were not rerun for this docs/launcher polish. Step 5's compact runbook is finished with normal-PowerShell start/reset/verification/seed commands and the three checked case walkthroughs. The formerly unverified source-enlargement and screenshot changes have now passed. Final PR review is requested once from Claudio · PR review after publication; no merge is authorized.

## Evidence limits and cost

Fake-provider success proves handling of declared fictional observations. The goal suite's strict xfails remain source grounding and independent completeness. No OCR/model accuracy, independent gold labels, real database integration, live OpenAI, production, hosting or cart/order behavior is verified.

**Cost: $0, zero external provider calls.** Step 4 remains deferred. Carlos must separately authorize a live run and source transfer in this chat; then the task's three-first/ten-maximum serial sequence and $3 cumulative cap apply. Free-mode authorization does not authorize that transfer.
