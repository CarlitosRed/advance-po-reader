"""Offline demo tooling only; the backend and its contracts remain unchanged."""
from __future__ import annotations

import builtins
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import io
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "poc-demo"
OUTPUT = ROOT / "output" / "poc-demo"
FIXTURES = ROOT / "fixtures" / "poc-demo"


def offline_boundary():
    """Guard the entire demo process before Settings or providers are imported."""
    for name in list(os.environ):
        if name == "OPENAI_API_KEY" or name.startswith(("PO_BACKEND_", "PG")):
            os.environ.pop(name)
    original_open, original_io_open, original_os_open = builtins.open, io.open, os.open

    def guard(path):
        if isinstance(path, (str, bytes, os.PathLike)) and Path(os.fsdecode(path)).name.casefold().startswith(".env"):
            raise RuntimeError("POC forbids dotenv access")

    def safe_open(path, *args, **kwargs):
        guard(path)
        return original_open(path, *args, **kwargs)

    def safe_io_open(path, *args, **kwargs):
        guard(path)
        return original_io_open(path, *args, **kwargs)

    def safe_os_open(path, *args, **kwargs):
        guard(path)
        return original_os_open(path, *args, **kwargs)

    builtins.open, io.open, os.open = safe_open, safe_io_open, safe_os_open
    import httpx
    from backend.providers import OpenAIProvider, SyntheticProvider

    def forbidden(*args, **kwargs):
        raise RuntimeError("POC forbids built-in providers and external HTTP")

    OpenAIProvider.extract = SyntheticProvider.extract = forbidden
    httpx.HTTPTransport.handle_request = httpx.AsyncHTTPTransport.handle_async_request = forbidden


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def pg_directory(explicit=None):
    candidates = [Path(explicit)] if explicit else []
    executable = shutil.which("initdb")
    if executable:
        candidates.append(Path(executable).parent)
    # Existing local installation is read-only tooling; its cluster is never used.
    candidates.extend((ROOT.parents[2] / ".codex" / "worktrees").glob(
        "*/Advance PO Reader/data/gate-a-verification/runtime/pgsql/bin"))
    suffix = ".exe" if os.name == "nt" else ""
    for directory in candidates:
        if all((directory / (name + suffix)).is_file() for name in ("initdb", "pg_ctl")):
            return directory.resolve()
    raise RuntimeError("PostgreSQL binaries missing: pass -PostgresBin; no service is installed")


@contextmanager
def local_database(postgres_bin=None, fresh=False):
    """Persistent, desk-owned cluster; reset selects a new DB and deletes nothing."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from alembic import command
    from alembic.config import Config

    directory = pg_directory(postgres_bin)
    runtime = DATA / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    owner_path = runtime / "owner.json"
    cluster = runtime / "cluster"
    if owner_path.exists():
        owner = json.loads(owner_path.read_text(encoding="utf-8"))
        if owner.get("desk") != str(ROOT.resolve()) or owner.get("cluster") != str(cluster.resolve()):
            raise RuntimeError("POC runtime ownership mismatch")
    else:
        if cluster.exists():
            raise RuntimeError("Refusing an unregistered cluster")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        owner = {"desk": str(ROOT.resolve()), "cluster": str(cluster.resolve()), "port": port,
                 "database": "gate_a_backend_poc_demo_" + uuid4().hex[:12], "history": []}
        write_json(owner_path, owner)
    if (not isinstance(owner.get("port"), int) or not 1024 <= owner["port"] <= 65535 or
            not re.fullmatch(r"gate_a_backend_poc_demo_[a-f0-9]{12}", owner.get("database", "")) or
            not isinstance(owner.get("history"), list)):
        raise RuntimeError("Invalid POC runtime marker; no database operation performed")

    suffix = ".exe" if os.name == "nt" else ""
    ctl = directory / ("pg_ctl" + suffix)
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}

    def run(arguments, check=True):
        with (runtime / "commands.log").open("a", encoding="utf-8") as log:
            return subprocess.run([str(arg) for arg in arguments], check=check, stdout=log,
                                  stderr=subprocess.STDOUT, timeout=60, **flags)

    if not (cluster / "PG_VERSION").is_file():
        run([directory / ("initdb" + suffix), "-D", cluster, "-U", "poc_demo", "--auth=trust",
             "--encoding=UTF8", "--locale=C"])
    running = run([ctl, "-D", cluster, "status"], check=False).returncode == 0
    started = False
    try:
        if not running:
            run([ctl, "-D", cluster, "-l", runtime / "postgres.log", "-o",
                 f"-h 127.0.0.1 -p {owner['port']}", "-w", "start"])
            started = True
        pid_lines = (cluster / "postmaster.pid").read_text(encoding="utf-8").splitlines()
        if Path(pid_lines[1]).resolve() != cluster.resolve() or int(pid_lines[3]) != owner["port"]:
            raise RuntimeError("Running cluster boundary mismatch")
        if fresh:
            owner["history"].append(owner["database"])
            owner["database"] = "gate_a_backend_poc_demo_" + uuid4().hex[:12]
            write_json(owner_path, owner)
        if not re.fullmatch(r"gate_a_backend_poc_demo_[a-f0-9]{12}", owner["database"]):
            raise RuntimeError("Refusing a database outside the POC namespace")
        admin_url = make_url(f"postgresql+psycopg://poc_demo@127.0.0.1:{owner['port']}/postgres")
        admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            if not connection.scalar(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": owner["database"]}):
                # Generated database name, never source input or a user-supplied SQL identifier.
                connection.execute(text(f'CREATE DATABASE "{owner["database"]}"'))
        admin.dispose()
        engine = create_engine(admin_url.set(database=owner["database"]))
        try:
            config = Config(str(ROOT / "backend.alembic.ini"))
            with engine.begin() as connection:
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
            yield engine, owner
        finally:
            engine.dispose()
    finally:
        if started:
            run([ctl, "-D", cluster, "-m", "fast", "-w", "stop"])


def seed_catalog(engine):
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from backend.catalog import ProductInput, import_products
    from backend.models import CatalogNamespace, Vendor
    from gate_a.models import Tenant

    catalog = json.loads((FIXTURES / "catalog.json").read_text(encoding="utf-8"))
    products = [ProductInput.model_validate(item) for item in catalog["products"]]
    if len(products) != 150 or len({item.sku for item in products}) != 150:
        raise RuntimeError("Expected exactly 150 unique fictional catalog products")
    with Session(engine) as session:
        namespaces = session.scalars(select(CatalogNamespace)).all()
        if namespaces:
            if len(namespaces) != 1 or namespaces[0].source_catalog_id != "poc-demo-fictional-v1" or not namespaces[0].synthetic:
                raise RuntimeError("Refusing a database containing other catalogs")
            namespace = namespaces[0]
            tenant, vendor = session.get(Tenant, namespace.tenant_id), session.get(Vendor, namespace.vendor_id)
        else:
            tenants = session.scalars(select(Tenant)).all()
            if any(str(item.id) != "00000000-0000-0000-0000-000000000001" or
                   item.name != "Gate A synthetic development tenant" for item in tenants):
                raise RuntimeError("Refusing a nonempty, unregistered POC database")
            tenant = Tenant(name="POC fictional workspace")
            session.add(tenant)
            session.flush()
            vendor = Vendor(tenant_id=tenant.id, name="POC fictional catalog (150 products)")
            session.add(vendor)
            session.flush()
            namespace = CatalogNamespace(tenant_id=tenant.id, vendor_id=vendor.id,
                source_catalog_id="poc-demo-fictional-v1", source_filename="Invented POC fixtures",
                workbook_sha256="0" * 64, database_sha256="0" * 64, source_sheet="Fictional",
                adapter_version="poc-demo.v1", assigned_by="Codex POC synthetic setup", synthetic=True)
            session.add(namespace)
        imported = import_products(session, tenant.id, vendor.id, products)
        session.commit()
        return {"tenant_id": str(tenant.id), "vendor_id": str(vendor.id), "products": imported,
                "product_count": len(imported), "synthetic": True}


def field(value, page, region, label=None):
    return {"state": "observed" if value is not None else "not_applicable", "raw_value": value,
            "source_label": label, "alternative_readings": [],
            "evidence": [{"page_number": page, "region_reference": region}] if value is not None else []}


def payload_for(case, page_rows=None):
    """Author fixed observations for invented rows; never infer from source text."""
    catalog = json.loads((FIXTURES / "catalog.json").read_text(encoding="utf-8"))["products"]
    pages, rows = [], []
    groups = page_rows if page_rows is not None else [case["rows"]]
    for page_number, descriptors in enumerate(groups, 1):
        regions = [{"region_reference": "header", "bbox": {"x0": .04, "y0": .03, "x1": .96, "y1": .13}}]
        spacing = min(.12, .76 / max(len(descriptors), 1))
        for index, descriptor in enumerate(descriptors):
            region = f"p{page_number}-line-{index + 1}"
            item = catalog[descriptor.get("product", 0)]
            mode = descriptor.get("mode", "certain")
            code = item["sku"] if mode == "certain" else item["sku"].replace("-", "") if mode == "probable" else None
            description = descriptor.get("description", item["description"])
            if mode == "embedded":
                description += " code " + item["sku"]
            kind = descriptor.get("kind", "unknown" if mode == "uncertain" else "product")
            quantity = descriptor.get("quantity", "002.00" if index == 0 else "3") if kind == "product" else None
            row = {"row_id": region, "row_kind": kind,
                   "evidence": [{"page_number": page_number, "region_reference": region}],
                   "identifiers": [{**field(code, page_number, region, "Vendor code"), "source_role": "vendor_sku"}] if code else [],
                   "description": field(description, page_number, region, "Description"),
                   "quantity": field(quantity, page_number, region, "Quantity"),
                   "unit": field("EA" if quantity else None, page_number, region, "Unit"),
                   "unit_price": field(None, page_number, region), "line_total": field(None, page_number, region),
                   "uncertainty": "Fictional ambiguous row: choose one of the three answers" if kind == "unknown" else None}
            rows.append(row)
            y = .17 + index * spacing
            regions.append({"region_reference": region, "bbox": {"x0": .04, "y0": y, "x1": .96, "y1": y + spacing * .85}})
        pages.append({"page_number": page_number, "state": "complete", "uncertainty": None, "regions": regions})
    return {"contract_name": "ProductDocument", "schema_version": "1.1", "document_type": "purchase_order",
            "document_type_reason": None, "document_number": field(case["id"], 1, "header", "PO number"),
            "vendor_name": field("Fictional POC supplies", 1, "header"), "currency": field(None, 1, "header"),
            "pages": pages, "rows": rows, "warnings": []}


def render_source(payload, media_type="application/pdf"):
    from reportlab.pdfgen.canvas import Canvas
    from PIL import Image, ImageDraw, ImageFont
    output = BytesIO()
    canvas = Canvas(output, pagesize=(900, 1100), invariant=1) if media_type == "application/pdf" else None
    image = Image.new("RGB", (900, 1100), "white") if canvas is None else None
    draw = ImageDraw.Draw(image) if image else None
    for page in payload["pages"]:
        lines = [(.07, "FICTIONAL POC - FIXED JSON, NO MODEL READING"),
                 (.11, "PO " + payload["document_number"]["raw_value"] + f" / page {page['page_number']}")]
        regions = {region["region_reference"]: region["bbox"] for region in page["regions"]}
        for row in payload["rows"]:
            if row["evidence"][0]["page_number"] != page["page_number"]:
                continue
            code = row["identifiers"][0]["raw_value"] if row["identifiers"] else ""
            text = " | ".join(str(value or "") for value in (code, row["description"]["raw_value"],
                                                            row["quantity"]["raw_value"], row["unit"]["raw_value"]))
            lines.append((regions[row["row_id"]]["y0"] + .02, text))
        if canvas:
            font_size = 10 if len(lines) < 20 else 6
            canvas.setFont("Helvetica", font_size)
            for y, text in lines:
                canvas.drawString(40, 1100 * (1 - y), text)
            canvas.showPage()
        else:
            for y, text in lines:
                draw.text((40, 1100 * y), text, fill="black", font=ImageFont.load_default(size=14))
    if canvas:
        canvas.save()
    else:
        if len(payload["pages"]) != 1:
            raise ValueError("Photo fixture must have one page")
        image.save(output, format="PNG" if media_type == "image/png" else "JPEG")
    return output.getvalue()


class FixedProvider:
    model = "poc-fixed-json-v1"
    prompt_version = "fictional-hand-authored-poc-v1"
    schema_version = "1.1"

    def __init__(self):
        self.registry = {}
        self.calls = 0

    def register(self, data, media_type, payload):
        self.registry[(sha256(data).hexdigest(), media_type)] = deepcopy(payload)

    def extract(self, source_bytes, media_type, page_count, fixture_name=None):
        from backend.contracts import validate_payload, ExtractionPayload
        from backend.providers import ProviderResult
        self.calls += 1
        value = self.registry.get((sha256(source_bytes).hexdigest(), media_type))
        if value is None:
            return ProviderResult(None, "invalid_output", error_code="poc_unknown_fixture_bytes", synthetic=True,
                                  model=self.model, prompt_version=self.prompt_version, schema_version=self.schema_version)
        payload = validate_payload(ExtractionPayload.model_validate(value), page_count)
        return ProviderResult(payload, "succeeded", synthetic=True, usage={}, model=self.model,
                              prompt_version=self.prompt_version, schema_version=self.schema_version)


def app_settings(engine, port):
    from backend.config import Settings
    from pydantic import SecretStr
    return Settings(_env_file=None, database_url=SecretStr(engine.url.render_as_string(hide_password=False)),
                    port=port, local_api_token=SecretStr(secrets.token_urlsafe(32)), openai_api_key=None,
                    live_processing_enabled=False, storage_directory=DATA / "uploads")


def ok(response):
    if response.status_code not in (200, 201):
        raise RuntimeError(f"POC HTTP {response.status_code}: {response.json().get('error', 'request_failed')}")
    return response.json()


def process_fixture(client, scope, data, media_type):
    source = ok(client.post("/documents", headers={"Idempotency-Key": uuid4().hex},
        data={"vendor_id": scope["vendor_id"]}, files={"file": ("fictional-poc", data, media_type)}))
    run = ok(client.post(f"/documents/{source['id']}/runs", headers={"Idempotency-Key": uuid4().hex},
                         json={"provider": "synthetic"}))
    run = ok(client.post(f"/runs/{run['id']}/process"))
    if run["state"] not in ("completed", "partial"):
        raise RuntimeError("Fixed-provider fixture did not complete: " + str(run.get("outcome_code")))
    suggestions = ok(client.get(f"/runs/{run['id']}/suggestions"))["suggestions"]
    summary = ok(client.get(f"/runs/{run['id']}/summary"))
    if summary["approved_products"]:
        raise RuntimeError("Fixture preparation must leave approvals pending")
    return {"source_id": source["id"], "run_id": run["id"], "state": run["state"],
            "tiers": [item["tier"] for item in suggestions], "approved_products": 0,
            "route": f"/#document={source['id']}&run={run['id']}"}
