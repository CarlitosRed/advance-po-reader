# Advance PO Reader

This repository's current development boundary is local Gate A: a FastAPI health/configuration service, PostgreSQL/Alembic foundation, and the first versioned contract boundary. Gate A makes no provider calls and starts without API credentials. See [PROJECT_GOAL.md](PROJECT_GOAL.md), [local logic rules](docs/local-logic-rules-2026-10-02.md), and [agent handoff](docs/agent-handoff.md).

The earlier prototype's local-model implementation and training-data tooling have been removed. The retained CLI extraction path uses the server-side OpenAI API only; it is a prototype and is not the new FastAPI/ProductDocument v1 workflow. Historical measurements and operating guides are in [docs/archive](docs/archive/README.md). Original research sources remain in `docs/research/` as evidence and do not authorize provider transfers, API spending, training, or deployment.

## OpenAI CLI prototype

The optional legacy CLI requires a server-side `OPENAI_API_KEY` and an API model available to the project. Requests send the selected document pages and extracted text to OpenAI and may incur API charges. Use only source documents authorized for that transfer.

```powershell
& .\.venv\Scripts\python.exe reader.py analyze 'AUTHORIZED_PURCHASE_ORDER.pdf' --provider openai --model YOUR_VISION_MODEL --summary
```

The sample catalog is provisional. A match remains subject to source validation and human review. The real catalog, tenant boundary, production UI, and cart contract are not implemented by this CLI.

## Local checks

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Customer documents, API keys, catalogs, review records, and generated outputs must stay out of Git. Gate A uses synthetic fixtures only.
