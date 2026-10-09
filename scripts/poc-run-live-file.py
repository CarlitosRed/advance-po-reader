"""Run ONE real document end to end against a running LIVE server, like the browser does.

Upload, create the run with the file-hash authorization, process, then read the result.
The order appears in "Recent orders" afterwards, ready for human review. Needs a server
started with start-poc-demo.ps1 -Live. Refuses without --confirm; the file must be
outside this repository. Prints only states, counts, tokens, latency and estimated cost
(never document text). Sending the file may cost real money.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main(argv=None, client=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm', action='store_true', help='Required: you authorize sending this document to OpenAI once')
    parser.add_argument('--file', required=True, help='The document (outside the repository)')
    parser.add_argument('--base-url', default='http://127.0.0.1:8021')
    parser.add_argument('--timeout', type=int, default=200, help='Seconds to wait for the reading')
    args = parser.parse_args(argv)
    if not args.confirm:
        print('Refused: this sends the document to OpenAI once and may cost real money. Run again with --confirm. Nothing was sent.')
        return 2
    path = Path(args.file).expanduser().resolve()
    if ROOT.resolve() == path or ROOT.resolve() in path.parents or path.name.casefold().startswith('.env') or not path.is_file():
        print('Refused: the file must exist outside this repository. Nothing was sent.')
        return 2
    import httpx
    import poc_live_support as live
    data = path.read_bytes()
    digest = sha256(data).hexdigest()
    media = live.source_media(path)
    own = client is None
    client = client or httpx.Client(base_url=args.base_url, timeout=args.timeout)
    try:
        client.get('/')  # opens the same website session the browser uses
        csrf = client.get('/website/session').json()['csrf']
        info = client.get('/poc-demo/info').json()
        headers = {'X-Tenant-ID': info['tenant_id'], 'X-Website-CSRF': csrf}

        def call(method, url, **kwargs):
            response = client.request(method, url, headers={**headers, **kwargs.pop('headers', {})}, **kwargs)
            if response.status_code >= 400:
                raise SystemExit(f"Stopped at {method} {url.split('/')[1]}: HTTP {response.status_code} {response.json().get('error', '')}")
            return response.json()

        source = call('POST', '/documents', data={'vendor_id': info['vendor_id']}, headers={'Idempotency-Key': uuid4().hex},
                      files={'file': (path.name, data, media)})
        assert source['sha256'] == digest
        runs = call('GET', f"/documents/{source['id']}/runs")['runs']
        earlier = [run for run in runs if run['state'] in ('completed', 'partial')]
        if earlier:
            run, sent = earlier[-1], False  # already read before: nothing is sent or charged again
        else:
            authorization = {'authorized': True, 'source_sha256': digest, 'authorized_by': 'POC owner (command line)',
                             'policy_reference': 'Owner confirmation with --confirm in the local live POC',
                             'reason': 'The owner confirmed sending this document to OpenAI'}
            run = call('POST', f"/documents/{source['id']}/runs", headers={'Idempotency-Key': uuid4().hex},
                       json={'provider': 'openai', 'external_authorization': authorization})
            run, sent = call('POST', f"/runs/{run['id']}/process"), True
        result = call('GET', f"/runs/{run['id']}/result")
        extraction = result.get('extraction') or {}
        rows = extraction.get('rows') or []
        attempt = (result.get('attempts') or [{}])[-1]
        suggestions = call('GET', f"/runs/{run['id']}/suggestions")['suggestions'] if extraction else []
        usage = {k: v for k, v in (attempt.get('usage') or {}).items() if isinstance(v, (int, dict))}
        cost = live.estimate_cost(usage, live.price_rates())
        tiers = {name: sum(item['tier'] == name for item in suggestions) for name in ('certain', 'probable', 'uncertain')}
        report = {'sent_to_openai_now': sent, 'run_state': run['state'], 'outcome_code': run.get('outcome_code'),
                  'review_state': run.get('review_state'), 'pages': len(extraction.get('pages') or []), 'rows': len(rows),
                  'product_rows': sum(row['row_kind'] == 'product' for row in rows),
                  'rows_with_catalog_candidates': sum(bool(item['candidates']) for item in suggestions), 'tiers': tiers,
                  'latency_ms': attempt.get('latency_ms'), 'tokens': usage,
                  'estimated_cost_usd': None if cost is None else round(cost, 4),
                  'open_in_browser': f"{args.base_url}/poc-demo (Recent orders)"}
        print(json.dumps(report, indent=2))
        return 0 if run['state'] in ('completed', 'partial') else 1
    finally:
        if own:
            client.close()


if __name__ == '__main__':
    sys.exit(main())
