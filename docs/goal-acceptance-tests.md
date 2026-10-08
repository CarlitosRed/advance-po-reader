> v1.1 backend integration, October 8: Safety Net defaults OFF. Inherited #9 backend tests explicitly enable it; original v1 grounding/completeness gaps remain strict expected failures under OFF. New Safety Net controls and their browser proof belong to the new UI track. See [mode ledger](integrate-safety-net-plan.md).

# Goal acceptance tests (T-007)

Owner: `Codex · goal tests`. Reviewer: Claudio. Assigned October 3, 2026.
Desk: `advance-po-reader.worktrees/goal-tests`, branch `codex/goal-acceptance-tests`.
Starting commit: `183412f4b1daaf8fc49b2a60f91ed8e34b749afb`, verified on remote
`origin/codex/worktree-standards`. The PR targets `codex/worktree-standards`.
This tests-only task measures existing behavior and makes no backend fixes.

## Run

Create an isolated Python 3.12 virtual environment in this desk, then install
the repository's pinned `requirements.backend.lock.txt`. PostgreSQL binaries
must be on PATH or supplied via `GOAL_POSTGRES_BIN`. No preexisting database or
PostgreSQL configuration is used. No API key is needed.

```powershell
# Run from the assigned goal-tests desk.
python -m venv .venv-goal
.\.venv-goal\Scripts\python.exe -m pip install -r requirements.backend.lock.txt
$env:GOAL_POSTGRES_BIN = 'C:\path\to\installed\postgresql\bin'
.\.venv-goal\Scripts\python.exe -m pytest -m goal
```

`pytest.ini` makes the default `pytest -m goal` command collect only `tests/goal`
and register the goal marker. Existing backend, Gate A and agent suites retain
their explicit `-c pytest.backend.ini`, `-c pytest.gate-a.ini`, and
`-c pytest.agent.ini` configurations. Legacy discovery can still explicitly
target its test directory. This task did not run unrelated suites.

To regenerate the tracked scorecard from actual pytest outcomes:

```powershell
.\.venv-goal\Scripts\python.exe -m pytest -m goal -q --goal-scorecard docs\goal-scorecard-2026-10-03.md
```

The task also delivers an identical copy to
`project-notes/audits/goal-scorecard-2026-10-03.md`, as T-007 explicitly requires.
The tests write only the optional named scorecard and their own ignored scratch
area; copying the requested project-notes report is a delivery step.

## Isolation and evidence

- One writer owns this desk. A second agent reviewed the tests and backend
  read-only; it made no writes or runtime calls.
- Allowed edits: test harness/configuration, tests, ignore entries, this guide,
  scorecard and the required handoff note. Repository `data/`, `output/`, `.env*`,
  customer PDFs and provider settings are excluded.
- `.venv-goal/` and `.goal-test-runtime/` are desk-owned and ignored. Each run
  initializes an independent PostgreSQL cluster under pytest's basetemp, picks
  a loopback port and creates a uniquely named `gate_a_test_backend_goal_*`
  database. It applies actual migrations and uses actual catalog queries,
  including pg_trgm. Teardown drops the database and stops only that server.
- Installed PostgreSQL executables are used as read-only tooling. They never
  operate on their installation's existing cluster or database.
- Settings has `_env_file=None` and an explicit null provider key. The process
  removes inherited `OPENAI_API_KEY`, `PO_BACKEND_*`, and PostgreSQL override
  variables. The harness guards dotenv opens, built-in provider extraction and
  external HTTP transports. It injects only `FixedJSONProvider` into the app.
- Source PDFs, PNGs and JPGs are generated from fictional text in memory. The
  real decoder, upload, persistence, matching, snippet and review routes run.
  Only the configuration/storage root is redirected to private pytest scratch;
  the harness runs actual matching, review and validation logic.
- Every expected failure is strict and restricted to `AssertionError`. Helper
  HTTP/provider errors use `pytest.fail`, so they cannot be hidden as product
  xfails. Missing PostgreSQL binaries are blocked skips; startup/migration
  errors fail setup. `--runxfail --tb=short` exposes the actual failing assertions.

The scorecard counts test clauses per goal. It is not an estimate that the app
is a particular percentage complete. Fixed JSON checks establish software
handling of known observations, not vision extraction accuracy. The adversarial
goal 7/8 responses intentionally disagree with the generated page. Every match
remains pending until an explicit synthetic human review event; there are no
cart, order, training, external provider or production database actions.

## Recovery point

The base branch is preserved. The feature commit and PR provide the source
recovery point; the disposable runtime contains no customer evidence and is
not a backup artifact. No service or shared checkout is modified by the suite.

## T-009 PR A regression checks

PR A updates tiers, three explicit line answers, marked/scoped review-created
catalog entries, and same-row quantity/unit validation. The original T-007
edit scope and measurement above describe its baseline; the current scorecard
records A's implementation. Source grounding, independent completeness and
F7/F8 remain for PR B. Missing optional browser tooling counts as blocked.

The browser regression uses the installed Node/Playwright runtime and a
headless browser in a fresh temporary profile. It reaches only a test-owned
loopback bridge to the fixed-provider API. Startup corpus enumeration is
disabled; it opens the generated fictional run directly and exercises all
three answers, explicit approval, and the disabled/enabled Finish button.
It never connects to an existing application service or opens customer files.

```powershell
$env:GOAL_POSTGRES_BIN = '<PostgreSQL binary directory>'
$env:GOAL_NODE_BIN = '<Node executable with Playwright available>'
$env:GOAL_BROWSER_BIN = '<headless-capable browser executable>'
.\.venv-goal\Scripts\python.exe -m pytest -m goal -q --goal-scorecard docs\goal-scorecard-2026-10-03.md
```

The new migration adds `origin` and `review_pool_id` and extends immutable
binding snapshots. Its tested downgrade restores the previous guard and schema
on an empty throwaway database. Downgrade refuses when review-created products
or new answer events exist, so it cannot silently discard their evidence.

## PR #7 B2: named backend and goal CI coverage

`Backend and goal checks` adds the `backend-goal` job for pushes and PRs.
It runs these distinct steps with pinned backend dependencies and PostgreSQL 17:

```text
python -m pytest -c pytest.backend.ini --isolated-backend --basetemp=.backend-ci-runtime -q --tb=short --junitxml=backend-results.xml
python -m pytest -m goal -q --tb=short --goal-scorecard=goal-scorecard-ci.md --junitxml=goal-results.xml
```

The backend harness provisions all five required test database settings,
including a separate empty historical-migration database. Goal tests get
another freshly created database. Both use the ephemeral loopback CI service;
they refuse to reuse a preexisting database. Only databases created by the
harness are dropped. The service URL path is permitted only in GitHub Actions
and must name the dedicated test administrator database. Local runs instead
start and stop their own native PostgreSQL cluster under this worktree.
No secrets or live provider connection are needed. Dotenv opens and real HTTP
transports are blocked; the backend suite permits its generated synthetic
provider and injected mock transports, while goal tests permit only fixed JSON.


PR B item 3 expands `pytest.backend.ini` to collect `tests/backend` and
`tests/goal` with importlib collection. Every new B acceptance case therefore
runs in both commands in the same `backend-goal` job. The first command's
totals include the goal cases, while the separate goal command measures that
suite again and generates its scorecard. Each command gets fresh databases.
Local browser tooling enables the website check in both commands; CI omits
it, so both commands report that browser case as a blocked skip.
