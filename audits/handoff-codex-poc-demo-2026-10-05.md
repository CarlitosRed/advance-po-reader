# T-017 checkpoint: Codex · poc demo

Date: October 5, 2026. Target: Wednesday, October 7. PR: #12 into `codex/worktree-standards`.
Desk: `C:\Users\carlo\dev\advance-po-reader.worktrees\poc-demo`; branch `codex/poc-demo-kit`.
Committed head at checkpoint: `93483f2ae0f23a5e4e503a2d430f8608dafe1b16` (plan); implementation remains uncommitted.

## Authority

Carlos gave GO for free steps 1, 2, 3 and 5, and skipped separate plan review; Claudio · PR review will review the finished PR once. Carlos separately confirmed local-only use of the 33 POs after the first source triggered the customer-details stop condition. Keep all source details, filenames and text out of Git, PRs, logs and the runbook. Original files and inspection receipts remain ignored and local. No provider call is authorized. Step 4 requires a separate explicit go in this chat, including the source-transfer decision. Stop and ask Carlos before a backend change.

## Progress and evidence

- Own `.venv-backend` created from bundled Python 3.12.14; pinned requirements installed, `pip check` passed. Initial sandbox setup stalled; installation outside the sandbox succeeded.
- Original archive inspected locally under Carlos's authorization: 33 PDFs, 45 pages, all rendered/decoded; 39 pages contain native text. Terms pages, image-only/handwritten and dense-table structures are present. No extraction accuracy is claimed.
- Added script-owned offline entry page, launcher, fixed provider, owned PostgreSQL setup and seed script; fixtures contain exactly 150 invented products across 30 families and three review cases. Backend/migrations/CI/frontend source files remain unchanged.
- `scripts/start-poc-demo.ps1 -PrepareOnly` passed outside the sandbox. Desk-owned PostgreSQL reached `0009_review_answers`; 150 products seeded. Cases have Certain/Probable/Uncertain, Probable/Probable/Uncertain, and three Uncertain rows. All approvals remain pending. Zero external provider calls and $0 spend.
- Sandbox PostgreSQL startup failed with restricted-token error 87; outside-sandbox startup/stop succeeded. Seed guard initially rejected the migration's default synthetic tenant; fixed in the script. No backend change was needed.
- Regular upload landing page requires a default real-catalog pool, and synthetic namespaces cannot join one. The script-owned `/poc-demo` entry uses existing vendor-scoped APIs and opens the unchanged review screen. The regular landing page is not the offline upload entry.
- Script byte compilation and current diff whitespace check passed. No runtime/test result beyond preparation is claimed yet.

## Private locations

- `data/poc-demo/runtime/`: owner marker, desk-owned cluster and database-generation history; never touch another cluster. Installed PostgreSQL binaries are read-only tools.
- `data/poc-demo/generated/`: generated fictional PDF/PNG/JPG fixtures.
- `output/poc-demo/demo-ready.json` and `runtime.json`: current local receipts; no token/key stored.
- `output/poc-demo/corpus-inspection/`: private original inspection evidence. Never publish its files or contents.
- `tmp/`: ignored build/inspection helpers; not deliverables.

## Checkpoint requested by Carlos at 81% context

Steps 1–3 have now been verified: 33 local original uploads/45 pages, 33 fictional structural runs/156 fictional rows, all three tiers and zero original-source provider attempts. Phone QA at 390×844 passed the three answers, explicit approvals, correction persistence, Finish blockers, resolved reload and PDF/PNG/JPG uploads with zero external browser requests/page errors. Goal suite: **54 passed, 2 strict xfailed in 28.48s**, no skips. Idempotency/offline guards and a non-destructive reset passed. A later non-reset check overwrote the private isolation receipt's reset field as false (not requested), not a reset failure. The last added source-enlargement browser assertion and screenshot blur/scroll adjustment are not rerun yet.

Step 5's runbook draft and evidence document exist; polish remains. Carlos requested logical commits/push, current PR evidence and a compact project-notes handoff, then stop. No additional implementation or runtime work is authorized by that checkpoint request.

## Next work after this checkpoint

1. Polish step 5's one-page runbook; rerun the last added source-enlargement/screenshot assertion, then update evidence only for what actually ran.
2. Push the final polish/evidence and hand finished PR #12 to Claudio · PR review once. Do not merge.
3. Keep step 4 blocked until Carlos separately authorizes both a live run and which POs may leave this PC. Only then use his privately set key/token, the normal source-bound path, and the $3 cumulative cap.

If resumed, inspect Git status and this desk's port ownership before any runtime action. Never open `.env*`. Use outside-sandbox `gh` for this repository as global AGENTS.md directs; do not use browser/connector comment fallbacks.
