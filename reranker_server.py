"""Optional, CPU-only Qwen3 cross-encoder service. No training or eager downloads."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import re
import threading
from typing import Any, Callable


MODEL = "Qwen/Qwen3-Reranker-0.6B"
# Official model revision verified on October 1, 2026, including LogitScore modules.
MODEL_REVISION = "e61197ed45024b0ed8a2d74b80b4d909f1255473"
MAX_BODY_BYTES = 256 * 1024
MAX_DOCUMENTS = 50
MAX_QUERY_CHARS = 1024
MAX_DOCUMENT_CHARS = 4096


class RequestError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class ServiceUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class RerankerConfig:
    revision: str = MODEL_REVISION
    cpu_threads: int = 4
    batch_size: int = 1
    max_length: int = 2048
    cache_dir: Path = Path(__file__).resolve().parent / "data/models/reranker"
    local_files_only: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.revision, str) or not self.revision.strip():
            raise ValueError("revision must be a nonempty Hugging Face revision")
        for name, low, high in (
            ("cpu_threads", 1, 16), ("batch_size", 1, 8), ("max_length", 256, 8192)
        ):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{name} must be an integer between {low} and {high}")


def load_cross_encoder(config: RerankerConfig) -> tuple[Any, str | None]:
    """Import optional packages only when a real reranking request arrives."""
    import torch
    from sentence_transformers import CrossEncoder

    torch.set_num_threads(config.cpu_threads)
    # Identity preserves the yes-minus-no logit score used by Qwen's LogitScore.
    model = CrossEncoder(
        MODEL,
        device="cpu",
        revision=config.revision,
        cache_folder=str(config.cache_dir),
        local_files_only=config.local_files_only,
        trust_remote_code=False,
        model_kwargs={"dtype": torch.float32, "use_safetensors": True},
        max_length=config.max_length,
        activation_fn=torch.nn.Identity(),
        prompts={
            "query": "Given a purchase order product request, retrieve catalog products "
            "that match the requested product, identifiers, specifications and unit."
        },
        default_prompt_name="query",
    )
    resolved = getattr(model.config, "_commit_hash", None)
    if resolved is None and re.fullmatch(r"[0-9a-fA-F]{40}", config.revision):
        resolved = config.revision
    return model, resolved


def validate_request(payload: Any) -> tuple[str, list[dict[str, str]], int]:
    if not isinstance(payload, dict):
        raise RequestError("request must be a JSON object")
    if set(payload) != {"model", "query", "documents", "top_n"}:
        raise RequestError("required fields: model, query, documents, top_n")
    if payload["model"] != MODEL:
        raise RequestError(f"supported model is {MODEL}")
    query = payload["query"]
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_CHARS:
        raise RequestError(f"query must be nonempty text of at most {MAX_QUERY_CHARS} characters")
    documents = payload["documents"]
    if not isinstance(documents, list) or not 1 <= len(documents) <= MAX_DOCUMENTS:
        raise RequestError(f"documents must contain between 1 and {MAX_DOCUMENTS} items")
    seen_ids: set[str] = set()
    for document in documents:
        if not isinstance(document, dict) or set(document) != {"id", "text"}:
            raise RequestError("each document requires only id and text")
        doc_id, text = document["id"], document["text"]
        if not isinstance(doc_id, str) or not doc_id.strip() or len(doc_id) > 128:
            raise RequestError("document id must be nonempty text of at most 128 characters")
        if doc_id in seen_ids:
            raise RequestError("document ids must be unique")
        seen_ids.add(doc_id)
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_DOCUMENT_CHARS:
            raise RequestError(f"document text must contain 1 to {MAX_DOCUMENT_CHARS} characters")
    top_n = payload["top_n"]
    if type(top_n) is not int or not 1 <= top_n <= len(documents):
        raise RequestError("top_n must be an integer between 1 and the document count")
    return query, documents, top_n


class RerankerEngine:
    def __init__(
        self,
        config: RerankerConfig,
        loader: Callable[[RerankerConfig], tuple[Any, str | None]] = load_cross_encoder,
    ) -> None:
        self.config = config
        self._loader = loader
        self._model: Any = None
        self._model_revision: str | None = None
        self._state = "unloaded"
        self._error: str | None = None
        self._state_lock = threading.Lock()
        self._inference_lock = threading.Lock()

    def health(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                "model": MODEL,
                "requested_revision": self.config.revision,
                "model_revision": self._model_revision,
                "status": self._state,
                "ready": self._model is not None and self._state == "ready",
                "loading": self._state == "loading",
                "busy": self._inference_lock.locked(),
                "device": "cpu",
                "cpu_threads": self.config.cpu_threads,
                "batch_size": self.config.batch_size,
                "max_length": self.config.max_length,
                "local_files_only": self.config.local_files_only,
                "score_type": "yes_minus_no_logit",
                "error": self._error,
            }

    def rerank(self, payload: Any) -> dict[str, Any]:
        query, documents, top_n = validate_request(payload)
        if not self._inference_lock.acquire(blocking=False):
            raise ServiceUnavailable("reranker is busy loading or scoring; retry later")
        try:
            if self._model is None:
                with self._state_lock:
                    self._state, self._error = "loading", None
                try:
                    model, revision = self._loader(self.config)
                    with self._state_lock:
                        self._model, self._model_revision = model, revision
                        self._state = "ready"
                except Exception as exc:
                    with self._state_lock:
                        self._state = "error"
                        self._error = f"{type(exc).__name__}: {exc}"
                    raise ServiceUnavailable("model loading failed; inspect /health") from exc
            pairs = [(query, document["text"]) for document in documents]
            scores = self._model.predict(
                pairs, batch_size=self.config.batch_size,
                show_progress_bar=False, convert_to_numpy=True,
            )
            if len(scores) != len(documents):
                raise RuntimeError("model returned a different score count from document count")
            results = []
            for index, (document, score) in enumerate(zip(documents, scores)):
                value = float(score)
                if not math.isfinite(value):
                    raise RuntimeError("model returned a non-finite score")
                results.append({"id": document["id"], "index": index, "score": value})
            # Stable ties retain input order, with catalog IDs and original indices intact.
            results.sort(key=lambda result: (-result["score"], result["index"]))
            return {"model": MODEL, "model_revision": self._model_revision, "results": results[:top_n]}
        finally:
            self._inference_lock.release()


def create_server(engine: RerankerEngine, port: int = 11436) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, format: str, *args: Any) -> None:
            # Do not log customer query strings or document bodies.
            pass

        def respond(self, status: int, data: dict[str, Any]) -> None:
            body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path != "/health":
                self.respond(404, {"error": "route not found"})
                return
            self.respond(200, engine.health())

        def do_POST(self) -> None:
            if self.path != "/rerank":
                self.respond(404, {"error": "route not found"})
                return
            try:
                if self.headers.get("Transfer-Encoding"):
                    raise RequestError("transfer encoding is not supported")
                if self.headers.get_content_type() != "application/json":
                    raise RequestError("Content-Type must be application/json", 415)
                raw_length = self.headers.get("Content-Length")
                if raw_length is None:
                    raise RequestError("Content-Length is required", 411)
                try:
                    length = int(raw_length)
                except ValueError as exc:
                    raise RequestError("Content-Length must be an integer") from exc
                if not 0 < length <= MAX_BODY_BYTES:
                    raise RequestError(f"body must contain 1 to {MAX_BODY_BYTES} bytes", 413)
                body = self.rfile.read(length)
                if len(body) != length:
                    raise RequestError("incomplete request body")
                try:
                    payload = json.loads(body)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise RequestError("body must contain valid UTF-8 JSON") from exc
                self.respond(200, engine.rerank(payload))
            except RequestError as exc:
                self.respond(exc.status, {"error": str(exc)})
            except ServiceUnavailable as exc:
                self.respond(503, {"error": str(exc)})
            except (TimeoutError, OSError):
                self.close_connection = True
            except Exception:
                self.respond(500, {"error": "model scoring failed"})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=11436)
    parser.add_argument("--revision", default=MODEL_REVISION)
    parser.add_argument("--cpu-threads", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--max-length", type=int, default=2048)
    parser.add_argument("--cache-dir", type=Path, default=RerankerConfig.cache_dir)
    parser.add_argument("--local-files-only", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    try:
        config = RerankerConfig(
            revision=args.revision, cpu_threads=args.cpu_threads,
            batch_size=args.batch_size, max_length=args.max_length,
            cache_dir=args.cache_dir, local_files_only=args.local_files_only,
        )
    except ValueError as exc:
        parser.error(str(exc))
    server = create_server(RerankerEngine(config), port=args.port)
    print(f"Reranker listening at http://127.0.0.1:{args.port}; model loads on first /rerank", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
