"""One paid request to find out WHY a live reading failed validation.

Sends ONE document (a --file OUTSIDE this repository) once through the same adapter and
model the server uses, keeps the raw model answer, re-runs the validation locally and
prints only rule names and field paths, counts, tokens, latency and estimated cost.
Never prints document text or values. The raw model JSON goes to the ignored folder
output/poc-demo/diagnostics/. Refuses to run without --confirm.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main(argv=None, transport=None, env_file='default', output_directory=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm', action='store_true', help='Required: confirms you authorize one paid request')
    parser.add_argument('--file', required=True, help='The document to send (must be outside the repository)')
    args = parser.parse_args(argv)
    if not args.confirm:
        print('Refused: this sends the document to OpenAI once and may cost real money. '
              'Run again with --confirm to proceed. Nothing was sent.')
        return 2
    import poc_live_support as live
    path = Path(args.file).expanduser().resolve()
    if ROOT.resolve() == path or ROOT.resolve() in path.parents or path.name.casefold().startswith('.env'):
        print('Refused: the file must be outside this repository. Nothing was sent.')
        return 2
    if not path.is_file():
        print('Refused: the file was not found. Nothing was sent.')
        return 2
    try:
        settings = live.check_live_settings(require_token=False, **({} if env_file == 'default' else {'env_file': env_file}))
        media = live.source_media(path)
        data = path.read_bytes()
        pages = live.source_page_count(data, media)
    except live.LiveRefusal as refusal:
        print(refusal)
        return 2
    report, body, raw_text = live.run_diagnosis(settings, data, media, pages, transport=transport)
    folder = Path(output_directory) if output_directory else ROOT / 'output' / 'poc-demo' / 'diagnostics'
    folder.mkdir(parents=True, exist_ok=True)
    saved = folder / (datetime.now().strftime('%Y%m%d-%H%M%S') + '-model-answer.json')
    if raw_text is not None:
        saved.write_text(raw_text, encoding='utf-8')
        report['raw_model_json_saved_to'] = str(saved)
    elif body is not None:
        saved.write_text(body, encoding='utf-8')
        report['raw_response_saved_to'] = str(saved)
    print(json.dumps(report, indent=2))
    return 0 if not report['validation_failures'] and report['adapter_state'] == 'succeeded' else 1


if __name__ == '__main__':
    sys.exit(main())
