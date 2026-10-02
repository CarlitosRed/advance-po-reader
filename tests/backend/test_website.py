"""Meaningful local catalog/session/manual-review checks; fictional data only."""
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app import create_app
from backend.catalog import retrieve_candidates
from backend.config import ROOT, Settings
from backend.models import CatalogAlias, CatalogNamespace, CatalogProduct, CatalogSourceProduct, Vendor
from backend.source_import import import_catalogs
from backend.synthetic import generate_fixture
from backend.uploads import digest

TOKEN = "synthetic-website-test-token"


@pytest.fixture(scope="module")
def web_engine():
    value = os.environ.get("PO_BACKEND_API_TEST_DATABASE_URL")
    if not value:
        pytest.skip("Dedicated website PostgreSQL test database not configured")
    url = make_url(value)
    if url.host not in {"localhost","127.0.0.1","::1"} or url.database != "gate_a_test_backend_website_api":
        pytest.fail("Website tests require their own loopback test database")
    engine = create_engine(url)
    config = Config(str(ROOT / "backend.alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config,"head")
    yield engine
    engine.dispose()


@pytest.fixture
def web_client(web_engine):
    settings = Settings(_env_file=None, database_url=SecretStr(web_engine.url.render_as_string(hide_password=False)),
        local_api_token=SecretStr(TOKEN), live_processing_enabled=False, openai_api_key=None,
        storage_directory=ROOT/"data"/"website-tests"/uuid4().hex)
    with TestClient(create_app(settings,engine=web_engine),base_url="http://127.0.0.1:8014") as client:
        yield client


def scope(client):
    client.headers["X-Local-Token"]=TOKEN
    tenant=client.post("/tenants",json={"name":"Fictional website "+uuid4().hex}).json()
    client.headers["X-Tenant-ID"]=tenant["id"]
    vendor=client.post("/vendors",json={"name":"Fictional vendor"}).json()
    products=client.post("/catalog/import",json={"vendor_id":vendor["id"],"products":[
        {"sku":"SYN-001","description":"Synthetic blue widget"},
        {"sku":"SYN-002","description":"Synthetic red widget"},
        {"sku":"MANUAL-003","description":"Fictional manually found product"}]}).json()["products"]
    source=client.post("/documents",headers={"Idempotency-Key":uuid4().hex},
        data={"vendor_id":vendor["id"]},files={"file":("fictional.pdf",generate_fixture(),"application/pdf")}).json()
    run=client.post("/documents/"+source["id"]+"/runs",headers={"Idempotency-Key":uuid4().hex},
        json={"provider":"synthetic","fixture_name":"purchase_order"}).json()
    assert client.post("/runs/"+run["id"]+"/process").status_code==200
    result=client.get("/runs/"+run["id"]+"/result").json()
    return tenant,vendor,products,source,run,result


def event(row,action,**extra):
    return {"action":action,"row_id":row["row_id"],"reviewer":"Fictional QA",
        "reason":"Synthetic source checked","evidence_reference":row["evidence"],**extra}


def test_http_only_session_and_csrf(web_client):
    home=web_client.get("/")
    assert home.status_code==200 and "httponly" in home.headers["set-cookie"].lower()
    assert "samesite=strict" in home.headers["set-cookie"].lower()
    assert "script-src 'self'" in home.headers["content-security-policy"]
    csrf=web_client.get("/website/session").json()["csrf"]
    assert web_client.post("/tenants",json={"name":"Rejected missing CSRF"}).status_code==403
    response=web_client.post("/tenants",headers={"X-Website-CSRF":csrf},json={"name":"Fictional cookie "+uuid4().hex})
    assert response.status_code==201
    assert web_client.get("/website/corpus",headers={"Sec-Fetch-Site":"cross-site"}).status_code==403
    assert web_client.get("/website/corpus",headers={"Origin":"https://foreign.invalid"}).status_code==403
    assert response.headers["cache-control"]=="no-store"


def test_cross_site_navigation_does_not_grant_session(web_client):
    response=web_client.get("/",headers={"Sec-Fetch-Site":"cross-site"})
    assert "set-cookie" not in response.headers
    assert web_client.get("/website/session").status_code==401
    assert web_client.get("/website/corpus").status_code==401


def test_host_and_private_content_boundaries(web_client):
    assert web_client.get("/",headers={"Host":"foreign.invalid"}).status_code==403
    assert web_client.get("/website/workspaces").status_code==401
    assert web_client.get("/website/corpus/../../private/content").status_code in {401,404}
    assert "sk-" not in web_client.get("/").text
    assert TOKEN not in web_client.get("/web-assets/app.js").text


def test_real_decoder_previews_and_scope(web_client):
    tenant,vendor,products,source,run,result=scope(web_client)
    preview=web_client.get("/documents/"+source["id"]+"/pages/1")
    assert preview.status_code==200 and preview.content.startswith(b"\x89PNG")
    assert preview.headers["cache-control"]=="no-store"
    row=result["extraction"]["rows"][0]
    crop=web_client.get("/runs/"+run["id"]+"/rows/"+row["row_id"]+"/preview")
    assert crop.status_code==200 and crop.content.startswith(b"\x89PNG")
    assert web_client.get("/documents/"+source["id"]+"/pages/2").status_code==422
    assert web_client.get("/documents/"+source["id"]+"/content").content==generate_fixture()
    other=web_client.post("/tenants",json={"name":"Other fictional "+uuid4().hex}).json()
    web_client.headers["X-Tenant-ID"]=other["id"]
    assert web_client.get("/documents/"+source["id"]+"/pages/1").status_code==404
    assert web_client.get("/website/catalog/"+products[0]["candidate_id"]+"?vendor_id="+vendor["id"]).status_code==404


def test_manual_candidate_requires_proposal_and_preserves_evidence(web_client):
    tenant,vendor,products,source,run,result=scope(web_client)
    row=result["extraction"]["rows"][0];candidate=products[2]["candidate_id"]
    url="/runs/"+run["id"]+"/reviews"
    original=web_client.get("/runs/"+run["id"]+"/suggestions").json()
    assert web_client.post(url,json=event(row,"approve",selected_candidate_id=candidate)).status_code==422
    assert web_client.post(url,json=event(row,"propose_candidate",candidate_ids=[candidate])).status_code==201
    assert web_client.post(url,json=event(row,"approve",selected_candidate_id=candidate)).status_code==201
    assert web_client.get("/runs/"+run["id"]+"/result").json()==result
    assert web_client.get("/runs/"+run["id"]+"/suggestions").json()==original
    events=web_client.get(url).json()["events"]
    assert events[-2]["new_value"]["candidates"][0]["method"]=="human_catalog_search"
    assert events[-1]["new_value"]["candidate"]["candidate_id"]==candidate


@pytest.mark.parametrize("kind",["foreign_vendor","foreign_tenant","non_product","duplicate","too_many"])
def test_proposal_rejects_wrong_scope_or_unbounded_input(web_client,kind):
    tenant,vendor,products,source,run,result=scope(web_client)
    row=result["extraction"]["rows"][0];ids=[products[0]["candidate_id"]]
    if kind in {"foreign_vendor","foreign_tenant"}:
        if kind=="foreign_tenant":
            other=web_client.post("/tenants",json={"name":"Foreign fictional "+uuid4().hex}).json()
            web_client.headers["X-Tenant-ID"]=other["id"]
        other_vendor=web_client.post("/vendors",json={"name":"Another fictional vendor"}).json()
        ids=[web_client.post("/catalog/import",json={"vendor_id":other_vendor["id"],
            "products":[{"sku":"FOREIGN","description":"Foreign fictional product"}]}).json()["products"][0]["candidate_id"]]
        web_client.headers["X-Tenant-ID"]=tenant["id"]
    if kind=="non_product":row=result["extraction"]["rows"][2]
    if kind=="duplicate":ids*=2
    if kind=="too_many":ids=[str(uuid4()) for _ in range(6)]
    assert web_client.post("/runs/"+run["id"]+"/reviews",json=event(row,"propose_candidate",candidate_ids=ids)).status_code==422


def test_correction_is_raw_string_and_invalidates_prior_decision(web_client):
    tenant,vendor,products,source,run,result=scope(web_client)
    rows=result["extraction"]["rows"];url="/runs/"+run["id"]+"/reviews"
    for row,product in zip(rows[:2],products[:2]):
        assert web_client.post(url,json=event(row,"approve",selected_candidate_id=product["candidate_id"])).status_code==201
    for row in rows[2:]:
        assert web_client.post(url,json=event(row,"acknowledge")).status_code==201
    correction=web_client.post(url,json=event(rows[0],"correct",field_name="quantity",new_value="002.50"))
    assert correction.status_code==201 and correction.json()["new_value"]["value"]=="002.50"
    resolve={"action":"resolve","reviewer":"Fictional QA","reason":"All synthetic rows reviewed"}
    assert web_client.post(url,json=resolve).status_code==409
    assert web_client.post(url,json=event(rows[0],"approve",selected_candidate_id=products[0]["candidate_id"])).status_code==201
    assert web_client.post(url,json=resolve).status_code==201
    assert web_client.get("/runs/"+run["id"]+"/result").json()["extraction"]["rows"][0]["quantity"]["raw_value"]=="2"
    assert web_client.post(url,json=event(rows[0],"correct",field_name="quantity",new_value="3")).status_code==409


def fictional_sqlite(path):
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE catalogs(catalog_id TEXT,region_label TEXT,source_id TEXT,primary_sheet TEXT);
        CREATE TABLE source_workbooks(source_id TEXT,filename TEXT,sha256 TEXT);
        CREATE TABLE catalog_products(catalog_id TEXT,product_id_display TEXT,product_id_raw TEXT,
          product_name_raw TEXT,product_description_raw TEXT,product_features_raw TEXT,language_raw TEXT,
          product_id_source_label TEXT,source_row_number INTEGER,raw_product_fields_json TEXT);
        CREATE TABLE product_attributes(catalog_id TEXT,product_id_display TEXT,source_row_number INTEGER,
          attribute_label_raw TEXT,attribute_value_raw TEXT,attribute_value_display TEXT);
        CREATE TABLE product_detail_sections(catalog_id TEXT,product_id_display TEXT,source_row_number INTEGER,
          detail_section_label_raw TEXT,raw_detail_fields_json TEXT);
        """)
        for key in ["fictional_a","fictional_b"]:
            db.execute("INSERT INTO source_workbooks VALUES(?,?,?)",(key,key+".xlsx","a"*64))
            db.execute("INSERT INTO catalogs VALUES(?,?,?,?)",(key,key,key,"Product Information"))
            db.execute("INSERT INTO catalog_products VALUES(?,?,?,?,?,?,?,?,?,?)",
                (key,"001.00","001.00","Fictional "+key,"literal description","feature",None,"ProductID",2,'{"literal":"001.00"}'))
            db.execute("INSERT INTO product_attributes VALUES(?,?,?,?,?,?)",(key,"001.00",3,"Size","00.50","00.50"))
            db.execute("INSERT INTO product_detail_sections VALUES(?,?,?,?,?)",(key,"001.00",4,"Specifications",'{"raw":"verbatim"}'))


def test_catalog_adapter_provenance_separation_idempotency_and_immutability(web_engine,tmp_path):
    path=tmp_path/"fictional.sqlite3";fictional_sqlite(path);sha=digest(path.read_bytes())
    # Separate transactional schema from API fixtures. No real staging files.
    with web_engine.connect() as connection:
        transaction=connection.begin()
        with Session(bind=connection,join_transaction_mode="create_savepoint") as session:
            # Other test tenants have no real namespace; this savepoint is rolled back.
            receipts=import_catalogs(session,path,sha,"Fictional QA","single-workspace")
            assert sum(r["products"] for r in receipts)==2
            assert len({r["tenant_id"] for r in receipts})==1
            assert import_catalogs(session,path,sha,"Fictional QA","single-workspace")==receipts
            for receipt in receipts:
                from uuid import UUID
                candidates=retrieve_candidates(session,UUID(receipt["tenant_id"]),UUID(receipt["vendor_id"]),
                    [{"raw_value":"001.00","source_role":"vendor_sku"}],None)
                assert len(candidates["candidates"])==1
            sources=session.scalars(select(CatalogSourceProduct)).all()
            assert len(sources)==2
            assert sources[0].raw_fields["product_id_raw"]=="001.00"
            assert sources[0].attributes[0]["attribute_value_raw"]=="00.50"
            assert sources[0].detail_sections[0]["raw_detail_fields_json"]=='{"raw":"verbatim"}'
            assert session.scalar(select(func.count()).select_from(CatalogAlias).where(CatalogAlias.tenant_id==sources[0].tenant_id))==0
            with pytest.raises(IntegrityError):
                with session.begin_nested():
                    session.execute(text("UPDATE catalog_source_products SET source_row_number=99"))
            with pytest.raises(ValueError):
                import_catalogs(session,path,"b"*64,"Fictional QA","single-workspace")
            with pytest.raises(ValueError):
                import_catalogs(session,path,sha,"Fictional QA","separate-workspaces")
            # Source namespaces cannot receive unversioned browser/CLI additions.
            settings=Settings(_env_file=None, database_url=SecretStr(web_engine.url.render_as_string(hide_password=False)),
                local_api_token=SecretStr(TOKEN))
            with TestClient(create_app(settings,engine=connection),base_url="http://127.0.0.1:8014",
                headers={"X-Local-Token":TOKEN,"X-Tenant-ID":receipts[0]["tenant_id"]}) as client:
                response=client.post("/catalog/import",json={"vendor_id":receipts[0]["vendor_id"],
                    "products":[{"sku":"INVENTED","description":"Not a source record"}]})
                assert response.status_code==409
        transaction.rollback()


def test_database_guard_rejects_foreign_manual_proposal(web_client,web_engine):
    tenant,vendor,products,source,run,result=scope(web_client)
    row=result["extraction"]["rows"][0]
    from backend.models import ReviewEvent
    from uuid import UUID
    with Session(web_engine) as session:
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.add(ReviewEvent(tenant_id=UUID(tenant["id"]),run_id=UUID(run["id"]),
                    row_id=row["row_id"],action="propose_candidate",reviewer="Fictional QA",
                    reason="Foreign product must be denied",evidence_reference=row["evidence"],
                    new_value={"candidates":[{"candidate_id":str(uuid4())}]}))
                session.flush()
