"""Three-tab review page: pure client-side helpers (tabs, counts, crop geometry), checked with Node only."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.goal
ROOT = Path(__file__).resolve().parents[2]


def test_goal_9_three_tab_helpers_assign_every_line_once_and_crop_inside_the_page():
    node = os.environ.get("GOAL_NODE_BIN") or shutil.which("node")
    if not node:
        pytest.skip("BLOCKED: Node is needed for the three-tab helper check")
    completed = subprocess.run([node, str(ROOT / "tests/goal/tabs.cjs")], capture_output=True, text=True, timeout=30,
                               **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "three-tab helpers passed" in completed.stdout
