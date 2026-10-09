"""Temporary offline browser QA on port 8016 and a dedicated fictional database.

The OpenAI adapter receives an injected MockTransport. Only the exact generated
fictional PDF is accepted, and no customer library is exposed by this server.
"""
import argparse
import base64
import json
from pathlib import Path
import shutil
import sys
import time
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from alembic import command
from alembic.config import Config
import httpx
from pydantic import SecretStr
from sqlalchemy import create_engine,select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
import uvicorn

from backend.app import create_app
from backend.catalog import ProductInput,import_products
from backend.config import Settings
from backend.database import create_database
from backend.models import CatalogNamespace,Vendor
from backend.providers import OpenAIProvider
from backend.synthetic import fixture_payload,generate_fixture
import backend.website as website
from gate_a.models import Tenant
from tests.isolated_postgres import require_test_database_url


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outcome",choices=["success","timeout"],default="success")
    args=parser.parse_args()
    production=Settings()
    test_url=require_test_database_url(make_url(production.database_url.get_secret_value()).set(
        database="gate_a_test_backend_website_browser_mock").render_as_string(hide_password=False))
    create_database(test_url.render_as_string(hide_password=False))
    engine=create_engine(test_url,connect_args={"connect_timeout":3})
    configuration=Config(str(ROOT/"backend.alembic.ini"))
    with engine.begin() as connection:
        configuration.attributes["connection"]=connection
        command.upgrade(configuration,"head")
    settings=Settings(_env_file=None,database_url=SecretStr(test_url.render_as_string(hide_password=False)),port=8016,
        local_api_token=SecretStr("fictional-browser-qa-local-token"),live_processing_enabled=True,
        openai_api_key=SecretStr("fake-offline-browser-key"),storage_directory=ROOT/"data/browser-qa/uploads")
    with Session(engine) as session:
        existing=session.scalars(select(CatalogNamespace).where(CatalogNamespace.source_catalog_id=="fictional")).all()
        assert len(existing)<=1,"Keep this dedicated QA database limited to one fictional workspace"
        if existing:
            tenant=session.get(Tenant,existing[0].tenant_id)
            vendor=session.get(Vendor,existing[0].vendor_id)
        else:
            tenant=Tenant(name="Fictional offline browser QA "+uuid4().hex)
            session.add(tenant);session.flush()
            vendor=Vendor(tenant_id=tenant.id,name="Fictional offline catalog")
            session.add(vendor);session.flush()
            session.add(CatalogNamespace(tenant_id=tenant.id,vendor_id=vendor.id,source_catalog_id="fictional",
                source_filename="Generated fictional fixture",workbook_sha256="0"*64,database_sha256="0"*64,
                source_sheet="Fictional",adapter_version="browser-qa.v1",assigned_by="Fictional offline QA",synthetic=True))
            import_products(session,tenant.id,vendor.id,[ProductInput(sku="SYN-001",description="Synthetic blue widget"),
                                                       ProductInput(sku="SYN-002",description="Synthetic red widget")])
        session.commit()
        tenant_id,vendor_id=str(tenant.id),str(vendor.id)
    fixture=generate_fixture()
    def mocked(request):
        body=json.loads(request.content)
        observed=base64.b64decode(body["input"][0]["content"][0]["file_data"].split(",",1)[1])
        assert observed==fixture,"Only declared fictional fixture bytes may reach this mock"
        time.sleep(20)
        if args.outcome=="timeout": raise httpx.ReadTimeout("Fictional offline timeout",request=request)
        return httpx.Response(200,headers={"x-request-id":"req_browser_offline"},json={
            "id":"resp_browser_offline","status":"completed","model":"fictional-offline-response",
            "usage":{"input_tokens":0,"output_tokens":0},
            "output":[{"type":"message","content":[{"type":"output_text","text":fixture_payload().model_dump_json()}]}]})
    provider=OpenAIProvider(api_key="fake-offline-browser-key",enabled=True,transport=httpx.MockTransport(mocked))
    private=ROOT/"data/browser-qa"
    website.CORPUS=private/"empty-corpus"
    website.CORPUS.mkdir(parents=True,exist_ok=True)
    website.WEB=private/"web"
    shutil.copytree(ROOT/"web/local-reader",website.WEB,dirs_exist_ok=True)
    index=website.WEB/"index.html"
    index.write_text(index.read_text(encoding="utf-8").replace("Local workspace","Fictional offline QA")
        .replace("<title>Purchase Order Reader</title>","<title>Fictional offline browser QA</title>"),encoding="utf-8")
    app=create_app(settings,engine=engine,provider=provider)
    from fastapi.testclient import TestClient
    with TestClient(app,base_url="http://127.0.0.1:8016",headers={"X-Local-Token":settings.local_api_token.get_secret_value(),"X-Tenant-ID":tenant_id}) as client:
        source=client.post("/documents",headers={"Idempotency-Key":uuid4().hex},data={"vendor_id":vendor_id},
            files={"file":("fictional.pdf",fixture,"application/pdf")}).json()
        run=client.post("/documents/"+source["id"]+"/runs",headers={"Idempotency-Key":uuid4().hex},json={"provider":"openai"}).json()
    receipt={"fixture_only":True,"external_provider_requests":0,"tenant_id":tenant_id,"vendor_id":vendor_id,
        "source_id":source["id"],"run_id":run["id"],"outcome":args.outcome,
        "url":"http://127.0.0.1:8016/#document="+source["id"]+"&run="+run["id"]}
    (ROOT/"output/agent-ready/browser-mock.json").write_text(json.dumps(receipt,indent=2))
    print(json.dumps(receipt),flush=True)
    uvicorn.run(app,host="127.0.0.1",port=8016,access_log=False)


if __name__=="__main__": main()
