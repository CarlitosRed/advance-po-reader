# Worktree operating standard

Updated October 2, 2026. This document defines how OrderLens work is assigned, integrated, backed up, and recovered. The private, ignored workstation registry holds machine-specific paths, owners, service identifiers, and recovery references. Do not copy that registry into Git.

## Assignment and ownership

- Assign one human-visible chat as the writer for each checkout. A branch name, clean status, sidebar section, archived chat, or app attachment alone does not establish ownership.
- Mark ownership `Unknown` when the app chat inventory and the checkout's actual recent activity disagree. Do not send messages to old chats or reactivate workers just to resolve an inventory gap.
- Keep one integration owner. Feature work belongs in an assigned worktree and returns as a reviewed commit or patch. Only the integration owner writes the shared integration checkout.
- Record task, checkout path, branch and full starting SHA, owner chat ID/title, allowed paths, excluded/private paths, isolated environment/database/output location, and recovery point before work starts.
- Never let concurrent writers share a checkout. Different worktrees still need separate writable databases, uploads, review events, and outputs.

## Worktree lifecycle

- Inventory Git worktrees, app attachments/chats, filesystem directories, and live services separately. These lists answer different questions.
- Treat unregistered directories as `Unregistered`; inspect contents and live dependencies before recovery or cleanup. A missing `.git` file is not evidence that a directory is disposable.
- Mark lifecycle as `Active`, `Idle`, `Detached`, `Unregistered`, or `Unknown`, based on evidence. Detached worktrees require explicit ownership and recovery review before reuse.
- Before archive/removal, verify ownership, ignored assets, nested repositories, initialized submodules, runtime dependencies, and an independent restore path. App-managed archives preserve Git state but not ignored files.
- Keep private data local: PDFs, raw text, source labels, catalog databases, review corrections, credentials, model weights, run outputs, and runtime/database clusters. Never share writable evidence directories between worktrees.

## GitHub backup

- A configured remote or cached remote-tracking ref is not backup evidence. Query the actual remote and record the exact advertised refs and full SHAs.
- Audit the complete history being published as well as the final tree. Review text, binary assets, commit messages, deleted paths, renamed paths, secrets, customer identifiers, local runtime values, and data files. A pre-push hook is only a secondary check.
- Publish a source/documentation snapshot only after the audit. If the local history contains operational evidence, preserve it locally and construct a sanitized source snapshot based on a verified remote baseline. Never push all refs, mirror, force-push, or rewrite existing remote history for this purpose.
- After push, read back the exact branch ref and commit SHA from the remote. Report the paths and history actually covered. Keep confidential runtime/evidence backup separate, local, encrypted as appropriate, and independently recoverable.

## Evidence and claims

- Keep implementation behavior, documentation, tests, runtime readiness, provider activity, evaluation accuracy, and publication as separate evidence states.
- Preserve exact hashes and immutable provider attempts in private receipts. Do not put request/run/source identifiers or raw observations into public documentation.
- Synthetic tests prove the tested software behavior only. They do not establish extraction accuracy across the corpus. Evaluation must cover the complete supplied corpus plus varied incoming handwritten notes, scans, photos, structured PDFs, and order sizes from one to 100.
- Keep terminal failures terminal. Workspace organization does not authorize retries, new provider calls, review decisions, training, deployment, cart writes, or orders.

## Integration and recovery checklist

Before writing: read project goal and local logic rules; verify the assigned checkout, owner, full SHA, branch, and clean/expected status; confirm allowed paths and test isolation.

Before integration: review the complete diff and relevant commit history; check private-data boundaries; verify synthetic checks without touching live services; record resulting full SHA and exact changed paths.

Before archival or recovery: capture Git status and branch/SHA; inventory ignored data and running processes; create and verify a separate backup of any required ignored data; confirm the restore path; then use managed worktree lifecycle tools.
