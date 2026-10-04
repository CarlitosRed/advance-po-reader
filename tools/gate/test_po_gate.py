import json
import os
import subprocess
import tempfile
import unittest

import po_gate as g

HEAD = "a" * 40
OLD = "b" * 40
SEP = "·"

CFG = dict(g.DEFAULTS)
CFG["repo"] = "CarlitosRed/advance-po-reader"

REVIEW = f"Claudio {SEP} PR review"      # anthropic
CODEX_REVIEW = f"Codex {SEP} PR review"  # openai
AUTHOR = f"Codex {SEP} goal gaps"        # openai (branch codex/...)

BODY = "## Plan\nwhat changes\n## Evidence\n10 passed\n## Cost\n$0\n"


def comment(name, text, when, minimized=False):
    body = f"**{name}:** {text}" if name else text
    return {"author": {"login": "CarlitosRed"}, "body": body, "createdAt": when, "isMinimized": minimized}


def go(name=REVIEW, when="2026-10-04T09:00:00Z"):
    return comment(name, "go", when)


def approve(name=REVIEW, sha=HEAD, when="2026-10-04T10:00:00Z"):
    return comment(name, f"Approved at `{sha[:7]}`. Tests pass.", when)


def pr(**over):
    base = {
        "number": 7, "title": "Add tiers", "state": "OPEN", "isDraft": False,
        "baseRefName": "main", "headRefName": "codex/close-goal-gaps", "headRefOid": HEAD,
        "author": {"login": "CarlitosRed"},
        "labels": [{"name": "tier-2"}], "body": BODY,
        "files": [{"path": "backend/tiers.py"}],
        "statusCheckRollup": [
            {"__typename": "CheckRun", "name": "tests", "status": "COMPLETED", "conclusion": "SUCCESS"},
            {"__typename": "CheckRun", "name": "gate-tests", "status": "COMPLETED", "conclusion": "SUCCESS"},
            {"__typename": "CheckRun", "name": "scan", "status": "COMPLETED", "conclusion": "SUCCESS"},
        ],
        "comments": [go(), approve()],
        "reviews": [],
    }
    base.update(over)
    return base


def rules(ev):
    return {r["rule"]: r["ok"] for r in ev["results"]}


class FakeGH:
    def __init__(self, pull):
        self.pull, self.calls = pull, []

    def __call__(self, args):
        self.calls.append(args)
        if args[:2] == ["pr", "view"]:
            return json.dumps(self.pull)
        if args[:2] == ["repo", "view"]:
            return "CarlitosRed/advance-po-reader\n"
        return ""

    def merged(self):
        return [c for c in self.calls if c[:2] == ["pr", "merge"]]


class SignatureTests(unittest.TestCase):
    def test_signature_forms(self):
        self.assertEqual(g.split_signature(f"**Codex {SEP} Gate A:** Approved at `318ae2d`"),
                         (f"Codex {SEP} Gate A", "Approved at `318ae2d`"))
        self.assertEqual(g.split_signature("**Carlos:** hold")[0], "Carlos")
        self.assertEqual(g.split_signature("**Carlos**: hold")[0], "Carlos")
        self.assertEqual(g.split_signature("plain text"), (None, "plain text"))

    def test_vendor_by_first_word(self):
        self.assertEqual(g.vendor_of(CFG, f"Claudio {SEP} IT"), "anthropic")
        self.assertEqual(g.vendor_of(CFG, f"Chat {SEP} design"), "openai")
        self.assertEqual(g.vendor_of(CFG, f"Codex {SEP} x"), "openai")
        self.assertIsNone(g.vendor_of(CFG, f"Gemini {SEP} x"))


class ReviewTests(unittest.TestCase):
    def test_clean_tier2_passes(self):
        ev = g.evaluate(pr(), CFG)
        self.assertTrue(ev["passed"], g.format_report(ev, 7))
        self.assertEqual(ev["tier"], 2)
        self.assertEqual(ev["approvers"], [REVIEW])
        self.assertEqual(ev["author_vendor"], "openai")

    def test_full_length_sha_is_accepted(self):
        p = pr(comments=[go(), approve(sha=HEAD)])
        p["comments"][1]["body"] = f"**{REVIEW}:** Approved at {HEAD}"
        self.assertTrue(rules(g.evaluate(p, CFG))["review"])

    def test_short_sha_below_seven_characters_is_not_an_approval(self):
        p = pr(comments=[go(), comment(REVIEW, "Approved at `aaaa`", "2026-10-04T10:00:00Z")])
        self.assertFalse(rules(g.evaluate(p, CFG))["review"])

    def test_approval_of_an_older_commit_is_ignored(self):
        p = pr(comments=[go(), approve(sha=OLD)])
        ev = g.evaluate(p, CFG)
        self.assertFalse(rules(ev)["review"])
        self.assertIn("older commit", [r for r in ev["results"] if r["rule"] == "review"][0]["msg"])

    def test_reapproval_at_the_new_head_passes(self):
        p = pr(comments=[go(), approve(sha=OLD, when="2026-10-04T09:30:00Z"), approve(when="2026-10-04T11:00:00Z")])
        self.assertTrue(rules(g.evaluate(p, CFG))["review"])

    def test_same_vendor_reviewer_is_refused(self):
        p = pr(comments=[go(CODEX_REVIEW), approve(CODEX_REVIEW)])
        r = rules(g.evaluate(p, CFG))
        self.assertFalse(r["review"])
        self.assertFalse(r["plan"])

    def test_chat_desk_counts_as_openai(self):
        p = pr(headRefName="chat/mockup-v3", comments=[go(CODEX_REVIEW), approve(CODEX_REVIEW)])
        self.assertFalse(rules(g.evaluate(p, CFG))["review"])
        p = pr(headRefName="chat/mockup-v3")
        self.assertTrue(g.evaluate(p, CFG)["passed"])

    def test_claude_branch_needs_a_codex_reviewer(self):
        p = pr(headRefName="claude/t-010-adopt", comments=[go(), approve()])
        self.assertFalse(rules(g.evaluate(p, CFG))["review"])
        p = pr(headRefName="claude/t-010-adopt", comments=[go(CODEX_REVIEW), approve(CODEX_REVIEW)])
        self.assertTrue(rules(g.evaluate(p, CFG))["review"])

    def test_unknown_branch_prefix_is_refused(self):
        ev = g.evaluate(pr(headRefName="feature/x"), CFG)
        self.assertFalse(rules(ev)["author"])
        self.assertFalse(ev["passed"])

    def test_unknown_signer_and_unsigned_approval_are_ignored(self):
        p = pr(comments=[go(), approve(f"Gemini {SEP} review")])
        self.assertFalse(rules(g.evaluate(p, CFG))["review"])
        p = pr(comments=[go(), comment(None, "Approved at `aaaaaaa`", "2026-10-04T10:00:00Z")])
        self.assertFalse(rules(g.evaluate(p, CFG))["review"])

    def test_not_approved_cancels_an_earlier_approval_by_the_same_chat(self):
        p = pr(comments=[go(), approve(),
                         comment(REVIEW, "Not approved at `aaaaaaa`. Found a problem.", "2026-10-04T10:30:00Z")])
        self.assertFalse(rules(g.evaluate(p, CFG))["review"])

    def test_not_approved_by_another_reviewer_blocks(self):
        p = pr(comments=[go(), approve(),
                         comment(f"Claudio {SEP} IT", "Not approved at `aaaaaaa`", "2026-10-04T10:05:00Z")])
        self.assertFalse(rules(g.evaluate(p, CFG))["review"])

    def test_not_approved_at_an_older_commit_does_not_block_others(self):
        p = pr(comments=[go(), approve(),
                         comment(f"Claudio {SEP} IT", "Not approved at `bbbbbbb`", "2026-10-04T08:00:00Z")])
        self.assertTrue(rules(g.evaluate(p, CFG))["review"])

    def test_approval_text_inside_a_review_body_counts(self):
        p = pr(comments=[go()], reviews=[{"body": f"**{REVIEW}:** Approved at `aaaaaaa`",
                                          "submittedAt": "2026-10-04T10:00:00Z", "state": "COMMENTED"}])
        self.assertTrue(rules(g.evaluate(p, CFG))["review"])

    def test_hidden_comment_is_ignored(self):
        p = pr(comments=[go(), comment(REVIEW, "Approved at `aaaaaaa`", "2026-10-04T10:00:00Z", minimized=True)])
        self.assertFalse(rules(g.evaluate(p, CFG))["review"])


class SameVendorOptionTests(unittest.TestCase):
    """The owner may let a Codex reviewer chat approve Codex work at chosen tiers."""
    CFG2 = dict(CFG, same_vendor_ok_tiers=[2])

    def test_off_by_default(self):
        p = pr(comments=[go(CODEX_REVIEW), approve(CODEX_REVIEW)])
        self.assertFalse(g.evaluate(p, CFG)["passed"])

    def test_listed_reviewer_chat_counts_at_the_chosen_tier(self):
        p = pr(comments=[go(CODEX_REVIEW), approve(CODEX_REVIEW)])
        ev = g.evaluate(p, self.CFG2)
        self.assertTrue(ev["passed"], g.format_report(ev, 7))

    def test_a_task_chat_of_the_same_vendor_never_counts(self):
        p = pr(comments=[go(AUTHOR), approve(AUTHOR)])
        self.assertFalse(rules(g.evaluate(p, self.CFG2))["review"])

    def test_tier3_still_needs_the_other_vendor(self):
        p = pr(labels=[{"name": "tier-3"}], comments=[go(CODEX_REVIEW), approve(CODEX_REVIEW),
                                                      comment("Carlos", "Approved at `aaaaaaa`", "2026-10-04T12:00:00Z")])
        self.assertFalse(rules(g.evaluate(p, self.CFG2))["review"])


class PlanTests(unittest.TestCase):
    def test_tier2_needs_a_plan_go(self):
        p = pr(comments=[approve()])
        self.assertFalse(rules(g.evaluate(p, CFG))["plan"])

    def test_go_from_the_same_vendor_does_not_count(self):
        p = pr(comments=[go(CODEX_REVIEW), approve()])
        self.assertFalse(rules(g.evaluate(p, CFG))["plan"])

    def test_go_from_carlos_counts(self):
        p = pr(comments=[go("Carlos"), approve()])
        self.assertTrue(rules(g.evaluate(p, CFG))["plan"])

    def test_the_word_goal_is_not_go(self):
        p = pr(comments=[comment(REVIEW, "goal tests look fine", "2026-10-04T09:00:00Z"), approve()])
        self.assertFalse(rules(g.evaluate(p, CFG))["plan"])

    def test_change_x_first_is_not_go(self):
        p = pr(comments=[comment(REVIEW, "change the tier rule first", "2026-10-04T09:00:00Z"), approve()])
        self.assertFalse(rules(g.evaluate(p, CFG))["plan"])


class TierTests(unittest.TestCase):
    def test_tier1_docs_needs_no_reviewer_and_no_plan(self):
        p = pr(labels=[{"name": "tier-1"}], files=[{"path": "docs/agent-handoff.md"}],
               comments=[], body="")
        ev = g.evaluate(p, CFG)
        self.assertTrue(ev["passed"], g.format_report(ev, 7))
        self.assertEqual(ev["tier"], 1)

    def test_tier1_touching_code_is_raised_to_2(self):
        p = pr(labels=[{"name": "tier-1"}], files=[{"path": "backend/tiers.py"}])
        self.assertEqual(g.evaluate(p, CFG)["tier"], 2)
        p = pr(labels=[{"name": "tier-1"}], files=[{"path": "backend/tiers.py"}], comments=[])
        self.assertFalse(g.evaluate(p, CFG)["passed"])

    def test_tier1_touching_tests_is_raised_to_2(self):
        p = pr(labels=[{"name": "tier-1"}], files=[{"path": "tests/test_goal.py"}])
        self.assertEqual(g.evaluate(p, CFG)["tier"], 2)

    def test_protected_paths_raise_to_tier3(self):
        for path in ("AGENTS.md", ".github/workflows/python-checks.yml", ".githooks/pre-push",
                     ".claude/settings.json", ".claude/agents/reviewer.md",
                     "tools/gate/po_gate.py", "backend/providers.py", "reader.py", "alembic/versions/001.py",
                     "backend/alembic/env.py"):
            p = pr(files=[{"path": path}], labels=[{"name": "tier-1"}])
            self.assertEqual(g.evaluate(p, CFG)["tier"], 3, path)

    def test_tier3_needs_carlos_to_approve_the_head(self):
        p = pr(labels=[{"name": "tier-3"}])
        ev = g.evaluate(p, CFG)
        self.assertFalse(rules(ev)["owner"])
        self.assertFalse(ev["passed"])
        p["comments"].append(comment("Carlos", "Approved at `bbbbbbb`", "2026-10-04T11:00:00Z"))
        self.assertFalse(rules(g.evaluate(p, CFG))["owner"])
        p["comments"].append(comment("Carlos", "Approved at `aaaaaaa`", "2026-10-04T12:00:00Z"))
        ev = g.evaluate(p, CFG)
        self.assertTrue(ev["passed"], g.format_report(ev, 7))
        self.assertTrue(ev["owner_approved"])

    def test_carlos_alone_is_not_the_independent_reviewer(self):
        p = pr(labels=[{"name": "tier-3"}],
               comments=[go("Carlos"), comment("Carlos", "Approved at `aaaaaaa`", "2026-10-04T12:00:00Z")])
        self.assertFalse(rules(g.evaluate(p, CFG))["review"])

    def test_tier4_is_never_mergeable(self):
        ev = g.evaluate(pr(labels=[{"name": "tier-4"}]), CFG)
        self.assertFalse(ev["passed"])
        self.assertFalse(rules(ev)["tier"])

    def test_tier_label_required_exactly_once(self):
        self.assertFalse(rules(g.evaluate(pr(labels=[]), CFG))["tier"])
        two = pr(labels=[{"name": "tier-1"}, {"name": "tier-2"}])
        self.assertFalse(rules(g.evaluate(two, CFG))["tier"])


class HoldTests(unittest.TestCase):
    def test_hold_comment_blocks(self):
        p = pr()
        p["comments"].append(comment("Carlos", "hold", "2026-10-04T10:30:00Z"))
        ev = g.evaluate(p, CFG)
        self.assertFalse(rules(ev)["hold"])
        self.assertFalse(ev["passed"])

    def test_unsigned_hold_blocks(self):
        p = pr()
        p["comments"].append(comment(None, "Hold", "2026-10-04T10:30:00Z"))
        self.assertFalse(rules(g.evaluate(p, CFG))["hold"])

    def test_carlos_unhold_lifts_it(self):
        p = pr()
        p["comments"] += [comment("Carlos", "hold", "2026-10-04T10:30:00Z"),
                          comment("Carlos", "unhold", "2026-10-04T11:30:00Z")]
        self.assertTrue(rules(g.evaluate(p, CFG))["hold"])

    def test_an_agent_cannot_lift_a_hold(self):
        p = pr()
        p["comments"] += [comment("Carlos", "hold", "2026-10-04T10:30:00Z"),
                          comment(AUTHOR, "unhold", "2026-10-04T11:30:00Z")]
        self.assertFalse(rules(g.evaluate(p, CFG))["hold"])

    def test_hold_label_blocks(self):
        p = pr(labels=[{"name": "tier-2"}, {"name": "hold"}])
        self.assertFalse(rules(g.evaluate(p, CFG))["hold"])

    def test_the_word_holding_is_not_a_hold(self):
        p = pr()
        p["comments"].append(comment(AUTHOR, "holding the line on scope", "2026-10-04T10:30:00Z"))
        self.assertTrue(rules(g.evaluate(p, CFG))["hold"])


class OtherRuleTests(unittest.TestCase):
    def test_failed_check_blocks(self):
        p = pr()
        p["statusCheckRollup"][0]["conclusion"] = "FAILURE"
        r = rules(g.evaluate(p, CFG))
        self.assertFalse(r["check:tests"])
        self.assertTrue(r["check:scan"])

    def test_missing_check_blocks(self):
        r = rules(g.evaluate(pr(statusCheckRollup=[]), CFG))
        self.assertFalse(r["check:tests"])
        self.assertFalse(r["check:scan"])

    def test_rerun_with_a_failed_entry_blocks(self):
        p = pr()
        p["statusCheckRollup"].append({"__typename": "CheckRun", "name": "tests", "conclusion": "FAILURE"})
        self.assertFalse(rules(g.evaluate(p, CFG))["check:tests"])

    def test_status_context_form_is_read(self):
        cfg = dict(CFG, required_checks=["ci/legacy"])
        p = pr(statusCheckRollup=[{"__typename": "StatusContext", "context": "ci/legacy", "state": "SUCCESS"}])
        self.assertTrue(rules(g.evaluate(p, cfg))["check:ci/legacy"])

    def test_forbidden_files_block(self):
        for path in ("docs/order.pdf", "scan.png", "models/x.gguf", ".env", "a/b/.env.local",
                     "data/orders.csv", "output/run1.json", "x/y.sqlite3"):
            ev = g.evaluate(pr(files=[{"path": path}]), CFG)
            self.assertFalse(rules(ev)["files"], path)

    def test_env_example_is_allowed(self):
        for path in (".env.example", "backend/.env.backend.example"):
            self.assertTrue(rules(g.evaluate(pr(files=[{"path": path}]), CFG))["files"], path)

    def test_hundred_files_cannot_be_verified(self):
        p = pr(files=[{"path": f"backend/f{i}.py"} for i in range(100)])
        self.assertFalse(rules(g.evaluate(p, CFG))["files"])

    def test_hundred_comments_cannot_be_read(self):
        p = pr(comments=[go(), approve()] + [comment(AUTHOR, "note", f"2026-10-04T12:{i % 60:02d}:00Z") for i in range(98)])
        self.assertFalse(rules(g.evaluate(p, CFG))["comments"])

    def test_missing_evidence_heading_blocks_at_tier2(self):
        r = rules(g.evaluate(pr(body="## Plan\nx\n## Cost\ny\n"), CFG))
        self.assertFalse(r["evidence:Evidence"])
        self.assertTrue(r["evidence:Plan"])

    def test_draft_wrong_base_and_merged_block(self):
        self.assertFalse(rules(g.evaluate(pr(isDraft=True), CFG))["state"])
        self.assertFalse(rules(g.evaluate(pr(baseRefName="dev"), CFG))["state"])
        self.assertFalse(rules(g.evaluate(pr(state="MERGED"), CFG))["state"])

    def test_report_carries_the_shared_account_note(self):
        text = g.format_report(g.evaluate(pr(), CFG), 7)
        self.assertIn("shared GitHub account", text)
        self.assertIn("RESULT: PASS", text)


class MergeTests(unittest.TestCase):
    def run_merge(self, gh, merged_as=AUTHOR, **kw):
        lines = []
        code = g.cmd_merge(gh, CFG, 7, merged_as, out=lines.append, **kw)
        return code, "\n".join(lines)

    def test_passing_pr_is_merged_pinned_to_head_with_a_record(self):
        gh = FakeGH(pr())
        code, out = self.run_merge(gh)
        self.assertEqual(code, 0, out)
        call = gh.merged()[0]
        self.assertEqual(call[call.index("--match-head-commit") + 1], HEAD)
        self.assertIn("--squash", call)
        body = call[call.index("--body") + 1]
        self.assertIn(f"Gate-Record: pass tier=2 head={HEAD}", body)
        self.assertIn(f"by={AUTHOR}", body)
        self.assertIn(f"reviewers={REVIEW}", body)
        self.assertTrue(g.TRAILER.search(body))

    def test_repo_is_detected_when_not_configured(self):
        gh = FakeGH(pr())
        self.run_merge(gh)
        call = gh.merged()[0]
        self.assertEqual(call[call.index("--repo") + 1], "CarlitosRed/advance-po-reader")

    def test_failing_pr_is_not_merged(self):
        p = pr()
        p["statusCheckRollup"][0]["conclusion"] = "FAILURE"
        gh = FakeGH(p)
        code, _ = self.run_merge(gh)
        self.assertEqual(code, 1)
        self.assertEqual(gh.merged(), [])

    def test_held_pr_is_not_merged(self):
        p = pr()
        p["comments"].append(comment("Carlos", "hold", "2026-10-04T10:30:00Z"))
        gh = FakeGH(p)
        self.assertEqual(self.run_merge(gh)[0], 1)
        self.assertEqual(gh.merged(), [])

    def test_the_other_vendor_cannot_merge(self):
        gh = FakeGH(pr())
        with self.assertRaises(g.GateError):
            self.run_merge(gh, merged_as=REVIEW)
        self.assertEqual(gh.merged(), [])

    def test_unknown_or_malformed_merger_is_refused(self):
        for who in ("", "Gemini · x", "Codex", "just me"):
            with self.assertRaises(g.GateError, msg=who):
                self.run_merge(FakeGH(pr()), merged_as=who)

    def test_another_chat_of_the_author_vendor_may_merge(self):
        gh = FakeGH(pr())
        self.assertEqual(self.run_merge(gh, merged_as=f"Chat {SEP} design")[0], 0)

    def test_carlos_may_merge(self):
        gh = FakeGH(pr())
        self.assertEqual(self.run_merge(gh, merged_as="Carlos")[0], 0)

    def test_tier3_merges_only_with_carlos_approval_and_records_it(self):
        p = pr(labels=[{"name": "tier-3"}])
        gh = FakeGH(p)
        self.assertEqual(self.run_merge(gh)[0], 1)
        self.assertEqual(gh.merged(), [])
        p["comments"].append(comment("Carlos", "Approved at `aaaaaaa`", "2026-10-04T12:00:00Z"))
        code, out = self.run_merge(gh)
        self.assertEqual(code, 0, out)
        self.assertIn("owner=yes", gh.merged()[0][gh.merged()[0].index("--body") + 1])

    def test_dry_run_prints_and_does_not_merge(self):
        gh = FakeGH(pr())
        code, out = self.run_merge(gh, dry_run=True)
        self.assertEqual(code, 0)
        self.assertIn("DRY RUN", out)
        self.assertIn("--match-head-commit", out)
        self.assertEqual(gh.merged(), [])


def git_repo():
    d = tempfile.mkdtemp()

    def git(*a):
        return subprocess.run(["git", *a], cwd=d, capture_output=True, text=True, check=True).stdout.strip()
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "Tester")
    return d, git


def write(d, name, text):
    with open(os.path.join(d, name), "w") as fh:
        fh.write(text)


def git_runner(d):
    return lambda args, binary=False: g.run_git(args, cwd=d, binary=binary)


class AuditTests(unittest.TestCase):
    def first(self):
        d, git = git_repo()
        write(d, "a.txt", "1")
        git("add", ".")
        git("commit", "-q", "-m", "first")
        return d, git, git("rev-parse", "HEAD")

    def audit(self, d, rng, cfg=CFG):
        lines = []
        code = g.cmd_audit(git_runner(d), cfg, rng, out=lines.append)
        return code, "\n".join(lines)

    def test_flags_commit_without_a_gate_record(self):
        d, git, base = self.first()
        write(d, "a.txt", "2")
        git("commit", "-qam", "good change (#1)", "-m", f"Gate-Record: pass tier=2 head={'c' * 40} reviewers=x owner=no by=y")
        write(d, "a.txt", "3")
        git("commit", "-qam", "sneaky direct push")
        code, text = self.audit(d, f"{base}..{git('rev-parse', 'HEAD')}")
        self.assertEqual(code, 1)
        self.assertIn("sneaky direct push", text)
        self.assertNotIn("good change", text)

    def test_clean_range_passes(self):
        d, git, base = self.first()
        write(d, "a.txt", "2")
        git("commit", "-qam", "ok (#2)", "-m", f"Gate-Record: pass tier=1 head={'d' * 40} reviewers=none owner=no by=y")
        self.assertEqual(self.audit(d, f"{base}..{git('rev-parse', 'HEAD')}")[0], 0)

    def test_tier4_record_is_not_accepted(self):
        d, git, base = self.first()
        write(d, "a.txt", "2")
        git("commit", "-qam", "forged", "-m", f"Gate-Record: pass tier=4 head={'e' * 40}")
        self.assertEqual(self.audit(d, f"{base}..{git('rev-parse', 'HEAD')}")[0], 1)

    def test_tier3_record_without_owner_is_flagged_and_with_owner_is_listed(self):
        d, git, base = self.first()
        write(d, "a.txt", "2")
        git("commit", "-qam", "risky A", "-m", f"Gate-Record: pass tier=3 head={'e' * 40} reviewers=x owner=no by=y")
        code, text = self.audit(d, f"{base}..{git('rev-parse', 'HEAD')}")
        self.assertEqual(code, 1)
        self.assertIn("without owner approval", text)
        mid = git("rev-parse", "HEAD")
        write(d, "a.txt", "3")
        git("commit", "-qam", "risky B", "-m", f"Gate-Record: pass tier=3 head={'f' * 40} reviewers=x owner=yes by=y")
        code, text = self.audit(d, f"{mid}..{git('rev-parse', 'HEAD')}")
        self.assertEqual(code, 0)
        self.assertIn("Tier 3 merges in this range", text)
        self.assertIn("risky B", text)

    def test_bootstrap_record_is_accepted(self):
        d, git, base = self.first()
        write(d, "a.txt", "2")
        git("commit", "-qam", "adopt the gate (#10)", "-m",
            f"Gate-Record: pass tier=3 head={'a' * 40} reviewers=Codex PR review owner=yes by=bootstrap")
        self.assertEqual(self.audit(d, f"{base}..{git('rev-parse', 'HEAD')}")[0], 0)

    def test_new_branch_push_audits_only_the_tip(self):
        d, git, base = self.first()
        code, text = self.audit(d, f"{'0' * 40}..{base}")
        self.assertEqual(code, 1)
        self.assertEqual(len([l for l in text.split("\n") if l.startswith("  ")]), 1)

    def test_exempt_commit_is_skipped(self):
        d, git, base = self.first()
        write(d, "a.txt", "2")
        git("commit", "-qam", "adoption commit")
        head = git("rev-parse", "HEAD")
        self.assertEqual(self.audit(d, f"{base}..{head}", dict(CFG, audit_exempt=[head]))[0], 0)


class ScanTests(unittest.TestCase):
    def repo_with(self, files):
        d, git = git_repo()
        for name, data in files.items():
            path = os.path.join(d, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(data)
        git("add", "-A")
        return d, git

    def scan(self, d, cfg=CFG, **kw):
        lines = []
        code = g.cmd_scan(git_runner(d), cfg, out=lines.append, **kw)
        return code, "\n".join(lines)

    def test_clean_repo_passes(self):
        d, git = self.repo_with({"src/a.py": b"print('hi')\n", "README.md": b"# hi\n", ".env.example": b"KEY=\n"})
        git("commit", "-q", "-m", "x")
        self.assertEqual(self.scan(d)[0], 0)

    def test_pdf_renamed_to_txt_is_caught_by_content(self):
        d, git = self.repo_with({"notes/order.txt": b"%PDF-1.4\n%fake body\n"})
        git("commit", "-q", "-m", "x")
        code, out = self.scan(d)
        self.assertEqual(code, 1)
        self.assertIn("content is a PDF", out)

    def test_png_and_gguf_by_content(self):
        d, git = self.repo_with({"a.dat": b"\x89PNG\r\n\x1a\nrest", "b.dat": b"GGUF\x03\x00\x00\x00"})
        git("commit", "-q", "-m", "x")
        out = self.scan(d)[1]
        self.assertIn("PNG image", out)
        self.assertIn("GGUF model file", out)

    def test_data_folder_is_forbidden_by_name(self):
        d, git = self.repo_with({"data/orders.csv": b"a,b\n"})
        git("commit", "-q", "-m", "x")
        self.assertIn("forbidden file name", self.scan(d)[1])

    def test_secret_in_text_is_caught_and_never_printed(self):
        fake = "sk-" + "Z" * 24
        d, git = self.repo_with({"cfg.py": f"KEY = '{fake}'\n".encode()})
        git("commit", "-q", "-m", "x")
        code, out = self.scan(d)
        self.assertEqual(code, 1)
        self.assertIn("API key", out)
        self.assertNotIn(fake, out)

    def test_secret_in_an_allowed_file_is_still_caught(self):
        fake = "sk-" + "Y" * 24
        d, git = self.repo_with({".env.example": f"OPENAI_API_KEY={fake}\n".encode()})
        git("commit", "-q", "-m", "x")
        self.assertEqual(self.scan(d)[0], 1)

    def test_word_ending_in_sk_is_not_a_secret(self):
        d, git = self.repo_with({"a.md": b"the disk-" + b"x" * 30 + b" is fine\n"})
        git("commit", "-q", "-m", "x")
        self.assertEqual(self.scan(d)[0], 0)

    def test_private_key_header_is_caught(self):
        d, git = self.repo_with({"k.txt": b"-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n"})
        git("commit", "-q", "-m", "x")
        self.assertEqual(self.scan(d)[0], 1)

    def test_staged_mode_sees_only_the_index(self):
        d, git = self.repo_with({"ok.py": b"x = 1\n"})
        git("commit", "-q", "-m", "x")
        with open(os.path.join(d, "bad.pdf"), "wb") as fh:
            fh.write(b"%PDF-1.7")
        git("add", "bad.pdf")
        code, out = self.scan(d, staged=True)
        self.assertEqual(code, 1)
        self.assertIn("bad.pdf", out)

    def test_range_mode_checks_files_changed_in_range(self):
        d, git = self.repo_with({"ok.py": b"x = 1\n"})
        git("commit", "-q", "-m", "x")
        a = git("rev-parse", "HEAD")
        with open(os.path.join(d, "n.bin"), "wb") as fh:
            fh.write(b"%PDF-1.7")
        git("add", "-A")
        git("commit", "-q", "-m", "y")
        b = git("rev-parse", "HEAD")
        code, out = self.scan(d, rng=f"{a}..{b}")
        self.assertEqual(code, 1)
        self.assertIn("n.bin", out)

    def test_allow_list_permits_a_fictional_fixture(self):
        d, git = self.repo_with({"tests/fixtures/fictional/po1.pdf": b"%PDF-1.4 fictional"})
        git("commit", "-q", "-m", "x")
        cfg = dict(CFG, scan_allow=["tests/fixtures/fictional/*"])
        self.assertEqual(self.scan(d, cfg=cfg)[0], 0)

    def test_large_file_is_flagged(self):
        d, git = self.repo_with({"big.dat": b"a" * (2 * 1024 * 1024)})
        git("commit", "-q", "-m", "x")
        self.assertIn("larger than", self.scan(d, cfg=dict(CFG, max_file_mb=1))[1])


class PathsTests(unittest.TestCase):
    def test_counts_and_warns_about_empty_globs(self):
        d, git = git_repo()
        os.makedirs(os.path.join(d, ".github", "workflows"))
        write(d, "AGENTS.md", "x")
        write(d, ".github/workflows/ci.yml", "x")
        git("add", "-A")
        git("commit", "-q", "-m", "x")
        lines = []
        g.cmd_paths(git_runner(d), dict(CFG, protected_paths=["AGENTS.md", ".github/*", "nothing/*"]), out=lines.append)
        text = "\n".join(lines)
        self.assertIn("   1  AGENTS.md", text)
        self.assertIn("   1  .github/*", text)
        self.assertIn("   0  nothing/*", text)
        self.assertIn("match no file today", text)


class ConfigTests(unittest.TestCase):
    def test_missing_file_gives_the_defaults(self):
        cfg = g.load_config(os.path.join(tempfile.mkdtemp(), "nope.json"))
        self.assertEqual(cfg["base"], "main")
        self.assertEqual(cfg["approvals_required"]["1"], 0)

    def test_file_overrides_defaults(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"base": "trunk"}, fh)
        cfg = g.load_config(fh.name)
        self.assertEqual(cfg["base"], "trunk")
        self.assertIn("*.pdf", cfg["forbidden_globs"])

    def test_default_config_sits_next_to_the_script(self):
        self.assertTrue(g.default_config_path().endswith("gate.json"))
        self.assertEqual(os.path.dirname(g.default_config_path()), os.path.dirname(os.path.abspath(g.__file__)))


if __name__ == "__main__":
    unittest.main()
