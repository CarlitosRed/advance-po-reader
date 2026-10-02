import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from reranker_server import (
    MODEL, MODEL_REVISION, MAX_BODY_BYTES, MAX_DOCUMENTS,
    RequestError, RerankerConfig, RerankerEngine, ServiceUnavailable,
    create_server, validate_request,
)


class FakeCrossEncoder:
    """Protocol fixture only; these scores do not measure a real model."""

    def __init__(self, scores):
        self.scores = scores
        self.calls = []

    def predict(self, pairs, **options):
        self.calls.append((pairs, options))
        return self.scores


def request_payload():
    return {
        "model": MODEL, "query": "printed request",
        "documents": [
            {"id": "catalog-9", "text": "first candidate"},
            {"id": "catalog-3", "text": "second candidate"},
            {"id": "catalog-6", "text": "third candidate"},
        ],
        "top_n": 2,
    }


class RerankerEngineTests(unittest.TestCase):
    def test_lazy_load_preserves_ids_indices_and_raw_logits(self):
        model = FakeCrossEncoder([-11.375, 7.625, 7.625])
        loads = []

        def loader(config):
            loads.append(config)
            return model, MODEL_REVISION

        engine = RerankerEngine(RerankerConfig(), loader=loader)
        health = engine.health()
        self.assertEqual(health["status"], "unloaded")
        self.assertFalse(health["ready"])
        self.assertIsNone(health["model_revision"])
        self.assertEqual(loads, [])
        result = engine.rerank(request_payload())
        self.assertEqual(set(result), {"model", "model_revision", "results"})
        self.assertEqual(result["model"], MODEL)
        self.assertEqual(result["model_revision"], MODEL_REVISION)
        self.assertEqual(result["results"], [
            {"id": "catalog-3", "index": 1, "score": 7.625},
            {"id": "catalog-6", "index": 2, "score": 7.625},
        ])
        self.assertEqual(model.calls[0][0], [
            ("printed request", "first candidate"),
            ("printed request", "second candidate"),
            ("printed request", "third candidate"),
        ])
        self.assertTrue(engine.health()["ready"])
        engine.rerank(request_payload())
        self.assertEqual(len(loads), 1)

    def test_invalid_request_never_loads_model(self):
        def forbidden_loader(config):
            self.fail("invalid request must not load the model")

        engine = RerankerEngine(RerankerConfig(), loader=forbidden_loader)
        cases = []
        for field, value in (("model", "other/model"), ("top_n", True), ("query", "")):
            payload = request_payload()
            payload[field] = value
            cases.append(payload)
        duplicate = request_payload()
        duplicate["documents"][1]["id"] = duplicate["documents"][0]["id"]
        cases.append(duplicate)
        oversized = request_payload()
        oversized["documents"] = [{"id": str(i), "text": "candidate"} for i in range(MAX_DOCUMENTS + 1)]
        cases.append(oversized)
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(RequestError):
                engine.rerank(payload)

    def test_loading_state_and_busy_request_are_visible(self):
        loading = threading.Event()
        release = threading.Event()
        results = []

        def loader(config):
            loading.set()
            if not release.wait(timeout=2):
                raise RuntimeError("fixture load timed out")
            return FakeCrossEncoder([0, 1, 2]), MODEL_REVISION

        engine = RerankerEngine(RerankerConfig(), loader=loader)
        worker = threading.Thread(target=lambda: results.append(engine.rerank(request_payload())))
        worker.start()
        try:
            self.assertTrue(loading.wait(timeout=2))
            self.assertTrue(engine.health()["loading"])
            self.assertFalse(engine.health()["ready"])
            with self.assertRaises(ServiceUnavailable):
                engine.rerank(request_payload())
        finally:
            release.set()
            worker.join(timeout=2)
        self.assertEqual(len(results), 1)
        self.assertFalse(engine.health()["busy"])

    def test_load_failure_remains_unready(self):
        def loader(config):
            raise ImportError("optional package missing")

        engine = RerankerEngine(RerankerConfig(), loader=loader)
        with self.assertRaises(ServiceUnavailable):
            engine.rerank(request_payload())
        health = engine.health()
        self.assertEqual(health["status"], "error")
        self.assertFalse(health["ready"])
        self.assertIn("ImportError", health["error"])

    def test_nonfinite_scores_are_not_serialized_as_results(self):
        engine = RerankerEngine(
            RerankerConfig(), loader=lambda config: (FakeCrossEncoder([0, float("nan"), 2]), MODEL_REVISION)
        )
        with self.assertRaisesRegex(RuntimeError, "non-finite"):
            engine.rerank(request_payload())


class RerankerHTTPTests(unittest.TestCase):
    def setUp(self):
        self.model = FakeCrossEncoder([-4.0, 8.0, 1.0])
        engine = RerankerEngine(RerankerConfig(), loader=lambda config: (self.model, MODEL_REVISION))
        self.server = create_server(engine, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_health_and_rerank_http_schema(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        with urlopen(self.url + "/health", timeout=3) as response:
            self.assertFalse(json.load(response)["ready"])
        request = Request(
            self.url + "/rerank", data=json.dumps(request_payload()).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urlopen(request, timeout=3) as response:
            result = json.load(response)
        self.assertEqual(result["results"], [
            {"id": "catalog-3", "index": 1, "score": 8.0},
            {"id": "catalog-6", "index": 2, "score": 1.0},
        ])
        with urlopen(self.url + "/health", timeout=3) as response:
            health = json.load(response)
        self.assertTrue(health["ready"])
        self.assertEqual(health["model_revision"], MODEL_REVISION)

    def test_http_body_bound_and_content_type(self):
        oversized = Request(
            self.url + "/rerank", data=b"x" * (MAX_BODY_BYTES + 1),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        wrong_type = Request(self.url + "/rerank", data=b"{}", method="POST")
        malformed = Request(
            self.url + "/rerank", data=b"{",
            headers={"Content-Type": "application/json"}, method="POST",
        )
        for request, status in ((oversized, 413), (wrong_type, 415), (malformed, 400)):
            with self.subTest(status=status), self.assertRaises(HTTPError) as error:
                urlopen(request, timeout=3)
            self.assertEqual(error.exception.code, status)
            error.exception.close()
        self.assertEqual(self.model.calls, [])


if __name__ == "__main__":
    unittest.main()
