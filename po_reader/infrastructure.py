"""Working model configuration and read-only infrastructure readiness."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .candidate_services import LoopbackReranker, OllamaSemanticRetriever, loopback_url, request_json
from .model_provider import ProviderError

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'config/model-stack.json'


def read_config(path=CONFIG):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if value.get('schema_version') != 1 or value.get('training_enabled') is not False:
        raise ValueError('Only schema version 1 with training_enabled=false is supported in this phase')
    loopback_url(value['ollama_url'])
    loopback_url(value['reranker_url'])
    for name in ('extractor_model','adjudicator_model','embedding_model','reranker_model'):
        if not isinstance(value.get(name), str) or not value[name].strip():
            raise ValueError('Missing model configuration: ' + name)
    return value


def build_stack(config_path=CONFIG, extractor_model=None, adjudicator_model=None, base_url=None,
                timeout=None, semantic=True, reranker=True):
    from .model_provider import build_cascade_provider
    config = read_config(config_path)
    endpoint = base_url or config['ollama_url']
    seconds = timeout or config['request_timeout_seconds']
    retriever = (OllamaSemanticRetriever(config['embedding_model'], endpoint, seconds)
                 if semantic and config['semantic_retrieval_enabled'] else None)
    ranker = (LoopbackReranker(config['reranker_url'], config['reranker_model'], seconds)
              if reranker and config['reranker_enabled'] else None)
    return build_cascade_provider(extractor_model or config['extractor_model'],
                                 adjudicator_model or config['adjudicator_model'], endpoint, seconds,
                                 candidate_retriever=retriever, candidate_ranker=ranker)


def readiness(config_path=CONFIG):
    config = read_config(config_path)
    report = dict(schema_version=1, checked_utc=datetime.now(timezone.utc).isoformat(),
                  phase=config['phase'], training_enabled=False, configuration=config,
                  configuration_sha256=hashlib.sha256(Path(config_path).read_bytes()).hexdigest(),
                  components={}, limitations=['Downloaded weights do not establish PDF extraction accuracy.',
                                              'Sample catalog is not an authoritative website catalog.'])
    try:
        version = request_json(config['ollama_url'] + '/api/version', timeout=5)
        tags = request_json(config['ollama_url'] + '/api/tags', timeout=5)
        report['ollama'] = dict(status='reachable', endpoint=config['ollama_url'], version=version.get('version'))
        models = {m['name']:m for m in tags.get('models', [])}
    except ProviderError:
        models = {}
        report['ollama'] = dict(status='unavailable', endpoint=config['ollama_url'])
    for role, key in (('extractor','extractor_model'),('baseline','baseline_model'),
                      ('adjudicator','adjudicator_model'),('embedding','embedding_model')):
        name = config[key]
        installed = models.get(name)
        report['components'][role] = dict(model=name, status='downloaded' if installed else 'not_downloaded',
                    digest=installed.get('digest') if installed else None,
                    size_bytes=installed.get('size') if installed else None,
                    details=installed.get('details') if installed else None,
                    end_to_end_verified=False)
    try:
        health = request_json(config['reranker_url'] + '/health', timeout=5)
        report['components']['reranker'] = dict(model=config['reranker_model'],
                    status='ready' if health.get('ready') and health.get('model') == config['reranker_model'] else 'reachable_not_ready',
                    health=health, end_to_end_verified=False)
    except ProviderError:
        report['components']['reranker'] = dict(model=config['reranker_model'], status='unavailable', end_to_end_verified=False)
    report['components']['verifier'] = dict(model=config['verifier_model'], status=config['verifier_status'], end_to_end_verified=False)
    return report
