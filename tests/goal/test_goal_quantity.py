"""Quantity display standardization: a pure client-side helper, checked with Node only."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.goal
ROOT = Path(__file__).resolve().parents[2]


def test_goal_9_quantity_display_is_standardized_without_guessing():
    node = os.environ.get("GOAL_NODE_BIN") or shutil.which("node")
    if not node:
        pytest.skip("BLOCKED: Node is needed for the quantity helper check")
    completed = subprocess.run([node, str(ROOT / "tests/goal/quantity.cjs")], capture_output=True, text=True, timeout=30,
                               **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "quantity standardization passed" in completed.stdout
