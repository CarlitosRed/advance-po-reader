"""One-command offline POC; all extraction uses hash-bound fictional fixtures."""
import argparse
import json
from pathlib import Path
import socket
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from poc_demo_support import (DATA, FIXTURES, OUTPUT, ROOT, FixedProvider, app_settings,
    load_catalog, local_database, offline_boundary, payload_for, process_fixture, render_source, seed_catalog, write_json)


def prepare_app(engine, port, catalog_file=None):
    from backend.app import create_app
    import backend.website as website
    from fastapi import Request
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.testclient import TestClient

    scope = seed_catalog(engine, catalog_file)
    products = load_catalog(catalog_file)['products']
    provider = FixedProvider()
    cases = json.loads((FIXTURES / 'cases.json').read_text(encoding='utf-8'))['cases']
    generated = DATA / 'generated'
    generated.mkdir(parents=True, exist_ok=True)
    files = {}
    for case in cases:
        payload = payload_for(case, catalog=products)
        for media, extension in [('application/pdf', 'pdf'), ('image/png', 'png'), ('image/jpeg', 'jpg')]:
            data = render_source(payload, media)
            key = case['id'] + '.' + extension
            path = generated / key
            path.write_bytes(data)
            provider.register(data, media, payload)
            files[key] = {'path': path, 'media_type': media, 'payload': payload, 'title': case['title']}
    # Load only this desk's generated surrogate registry, never a source archive.
    surrogate_registry = DATA / 'structural-surrogates' / 'registry.json'
    if surrogate_registry.exists():
        for item in json.loads(surrogate_registry.read_text(encoding='utf-8')):
            path = DATA / 'structural-surrogates' / item['filename']
            if path.parent.resolve() != (DATA / 'structural-surrogates').resolve():
                raise RuntimeError('Invalid surrogate registry path')
            provider.register(path.read_bytes(), 'application/pdf', item['payload'])
    website.CORPUS = DATA / 'empty-corpus'
    website.CORPUS.mkdir(parents=True, exist_ok=True)
    settings = app_settings(engine, port)
    app = create_app(settings, engine=engine, provider=provider)

    @app.middleware('http')
    async def free_runs_only(request: Request, call_next):
        if request.method == 'POST' and request.url.path.startswith('/documents/') and request.url.path.endswith('/runs'):
            try:
                if (await request.json()).get('provider') != 'synthetic':
                    return JSONResponse({'error': 'poc_offline_only_use_demo_entry'}, status_code=409)
            except ValueError:
                return JSONResponse({'error': 'invalid_request'}, status_code=422)
        return await call_next(request)

    with TestClient(app, base_url=f'http://127.0.0.1:{port}', headers={
            'X-Local-Token': settings.local_api_token.get_secret_value(), 'X-Tenant-ID': scope['tenant_id']}) as client:
        prepared = []
        for case in cases:
            key = case['id'] + '.pdf'
            receipt = process_fixture(client, scope, files[key]['path'].read_bytes(), 'application/pdf')
            prepared.append({'id': case['id'], 'title': case['title'], **receipt})
    info = {'fictional': True, 'provider': provider.model, 'external_provider_calls': 0, 'cost_usd': 0,
            'tenant_id': scope['tenant_id'], 'vendor_id': scope['vendor_id'], 'product_count': scope['product_count'],
            'cases': prepared, 'files': list(files)}
    write_json(OUTPUT / 'demo-ready.json', info)

    @app.get('/poc-demo', include_in_schema=False)
    def entry():
        return FileResponse(ROOT / 'scripts/poc-demo.html', media_type='text/html', headers={'Cache-Control': 'no-store'})

    @app.get('/poc-demo/ui.js', include_in_schema=False)
    def script():
        return FileResponse(ROOT / 'scripts/poc-demo-ui.js', media_type='application/javascript')

    @app.get('/poc-demo/info', include_in_schema=False)
    def information(request: Request):
        import hmac
        if not hmac.compare_digest(request.cookies.get(website.COOKIE, ''), app.state.website_cookie):
            return JSONResponse({'error': 'website_session_required'}, status_code=401)
        return info

    @app.get('/poc-demo/files/{key}', include_in_schema=False)
    def download(key: str):
        if key not in files:
            return JSONResponse({'error': 'fixture_not_found'}, status_code=404)
        return FileResponse(files[key]['path'], media_type=files[key]['media_type'], filename=key)

    return app, provider, settings, scope, files, info


def prepare_live_app(engine, port, catalog_file=None, rehearsal=False):
    """Live mode: documents go to OpenAI only after a per-file confirmation. Rehearsal uses a fake transport."""
    from backend.app import create_app
    from backend.providers import OpenAIProvider
    import backend.website as website
    from fastapi import Request
    from fastapi.responses import FileResponse, JSONResponse
    import poc_live_support as live

    scope = seed_catalog(engine, catalog_file)
    website.CORPUS = DATA / 'empty-corpus'
    website.CORPUS.mkdir(parents=True, exist_ok=True)
    settings = live.live_settings(engine, port, DATA, rehearsal)
    provider = None
    if rehearsal:
        cases = json.loads((FIXTURES / 'cases.json').read_text(encoding='utf-8'))['cases']
        products = load_catalog(catalog_file)['products']
        provider = OpenAIProvider(api_key=settings.openai_api_key.get_secret_value(), enabled=True,
                                  model=settings.extraction_model, timeout_seconds=settings.provider_timeout_seconds,
                                  transport=live.rehearsal_transport(payload_for(cases[0], catalog=products)))
    if live.images_mode_enabled():
        provider = live.PdfAsImageProvider(provider or OpenAIProvider(
            api_key=settings.openai_api_key.get_secret_value(), enabled=True, model=settings.extraction_model,
            store=settings.provider_store, timeout_seconds=settings.provider_timeout_seconds))
    app = create_app(settings, engine=engine, provider=provider)
    guard = live.SpendGuard(engine)
    live.install_live_guard(app, guard)
    info = {'live': True, 'rehearsal': rehearsal, 'model': 'rehearsal-fake-model' if rehearsal else settings.extraction_model,
            'pdf_as_images': live.images_mode_enabled(), 'tenant_id': scope['tenant_id'], 'vendor_id': scope['vendor_id'],
            'product_count': scope['product_count'], 'cases': [], 'files': []}
    write_json(OUTPUT / 'demo-ready.json', {k: v for k, v in info.items() if k != 'tenant_id'})

    def session_ok(request):
        import hmac
        return hmac.compare_digest(request.cookies.get(website.COOKIE, ''), app.state.website_cookie)

    @app.get('/poc-demo', include_in_schema=False)
    def entry():
        return FileResponse(ROOT / 'scripts/poc-demo.html', media_type='text/html', headers={'Cache-Control': 'no-store'})

    @app.get('/poc-demo/ui.js', include_in_schema=False)
    def script():
        return FileResponse(ROOT / 'scripts/poc-demo-ui.js', media_type='application/javascript')

    @app.get('/poc-demo/info', include_in_schema=False)
    def information(request: Request):
        return info if session_ok(request) else JSONResponse({'error': 'website_session_required'}, status_code=401)

    @app.get('/poc-demo/live-status', include_in_schema=False)
    def live_status(request: Request):
        return guard.status() if session_ok(request) else JSONResponse({'error': 'website_session_required'}, status_code=401)

    return app, settings, scope, info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres-bin')
    parser.add_argument('--port', type=int, default=8020)
    parser.add_argument('--catalog-file', help='Optional private catalog JSON stored OUTSIDE the repository (same shape as fixtures/poc-demo/catalog.json); use with --fresh-database')
    parser.add_argument('--fresh-database', action='store_true', help='Select a new demo DB; preserve all previous evidence')
    parser.add_argument('--live', action='store_true', help='Live mode: send documents to OpenAI after a per-file confirmation (needs the key in .env.backend)')
    parser.add_argument('--live-rehearsal', action='store_true', help='Run the live screens against a fake OpenAI transport: no key, no network')
    parser.add_argument('--prepare-only', action='store_true', help='Prepare and verify without retaining a server')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('port must be between 1024 and 65535')
    if args.live and args.live_rehearsal:
        parser.error('choose --live or --live-rehearsal, not both')
    if args.live:
        import poc_live_support
        try:
            poc_live_support.check_live_settings()
        except poc_live_support.LiveRefusal as refusal:
            print(refusal, flush=True)
            sys.exit(2)
        # Live mode talks to OpenAI with the server's own settings, so the offline guards are not installed.
    else:
        offline_boundary(block_providers=not args.live_rehearsal)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', args.port))  # Refuse occupied ports; never stop another service.
    with local_database(args.postgres_bin, fresh=args.fresh_database) as (engine, owner):
        if args.live or args.live_rehearsal:
            app, settings, scope, info = prepare_live_app(engine, args.port, args.catalog_file, args.live_rehearsal)
            write_json(OUTPUT / 'runtime.json', {'desk': str(ROOT), 'port': args.port, 'database': owner['database'],
                       'database_port': owner['port'], 'live_processing_enabled': True, 'rehearsal': args.live_rehearsal})
            print(f"{'Live rehearsal (fake transport, no key, no network)' if args.live_rehearsal else 'Live POC'} ready: "
                  f"{scope['product_count']} catalog products; model {info['model']}.", flush=True)
            print(f"Open http://127.0.0.1:{args.port}/poc-demo", flush=True)
            if args.prepare_only:
                return
            import uvicorn
            uvicorn.run(app, host='127.0.0.1', port=args.port, access_log=False)
            return
        app, provider, settings, scope, files, info = prepare_app(engine, args.port, args.catalog_file)
        write_json(OUTPUT / 'runtime.json', {'desk': str(ROOT), 'port': args.port, 'database': owner['database'],
                   'database_port': owner['port'], 'live_processing_enabled': False, 'provider_key_present': False})
        print(f"Free POC ready: {scope['product_count']} {'products from the private catalog file' if args.catalog_file else 'fictional products'}; three review cases; zero external calls.", flush=True)
        print(f"Open http://127.0.0.1:{args.port}/poc-demo", flush=True)
        if args.prepare_only:
            return
        import uvicorn
        uvicorn.run(app, host='127.0.0.1', port=args.port, access_log=False)


if __name__ == '__main__':
    main()
