"""Explicitly authorized LOCAL-ONLY decode checks and fictional structural dry runs.

Profiles are private, hand-authored structural notes, never extraction gold.
Original bytes are uploaded/validated locally but never given to a provider.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from uuid import uuid4
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from poc_demo_support import (DATA, OUTPUT, ROOT, FixedProvider, app_settings, local_database,
    offline_boundary, ok, payload_for, process_fixture, render_source, seed_catalog, write_json)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--profiles', required=True, type=Path)
    parser.add_argument('--authorized-local-only', action='store_true')
    parser.add_argument('--postgres-bin')
    args = parser.parse_args()
    if not args.authorized_local_only:
        parser.error('local-only source authorization is required')
    if not args.profiles.resolve().is_relative_to(DATA.resolve()):
        parser.error('structural profiles must stay in this desk\'s ignored data')
    offline_boundary()
    import pymupdf
    from backend.app import create_app
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session
    from backend.models import ProcessingRun, ProviderAttempt
    from uuid import UUID
    import backend.website as website

    profiles = json.loads(args.profiles.read_text(encoding='utf-8'))
    surrogate_directory = DATA / 'structural-surrogates'
    surrogate_directory.mkdir(parents=True, exist_ok=True)
    snapshots = DATA / 'local-corpus'
    snapshots.mkdir(parents=True, exist_ok=True)
    private_records, registry, failures = [], [], []
    with local_database(args.postgres_bin) as (engine, owner):
        scope = seed_catalog(engine)
        provider = FixedProvider()
        website.CORPUS = DATA / 'empty-corpus'
        website.CORPUS.mkdir(parents=True, exist_ok=True)
        settings = app_settings(engine, 8020)
        app = create_app(settings, engine=engine, provider=provider)
        with zipfile.ZipFile(args.archive) as archive, TestClient(app, base_url='http://127.0.0.1:8020', headers={
                'X-Local-Token': settings.local_api_token.get_secret_value(), 'X-Tenant-ID': scope['tenant_id']}) as client:
            names = sorted(name for name in archive.namelist() if name.lower().endswith('.pdf'))
            if len(names) != 33 or len(profiles) != len(names):
                raise RuntimeError('Expected 33 source profiles and 33 PDF entries')
            for index, name in enumerate(names, 1):
                label = f'PO-{index:02}'
                try:
                    source = archive.read(name)
                    source_hash = sha256(source).hexdigest()
                    document = pymupdf.open(stream=source, filetype='pdf')
                    page_count = len(document)
                    if document.needs_pass or page_count != len(profiles[index - 1]['page_rows']):
                        raise ValueError('source_profile_page_mismatch')
                    for page in document:
                        page.get_pixmap(matrix=pymupdf.Matrix(.2, .2), alpha=False)
                    document.close()
                    (snapshots / (source_hash + '.pdf')).write_bytes(source)
                    uploaded = ok(client.post('/documents', headers={'Idempotency-Key': uuid4().hex},
                        data={'vendor_id': scope['vendor_id']}, files={'file': ('opaque-source.pdf', source, 'application/pdf')}))
                    if uploaded['page_count'] != page_count:
                        raise ValueError('local_decoder_page_mismatch')
                    case = {'id': f'fictional-structure-{index:02}'}
                    payload = payload_for(case, profiles[index - 1]['page_rows'])
                    data = render_source(payload)
                    filename = case['id'] + '.pdf'
                    (surrogate_directory / filename).write_bytes(data)
                    provider.register(data, 'application/pdf', payload)
                    result = process_fixture(client, scope, data, 'application/pdf')
                    registry.append({'filename': filename, 'payload': payload})
                    private_records.append({'label': label, 'filename': name, 'source_sha256': source_hash,
                        'original_source_id': uploaded['id'], 'original_page_count': page_count, 'original_upload_validated': True,
                        'original_provider_attempts': 0, 'surrogate_rows': len(payload['rows']),
                        'surrogate_page_count': len(payload['pages']), 'fictional_dry_run': result})
                except Exception as error:
                    # Do not log filenames, original text, source fields or exception messages.
                    failures.append({'label': label, 'error_type': type(error).__name__})
        write_json(surrogate_directory / 'registry.json', registry)
        write_json(OUTPUT / 'local-corpus-private.json', {'records': private_records, 'failures': failures})
        with Session(engine) as session:
            original_attempts = session.scalar(select(func.count(ProviderAttempt.id)).join(ProcessingRun,
                ProviderAttempt.run_id == ProcessingRun.id).where(ProcessingRun.source_document_id.in_(
                    [UUID(record['original_source_id']) for record in private_records])))
        if original_attempts:
            raise RuntimeError('Original-source provider attempt detected; stop for investigation')
        report = {'original_documents': len(names), 'original_pages': sum(r['original_page_count'] for r in private_records),
                  'validated_original_uploads': len(private_records), 'original_provider_attempts': original_attempts,
                  'fictional_structural_runs': len(registry), 'fictional_structural_rows': sum(len(r['payload']['rows']) for r in registry),
                  'surrogate_pages': sum(len(r['payload']['pages']) for r in registry), 'failed': len(failures),
                  'tiers_seen': sorted({tier for r in private_records for tier in r['fictional_dry_run']['tiers']}),
                  'external_provider_calls': 0, 'cost_usd': 0,
                  'limitations': 'Hand-authored fictional structural cases; no OCR, source grounding, completeness or accuracy measurement.'}
        write_json(OUTPUT / 'corpus-summary.json', report)
        print(json.dumps(report, indent=2))
        if failures:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
