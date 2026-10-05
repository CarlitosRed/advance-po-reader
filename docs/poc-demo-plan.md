# T-017: local proof-of-concept demo plan

Owner: **Codex · poc demo:**
Decision: Carlos, October 5, 2026. Target: Wednesday, October 7, 2026.
Desk: `C:\Users\carlo\dev\advance-po-reader.worktrees\poc-demo`
Branch: `codex/poc-demo-kit`
Starting ref: `origin/codex/worktree-standards` at `fe5c1f421c4293d0b993a5e2e4abecc69fba500c` (merged PR #7).
PR base: `codex/worktree-standards`; T-017 assigns the old review rule and Claudio · PR review as reviewer.

## Plan

Carlos gave GO for steps 1, 2, 3 and 5 on October 5 and skipped separate plan review: Claudio · PR review reviews the finished PR once. This file retains the original plan and plan-phase evidence below; executed results are in [poc-demo-verification.md](poc-demo-verification.md). Step 4 still requires a separate explicit live-run go and source-transfer authorization from Carlos in this chat.

Milestone 1 demonstrates the existing local application against a synthetic catalog, with a fake provider and explicit human review. There is no real product database. Keep the existing live-demo runtime, other desks, main, customer data and private catalogs untouched. Do not deploy, host, add logins, make paid calls or open any `.env*` file, including examples.

### 1. Fresh-desk proof, no spend

- Create this desk's isolated `.venv-backend` using the pinned backend requirements. Use installed PostgreSQL binaries with a desk-owned cluster/database and an unused loopback port. Keep uploads, corpus copies, receipts and logs in this desk's ignored `data/` and `output/` paths.
- Reproduce the documented setup with explicit offline configuration. Build a script-level app entry around the existing `create_app` injection point with `Settings(_env_file=None)`, no provider key, live processing disabled, a local development token held only in the process, and a fixed-JSON fake provider. Remove inherited provider/configuration overrides and guard external provider transports and dotenv access, reusing the goal harness approach.
- Record each actual failed or missing setup step, its command/result, and its docs/scripts fix. The read-only findings below are setup assumptions to verify, not executed failures.
- Keep `scripts/start-local-website.ps1`'s existing live behavior intact unless a narrowly scoped startup fix is needed. Prefer a dedicated `scripts/start-poc-demo.ps1` and `scripts/poc-demo.py` for one-command offline startup. Check process and port ownership before starting/stopping anything.
- If startup needs a backend logic change, stop and ask Carlos with the exact blocker. Do not implement even a one-line backend fix without that direction.

### 2. Synthetic catalog

- Inspect the authorized 33 test POs locally only after the coding go. Stop if a PO appears to contain real customer details. Keep document bytes, filenames, hashes, raw text and source-specific coverage receipts out of Git.
- Build approximately 150 clearly fictional products covering the visible product families and matching situations in those POs, plus near-identical names, similar identifiers and codes embedded in descriptions. Do not import a real catalog or turn customer/source records into repository fixtures.
- Commit the synthetic catalog and fixed JSON under `fixtures/poc-demo/`, with invented identifiers, descriptions and deterministic case labels. Keep the private mapping from PO structure to fictional cases in ignored output.
- Add `scripts/seed-poc-demo.py` as the single seed command using existing catalog APIs/services. Scope it to the owned synthetic tenant/vendor and make repeated seeding idempotent; verify product count and stable IDs. Never seed another database or overwrite review evidence.
- Synthetic namespaces cannot join the existing all-products pool. Use the supported explicit vendor-scoped path for this demo; do not relabel a synthetic namespace as real or alter backend pool rules. Verify that the existing website can select and review that namespace; escalate a backend blocker if it cannot.

### 3. Free dry run and phone review

- Decode and inventory all 33 authorized POs locally, capturing actual page/format results and failures privately. Process their structural cases with the injected fake provider and fixed JSON using existing test patterns. Separate original-file decode/preview evidence from generated fictional extraction/review cases; fixture output is never represented as measured extraction of an original PO.
- Exercise PDF and photo upload, persistence, candidate retrieval and the actual review routes. Demonstrate Certain, Probable and Uncertain rows, similar-product distractors and no-match outcomes. Every tier remains pending until an explicit human action.
- Select three representative POs for the runbook after inventory: a clear identifier case, a description/similar-product case, and an ambiguous/no-match case. Use opaque local labels in tracked docs and keep filenames/coverage mappings private. Any unavailable structural coverage remains a named gap.
- Check the actual review screen at phone width (about 390 px): source inspection, candidate selection, explicit approval, all three Uncertain answers, raw quantity/unit correction, persistence after reload, and Finish blockers/resolution. Synthetic QA events must be attributed as simulation.
- Reuse the existing offline goal suite and browser controls for affected behavior. Keep the known source-grounding and independent-completeness strict xfails visible; do not repair backend logic or claim model accuracy in this task.

### 5. One-page runbook

Create `docs/poc-demo-runbook.md` with prerequisites, the tested one start command, the three selected local demo cases, upload/review clicks, plain-language tier meanings, known limits, stop/restart instructions and a reset command. Reset must confirm the owned demo database/cluster and preserve earlier receipts/review evidence with a checkpoint or a fresh demo database; it must never target the existing website or another desk.

The free runbook must work without a key or dotenv file. Clearly label fake extraction and the synthetic catalog. Add the short completion note to `docs/agent-handoff.md` after implementation, distinguishing implemented behavior from documented future live work.

### Step 4: separate live authorization gate

No live OpenAI call is authorized by plan approval or the coding go. Only after Carlos explicitly says go for step 4 in this chat: use his privately configured desk credentials through the normal source-bound authorization path, process 3 POs first and then at most 10 total, serially, record actual cost per attempt and stop at a $3 total. Verify current official API/model/pricing details then. Never ask for, read or print a key, password or token. Stop for missing credentials, apparent customer details, backend changes, or a projected spend above the cap. Do not blindly retry unknown outcomes.

### Intended file scope

- Add: `scripts/start-poc-demo.ps1`, `scripts/poc-demo.py`, `scripts/seed-poc-demo.py`, `fixtures/poc-demo/` fictional catalog/fixed JSON and `docs/poc-demo-runbook.md`.
- Update only where reproduction proves a gap: startup scripts and `docs/local-website.md`, `docs/local-agent-demo.md`, `docs/all-products-catalog-pool.md`; add the completion note to `docs/agent-handoff.md`.
- Write `audits/handoff-codex-poc-demo-2026-10-05.md` when context reaches about 60%, with branch/head, progress, commands/results, private receipt locations, blockers and authorization gates. Do not store source details or credentials in it.
- Leave `backend/`, migrations, CI workflows, `.claude/` and main alone. Add only focused script/fixture smoke checks if needed to verify isolation, seeding and startup; avoid backend refactoring and duplicate tests.

## Evidence

Plan preparation only:

- Read T-017, `C:\Users\carlo\.codex\AGENTS.md`, the dev workflow, repository instructions/project goal, worktree standards, handoff/logic notes and all six task-card references.
- Fetched the requested remote branch and created a new desk/branch from the PR #7 merge at the full starting SHA above. Main was clean and remains unchanged; other desks were inventoried without edits.
- Read existing startup scripts and offline harness entry points. The regular launcher relies on a pre-existing environment and dotenv configuration; the PostgreSQL restart script requires a private runtime record and fixes port 55433. The existing manual mock accepts one generated fixture only, so it does not prove a 33-PO dry run. Existing goal tests already provide fixed JSON, dotenv/transport guards and owned PostgreSQL.
- The all-products guide excludes synthetic namespaces and names an older migration head; verify the actual current head during fresh setup without changing migrations. `ROLES.md` is absent from this starting branch; the task's explicit old-rule base/reviewer instruction governs this PR.
- No environment was created, no database/service was started or migrated, no source PO was opened, and no runtime/test pass is claimed. Before publication, check that the diff contains only this plan, run `git diff --check`, audit the single new commit, then read back the remote branch SHA and draft PR base/head.

After the coding go, replace these planning statements in the PR evidence with actual commands, counts, test outcomes, phone-browser results, 33-document coverage and reproducibility gaps. Keep private evidence under ignored output; report failures and skips explicitly. Fake-provider success proves software handling of fixed observations, not OpenAI readiness or extraction accuracy. T-017's full live exit criterion remains pending until separately authorized and verified.

## Cost

Plan phase: **$0; zero paid provider calls**. Steps 1–3 and 5 stay free of paid calls. Step 4 is deferred and has a $3 cumulative cap after Carlos's explicit live-run go. No live-run result or cost measurement is claimed.
