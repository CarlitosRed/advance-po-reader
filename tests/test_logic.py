"""Load private PDF regressions only from the ignored local fixture directory."""
import importlib.util
import unittest
from po_reader.catalog import ROOT

_source = ROOT / 'data/private-tests/test_logic.py'
EXPECTED = {}
if _source.is_file() and (ROOT / 'data/catalog.sqlite3').is_file():
    _spec = importlib.util.spec_from_file_location('_private_logic_regression', _source)
    _module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_module)
    EXPECTED = _module.EXPECTED
    LogicTests = _module.LogicTests
else:
    @unittest.skip('Private PDF regression fixtures are unavailable; see docs/agent-handoff.md')
    class LogicTests(unittest.TestCase):
        def test_private_sample_regressions(self):
            pass
