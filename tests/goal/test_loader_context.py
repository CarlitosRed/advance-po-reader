"""R01 remainder: slow loaders never pair one document's source with another document's run (Node only).

Each check drives the production loader functions of web/local-reader (app.js, workflow.js) with deferred fake
responses. The earlier decision-race checks stay in test_review_context.py.
"""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.goal
ROOT = Path(__file__).resolve().parents[2]
CHECKS = [
    "processSavedRun_final_read_never_pairs_B_with_run_A",
    "openSource_slow_run_list_never_pairs_B_with_run_A",
    "openSource_every_slow_response_is_dropped_when_stale",
    "startUpload_slow_create_run_never_pairs_B_with_run_A",
    "startUpload_synthetic_steps_stop_when_stale",
    "startUpload_stale_failure_does_not_repaint_over_B",
    "startSample_keeps_its_catalog_across_the_byte_fetch",
    "startSample_is_dropped_when_another_document_opens_first",
    "library_download_is_dropped_when_another_document_opens_first",
    "restoreRoute_summary_is_not_painted_for_a_dropped_load",
    "openSource_without_navigation_installs_a_consistent_pair",
    "startUpload_without_navigation_installs_a_consistent_pair",
    "startSample_without_navigation_processes_the_sample_run",
    "processSavedRun_without_navigation_refreshes_the_run",
    "error_text_explains_product_exists_outside_catalog_pool",
]


def _node():
    node = os.environ.get("GOAL_NODE_BIN") or shutil.which("node")
    if not node:
        pytest.skip("BLOCKED: Node is needed for the loader-context check")
    return node


@pytest.mark.parametrize("check", CHECKS)
def test_loader_check(check):
    completed = subprocess.run([_node(), str(ROOT / "tests/goal/loader-context.cjs"), check], capture_output=True, text=True,
                               timeout=30, **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "PASS " + check in completed.stdout


def test_every_loader_check_is_listed():
    source = (ROOT / "tests/goal/loader-context.cjs").read_text(encoding="utf8")
    import re
    defined = re.findall(r"^  async (\w+)\(\) \{", source, flags=re.M)
    assert sorted(defined) == sorted(CHECKS)


def test_no_source_or_run_is_assigned_straight_from_an_await():
    # The pattern behind the mixed pairs: `state.run = await api(...)` installs a response nobody re-checked.
    import re
    for name in ("app.js", "workflow.js"):
        text = (ROOT / "web/local-reader" / name).read_text(encoding="utf8")
        assert not re.search(r"state\.(source|run)\s*=\s*await\b", text), name
