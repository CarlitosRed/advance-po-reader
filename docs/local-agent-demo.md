# Local agent connection and API activation

> **Superseded checkpoint (banner added 2026-10-08).** This guide describes the state before API activation: live provider and credential work deferred, native invocation from a refreshed Codex chat unverified, real OpenAI extraction unverified. Later records show the server key configured, native `po_reader` calls working, and one authorized PDF processed once; extraction accuracy is still unmeasured. Current scope and the Implemented versus Intended list are in [PROJECT_GOAL.md](../PROJECT_GOAL.md) and [AGENTS.md](../AGENTS.md); later evidence is in [api-activation-verification.md](api-activation-verification.md) and [live-demo-continuation.md](live-demo-continuation.md). The text below is kept unchanged as historical evidence.

Implemented October 2, 2026 in `codex/local-website-catalogs`, after website
checkpoint `d01b2ca`. The user chose both the document workflow and scoped Codex
tools. Work continues in the same chat and isolated worktree. Live provider
calls and credential work remain deferred; all provider verification here uses
injected mocks and generated fictional bytes.

## What is implemented

The local FastAPI website on port 8014 owns the files, database, provider
adapter, bounded suggestions and append-only human review. The new
`reader_agent` package exposes an official Python MCP SDK STDIO server that
calls only that loopback API. It has no model loop, remote MCP listener,
provider credential field, arbitrary URL/file-path tool, or human-review write
tool. Catalog/document text is untrusted data, never instructions.

The agent runtime has its own `.venv-agent` and `requirements.agent.lock.txt`;
the backend dependencies were not changed. The MCP entry uses absolute paths
and loads only the loopback connection settings from the ignored `.env.backend`
or environment. Its configuration contains no key or local API token. This is
local development access; it is not hosted customer identity/authentication.

| Tool | Behavior |
| --- | --- |
| `reader_status` | Read database/library/provider readiness, including the missing-key blocker. |
| `reader_list_catalogs` | List workspace/catalog IDs for explicit user selection. |
| `reader_list_test_documents` | List the original private email PDF library without extracting it. |
| `reader_search_catalog` | Read at most 50 products from an explicit workspace/catalog. |
| `reader_get_product` | Read one scoped product's original catalog fields and details. |
| `reader_get_run` | Read a scoped run, readiness blockers and its website URL. |
| `reader_get_extraction` | Read literal observations/parses/attempts and bounded suggestions. These are unreviewed predictions. |
| `reader_get_review_summary` | Read the same saved human decisions and blockers used by the website. |
| `reader_prepare_test_document` | Store a confirmed library PDF in an explicitly selected real catalog; create a run without authorizing or processing it. |
| `reader_start_sample_workflow` | Process only the exact generated fixture in the synthetic catalog; leave every human decision pending. |
| `reader_process_authorized_run` | Process an existing OpenAI run once, only after server configuration and hash-bound human authorization. |

Every scoped tool requires both `tenant_id` and `vendor_id`. Preparation tools
require a request UUID: reuse it only to recover an interrupted preparation;
use a new UUID for deliberate new work. Existing processing attempts and
unknown outcomes block a processing request. The bridge never retries a
transport failure or grants source authorization. It cannot correct values,
propose/approve products, resolve a review, or write to a cart/order.

The website offers **Authorize for agent** and **Authorize and extract now**.
Authorization records the unchanged source SHA-256, a named authorizer, policy
reference and reason. The first action saves a new authorized run without a
provider attempt. The site follows its status when an agent starts it. All
polling requests are reads. A prepared run can be cancelled before processing;
an in-flight cancellation retains any provider attempt/receipt and does not
guarantee cancellation at the external provider.

## Current machine and connection

The `po_reader` entry was registered with `codex mcp add`, with a 20-second
startup timeout and 240-second tool timeout. Other MCP entries were preserved.
The CLI reads it back as enabled STDIO with no environment credentials.
The actual STDIO handshake, tool inventory and API calls were exercised.

This running chat's tool inventory was established before registration and
does not yet include the new tools. Reload Codex's MCP configuration by
restarting the app when convenient, then confirm `po_reader` is enabled under
Settings > MCP servers. The workspace and this chat remain saved. See the
current official [Codex MCP guide](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
and [Python SDK host connection guide](https://py.sdk.modelcontextprotocol.io/get-started/real-host/).
Native invocation from a refreshed Codex chat is still unverified; protocol
invocation from the installed SDK is verified.

The website uses `gate_a_backend_website`, now at `0005_review_sequence`, and
the preserved PostgreSQL cluster on `127.0.0.1:55433`. The original Gate A and
backend checkpoints remain ready on ports 8010 and 8012 respectively.

If PostgreSQL is stopped, this machine has an ignored private runtime-path
record at `data/agent-runtime/local-postgres.json`. The restart script validates
the existing cluster and binds it to loopback; it does not initialize a
database, install a service, migrate, delete files, or change execution policy:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\carlo\.codex\worktrees\local-website-catalogs\Advance PO Reader\scripts\start-existing-local-postgres.ps1"
```

The `ExecutionPolicy` argument applies to that PowerShell process and leaves
the saved policy unchanged, as [Microsoft documents](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_powershell_exe?view=powershell-5.1#-executionpolicy-executionpolicy).
The user ran it successfully after automatic approval review blocked the
agent's restart command. Readiness was subsequently verified over HTTP.

## Activate later with the server API key

No provider credential was created, imported or tested in this phase. When the
user authorizes key setup, configure `OPENAI_API_KEY` privately on the backend,
using the existing ignored `.env.backend` or server process environment. Do
not put it in chat, JavaScript, an MCP argument, or Git. Merely storing a key
does not enable processing.

From this worktree, stop only its existing website terminal/process, then run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local-website.ps1 -LiveDemo
```

`-LiveDemo` checks for a nonblank server key and sets the live switch only for
that launch. Startup sends no document. Reload `http://127.0.0.1:8014/` after
the restart so its in-memory browser session is refreshed. Check readiness:

```powershell
& .\.venv-backend\Scripts\python.exe -m backend.preflight --require-live
```

Preflight reports booleans and local readiness; it makes no provider request
and does not validate the credential, quota, model access or response quality.
Verify current model/API/data-control requirements at actual activation.
The default model remains configurable and was checked against official docs
on October 2; that is documentation evidence, not live account access.

Select the catalog explicitly, choose one original PDF, and record the
applicable source/customer authorization in the website. Then extract there,
or give the agent the workspace/catalog/run IDs displayed in **Continue with
your agent** and ask it to process that authorized run. Review every candidate
and raw quantity against the source before finishing. A cancelled/failed run
is preserved; deliberate reprocessing creates a fresh run. Unknown outcomes
require investigation rather than blind retry.

First verify one authorized source end to end. The wider 33-PDF evaluation,
independent gold labels, extraction accuracy, realized API cost and model
latency remain future live work. Training, cart/order integration, hosted AWS,
Apple and Qwen work remain excluded.

## Reproduce verification

```powershell
& .\.venv-agent\Scripts\python.exe -m pytest -c pytest.agent.ini -q
& .\.venv-agent\Scripts\python.exe scripts\verify-agent-connection.py
```

Add `--run-sample` to the second command only when deliberately creating a
fictional workflow. It verifies recovery with the same request UUID and leaves
all rows pending. Reports stay under ignored `output/agent-ready/`.
The complete backend/Gate A suites remain in `scripts/test-backend.ps1`.
The optional `tests/manual/mock_live_website.py` uses a dedicated fictional
test database and port 8016, a fake key and injected transport, and exposes no
customer library. It accepts only the exact generated PDF. Its observed
latency/usage are simulated, not performance measurements.

## Executed evidence for this phase

- 245 backend tests passed on dedicated actual PostgreSQL databases; 135
  preserved Gate A tests passed; 20 agent protocol/permission tests passed.
  These runs had no skipped tests.
- The actual STDIO server listed 11 tools, searched the three real catalogs
  (2,380 / 160 / 180 products), and listed the 33 original PDFs.
- The fictional agent workflow produced four source rows, one synthetic
  attempt and zero approvals. Reusing its request UUID returned the same run
  without a second attempt.
- Browser QA approved fictional lines, changed a quantity from `2` to
  `002.50`, confirmed that approval reopened, reapproved, acknowledged the
  charge/total, finished review and reloaded successfully. The STDIO tool read
  back the same two approvals, corrected literal and original literal. QA
  attribution explicitly says **Synthetic QA (Codex simulation)**; it is not a
  customer decision or a gold/training label.
- The previously saved fictional review was also read back with its original
  eight-event history, two approvals and separate raw/corrected quantity.
- On the isolated mock website, browser authorization created a fresh run
  without processing. An MCP tool started it; the page followed saved
  `processing` state and automatically opened the four-row review when the
  injected OpenAI response completed. Immediate website processing and
  cancellation were also exercised. No external provider request occurred.
- All 33 corpus hashes were checked against the preserved private manifest;
  the owned website database still has three real catalogs, 2,720 products,
  and zero non-synthetic provider attempts. The post-migration integrity
  snapshot is a continuation baseline, not a pre-migration byte comparison.

The additive review migration preserves old rows with a NULL sequence and
their established timestamp/UUID order. New API events receive an increasing
sequence under the existing per-run lock, with a scoped uniqueness constraint.
Timestamps and old audit values are never rewritten. A regression test moves
the clock backward and confirms correction order remains correct.

Live credential validity, native tools in a refreshed Codex chat and real
OpenAI extraction are not yet verified. The code and local protocol are ready
for that activation step.
