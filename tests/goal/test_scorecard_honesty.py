"""R20: the generated goal scorecard may only claim what the recorded execution shows."""
import pytest

from datetime import datetime, timezone

from tests.goal_scorecard import MIGRATION_TEST, render_scorecard

pytestmark = pytest.mark.goal
NOW = datetime(2027, 3, 9, tzinfo=timezone.utc)


def record(goal, status, name=None):
    return {"goal": goal, "test": f"tests/goal/x.py::{name or f'test_goal_{goal}_case'}",
            "status": status, "reason": "gap" if status == "xfail" else ""}


def full(status_by_goal=None):
    status_by_goal = status_by_goal or {}
    return [record(g, status_by_goal.get(g, "passed")) for g in range(1, 11)]


def test_failed_goal_never_reads_as_pass():
    text = render_scorecard(full({4: "failed"}), 1, NOW)
    assert "Verdict for this run: FAIL" in text
    assert "now pass" not in text
    assert "1 failed" in text.split("## Goals 4-6 in this run")[1].split("##")[0]


def test_filtered_run_is_partial_and_names_missing_goals():
    text = render_scorecard([record(3, "passed")], 0, NOW)
    assert "PARTIAL" in text and "goals 1, 2, 4, 5, 6, 7, 8, 9, 10" in text
    assert "migration upgrade/downgrade/upgrade test: not run in this selection" in text


def test_nothing_recorded_is_not_a_pass():
    assert "NOT A PASS" in render_scorecard([], 5, NOW)


def test_migration_status_comes_from_its_own_record():
    records = full() + [record(6, "failed", MIGRATION_TEST)]
    text = render_scorecard(records, 1, NOW)
    assert "migration upgrade/downgrade/upgrade test: failed" in text


def test_date_and_provenance_are_not_frozen_in_the_past():
    text = render_scorecard(full(), 0, NOW)
    assert "March 9, 2027" in text
    head = text.split("## Historical notes")[0]
    for stale in ("October 4", "c06b4e99", "PR #5", "remain planned", "PR B", "now pass"):
        assert stale not in head
    assert "NOT verified by this run" in text


def test_clean_complete_run_is_reported_without_overclaiming():
    text = render_scorecard(full(), 0, NOW)
    assert "No failure recorded; every goal had at least one test" in text
    assert "Browser check: not passed in this run" in text
