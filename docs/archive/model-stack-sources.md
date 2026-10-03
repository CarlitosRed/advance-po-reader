# Verified model deployment sources

**Roadmap status updated October 2, 2026:** these are sources for the preserved Qwen/self-hosted comparison prototype. The current plan is OpenAI-first, then Apple on-device, with Qwen/self-hosting deferred until the first two milestones are measured. These references do not establish the live availability or quality of a future provider. Recheck current sources if Qwen work is later authorized.

Checked October 1, 2026 against official model cards, vendor documentation and PyPI metadata. Research benchmark results are external claims; these references do not establish accuracy on this project's PDFs. Current installed/loaded/verified status belongs in the run's readiness record.

| Component | Verified deployment details | Primary source |
| --- | --- | --- |
| Qwen3-VL-8B-Instruct | Official Ollama tag `qwen3-vl:8b-instruct-q4_K_M`, approximately 6.1 GB Q4_K_M; requires Ollama 0.12.7 or newer. | [Ollama explicit Instruct tag](https://ollama.com/library/qwen3-vl:8b-instruct-q4_K_M), [Qwen model card](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct) |
| Qwen3-Embedding-0.6B | Official Ollama `qwen3-embedding:0.6b`, 639 MB Q8_0, `/api/embed`; authoritative Qwen card lists 1024 dimensions and 32K context. | [Ollama tag](https://ollama.com/library/qwen3-embedding:0.6b), [Qwen card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B), [Embed API](https://docs.ollama.com/api/embed) |
| Qwen3-Reranker-0.6B | Official CrossEncoder pair scoring uses raw yes-minus-no logit differences; sigmoid is optional. This project preserves raw scores, which require calibration before any approval threshold. | [Official Qwen scoring examples](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B), [CrossEncoder reference](https://www.sbert.net/docs/package_reference/cross_encoder/model.html) |
| gpt-oss-20b | Official Ollama `gpt-oss:20b`, approximately 14 GB, text input. This exceeds the local GPU's VRAM, so sequential loading and offloading require measurement. | [Ollama model library](https://ollama.com/library/gpt-oss) |
| PaddleOCR-VL-1.6 | Official full layout-and-VLM pipeline via `PaddleOCRVL(pipeline_version="v1.6")`; PaddlePaddle >=3.2.1 and PaddleOCR doc-parser >=3.6.0. Native x64 CPU path is documented. This project's complete parser runtime and PDF comparison remain pending. | [Official model card](https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6), [Full pipeline guide](https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/PaddleOCR-VL.html) |

The local PC has a Ryzen 7 5800X, 31.9 GiB RAM and RX 6700 XT. The existing project Ollama runtime is version 0.35.0 at `http://127.0.0.1:11435`; its earlier 4B inference logs verify Vulkan GPU offloading and about 12 GiB VRAM. The RX 6700 XT is absent from the official Windows ROCm list, while [Ollama's documented Vulkan backend](https://docs.ollama.com/gpu) supports additional Windows GPUs. Paddle's [AMD tutorial](https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/PaddleOCR-VL-AMD-GPU.html) verifies MI300X only and leaves other AMD hardware unconfirmed. Its accelerated vLLM/SGLang/FastDeploy services cannot run natively on Windows.

## Optional CPU reranker service

`reranker_server.py` is a separate inference process, fixed to IPv4 loopback. It never trains. Python startup and `GET /health` do not import model libraries or download weights. The first valid `POST /rerank` loads the model; `--local-files-only` prevents network weight retrieval and reports a missing cache as an error. Setup installs libraries only. Raw CPU logits use float32 and an explicit Identity activation, with a purchase-order/catalog retrieval instruction.

The default model revision is `e61197ed45024b0ed8a2d74b80b4d909f1255473`, verified from the [official repository API](https://huggingface.co/api/models/Qwen/Qwen3-Reranker-0.6B). This revision's [module manifest](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B/blob/e61197ed45024b0ed8a2d74b80b4d909f1255473/modules.json) uses `Transformer` + `LogitScore`, and its [runtime configuration](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B/blob/e61197ed45024b0ed8a2d74b80b4d909f1255473/config_sentence_transformers.json) records Sentence Transformers 5.4.0. `--revision` accepts a different official commit, tag or branch. `/health` distinguishes the requested revision from the resolved model revision, which stays null before loading.

Selected pins are `sentence-transformers==5.4.1`, `transformers==5.4.0` and `torch==2.11.0+cpu`. [Sentence Transformers PyPI metadata](https://pypi.org/pypi/sentence-transformers/5.4.1/json) requires Python >=3.10, Transformers >=4.41,<6 and Torch >=1.11. [Transformers metadata](https://pypi.org/pypi/transformers/5.4.0/json) requires Python >=3.10. [Torch metadata](https://pypi.org/pypi/torch/2.11.0/json) lists Windows x64 Python 3.10–3.13 wheels, and the [official CPU wheel index](https://download.pytorch.org/whl/cpu/torch/) includes `torch-2.11.0+cpu-cp312-cp312-win_amd64.whl`. [PyTorch's installation guide](https://pytorch.org/get-started/previous-versions/) specifies the CPU index for this version. These are compatible published constraints; real model inference must still be checked after installation. Transitive dependencies are resolved by pip rather than fully locked by this small optional requirements file.

Install in an isolated environment and launch explicitly:

```powershell
.\setup-reranker.ps1
& .\data\tools\reranker-venv\Scripts\python.exe .\reranker_server.py --cpu-threads 4 --port 11436
Invoke-RestMethod http://127.0.0.1:11436/health
```

`GET /health` returns `unloaded`, `loading`, `ready` or `error`; `ready` is true only after loading succeeds. Concurrent scoring requests receive HTTP 503 while one request is loading/scoring. Configure the project's base reranker URL as `http://127.0.0.1:11436`; its request endpoint is `/rerank`.

```json
{
  "model": "Qwen/Qwen3-Reranker-0.6B",
  "query": "latex gloves, medium, box of 100",
  "documents": [
    {"id": "SYNTH-010", "text": "Natural latex examination gloves, medium, 100 per box"},
    {"id": "SYNTH-011", "text": "Nitrile examination gloves, medium, 100 per box"}
  ],
  "top_n": 2
}
```

The response contains `model`, `model_revision` and sorted `results` with original `id`, zero-based input `index` and raw `score`. Ties keep input order. Limits are 256 KiB JSON, 50 unique documents, 1024 query characters, 4096 characters per candidate, 128 characters per ID, and `top_n` between 1 and candidate count. The default tokenizer context is 2048 tokens (`--max-length`, range 256–8192); CrossEncoder truncates longer pairs to that configured context, so keep candidate descriptions concise and record this setting when comparing runs. CPU threads are bounded to 1–16 and batch size to 1–8.

The tests use a fake CrossEncoder solely to verify lazy readiness, request validation, stable ranking, preserved IDs/indices and HTTP JSON. Passing them does not establish real model readiness, speed or accuracy.
