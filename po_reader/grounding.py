"""Retrieval -> evidence context -> deterministic validation -> decision.

This is the RAG-style foundation. No generative model can bypass validation.
"""
from .catalog import match_line


def interpret_line(line, retriever):
    retrieved = retriever.retrieve(line) if line["kind"] == "product" else dict(hits=[],authority="sample_catalog",catalog_fingerprint=retriever.fingerprint)
    context = {hit["product_id"]:retriever.catalog[hit["product_id"]] for hit in retrieved["hits"]}
    line["retrieval"] = retrieved
    decision = match_line(line,context)
    hit = next((h for h in retrieved["hits"] if h["product_id"] == decision.get("product_id")),None)
    decision["catalog_evidence"] = hit["source_observations"] if hit else []
    for suggestion in decision["suggestions"]:
        suggestion["catalog_evidence"] = next((h["source_observations"] for h in retrieved["hits"] if h["product_id"] == suggestion["id"]),[])
    line["match"] = decision
    return decision
