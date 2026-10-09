"""R01: a click for one document must not approve, bind or process another after navigation (Node only)."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.goal
ROOT = Path(__file__).resolve().parents[2]


def test_review_clicks_stay_with_the_document_they_were_made_for():
    node = os.environ.get("GOAL_NODE_BIN") or shutil.which("node")
    if not node:
        pytest.skip("BLOCKED: Node is needed for the review-context check")
    completed = subprocess.run([node, str(ROOT / "tests/goal/review-context.cjs")], capture_output=True, text=True,
                               timeout=30, **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "review context passed" in completed.stdout
    assert "authorize block absent" not in completed.stdout
