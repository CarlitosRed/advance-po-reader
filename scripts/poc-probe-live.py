"""One paid request: does the configured OpenAI model accept this POC's input?

Sends a ONE-PAGE fictional PDF (never a real document) through the same adapter the
server uses, with the model from PO_BACKEND_EXTRACTION_MODEL (default gpt-6-luna).
Refuses to run without --confirm. Prints only sanitized facts; never the key.
Use --images to test a page image instead of a PDF file.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main(argv=None, transport=None, env_file='default'):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm', action='store_true', help='Required: confirms you want to send one small paid request')
    parser.add_argument('--images', action='store_true', help='Send the page as an image instead of a PDF file')
    args = parser.parse_args(argv)
    if not args.confirm:
        print('Refused: this sends one small fictional page to OpenAI and may cost a few cents. '
              'Run again with --confirm to proceed. Nothing was sent.')
        return 2
    import poc_live_support as live
    try:
        kwargs = {} if env_file == 'default' else {'env_file': env_file}
        settings = live.check_live_settings(require_token=False, **kwargs)
    except live.LiveRefusal as refusal:
        print(refusal)
        return 2
    report = live.run_probe(settings, transport=transport, images=args.images)
    usage = report['usage']
    print(json.dumps({
        'model': report['configured_model'], 'answered_by': report['answered_by'], 'input_sent': report['input'],
        'result': report['state'], 'failure': report['error'], 'latency_ms': report['latency_ms'],
        'tokens': {'input': usage.get('input_tokens'), 'output': usage.get('output_tokens'), 'total': usage.get('total_tokens')},
        'estimated_cost_usd': report['estimated_cost_usd'] if report['estimated_cost_usd'] is not None
        else 'not estimated (set PO_POC_INPUT_USD_PER_MTOK and PO_POC_OUTPUT_USD_PER_MTOK to your current price)',
        'model_accepted_this_input': report['input_accepted'],
    }, indent=2))
    return 0 if report['state'] == 'succeeded' else 1


if __name__ == '__main__':
    sys.exit(main())
