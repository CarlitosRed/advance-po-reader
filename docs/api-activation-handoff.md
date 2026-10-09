# New chat handoff: API activation and live demo

Continuation update, October 2, 2026: secure API configuration, native
`po_reader` connectivity, crash recovery and one human-authorized live PDF
extraction are verified. The saved result requires human review. Separate
development chats handle fixes while the current chat retains the live demo.
See [the demo continuation](live-demo-continuation.md) and
[API activation evidence](api-activation-verification.md). The original
transfer baseline below is preserved.

Prepared October 2, 2026 at Carlos's direct request to continue in a fresh
project chat. The previous chat stops source changes after committing this
handoff. The new chat is the sole continuation writer in the existing
`codex/local-website-catalogs` worktree; do not start competing writers.

## Worktree and starting evidence

Use this existing checkout for all project commands and edits:

`C:\Users\carlo\.codex\worktrees\local-website-catalogs\Advance PO Reader`

The new project chat may initially open the primary project folder. Set an
explicit working directory to the checkout above rather than switching,
resetting, or copying the primary checkout. Keep the original project and
`ffd4` checkpoint untouched. The verified implementation checkpoint is
`1d40dc9338b72962604aec35538452fc0dceca59`; the subsequent handoff commit changes
documentation only. Verify current Git status and ownership before edits.

Read these files from this worktree before continuing:

1. `PROJECT_GOAL.md` and `AGENTS.md`.
2. `docs/local-logic-rules-2026-10-02.md`.
3. `docs/agent-handoff.md` and `docs/local-agent-demo.md`.
4. The ignored `output/agent-ready/runtime.json` and
   `output/agent-ready/final-verification.json` for runtime hints; stored PIDs
   are historical hints and require a fresh ownership check.

The current direct request for a fresh continuation chat supersedes the old
handoff's instruction to remain in the previous chat. Its privacy, source
authorization, tenant/catalog scope, audit, and human-review rules still apply.

## Verified implementation and limits

- Website: `http://127.0.0.1:8014/`; owned database
  `gate_a_backend_website`, migration `0005_review_sequence`.
- Preserved PostgreSQL cluster: `127.0.0.1:55433`. Carlos started it successfully
  from his PowerShell terminal; recheck current readiness.
- One local test workspace with three manually selected real catalogs:
  WernerCo 2,380 products, United Kingdom 160, Australia 180. Never infer
  WernerCo's country or assign a document's catalog automatically.
- Confirmed original email batch: 33 local PDFs, 45 pages. All hashes were
  checked against the preserved private manifest; no real extraction was run.
- Eleven scoped STDIO MCP tools, shared review summary, source-specific
  authorization, one-attempt processing, read-only browser polling,
  cancellation, literal corrections, human approval and audit are implemented.
- 245 backend, 135 Gate A and 20 agent checks passed. Actual STDIO calls and
  browser workflows passed using generated fixtures and injected provider
  responses. These are local/offline checks, not model-accuracy measurements.
- `po_reader` is registered with absolute executable/script paths and no
  credentials in its MCP configuration. Native invocation after a Codex
  configuration reload remains unverified. Existing provider settings have no
  key and live processing is disabled. Main-workspace non-synthetic attempts
  were zero. The temporary mock website on port 8016 was stopped.

## First work in the new chat

Inspect the saved implementation and current local readiness, then continue
the API activation guide. Verify whether native `po_reader` tools are now
available; use a read-only status/list call first. Keep the agent bridge's
connection pointed at the existing website and isolated agent environment.

For credential setup, ask only for the missing choice or secure setup step.
Do not request a plaintext API key in chat, expose an existing key, or copy it
into browser code, MCP arguments, logs, Git, or a handoff. Use the relevant
credential and official-documentation skills when activation begins. Carlos
has not yet supplied a key or selected and authorized a particular customer
document for external processing. Creating this chat grants neither that
source permission nor authorization for automatic API spending.

After the chosen server credential is configured privately, follow the guide
for `start-local-website.ps1 -LiveDemo` and read-only
`python -m backend.preflight --require-live`. Activation alone sends no file.
`-LiveDemo` now starts the server through `scripts/serve_backend.py`: with live on it refuses the shared default API token and applies the POC spend cap (5 live runs unless `PO_POC_MAX_LIVE_RUNS` is set, plus a dollar cap when `PO_POC_INPUT_USD_PER_MTOK`/`PO_POC_OUTPUT_USD_PER_MTOK` are set; details in [poc-demo-runbook.md](poc-demo-runbook.md) step 5). It also refuses non-OpenAI runs while live is on. `python -m backend` refuses to start when live processing is enabled (it prints a refusal and exits with code 2); use `-LiveDemo` or `start-poc-demo.ps1 -Live`. Accepted limit: a server started by hand with uvicorn on `create_app` is still unguarded (no cap and no token check), so never start live mode that way. For the guided demo with a visible counter use `start-poc-demo.ps1 -Live`. Records written before this fix describe a launcher with no cap.
First confirm one manually selected catalog and one source with the required
hash-bound authorization. Then perform one deliberate live run, preserve its
receipt/usage/outcome, and keep corrections and product approvals human.
Investigate unknown outcomes rather than retrying automatically.

Keep supplied PDFs, private catalogs, credentials, source labels, run outputs
and review records in their existing ignored directories. Do not migrate to
AWS, publish private data, train, add cart/order writes, or implement Apple or
Qwen in this activation task. Report native connectivity, provider readiness,
live extraction, human review and measured quality as separate evidence.
