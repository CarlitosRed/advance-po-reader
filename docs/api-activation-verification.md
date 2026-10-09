# Local API activation evidence

Updated October 2, 2026 in the sole continuation worktree,
`codex/local-website-catalogs`, after implementation checkpoint `1d40dc9`
and documentation handoff `f145468`.

Carlos authorized secure server configuration and the first local PDF demo.
He selected WernerCo and an original document from the preserved library.
The exact private document/run references and receipts remain under ignored
`output/agent-ready/`; customer source labels are not reproduced here.

## Configured and checked

- Created the OpenAI API project **OrderLens** in the user's organization.
- The secure Platform picker confirmed that project and a seven-day key
  lifetime. The native destination form returned an immediate decline twice;
  Carlos then explicitly confirmed the existing ignored `.env.backend` path
  in chat. That direct user confirmation was used as the destination approval.
- Created the key once through the encrypted Platform connector and saved
  `OPENAI_API_KEY` with the supplied local helper. No plaintext key appeared
  in chat or command output. The key is backend-only and expires after the
  selected lifetime; no renewal or additional key is scheduled.
- Verified the current 8014 process and its parent executable in this
  worktree before stopping it. Restarted only the website with
  `scripts/start-local-website.ps1 -LiveDemo` in a hidden local process.
  At that time this launcher had no spend cap and no private-token check (added later; see
  [local-agent-demo.md](local-agent-demo.md)). A guided, capped alternative is `start-poc-demo.ps1 -Live`.
- Read-only `backend.preflight --require-live` passed. The running server
  reports database ready, three real catalogs, 2,720 products, 33 library PDFs,
  key present, live processing enabled, and no configuration blockers.
- Native Codex `po_reader` calls now work: status, catalog/library listing,
  preparation, authorized processing and reading the saved extraction/review
  summary were exercised.
- One authenticated `GET /v1/models/gpt-6.1-sol` returned HTTP 200 and the
  expected model ID. This verifies credential/model metadata access. It makes
  no generation request, sends no customer PDF and does not establish quota,
  extraction quality, latency or realized generation cost.
- Before the crash, only the verified website process was restarted. After
  the crash no prior service listener remained. The existing PostgreSQL
  cluster on 55433 was recovered with `start-existing-local-postgres.ps1`,
  then only the 8014 website was launched in live mode. Ports 8010 and 8012
  remain stopped. Current owners are in the private recovery receipt.

The configured model's image input and structured-output capabilities and
the Responses Base64 PDF format were rechecked in the current official
[model page](https://developers.openai.com/api/docs/models/gpt-6.1-sol) and
[file-input guide](https://developers.openai.com/api/docs/guides/file-inputs).
The adapter uses `store=false`. This is not a Zero Data Retention guarantee:
standard abuse-monitoring retention and the documented file-input exceptions
still require consideration under the relevant customer policy. See
[OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data).

## Recovered live extraction

The human saved the applicable authorization/policy reference, name, purpose
and source permission in the website. Recovery verified that the authorization
was bound to the unchanged source hash and the selected catalog. The run had
zero provider attempts before resumption. The agent processed that exact
authorized run once; its one real provider attempt succeeded.

Measured result:

- Configured and returned model: `gpt-6.1-sol`.
- Prompt version: `po-literal-evidence-v1`; extraction schema: `1.1`.
- Provider latency: **50,828 ms**.
- Usage: **3,984 input**, **3,860 output**, **7,844 total tokens**; zero
  cached input tokens and 203 reasoning tokens are recorded.
- One product row, one unknown row, one charge row, one total and two notes
  were saved. Literal quantity, unit and four-decimal price strings remain
  independent of parsed values.
- Run state is `partial`, outcome `review_required`, review `not_started`.
  The ambiguous row may be a separate product or a continuation; it was not
  silently joined. Blank charge data and document warnings remain visible.
- Original automatic suggestions contain no candidate. A separate scoped,
  read-only catalog search found one record for human comparison. The source
  code appears in the description while dedicated identifier fields are
  absent; description similarity did not reach the retrieval threshold.
- Approved products: **zero**. Pending rows: **six**. Source observations
  and original suggestions remain unchanged.

At the currently published model rates of $2 per million input tokens and
$10 per million output tokens, those token counts imply an estimated
**$0.046568** for this request. This is a rate-based estimate; the account's
actual invoice has not been checked. Rates were verified on the official
[model page](https://developers.openai.com/api/docs/models/gpt-6.1-sol).

The live path now demonstrates an authorized PDF reaching OpenAI, a saved
structured observation, a conservative no-match outcome, and read-only
comparison with the selected real catalog. Extraction fidelity, candidate
Recall@K, match precision and review burden need independent reviewed
evaluation. One successful request does not establish those metrics.

## Remaining human review

The human must compare the product record with the source, propose/approve
any supported resolution, review the unknown and non-product rows, and
explicitly acknowledge document warnings before finishing review. Agents
cannot make those decisions. Each future external source still requires
its own authorization; unknown processing outcomes require status inspection.

The previous 245 backend, 135 Gate A and 20 agent checks remain historical
offline evidence. The full suites were not rerun for API activation/recovery.
The separate catalog development chat is assigned synthetic verification
for its retrieval change; see [demo continuation](live-demo-continuation.md).

## Changes and private evidence

The upload page's two stale API-pending messages were replaced with accurate
source-authorization guidance. This changes displayed text only; provider,
catalog, authorization and human-review behavior are unchanged. Node syntax
checking passed for the edited JavaScript.

`PROJECT_GOAL.md`, `AGENTS.md` and the local logic rules now identify API
activation as the current directly authorized scope while retaining the
previous checkpoints. The API activation handoff and agent handoff link here.

Ignored evidence includes `api-model-access.json`, `api-first-live-result.json`,
`api-activation-runtime.json`, activation/recovery process logs and the live
review screenshot. The first live receipt was created without overwriting any
prior receipt and includes request/response IDs, prompt/schema versions,
actual usage/latency, raw observations, original suggestions, manual lookup
and pending review summary. Credentials, original PDFs, catalog data and
human audit records remain private.
