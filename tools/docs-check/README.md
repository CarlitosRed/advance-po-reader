# Offline documentation checker (V2-14)

Status: plan only. The checker and its tests have not been implemented or run.
This new directory is the entire proposed change. The pull request stays draft.

The checker will catch broken source links, stale line-number labels, mixed
commit pins, invalid Mermaid diagrams, possible private information, and line
ending changes before an independent reviewer spends time on them. It will not
decide whether a sentence is supported by the linked code.

## Plan

Add `check_docs.py`, `test_check_docs.py`, and, if a Node Mermaid package is
available, a small local parser adapter in this directory. Keep all fixtures
fictional and create Git test repositories in temporary directories. Use Python
3.12 and the standard library; use an installed Mermaid parser without fetching
packages or using `npx`. Do not change existing documents, gate files, workflows,
dependency manifests, or application code.

1. Parse links in Markdown pages under `docs/` and the root `README.md`, including
   inline links, images, reference links, and angle-bracket autolinks. Ignore
   fenced code examples. Check local paths inside the selected repository tree.
   Check this repository's GitHub `blob` and `tree` URLs at full commit SHAs using
   local `git cat-file -e` and object types. Report other remote URLs as outside
   this offline check; do not claim their destinations were verified. Reject
   unsafe paths before any filesystem or Git content access. Never read any
   `.env*` path or private data directory, even if a document links to it.
2. Check `#L12` and `#L12-L30` against the cited file's actual line count at that
   SHA. Compare all visible numeric line ranges associated with a link to its
   anchors. Handle deliberately combined citations as ranges; report stale or
   ambiguous associations instead of silently accepting them.
3. Print a page-by-SHA table. Determine the newest pin from commit ancestry;
   report incomparable histories instead of guessing from SHA order. Compare
   each older linked target with the same target at that pin by Git blob ID.
   Report missing, changed, and non-file targets explicitly. Validate optional
   `docs/pin-claims.json` against parsed links and document its exact schema
   before implementation. Never treat text equality as proof of URL routing.
4. Parse every Mermaid fence with installed `mmdc` or an installed Node Mermaid
   package. An unavailable or unusable parser means `unverified` with a reason,
   never a pass. Capture parser diagnostics without echoing diagram contents.
5. Scan selected text for configurable forbidden path patterns (default names:
   `project-data`, `poc-catalog`) and key-like strings. Print only source file
   and count, never the matched value or source excerpt. Optionally load a
   hash-only list from an environment-variable path outside the repository;
   document normalization and matching rules, reject an in-repository or
   unreadable list, and test private-string redaction with fictional values.
6. Compare file bytes with the selected base revision and report LF/CRLF/mixed
   line-ending changes, including content-equal newline conversions. Do not
   modify or normalize documents.

## Proposed use and exit codes

The final interface will support a repository path, an optional pinned document
revision, selected page paths, a comparison base, privacy configuration, and an
optional installed Mermaid module path. The README will show runnable commands
after the implementation exists.

| Exit | Meaning |
| --- | --- |
| 0 | All requested offline checks completed with no findings. |
| 1 | Checks completed and found defects. |
| 2 | At least one requested check could not be verified. Findings are still printed. |

Exit 2 takes precedence over exit 1. Missing required paths or malformed optional
configuration cannot silently produce a clean result. The optional private hash
check is disabled when its environment variable is unset and must be labelled
as disabled, not passed.

## Validation plan

For each of the six checks, write a pass case and a defect case that would be
missed if that check were removed. Also cover reference links, spaces/escapes,
missing Git objects, wrong object types, multi-range labels, incomparable pins,
claim-file disagreement, unavailable Mermaid, value-free privacy diagnostics,
forbidden paths, and changed-only line endings. Exercise the command exit codes
through its real entry point.

Run the suite without provider calls or credentials. Run the completed tool on
the current `docs/how-it-works/` pages and paste the complete report and exit
code into the PR evidence and external audit note. At the initial base
`d64e78338b487d8ea9694810c49980b5e82dbedd`, that tree is absent from `origin/main`;
it exists at integration commit
`0a580c75e526770d93a81099db91ab47a5a8dfe7`. A read-only Git revision input will
allow that evidence run without changing existing docs or another worktree.

Run the existing gate scanner on the changed-file range after checking that the
range contains no `.env*` paths. Record the exact head, commands, counts,
limitations, and scope. Do not claim a private catalog comparison without a
supplied external hash list. Do not approve or merge this PR.

## Suggestions

CI wiring can be proposed after review. It is outside this task and will not be
implemented here.
