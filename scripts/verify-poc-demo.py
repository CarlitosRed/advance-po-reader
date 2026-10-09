"""Meaningful negative-boundary, seed-idempotency and reset-preservation checks."""
import argparse
import importlib.util
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from poc_demo_support import (OUTPUT, FixedProvider, local_database, offline_boundary, ok,
                              seed_catalog, write_json)


def must_refuse(operation):
    try:
        operation()
    except RuntimeError:
        return
    raise AssertionError('Offline guard did not refuse the operation')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres-bin')
    parser.add_argument('--fresh-proof', action='store_true')
    args = parser.parse_args()
    offline_boundary()
    import httpx
    from backend.providers import OpenAIProvider
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, text

    must_refuse(lambda: Path('.env.forbidden-poc-check').read_bytes())
    must_refuse(lambda: httpx.HTTPTransport().handle_request(httpx.Request('GET', 'https://example.invalid')))
    must_refuse(lambda: OpenAIProvider.extract(None, b'', 'application/pdf', 1))
    spec = importlib.util.spec_from_file_location('poc_demo_entry', Path(__file__).with_name('poc-demo.py'))
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    with local_database(args.postgres_bin) as (engine, owner):
        first = seed_catalog(engine)
        second = seed_catalog(engine)
        assert first['products'] == second['products'], 'Repeated seed changed IDs or content'
        assert len(second['products']) == 153
        previous_url = engine.url
        with engine.connect() as connection:
            previous_counts = tuple(connection.execute(text(
                'SELECT (SELECT count(*) FROM source_documents), (SELECT count(*) FROM processing_runs), '
                '(SELECT count(*) FROM review_events)')).one())
        app, provider, settings, scope, files, info = entry.prepare_app(engine, 8021)
        data = files['demo-three-tiers.pdf']['path'].read_bytes()
        unsupported = provider.extract(data + b'\n% different fictional bytes\n', 'application/pdf', 1)
        assert unsupported.error_code == 'poc_unknown_fixture_bytes' and unsupported.payload is None
        assert settings.openai_api_key is None and settings.live_processing_enabled is False
        with TestClient(app, base_url='http://127.0.0.1:8021', headers={
                'X-Local-Token': settings.local_api_token.get_secret_value(), 'X-Tenant-ID': scope['tenant_id']}) as client:
            source_id = info['cases'][0]['source_id']
            refused = client.post(f'/documents/{source_id}/runs', json={'provider':'openai'},
                                  headers={'Idempotency-Key':'poc-forbidden-live-check'})
            assert refused.status_code == 409 and refused.json()['error'] == 'poc_offline_only_use_demo_entry'
            changed = ok(client.post('/documents', headers={'Idempotency-Key':uuid4().hex},
                data={'vendor_id':scope['vendor_id']}, files={'file':('fictional-unknown.pdf',
                    data + b'\n% different fictional bytes\n', 'application/pdf')}))
            changed_run = ok(client.post(f"/documents/{changed['id']}/runs", json={'provider':'synthetic'},
                                        headers={'Idempotency-Key':uuid4().hex}))
            changed_run = ok(client.post(f"/runs/{changed_run['id']}/process"))
            assert changed_run['state'] == 'failed' and changed_run['outcome_code'] == 'poc_unknown_fixture_bytes'
            assert ok(client.get(f"/runs/{changed_run['id']}/result"))['extraction'] is None
        old_database = owner['database']
    reset_verified = False
    if args.fresh_proof:
        with local_database(args.postgres_bin, fresh=True) as (engine, owner):
            assert owner['database'] != old_database and old_database in owner['history']
            current = seed_catalog(engine)
            assert current['product_count'] == 153
            with engine.connect() as connection:
                assert connection.scalar(text('SELECT count(*) FROM review_events')) == 0
                assert connection.scalar(text('SELECT count(*) FROM processing_runs')) == 0
            previous = create_engine(previous_url)
            try:
                with previous.connect() as connection:
                    preserved_counts = tuple(connection.execute(text(
                        'SELECT (SELECT count(*) FROM source_documents), (SELECT count(*) FROM processing_runs), '
                        '(SELECT count(*) FROM review_events)')).one())
                assert all(after >= before for after, before in zip(preserved_counts, previous_counts))
                reset_verified = True
            finally:
                previous.dispose()
    report = {'seed_idempotent':True, 'fixture_product_count':153, 'dotenv_reads_refused':True,
              'external_http_refused':True, 'builtin_openai_refused':True, 'live_run_creation_refused':True,
              'unknown_source_not_given_fixed_output':True, 'unknown_upload_fails_through_real_api':True,
              'no_key_live_disabled':True,
              'reset_new_database_preserves_previous_evidence':reset_verified, 'external_provider_calls':0}
    write_json(OUTPUT / 'isolation-qa.json', report)
    print(report)


if __name__ == '__main__':
    main()
