import copy
import unittest

from po_reader.catalog import load_catalog
from po_reader.grounding import interpret_line
from po_reader.model_matching import ModelMatcher
from po_reader.model_provider import CascadeProvider
from po_reader.retrieval import ProductRetriever


def product(identifier, name, **extra):
    return dict(id=identifier, name=name, variants=[name], provenance=[dict(source="test catalog")], **extra)


CATALOG = {
    "76-76": product("76-76", "Latex disposable gloves medium", attributes={"material": "latex", "size": "medium"}),
    "76-77": product("76-77", "Nitrile disposable gloves medium", attributes={"material": "nitrile", "size": "medium"}),
    "D1540-2": product("D1540-2", "Aluminum extension ladder 40 feet"),
    "0076-76": product("0076-76", "Latex disposable gloves large"),
}


def visual_line(identifier="76-76", role="vendor_product_code", **changes):
    line = dict(kind="product", description="Medium disposable latex gloves", quantity="2", uom="EA",
                identifiers=[dict(raw_value=identifier, printed_label="Product ID", role=role, status="observed")]
                if identifier is not None else [],
                source_validation=dict(status="corroborated"))
    line.update(changes)
    return line


class Comparator:
    name = "mock-text"
    model = "gpt-oss-test"
    def __init__(self, selected="76-76", relationship="compatible", conflicts=None):
        self.result = dict(selected_product_id=selected, description_relationship=relationship,
                           attribute_conflicts=conflicts or [], reason="Comparison of product name and attributes.")
        self.calls = []

    def compare(self, line, candidates):
        self.calls.append((copy.deepcopy(line), copy.deepcopy(candidates)))
        return copy.deepcopy(self.result)


class ModelMatchingTests(unittest.TestCase):
    def match(self, line, provider=None, catalog=None):
        with ModelMatcher(provider or Comparator(), catalog or CATALOG) as matcher:
            return matcher.match_line(line)

    def test_exact_id_and_semantically_compatible_name_matches(self):
        provider = Comparator()
        line = visual_line()
        decision = self.match(line, provider)
        self.assertEqual(decision["status"], "matched")
        self.assertEqual(decision["product_id"], "76-76")
        self.assertEqual(line["identifiers"][0]["raw_value"], "76-76")
        self.assertEqual(decision["validation_errors"], [])
        candidate = next(c for c in provider.calls[0][1] if c["product_id"] == "76-76")
        self.assertEqual(candidate["attributes"]["material"], "latex")
        self.assertEqual(candidate["variants"], [CATALOG["76-76"]["name"]])
        self.assertNotIn("source_observations", candidate)

    def test_model_cannot_invent_a_catalog_id(self):
        decision = self.match(visual_line(), Comparator("9999"))
        self.assertEqual(decision["status"], "review_needed")
        self.assertIsNone(decision["product_id"])
        self.assertIn("model_selected_outside_candidates", decision["validation_errors"])

    def test_existing_id_outside_retrieved_candidates_is_also_rejected(self):
        provider = Comparator("D1540-2")
        decision = self.match(visual_line(), provider)
        self.assertNotIn("D1540-2", {c["product_id"] for c in provider.calls[0][1]})
        self.assertIsNone(decision["product_id"])
        self.assertIn("model_selected_outside_candidates", decision["validation_errors"])

    def test_similar_product_name_cannot_replace_differing_id(self):
        # Even an overconfident semantic judgment cannot replace the printed code.
        decision = self.match(visual_line("76-99"), Comparator("76-76"))
        self.assertEqual(decision["status"], "review_needed")
        self.assertIn("selected_product_identifier_mismatch", decision["validation_errors"])
        self.assertIn("selection_has_no_exact_identifier_binding", decision["validation_errors"])

    def test_material_and_variant_conflicts_require_review(self):
        for conflict in ("material: latex versus nitrile", "size: medium versus large"):
            with self.subTest(conflict=conflict):
                decision = self.match(visual_line(), Comparator(conflicts=[conflict]))
                self.assertEqual(decision["status"], "review_needed")
                self.assertIn("product_attribute_conflict", decision["validation_errors"])
                self.assertEqual(decision["model_comparison"]["attribute_conflicts"], [conflict])
        self.assertIn("description_conflict", self.match(visual_line(), Comparator(relationship="conflict"))["validation_errors"])

    def test_unverified_vision_and_reader_disagreement_require_review(self):
        for source, expected in (("vision_only", "vision_reading_needs_confirmation"),
                                 ("disagreement", "source_disagreement"),
                                 ("missing_evidence", "missing_source_evidence")):
            with self.subTest(source=source):
                decision = self.match(visual_line(source_validation=dict(status=source)))
                self.assertEqual(decision["status"], "review_needed")
                self.assertIn(expected, decision["validation_errors"])

    def test_broad_ids_and_leading_zeroes_are_preserved(self):
        for identifier, description in (("D1540-2", "Aluminum extension ladder 40 feet"),
                                        ("0076-76", "Latex disposable gloves large")):
            with self.subTest(identifier=identifier):
                line = visual_line(identifier, description=description)
                decision = self.match(line, Comparator(identifier))
                self.assertEqual(decision["status"], "matched")
                self.assertEqual(decision["product_id"], identifier)
                self.assertEqual(line["retrieval"]["observed_identifiers"][0]["raw_value"], identifier)
        line = visual_line("0076-76")
        decision = self.match(line, Comparator("76-76"))
        self.assertEqual(decision["status"], "review_needed")
        self.assertIn("selected_product_identifier_mismatch", decision["validation_errors"])

    def test_customer_and_unknown_roles_do_not_supply_authoritative_ids(self):
        for role, expected in (("customer_item_number", "customer_identifier_without_approved_alias"),
                               ("unknown", "unknown_identifier_role")):
            with self.subTest(role=role):
                line = visual_line(role=role)
                decision = self.match(line)
                self.assertEqual(decision["status"], "review_needed")
                self.assertEqual(line["retrieval"]["exact_product_ids"], [])
                self.assertIn(expected, decision["validation_errors"])

    def test_unscoped_catalog_aliases_do_not_grant_authority(self):
        catalog = copy.deepcopy(CATALOG)
        catalog["76-76"]["approved_aliases"] = [dict(value="CUST76", role="customer_item_number")]
        line = visual_line("CUST76", role="customer_item_number")
        decision = self.match(line, catalog=catalog)
        self.assertEqual(decision["status"], "review_needed")
        self.assertEqual(line["retrieval"]["exact_bindings"], [])

    def test_conflicting_authoritative_ids_are_all_retrieved_and_reviewed(self):
        line = visual_line()
        line["identifiers"].append(dict(raw_value="76-77", printed_label="Vendor Part", role="manufacturer_part_number", status="observed"))
        decision = self.match(line)
        self.assertEqual(set(line["retrieval"]["exact_product_ids"]), {"76-76", "76-77"})
        self.assertEqual(decision["status"], "review_needed")
        self.assertIn("conflicting_authoritative_identifiers", decision["validation_errors"])

    def test_uncertain_identifier_requires_confirmation(self):
        line = visual_line()
        line["identifiers"][0]["status"] = "uncertain"
        decision = self.match(line)
        self.assertEqual(decision["status"], "review_needed")
        self.assertIn("uncertain_product_identifier", decision["validation_errors"])

    def test_missing_identifier_does_not_become_a_model_match(self):
        decision = self.match(visual_line(None))
        self.assertEqual(decision["status"], "review_needed")
        self.assertIn("missing_product_identifier", decision["validation_errors"])

    def test_uncertain_row_kind_cannot_become_a_product_match(self):
        for kind in ("uncertain", "note", None):
            with self.subTest(kind=kind):
                decision = self.match(visual_line(kind=kind))
                self.assertEqual(decision["status"], "review_needed")
                self.assertIn("uncertain_row_kind", decision["validation_errors"])

    def test_compatible_verdict_requires_an_observed_description(self):
        for description in (None, "", "  "):
            with self.subTest(description=description):
                decision = self.match(visual_line(description=description))
                self.assertEqual(decision["status"], "review_needed")
                self.assertIn("missing_source_description", decision["validation_errors"])

    def test_missing_invalid_quantity_and_units_require_review(self):
        for value in (None, "0", "-1", "NaN", "Infinity", "1e3", "1,000", True):
            with self.subTest(quantity=value):
                decision = self.match(visual_line(quantity=value))
                self.assertEqual(decision["status"], "review_needed")
                self.assertIn("invalid_or_missing_quantity", decision["validation_errors"])
        for unit in (None, "", "PK", "CASE", "unknown"):
            with self.subTest(unit=unit):
                decision = self.match(visual_line(uom=unit))
                self.assertEqual(decision["status"], "review_needed")
                self.assertIn("invalid_or_unconfirmed_unit", decision["validation_errors"])
        self.assertEqual(self.match(visual_line(uom="EACH", quantity="2.5"))["status"], "matched")

    def test_unknown_observed_code_can_report_not_in_catalog(self):
        decision = self.match(visual_line("NONE-404", description="Unrelated obscure widget"), Comparator(None))
        self.assertEqual(decision["status"], "not_in_catalog")
        self.assertIsNone(decision["product_id"])

    def test_provider_failure_and_invalid_output_fail_closed(self):
        class FailedProvider:
            def compare(self, *_):
                raise ValueError("Provider unavailable")
        decision = self.match(visual_line(), FailedProvider())
        self.assertEqual(decision["status"], "review_needed")
        self.assertIn("model_comparison_failed", decision["validation_errors"])
        provider = Comparator()
        provider.result["attribute_conflicts"] = "none"
        decision = self.match(visual_line(), provider)
        self.assertEqual(decision["status"], "review_needed")
        self.assertIn("invalid_model_comparison", decision["validation_errors"])

    def test_charges_skip_provider_and_resources_close(self):
        provider = Comparator()
        matcher = ModelMatcher(provider, CATALOG)
        decision = matcher.match_line(visual_line(kind="charge"))
        self.assertEqual(decision["status"], "excluded_charge")
        self.assertEqual(provider.calls, [])
        matcher.close()
        matcher.close()
        with self.assertRaises(RuntimeError):
            matcher.match_line(visual_line())

    def test_legacy_retrieval_and_grounding_keep_original_behavior(self):
        if not (__import__('pathlib').Path(__file__).resolve().parents[1] / 'data/catalog.sqlite3').is_file():
            self.skipTest('Private catalog fixture unavailable')
        retriever = ProductRetriever(load_catalog())
        try:
            line = dict(kind="product", vendor_id="7160618", supplier_id=None,
                        description="Werner 6 Tread Fibreglass Step Ladder", quantity="4.00", uom=None)
            retrieved = retriever.retrieve(line)
            self.assertEqual(retrieved["identifiers"], ["7160618"])
            self.assertEqual(retrieved["hits"][0]["method"], "exact_id")
            self.assertNotIn("observed_identifiers", retrieved)
            decision = interpret_line(line, retriever)
            self.assertEqual(decision["status"], "matched")
            self.assertEqual(decision["product_id"], "7160618")
        finally:
            retriever.close()

    def test_selective_cascade_skips_identical_unambiguous_exact_case(self):
        adjudicator = Comparator()
        provider = CascadeProvider(Comparator(), adjudicator)
        line = visual_line(description="  LATEX disposable gloves medium ",
                           attributes=[dict(name="Material", value="LATEX")])
        source = copy.deepcopy(line)
        decision = self.match(line, provider)
        self.assertEqual(decision["status"], "matched")
        self.assertEqual(adjudicator.calls, [])
        self.assertEqual(line["comparison_method"], "deterministic_exact_description")
        self.assertEqual(line["identifiers"], source["identifiers"])
        self.assertEqual(provider.stage_counts()["adjudication"], dict(used=0, skipped=1, failed=0))
        self.assertEqual(provider.stage_counts()["reranking"]["skipped"], 1)

    def test_description_paraphrases_variants_and_attributes_require_llm(self):
        cases = [visual_line(),
                 visual_line(description="Latex disposable gloves medium sterile"),
                 visual_line(description=CATALOG["76-76"]["name"],
                             attributes=[dict(name="material", value="nitrile")]),
                 visual_line(description=CATALOG["76-76"]["name"],
                             attributes=[dict(name="pack count", value="100")])]
        for line in cases:
            with self.subTest(line=line):
                adjudicator = Comparator()
                provider = CascadeProvider(Comparator(), adjudicator)
                self.match(line, provider)
                self.assertEqual(len(adjudicator.calls), 1)
                self.assertEqual(provider.stage_counts()["adjudication"]["used"], 1)

    def test_cascade_does_not_skip_source_disagreements_or_unknown_ids(self):
        for line, expected in ((visual_line(description=CATALOG["76-76"]["name"],
                                           source_validation=dict(status="disagreement")), "source_disagreement"),
                               (visual_line("76-99", description=CATALOG["76-76"]["name"]),
                                "observed_identifier_not_in_catalog"),
                               (visual_line(role="unknown", description=CATALOG["76-76"]["name"]),
                                "unknown_identifier_role")):
            with self.subTest(expected=expected):
                adjudicator = Comparator()
                provider = CascadeProvider(Comparator(), adjudicator)
                decision = self.match(line, provider)
                self.assertEqual(len(adjudicator.calls), 1)
                self.assertEqual(decision["status"], "review_needed")
                self.assertIn(expected, decision["validation_errors"])

    def test_cascade_conflicting_ids_and_invented_choice_remain_review(self):
        adjudicator = Comparator("invented")
        provider = CascadeProvider(Comparator(), adjudicator)
        line = visual_line(description=CATALOG["76-76"]["name"])
        line["identifiers"].append(dict(raw_value="76-77", role="manufacturer_part_number", status="observed"))
        decision = self.match(line, provider)
        self.assertEqual(len(adjudicator.calls), 1)
        self.assertIsNone(decision["product_id"])
        self.assertIn("model_selected_outside_candidates", decision["validation_errors"])
        self.assertIn("conflicting_authoritative_identifiers", decision["validation_errors"])

    def test_optional_reranker_preserves_candidates_and_records_real_usage(self):
        class Ranker:
            model = "mock-real-cross-encoder"

            def rank(self, line, candidates):
                return [dict(candidate, rank_score=float(index)) for index, candidate in enumerate(reversed(candidates))]
        adjudicator = Comparator()
        provider = CascadeProvider(Comparator(), adjudicator, candidate_ranker=Ranker())
        line = visual_line()
        self.match(line, provider)
        ids = {candidate["product_id"] for candidate in adjudicator.calls[0][1]}
        self.assertIn("76-76", ids)
        self.assertEqual(ids, {hit["product_id"] for hit in line["retrieval"]["hits"]})
        self.assertEqual(provider.stage_counts()["reranking"]["used"], 1)
        self.assertEqual(provider.stage_counts()["adjudication"]["used"], 1)

    def test_optional_candidate_services_cannot_change_bindings_or_drop_exact_hits(self):
        class UnsafeRetriever:
            def retrieve(self, line, catalog, retrieved):
                retrieved["exact_product_ids"] = ["76-77"]
                return retrieved
        class UnsafeRanker:
            def rank(self, line, candidates):
                return [candidate for candidate in candidates if candidate["product_id"] != "76-76"]
        provider = CascadeProvider(Comparator(), Comparator(), UnsafeRetriever(), UnsafeRanker())
        line = visual_line()
        decision = self.match(line, provider)
        self.assertEqual(decision["status"], "matched")
        self.assertEqual(line["retrieval"]["exact_product_ids"], ["76-76"])
        self.assertIn("76-76", {item["product_id"] for item in line["retrieval"]["hits"]})
        self.assertEqual(provider.stage_counts()["semantic_retrieval"]["failed"], 1)
        self.assertEqual(provider.stage_counts()["reranking"]["failed"], 1)

    def test_reranker_scores_revision_and_catalog_facts_are_saved(self):
        class Ranker:
            model = "Qwen/Qwen3-Reranker-test"

            def __init__(self):
                self.usage = []

            def rank(self, line, candidates):
                ranked = [dict(candidate, rank_score=-(index + .25)) for index, candidate in enumerate(candidates)]
                self.usage.append(dict(revision="test-revision-abc", score_type="cross_encoder_logit_difference"))
                return list(reversed(ranked))
        ranker = Ranker()
        provider = CascadeProvider(Comparator(), Comparator(), candidate_ranker=ranker)
        line = visual_line()
        self.match(line, provider)
        saved = line["retrieval"]
        self.assertEqual(saved["reranking"]["status"], "completed")
        self.assertEqual(saved["reranking"]["model"], ranker.model)
        self.assertEqual(saved["reranking"]["model_revision"], "test-revision-abc")
        self.assertEqual(saved["reranking"]["score_type"], "cross_encoder_logit_difference")
        for hit in saved["hits"]:
            self.assertIsInstance(hit["rank_score"], float)
            self.assertEqual(hit["name"], CATALOG[hit["product_id"]]["name"])
            self.assertEqual(hit["variants"], CATALOG[hit["product_id"]]["variants"])
        self.assertEqual(provider.metadata["stages"]["reranking"]["status"], "completed")
        self.assertEqual(provider.metadata["stages"]["reranking"]["last_execution"]["model_revision"], "test-revision-abc")

    def test_invalid_reranker_scores_and_catalog_mutations_fail_closed(self):
        class Ranker:
            def __init__(self, score=None, mutate=False):
                self.score, self.mutate = score, mutate

            def rank(self, line, candidates):
                for candidate in candidates:
                    candidate["rank_score"] = self.score
                    if self.mutate:
                        candidate["name"] = "Changed catalog name"
                return candidates
        for score, mutate in ((float("nan"), False), (float("inf"), False),
                              (True, False), ("0.1", False), (.1, True)):
            with self.subTest(score=score, mutate=mutate):
                provider = CascadeProvider(Comparator(), Comparator(), candidate_ranker=Ranker(score, mutate))
                line = visual_line()
                self.match(line, provider)
                self.assertEqual(provider.stage_counts()["reranking"]["failed"], 1)
                self.assertEqual(line["retrieval"]["reranking"]["status"], "failed")
                self.assertTrue(all("rank_score" not in hit for hit in line["retrieval"]["hits"]))
                self.assertTrue(all(hit["name"] == CATALOG[hit["product_id"]]["name"] for hit in line["retrieval"]["hits"]))

    def test_semantic_service_statuses_reflect_actual_availability(self):
        class Retriever:
            def __init__(self, status):
                self.status = status

            def retrieve(self, line, catalog, retrieved):
                retrieved["semantic_retrieval"] = dict(status=self.status)
                return retrieved
        for reported, expected in (("completed", "used"), ("unavailable", "failed"),
                                   ("skipped_empty_query_or_catalog", "skipped")):
            with self.subTest(reported=reported):
                provider = CascadeProvider(Comparator(), Comparator(), candidate_retriever=Retriever(reported))
                line = visual_line()
                self.match(line, provider)
                self.assertEqual(provider.stage_counts()["semantic_retrieval"][expected], 1)
                self.assertEqual(line["retrieval"]["semantic_retrieval"]["status"], reported)


if __name__ == "__main__":
    unittest.main()
