# Offline documentation checker (V2-14)

This tool checks documentation references before independent review. It reads
local files or local Git objects, reports defects, and leaves the documents alone.
It checks mechanics; a working citation does not prove that its prose is true.
This draft PR adds only this directory. CI wiring is a separate suggestion.

## Run it

Requires Python 3.12 and Git. The Python checker and tests use the standard
library. An installed Node Mermaid package is optional. Nothing is downloaded.
From the repository root:

```powershell
python tools/docs-check/check_docs.py --repo .
python tools/docs-check/check_docs.py --repo . --page docs/example.md --base HEAD
python -m unittest discover -s tools/docs-check -p test_check_docs.py
```

The first command selects Markdown files below `docs/` and root `README.md`.
Repeat `--page` to choose files or directories; a missing or empty selection is
unverified. `--base` defaults to `HEAD`. The checker compares the selected pages,
not every file in the repository. New pages without a base version are counted
as added, with no newline comparison claimed.

Use a read-only document revision when pages live on another branch. Local
links, the optional claims file, diagrams and privacy text then come from that
commit too, without reading another worktree. Full-SHA GitHub links always use
their own cited commit. For the current integration documentation:

```powershell
python tools/docs-check/check_docs.py --repo . --revision 0a580c75e526770d93a81099db91ab47a5a8dfe7 --page docs/how-it-works --base d64e78338b487d8ea9694810c49980b5e82dbedd
```

| Exit | Meaning |
| --- | --- |
| 0 | Requested checks completed with no findings. Other remote URLs remain outside offline verification. |
| 1 | Checks found defects. |
| 2 | A requested check or input could not be verified. Findings are retained; 2 takes precedence over 1. |

Configuration errors and unavailable Git objects produce exit 2. An unset
external private-hash variable is labelled `disabled`, not passed. With no
Mermaid fences there is no diagram to verify; with fences and no usable parser,
exit 2 is required.

## What the six checks do

1. **Links.** Resolve inline links and images, full/collapsed/shortcut reference
   links, and angle-bracket HTTP/mail autolinks. Escaped spaces/parentheses,
   nested labels and percent-encoded paths are supported. Fenced examples,
   inline code and HTML comments are excluded. Missing explicit references,
   duplicate definitions, incomplete destinations and HTML link tags are
   unverified. Other Markdown dialect extensions are not a complete CommonMark
   conformance claim. Local file/directory destinations must exist. Heading
   fragments use the checker's ATX heading slug rules. Same-repository GitHub
   `blob`/`tree` links require a full lowercase 40-character commit SHA, a local
   commit object, and the correct target type. `git cat-file -e` checks the
   object; `ls-tree` checks its mode and type. Other remote URLs, including PR
   URLs, are counted as outside offline verification. No URL is fetched.
2. **Line labels.** Check `#L12` and `#L12-L30` against actual file bytes. Explicit
   visible `line`/`lines`/`L` labels, numeric labels on line-anchor links, and
   immediately adjacent line labels must equal the anchor range. Commas, `and`,
   `&`, hyphens, en/em dashes and `to` can separate ranges. Multiple visible
   ranges cannot equal one continuous anchor; that is a finding. Unrecognized
   label associations are unverified. Numeric page names are not line labels.
3. **Pins.** Print counts per page and SHA from parsed links. The newest pin must
   descend from every other pin in the selected pages. If none does, histories
   are incomparable and comparison is unverified; commit dates and SHA order
   are not substitutes. Compare every older linked file's blob ID with the same
   target at that newest pin. Changed, absent or non-file targets are findings.
   This proves byte equality only. Optional claims below check actual URL counts.
4. **Mermaid.** The local adapter uses installed Mermaid's `parse` API through
   Node, without rendering, a browser or `npx`. It tries local module resolution,
   or the installed package/entry-point path supplied with `--mermaid-module`.
   A known-valid and a known-invalid control must work before a diagram can
   pass. Missing packages, missing Node, bad output, timeouts and runtime errors
   are unverified. Recognized syntax errors are findings. Package diagnostics
   and diagram contents are withheld. The installed parser is trusted code;
   synthetic adapter tests do not establish real Mermaid validity.
5. **Privacy.** Scan complete selected page text, including code examples, for
   case-insensitive `project-data`/`poc-catalog` patterns and common key-shaped
   strings. Add regexes with repeatable `--forbid`. Findings contain source file
   and count, without matched text or excerpts. Heuristics can have false
   positives and cannot prove that no private information exists. The optional
   external hash contract below checks only supplied normalized phrases.
6. **Newlines.** Compare selected page bytes with `--base`. Report LF, CRLF, lone
   CR or mixed style changes, including content-equal newline conversions.
   Changing content while retaining the same newline style is not a finding.
   Files are not normalized or rewritten.

Path checks run before content reads. Dot traversal beyond the repository,
absolute/drive/UNC paths, control or separator characters, repeated percent
encoding, Windows device/ADS/short-name aliases, trailing dots/spaces, `.env*`
components, and private directories are refused. Git symlinks/submodules and
filesystem symlinks/junctions/reparse points are unverified, without following
their targets. Excluded data directories include `data`, `output`, `project-data`
and `poc-catalog`; source traversal also refuses `.git`, `.venv`, `node_modules`.
An explicitly supplied installed parser may live under `node_modules`.
Use a stable checkout: these local checks do not lock files against concurrent
replacement. Git reads disable lazy fetching and do not invoke GitHub/provider
clients. The checker makes no provider request and needs no credentials.

## Optional pin claims

`docs/pin-claims.json`, when present in the selected document tree, must use
exactly this schema (the SHA below is a fictional placeholder):

```json
{
  "version": 1,
  "pages": {
    "docs/example.md": [
      {"target": "src/example.py", "sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "count": 2}
    ]
  }
}
```

For each listed page, rows describe its **entire** multiset of same-repository
full-SHA blob/tree links, including images and repeated references. Unlisted
pages make no claim. Empty rows mean zero such links. Each page must be selected
in this run. Targets and page names are canonical safe repository-relative
paths; a target of `.` names a repository-root tree link. SHA fields must identify
locally available commits. Counts are positive JSON integers, excluding booleans
and floats. Extra/missing fields, duplicate
JSON keys, duplicate target/SHA rows and unselected pages are unverified.
Differences from parsed links produce `claims_disagree` and exit 1, unless
another check requires exit 2. The tool does not read or validate prose claims.

## Optional private phrases without plaintext

By default `DOCS_PRIVATE_HASHES` may name an absolute path to a hash-only JSON
file **outside** this repository. Use `--hash-env NAME` for another variable.
Do not put plaintext phrases in the file or in Git. Schema:

```json
{
  "version": 1,
  "entries": [
    {"words": 3, "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
  ]
}
```

The repeated `a` digest above is a placeholder. For each authorized phrase,
normalize with Unicode NFKC, then Python `casefold()`, then split on whitespace
and join words with one ASCII space. Hash those UTF-8 bytes with SHA-256. Keep
punctuation. `words` is its token count (an integer 1 through 32); `sha256` is
64 lowercase hexadecimal characters. The checker hashes every contiguous
window of that many whitespace tokens in normalized page text. A phrase that
has different punctuation, lies inside a larger token, or is longer than 32
tokens is not covered by this contract. No plaintext catalog is loaded.

Missing/unreadable/in-repository files, private or aliased paths, empty lists,
malformed schemas, duplicate rows, and extra fields are unverified. An unset or
empty variable disables this optional check. Hash matches print only file and
count. The current real-doc run has no supplied private hash list, so it makes
no private catalog comparison claim.

## Validation and limits

The unittest suite builds disposable fictional Git repositories. It covers all
six checks with pass and defect cases, field matrices, Windows path forms,
wrong Git types, aliases, multiple ranges, divergent pins, claim disagreement,
parser protocol failures, value-free privacy output, and newline-only changes.
An in-memory mutation test removes each of the six checks in turn and requires
its defect test to fail. The real process entry point exercises exit codes too.

The current `how-it-works` report, exact commands, counts, class sweep and claims
ledger are recorded in PR #28 and the external audit note. Findings are reported
without editing those pages. Real Mermaid validation remains unverified when
no installed parser is available. Whole-application/browser/demo tests are not
evidence for this new offline CLI and are not claimed by its unit suite.
