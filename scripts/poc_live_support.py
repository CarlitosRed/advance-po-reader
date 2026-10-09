"""Live-mode helpers for the POC (scripts only; backend/ is not changed).

Free mode stays the default. Live mode sends a document to OpenAI only after the
person confirms that exact file in the browser; the backend then checks the
authorization against the file hash. Nothing here prints a key or token.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
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
    # Safety parameter: NaN, infinite, zero or negative rates would make the dollar cap meaningless,
    # so they count as "no prices" and the run-count limit applies instead.
    return rates if all(math.isfinite(rate) and rate > 0 for rate in rates) else None


def estimate_cost(usage, rates):
    if rates is None or not isinstance(usage, dict):
        return None
    return (usage.get("input_tokens", 0) * rates[0] + usage.get("output_tokens", 0) * rates[1]) / 1_000_000


# A live attempt whose usage is missing or unreadable (timeout, 5xx, unknown outcome) may still have
# been billed. It is charged this deliberately high amount instead of zero.
UNKNOWN_INPUT_TOKENS = 100_000
UNKNOWN_OUTPUT_TOKENS = 16_000


def _token_count(value, fallback):
    if type(value) is int and value >= 0:
        return min(value, 10 ** 12)  # clamp so float math cannot overflow; still far above any cap
    return fallback


def conservative_cost(usage, rates):
    """Estimated dollars for one stored attempt; unknown or invalid token counts are charged at the worst case."""
    usage = usage if isinstance(usage, dict) else {}
    tokens_in = _token_count(usage.get("input_tokens"), UNKNOWN_INPUT_TOKENS)
    tokens_out = _token_count(usage.get("output_tokens"), UNKNOWN_OUTPUT_TOKENS)
    return (tokens_in * rates[0] + tokens_out * rates[1]) / 1_000_000


class SpendGuard:
    """Counts live attempts stored by the backend and blocks new ones at the cap.

    Safety parameters fail closed: a cap that is not a finite positive number falls back to $3,
    a run ceiling that is not a whole number falls back to 5 (a value below 1 blocks everything),
    and the run ceiling is always on, also when prices are set.
    """

    def __init__(self, engine, environment=None):
        environment = os.environ if environment is None else environment
        self.engine = engine
        self.rates = price_rates(environment)
        try:
            self.cap_usd = float(environment.get("PO_POC_SPEND_CAP_USD", "3"))
        except ValueError:
            self.cap_usd = 3.0
        if not math.isfinite(self.cap_usd) or self.cap_usd <= 0:
            self.cap_usd = 3.0
        self.runs_explicit = "PO_POC_MAX_LIVE_RUNS" in environment
        try:
            self.max_runs = int(environment.get("PO_POC_MAX_LIVE_RUNS", "5"))
        except ValueError:
            self.max_runs = 5

    def _usages(self):
        from sqlalchemy import select
        from sqlalchemy.orm import Session
        from backend.models import ProviderAttempt
        with Session(self.engine) as session:
            return session.scalars(select(ProviderAttempt.usage).where(ProviderAttempt.synthetic.is_(False))).all()

    def status(self):
        usages = self._usages()
        runs = len(usages)
        by_cost = self.rates is not None
        estimated = sum(conservative_cost(usage, self.rates) for usage in usages) if by_cost else None
        # "not (x < cap)" so that any unexpected NaN blocks instead of passing.
        blocked = ((by_cost and not estimated < self.cap_usd) or runs >= self.max_runs)
        if by_cost:
            detail = (f"Estimated spend ${estimated:.2f} of ${self.cap_usd:.2f} · "
                      f"{runs} of {self.max_runs} live {'run' if self.max_runs == 1 else 'runs'} used")
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

    import asyncio
    # One live processing request at a time: the cap check and the attempt row (written by the backend
    # before the provider call) cannot interleave, so two requests can never share the last slot.
    admission = asyncio.Lock()

    @app.middleware("http")
    async def live_spend_cap(request: Request, call_next):
        path = request.url.path
        creates = path.startswith("/documents/") and path.endswith("/runs")
        processes = path.startswith("/runs/") and path.endswith("/process")
        if request.method != "POST" or not (creates or processes):
            return await call_next(request)
        if creates:
            try:
                body = await request.json()
            except ValueError:
                return JSONResponse({"error": "invalid_request"}, status_code=422)
            if not isinstance(body, dict):  # valid JSON that is not an object ([], null, "x", 1, true)
                return JSONResponse({"error": "invalid_request"}, status_code=422)
            if body.get("provider") != "openai":
                return JSONResponse({"error": "poc_live_openai_only"}, status_code=409)
            if (await run_in_threadpool(guard.status))["blocked"]:
                return JSONResponse({"error": "poc_spend_cap_reached"}, status_code=409)
            return await call_next(request)
        async with admission:
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


# ---- diagnosis of one failed reading -----------------------------------------------------------

def capturing_transport(inner):
    """Wrap a transport and keep the raw response body (never printed)."""
    import httpx

    class CapturingTransport(httpx.BaseTransport):
        body = b""

        def handle_request(self, request):
            response = inner.handle_request(request)
            response.read()
            self.body = response.content
            return response

    return CapturingTransport()


UNEXPECTED_FIELD = "<unexpected field>"


def contract_field_names():
    """Every property name the extraction contract declares (the only names safe to print)."""
    from backend.contracts import ExtractionPayload
    names = set()

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("properties"), dict):
                names.update(node["properties"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(ExtractionPayload.model_json_schema())
    return frozenset(names)


def printable_path(loc, known):
    """Pydantic loc -> path text. For extra_forbidden a loc part is the model's own property
    name (untrusted, may be document text), so only declared field names and indices pass."""
    parts = []
    for part in loc:
        if type(part) is int:
            parts.append(f"[{part}]")
        else:
            parts.append(("." if parts else "") + (part if isinstance(part, str) and part in known else UNEXPECTED_FIELD))
    return "".join(parts)


def validation_findings(body_bytes, page_count):
    """Re-run the adapter's decoding and validate_payload; return rule names and paths only."""
    from pydantic import ValidationError
    from backend.contracts import validate_payload
    from backend.providers import _unique_json_keys
    findings = {"failures": [], "pages": None, "rows": None}
    known = contract_field_names()
    try:
        body = json.loads(body_bytes)
        texts = [part["text"] for item in body.get("output", []) if isinstance(item, dict) and item.get("type") == "message"
                 for part in item.get("content", []) if isinstance(part, dict) and part.get("type") == "output_text"]
    except (ValueError, AttributeError, TypeError, KeyError):
        findings["failures"].append("response_body: not a readable Responses object")
        return findings, None
    if len(texts) != 1:
        findings["failures"].append(f"output: expected exactly one output_text part, found {len(texts)}")
        return findings, None
    try:
        decoded = json.loads(texts[0], object_pairs_hook=_unique_json_keys)
    except ValueError as error:
        findings["failures"].append("output_text: " + ("duplicate JSON key" if "duplicate" in str(error) else "not valid JSON"))
        return findings, texts[0]
    if isinstance(decoded, dict):
        findings["pages"] = len(decoded["pages"]) if isinstance(decoded.get("pages"), list) else None
        findings["rows"] = len(decoded["rows"]) if isinstance(decoded.get("rows"), list) else None
    try:
        validate_payload(decoded, page_count)
    except ValidationError as error:
        for item in error.errors(include_input=False, include_url=False):
            path = printable_path(item["loc"], known)
            rule = str(item["msg"]).removeprefix("Value error, ") if item["type"] == "value_error" else ""
            findings["failures"].append(f"{path or '(payload)'}: {item['type']}" + (f" - {rule}" if rule else ""))
    except ValueError as error:
        findings["failures"].append("(payload): value_error - " + str(error))
    return findings, texts[0]


def source_media(path):
    suffix = Path(path).suffix.lower()
    media = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(suffix)
    if media is None:
        raise LiveRefusal("The file must be a .pdf, .png or .jpg. Nothing was sent.")
    return media


def source_page_count(data, media):
    if media != "application/pdf":
        return 1
    import pymupdf
    with pymupdf.open(stream=data, filetype="pdf") as document:
        return document.page_count


def run_diagnosis(settings, data, media, page_count, transport=None):
    """One request through the same adapter; returns sanitized facts and the raw model JSON text."""
    import httpx
    from backend.providers import OpenAIProvider
    capture = capturing_transport(transport or httpx.HTTPTransport())
    provider = OpenAIProvider(api_key=settings.openai_api_key.get_secret_value(), enabled=True,
                              model=settings.extraction_model, store=settings.provider_store,
                              timeout_seconds=settings.provider_timeout_seconds, transport=capture)
    result = provider.extract(data, media, page_count)
    findings, raw_text = validation_findings(capture.body, page_count) if capture.body else ({"failures": [], "pages": None, "rows": None}, None)
    usage = {key: value for key, value in result.usage.items() if isinstance(value, (int, dict))}
    cost = estimate_cost(usage, price_rates())
    report = {"model": settings.extraction_model, "answered_by": result.actual_model, "adapter_state": result.state,
              "adapter_error": result.error_code, "latency_ms": result.latency_ms, "source_pages": page_count,
              "model_pages": findings["pages"], "model_rows": findings["rows"], "usage": usage,
              "estimated_cost_usd": None if cost is None else round(cost, 4), "validation_failures": findings["failures"]}
    return report, (capture.body.decode("utf-8", "replace") if capture.body else None), raw_text
