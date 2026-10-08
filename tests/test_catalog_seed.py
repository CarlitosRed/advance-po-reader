"""Fresh-clone CLI behavior using fictional catalog data only."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CatalogSeedTests(unittest.TestCase):
    def test_missing_private_seed_exits_plainly_and_present_seed_still_builds(self):
        with tempfile.TemporaryDirectory() as scratch:
            project = Path(scratch)
            shutil.copy2(ROOT / "reader.py", project / "reader.py")
            (project / "po_reader").mkdir()
            for source in (ROOT / "po_reader").glob("*.py"):
                shutil.copy2(source, project / "po_reader" / source.name)
            environment = {
                key: value for key, value in os.environ.items()
                if key != "OPENAI_API_KEY" and not key.startswith(("PO_BACKEND_", "PG"))
            }
            command = [sys.executable, "reader.py", "catalog"]
            missing = subprocess.run(command, cwd=project, env=environment,
                                     capture_output=True, text=True, timeout=30)
            self.assertEqual(missing.returncode, 1)
            self.assertEqual(missing.stdout, "")
            self.assertEqual(len(missing.stderr.splitlines()), 1)
            self.assertIn("private", missing.stderr)
            self.assertIn("not in Git", missing.stderr)
            self.assertIn("README.md: Run the free demo on Windows", missing.stderr)
            self.assertNotIn("Traceback", missing.stderr)
            self.assertFalse((project / "data").exists())

            (project / "data").mkdir()
            product = {"id": "fict-roy-01", "name": "Fictional demo product",
                       "variants": ["Fictional demo product"], "provenance": []}
            (project / "data" / "catalog-seed.json").write_text(
                json.dumps({"products": [product]}), encoding="utf-8")
            present = subprocess.run(command, cwd=project, env=environment,
                                     capture_output=True, text=True, timeout=30)
            self.assertEqual(present.returncode, 0, present.stderr)
            self.assertEqual(present.stderr, "")
            self.assertEqual(json.loads(present.stdout), {
                "authority": "sample_catalog",
                "products": [{**product, "id": "FICT-ROY-01", "authority": "sample_catalog"}],
            })
            self.assertTrue((project / "data" / "catalog.sqlite3").is_file())


if __name__ == "__main__":
    unittest.main()
