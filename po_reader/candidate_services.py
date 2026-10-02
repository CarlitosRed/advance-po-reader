"""Local candidate services. Ranking signals never alter printed identifiers."""
import copy
import hashlib
import json
import math
import urllib.parse
import urllib.request

from .catalog import normalize_id, similarity
from .model_provider import ProviderError


def loopback_url(value):
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme not in ('http', 'https') or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
            or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password):
        raise ValueError('Candidate services require a loopback server URL without a path or credentials')
    return value.rstrip('/')


def request_json(url, payload=None, timeout=60):
    raw = None if payload is None else json.dumps(payload).encode('utf-8')
    request = urllib.request.Request(url, data=raw, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(8 * 1024 * 1024 + 1)
        if len(body) > 8 * 1024 * 1024:
            raise ProviderError('Candidate service response exceeds its byte limit')
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError('Response must be an object')
        return value
    except (OSError, ValueError) as exc:
        raise ProviderError('Candidate service unavailable or returned an invalid response') from exc


def confusion_distance(left, right):
    """Bounded weighted edit distance for suggestions, never identifier binding."""
    if max(len(left), len(right)) > 64:
        return float('inf')
    confusions = [set(pair) for pair in ('0O', '1IL', '5S', '8B', '2Z', '7T')]
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            cost = 0 if a == b else .25 if any(a in pair and b in pair for pair in confusions) else 1
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j-1] + cost))
        previous = current
    return previous[-1]


def _text(product):
    return '\n'.join([product['name'], *product.get('variants', [])])


def _hit(identifier, product, method, **scores):
    return dict(product_id=identifier, name=product['name'], variants=product.get('variants', []),
                source_observations=product.get('provenance', []), method=method, **scores)


class OllamaSemanticRetriever:
    """Cached real embeddings plus bounded visual-confusion candidates."""
    def __init__(self, model='qwen3-embedding:0.6b', base_url='http://127.0.0.1:11435', timeout=120, limit=5):
        self.model, self.base_url = model, loopback_url(base_url)
        self.timeout, self.limit = timeout, limit
        self._cache_key, self._vectors = None, None
        self._unavailable = False
        self.usage = []

    def _embed(self, texts):
        response = request_json(self.base_url + '/api/embed', dict(model=self.model, input=texts,
                                truncate=False, keep_alive='0'), self.timeout)
        vectors = response.get('embeddings')
        if not isinstance(vectors, list) or len(vectors) != len(texts) or not vectors:
            raise ProviderError('Embedding response has the wrong number of vectors')
        dimension = len(vectors[0]) if isinstance(vectors[0], list) else 0
        if not dimension or any(not isinstance(v, list) or len(v) != dimension or
                any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in v)
                or not any(v) for v in vectors):
            raise ProviderError('Embedding response contains invalid vectors')
        self.usage.append(dict(stage='semantic_embedding', model=self.model, input_count=len(texts),
                               dimension=dimension, prompt_tokens=response.get('prompt_eval_count'),
                               total_duration_ns=response.get('total_duration')))
        return vectors

    def retrieve(self, line, catalog, retrieved):
        result = copy.deepcopy(retrieved)
        by_id = {hit['product_id']: hit for hit in result['hits']}
        # Restrict fuzzy suggestions to identifiers with a business role. They
        # remain suggestions even when the visual-confusion cost is very small.
        fuzzy = {}
        for observation in line.get('identifiers', []):
            if observation.get('role') not in ('vendor_product_code', 'manufacturer_part_number'):
                continue
            raw = observation.get('raw_value')
            if not isinstance(raw, str) or len(raw.strip()) < 4:
                continue
            value = normalize_id(raw)
            for identifier in catalog:
                distance = confusion_distance(value, identifier)
                if 0 < distance <= 1:
                    fuzzy[identifier] = min(distance, fuzzy.get(identifier, float('inf')))
        for identifier in sorted(fuzzy, key=lambda i: (fuzzy[i], i))[:self.limit]:
            by_id.setdefault(identifier, _hit(identifier, catalog[identifier], 'visual_confusion_suggestion',
                                             weighted_edit_distance=fuzzy[identifier], description_similarity=similarity(line.get('description') or '', catalog[identifier])))
        key = hashlib.sha256(json.dumps(catalog, sort_keys=True).encode()).hexdigest()
        ids = sorted(catalog)
        query = line.get('description') or ''
        semantic_status = 'skipped_empty_query_or_catalog'
        if ids and query.strip() and not self._unavailable:
            try:
                if key != self._cache_key:
                    self._vectors = []
                    for start in range(0, len(ids), 32):
                        self._vectors.extend(self._embed([_text(catalog[i]) for i in ids[start:start+32]]))
                    if any(len(v) != len(self._vectors[0]) for v in self._vectors):
                        self._vectors = None
                        raise ProviderError('Catalog embedding dimensions disagree across batches')
                    self._cache_key = key
                vector = self._embed(['Instruct: Retrieve catalog products matching the purchase order description\nQuery: ' + query])[0]
                if len(vector) != len(self._vectors[0]):
                    raise ProviderError('Query and catalog embedding dimensions disagree')
                def cosine(other):
                    return sum(a*b for a,b in zip(vector, other)) / math.sqrt(sum(a*a for a in vector) * sum(b*b for b in other))
                scores = sorted(((cosine(v), i) for i,v in zip(ids, self._vectors)), key=lambda pair: (-pair[0], pair[1]))
                for score, identifier in scores[:self.limit]:
                    if identifier in by_id:
                        by_id[identifier]['cosine_similarity'] = score
                    else:
                        by_id[identifier] = _hit(identifier, catalog[identifier], 'qwen_embedding_cosine', cosine_similarity=score,
                                                description_similarity=similarity(query, catalog[identifier]))
                semantic_status = 'completed'
            except ProviderError:
                self._unavailable = True
                semantic_status = 'unavailable'
        elif self._unavailable:
            semantic_status = 'unavailable'
        # Preserve every exact binding while bounding other candidates to top-K.
        exact = set(result['exact_product_ids'])
        hits = list(by_id.values())
        hits.sort(key=lambda h: (h['product_id'] not in exact, -h.get('cosine_similarity', -2),
                                  h.get('weighted_edit_distance', 2), h['product_id']))
        original_ids = {h['product_id'] for h in retrieved['hits']}
        result['hits'] = [h for h in hits if h['product_id'] in original_ids] + [h for h in hits if h['product_id'] not in original_ids][:self.limit]
        result['semantic_retrieval'] = dict(status=semantic_status, model=self.model,
                                           score_note='Cosine and edit scores rank suggestions; they are not match probabilities.')
        return result


class LoopbackReranker:
    """Dedicated score endpoint, backed by a real cross-encoder service."""
    def __init__(self, base_url='http://127.0.0.1:11436', model='Qwen/Qwen3-Reranker-0.6B', timeout=120):
        self.base_url, self.model, self.timeout = loopback_url(base_url), model, timeout
        self.usage = []
        self._unavailable = False

    def rank(self, line, candidates):
        if not candidates:
            return []
        if self._unavailable:
            raise ProviderError('Reranker is unavailable for this run')
        try:
            response = request_json(self.base_url + '/rerank', dict(model=self.model,
                    query=line.get('description') or '',
                    documents=[dict(id=c['product_id'], text=_text(c)) for c in candidates],
                    top_n=len(candidates)), self.timeout)
            results = response.get('results')
            expected = {c['product_id'] for c in candidates}
            if response.get('model') != self.model or not isinstance(results, list) or len(results) != len(expected):
                raise ProviderError('Reranker returned invalid model or candidate count')
            seen = set()
            scores = {}
            for record in results:
                identifier, score = record.get('id'), record.get('score')
                if identifier not in expected or identifier in seen or isinstance(score, bool) or not isinstance(score, (int,float)) or not math.isfinite(score):
                    raise ProviderError('Reranker returned an invalid identifier or score')
                seen.add(identifier)
                scores[identifier] = score
            ranked = [dict(c, rank_score=scores[c['product_id']]) for c in candidates]
            ranked.sort(key=lambda c: (-c['rank_score'], c['product_id']))
            self.usage.append(dict(stage='candidate_reranking', model=self.model, revision=response.get('model_revision'),
                                   count=len(ranked), score_type='cross_encoder_logit_difference'))
            return ranked
        except (ProviderError, AttributeError, TypeError) as exc:
            self._unavailable = True
            raise ProviderError('Reranker unavailable or returned invalid candidate scores') from exc
