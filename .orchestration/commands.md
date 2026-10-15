# Commands -- migrated and consolidated

Substance kept from `README.md`, `.github\workflows\*.yml` and
`tools\gate\README.md`; nothing here changes what those files say, this is
just the agent-facing consolidation in one place. If this file and one of
those ever disagree, the workflow YAML (what CI actually runs) wins.

## Tests
```powershell
# Full suite (what CI runs: python-checks.yml)
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v

# Gate A (synthetic fixtures only; gate-a-checks.yml)
& .\.venv-gate-a\Scripts\python.exe -m pytest -c pytest.gate-a.ini

# Backend goal checks (backend-goal-checks.yml, two separate pytest runs)
python -m pytest -c pytest.backend.ini --isolated-backend --basetemp=.backend-ci-runtime -q --tb=short --junitxml=backend-results.xml
python -m pytest -m goal -q --tb=short --goal-scorecard=goal-scorecard-ci.md --junitxml=goal-results.xml

# Gate tool's own tests
python -m unittest discover -s tools\gate -p "test_po_gate.py" -v
```

## Scan (required check, gate-enforced)
```powershell
python tools\gate\po_gate.py scan --rev HEAD
```

## Gate (merge, check, audit -- see ROLES.md for who runs what, when)
```powershell
python tools\gate\po_gate.py check <PR>
python tools\gate\po_gate.py merge <PR> --as "<chat name>" --dry-run
python tools\gate\po_gate.py merge <PR> --as "<chat name>"
python tools\gate\po_gate.py paths
python tools\gate\po_gate.py audit --range <old>..<new>
```

## The free demo launcher
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-poc-demo.ps1
# -Port <n> if 8020 is busy; -PostgresBin '<bin>' / -Python '<exe>' if not on PATH; -FreshDatabase for a clean DB
```
Prerequisites and the full walkthrough: `README.md`, "Run the free demo on
Windows". Desk-specific paths (which PostgreSQL bin, which Python) belong in
`desk.md` (a pointer to `project-notes\tasks\desk-environment.md`), not here --
this file is the command shape, that file is this desk's actual values.

## Verification drive
Not this file's job. Once `.orchestration/verify/SKILL.md` exists (pending --
see PR #43 and the three F4 trials, not yet merged as of this retrofit), it is
the one source for how to launch, doctor and drive a feature for proof. This
file will point there, not repeat it, per `adapters/README.md`'s own
instruction ("for the verification drive it points at verify/SKILL.md instead
of repeating it").
