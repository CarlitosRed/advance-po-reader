import copy
import unittest
from unittest.mock import patch

from po_reader.candidate_services import LoopbackReranker, OllamaSemanticRetriever, confusion_distance, loopback_url
from po_reader.model_provider import ProviderError


class CandidateServiceTests(unittest.TestCase):
    def test_remote_services_rejected(self):
        for url in ('https://example.com', 'http://user@localhost:9000', 'http://localhost:9000/v1'):
            with self.assertRaises(ValueError):
                loopback_url(url)

    def test_visual_confusion_is_a_suggestion_without_exact_binding(self):
        catalog = {'00123-B': dict(name='Widget', variants=[], provenance=[])}
        retrieved = dict(hits=[], exact_product_ids=[], exact_bindings=[], observed_identifiers=[])
        line = dict(description='', identifiers=[dict(raw_value='O0123-B', role='vendor_product_code')])
        before = copy.deepcopy(line)
        result = OllamaSemanticRetriever().retrieve(line, catalog, retrieved)
        self.assertEqual(result['hits'][0]['product_id'], '00123-B')
        self.assertEqual(result['exact_bindings'], [])
        self.assertEqual(line, before)
        self.assertLess(confusion_distance('O0123-B', '00123-B'), 1)

    def test_semantic_retrieval_preserves_all_exact_candidates(self):
        catalog = {i:dict(name=i, variants=[], provenance=[]) for i in ('A','B','C')}
        retrieved = dict(hits=[dict(product_id='A',name='A'),dict(product_id='B',name='B')],
                         exact_product_ids=['A','B'], exact_bindings=[dict(product_id='A'),dict(product_id='B')])
        response = [{'embeddings': [[1,0],[0,1],[1,1]]}, {'embeddings': [[1,1]]}]
        with patch('po_reader.candidate_services.request_json', side_effect=response):
            result = OllamaSemanticRetriever(limit=1).retrieve(dict(description='widget'), catalog, retrieved)
        self.assertEqual({h['product_id'] for h in result['hits']}, {'A','B','C'})
        self.assertEqual(result['exact_bindings'], retrieved['exact_bindings'])

    def test_invalid_embeddings_mark_service_unavailable_without_losing_fuzzy_hits(self):
        catalog = {'00123-B': dict(name='Widget', variants=[], provenance=[])}
        original = dict(hits=[], exact_product_ids=[], exact_bindings=[])
        with patch('po_reader.candidate_services.request_json', return_value={'embeddings': [[float('nan')]]}):
            result = OllamaSemanticRetriever().retrieve(dict(description='Widget',identifiers=[]), catalog, original)
        self.assertEqual(result['semantic_retrieval']['status'], 'unavailable')
        self.assertEqual(original['hits'], [])

    def test_reranker_uses_scores_and_preserves_candidate_data(self):
        candidates = [dict(product_id='001-B',name='Widget B',variants=['B']),dict(product_id='001-A',name='Widget A',variants=['A'])]
        response = dict(model='Qwen/Qwen3-Reranker-0.6B', model_revision='pin',
                        results=[dict(id='001-A',score=2.1),dict(id='001-B',score=-1)])
        with patch('po_reader.candidate_services.request_json',return_value=response) as request:
            ranked = LoopbackReranker().rank(dict(description='Widget A'), candidates)
        self.assertEqual(ranked[0]['product_id'],'001-A')
        self.assertEqual(ranked[0]['variants'],['A'])
        self.assertNotIn('rank_score',candidates[0])
        self.assertTrue(request.call_args.args[0].endswith('/rerank'))

    def test_catalog_embedding_batches_require_same_dimension(self):
        catalog = {str(i):dict(name=str(i),variants=[],provenance=[]) for i in range(33)}
        response = [{'embeddings': [[1,0] for _ in range(32)]}, {'embeddings': [[1]]}]
        with patch('po_reader.candidate_services.request_json',side_effect=response):
            result = OllamaSemanticRetriever().retrieve(dict(description='widget'),catalog,
                dict(hits=[],exact_product_ids=[],exact_bindings=[]))
        self.assertEqual(result['semantic_retrieval']['status'],'unavailable')

    def test_reranker_unknown_or_duplicate_id_rejected(self):
        for rows in ([dict(id='invented',score=2)], [dict(id='001-A',score=2),dict(id='001-A',score=1)]):
            response = dict(model='Qwen/Qwen3-Reranker-0.6B',results=rows)
            with patch('po_reader.candidate_services.request_json',return_value=response):
                with self.assertRaises(ProviderError):
                    LoopbackReranker().rank(dict(description='A'),[dict(product_id='001-A',name='A',variants=[])])
