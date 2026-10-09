"""Render the goal scorecard from what THIS pytest execution recorded.

Every pass/fail sentence is derived from the recorded results. Prose written for an
earlier change is kept only under an explicitly historical heading.
"""
from datetime import datetime, timezone
import os

STATUSES = ("passed", "xfail", "blocked", "failed")
MIGRATION_TEST = "test_goal_6_new_migration_upgrade_downgrade_upgrade"


def _counts(records, goals=None):
    return {status: sum(r["status"] == status and (goals is None or r["goal"] in goals) for r in records)
            for status in STATUSES}


def render_scorecard(records, exitstatus, now=None, execution=None):
    now = now or datetime.now(timezone.utc)
    execution = execution if execution is not None else os.environ.get("GOAL_TEST_EXECUTION", "local isolated run")
    total = _counts(records)
    missing = [goal for goal in range(1, 11) if not any(r["goal"] == goal for r in records)]
    if total["failed"]:
        verdict = "FAIL: at least one goal test failed in this run."
    elif exitstatus != 0 or not records:
        verdict = "NOT A PASS: pytest exit status " + str(exitstatus) + " or no goal test was recorded."
    elif missing:
        verdict = ("PARTIAL: no failure was recorded, but goals " + ", ".join(map(str, missing)) +
                   " had no test in this run (a filtered or incomplete selection).")
    else:
        verdict = "No failure recorded; every goal had at least one test in this run."
    lines = [f"# Goal acceptance scorecard — generated {now:%B} {now.day}, {now.year} (UTC)", "",
             "Execution: " + execution + ". "
             "Suite: `python -m pytest -m goal`. Skips count as blocked; strict xfails are separate.", "",
             f"**Verdict for this run: {verdict}** Pytest exit status: {exitstatus}. Every number below was "
             "recorded by this execution; sentences under a Historical heading were not.", "",
             "Measured with generated fictional PDFs/PNG/JPG, fixed JSON from an injected fake "
             "provider, actual upload/processing/catalog/review HTTP routes, and a disposable "
             "PostgreSQL cluster. No model accuracy or real-document performance is measured.", "",
             "| Goal | Passed | Xfail | Blocked | Failed |", "| --- | ---: | ---: | ---: | ---: |"]
    for goal in range(1, 11):
        counts = _counts(records, {goal})
        lines.append(f"| {goal} | {counts['passed']} | {counts['xfail']} | "
                     f"{counts['blocked']} | {counts['failed']} |")
    lines += ["", f"Total: {total['passed']} passed, {total['xfail']} xfail, "
              f"{total['blocked']} blocked, {total['failed']} failed. Pytest exit status: {exitstatus}.", ""]
    if missing:
        lines += ["Goals with no recorded test in this run: " + ", ".join(map(str, missing)) + ".", ""]
    mid = _counts(records, {4, 5, 6})
    migration = [r for r in records if r["test"].endswith(MIGRATION_TEST)]
    migration_text = (f"migration upgrade/downgrade/upgrade test: {migration[0]['status']}" if migration
                      else "migration upgrade/downgrade/upgrade test: not run in this selection")
    lines += ["## Goals 4-6 in this run", "",
              f"{mid['passed']} passed, {mid['xfail']} xfail, {mid['blocked']} blocked, {mid['failed']} failed; "
              + migration_text + ".", "",
              ("Browser check: passed against the real review controls and test-owned API."
               if any(r["status"] == "passed" and "website_three_answers" in r["test"] for r in records)
               else "Browser check: not passed in this run. CI deliberately omits browser tooling; "
                    "the resulting skip is visible as blocked goal 9, not a browser pass."), "",
              "## Expected failures", ""]
    lines += [f"- `{record['test'].split('::')[-1]}`: {record['reason']}"
              for record in records if record["status"] == "xfail"]
    lines += ["", "## Historical notes (written October 4, 2026 for PR A; NOT verified by this run)", "",
              "PR A (tiers, three answers, same-row evidence) was written against base "
              "`codex/worktree-standards` at `c06b4e9994277997e6ec8b828317cb5942e0daf6`; the original PR #5 "
              "baseline was 10 passed and 8 strict xfail. The intended behavior then: only Certain is "
              "initially preselected, every product needs explicit approval, Uncertain rows need a binding "
              "or an explicit not-a-product exclusion, and corrections require fresh approval. Read the "
              "table above, not this paragraph, for what this run proved.", ""]
    lines += ["", "## Interpretation and isolation", "",
              "Each goal has one or more separately scored clauses. A passed clause does not "
              "mean its entire goal passed. Strict xfail marks fail on unexpected success; "
              "they only catch AssertionError so harness/infrastructure errors stay visible.", "",
              "Goals 1–3 test the backend's handling of hand-authored extraction observations; "
              "the fake provider does not prove that a vision model finds or classifies rows. "
              "Goal 2 tests the backend's actual description-code retrieval. Goals 7–8 deliberately "
              "give the fake provider incorrect but schema-valid observations.", "",
              "All OPENAI_API_KEY and PO_BACKEND_* variables are removed inside the test process; "
              "Settings uses `_env_file=None`. Dotenv file opens, built-in provider extraction and "
              "external HTTP transports are guarded. No `.env` file or customer document is opened. "
              "Application configuration and storage path roots are redirected only in the test "
              "harness, so repository `data/` and `output/` stay untouched. Existing services "
              "and databases are not migrated or restarted. This scorecard measures the "
              "checked-out source with isolated fixtures; it is not production validation.", "",
              "Locally PostgreSQL is initialized on an available loopback port from GOAL_POSTGRES_BIN (or PATH), "
              "with an owned cluster and fresh `gate_a_test_backend_*` database. CI creates fresh databases "
              "on its ephemeral loopback PostgreSQL service, never a preexisting application database. Migrations and pg_trgm "
              "run there. Each created database is dropped at teardown; only the locally owned server is stopped. "
              "Missing binaries are reported as blocked skips; initialization or migration errors fail "
              "setup rather than becoming xfail.", ""]
    return "\n".join(lines)
