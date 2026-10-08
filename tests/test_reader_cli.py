import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import reader


class ReaderCliTests(unittest.TestCase):
    def test_analyze_uses_native_engine_even_when_api_key_is_set(self):
        class ExistingCatalog:
            @staticmethod
            def exists():
                return True

        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "order.pdf"
            source.write_bytes(b"%PDF-1.7")
            with patch.object(reader, "DB", ExistingCatalog), \
                 patch.object(reader, "create", return_value={"filename": "order.pdf", "status": "review_needed"}) as create, \
                 patch.object(sys, "argv", ["reader.py", "analyze", str(source)]), \
                 patch.dict(os.environ, {"OPENAI_API_KEY": "must-not-be-used"}, clear=False), \
                 contextlib.redirect_stdout(io.StringIO()):
                reader.main()
            create.assert_called_once_with(b"%PDF-1.7", "order.pdf", render=False)

    def test_analyze_help_says_vision_is_unavailable(self):
        with patch.object(sys, "argv", ["reader.py", "analyze", "--help"]), \
             contextlib.redirect_stdout(io.StringIO()) as output, self.assertRaises(SystemExit):
            reader.main()
        self.assertIn("Vision analysis is unavailable", output.getvalue())
        self.assertIn("native PDF text engine only", output.getvalue())

    def test_provider_flag_is_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "order.pdf"
            source.write_bytes(b"%PDF-1.7")
            with patch.object(sys, "argv", ["reader.py", "analyze", str(source), "--provider", "openai"]), \
                 contextlib.redirect_stderr(io.StringIO()) as error, self.assertRaises(SystemExit) as raised:
                reader.main()
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("unrecognized arguments: --provider openai", error.getvalue())


if __name__ == "__main__":
    unittest.main()
