"""Local retrieval layer for the sample catalog.

Exact identifier lookup + FTS5/BM25 description search + deterministic reranking.
Results carry their catalog source observations. Retrieval never changes data.
"""
import hashlib
import json
import sqlite3

from .catalog import CODE, normalize_id, similarity, tokens


class ProductRetriever:
    def __init__(self, catalog):
        self.catalog = catalog
        self.fingerprint = hashlib.sha256(json.dumps(catalog,sort_keys=True,ensure_ascii=True).encode()).hexdigest()
        self._db = sqlite3.connect(":memory:")
        self._db.execute("CREATE VIRTUAL TABLE product_search USING fts5(id UNINDEXED, name, descriptions, tokenize='porter unicode61')")
        self._db.executemany("INSERT INTO product_search VALUES (?, ?, ?)",
                             [(p["id"],p["name"],"\n".join(p["variants"])) for p in catalog.values()])

    def close(self):
        self._db.close()

    def retrieve_for_model(self, line, limit=5):
        """Build model context from labeled identifiers without inferring IDs.

        The native parser's retrieve() retains its existing identifier rules.
        This path accepts broad codes directly from the visual extraction and
        keeps their original values and printed roles in the evidence record.
        """
        description = line.get("description") or ""
        observations = []
        bindings = []
        for observation in line.get("identifiers", []):
            raw = observation.get("raw_value")
            role = observation.get("role", "unknown")
            if not isinstance(raw, str) or not raw.strip():
                continue
            observations.append(dict(observation))
            identifier = normalize_id(raw)
            # A future customer crosswalk needs trusted supplier/customer scope.
            if role in ("vendor_product_code", "manufacturer_part_number") and identifier in self.catalog:
                bindings.append(dict(raw_value=raw, role=role, product_id=identifier, method="exact_id"))

        exact = list(dict.fromkeys(binding["product_id"] for binding in bindings))
        search_terms = sorted(tokens(description))[:32]
        query = " OR ".join('"' + term + '"' for term in search_terms)
        search = self._db.execute(
            "SELECT id, bm25(product_search) FROM product_search WHERE product_search MATCH ? ORDER BY bm25(product_search), id LIMIT ?",
            (query, max(10, limit * 3)),
        ).fetchall() if query else []
        ranks = {identifier: rank for identifier, rank in search}
        pool = list(dict.fromkeys(exact + [identifier for identifier, _ in search]))
        ranked = sorted(pool, key=lambda identifier: (
            identifier not in exact, -similarity(description, self.catalog[identifier]),
            ranks.get(identifier, 0), identifier,
        ))
        selected = list(dict.fromkeys(exact + ranked[:limit]))
        hits = []
        for identifier in selected:
            product = self.catalog[identifier]
            hits.append(dict(
                product_id=identifier, name=product["name"],
                method="exact_id" if identifier in exact else "fts5_bm25",
                description_similarity=similarity(description, product), bm25=ranks.get(identifier),
                source_observations=product["provenance"], variants=product["variants"],
            ))
        return dict(
            identifiers=[normalize_id(observation["raw_value"]) for observation in observations],
            observed_identifiers=observations, exact_bindings=bindings,
            exact_product_ids=exact, description_query=description, hits=hits,
            catalog_fingerprint=self.fingerprint, authority="sample_catalog",
            score_note="Search ranks and token overlap are not confidence probabilities.",
        )

    def retrieve(self, line, limit=5):
        description = line.get("description") or ""
        identifiers = list(dict.fromkeys(normalize_id(c) for c in
                           [line.get("vendor_id"),line.get("supplier_id"),*CODE.findall(description)] if c))
        exact = [identifier for identifier in identifiers if identifier in self.catalog]
        # Extract/quote terms rather than interpreting PDF text as FTS syntax.
        search_terms = sorted(tokens(description))[:32]
        query = " OR ".join('"'+term+'"' for term in search_terms)
        search = self._db.execute("SELECT id, bm25(product_search) FROM product_search WHERE product_search MATCH ? ORDER BY bm25(product_search), id LIMIT ?",
                                  (query,max(10,limit*3))).fetchall() if query else []
        ranks = {identifier:rank for identifier,rank in search}
        pool = list(dict.fromkeys(exact+[identifier for identifier,_ in search]))
        ranked = sorted(pool,key=lambda identifier:(identifier not in exact,-similarity(description,self.catalog[identifier]),ranks.get(identifier,0),identifier))
        # Return every explicit exact hit even if several conflicting IDs occur.
        selected = list(dict.fromkeys(exact+ranked[:limit]))
        hits = []
        for identifier in selected:
            product = self.catalog[identifier]
            hits.append(dict(product_id=identifier,name=product["name"],
                             method="exact_id" if identifier in exact else "fts5_bm25",
                             description_similarity=similarity(description,product),
                             bm25=ranks.get(identifier),source_observations=product["provenance"]))
        return dict(identifiers=identifiers,description_query=description,hits=hits,catalog_fingerprint=self.fingerprint,
                    authority="sample_catalog",score_note="Search ranks and token overlap are not confidence probabilities.")
