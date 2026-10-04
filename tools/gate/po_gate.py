#!/usr/bin/env python3
"""po_gate: the merge gate for Advance PO Reader, for a repository on a plan without branch protection.

Standard library only. Uses the GitHub CLI (gh) and git. Works the way the project already works:
all chats post as one GitHub account, so approvals are signed comments, not GitHub reviews.

Commands
  check <PR>              Evaluate every gate rule against the PR's current head commit.
  merge <PR> --as NAME    Run check; if it passes, squash-merge with the head commit pinned.
  audit --range A..B      Flag commits on main that did not come through `merge`.
  scan                    Block forbidden files and secrets, by content as well as by name.
  paths                   Show how many tracked files each protected path matches.

What the gate cannot do: stop someone who has the account's credentials from merging by hand.
It makes the rules checkable and leaves a record on every merge. The audit job and Carlos's
"hold" are the backstops. See README.md.
"""
import argparse
import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys

TIER_LABELS = {"tier-1": 1, "tier-2": 2, "tier-3": 3, "tier-4": 4}
TRAILER = re.compile(r"^Gate-Record: pass tier=([123]) head=([0-9a-f]{40})\b(.*)$", re.M)

# A signed comment starts with the chat's name in bold, for example:  **Codex · Gate A:** Approved at `318ae2d`.
SIGNATURE = re.compile(r"^\s*\*\*\s*(?P<name>[^*\n]+?)\s*:?\s*\*\*\s*:?\s*(?P<rest>.*)\Z", re.S)
VERDICT = re.compile(r"^(approved|not approved) at\s+`?([0-9a-f]{7,40})`?", re.I)
GO = re.compile(r"^go\b", re.I)
HOLD = re.compile(r"^hold\b", re.I)
UNHOLD = re.compile(r"^unhold\b", re.I)
SEP = "·"  # the middle dot in "Codex · Gate A"

MAGIC = [
    (b"%PDF-", "PDF"),
    (b"\x89PNG\r\n\x1a\n", "PNG image"),
    (b"\xff\xd8\xff", "JPEG image"),
    (b"GIF87a", "GIF image"),
    (b"GIF89a", "GIF image"),
    (b"II*\x00", "TIFF image"),
    (b"MM\x00*", "TIFF image"),
    (b"GGUF", "GGUF model file"),
]
SECRETS = [
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), "API key (sk-...)"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"), "private key"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"), "GitHub token"),
]
VIEW_FIELDS = ("number,title,state,isDraft,baseRefName,headRefName,headRefOid,author,labels,"
               "body,files,statusCheckRollup,comments,reviews")

DEFAULTS = {
    "repo": "",                       # empty = detect with `gh repo view` from the current folder
    "base": "main",
    "owner_names": ["Carlos"],        # who may approve Tier 3 and lift a hold
    "vendors": {"Claudio": "anthropic", "Claude": "anthropic", "Codex": "openai", "Chat": "openai"},
    "branch_vendors": {"claude/": "anthropic", "codex/": "openai", "chat/": "openai"},
    "approvals_required": {"1": 0, "2": 1, "3": 1},
    "same_vendor_ok_tiers": [],       # tiers where a reviewer chat of the author's own vendor may approve
    "reviewer_chats": ["Codex \u00b7 PR review", "Claudio \u00b7 PR review"],
    "owner_approval_tiers": [3],
    "plan_go_tiers": [2, 3],
    "evidence_tiers": [2, 3],
    "evidence_headings": ["Plan", "Evidence", "Cost"],
    "tier1_paths": ["docs/*", "README.md"],
    "required_checks": ["tests", "gate-tests", "scan"],
    "protected_paths": [
        "AGENTS.md", "CLAUDE.md", "ROLES.md", "PROJECT_GOAL.md", "CODEOWNERS",
        ".github/*", ".githooks/*", ".claude/*", "tools/gate/*",
        "backend/providers.py", "po_reader/model_provider.py", "reader.py", "benchmark_vision.py",
        "scripts/*", "alembic/*", "*/alembic/*", "*/migrations/*",
    ],
    "forbidden_globs": [
        "*.pdf", "*.png", "*.jpg", "*.jpeg", "*.gif", "*.tif", "*.tiff",
        "*.gguf", "*.safetensors", "*.pt", "*.pth", "*.onnx", "*.sqlite3", "*.pem", "*.key",
        ".env", ".env.*", "data/*", "output/*", "tmp/*", ".venv/*",
    ],
    "scan_allow": [".env.example", ".env.*.example"],
    "max_file_mb": 5,
    "shared_account": True,
    "audit_exempt": [],
}


class GateError(Exception):
    pass


def default_config_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "gate.json")


def load_config(path):
    cfg = dict(DEFAULTS)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    return cfg


def match_any(path, globs):
    """A glob with no slash also matches the file's own name in any folder."""
    name = path.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatchcase(path, g) or ("/" not in g and fnmatch.fnmatchcase(name, g))
               for g in globs)


# ---------------------------------------------------------------- runners

def run_gh(args):
    p = subprocess.run(["gh"] + args, capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        raise GateError(f"gh {' '.join(args)} failed: {p.stderr.strip()}")
    return p.stdout


def run_git(args, cwd=None, binary=False):
    p = subprocess.run(["git"] + args, capture_output=True, cwd=cwd)
    if p.returncode != 0:
        raise GateError(f"git {' '.join(args)} failed: {p.stderr.decode(errors='replace').strip()}")
    return p.stdout if binary else p.stdout.decode("utf-8", errors="replace")


# ---------------------------------------------------------------- reading signed comments

def split_signature(body):
    """Return (name, rest). name is None when the comment is not signed."""
    m = SIGNATURE.match(body or "")
    if not m:
        return None, (body or "").strip()
    return m.group("name").strip(), m.group("rest").strip()


def who_of(name):
    """'Codex · Gate A' -> 'Codex'."""
    return name.split(SEP)[0].strip()


def vendor_of(cfg, name):
    who = who_of(name).lower()
    for key, vendor in cfg["vendors"].items():
        if key.lower() == who:
            return vendor
    return None


def is_owner(cfg, name):
    return who_of(name).lower() in [o.lower() for o in cfg["owner_names"]]


def author_vendor_of(cfg, branch):
    for prefix, vendor in cfg["branch_vendors"].items():
        if (branch or "").startswith(prefix):
            return vendor
    return None


def timeline(pr):
    """Comments and review bodies, oldest first. Hidden (minimized) comments are ignored."""
    items = []
    for cm in pr.get("comments") or []:
        if cm.get("isMinimized"):
            continue
        items.append({"body": cm.get("body") or "", "when": cm.get("createdAt") or ""})
    for rv in pr.get("reviews") or []:
        if rv.get("body"):
            items.append({"body": rv["body"], "when": rv.get("submittedAt") or ""})
    items.sort(key=lambda i: i["when"])
    return items


def read_signals(pr, cfg):
    """Parse the conversation into the latest verdict per signer, plan 'go' signers and hold state."""
    latest, go_by, held, held_by = {}, set(), False, None
    for it in timeline(pr):
        name, rest = split_signature(it["body"])
        if HOLD.match(rest):
            held, held_by = True, name or "an unsigned comment"
        elif UNHOLD.match(rest) and name and is_owner(cfg, name):
            held, held_by = False, None
        if not name:
            continue
        m = VERDICT.match(rest)
        if m:
            latest[name] = ("approve" if m.group(1).lower() == "approved" else "reject", m.group(2).lower())
        if GO.match(rest):
            go_by.add(name)
    return {"latest": latest, "go_by": go_by, "held": held, "held_by": held_by}


# ---------------------------------------------------------------- check

def repo_of(gh, cfg):
    if cfg.get("repo"):
        return cfg["repo"]
    repo = gh(["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"]).strip()
    if not repo:
        raise GateError("could not detect the repository; run inside the repo folder or set 'repo' in gate.json")
    cfg["repo"] = repo
    return repo


def fetch_pr(gh, cfg, number):
    raw = gh(["pr", "view", str(number), "--repo", repo_of(gh, cfg), "--json", VIEW_FIELDS])
    return json.loads(raw)


def evaluate(pr, cfg):
    results, notes = [], []

    def add(rule, ok, msg):
        results.append({"rule": rule, "ok": bool(ok), "msg": msg})

    head = pr.get("headRefOid") or ""
    branch = pr.get("headRefName") or ""
    files = [f.get("path", "") for f in (pr.get("files") or [])]
    labels = [lb.get("name") for lb in (pr.get("labels") or [])]
    sig = read_signals(pr, cfg)
    a_vendor = author_vendor_of(cfg, branch)

    # state
    add("state", pr.get("state") == "OPEN" and not pr.get("isDraft") and pr.get("baseRefName") == cfg["base"],
        f"PR is {pr.get('state')}{' (draft)' if pr.get('isDraft') else ''} into {pr.get('baseRefName')}; "
        f"needs to be open, not draft, into {cfg['base']}")

    # hold
    hold_label = "hold" in labels
    add("hold", not (sig["held"] or hold_label),
        "no hold" if not (sig["held"] or hold_label) else
        ("the 'hold' label is on; remove it to continue" if hold_label else
         f"on hold ({sig['held_by']}); a comment from Carlos starting with 'unhold' lifts it"))

    # tier
    tier_labels = [t for t in labels if t in TIER_LABELS]
    tier = None
    if len(tier_labels) != 1:
        add("tier", False, f"needs exactly one tier label (tier-1..tier-4), found {tier_labels or 'none'}")
    else:
        tier = TIER_LABELS[tier_labels[0]]
        protected = [f for f in files if match_any(f, cfg["protected_paths"])]
        if tier == 4:
            add("tier", False, "tier-4 is human only: agents and this gate never merge it")
        elif protected and tier < 3:
            add("tier", True, f"{tier_labels[0]} raised to tier-3 because it touches protected paths: "
                f"{', '.join(protected[:3])}{' ...' if len(protected) > 3 else ''}")
            tier = 3
        elif tier == 1 and any(not match_any(f, cfg["tier1_paths"]) for f in files):
            add("tier", True, "tier-1 raised to tier-2 because it changes more than docs and tests")
            tier = 2
        else:
            add("tier", True, tier_labels[0])

    # files
    if len(files) >= 100:
        add("files", False, "100 or more changed files: the file list cannot be fully verified; split the change")
    else:
        bad = [f for f in files if match_any(f, cfg["forbidden_globs"]) and not match_any(f, cfg["scan_allow"])]
        add("files", not bad, "no forbidden files" if not bad else f"forbidden files changed: {', '.join(bad[:5])}")

    # conversation size
    if len(pr.get("comments") or []) >= 100:
        add("comments", False, "100 or more comments: the conversation cannot be fully read; open a fresh PR")

    # required checks
    rollup = pr.get("statusCheckRollup") or []
    for name in cfg["required_checks"]:
        entries = [c for c in rollup if (c.get("name") or c.get("context")) == name]
        okay = bool(entries) and all(
            (c.get("conclusion") == "SUCCESS" if c.get("__typename", "CheckRun") == "CheckRun"
             else c.get("state") == "SUCCESS") for c in entries)
        add(f"check:{name}", okay, "passed on the head commit" if okay else
            ("not found on the head commit" if not entries else "not successful on the head commit"))

    if tier is None:
        return _finish(results, notes, head, tier, [], False, a_vendor, branch, pr, cfg)

    # evidence packet
    if tier in cfg["evidence_tiers"]:
        body = pr.get("body") or ""
        for heading in cfg["evidence_headings"]:
            has = re.search(rf"(?im)^#{{1,6}}\s*{re.escape(heading)}\b", body) is not None
            add(f"evidence:{heading}", has, "present in the PR body" if has else "missing heading in the PR body")

    # who is the author's vendor
    if a_vendor is None and (tier in cfg["plan_go_tiers"] or cfg["approvals_required"].get(str(tier), 0) > 0):
        add("author", False, f"branch '{branch}' does not start with one of: {', '.join(cfg['branch_vendors'])}; "
            "the gate cannot tell which vendor wrote it")

    def independent(name):
        v = vendor_of(cfg, name)
        if v is None or a_vendor is None:
            return False
        if v != a_vendor:
            return True
        return tier in cfg["same_vendor_ok_tiers"] and name.lower() in [r.lower() for r in cfg["reviewer_chats"]]

    # plan go
    if tier in cfg["plan_go_tiers"]:
        goers = sorted(n for n in sig["go_by"] if independent(n) or is_owner(cfg, n))
        add("plan", bool(goers),
            f"plan 'go' from {', '.join(goers)}" if goers else
            "no plan 'go' from the other vendor's reviewer (or Carlos); comment must start with the word go")

    # independent review
    needed = cfg["approvals_required"].get(str(tier), 0)
    approvers, blockers, ignored = [], [], []
    for name, (kind, sha) in sorted(sig["latest"].items()):
        matches = bool(head) and head.startswith(sha)
        if kind == "reject":
            if matches:
                blockers.append(name)
            continue
        if is_owner(cfg, name):
            continue
        if not matches:
            ignored.append(f"{name} approved an older commit")
        elif vendor_of(cfg, name) is None:
            ignored.append(f"{name} is not a known chat")
        elif not independent(name):
            ignored.append(f"{name} is the same vendor as the author (tier {tier} needs the other vendor)")
        else:
            approvers.append(name)
    if needed or approvers or blockers:
        add("review", len(approvers) >= needed and not blockers,
            f"{len(approvers)} of {needed} independent approval(s) at the head commit"
            + (f" by {', '.join(approvers)}" if approvers else "")
            + (f"; not approved by {', '.join(blockers)}" if blockers else "")
            + (f"; ignored: {'; '.join(ignored)}" if ignored else ""))

    # owner approval
    owner_ok = False
    if tier in cfg["owner_approval_tiers"]:
        owners = [n for n, (kind, sha) in sig["latest"].items()
                  if is_owner(cfg, n) and kind == "approve" and head.startswith(sha)]
        owner_ok = bool(owners)
        add("owner", owner_ok, "Carlos approved at the head commit" if owner_ok else
            "tier 3 needs a comment from Carlos: **Carlos:** Approved at <commit>, matching the current head")
    else:
        owner_ok = any(is_owner(cfg, n) and k == "approve" and head.startswith(s)
                       for n, (k, s) in sig["latest"].items())

    return _finish(results, notes, head, tier, approvers, owner_ok, a_vendor, branch, pr, cfg)


def _finish(results, notes, head, tier, approvers, owner_ok, a_vendor, branch, pr, cfg):
    if cfg.get("shared_account"):
        notes.append("Approvals are comments from one shared GitHub account, so the gate cannot prove "
                     "which person or chat wrote them. It records them; the audit job and Carlos's hold "
                     "are the backstop.")
    return {
        "head": head, "tier": tier, "branch": branch, "author_vendor": a_vendor,
        "title": pr.get("title", ""), "results": results,
        "passed": all(r["ok"] for r in results), "approvers": approvers,
        "owner_approved": owner_ok, "notes": notes,
    }


def format_report(ev, number):
    lines = [f"PR #{number}  head {ev['head'][:8]}  branch {ev['branch']}  tier {ev['tier']}  "
             f"author vendor {ev['author_vendor']}"]
    for r in ev["results"]:
        lines.append(f"  [{'PASS' if r['ok'] else 'FAIL'}] {r['rule']}: {r['msg']}")
    lines.append("RESULT: " + ("PASS" if ev["passed"] else "FAIL"))
    for n in ev["notes"]:
        lines.append("NOTE: " + n)
    return "\n".join(lines)


def cmd_check(gh, cfg, number, out=print):
    ev = evaluate(fetch_pr(gh, cfg, number), cfg)
    out(format_report(ev, number))
    return 0 if ev["passed"] else 1


def validate_merger(cfg, merged_as):
    if not merged_as or not merged_as.strip():
        raise GateError("--as is required, for example --as \"Codex · goal gaps\"")
    who = who_of(merged_as)
    known = [w.lower() for w in cfg["vendors"]] + [o.lower() for o in cfg["owner_names"]]
    if who.lower() not in known:
        raise GateError(f"'{merged_as}' does not start with a known name ({', '.join(cfg['vendors'])}, "
                        f"{', '.join(cfg['owner_names'])}); write it like: Codex {SEP} goal gaps")
    if not is_owner(cfg, merged_as) and SEP not in merged_as:
        raise GateError(f"'{merged_as}' needs the chat's job after the dot, like: {who} {SEP} <job>")


def cmd_merge(gh, cfg, number, merged_as, dry_run=False, out=print):
    validate_merger(cfg, merged_as)
    ev = evaluate(fetch_pr(gh, cfg, number), cfg)
    out(format_report(ev, number))
    if not ev["passed"]:
        return 1
    if not is_owner(cfg, merged_as):
        if vendor_of(cfg, merged_as) != ev["author_vendor"]:
            raise GateError(f"the author merges: this PR is on a {ev['author_vendor']} branch "
                            f"({ev['branch']}), so '{merged_as}' cannot merge it")
        if merged_as in ev["approvers"]:
            raise GateError("a reviewer who approved this PR cannot also merge it")
    head = ev["head"]
    record = (f"Gate-Record: pass tier={ev['tier']} head={head} "
              f"reviewers={'; '.join(ev['approvers']) or 'none'} "
              f"owner={'yes' if ev['owner_approved'] else 'no'} by={merged_as}")
    cmd = ["pr", "merge", str(number), "--repo", repo_of(gh, cfg), "--squash",
           "--match-head-commit", head, "--subject", f"{ev['title']} (#{number})", "--body", record]
    if dry_run:
        out("DRY RUN: gh " + " ".join(shlex.quote(c) for c in cmd))
        return 0
    gh(cmd)
    out(f"Merged PR #{number} at {head[:8]}. {record}")
    return 0


# ---------------------------------------------------------------- audit

def cmd_audit(git, cfg, rng, out=print):
    zeros = re.match(r"^0+\.\.(.+)$", rng or "")
    args = ["log", "--first-parent", "--format=%H%x1f%an%x1f%s%x1f%b%x1e"]
    args += ["-n", "1", zeros.group(1)] if zeros else [rng]
    flagged, tier3 = [], []
    for rec in git(args).split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        sha, author, subject, body = (rec.split("\x1f") + ["", "", "", ""])[:4]
        if sha in cfg["audit_exempt"]:
            continue
        m = TRAILER.search(body)
        if not m:
            flagged.append((sha, author, subject, "no gate record"))
        elif m.group(1) == "3":
            if "owner=yes" not in m.group(3):
                flagged.append((sha, author, subject, "tier 3 record without owner approval"))
            else:
                tier3.append((sha, subject))
    if flagged:
        out("GATE BYPASSED: these commits on the main branch need a look:")
        for sha, author, subject, why in flagged:
            out(f"  {sha[:8]}  {author}  {subject}  ({why})")
    else:
        out("Audit clean: every commit in the range has a gate record.")
    if tier3:
        out("Tier 3 merges in this range (Carlos: confirm you approved each one):")
        for sha, subject in tier3:
            out(f"  {sha[:8]}  {subject}")
    return 1 if flagged else 0


# ---------------------------------------------------------------- scan

def scan_blob(path, data, cfg):
    problems = []
    allowed = match_any(path, cfg["scan_allow"])
    if not allowed:
        if match_any(path, cfg["forbidden_globs"]):
            problems.append("forbidden file name")
        for magic, kind in MAGIC:
            if data.startswith(magic):
                problems.append(f"content is a {kind}")
                break
        if len(data) > cfg["max_file_mb"] * 1024 * 1024:
            problems.append(f"larger than {cfg['max_file_mb']} MB")
    if b"\x00" not in data[:8192]:  # secrets are looked for even in allowed text files
        text = data.decode("utf-8", errors="replace")
        for rx, label in SECRETS:
            if rx.search(text):
                problems.append(f"looks like: {label}")
    return problems


def scan_history(git, cfg, commits):
    """Scan every file version that any of these commits adds or changes, so a file
    that is added in one commit and removed in the next is still seen."""
    bad, seen = [], set()
    for commit in commits:
        raw = git(["diff-tree", "-r", "-m", "--root", "-z", "--no-commit-id",
                   "--diff-filter=ACMR", commit])
        tokens = [t for t in raw.split("\0") if t]
        for meta, path in zip(tokens[0::2], tokens[1::2]):
            blob = meta.split()[3]  # ":old-mode new-mode old-sha new-sha status"
            if (blob, path) in seen:
                continue
            seen.add((blob, path))
            for problem in scan_blob(path, git(["cat-file", "blob", blob], binary=True), cfg):
                bad.append((f"{path} (commit {commit[:7]})", problem))
    return bad


def cmd_scan(git, cfg, staged=False, rev="HEAD", rng=None, outgoing=None, out=print):
    bad = []
    if rng or outgoing:
        if rng:
            a, b = rng.split("..")
            args = ["rev-list", "--reverse", f"{a}..{b}"]
        else:  # commits no remote branch has yet: what a push of this revision would upload
            args = ["rev-list", "--reverse", outgoing, "--not", "--remotes"]
        bad = scan_history(git, cfg, git(args).split())
    else:
        if staged:
            names = git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"]).split("\n")
            spec = lambda p: ":" + p
        else:
            names = git(["ls-tree", "-r", "--name-only", rev]).split("\n")
            spec = lambda p: f"{rev}:{p}"
        for path in [n for n in names if n]:
            data = git(["show", spec(path)], binary=True)
            for problem in scan_blob(path, data, cfg):
                bad.append((path, problem))
    if bad:
        out("SCAN FAILED:")
        for path, problem in bad:
            out(f"  {path}: {problem}")
    else:
        out("Scan clean.")
    return 1 if bad else 0


# ---------------------------------------------------------------- paths

def cmd_paths(git, cfg, out=print):
    tracked = [n for n in git(["ls-files"]).split("\n") if n]
    out(f"{len(tracked)} tracked files. Protected paths (a change to any of them is tier 3):")
    empty = 0
    for g in cfg["protected_paths"]:
        n = sum(1 for p in tracked if match_any(p, [g]))
        out(f"  {n:4d}  {g}")
        empty += n == 0
    if empty:
        out(f"{empty} protected path(s) match no file today. Fine for paths that will exist later; "
            "otherwise correct the name in gate.json.")
    return 0


# ---------------------------------------------------------------- cli

def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(prog="po_gate", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=default_config_path())
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("pr", type=int)
    m = sub.add_parser("merge")
    m.add_argument("pr", type=int)
    m.add_argument("--as", dest="merged_as", required=True,
                   help='the chat that merges, for example "Codex · goal gaps"')
    m.add_argument("--dry-run", action="store_true")
    a = sub.add_parser("audit")
    a.add_argument("--range", required=True, help="A..B of commits to audit")
    s = sub.add_parser("scan")
    s.add_argument("--staged", action="store_true")
    s.add_argument("--rev", default="HEAD")
    s.add_argument("--range", help="A..B: scan every commit in the range")
    s.add_argument("--outgoing", help="REV: scan every commit of REV that no remote branch has yet")
    sub.add_parser("paths")
    args = ap.parse_args(argv)
    try:
        cfg = load_config(args.config)
        if args.cmd == "check":
            return cmd_check(run_gh, cfg, args.pr)
        if args.cmd == "merge":
            return cmd_merge(run_gh, cfg, args.pr, args.merged_as, args.dry_run)
        if args.cmd == "audit":
            return cmd_audit(run_git, cfg, args.range)
        if args.cmd == "paths":
            return cmd_paths(run_git, cfg)
        return cmd_scan(run_git, cfg, args.staged, args.rev, args.range, args.outgoing)
    except GateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
