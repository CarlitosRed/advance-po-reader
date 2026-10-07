# The merge gate

`po_gate.py` is the merge gate for this repository. It exists because the repository is private on GitHub's free plan, and that plan cannot enforce branch protection or required checks. The gate makes the rules in `ROLES.md` checkable and leaves a record on every merge.

It is plain Python (standard library only) and uses two programs you already have: `git` and the GitHub CLI `gh`, signed in as the project's GitHub account. No package install, no network call except through `gh`, no key.

## Commands

Run them from any desk (worktree) of this repository, in PowerShell. The settings file `gate.json` is found next to the script.

```powershell
python tools\gate\po_gate.py check 12
python tools\gate\po_gate.py merge 12 --as "Codex · goal gaps" --dry-run
python tools\gate\po_gate.py merge 12 --as "Codex · goal gaps"
python tools\gate\po_gate.py scan --rev HEAD
python tools\gate\po_gate.py paths
python tools\gate\po_gate.py audit --range <old>..<new>
```

If `python` is not found, use `py -3` instead.

| Command | What it does | Changes anything? |
| --- | --- | --- |
| `check <PR>` | Prints every rule as PASS or FAIL for the pull request's current head commit. Exit code 0 only if all pass. | No |
| `merge <PR> --as "<chat name>"` | Runs `check`. If all pass, squash-merges that exact commit (`--match-head-commit`) and writes a `Gate-Record:` line into the merge commit. `--dry-run` prints the command and merges nothing. | Yes, merges |
| `scan` | Looks for forbidden files and secrets by name and by content (a PDF renamed `.txt` is still a PDF). `--staged`, `--rev <commit>` or `--range A..B`. Used by the pre-push hook and the `scan` CI job. | No |
| `paths` | Shows how many tracked files each protected path matches, to catch a mistyped folder name. | No |
| `audit --range A..B` | Flags commits on `main` that have no `Gate-Record:` line, and lists Tier 3 merges for Carlos. Used by the `Gate audit` workflow. | No |

Exit codes: 0 passed, 1 a rule failed, 2 the tool could not run (the message says why).

## The rules `check` applies

| Rule | Passes when |
| --- | --- |
| `state` | The pull request is open, not a draft, and targets `main`. |
| `hold` | No comment starting with `hold` is active (Carlos's `unhold` lifts it) and the `hold` label is off. |
| `tier` | Exactly one `tier-N` label. Protected paths raise it to 3 (the old name of a renamed file counts too), and a Tier 1 label that touches more than `docs\` and `README.md` is raised to 2. Tier 4 never passes. |
| `files` | The gate reads the complete list of changed files, page by page (`gh api repos/<repo>/pulls/<n>/files --paginate`), because `gh pr view` stops at 100 files. It only trusts the list when it can prove it is complete: the number of files in the list must equal GitHub's own count for the pull request, every entry must have a file name, and no file may appear twice. An empty answer, an error answer, a short list, a missing count, or a missing or unknown file status all stop the check (never a pass). The list must also belong to the same change the gate is judging: the pull request's number, base branch, base commit, head branch, head commit and file count are read before and after the list, and if any of them moved (for example `main` advanced and the change now compares against a different base), the check stops and must be run again. A file marked renamed or copied must name the file it came from, otherwise the check stops. Every value the gate relies on is checked as exact text or a whole number before it is compared: commit ids must be exactly 40 lowercase hex characters (no spaces or line breaks around them), branch names must be plain text without spaces or line breaks, the file count must be a real whole number (not `true` or `1.0`), and file names, old names and statuses must be clean text. A file name is refused if it contains any hidden or control character (line breaks, tabs, zero-width or right-to-left marks, private-use or unassigned characters, broken surrogate pairs) or any space-like character other than the ordinary space inside a file name (never at its start or end), a backslash, a `..` part, or a root: a leading `/` or `//`, a drive such as `C:`, or a network share. A branch name must be a valid Git branch name, checked exactly and never repaired: no spaces or hidden characters, none of `~ ^ : ? * [` or a backslash, no `..` or `@{`, no leading `-`, no empty part (`//`, or a leading or trailing `/`), no part starting with `.` or ending in `.lock`, no trailing `.`, The repository name must be a plain `owner/name` (letters, digits, `.`, `_`, `-`). Ordinary accents, Chinese, Japanese and other letters are fine. A status must be exactly one of GitHub's seven lowercase words. Anything else stops the check. The forbidden-file and protected-path rules ignore upper and lower case, so `Reader.py` counts as `reader.py`. A renamed file is judged under both its new and its old name, so moving `reader.py` or a `.github` file somewhere ordinary still counts as touching it. Then: no forbidden file names (PDFs, images, model files, `.env*`, `data\`, `output\`, `tmp\`, `.venv\`, SQLite files, keys), and fewer than 3000 changed files. GitHub lists at most 3000 files, so at 3000 or more the list may be cut off and the gate refuses (split the change). A rename counts as one file. |
| `check:<name>` | Each required check (`tests`, `gate-tests`, `scan`) succeeded on the head commit, in every run of that name. |
| `evidence:<heading>` | Tier 2 and 3: the pull request body has `## Plan`, `## Evidence` and `## Cost`. |
| `plan` | Tier 2 and 3: a signed comment starting with `go` from the other vendor's reviewer, or from Carlos. |
| `review` | Tier 2 and 3: one signed `Approved at <commit>` matching the head, from a chat of the other vendor. A later `Not approved at <commit>` from the same chat cancels it, and a `Not approved` at the head from any chat blocks. |
| `owner` | Tier 3: `**Carlos:** Approved at <commit>` matching the head. |
| `comments` | Fewer than 100 comments, so the conversation can be read in full. |

Who counts as author, reviewer and owner comes from `gate.json`: `branch_vendors` (branch prefix to vendor), `vendors` (first word of a chat name to vendor) and `owner_names`.

## `merge` rules

- `--as` is required and must look like `Codex · goal gaps`. It is written into the merge record.
- The author's vendor merges. A Codex-branch pull request is merged by a Codex or Chat chat, a Claude-branch one by a Claudio chat. Carlos may always merge. A chat that approved the pull request may not merge it.
- The merge is a squash. The commit message ends with `Gate-Record: pass tier=N head=<40 characters> reviewers=<names> owner=<yes|no> by=<name>`.

## What the gate cannot do

- **It cannot stop a manual merge.** Anyone holding the account's credentials can click the green button or run `gh pr merge`. The audit workflow then opens an issue, after the fact.
- **It cannot prove who wrote a comment.** Every chat posts as one GitHub account, and comments can be edited. The report always says so. Carlos's `hold` and the audit are the backstop.
- **It checks the head commit, not the code.** A reviewer who approves a bad change still approves it. The checks (`tests`, `scan`) and the reviewer are the quality control, not the gate.

If the project later pays for a GitHub plan, turn on branch protection with required checks and keep this gate as a second layer. In that case, move owner approval from a comment to a real review by a second GitHub account.

## Changing the rules

`gate.json` holds every setting. It is in `tools\gate\`, so a change is a Tier 3 pull request. The settings Carlos is most likely to change:

| Setting | Meaning | Default |
| --- | --- | --- |
| `approvals_required` | Approvals per tier | `1`: 0, `2`: 1, `3`: 1 |
| `same_vendor_ok_tiers` | Tiers where a listed reviewer chat of the author's own vendor may approve | `[]` (never) |
| `protected_paths` | Paths that make a change Tier 3 | see the file |
| `scan_allow` | Paths exempt from the file-name, file-type and size checks (secrets are still looked for). Add a path only with Carlos's yes, for synthetic fixtures. | `.env.example` and `.env.*.example` |
| `required_checks` | CI job names that must pass | `tests`, `gate-tests`, `scan` |

## First use after the gate is merged

1. `python tools\gate\po_gate.py check <an open pull request>`. Expect a list of rules and probably a few FAIL lines (no tier label, no plan comment). A Python error or an `ERROR:` line means the gate and GitHub disagree about a field name. Stop and tell Claudio · PM.
2. `python tools\gate\po_gate.py merge <a ready pull request> --as "<chat name>" --dry-run`. It prints the `gh pr merge` command and merges nothing.
3. Only then merge for real.

## Tests

```powershell
python -m unittest discover -s tools\gate -p "test_po_gate.py" -v
```

The tests use a pretend `gh` and temporary git repositories. They never contact GitHub. CI runs them as the `gate-tests` job.
