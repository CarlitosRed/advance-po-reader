# OrderLens live demo continuation

Updated October 2, 2026 after recovery from a computer crash.

## Chat ownership

Carlos requested that the current chat focus on the live demo. When an issue
needs implementation or testing, create a separate development chat with a
specific handoff. Automatic conversation compaction is managed by Codex and
cannot be disabled by the agent; durable notes and saved receipts preserve
the state needed to continue.

The live demo owns the existing `codex/local-website-catalogs` checkout and
website on `http://127.0.0.1:8014/`. Development chats must use separate
checkouts, branches, databases and private output directories. Serialize any
later integration into the live checkout.

## Current evidence

- Existing PostgreSQL was restarted from its preserved cluster; no new
  cluster or migration was needed for recovery.
- The website was restarted with `scripts/start-local-website.ps1 -LiveDemo`.
  Its existing backend key and saved source authorization remained available.
- One previously authorized original PDF was processed once. The provider
  attempt succeeded and the saved run is partial with review required.
- Six rows await review: product, unknown, charge, total and two notes.
  The unknown row may be a continuation; the agent did not join it.
- Automatic retrieval returned no product candidate. A separate read-only
  search within the selected catalog found one record for comparison.
- No products are approved. Human decisions and warning acknowledgement
  must be completed in the website.
- Provider latency was 50.828 seconds, with 3,984 input tokens and 3,860
  output tokens. This is one measured attempt, not an accuracy benchmark.

Exact source hashes, run IDs, raw fields, catalogue records and screenshots
remain in ignored `output/agent-ready/`. Start with `api-first-live-result.json`
and `api-activation-runtime.json`; verify current process ownership before
using any saved process ID. Never automatically repeat this successful run.

## Catalog lookup issue delegated for a fix

The source described a product using a catalog-like code embedded in its
description, while the dedicated item/manufacturer identifier fields were
blank. Existing exact lookup therefore had no eligible identifier. The
description similarity also did not reach the current retrieval threshold.

The dedicated development checkout is:

`C:\Users\carlo\.codex\worktrees\orderlens-catalog-fix\Advance PO Reader`

It starts at the preserved `f145468` handoff. Its development chat may diagnose
and improve bounded candidate retrieval, then verify with synthetic fixtures.
Treat any description token as a retrieval hint with separate provenance;
never rewrite the source identifier or claim the token's role was observed.
Preserve tenant/vendor scope, bounded candidates, ambiguity and human approval.
Keep this demo's saved observations and original suggestions immutable.

## Next human demo step

Continue in the current PDF review tab. Use the catalog search to inspect the
record found for the product row. If it is supported by the source, the human
can propose and approve it with a reviewer name and reason. Review the unknown
and non-product rows, acknowledge document warnings, then finish review when
the website permits it. Review decisions are not automatically evaluation
ground truth, cart changes or orders.

See [API activation evidence](api-activation-verification.md) for configuration,
live-call measurements and the boundaries of what has been verified.
