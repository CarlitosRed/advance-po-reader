"""Drive the production review controls against this test's real, isolated API."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
from threading import Thread

import pytest

from conftest import ROOT, PRODUCTS, process, product_row

pytestmark = pytest.mark.goal


def test_goal_9_website_three_answers_and_explicit_approval(desk, tmp_path):
    node = os.environ.get("GOAL_NODE_BIN") or shutil.which("node")
    browser = os.environ.get("GOAL_BROWSER_BIN")
    if not node or not browser:
        pytest.skip("BLOCKED: set GOAL_NODE_BIN and GOAL_BROWSER_BIN for the isolated browser check")
    rows = [product_row(1, code="GOAL-001", description=PRODUCTS[0]["description"], quantity="2"),
            product_row(2, description=PRODUCTS[1]["description"], quantity="3"),
            product_row(3, description="Synthetic accessory to classify", quantity="1", kind="unknown")]
    result = process(desk, rows)
    seed = {"workspace": desk.tenant, "catalog": {**desk.vendor, "synthetic": True},
            "catalogs": [desk.vendor], "source": result.source, "run": result.run,
            "result": result.result, "suggestions": result.suggestions, "summary": result.summary,
            "reviewer": "Fictional browser reviewer", "reason": "Checked generated fixture",
            "name": "Generated fictional browser fixture", "events": []}
    fixture = tmp_path / "browser-seed.json"
    fixture.write_text(json.dumps(seed), encoding="utf-8")
    allowed = (f"/runs/{result.run['id']}", f"/documents/{result.source['id']}/pages/", "/website/catalog")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/":
                value, mime = (ROOT / "web/local-reader/index.html").read_bytes(), "text/html"
            elif self.path in {"/web-assets/app.js", "/web-assets/workflow.js", "/web-assets/styles.css"}:
                name = self.path.rsplit("/", 1)[1]
                value = (ROOT / "web/local-reader" / name).read_bytes()
                if name == "app.js":
                    # Seed a known fictional run; do not initialize or enumerate the local corpus.
                    value = value.replace(b"\ninitialize();", b"\n")
                mime = "text/css" if name.endswith("css") else "text/javascript"
            elif self.path.startswith(allowed):
                response = desk.client.get(self.path)
                return self.send(response.status_code, response.content, response.headers.get("content-type"))
            else:
                return self.send(404, b"", "text/plain")
            self.send(200, value, mime)

        def do_POST(self):
            if self.path != f"/runs/{result.run['id']}/reviews":
                return self.send(404, b"", "text/plain")
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            response = desk.client.post(self.path, content=body, headers={"Content-Type": "application/json"})
            self.send(response.status_code, response.content, response.headers.get("content-type"))

        def send(self, code, value, mime):
            self.send_response(code)
            self.send_header("Content-Type", mime or "application/octet-stream")
            self.send_header("Content-Length", str(len(value)))
            self.end_headers()
            self.wfile.write(value)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        completed = subprocess.run([node, str(ROOT / "tests/goal/review-controls.cjs"),
            f"http://127.0.0.1:{server.server_port}", str(fixture), browser],
            capture_output=True, text=True, timeout=75,
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert "three answers and explicit approval passed" in completed.stdout
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
