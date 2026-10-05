"""Live-mode helpers for the POC (scripts only; backend/ is not changed).

Free mode stays the default. Live mode sends a document to OpenAI only after the
person confirms that exact file in the browser; the backend then checks the
authorization against the file hash. Nothing here prints a key or token.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import secrets
from time import perf_counter

DEFAULT_TOKEN = "local-backend-dev-only"
_DEFAULT_ENV = object()


class LiveRefusal(RuntimeError):
    """Fixed, value-free refusal text; safe to print."""


def check_live_settings(env_file=_DEFAULT_ENV, require_token=True):
    """Load the server settings like the backend does and refuse unless live mode is safe.

    The backend's own Settings reads the ignored .env.backend; this function never opens
    it and never returns or prints a secret. Tests pass env_file=None and set variables.
    """
    from backend.config import Settings
    extra = {} if env_file is _DEFAULT_ENV else {"_env_file": env_file}
    try:
        settings = Settings(live_processing_enabled=True, **extra)
    except Exception:
        raise LiveRefusal("The server settings could not be loaded. Check this desk's .env.backend for typos "
                          "(values are never printed). Nothing was started.") from None
    key = settings.openai_api_key.get_secret_value().strip() if settings.openai_api_key else ""
    if require_token and settings.local_api_token.get_secret_value() == DEFAULT_TOKEN:
        raise LiveRefusal("Live mode needs a private local API token in this desk's ignored .env.backend "
                          "(PO_BACKEND_LOCAL_API_TOKEN, at least 16 characters, not the shared default). "
                          "Nothing was started.")
    if not key:
        raise LiveRefusal("Live mode needs your OpenAI key in this desk's ignored .env.backend "
                          "(OPENAI_API_KEY=...). Put it there yourself and never paste it into chat. "
                          "Nothing was started.")
    return settings


def live_settings(engine, port, data_directory, rehearsal=False):
    """Settings for the running live app; the database and storage are always this demo's own."""
    from backend.config import Settings
    from pydantic import SecretStr
    own = dict(database_url=SecretStr(engine.url.render_as_string(hide_password=False)), port=port,
               storage_directory=data_directory / "uploads", live_processing_enabled=True)
    if rehearsal:
        return Settings(_env_file=None, local_api_token=SecretStr(secrets.token_urlsafe(32)),
                        openai_api_key=SecretStr("rehearsal-not-a-real-key"), provider_timeout_seconds=30, **own)
    return Settings(**own)


# ---- cost and the spend guard -------------------------------------------------------------

def price_rates(environment=None):
    """USD per million tokens from PO_POC_INPUT_USD_PER_MTOK / PO_POC_OUTPUT_USD_PER_MTOK, or None."""
    environment = os.environ if environment is None else environment
    try:
        rates = (float(environment["PO_POC_INPUT_USD_PER_MTOK"]), float(environment["PO_POC_OUTPUT_USD_PER_MTOK"]))
    except (KeyError, ValueError):
        return None
    return rates if all(rate >= 0 for rate in rates) else None


def estimate_cost(usage, rates):
    if rates is None or not isinstance(usage, dict):
        return None
    return (usage.get("input_tokens", 0) * rates[0] + usage.get("output_tokens", 0) * rates[1]) / 1_000_000


class SpendGuard:
    """Counts live attempts stored by the backend and blocks new ones at the cap."""

    def __init__(self, engine, environment=None):
        environment = os.environ if environment is None else environment
        self.engine = engine
        self.rates = price_rates(environment)
        try:
            self.cap_usd = float(environment.get("PO_POC_SPEND_CAP_USD", "3"))
        except ValueError:
            self.cap_usd = 3.0
        self.runs_explicit = "PO_POC_MAX_LIVE_RUNS" in environment
        try:
            self.max_runs = int(environment.get("PO_POC_MAX_LIVE_RUNS", "5"))
        except ValueError:
            self.max_runs = 5

    def status(self):
        from sqlalchemy import select
        from sqlalchemy.orm import Session
        from backend.models import ProviderAttempt
        with Session(self.engine) as session:
            usages = session.scalars(select(ProviderAttempt.usage).where(ProviderAttempt.synthetic.is_(False))).all()
        runs = len(usages)
        by_cost = self.rates is not None
        estimated = sum(estimate_cost(usage, self.rates) or 0 for usage in usages) if by_cost else None
        blocked = ((by_cost and estimated >= self.cap_usd) or
                   (runs >= self.max_runs and (not by_cost or self.runs_explicit)))
        if by_cost:
            detail = f"Estimated spend ${estimated:.2f} of ${self.cap_usd:.2f} · {runs} live {'run' if runs == 1 else 'runs'}"
        else:
            detail = (f"{runs} of {self.max_runs} live runs used. Cost is not recorded here, so this limit counts runs")
        message = (detail + ". The limit for this demo is reached: raise PO_POC_SPEND_CAP_USD or PO_POC_MAX_LIVE_RUNS "
                   "and restart to continue.") if blocked else detail + "."
        return {"runs": runs, "basis": "cost" if by_cost else "runs", "cap_usd": self.cap_usd,
                "max_runs": self.max_runs, "estimated_usd": None if estimated is None else round(estimated, 4),
                "blocked": bool(blocked), "message": message}


def install_live_guard(app, guard):
    """Refuse new live runs once the cap is reached and keep live mode OpenAI-only."""
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from starlette.concurrency import run_in_threadpool

    @app.middleware("http")
    async def live_spend_cap(request: Request, call_next):
        path = request.url.path
        creates = path.startswith("/documents/") and path.endswith("/runs")
        if request.method == "POST" and (creates or (path.startswith("/runs/") and path.endswith("/process"))):
            if creates:
                try:
                    if (await request.json()).get("provider") != "openai":
                        return JSONResponse({"error": "poc_live_openai_only"}, status_code=409)
                except ValueError:
                    return JSONResponse({"error": "invalid_request"}, status_code=422)
            if (await run_in_threadpool(guard.status))["blocked"]:
                return JSONResponse({"error": "poc_spend_cap_reached"}, status_code=409)
        return await call_next(request)


# ---- rehearsal: the live path with a fake transport (no key, no network) --------------------

def v12_payload(payload):
    """The fixed sample observations as ProductDocument 1.2, which the OpenAI adapter expects."""
    value = deepcopy(payload)
    value["schema_version"] = "1.2"
    for row in value["rows"]:
        if row["row_kind"] == "product":
            row["item_group_id"], row["row_role"] = row["row_id"], "product_item"
        else:
            row["row_role"] = "unknown"
    return value


def rehearsal_transport(payload):
    """An httpx transport that answers like the Responses API for one fixed one-page sample."""
    import httpx
    body = {"id": "resp_rehearsal", "model": "rehearsal-fake-model", "status": "completed",
            "usage": {"input_tokens": 1800, "output_tokens": 900, "total_tokens": 2700},
            "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(v12_payload(payload))}]}]}
    return httpx.MockTransport(lambda request: httpx.Response(200, json=body, headers={"x-request-id": "req_rehearsal"}))


# ---- optional: send a one-page PDF as an image instead of a file ----------------------------

def render_first_page_png(pdf_bytes, dpi=150):
    import pymupdf
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        return document[0].get_pixmap(dpi=dpi).tobytes("png")


class PdfAsImageProvider:
    """Wraps the OpenAI adapter. A one-page PDF becomes a page image (PO_POC_PDF_AS_IMAGES=1).

    Multi-page PDFs would need page merging inside backend/, which this POC does not change,
    so they stop with a plain error instead of guessing.
    """

    def __init__(self, inner):
        self.inner = inner
        self.model = inner.model
        self.prompt_version = inner.prompt_version
        self.schema_version = inner.schema_version

    def extract(self, source_bytes, media_type, page_count, fixture_name=None):
        from backend.providers import ProviderResult
        if media_type != "application/pdf":
            return self.inner.extract(source_bytes, media_type, page_count, fixture_name)
        if page_count != 1:
            return ProviderResult(None, "failed", error_code="poc_images_mode_single_page_only", model=self.model,
                                  prompt_version=self.prompt_version, schema_version=self.schema_version)
        return self.inner.extract(render_first_page_png(source_bytes), "image/png", 1, fixture_name)


def images_mode_enabled(environment=None):
    environment = os.environ if environment is None else environment
    return environment.get("PO_POC_PDF_AS_IMAGES", "").strip().lower() in {"1", "true", "yes"}


# ---- one-page probe ---------------------------------------------------------------------------

def probe_document(images=False):
    """A one-page fictional PDF (or its page image); never derived from a real document."""
    from poc_demo_support import FIXTURES, payload_for, render_source
    case = {"id": "probe-one-page", "title": "Probe", "rows": [
        {"product": 0, "mode": "certain"}, {"product": 5, "mode": "probable"},
        {"mode": "uncertain", "description": "Fictional item needing a human answer"}]}
    products = json.loads((FIXTURES / "catalog.json").read_text(encoding="utf-8"))["products"]
    pdf = render_source(payload_for(case, catalog=products), "application/pdf")
    return (render_first_page_png(pdf), "image/png") if images else (pdf, "application/pdf")


def run_probe(settings, transport=None, images=False):
    """One request through the same adapter. Returns only sanitized facts."""
    from backend.providers import OpenAIProvider
    data, media_type = probe_document(images)
    provider = OpenAIProvider(api_key=settings.openai_api_key.get_secret_value(), enabled=True,
                              model=settings.extraction_model, store=settings.provider_store,
                              timeout_seconds=settings.provider_timeout_seconds, transport=transport)
    started = perf_counter()
    result = provider.extract(data, media_type, 1)
    usage = {key: value for key, value in result.usage.items() if isinstance(value, int)}
    if result.state in {"succeeded", "invalid_output", "incomplete", "refused"}:
        accepted = "yes"
    elif result.error_code in {"provider_http_400", "provider_http_404", "provider_http_422"}:
        accepted = "probably_no"
    else:
        accepted = "unknown"
    cost = estimate_cost(usage, price_rates())
    return {"configured_model": settings.extraction_model, "answered_by": result.actual_model,
            "input": "page image (PNG)" if images else "PDF file", "state": result.state,
            "error": result.error_code, "latency_ms": result.latency_ms or int((perf_counter() - started) * 1000),
            "usage": usage, "estimated_cost_usd": None if cost is None else round(cost, 4),
            "input_accepted": accepted}
