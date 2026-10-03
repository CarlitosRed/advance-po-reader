# Advance PO Reader

This repository's current development boundary is local Gate A: a FastAPI health/configuration service, PostgreSQL/Alembic foundation, and the first versioned contract boundary. Gate A makes no provider calls and starts without API credentials. See [PROJECT_GOAL.md](PROJECT_GOAL.md), [local logic rules](docs/local-logic-rules-2026-10-02.md), and [agent handoff](docs/agent-handoff.md).

The earlier prototype's local-model implementation and training-data tooling have been removed. The retained CLI extraction path uses the native PDF text engine; it is a prototype and is not the new FastAPI/ProductDocument v1 workflow. Historical measurements and operating guides are in [docs/archive](docs/archive/README.md). Original research sources remain in `docs/research/` as evidence and do not authorize provider transfers, API spending, training, or deployment.

## Run local Gate A

The local foundation in `gate_a/` implements health/configuration routes, a tenant-only PostgreSQL/Alembic baseline, and a versioned ProductDocument v1 envelope with observation/state validators. It starts without provider credentials or a running database. The full extraction payload remains outside Gate A.

```powershell
powershell -ExecutionPolicy Bypass -File .\setup-gate-a.ps1 -PythonPath 'PATH_TO_PYTHON_3_12.exe'
& .\.venv-gate-a\Scripts\python.exe -m gate_a
```

Run synthetic checks in a second terminal:

```powershell
& .\.venv-gate-a\Scripts\python.exe -m pytest -c pytest.gate-a.ini
```

The API defaults to `127.0.0.1:8000`. PostgreSQL is optional for startup/liveness and required for readiness. Apply migrations explicitly with `python -m alembic upgrade head` in the Gate A environment. See [Gate A setup and verification](docs/gate-a.md) for configuration, health routes, isolated database tests, and verification limits.

Gate A stops at this foundation. Later gates cover uploads, extraction, catalog matching, and human review. Gate A makes no provider request and implements no cart action.

## Native CLI prototype

The legacy CLI analyzes PDFs with its native text engine. Vision-model analysis is unavailable in this CLI; image-only PDF pages need OCR and require manual review.

```powershell
& .\.venv\Scripts\python.exe reader.py analyze 'PURCHASE_ORDER.pdf' --summary
```

The sample catalog is provisional. A match remains subject to source validation and human review. The real catalog, tenant boundary, production UI, and cart contract are not implemented by this CLI.

## Local checks

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Customer documents, API keys, catalogs, review records, and generated outputs must stay out of Git. Gate A uses synthetic fixtures only.
