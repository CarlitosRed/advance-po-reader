"""Exercise the actual STDIO protocol against the local website, without a provider.

Run with .venv-agent/Scripts/python.exe. --run-sample creates only a fictional
workflow in the synthetic catalog and leaves all human decisions pending.
"""
import argparse
import json
from pathlib import Path
from uuid import uuid4

import anyio
from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]


async def verify(run_sample=False):
    server = StdioServerParameters(command=str(ROOT/".venv-agent/Scripts/python.exe"),
        args=[str(ROOT/"scripts/reader-agent-server.py")])
    async with Client(server) as client:
        tools=(await client.list_tools()).tools
        assert len(tools)==11
        async def call(name,arguments=None):
            result=await client.call_tool(name,arguments or {})
            if result.is_error: raise RuntimeError(f"Local protocol verification failed: {name}")
            if not isinstance(result.structured_content,dict): raise RuntimeError("Structured tool result missing")
            return result.structured_content
        status=await call("reader_status")
        assert status["database"]=="ready"
        workspaces=(await call("reader_list_catalogs"))["workspaces"]
        assert len(workspaces)==1
        workspace=workspaces[0]
        library=await call("reader_list_test_documents")
        counts=[]
        for catalog in workspace["catalogs"]:
            if catalog["synthetic"]: continue
            result=await call("reader_search_catalog",{"tenant_id":workspace["id"],"vendor_id":catalog["id"],"limit":1})
            assert result["total"]==catalog["product_count"]
            counts.append({"name":catalog["name"],"product_count":result["total"]})
        report={"transport":"stdio","tools":len(tools),"catalogs":counts,"library_pdfs":len(library["documents"]),
                "provider_configured":status["provider_configured"],"synthetic_sample":None}
        if run_sample:
            synthetic=[c for c in workspace["catalogs"] if c["synthetic"]]
            assert len(synthetic)==1
            arguments={"tenant_id":workspace["id"],"vendor_id":synthetic[0]["id"],"request_id":str(uuid4())}
            sample=await call("reader_start_sample_workflow",arguments)
            run_id=sample["run"]["id"]
            scope={"tenant_id":workspace["id"],"vendor_id":synthetic[0]["id"],"run_id":run_id}
            extraction=await call("reader_get_extraction",scope)
            summary=await call("reader_get_review_summary",scope)
            assert sample["run"]["state"]=="completed" and summary["approved_products"]==[]
            assert len(summary["pending_row_ids"])==4
            assert len(extraction["attempts"])==1 and extraction["attempts"][0]["synthetic"] is True
            # Explicit recovery of the same UUID returns the saved run, with no second processing attempt.
            recovered=await call("reader_start_sample_workflow",arguments)
            assert recovered["run"]["id"]==run_id
            extraction=await call("reader_get_extraction",scope)
            assert len(extraction["attempts"])==1
            report["synthetic_sample"]={"run_id":run_id,"review_url":sample["review_url"],
                "state":sample["run"]["state"],"human_review_required":True,"pending_rows":4,"attempts":1}
        destination=ROOT/"output/agent-ready/mcp-verification.json"
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-sample",action="store_true")
    arguments=parser.parse_args()
    anyio.run(verify,arguments.run_sample)
