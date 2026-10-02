"""Run the preserved private source-integrity checks on this machine."""
import runpy
from pathlib import Path

root = Path(__file__).resolve().parent
source = root / 'data/private-tests/verify_samples.py'
if not source.is_file():
    raise SystemExit('Private verification fixtures unavailable. See docs/agent-handoff.md.')
# The legacy verifier resolves data/output beside its __file__; execute it at this root.
exec(compile(source.read_text(encoding='utf-8'), str(root / 'verify_samples.py'), 'exec'),
     {'__name__': '__main__', '__file__': str(root / 'verify_samples.py')})
